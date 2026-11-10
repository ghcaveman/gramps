# WebSearch & Gramps Core Interaction: HTML View & HtmlBridge Analysis

## Executive Summary

This document captures the analysis of diverting HTML content from the **WebSearch plugin** to an internal **HTMLView** in **Gramps Core** via **`HtmlBridge`**, and how this integrates with the standard `display_url` utility.

---

## 1. Context & Objectives

* **Goal**: Allow web links (from WebSearch results, badges, notes, and Gramps core) to be displayed in an internal `HTMLView` within Gramps when enabled, while falling back to the system's default external web browser when disabled or on network failure.
* **Key Mechanism**: Gramps core's `HtmlBridge` (`gramps.gui.htmlbridge.HtmlBridge`), which manages the queueing, fetching, and routing of HTML content to `HTMLView` and registered external callbacks.
* **Key Question**: Does the WebSearch plugin need extensive changes, or can the functionality be handled predominantly or entirely on the Gramps core side via `display_url`?

---

## 2. Analysis of the `html_view` Branch in `gramps_WebSearch`

In commit `bb017e4` on the `html_view` branch of `gramps_WebSearch`:

1. **Ad-hoc URL Fetching Added to `open_url`**:
   Inside `WebSearch.open_url(self, url)`:
   - Checked `if os.environ.get("GRAMPS_HTML"):`.
   - Used `urllib.request.urlopen` with custom browser headers to synchronously download HTML.
   - Called `HTMLView.set_html_text(html_content)` directly.
   - Fell back to `webbrowser.open(...)` if `GRAMPS_HTML` was unset or if an exception occurred.
2. **Inline Link Clicks**:
   - In line 499 (handling clicks on links inside note/preview text tags), `webbrowser.open(url)` was changed to `self.open_url(url)`.
3. **Primary Search Results Ignored the New Logic**:
   - In `on_link_clicked` (line 1067, executed when clicking a search result row in the main treeview table), the code was:
     ```python
     encoded_url = urllib.parse.quote(url, safe=URL_SAFE_CHARS)
     display_url(encoded_url)
     ```
   - It **already called `display_url`** from `gramps.gui.display` and bypassed `self.open_url` entirely.

---

## 3. Analysis of the `html_view_pango` Branch in `gramps` (Core)

In the `html_view_pango` branch of Gramps core:

### A. The `GRAMPS_HTML` Flag
- The environment variable `GRAMPS_HTML` acts as the feature gate:
  - In `gramps/plugins/view/view.gpr.py`, `HTMLView` is only registered when `os.environ.get("GRAMPS_HTML")` is set.
  - In `grizardresultsgramplet.py`, link activation is hooked to `HtmlBridge` only when `os.environ.get("GRAMPS_HTML")` is set.

### B. `HtmlBridge` (`gramps/gui/htmlbridge.py`)
- Maintains the active `HTMLView` reference (`active_view: HTMLViewProtocol | None`).
- Supports an optional consumer callback (`html_callback: Callable[[str, str], None] | None`).
- Provides two key entry points:
  - `HtmlBridge.route_html(url, html_content)`: Delivers HTML to `active_view` (or queues it in `pending_html` if the view is not yet open) and triggers any registered `html_callback`.
  - `HtmlBridge.route_url(url) -> bool`:
    - If `active_view` is loaded: fetches the HTML via `_fetch_url(url)` using standard browser headers, routes it to `route_html`, and returns `True`. Returns `False` on fetch failure.
    - If `active_view` is not yet loaded: queues `(url, None)` in `pending_html` and returns `True`. When `HTMLView` opens, `flush_pending(view)` triggers the fetch and renders the page.

### C. Existing `display_url` (`gramps/gui/display.py`)
```python
def display_url(link, uistate=None):
    """
    Open the specified URL in a browser.
    """
    webbrowser.open_new_tab(link)
```
Every component across Gramps core (citations, notes, web address editor, repositories) uses `display_url` to open links.

---

## 4. Can It All Be Changed on the Gramps Core Side?

### Primary Search Results
**Yes, 100% on the core side.** Because `on_link_clicked` in WebSearch already delegates to `display_url(encoded_url)`, modifying `display_url` in Gramps core immediately diverts all search result clicks to `HtmlBridge` without requiring any changes to WebSearch.

### Badges and Inline Note Links
In upstream WebSearch (prior to commit `bb017e4`):
- Line 499 (note/text tag clicks) called `webbrowser.open(url)` directly.
- Line 1734 (badge clicks) called `webbrowser.open(...)` directly inside `open_url()`.

Because Python's standard `webbrowser.open` cannot be cleanly intercepted by Gramps core, a small 3-line change in WebSearch is recommended to forward `open_url` to `display_url`.

---

## 5. Recommended Implementation

### 1. Gramps Core: `gramps/gui/display.py`
Update `display_url` to check for `GRAMPS_HTML` and divert HTTP/HTTPS links to `HtmlBridge`:

```python
def display_url(link, uistate=None):
    """
    Open the specified URL in an internal HTML view if enabled,
    or fall back to the default external browser.
    """
    if os.environ.get("GRAMPS_HTML") and link.lower().startswith(("http://", "https://")):
        try:
            from gramps.gui.htmlbridge import HtmlBridge

            if HtmlBridge.route_url(link):
                return
        except Exception:
            pass

    webbrowser.open_new_tab(link)
```

**Behavior**:
- `GRAMPS_HTML` unset: immediately launches external browser via `webbrowser.open_new_tab`.
- `GRAMPS_HTML` set: tries `HtmlBridge.route_url(link)`. If successful (or queued), returns.
- Fetch failure (network error, timeout, server failure): `route_url` returns `False`, smoothly falling back to `webbrowser.open_new_tab`.

### 2. WebSearch Plugin: `WebSearch.py`
Remove all ad-hoc `urllib` fetching, `HTMLView` imports, and `GRAMPS_HTML` checks. Unify link opening to use `display_url`:

1. **Keep line 499** routing through `self.open_url(url)`:
   ```python
   self.open_url(url)
   ```
2. **Simplify `open_url`** to delegate directly to `display_url`:
   ```python
   def open_url(self, url):
       """Opens the given URL using the standard Gramps URL handler."""
       encoded_url = urllib.parse.quote(url, safe=URL_SAFE_CHARS)
       display_url(encoded_url)
   ```

---

## 6. Benefits of this Architecture

1. **Zero Plugin Coupling**: The WebSearch plugin remains completely agnostic of how HTML is viewed. It does not need to know whether `HTMLView`, `WebKit2`, `Pango`, or an external browser is used.
2. **Unified URL Routing**: Every URL activated anywhere in Gramps (WebSearch, notes, sources, repositories, citations) follows the exact same path through `display_url`.
3. **Resilient Fallback**: If network fetching inside Gramps fails or the feature flag is disabled, URLs reliably open in the user's external browser.
4. **Clean Codebase**: Deletes duplicate network fetching routines and replaces them with a single centralized routing point in `gramps.gui.display`.
