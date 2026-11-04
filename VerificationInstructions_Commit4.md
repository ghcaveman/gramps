# GUI Verification Instructions for Final Python Dialogs (Commit 4)

This document provides step-by-step instructions to navigate to each of the remaining Python dialogs updated in Commit 4 with GTK's native `set_alternative_button_order_from_array` method to validate the button ordering on Windows and Linux.

---

## Summary of Changes

Both dialogs below use `set_alternative_button_order_from_array`.
* **When running on Linux / macOS** (`gtk-alternative-button-order = False`): The buttons appear in the default GNOME HIG order with `[Help]` on the far left.
* **When running on Windows** (`gtk-alternative-button-order = True`): GTK automatically reorders the action buttons to conform to the Windows standard with action/dialog buttons on the left and `[Help]` on the far right.

---

## 1. Undo History Dialog (`UndoHistory`)

* **File**: `gramps/gui/undohistory.py`
* **How to Navigate**:
  1. Open any family tree database in Gramps.
  2. From the top menu bar, select **Edit → Undo History...** (or press `Ctrl+H`).
* **What to Observe**:
  * Inspect the action buttons at the bottom of the dialog:
    * **Linux**: `[Help]` `[Undo]` `[Redo]` `[Clear]` `[Close]`
    * **Windows**: `[Undo]` `[Redo]` `[Clear]` `[Close]` `[Help]`
  * On Windows, `[Help]` is placed at the far right following the Windows convention, with the operational buttons (`[Undo]`, `[Redo]`, `[Clear]`, `[Close]`) on the left.

---

## 2. Choose Favorite Views Dialog (`FavoriteViews`)

* **File**: `gramps/plugins/sidebar/favoritessidebar.py`
* **How to Navigate**:
  1. Open any family tree database in Gramps.
  2. Ensure the sidebar is visible (**View → Sidebar** or press `Ctrl+Alt+S`).
  3. Click the **Favorites** tab on the sidebar.
  4. Click the gear/configuration icon on the favorites sidebar tab or choose **"Choose your favorite views..."**.
* **What to Observe**:
  * Inspect the action buttons at the bottom of the dialog:
    * **Linux**: `[Help]` `[Select All]` `[Clear All]` `[Close]`
    * **Windows**: `[Select All]` `[Clear All]` `[Close]` `[Help]`
  * On Windows, `[Help]` moves from the far left to the far right, with the action buttons (`[Select All]`, `[Clear All]`, `[Close]`) positioned on the left.
