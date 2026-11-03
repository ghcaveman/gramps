# GUI Verification Instructions for Native GTK Alternative Button Order Changes (Commit 2)

This document provides step-by-step instructions to navigate to each of the dialogs updated with GTK's native `set_alternative_button_order_from_array` method to validate the button ordering on Windows and Linux.

---

## Summary of Changes

All dialogs below use `set_alternative_button_order_from_array`.
* **When running on Linux / macOS** (`gtk-alternative-button-order = False`): The buttons appear in the default GTK order (`[Cancel / Close]` on the left, `[OK / Affirmative Action]` on the right).
* **When running on Windows** (`gtk-alternative-button-order = True`): GTK automatically reorders the action buttons to place the affirmative button on the left (`[OK / Affirmative Action]` on the left, `[Cancel / Close]` on the right).

---

## 1. File Chooser Dialogs

### 1.1 Export View File Chooser
* **File**: `gramps/gui/views/listview.py`
* **How to Navigate**:
  1. Open any list view (e.g., **People → People List View**, **Families**, or **Events**).
  2. From the top menu bar, select **Family Trees → Export View...**
* **What to Observe**:
  * Action buttons in the file chooser:
    * **Linux**: `[Cancel]` `[Save]`
    * **Windows**: `[Save]` `[Cancel]`

### 1.2 Preferences Path Choosers (Media, Database, and Backup)
* **File**: `gramps/gui/configure.py`
* **How to Navigate**:
  1. From the top menu bar, select **Edit → Preferences...** (or press `Ctrl+Shift+P`).
  2. Test each path chooser:
     * **General tab**: Click the folder browse button next to **"Base path for relative media paths:"**.
     * **Database tab**: Click the folder browse button next to **"Database path:"**.
     * **Database tab**: Click the folder browse button next to **"Backup path:"**.
* **What to Observe**:
  * Action buttons in each directory chooser dialog:
    * **Linux**: `[Cancel]` `[Apply]`
    * **Windows**: `[Apply]` `[Cancel]`

### 1.3 Media Path Chooser (Quick Backup)
* **File**: `gramps/gui/viewmanager.py`
* **How to Navigate**:
  1. From the top menu bar, select **Family Trees → Make Backup...**
  2. In the "Gramps XML Backup" dialog, click the folder browse icon next to the **"Path:"** field.
* **What to Observe**:
  * Action buttons in the directory chooser:
    * **Linux**: `[Cancel]` `[Apply]`
    * **Windows**: `[Apply]` `[Cancel]`

### 1.4 Install Addon File Chooser
* **File**: `gramps/gui/plug/_windows.py`
* **How to Navigate**:
  1. From the top menu bar, select **Help → Plugin Manager**.
  2. Click the **Install Addons** tab.
  3. Click the file browse button next to **"Install addon from local file:"**.
* **What to Observe**:
  * Action buttons in the file chooser:
    * **Linux**: `[Cancel]` `[Open]`
    * **Windows**: `[Open]` `[Cancel]`

### 1.5 Report Destination File Chooser
* **File**: `gramps/gui/plug/report/_fileentry.py`
* **How to Navigate**:
  1. Select **Reports → Text Reports → Detailed Ancestral Report...** (or any text report).
  2. On the **Document Options** tab, click the file browse icon next to **"Destination:"**.
* **What to Observe**:
  * Action buttons in the file chooser:
    * **Linux**: `[Cancel]` `[Open]`
    * **Windows**: `[Open]` `[Cancel]`

### 1.6 Option File Chooser
* **File**: `gramps/gui/plug/_guioptions.py`
* **How to Navigate**:
  1. Select **Reports → Books → Book Report...**
  2. On the **Paper Options** tab, click the browse button next to any file/directory destination option.
* **What to Observe**:
  * Action buttons in the file chooser:
    * **Linux**: `[Cancel]` `[Open]`
    * **Windows**: `[Open]` `[Cancel]`

---

## 2. Action & Confirmation Dialogs

### 2.1 Quick Backup Dialog (`QuickBackup`)
* **File**: `gramps/gui/viewmanager.py`
* **How to Navigate**:
  1. From the top menu bar, select **Family Trees → Make Backup...**
* **What to Observe**:
  * Action buttons at the bottom of the "Gramps XML Backup" dialog:
    * **Linux**: `[Close]` `[OK]`
    * **Windows**: `[OK]` `[Close]`

### 2.2 Jump to by Gramps ID Dialog (`Jump to Dialog`)
* **File**: `gramps/gui/views/navigationview.py`
* **How to Navigate**:
  1. In any list view (People, Families, Events, etc.), press `Ctrl+J`.
* **What to Observe**:
  * Action buttons at the bottom of the dialog:
    * **Linux**: `[Cancel]` `[Jump to]`
    * **Windows**: `[Jump to]` `[Cancel]`

### 2.3 Import Family Tree Dialog (`GrampsImportFileDialog`)
* **File**: `gramps/gui/dbloader.py`
* **How to Navigate**:
  1. From the top menu bar, select **Family Trees → Import...** (or press `Ctrl+I`).
* **What to Observe**:
  * Action buttons at the bottom of the file chooser dialog:
    * **Linux**: `[Cancel]` `[Import]`
    * **Windows**: `[Import]` `[Cancel]`

### 2.4 Database Login Dialog (`GrampsLoginDialog`)
* **File**: `gramps/gui/dbloader.py`
* **How to Navigate**:
  1. Connect to or configure a database backend requiring authentication (e.g., PostgreSQL or MySQL via **Family Trees → Manage Family Trees... → New**).
* **What to Observe**:
  * Action buttons at the bottom of the login credentials dialog:
    * **Linux**: `[Cancel]` `[Login]`
    * **Windows**: `[Login]` `[Cancel]`

---

## 3. Dialogs in Previously Touched Files

### 3.1 Select Surname Dialog (`LastNameDialog`)
* **File**: `gramps/gui/plug/_guioptions.py`
* **How to Navigate**:
  1. From the top menu bar, select **Reports → Graphs → Family Lines Graph...**
  2. Under the **"Family colors"** section, click the `[+]` button to add a surname color rule.
  3. The **"Select surname"** modal dialog appears.
* **What to Observe**:
  * Action buttons at the bottom of the dialog:
    * **Linux**: `[Cancel]` `[OK]`
    * **Windows**: `[OK]` `[Cancel]`

### 3.2 Addon Project Dialog (`Addon Project Dialog`)
* **File**: `gramps/gui/plug/_windows.py`
* **How to Navigate**:
  1. From the top menu bar, select **Edit → Addon Manager...**
  2. Select the **Projects** tab.
  3. Click the `[+]` (Insert a project) button below the project list.
* **What to Observe**:
  * Action buttons at the bottom of the modal dialog:
    * **Linux**: `[Cancel]` `[OK]`
    * **Windows**: `[OK]` `[Cancel]`
