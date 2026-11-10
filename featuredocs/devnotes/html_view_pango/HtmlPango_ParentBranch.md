# Git Branch Analysis: Basing HTML View Branches off `html_view_pango`

## Overview

Analysis of the following Git branches:
- `remotes/origin/html_view_cffi`
- `remotes/origin/html_view_gtkwebkit2`
- `remotes/origin/html_view_pango`
- `remotes/origin/html_view_playwright`
- `remotes/origin/html_view_selenium`

Specifically evaluating the premise:
> *"I suspect it makes sense to have everything inherit from html_view_pango, but is there anything I need to know before I go down that road?"* (from a Git branching perspective, to avoid duplicating code).

---

## 1. Git History & The Fork Point

All four other branches diverged from the **exact same commit**:
* **Common ancestor of `cffi`, `gtkwebkit2`, `playwright`, and `selenium`**: `b905354659` (*"Added WebSearch filters (not yet functional)"*).
* **Where `html_view_pango` stands**:
  `html_view_pango` contains the exact same feature commits, but it was **rebased onto a newer baseline** (which brought in 6.1.0-beta2 and DNA updates; its equivalent commit is `3ae075bd79`), followed by 7 newer commits up to `8dbd7c5d94` (*"Update htmlbridge to have no dependencies"*).

---

## 2. What Files Are Shared vs. What Diverged

Outside of **two core files**, the entire HTML view feature is already identical across all branches.

### A. Shared Files (Identical / Common Baseline across all 5 branches)
These ~28 files form the shared feature foundation:
* **WebSearch Filter Rules**:
  * `gramps/gen/filters/rules/websearch/__init__.py`
  * `gramps/gen/filters/rules/websearch/_ancestry.py`
  * `gramps/gen/filters/rules/websearch/_billiongraves.py`
  * `gramps/gen/filters/rules/websearch/_familyservice.py`
  * `gramps/gen/filters/rules/websearch/_findagrave.py`
  * `gramps/gen/filters/rules/websearch/_websearchfilter.py`
  * `gramps/gen/filters/rules/websearch/test/websearch_filter_test.py`
* **Gramplet & View Registrations**:
  * `gramps/plugins/gramplet/grizardresultsgramplet.py`
  * `gramps/plugins/gramplet/test/grizard_results_gramplet_test.py`
  * `gramps/plugins/gramplet/gramplet.gpr.py`
  * `gramps/plugins/view/view.gpr.py`
* **Core GUI Hooks**:
  * `gramps/gui/views/pageview.py`
  * `gramps/gui/widgets/grampletbar.py`
  * `gramps/gui/viewmanager.py`
  * `gramps/gui/navigator.py`
* **Test Fixtures & Canned HTML**:
  * `gramps/gui/test/html_to_pango_test.py`
  * `gramps/gui/test/htmlview_order_test.py`
  * `gramps/plugins/view/test/htmlview_pango_raw_test.py`
  * `gramps/plugins/view/test/canned/*` (6 canned HTML fixtures)
* **Translation Lists**:
  * `po/POTFILES.in` & `po/POTFILES.skip`

### B. The Only Divergent Files Across the Branches

Since diverging from commit `b905354659`, here is **everything** each branch touched:

| Branch | Files Modified / Added |
| :--- | :--- |
| **`html_view_playwright`** | `M gramps/plugins/view/htmlview.py` *(1 file)* |
| **`html_view_cffi`** | `M gramps/gui/htmlbridge.py`<br>`M gramps/plugins/view/htmlview.py` *(2 files)* |
| **`html_view_gtkwebkit2`** | `M gramps/gui/htmlbridge.py`<br>`M gramps/plugins/view/htmlview.py` *(2 files)* |
| **`html_view_selenium`** | `M gramps/gui/htmlbridge.py`<br>`M gramps/plugins/view/htmlview.py`<br>`A gramps/plugins/gramplet/scraper.py`<br>`A debug_selenium.py`, `selenium_check.py`, `test_js_render.py` *(6 files)* |
| **`html_view_pango`** *(Tip)* | `M gramps/gui/htmlbridge.py` *(clean protocol/callback refactor)*<br>`M gramps/plugins/view/htmlview.py`<br>`M gramps/plugins/gramplet/grizardresultsgramplet.py`<br>`A gramps/gui/test/htmlbridge_test.py` |

---

## 3. What You Need to Know Before Rebasing onto `html_view_pango`

1. **Use `git rebase --onto` to avoid duplicate commit replays**:
   Because `html_view_pango` rebased earlier commits, the initial feature commits (`Have a working pango implementation`, `Fixed parsing for FindAGrave`, etc.) exist under different commit hashes in `html_view_pango`.
   To rebase cleanly without replaying those commits, use:
   ```bash
   git rebase --onto origin/html_view_pango b905354659 <branch-name>
   ```
2. **Expect merge conflicts in `htmlview.py` and `htmlbridge.py`**:
   Conflicts will occur in these two files:
   * In `htmlbridge.py`: `html_view_pango` introduced `HTMLViewProtocol` and `register_html_callback` (commit `8dbd7c5d94`), whereas `cffi`, `gtkwebkit2`, and `selenium` modified `_fetch_url()` directly on the older `HtmlBridge`.
   * In `htmlview.py`: `html_view_pango` had UI changes (adding `engine_label` toolbar placement in commits `6879222002` and `fb0240a1f8`), which will collide with how the other branches added engine labels or rendering hooks.
3. **Dead import in `html_view_pango`**:
   In `html_view_pango`'s `htmlview.py` (lines 76–81), there is an uncommitted/dangling try-import:
   ```python
   try:
       from gramps.plugins.gramplet.scraper import scrape_page_async
       _USE_SELENIUM = True
   except Exception:
       _USE_SELENIUM = False
   ```
   Because `scraper.py` was only ever committed to `html_view_selenium`, this import always fails silently in `html_view_pango`. If you rebase `selenium`, `scraper.py` will fulfill this import; for the other branches, that block should be cleaned up.
