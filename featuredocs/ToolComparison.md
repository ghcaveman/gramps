# Comparison: GWizard Media Fix vs. Built-in Media Manager

## Overview

This document provides a comprehensive comparison between the **Built-in Media Manager** tool and the **GWizard Media Fix** tool in Gramps.

* **Built-in Media Manager (`mediamanager.py`)**:
  * **Core Philosophy:** Treats media files as *external, unmanaged assets*. It operates primarily as a **database string manipulation utility** and bulk-import tool.
  * **Key Function:** Batch updates path strings stored inside Gramps database records (e.g., search-and-replace directory paths, converting between absolute and relative paths) and discovers unindexed images to create new media records. It **does not alter files on disk**.
  * **Location in Gramps:** Top menu **Tools → Tree Repair → Media Manager** (or **Tools → Utilities → Media Manager** depending on Gramps version).

* **GWizard Media Fix (`gwizardmediafix.py`)**:
  * **Core Philosophy:** An **end-to-end media maintenance, repair, and curation workbench** that synchronizes both the Gramps database and the physical file system.
  * **Key Function:** Audits media health, detects and recovers broken/missing links, resolves duplicate/unreferenced records, physically moves/copies/consolidates files into the base media directory, standardizes file naming using genealogical metadata tokens, cleans import artifacts, and provides diagnostic audit reporting.
  * **Location in Gramps:** Top menu **Tools → GWizard Media Fix**.

---

## Feature Comparison Matrix

| Capability | Built-in Media Manager | GWizard Media Fix |
| :--- | :--- | :--- |
| **Primary Target** | Database path strings | Database records **and** physical disk files |
| **UI Paradigm** | Step-by-step wizard (`Gtk.Assistant`) running one isolated operation per run | Interactive dashboard with modular tools + one-click automated "Accept all hints" pipeline |
| **Path Conversion** | Converts Relative $\leftrightarrow$ Absolute via pure DB string prepending/stripping | Consolidates all files into the base directory as relative paths with physical move/copy |
| **File System Operations** | **None** (does not touch, move, or rename disk files) | **Active** (moves, copies, and renames files on disk with collision handling & dry-run previews) |
| **Broken Link / Missing Media Detection** | None (cannot detect if a file is missing or broken) | Automatically detects missing files, scans directories for candidate matches, and offers resolution hints |
| **Duplicate Media Records** | None | Detects multiple media records pointing to the same file; merges into a keeper record or splits into separate file copies |
| **Unreferenced Media Records** | None | Identifies media objects with 0 backlinks / references and allows safe removal or retention |
| **Unreferenced Files on Disk** | Scans directories and **bulk-adds** unindexed images as new database records | Detects unreferenced disk files and flags them in the comprehensive diagnostic report |
| **File Naming & Standardization** | Arbitrary substring replacement (`from_text` $\rightarrow$ `to_text`) | Contextual naming templates using metadata tokens (`{surname}`, `{given}`, `{year}`, `{doc_type}`, `{ref_id}`, `{hash}`) |
| **Stale Import Notes Cleanup** | None | Automatically detects and removes stale GEDCOM import notes (*"Records not imported into OBJE"*) once resolved |
| **Safety & Protection** | Progress bar and transaction rollback | Transaction safety, dry-run previews, collision-proof filename hashing, permission checks, and `GWizard: Locked` / `GWizard: Media Fixed` tags |
| **Diagnostic Reporting** | None (simple success/fail summary page) | Generates and displays a detailed diagnostic health report (`GWizardMediaFixReport.txt`) |

---

## Detailed Functional Differences

### 1. Path Conversion vs. Physical File Consolidation

* **Media Manager:**
  * Offers three path-string operations:
    1. *Replace substrings in the path* (`PathChange`): Substring search-and-replace across stored path strings.
    2. *Convert paths from relative to absolute* (`Convert2Abs`): Prepends the Base media path or user home directory to relative paths.
    3. *Convert paths from absolute to relative* (`Convert2Rel`): Strips the Base media path prefix to convert absolute paths into relative paths.
  * **Limitation:** Gramps assumes the user handled physical file moves manually outside of Gramps. If files were moved inconsistently or typos occurred in the path replacement, links remain broken with no notification.
* **GWizard Media Fix:**
  * Through **Consolidate media location**, it physically moves or copies files from scattered locations (or absolute paths) into the Gramps *Base media path*.
  * It verifies file existence and directory write permissions before making changes, calculates relative paths, and handles collisions safely without overwriting existing files.

### 2. Broken Links and Missing Files

* **Media Manager:**
  * Has no concept of link verification. If a path points to a deleted, renamed, or relocated file, Media Manager ignores it.
* **GWizard Media Fix:**
  * The **Find missing media** tool scans all media records, verifies physical existence, and presents a dedicated table of broken links.
  * Suggests candidate matches found in the base media folder (using basename matching and similarity scoring) and allows users to specify an external folder to locate and copy missing files back into the project.

### 3. Handling Duplicates and Unreferenced Media

* **Media Manager:**
  * Cannot detect duplicate records.
  * Offers **"Add images not included in database"** (`ImagesNotIncluded`), which recursively scans directories mentioned by existing media and automatically imports any unindexed image files as new `Media` objects.
* **GWizard Media Fix:**
  * **Fix media references** addresses the opposite problem: duplicate media entries in the database pointing to the same physical file (often created by repeated GEDCOM imports or manual re-entry).
  * Lets the user merge duplicate records into a single "keeper" record (re-pointing all citations and person backlinks) or create distinct disk copies for each reference.
  * Also identifies "bare" or unreferenced image tags (media records with 0 backlinks) so the database can be cleaned up without leaving orphaned records.

### 4. Naming Conventions & Genealogical Context

* **Media Manager:**
  * Limited to raw string substitution across paths without any awareness of person or event metadata.
* **GWizard Media Fix:**
  * Understands the genealogical hierarchy. It queries backlinks to find the associated `Person`, `Family`, or `Event`, extracting dates, names, and document types.
  * Supports standardized naming patterns (e.g., `{surname}_{given}_{year}_{doc_type}.ext`), transforming arbitrary camera or scan names (`IMG_0492.JPG`) into organized, human-readable file collections.

### 5. Import Artifact Cleanup

* **Media Manager:**
  * Does not inspect notes or import artifacts.
* **GWizard Media Fix:**
  * Includes a dedicated **Clean import notes** action that detects and removes stale *"Records not imported into OBJE"* notes left behind by GEDCOM importers once missing media files have been re-linked.

### 6. Audit and Reporting

* **Media Manager:**
  * Only shows a completion screen indicating how many records were modified.
* **GWizard Media Fix:**
  * Features **Generate report**, which writes a diagnostic text report (`GWizardMediaFixReport.txt`) cataloging:
    * Missing media files
    * Inaccessible directories / permission errors
    * Absolute paths needing relative conversion
    * Duplicate reference groups
    * Non-standard filenames
    * Name mismatches (media description vs. linked person)
    * Unreferenced files residing in the base media directory

---

## When to Use Which Tool

* **Use Built-in Media Manager when:**
  * You moved an entire folder structure on disk manually and only need a quick batch text find-and-replace on path strings.
  * You simply want to convert all existing database paths between relative and absolute without touching files on disk.
  * You dropped a batch of photos into an existing media directory and want Gramps to quickly import them all as new blank media records.

* **Use GWizard Media Fix when:**
  * You need to audit the overall health and integrity of your tree's media.
  * You have missing or broken media links and need assistance finding or restoring the files.
  * You have duplicate media records or clutter from multiple GEDCOM imports.
  * You want Gramps to physically consolidate scattered media files into a central directory and enforce clean, standard naming conventions.
