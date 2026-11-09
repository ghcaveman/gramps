# GUI Verification Instructions for Button Placement Changes (Commit 1)

This document provides step-by-step instructions to navigate to each of the changed windows and widgets in Gramps to validate the button ordering differences between Linux and Windows.

---

## 1. Column Order Configuration (`ColumnOrder`)

* **File**: `gramps/gui/columnorder.py`
* **How to Navigate**:
  1. Open Gramps and navigate to the **People** category on the left sidebar (select **People List View**).
  2. Select **View → Configure View...** from the top menu (or click the **Configure View** button in the toolbar, or press `Ctrl+Shift+C`).
  3. Select the **Columns** tab in the configuration dialog.
* **What to Observe**:
  * Check the bottom-right corner of the tab for the **Apply** button.
  * In Commit 1, it uses `btns.set_layout(Gtk.ButtonBoxStyle.END)` and honors Windows button ordering conventions, placing `[Apply]` at the bottom-right on both platforms (`Windows/Linux`).

---

## 2. Sidebar Search Filter (`SidebarFilter`)

* **File**: `gramps/gui/filters/sidebar/_sidebarfilter.py`
* **How to Navigate**:
  1. Open any main category view (e.g., **People**, **Families**, or **Events**).
  2. Ensure the sidebar is visible (**View → Sidebar** or press `Ctrl+Alt+S`).
  3. Click the top **Filter** tab on the sidebar.
* **What to Observe**:
  * Inspect the action buttons located directly below the filter search entry fields:
    * **Linux**: `[Find]` is on the left, `[Reset]` is on the right.
    * **Windows**: `[Reset]` is on the left, `[Find]` is on the right.

---

## 3. Organize Bookmarks Dialog (`BookmarksDialog`)

* **File**: `gramps/gui/views/bookmarks.py`
* **How to Navigate**:
  1. From the top menu bar, select **Bookmarks → Organize Bookmarks...**
* **What to Observe**:
  * Look at the vertical button stack directly to the right of the bookmarks list:
    * **Linux**: Top-to-bottom order is `[Up]`, `[Down]`, `[Remove]`.
    * **Windows**: Top-to-bottom order is `[Remove]`, `[Down]`, `[Up]`.
  * The bottom dialog action buttons remain `[Close]` and `[Help]`.

---

## 4. Organize Tags Dialog (`OrganizeTagsDialog`)

* **File**: `gramps/gui/views/tags.py`
* **How to Navigate**:
  1. From the top menu bar, select **Edit → Organize Tags...** (or click the **Tag** dropdown icon in the toolbar and select **Organize Tags...**).
* **What to Observe**:
  * Inspect the vertical button stack directly to the right of the tags list:
    * **Linux**: Top-to-bottom order is `[Up]`, `[Down]`, `[Add]`, `[Edit]`, `[Remove]`.
    * **Windows**: Top-to-bottom order is reversed: `[Remove]`, `[Edit]`, `[Add]`, `[Down]`, `[Up]`.
  * The bottom dialog action buttons remain `[Close]` and `[Help]`.

---

## 5. Plugin Manager (`PluginStatus`)

* **File**: `gramps/gui/plug/_windows.py`
* **How to Navigate**:
  1. From the top menu bar, select **Help → Plugin Manager**.
* **What to Observe**:
  * **"Registered Plugins" and "Loaded Plugins" tabs**: Look at the button box below the list:
    * **Linux**: `[Info]` on the left, `[Hide/Unhide]` on the right.
    * **Windows**: `[Hide/Unhide]` on the left, `[Info]` on the right.
  * **"Install Addons" tab**: Look at the button box at the bottom of the page:
    * **Linux**: `[Install Addon]`, `[Install All Addons]`, `[Refresh Addon List]`.
    * **Windows**: `[Refresh Addon List]`, `[Install All Addons]`, `[Install Addon]`.

---

## 6. Report List Options (`_guioptions.py`: Person, Place, and Surname Color Lists)

* **File**: `gramps/gui/plug/_guioptions.py`
* **How to Navigate**:
  * **Place List Option**:
    1. Select **Reports → Text Reports → Place Report...** from the top menu.
    2. Locate the **"Select places individually"** section.
  * **Person List & Surname Color Options**:
    1. Select **Reports → Graphs → Family Lines Graph...** from the top menu.
    2. Locate the **"People of interest"** and **"Family colors"** sections.
* **What to Observe**:
  * Inspect the vertical button boxes alongside the item lists:
    * **Linux**: `[+]` (Add) on top, `[-]` (Remove) below it.
    * **Windows**: `[-]` (Remove) on top, `[+]` (Add) below it.

---

## 7. Error Report Assistant (`ErrorReportAssistant`)

* **File**: `gramps/gui/logger/_errorreportassistant.py`
* **How to Navigate**:
  1. When a warning or error occurs in Gramps, click the notification icon on the statusbar to open the **Error View** dialog.
  2. In the Error View dialog, click the **Report** button to launch the **Error Report Assistant**.
* **What to Observe**:
  * On Page 1 (*Error Details*) and Page 2 (*System Information*), examine the button box at the bottom right of the text area:
    * **Linux**: `[Clear]` on the left, `[Reset]` on the right.
    * **Windows**: `[Reset]` on the left, `[Clear]` on the right.
