# GWizard Media Fix — Opportunities for Improvement

These opportunities come from comparing GWizard Media Fix (`addons-source/MediaFix`, v0.0.1) with the built-in Media Manager and the Media Browser, Merge Media, Media Report and Media Verify addons. See `MediaAddons_ToolComparison.md` for that comparison.

Each item lists the gap, where the idea comes from, and a suggested approach. Priority: **H** = fills a real functional gap or fixes a defect · **M** = noticeable usability or robustness gain · **L** = polish.

## Status (updated 2026-11-17)

| Item | Status |
| :--- | :--- |
| 1.1 Content-hash matching | ✅ Done |
| 1.2 Maintain the checksum field | ✅ Done |
| 1.5 Verified folder remap | ✅ Done, as *Look in folder...* (also replaced *Copy from folder...*) |
| 1.6 Image preview | ✅ Done |
| 2.5 Check and Repair clears checksums (new) | ✅ Fixed in the separate `checkandrepair_checksumfix` branch |
| 2.6 Accept all hints closed the main window (new) | ✅ Done |
| 2.3 Search roots | ◐ Partly covered by *Look in folder...* |
| 4.1 Correct the comparison doc | Open: still says "similarity scoring", and now also describes the removed copy-from-folder action |
| All other items | Open |

"Done" items keep their original gap and approach text, followed by what was built.

---

## 1. Functional Gaps (features other tools have)

### 1.1 Content-hash matching for renamed or moved files — **H** ✅ Done
* **Gap:**
  * *Find missing media* only suggests a file with the **same basename**, and only when it is unique.
  * Files renamed on disk (`IMG_0492.JPG` → `Smith_John_1910.jpg`) are never found.
  * Media Verify finds them by comparing MD5 hashes.
* **Approach:**
  * When a record has a stored checksum (`media.get_checksum()`), build a `{md5: [paths]}` index of the base dir (and of any other folder searched) and offer content matches as hints, ranked above name matches.
  * Before hashing, filter candidates by file size and extension so large libraries stay fast.
  * Keep the `ambiguous_matches()` safety rule: if a checksum matches several files, offer no automatic hint.
* **Done:**
  * *Find missing media*, *Look in folder...* and Accept all hints match by stored checksum first, then by unique file name.
  * Several identical copies are resolved only when exactly one still has the record's file name, as Media Verify does.
  * A same-name file whose content differs from the stored checksum is no longer suggested, and picking a file only fills other same-name rows whose checksum agrees.
  * Size filtering was not possible: Gramps stores no size for a missing file. Hashing is limited by extension family (`.jpg` and `.jpeg` together), and hashes are cached by path, size and modification time.
  * Records imported from GEDCOM have no checksum, so they gain from this only after *Store checksums* (or Accept all hints) has run while their files were present.

### 1.2 Maintain the media checksum field — **H** ✅ Done
* **Gap:**
  * GWizard moves, copies and relinks files but never writes `media.set_checksum()`.
  * Records relinked to a different file (*Find missing*, files copied in from another folder, *Split* copies) keep a stale checksum or none at all, which breaks Media Verify and Gramps' own checksum use.
* **Approach:**
  * After any relink or copy, recompute the MD5 with `gramps.gen.utils.file.create_checksum` and store it in the same transaction.
  * Optionally add a "Generate missing checksums" step to Accept all hints.
  * This also enables 1.1.
* **Done:**
  * A relink recalculates the checksum from the new file; a move, copy, split or merge fills in a missing one; undoing file moves recalculates it.
  * New **Store checksums** button on the main window (adds missing checksums, updates changed ones) and a **Store checksums** step at the end of Accept all hints.
  * A checksum is never cleared when a file cannot be read.
  * The report shows "Records with checksum" and "Missing with checksum" counts.

### 1.3 Duplicate *content* at different paths — **M**
* **Gap:**
  * *Fix media references* groups records by resolved **path** only.
  * Two records pointing at byte-identical files in different folders (common after repeated imports or copy-pasted folders) are not detected.
  * Media Verify lists these files but cannot merge them.
* **Approach:**
  * Add a second group type, `"same_content"`, built from checksums, with *Merge records (keep one file)* / *Keep both* actions.
  * After merging, list the redundant file for the user to delete; never delete it automatically.

### 1.4 Import unreferenced files on disk — **M**
* **Gap:**
  * The report lists *Unreferenced path files* but offers no action.
  * Media Manager's *Add images not included in database* imports them, but only images, with no naming and no preview.
* **Approach:** add an *Add unreferenced files* dialog:
  * Checkbox per file.
  * MIME type from `gramps.gen.mime.get_type`.
  * Checksum set on import.
  * Optional template rename on import.
  * `GWizard: MediaFixed` tag.
  * Log the run so it can be undone.

### 1.5 Verified folder-prefix remap for missing files — **M** ✅ Done
* **Gap:**
  * When many missing records share an old folder (`D:/OldPC/Pictures/...`), today the user picks files one by one or relies on unique basenames.
  * Media Manager's *Replace substrings* does this in bulk but blindly.
* **Approach:**
  * In *Find missing media*, group missing rows by parent folder and offer "Map `D:/OldPC/Pictures` → *chosen folder*".
  * Preview how many records would resolve to an **existing** file, and apply only those.
* **Done**, as **Look in folder...** in *Find missing media*:
  * The user picks a folder; for each row without a new path, the old folder layout is mapped onto it (case-insensitive, verified on disk), then content, then unique name are tried.
  * The old folder that explains the most records wins; a tie is not used.
  * A preview groups the results by old folder (`D:/OldPC/Pictures -> <folder>: 37 records`) and lists what was not found or not used; only found files are filled in, used where they are, and saved on *Apply*.
  * It replaced *Copy from folder...*. To copy files into the base path instead, use *Look in folder...* and then *Consolidate media location* with *Make a copy*.

### 1.6 Image preview when choosing a match — **M** ✅ Done
* **Gap:**
  * Users confirm a suggested file by its path only.
  * Media Browser and the Gramps `Photo` widget show the image (with region cropping).
* **Approach:**
  * Add a small `gramps.gui.widgets.Photo` preview pane to *Find missing media* and *Fix media references* that updates on row focus.
  * For duplicate groups, show the region rectangle of each media reference so the user can see what a merge would combine.
* **Done** (new module `gw_mediapreview.py`):
  * A pane under the table in *Find missing media* and *Fix media references* shows the focused row's file, with each reference's region outlined, numbered and listed.
  * In *Fix media references*, outlines are coloured per media record, and the caption says how many references a merge would keep on the keeper.
  * Built from the same parts as Gramps' `Photo` widget (Gramps thumbnails; a double-click opens the file) rather than `Photo` itself, because `gramps.gui.widgets` cannot be imported under the test fakes.

### 1.7 Open the media editor from any row — **L**
* **Gap:** Media Verify opens `EditMedia` when a record row is double-clicked and opens the file when a disk-file row is double-clicked. GWizard tables and the report viewer can't do either.
* **Approach:**
  * Add the same double-click handlers in GWizard's tables.
  * In the report viewer, make the Gramps IDs (`O0123`) clickable.

---

## 2. Robustness and Correctness

### 2.1 Addon translations are not loaded — **H**
* **Defect:**
  * `gwizardmediafix.py` uses `glocale.translation.sgettext`, and the `.gpr.py` uses `glocale.translation.gettext`.
  * Addons are expected to use `glocale.get_addon_translator(__file__)`, as every other media addon does.
  * As written, translations shipped in `MediaFix/po/` are never used.
* **Fix:** use the standard addon pattern in every module (keep `sgettext`):
  ```python
  try:
      _trans = glocale.get_addon_translator(__file__)
  except ValueError:
      _trans = glocale.translation
  _ = _trans.sgettext
  ngettext = _trans.ngettext
  ```
  Also apply it in `gw_fixmediareferencesdialog.py`, `gwizard_common.py` and the new `gw_mediapreview.py`.

### 2.2 Disk-scan limits are hard-coded and only partly visible — **M**
* **Gap:**
  * `find_unreferenced_default_path_files()` uses a fixed extension list, a fixed skip-folder list and a 5,000-file cap.
  * The cap sets `stats["truncated"]`, but the user can't raise it.
  * Unusual media types are skipped (`.heic`, `.jfif`, `.jp2`, `.djvu`, `.3gp`, `.m4v`, `.ogv`).
* **Approach:**
  * Use the MIME type for the media check (`gramps.gen.mime.get_type` / `is_valid_type`) instead of the extension set.
  * Make the cap a preference.
  * Always print "scan stopped at N files" in the report when the cap is hit.

### 2.3 Search roots — **L** ◐ Partly done
* **Gap:** the recursive basename index runs only when a base media path is configured. That is a sensible guard, but it leaves users with no base path set without hints.
* **Approach:** let the user add extra search folders in *Find missing media* (remembered in config).
* **Partly done:** *Look in folder...* searches any folder the user picks, with or without a base path. Folders are not remembered between sessions.

### 2.4 Changed-content awareness — **L**
* **Gap:** when a file exists but its stored checksum no longer matches, the file was edited or replaced. Media Verify reports this (as "Missing"); GWizard does not.
* **Approach:** now that 1.2 is in place, add a "Content changed since checksum" section to the report (informational). Reading every file makes the report slower, so it could be an option.

### 2.5 Gramps' Check and Repair clears checksums — **H** ✅ Fixed (separate branch)
* **Defect:** Check and Repair recalculated every checksum and stored an empty one when the file was missing, erasing exactly what content matching needs.
* **Fixed** in the `checkandrepair_checksumfix` branch (`gramps/plugins/tool/check.py`, with `gramps/plugins/test/check_checksum_test.py`): a stored checksum is kept when the file cannot be read. A candidate for an upstream Gramps pull request.

### 2.6 Accept all hints closed the main window — **H** ✅ Done
* **Defect:** the *Accept all hints* button sits in the main window's action area, so GTK also sends the window a response when it is used; the window closed on any response.
* **Fixed:** the main window now closes only on *Close*, its X or Escape. The preview also names its steps instead of numbering them, and explains a skipped consolidation (no base media path) and how to fix it.

---

## 3. Usability and Workflow

### 3.1 Machine-readable report export — **M**
* The `.txt` report is good for reading but hard to filter.
* Add an option to also write CSV (one row per finding: category, Gramps ID, description, path, hint), so findings can be sorted in a spreadsheet or compared between runs.
* Media Verify exports text only, so this would go beyond it.

### 3.2 Run the report from the command line — **L**
* `generate_media_fix_report()` does no GUI work.
* Registering `TOOL_MODE_CLI` with a thin CLI entry point would allow `gramps -O "Tree" -a tool -p name=gwizardmediafix,...` for scheduled health checks.
* Avoid Media Verify's mistake: it registers CLI mode but builds a GTK window in `__init__`.

### 3.3 Per-person media health view — **L** (idea)
* A small Gramplet in the style of Media Browser could show, for the active person, each media item's status: missing, non-standard name, shared, or unreferenced region.
* Each line would link to the matching GWizard dialog.

### 3.4 Accept-all plan readability — **L**
* `format_plan()` truncates each section to 6 rows.
* Add a "Show full plan…" button that opens the whole plan in the report viewer, so large trees can be reviewed before committing.

---

## 4. Documentation and Ecosystem

### 4.1 Correct the comparison doc — **H** (quick)
* `MediaManager_ToolComparison.md` (Detailed Functional Differences §2) says missing-file candidates use "basename matching and similarity scoring".
* The code uses exact, unique basename matching only.
* Either fix the wording (and the wiki prompt in `featuredocs/create_gwizard_mediafix_wiki.bash` if it carries the same claim) or implement 1.1 and describe that.

### 4.2 Name consistency — **M**
* The addon directory is `MediaFix`, the registered name is "Media Fix", the id is `gwizardmediafix`, and the wiki page is `Addon:GWizardMediaFix_Tool`.
* "Media Fix" sits next to "Media Verify" / "Merge Media" in the Tools menu, so users may not recognise it as GWizard.
* Align on **"GWizard Media Fix"** for the menu name, and consider naming the addon directory `GWizardMediaFix`.

### 4.3 Position against existing addons on the wiki — **M**
State plainly on the wiki page that:
* GWizard Media Fix covers Merge Media's function, adding preview, undo and keeper selection.
* It now matches renamed files by content and maintains checksums, as Media Verify does; Media Verify still lists content-identical files at different paths (1.3).
* It is unrelated to Media Report and Media Browser.

### 4.4 Upstream fixes noticed in the other addons — **L** (optional contributions)
While reading the other addons, these issues turned up. They could be offered upstream as small pull requests from the `ghcaveman/addons-source` fork:
* **MediaMerge:**
  * The `else:  # not (match and match1)` branch is attached to the inner ID comparison, not to `if match and match1`. Records whose IDs don't fit the pattern never reach the handle tie-break.
  * IDs are compared as digit strings, not integers.
* **MediaVerify:**
  * Registers `TOOL_MODE_CLI`, but its constructor builds a GTK window.
  * Records with correct absolute paths are listed as "Moved/Renamed".
* **MediaBrowser:**
  * The registered description is a generic placeholder.
  * Family media and media attached to citations are not shown.
  * `add_media()` computes `full_path`/`rect` but never uses them.

---

## Suggested Order

Done so far: 1.1, 1.2, 1.5, 1.6, 2.5, 2.6. Remaining, in suggested order:

1. **2.1** translations and **4.1** doc correction: small and defect-level.
2. **1.3** duplicate content at different paths, now possible because checksums are maintained.
3. **1.4** import unreferenced files, and **2.4** changed-content awareness.
4. The remaining M/L items.
