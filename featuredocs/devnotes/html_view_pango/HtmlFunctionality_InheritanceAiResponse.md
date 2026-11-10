# Analysis of HTML View Branches and Inheritance Feasibility

## Background & Question

An analysis of the following Git branches:
- `remotes/origin/html_view_cffi`
- `remotes/origin/html_view_gtkwebkit2`
- `remotes/origin/html_view_pango`
- `remotes/origin/html_view_playwright`
- `remotes/origin/html_view_selenium`

Specifically regarding the premise:
> *"I suspect it makes sense to have everything inherit from html_view_pango, but is there anything I need to know before I go down that road?"*

---

## 1. Core Architectural Finding: Conflating "Viewing" with "Fetching"

At first glance, it appears that there are five distinct view implementations across these branches. However, examining the code reveals that **two completely separate responsibilities are being tangled together**:

1. **Presentation / Display Widget (UI)**: How HTML is shown in the GTK interface.
2. **Content Acquisition / Fetching / Scraping (Data retrieval)**: How remote HTML / DOM content is acquired from a URL.

### Branch Breakdown

| Branch | Display / UI Widget | Fetching / Scraping Engine | Dependencies |
| :--- | :--- | :--- | :--- |
| **`html_view_pango`** | Pango markup in `Gtk.Label` + `Gtk.TextView` | Standard library `urllib.request` | **Zero** (Stdlib + GTK3) |
| **`html_view_gtkwebkit2`** | Native `WebKit2.WebView` tab + Pango fallback | Browser internal (`WebKit2`) + `urllib` fallback | `WebKit2GTK` (GObject) |
| **`html_view_playwright`** | Pango markup in `Gtk.Label` *(Same as pango)* | Headless Chromium via `playwright.sync_api` | `playwright`, Node/browser binaries, `playwright-stealth` |
| **`html_view_selenium`** | Pango markup in `Gtk.Label` *(Same as pango)* | Headless Chrome via `selenium` + `chromedriver` | `selenium`, `webdriver_manager`, `selenium-stealth`, Google Chrome |
| **`html_view_cffi`** | Pango markup in `Gtk.Label` *(Same as pango)* | `curl_cffi` (TLS evasion) + Playwright JS fallback | `curl_cffi`, native BoringSSL, `playwright` |

### Key Takeaway
`playwright`, `selenium`, and `cffi` are **not different HTML views**; they are **different HTTP/DOM fetchers and scrapers**.
In all three branches, once the HTML is acquired, it is fed straight into `HTMLToPangoParser` and displayed using the exact same Pango label and GTK text buffer as `html_view_pango`.

---

## 2. Why Class Inheritance from `HTMLViewPango` is Problematic

Attempting to structure this via subclassing (e.g. `HTMLViewPlaywright(HTMLViewPango)` or `HTMLViewSelenium(HTMLViewPango)`) introduces several architectural issues:

1. **Violates the Single Responsibility Principle**:
   The view class would become responsible for launching headless browser processes, managing Chrome/Chromium drivers, handling anti-bot evasion, *and* managing GTK UI components (tabs, text buffers, clipboard, scroll windows).
2. **Couples the Pipeline to the View**:
   Other components in Gramps (such as `HtmlBridge`, `WebSearch`, or `GrizardAssistant`) also route or consume fetched HTML. If URL fetching/scraping is implemented inside a subclass of `PageView`, non-GUI flows and background services cannot reuse the scraper without instantiating a GTK PageView.
3. **`WebKit2` is fundamentally different from Pango**:
   `WebKit2` is an embedded browser widget (`WebKit2.WebView`), not a markup parser. It handles its own layout, CSS, DOM, and JavaScript execution. Inheriting from a class designed around `HTMLToPangoParser` and `Gtk.Label` results in awkward overrides where parent widgets and rendering pathways are bypassed or unused.

---

## 3. Threading and GTK Main Loop Freezes

A critical problem in the branches is how fetching interacts with the GTK event loop:

* **In `html_view_playwright`**:
  `_render_with_playwright()` calls `sync_playwright()` directly inside the rendering path on the **GTK main thread**:
  ```python
  with sync_playwright() as pw:
      browser = pw.chromium.launch(headless=headless)
      ...
      page.goto(url, wait_until="networkidle")
  ```
  `sync_playwright` blocks the main loop, causing the entire Gramps GUI to freeze for 3–15+ seconds (or up to 30s on timeout) while Chromium boots and waits for network idle.
* **In `html_view_selenium`**:
  It used a background thread (`_ScrapeThread`) and scheduled updates back to the UI with `GLib.idle_add(callback, html)`, avoiding UI lockup.
* **In an inherited view architecture**:
  The base `HTMLViewPango` expects synchronous HTML text passed to `set_text()`. Subclasses introducing asynchronous fetching must manage complex state (loading spinners, cancelling obsolete requests if the user navigates elsewhere, error propagation) which does not fit standard view inheritance.

---

## 4. Cross-Platform & Packaging Constraints

Gramps targets three primary distribution channels: Linux distribution packages (`.deb`, `.rpm`), macOS `.app` bundles, and the Windows All-In-One (AIO) installer (MSYS2/MinGW).

* **WebKit2GTK (`html_view_gtkwebkit2`)**:
  Gramps explicitly disables WebKit2 on Windows (see `gramps/gen/fs/session.py` and `gramps/gui/fs/fs_source_image.py`: `(not win()) and has_webkit`). WebKit2GTK is not available or maintained for Windows MSYS2 builds, and GTK3 WebKit is being phased out in several Linux distros.
* **Playwright (`html_view_playwright`)**:
  Requires external browser binaries (~200MB download via `playwright install chromium`) stored outside standard system paths. Cannot be cleanly bundled in standard Linux repos (`.deb`, `.rpm`) or Gramps Windows AIO.
* **Selenium (`html_view_selenium`)**:
  `scraper.py` hardcodes `CHROME_BINARY = "C:/Program Files/Google/Chrome/Application/chrome.exe"`, breaking Linux/macOS. Furthermore, `webdriver_manager` downloads drivers from Google at runtime, which fails in offline or firewalled environments.
* **curl_cffi (`html_view_cffi`)**:
  Relies on precompiled native libraries (BoringSSL). Difficult to support across all platforms supported by Gramps.
* **Pango (`html_view_pango`)**:
  Has **zero third-party dependencies**. It works out of the box on Windows, Linux, and macOS without extra packages or configuration.

---

## 5. Recommended Architecture: Separate Strategy Pattern

Instead of having view subclasses inherit from `html_view_pango`, decouple the system into two independent layers using the Strategy pattern:

```
┌────────────────────────────────────────────────────────┐
│                   Fetching Strategy                    │
│  BaseFetcher (Protocol / ABC)                          │
│    ├── UrllibFetcher       (Default, zero-deps, stdlib)│
│    ├── SeleniumFetcher     (Optional / background)     │
│    └── PlaywrightFetcher   (Optional / background)     │
└───────────────────────────┬────────────────────────────┘
                            │ delivers HTML asynchronously
                            ▼
┌────────────────────────────────────────────────────────┐
│                      HtmlBridge                        │
└───────────────────────────┬────────────────────────────┘
                            │ delivers to active view
                            ▼
┌────────────────────────────────────────────────────────┐
│                   HTMLView (PageView)                  │
│  - Tab 1: Rendered (HTMLToPangoParser -> Gtk.Label)    │
│  - Tab 2: Source   (Gtk.TextView)                      │
│  - Tab 3: Browser  (Optional WebKit2 tab if available) │
└────────────────────────────────────────────────────────┘
```

1. **Keep `HTMLView` focused purely on rendering**:
   Use `HTMLToPangoParser` as the universal baseline display. If `WebKit2` is available (e.g., Linux), it can optionally provide an embedded browser tab.
2. **Move fetching logic out of the view**:
   Let `HtmlBridge` (or a dedicated `fetcher` module) handle URLs using a pluggable fetcher strategy. If the user has Selenium or Playwright installed, they can enable dynamic JS scraping; otherwise, it falls back gracefully to `urllib`.
3. **Clean up lingering artifacts in `html_view_pango`**:
   In `html_view_pango` (`gramps/plugins/view/htmlview.py`), there is currently an orphan try/except block importing `scrape_page_async` from `gramps.plugins.gramplet.scraper` and setting `_USE_SELENIUM`. Because `scraper.py` was never committed to `html_view_pango`, this import always fails silently. If `pango` is made the foundation, remove these hardcoded Selenium checks and replace them with a proper backend-agnostic configuration or hook.
