# GUI Verification Instructions for Remaining Python Dialogs (Commit 3)

This document provides step-by-step instructions to navigate to each of the remaining Python dialogs updated in Commit 3 with GTK's native `set_alternative_button_order_from_array` method to validate the button ordering on Windows and Linux.

---

## Summary of Changes

All dialogs below use `set_alternative_button_order_from_array`.
* **When running on Linux / macOS** (`gtk-alternative-button-order = False`): The buttons appear in the default GTK order (`[Help]` on the far left, `[Cancel / Close]` in the middle, `[OK / Affirmative Action]` on the right).
* **When running on Windows** (`gtk-alternative-button-order = True`): GTK automatically reorders the action buttons to conform to the Windows standard (`[OK / Affirmative Action]` on the left, `[Cancel / Close]` in the middle/right, and `[Help]` on the far right).

---

## 1. Dialogs with Help (`[Help] [Cancel] [OK]` → Windows: `[OK] [Cancel] [Help]`)

### 1.1 Edit Tag List Dialog (`EditTagList`)
* **File**: `gramps/gui/editors/edittaglist.py`
* **How to Navigate**:
  1. Open the Person Editor on any person (**People → Edit Person**).
  2. Next to the Tags field, click the **Edit Tag List** icon/button (or open the tag selection dialog).
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Help]` `[Cancel]` `[OK]`
    * **Windows**: `[OK]` `[Cancel]` `[Help]`

### 1.2 Edit Tag Dialog (`EditTag`)
* **File**: `gramps/gui/views/tags.py`
* **How to Navigate**:
  1. From the top menu bar, select **Edit → Organize Tags...**
  2. Select an existing tag and click **Edit** (or click **Add**).
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Help]` `[Cancel]` `[OK]`
    * **Windows**: `[OK]` `[Cancel]` `[Help]`

### 1.3 Report Dialog (`ReportDialog`)
* **File**: `gramps/gui/plug/report/_reportdialog.py`
* **How to Navigate**:
  1. Select any report from the menu (e.g., **Reports → Text Reports → Detailed Ancestral Report...**).
* **What to Observe**:
  * Bottom dialog action buttons:
    * **Linux**: `[Help]` `[Cancel]` `[OK]`
    * **Windows**: `[OK]` `[Cancel]` `[Help]`

### 1.4 Test Case Generator Dialog (`TestCaseGenerator Dialog`)
* **File**: `gramps/plugins/tool/testcasegenerator.py`
* **How to Navigate**:
  1. From the top menu bar, select **Tools → Debug → Generate Test Cases...**
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[OK]` `[Help]`
    * **Windows**: `[OK]` `[Cancel]` `[Help]`

### 1.5 Error View Dialog (`ErrorView`)
* **File**: `gramps/gui/logger/_errorview.py`
* **How to Navigate**:
  1. When a warning or error occurs in Gramps, click the warning notification in the bottom statusbar.
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[Report]` `[Help]`
    * **Windows**: `[Report]` `[Cancel]` `[Help]`

---

## 2. FamilySearch Plugin Dialogs (`gramps/gui/fs/`)

### 2.1 Link FamilySearch ID (`link_familysearch_id`)
* **File**: `gramps/gui/fs/actions.py`
* **How to Navigate**:
  1. In the Person Editor or FamilySearch Tools, select **Link FamilySearch ID...**
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[OK]`
    * **Windows**: `[OK]` `[Cancel]`

### 2.2 Import Selected Relatives (`_prompt_and_import_relatives`)
* **File**: `gramps/gui/fs/actions.py`
* **How to Navigate**:
  1. In FamilySearch integration, trigger the relative import prompt.
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[Import selected]`
    * **Windows**: `[Import selected]` `[Cancel]`

### 2.3 Bulk Import Relatives (`bulk_import_relatives`)
* **File**: `gramps/gui/fs/actions.py`
* **How to Navigate**:
  1. Open the FamilySearch Tools window (**Tools → Utilities → FamilySearch Tools**).
  2. Click the **Bulk Import Relatives** button.
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[Import]`
    * **Windows**: `[Import]` `[Cancel]`

### 2.4 FamilySearch Match Dialog (`import_from_familysearch_match_dialog`)
* **File**: `gramps/gui/fs/actions.py`
* **How to Navigate**:
  1. In FamilySearch import workflow when matching an existing person or tree.
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[Continue]`
    * **Windows**: `[Continue]` `[Cancel]`

### 2.5 FamilySearch Authentication Session (`_prompt_for_auth_code`)
* **File**: `gramps/gui/fs/session.py`
* **How to Navigate**:
  1. Initiate FamilySearch login requiring browser authorization code copy-paste.
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[Continue]`
    * **Windows**: `[Continue]` `[Cancel]`

### 2.6 Sync to FamilySearch Directions
* **File**: `gramps/gui/fs/sync_directions.py`
* **How to Navigate**:
  1. Trigger Sync to FamilySearch comparison options.
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[Apply Selected]`
    * **Windows**: `[Apply Selected]` `[Cancel]`

### 2.7 Export to FamilySearch
* **File**: `gramps/gui/fs/sync_directions.py`
* **How to Navigate**:
  1. In FamilySearch Tools, select **Export to FamilySearch**.
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[Export]`
    * **Windows**: `[Export]` `[Cancel]`

### 2.8 Import FamilySearch Sources (`sources_dialog`)
* **File**: `gramps/gui/fs/person/mixins/sources_dialog.py`
* **How to Navigate**:
  1. In FamilySearch person comparison, click the **Import sources...** button.
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[Import selected]`
    * **Windows**: `[Import selected]` `[Cancel]`

---

## 3. Plugins & Tools Dialogs / Choosers (`gramps/plugins/`)

### 3.1 Check Image File Chooser
* **File**: `gramps/plugins/tool/check.py`
* **How to Navigate**:
  1. Run **Tools → Database Processing → Check and Repair Database...** when missing media files are identified.
* **What to Observe**:
  * Action buttons in the file chooser:
    * **Linux**: `[Cancel]` `[OK]`
    * **Windows**: `[OK]` `[Cancel]`

### 3.2 Populate Sources Tool Dialog
* **File**: `gramps/plugins/tool/populatesources.py`
* **How to Navigate**:
  1. Select **Tools → Debug → Populate sources and citations...**
* **What to Observe**:
  * Action buttons:
    * **Linux**: `[Cancel]` `[OK]`
    * **Windows**: `[OK]` `[Cancel]`

### 3.3 Event Comparison Spreadsheet Chooser
* **File**: `gramps/plugins/tool/eventcmp.py`
* **How to Navigate**:
  1. Run **Tools → Utilities → Event Comparison...**
  2. Click the save/export spreadsheet button.
* **What to Observe**:
  * Action buttons in the file chooser:
    * **Linux**: `[Cancel]` `[Save]`
    * **Windows**: `[Save]` `[Cancel]`

### 3.4 KML Import File Chooser
* **File**: `gramps/plugins/lib/maps/geography.py`
* **How to Navigate**:
  1. In the Geography view, click the KML place import button.
* **What to Observe**:
  * Action buttons in the file chooser:
    * **Linux**: `[Cancel]` `[Apply]`
    * **Windows**: `[Apply]` `[Cancel]`

### 3.5 Geography Tile Cache Directory Chooser
* **File**: `gramps/plugins/lib/maps/geography.py`
* **How to Navigate**:
  1. In the Geography view preferences, choose the offline tile cache directory.
* **What to Observe**:
  * Action buttons in the directory chooser:
    * **Linux**: `[Cancel]` `[Apply]`
    * **Windows**: `[Apply]` `[Cancel]`

---

## 4. Miscellaneous Windows

### 4.1 Tool Managed Window (`ToolManagedWindow`)
* **File**: `gramps/gui/plug/_windows.py`
* **How to Navigate**:
  1. Select any interactive tool from **Tools** that opens a managed tool window (e.g., **Tools → Utilities → Media Manager...**).
* **What to Observe**:
  * Bottom dialog action buttons:
    * **Linux**: `[Close]` `[Execute]`
    * **Windows**: `[Execute]` `[Close]`
