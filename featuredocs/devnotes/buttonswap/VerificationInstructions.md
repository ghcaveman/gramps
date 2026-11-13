# Button order (buttonswap): verification

How to check that dialog buttons follow the platform convention.

| Order   | Main buttons                   | Used when                                   |
|---------|--------------------------------|---------------------------------------------|
| GNOME   | `[Help] ...  [Cancel] [OK]`    | Linux/macOS by default                      |
| Windows | `[OK] [Cancel] [Help]`         | Windows by default                          |

## How it works

* `gramps/gui/buttonorder.py` holds all the logic.
  * `apply_platform_button_order()` sets GTK's `gtk-alternative-button-order`
    from the preference (called at startup and when the preference changes).
  * `apply_button_order(dialog)` moves the affirmative button (OK, Accept,
    Yes, Apply) first and Help last when that setting is on.
  * `apply_window_button_order(ok, help)` does the same for plain windows
    whose buttons carry no response ids.
* Hooks that apply it:
  * `Glade.__init__` (`gramps/gui/glade.py`): every dialog loaded from a
    `.glade` file.
  * `ManagedWindow.set_window()`: every Python-built ManagedWindow dialog,
    when the dialog is realized.
  * One-line `apply_button_order(dialog)` calls for file choosers and other
    dialogs that are not ManagedWindows.
  * `apply_window_button_order()` in the Book window, Change Names and
    Owner Editor.
* Only the main OK/Cancel row of a dialog is reordered. Other button rows
  (Add/Remove, Up/Down, sidebar Find/Clear, Plugin Manager) keep their
  order on every platform.

## Preference

**Edit → Preferences → General → Dialog button order**

* *Automatic* (default): Windows order on Windows, GNOME order elsewhere.
* *OK on the right (GNOME)* / *OK on the left (Windows)*: force one order.

Config key `interface.dialog-button-order` (0 = Automatic, 1 = GNOME,
2 = Windows). The change applies to dialogs opened afterwards; no restart.
On Windows the title-bar layout comes from `interface.window-controls`.

## Checks

Do each check twice: once with *OK on the left (Windows)* and once with
*OK on the right (GNOME)*. A Linux machine can test both orders.

| # | Open | Windows order | GNOME order |
|---|------|---------------|-------------|
| 1 | Edit → Add (any person): **Edit Person** | OK · Cancel · Help | [Help] … Cancel · OK |
| 2 | Any event → **Edit Event** | OK · Cancel · Help | [Help] … Cancel · OK |
| 3 | Edit → Remove a person → confirmation (**QuestionDialog**) | Yes/Delete first | Yes/Delete last |
| 4 | Edit a person, change a field, press Esc (**Save** dialog) | Save first | Save last |
| 5 | Reports → any text report (**ReportDialog**) | OK · Cancel · Help | [Help] … Cancel · OK |
| 6 | Preferences → Family Tree → media path **…** (file chooser) | Open/Select first | Open/Select last |
| 7 | Reports → Books (**Book window**) | OK · Close · Help | [Help] … Close · OK |
| 8 | Tools → Family Tree Processing → Fix Capitalization (**Change Names**) | Accept · Cancel · Help | Help · Cancel · Accept |
| 9 | Tools → Family Tree Processing → Edit Database Owner Information (**Owner Editor**) | OK · Cancel · Help | [Help] … Cancel · OK |
| 10 | Edit → Undo History (no OK button) | unchanged | unchanged |

Must **not** change between the two orders:

* Organize Tags and Bookmarks: Up / Down / Add / Edit / Remove
* Report options person/place lists: Add / Remove
* Sidebar filter: Find / Clear
* Plugin Manager: Info / Hide, Install / Refresh
* Tip of the Day: Forward / Close

Switch the preference while Gramps is running, then open a new dialog: it
should use the new order straight away.

## Static audit

`generate_dialog_placement.py` scans the source and writes
`DialogPlacement_Windows.csv` and `DialogPlacement_Linux.csv`
(`--platform windows|linux|both`). It reports the order the buttons are
declared in, i.e. before `buttonorder.py` reorders them at run time.
