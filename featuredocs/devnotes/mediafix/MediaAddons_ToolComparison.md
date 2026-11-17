# Comparison: GWizard Media Fix vs. Gramps Media Tools and Addons

## Overview

This document compares **GWizard Media Fix** with the built-in **Media Manager** and the four media addons in `addons-source` whose functionality overlaps with it. It was written from the source code in `C:\gramps_dev\gramps_gwizard_mediafix_plugin\addons-source` (fork: `https://github.com/ghcaveman/addons-source.git`) and `gramps/plugins/tool/mediamanager.py`.

> Note: the `addons-source/MediaFix` directory **is** GWizard Media Fix packaged as an addon (`gwizardmediafix.py`, `gw_fixmediareferencesdialog.py`, `gwizard_common.py`). It is listed below as "GWizard Media Fix".
>
> **Updated 2026-11-17** for the GWizard Media Fix changes made since: checksum storing and content matching, the image preview pane, *Look in folder...* (which replaced *Copy from folder...*), and the new `gw_mediapreview.py` module. Until the `addons-source/MediaFix` copy is rebuilt from the branch with `package_addon.py`, it still has the older behaviour.

| Tool | Type / menu | Author | Version | Status | Size (code) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Media Manager** (built-in) | Tool, `Gtk.Assistant` wizard | Gramps project | core | Stable | ~750 lines |
| **Media Browser** | Gramplet (Person views) | Nick Hall | 1.0.39 | Stable | ~150 lines |
| **Merge Media** (`MediaMerge`) | Tool → Family Tree Processing (BatchTool) | Paul Culley | 1.0.14 | Stable | ~130 lines |
| **Media Report** (`MediaReport`) | Text report (PDF only) | Matthias Kemmer | 1.1.15 | Stable | ~400 lines |
| **Media Verify** (`MediaVerify`) | Tool → Utilities | Nick Hall | 1.0.32 | Stable | ~330 lines |
| **GWizard Media Fix** (`MediaFix`) | Tool → Family Tree Processing | Kevin White | 0.0.1 | Experimental / Expert, Gramps 5.2–6.2 | ~7,600 lines + 8 test modules (182 tests) |

### One-line summary of each

* **Media Manager**: Rewrites path *strings* in bulk (substring replace, relative ↔ absolute) and imports unindexed *images* from folders that existing media already use. It never touches files on disk.
* **Media Browser**: A read-only viewer. For the active person it shows a tree of media attached to the person, the person's events, and the sources cited, with an image preview that honors region rectangles.
* **Merge Media**: A one-shot batch job that merges every media record whose normalized full path matches another, with no preview or per-item choice.
* **Media Report**: A *presentation* report. For one selected image it produces a PDF page with the image, an optional note, the media data (description, MIME, attributes, tags, notes, citations), and cropped thumbnails of each person tagged in a region.
* **Media Verify**: An MD5-based integrity checker. It stores checksums in media records, then scans the base media directory to find moved or renamed files, missing files, identical-content duplicates, and extra files. It can repoint moved files.
* **GWizard Media Fix**: A maintenance workbench for both database records and disk files. It reports media health; finds and relinks missing files by content (MD5), folder layout or name; previews each file with its people's regions outlined; merges, splits or removes duplicate and unreferenced records; moves or copies files into the base path under template-based names; stores checksums; removes stale GEDCOM import notes; and can undo file moves. "Accept all hints" runs the full pipeline after a preview.

---

## Feature Comparison Matrix

Legend: ✅ full support · ◐ partial / limited · — none

| Capability | Media Manager | Media Browser | Merge Media | Media Report | Media Verify | GWizard Media Fix |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Changes database records** | ✅ paths, new records | — | ✅ merges | — | ✅ checksums, paths | ✅ paths, merges, removals, notes, tag |
| **Moves / copies / renames disk files** | — | — | — | — | — | ✅ (collision-safe, logged) |
| **Missing-file detection** | — | — (blank preview) | — | ◐ warns for the one file reported | ✅ via checksum | ✅ via existence + permission check |
| **Relink missing file: same name elsewhere** | — | — | — | — | — | ✅ unique basename in base dir (recursive) or in a chosen folder |
| **Relink missing file: renamed file** | — | — | — | — | ✅ MD5 match | ✅ MD5 match (base dir or a chosen folder), when the record has a checksum |
| **Permission / unreadable-folder diagnosis** | — | — | — | — | ◐ lists IOErrors | ✅ names the blocking folder |
| **Duplicate records (same path)** | — | — | ✅ automatic merge | — | — | ✅ merge / split / keep, per group |
| **Duplicate files (same content, different paths)** | — | — | — | — | ✅ listed only | — |
| **Unreferenced media records** (0 backlinks) | — | — | — | — | — | ✅ remove if "bare", otherwise keep |
| **Files on disk not in the database** | ✅ imports images | — | — | — | ✅ "Extra Files" tab | ◐ listed in report (5,000-file cap) |
| **Relative ↔ absolute path conversion** | ✅ string only | — | — | — | ◐ as a side effect of Fix | ✅ by consolidating into base path |
| **Bulk path substring replace** | ✅ | — | — | — | — | ◐ *Look in folder*: old folder → new folder, only where the file exists |
| **Genealogy-aware file naming** | — | — | — | — | — | ✅ token templates + presets |
| **Name mismatch detection** (description vs. linked person) | — | — | — | — | — | ✅ |
| **GEDCOM import-note cleanup** | — | — | — | — | — | ✅ |
| **Checksums (MD5) maintained** | — | — | — | — | ✅ | ✅ on every relink/move/copy, *Store checksums* button, Accept-all step; never cleared |
| **Preview before changes** | ✅ confirmation page | n/a | — | n/a | ◐ tab list before Fix | ✅ per-dialog tables + Accept-all plan |
| **Undo** | Gramps undo | n/a | ✗ erases undo history (BatchTool) | n/a | Gramps undo (batch txn) | Gramps undo + file-move log ("Undo last file moves") |
| **Exportable results** | — | — | — | ✅ PDF | ✅ text file | ✅ `GWizardMediaFixReport.txt` + viewer |
| **Image preview** | — | ✅ with region | — | ✅ in PDF | — (double-click opens file) | ✅ in Find missing and Fix references, all regions outlined; double-click opens file |
| **Jump to media editor** | — | — | — | — | ✅ double-click | — |
| **CLI mode** | — | — | — | ✅ | ◐ registered, but builds a GTK window | — |
| **Automated tests** | core tests | — | — | — | — | ✅ 8 test modules, 182 tests |

---

## Tool-by-tool Detail

### 1. Built-in Media Manager

Four batch operations, one per wizard run:

1. *Replace substrings in the path* (`PathChange`)
2. *Convert paths from relative to absolute* (`Convert2Abs`)
3. *Convert paths from absolute to relative* (`Convert2Rel`)
4. *Add images not included in database* (`ImagesNotIncluded`): walks every directory already referenced by a media record and adds any **image** MIME type not yet in the database.

It edits strings only and never checks that the resulting path exists. Overlap with GWizard Media Fix: path conversion (GWizard does it by physically consolidating files) and unindexed files (GWizard reports them but does not import them). See `MediaManager_ToolComparison.md` for the full head-to-head.

### 2. Media Browser (Gramplet)

* Shown in the Person category. For the active person it builds a tree of:
  * the person's own media,
  * each event's media and the media of that event's cited sources,
  * the media of the person's cited sources.
* Selecting a row shows the image in a `Photo` widget, cropped to the media reference's region rectangle.
* **Read-only.** It does no detection, fixing or reporting. A missing file simply shows no image.
* Limits seen in the code: family media and media attached directly to citations are not shown. The registered description ("Gramplet showing details of a person") is generic.
* **Overlap with GWizard Media Fix:** none functionally. It complements GWizard, because a user can visually confirm a person's images after a fix.

### 3. Merge Media (`MediaMerge`)

* Runs over every media record and builds a key with `os.path.normcase(os.path.normpath(media_path_full(...)))`. When two records share a key, it merges them with `MergeMediaQuery`.
* **Keeper choice:** the shorter stored path wins; on a tie, the lower numeric Gramps ID; failing that, the lower handle.
* It runs as a `BatchTool`, so Gramps warns that the **undo history will be erased**. There is no preview and no per-group choice. It merges whether or not the file exists.
* **Overlap with GWizard Media Fix:** this is exactly the "duplicate file references" half of *Fix media references*. GWizard is a superset:
  * It picks the keeper by **most backlinks**, then having an associated person/event, then having a description, then Gramps ID.
  * Each group can be merged, split into separate file copies, or left shared.
  * Changes are previewed, run inside an undoable `DbTxn`, and the run also handles unreferenced records.

### 4. Media Report (`MediaReport`)

* A text report that produces **PDF only**, for **one image** chosen in the options.
* Contents: optional heading, the image (scaled to a % of the page), an optional custom note, and optionally the media's description, MIME type, attributes, tags, notes and citations (source author/title/pub info + page), plus a table of **referenced people** with a cropped face thumbnail taken from each Person media-reference rectangle.
* **Overlap with GWizard Media Fix:** only the word "report". MediaReport is for printing and sharing one image. GWizard's *Generate report* is a database-wide diagnostic.

### 5. Media Verify (`MediaVerify`)

* **Generate:** computes an MD5 checksum for each media file and stores it with `media.set_checksum()` in one batch transaction. Unreadable files go to an *Errors* tab.
* **Verify** (requires a base media path): hashes **every file** under the base media path, then compares the hashes with the stored checksums and fills six tabs:
  * **Moved/Renamed Files:** the record's checksum was found at a different relative path. When several copies exist, the copy with the same basename is chosen.
  * **Missing Files:** no file under the base path has the record's checksum.
  * **Duplicate Files:** two or more files on disk have identical content.
  * **Extra Files:** files on disk whose checksum belongs to no record.
  * **No md5 Generated** and **Errors**.
* **Fix:** repoints every "moved" record to its new relative path.
* **Export:** writes all tabs to a text file. Double-clicking a row opens `EditMedia` (records) or the file itself (disk files).
* Behaviors to be aware of:
  * Stored paths are compared literally with *relative* paths, so a record with a correct **absolute** path is listed as "moved". Fix then converts it to relative.
  * A file whose content changed after Generate (edited, re-saved, EXIF rotated) is reported as **Missing**.
  * Files outside the base media path are never seen, so their records always appear as Missing.
* **Overlap with GWizard Media Fix:** high. Both find missing files, find disk files that aren't in the database, repoint records, store MD5 checksums and match renamed files by content. Media Verify's remaining unique strengths are listing files that are **identical in content but stored at different paths**, matching extra disk files by content, and flagging files whose content changed since their checksum. GWizard's strengths are permission diagnosis, ambiguity protection, folder-layout matching, the image preview, consolidation, naming, and undoable file moves. Both use Gramps' own MD5 format, so checksums stored by one are used by the other.

### 6. GWizard Media Fix (`MediaFix`)

Main window: *Generate report*, *Find missing media*, *Fix media references*, *Consolidate media location*, *Clean import notes*, *Store checksums*, *Undo last file moves*, and **Accept all hints** (builds a full plan with `build_accept_all_plan`, shows it for confirmation, then runs it: find missing, fix references, consolidate, store checksums).

* **Find missing media:**
  * Checks each record's file for existence. If the file is missing, it checks permissions along the path and names the folder that blocks access.
  * It then looks in the base media directory: first for a file with the record's stored **checksum** (found even if renamed or moved), then for a **unique** file with the same basename. A same-name file whose content differs from the stored checksum is not suggested. The search is recursive only when a base media path is configured, so a whole home folder is never walked by accident.
  * `ambiguous_matches()` refuses a hint when different original paths would land on the same file.
  * Picking a file fills in other records missing a file of the same name, unless their checksum shows different content.
  * *Look in folder...* searches a chosen folder and its subfolders: by the **old folder layout** (`D:/OldPC/Pictures/1910/a.jpg` → `<folder>/1910/a.jpg`, verified on disk), then by content, then by unique name. A preview groups the results by old folder before any row is filled; the files are used where they are.
  * A preview pane under the table shows the focused row's file, with each media reference's region outlined and listed.
* **Fix media references:**
  * Groups records by resolved path. Each group can be **merged** into a keeper (most backlinks first), **split** into separate file copies, or **kept shared**.
  * Records with zero backlinks are removed only if they are "bare": no notes, attributes, tags, citations or date.
  * A preview pane shows the shared file with every record's references outlined, one colour per record, so a merge's result can be seen.
* **Consolidate media location:**
  * Moves or copies files into the base path, stores them as relative paths and optionally renames them with a template.
  * Template tokens: `{ref_id}`, `{surname}`, `{given}`, `{doc_type}`, `{year}`, `{id}`, `{orig}`, `{hash}`, `{ext}`. There are seven presets, and the chosen template is persisted in config.
  * The name comes from the person a file is *of* (for example, the right participant on a shared census event).
  * A shared file is moved once and every record pointing at it is repointed. Collisions never overwrite.
  * Every move is written to `GWizardMediaFix-moves.csv`, which *Undo last file moves* reverses safely.
* **Clean import notes:** removes stale GEDCOM *"Records not imported into OBJE"* notes once the media has been relinked.
* **Generate report:**
  * Summary metrics, then sections for duplicates, permission problems, unreferenced records, name mismatches, files outside the default path, unreferenced disk files, missing files, absolute paths and non-standard filenames.
  * The unreferenced-disk-files scan uses a fixed list of multimedia extensions, skips system and hidden folders, and stops at 5,000 files.
* **Store checksums:** reads every media file and stores its MD5 on the record (adds missing ones, updates changed ones). A checksum is never cleared when a file cannot be read, because that is what lets a renamed file be found again.
* Fixed records get the **`GWizard: MediaFixed`** tag.

> **Correction to `MediaManager_ToolComparison.md`:** that document says missing-file candidates use "basename matching and similarity scoring". There is no similarity scoring for files: candidates are matched by **stored checksum** (content), by **folder layout** (*Look in folder*), or by **exact, unique, case-insensitive basename**. `difflib` similarity is used only for *person-name* matching (`_name_score`, `find_name_mismatches`).

---

## Overlap Map

| Problem the user has | Best existing tool | Notes |
| :--- | :--- | :--- |
| "I moved my whole folder and every path is wrong" | **GWizard *Look in folder*** | Maps the old folder onto the new one and uses only files that exist. Media Manager's *Replace substrings* is faster but doesn't check the result. |
| "I renamed files on disk" | **GWizard Media Fix** or **Media Verify** | Both match by content, but only for records that had a checksum stored before the rename (GEDCOM imports have none: run *Store checksums* first). |
| "Several records point at the same file" | **GWizard Media Fix** | Merge Media does this too, but blindly and without undo. |
| "Two different paths hold the same picture" | **Media Verify** (lists them only) | No tool merges these. |
| "Files in my folder aren't in Gramps" | Media Manager (imports images) / Media Verify (lists) / GWizard (reports) | Only Media Manager adds records. |
| "Scattered absolute paths, inconsistent names" | **GWizard Media Fix** | Unique in ecosystem. |
| "Is this person's media right?" (visual check) | **Media Browser** | Complements any fix tool. |
| "Print a page about this photo" | **Media Report** | Out of scope for GWizard. |

---

## When to Use Which Tool

* **Media Manager:** for quick string-only path rewrites, or to bulk-import new images from folders already in use.
* **Media Browser:** to visually check a person's media tree (including region crops) while you work.
* **Merge Media:** for a quick one-shot merge of same-path records, if losing undo history is acceptable. GWizard's *Fix media references* is the safer choice.
* **Media Report:** to produce a printable PDF about a single photo and the people in it.
* **Media Verify:** to find files that are identical in content but stored at different paths, or files edited since their checksum was stored.
* **GWizard Media Fix:** for an end-to-end audit and repair: missing files (by content, folder layout or name, with a preview of each image), permissions, duplicate and orphan records, consolidating into the base path, standard names, checksums, import-note cleanup, and an undoable file-move history.
