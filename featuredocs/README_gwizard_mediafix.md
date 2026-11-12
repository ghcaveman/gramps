## Overview

The **GWizard Media Fix** tool helps genealogists clean up media files in a Gramps database.  It scans the database for missing files, duplicate references, and media stored outside the configured media base directory.  It can automatically rename files to a consistent naming convention, move scattered files into a single media folder, and generate a detailed report of any remaining issues.

## Usage

1. Open Gramps and select **Tools → GWizard Media Fix**.
2. In the dialog that appears you will see a set of buttons:
   - **Generate report** – creates a plain‑text report (`GWizardMediaFixReport.txt`).
   - **Find missing media** – lists media records whose files are not present on disk and lets you supply a new path.
   - **Fix media references** – resolves duplicate media records that point to the same file and removes unreferenced image tags.
   - **Consolidate media location** – moves or copies all media files into the configured *Base media path* and applies the selected naming template.
   - **Clean import notes** – removes stale “Records not imported into OBJE” notes after the missing files have been restored.
   - **Accept all hints** – runs the three automated steps above in sequence, showing a preview of the changes before applying them.
3. Follow the on‑screen instructions for each step.  Most actions present a preview table where you can edit the suggested new paths before clicking **Apply**.
4. After applying changes, the tool updates the database and, where applicable, moves or copies the actual files on disk.

## Configure Options

* **Base media path** – the folder that Gramps uses for relative media paths.  Set this in *Edit → Preferences → Family Tree* or directly in the **Consolidate media location** dialog.
* **Naming template** – choose one of the predefined filename templates or enter a custom pattern.  Tokens include:
  - `{ref_id}` – reference ID (person, event, family, or media ID)
  - `{surname}` – surname of the linked person (if any)
  - `{given}` – given name of the linked person (if any)
  - `{doc_type}` – description of the media
  - `{year}` – year extracted from the event or person
  - `{orig}` – original filename (used when *Keep original filename* is selected)
  - `{hash}` – short content hash (optional for guaranteed uniqueness)
* **Naming style** – *Use naming standard* (applies the chosen template) or *Keep original filename* (stores the file unchanged).
* **File operation** – *Move files* (renames the original file) or *Make a copy* (leaves the original untouched).

## Features

* **Detect missing media** – finds media records whose files cannot be located on disk and suggests possible matches in the media base folder.
* **Resolve duplicate references** – merges duplicate media records that share the same file, or creates separate copies for each reference.
* **Consolidate media locations** – moves all media files into the configured base directory, applying a consistent, safe filename.
* **Generate comprehensive report** – produces a human‑readable summary of all media issues, including missing files, permission problems, absolute paths, non‑standard filenames, duplicate references, and unreferenced files on disk.
* **Automated “Accept all hints”** – runs the three main fix steps automatically, with a preview of the actions and a list of any items that still require manual attention.
* **Clean stale import notes** – removes “Records not imported into OBJE” notes after the corresponding files have been restored.

![GWizard Media Fix main dialog](images/gwizard_mediafix-main.png)

![Find missing media dialog](images/gwizard_mediafix-find_missing.png)

![Fix media references dialog](images/gwizard_mediafix-fix_references.png)

![Consolidate media location dialog](images/gwizard_mediafix-consolidate.png)

![Generated report preview](images/gwizard_mediafix-report.png)
