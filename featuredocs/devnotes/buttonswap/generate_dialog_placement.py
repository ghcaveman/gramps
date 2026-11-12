#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Kevin White
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import glob
import os
import re
import csv
import html
import xml.etree.ElementTree as ET

BUTTON_CLASSES = {
<<<<<<< HEAD
    'GtkButton', 'GtkToggleButton', 'GtkColorButton',
    'GtkToolButton', 'GtkToggleToolButton', 'GtkMenuButton'
}

POSITIVE_KEYWORDS = {
    'ok', 'yes', 'save', 'load', 'confirm', 'accept', 'apply', 'add',
    'forward', 'next', 'import', 'execute', 'run', 'merge', 'jump',
    'jump to', 'select', 'login', 'connect', 'continue', 'retag',
    'check', 'reorder', 'convert', 'repair', 'archive', 'test',
    'install', 'install addon', 'install all addons', 'keep reference',
    'select all', 'import selected', 'merge selected', 'apply selected',
    'export', 'report', 'calculate previews', 'file bug report',
    'copy to clipboard', 'change order'
}

NEGATIVE_KEYWORDS = {
    'cancel', 'close', 'no', 'abort', 'reject', 'back', 'previous',
    'delete', 'remove', 'stop', 'clear', 'reset', 'dismiss',
    'close without saving', 'clear all', 'close window', 'abandon changes',
    'remove object', 'undo'
}

ICON_TO_LABEL = {
    'list-add': 'Add',
    'gtk-add': 'Add',
    'list-remove': 'Remove',
    'gtk-remove': 'Remove',
    'gtk-delete': 'Delete',
    'gtk-edit': 'Edit',
    'document-edit': 'Edit',
    'gtk-index': 'Share',
    'go-up': 'Up',
    'go-down': 'Down',
    'go-jump': 'Jump',
    'go-previous': 'Previous',
    'go-next': 'Next',
    'edit-clear': 'Clear',
    'document-revert': 'Revert',
    'document-new': 'New',
    'view-refresh': 'Refresh',
    'help-browser': 'Help',
    'gtk-help': 'Help',
    'gtk-close': 'Close',
    'gtk-cancel': 'Cancel',
    'gtk-ok': 'OK',
    'gtk-save': 'Save',
    'gtk-open': 'Open',
    'gtk-apply': 'Apply',
}

ID_TO_LABEL = {
    'ok': 'OK',
    'okbutton': 'OK',
    'ok_button': 'OK',
    'cancel': 'Cancel',
    'cancelbutton': 'Cancel',
    'cancel_button': 'Cancel',
    'cancel_btn': 'Close Window',
    'close': 'Close',
    'close_button': 'Close',
    'close_btn': 'Close',
    'help': 'Help',
    'helpbutton': 'Help',
    'help_button': 'Help',
    'help_btn': 'Help',
    'delete_button': 'Delete',
    'apply_button': 'Apply',
    'preview_button': 'Calculate Previews',
    'advanced_button': 'Change Order',
    'add_btn': 'Add',
    'edit_btn': 'Edit',
    'del_btn': 'Remove',
    'share_btn': 'Share',
    'up_btn': 'Up',
    'down_btn': 'Down',
    'jump_btn': 'Jump',
    'search_button': 'Search',
    'connect_btn': 'Load Family Tree',
    'btn_clear_all': 'Clear All',
    'btn_clear': 'Clear',
    'btn_close': 'Close',
}

def clean_label(text):
    if not text:
        return ''
    text = html.unescape(text)
    text = re.sub(r'_(?=\w)', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('…', '...').strip()
    return text

def classify_action(lbl):
    l = lbl.lower().strip()
    if not l:
        return 'Unknown'
    if l in POSITIVE_KEYWORDS:
        return 'Positive'
    if l in NEGATIVE_KEYWORDS:
        return 'Negative'
    
    for kw in ['close without saving', 'clear all', 'close window', 'abandon changes', 'remove object', 'undo']:
        if kw in l:
            return 'Negative'
    for kw in ['install all addons', 'install addon', 'keep reference', 'select all', 'import selected', 'merge selected', 'apply selected', 'jump to']:
        if kw in l:
            return 'Positive'
    for kw in ['cancel', 'close', 'clear', 'delete', 'remove', 'abort', 'reject']:
        if re.search(rf'\b{kw}\b', l):
            return 'Negative'
    if re.search(r'\bno\b', l):
        return 'Negative'
    for kw in ['ok', 'yes', 'save', 'load', 'confirm', 'accept', 'apply', 'add', 'next', 'forward', 'run', 'import', 'execute', 'merge', 'install', 'connect', 'login', 'repair', 'reorder']:
        if re.search(rf'\b{kw}\b', l):
            return 'Positive'
    return 'Unknown'

def check_windows_adherence(btn_names):
    if not btn_names:
        return 'N/A'
    if len(btn_names) == 1:
        # A single Close or OK button at the end adheres to both Windows and Linux
        act = classify_action(btn_names[0])
        return 'Yes' if act in ['Positive', 'Negative'] else 'N/A'

    actions = [classify_action(b) for b in btn_names]
    pos_indices = [i for i, a in enumerate(actions) if a == 'Positive']
    neg_indices = [i for i, a in enumerate(actions) if a == 'Negative']
=======
    "GtkButton",
    "GtkToggleButton",
    "GtkColorButton",
    "GtkToolButton",
    "GtkToggleToolButton",
    "GtkMenuButton",
}

POSITIVE_KEYWORDS = {
    "ok",
    "yes",
    "save",
    "load",
    "confirm",
    "accept",
    "apply",
    "add",
    "forward",
    "next",
    "import",
    "execute",
    "run",
    "merge",
    "jump",
    "jump to",
    "select",
    "login",
    "connect",
    "continue",
    "retag",
    "check",
    "reorder",
    "convert",
    "repair",
    "archive",
    "test",
    "install",
    "install addon",
    "install all addons",
    "keep reference",
    "select all",
    "import selected",
    "merge selected",
    "apply selected",
    "export",
    "report",
    "calculate previews",
    "file bug report",
    "copy to clipboard",
    "change order",
}

NEGATIVE_KEYWORDS = {
    "cancel",
    "close",
    "no",
    "abort",
    "reject",
    "back",
    "previous",
    "delete",
    "remove",
    "stop",
    "clear",
    "reset",
    "dismiss",
    "close without saving",
    "clear all",
    "close window",
    "abandon changes",
    "remove object",
    "undo",
}

ICON_TO_LABEL = {
    "list-add": "Add",
    "gtk-add": "Add",
    "list-remove": "Remove",
    "gtk-remove": "Remove",
    "gtk-delete": "Delete",
    "gtk-edit": "Edit",
    "document-edit": "Edit",
    "gtk-index": "Share",
    "go-up": "Up",
    "go-down": "Down",
    "go-jump": "Jump",
    "go-previous": "Previous",
    "go-next": "Next",
    "edit-clear": "Clear",
    "document-revert": "Revert",
    "document-new": "New",
    "view-refresh": "Refresh",
    "help-browser": "Help",
    "gtk-help": "Help",
    "gtk-close": "Close",
    "gtk-cancel": "Cancel",
    "gtk-ok": "OK",
    "gtk-save": "Save",
    "gtk-open": "Open",
    "gtk-apply": "Apply",
}

ID_TO_LABEL = {
    "ok": "OK",
    "okbutton": "OK",
    "ok_button": "OK",
    "cancel": "Cancel",
    "cancelbutton": "Cancel",
    "cancel_button": "Cancel",
    "cancel_btn": "Close Window",
    "close": "Close",
    "close_button": "Close",
    "close_btn": "Close",
    "help": "Help",
    "helpbutton": "Help",
    "help_button": "Help",
    "help_btn": "Help",
    "delete_button": "Delete",
    "apply_button": "Apply",
    "preview_button": "Calculate Previews",
    "advanced_button": "Change Order",
    "add_btn": "Add",
    "edit_btn": "Edit",
    "del_btn": "Remove",
    "share_btn": "Share",
    "up_btn": "Up",
    "down_btn": "Down",
    "jump_btn": "Jump",
    "search_button": "Search",
    "connect_btn": "Load Family Tree",
    "btn_clear_all": "Clear All",
    "btn_clear": "Clear",
    "btn_close": "Close",
}


def clean_label(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"_(?=\w)", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("…", "...").strip()
    return text


def classify_action(lbl):
    l = lbl.lower().strip()
    if not l:
        return "Unknown"
    if l in POSITIVE_KEYWORDS:
        return "Positive"
    if l in NEGATIVE_KEYWORDS:
        return "Negative"

    for kw in [
        "close without saving",
        "clear all",
        "close window",
        "abandon changes",
        "remove object",
        "undo",
    ]:
        if kw in l:
            return "Negative"
    for kw in [
        "install all addons",
        "install addon",
        "keep reference",
        "select all",
        "import selected",
        "merge selected",
        "apply selected",
        "jump to",
    ]:
        if kw in l:
            return "Positive"
    for kw in ["cancel", "close", "clear", "delete", "remove", "abort", "reject"]:
        if re.search(rf"\b{kw}\b", l):
            return "Negative"
    if re.search(r"\bno\b", l):
        return "Negative"
    for kw in [
        "ok",
        "yes",
        "save",
        "load",
        "confirm",
        "accept",
        "apply",
        "add",
        "next",
        "forward",
        "run",
        "import",
        "execute",
        "merge",
        "install",
        "connect",
        "login",
        "repair",
        "reorder",
    ]:
        if re.search(rf"\b{kw}\b", l):
            return "Positive"
    return "Unknown"


def check_windows_adherence(btn_names):
    if not btn_names:
        return "N/A"
    if len(btn_names) == 1:
        # A single Close or OK button at the end adheres to both Windows and Linux
        act = classify_action(btn_names[0])
        return "Yes" if act in ["Positive", "Negative"] else "N/A"

    actions = [classify_action(b) for b in btn_names]
    pos_indices = [i for i, a in enumerate(actions) if a == "Positive"]
    neg_indices = [i for i, a in enumerate(actions) if a == "Negative"]
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197

    if pos_indices and neg_indices:
        first_pos = min(pos_indices)
        first_neg = min(neg_indices)
        # Windows standard: Positive on the left of Negative ([ OK ] [ Cancel ])
        if first_pos < first_neg:
<<<<<<< HEAD
            return 'Yes'
        else:
            return 'No'
    elif neg_indices and not pos_indices:
        return 'Yes'
    elif pos_indices and not neg_indices:
        return 'Yes'
    return 'N/A'

def extract_glade_dialogs():
    dialogs = []
    glade_files = sorted(glob.glob('gramps/**/*.glade', recursive=True) + glob.glob('gramps/**/*.ui', recursive=True))

    for gf in glade_files:
        norm_path = gf.replace('\\', '/')
=======
            return "Yes"
        else:
            return "No"
    elif neg_indices and not pos_indices:
        return "Yes"
    elif pos_indices and not neg_indices:
        return "Yes"
    return "N/A"


def extract_glade_dialogs():
    dialogs = []
    glade_files = sorted(
        glob.glob("gramps/**/*.glade", recursive=True)
        + glob.glob("gramps/**/*.ui", recursive=True)
    )

    for gf in glade_files:
        norm_path = gf.replace("\\", "/")
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
        try:
            tree = ET.parse(gf)
            root = tree.getroot()
        except Exception:
            continue

        parent_map = {c: p for p in root.iter() for c in p}

        top_windows = []
        for elem in root:
<<<<<<< HEAD
            if (elem.tag == 'object' and elem.attrib.get('class', '') in ['GtkDialog', 'GtkWindow']) or elem.tag == 'template':
                top_windows.append(elem)

        for win in top_windows:
            win_id = win.attrib.get('id', win.attrib.get('class', ''))
            win_title = ''
            for p in win.iter('property'):
                if p.attrib.get('name') == 'title':
                    win_title = p.text or ''
                    break

            dialog_name = win_title if (win_title and win_title not in ['window1', 'window2']) else win_id

            # Find action-widgets map if present
            action_map = {}
            for aw in win.iter('action-widget'):
                resp = aw.attrib.get('response', '')
                widget_id = aw.text.strip() if aw.text else ''
=======
            if (
                elem.tag == "object"
                and elem.attrib.get("class", "") in ["GtkDialog", "GtkWindow"]
            ) or elem.tag == "template":
                top_windows.append(elem)

        for win in top_windows:
            win_id = win.attrib.get("id", win.attrib.get("class", ""))
            win_title = ""
            for p in win.iter("property"):
                if p.attrib.get("name") == "title":
                    win_title = p.text or ""
                    break

            dialog_name = (
                win_title
                if (win_title and win_title not in ["window1", "window2"])
                else win_id
            )

            # Find action-widgets map if present
            action_map = {}
            for aw in win.iter("action-widget"):
                resp = aw.attrib.get("response", "")
                widget_id = aw.text.strip() if aw.text else ""
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
                if widget_id:
                    action_map[widget_id] = resp

            # Find primary action area button box
            action_bb = None
<<<<<<< HEAD
            for bb in win.iter('object'):
                if bb.attrib.get('class') == 'GtkButtonBox':
                    bb_parent = parent_map.get(bb)
                    if bb_parent is not None and bb_parent.attrib.get('internal-child') == 'action_area':
=======
            for bb in win.iter("object"):
                if bb.attrib.get("class") == "GtkButtonBox":
                    bb_parent = parent_map.get(bb)
                    if (
                        bb_parent is not None
                        and bb_parent.attrib.get("internal-child") == "action_area"
                    ):
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
                        action_bb = bb
                        break
                    elif action_bb is None:
                        # Fallback to horizontal buttonbox
<<<<<<< HEAD
                        ori = 'horizontal'
                        for p in bb.iter('property'):
                            if p.attrib.get('name') == 'orientation':
                                ori = p.text or 'horizontal'
                        if ori == 'horizontal':
=======
                        ori = "horizontal"
                        for p in bb.iter("property"):
                            if p.attrib.get("name") == "orientation":
                                ori = p.text or "horizontal"
                        if ori == "horizontal":
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
                            action_bb = bb

            buttons = []
            if action_bb is not None:
                # Get buttons in action_bb
                bb_btns = []
<<<<<<< HEAD
                for b in action_bb.iter('object'):
                    if b.attrib.get('class', '') in BUTTON_CLASSES:
=======
                for b in action_bb.iter("object"):
                    if b.attrib.get("class", "") in BUTTON_CLASSES:
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
                        bb_btns.append(b)

                def get_pos(btn_elem):
                    child_elem = parent_map.get(btn_elem)
                    if child_elem is not None:
<<<<<<< HEAD
                        packing = child_elem.find('packing')
                        if packing is not None:
                            for p in packing.iter('property'):
                                if p.attrib.get('name') == 'position':
=======
                        packing = child_elem.find("packing")
                        if packing is not None:
                            for p in packing.iter("property"):
                                if p.attrib.get("name") == "position":
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
                                    return int(p.text) if p.text else 0
                    return 0

                bb_btns.sort(key=get_pos)

                for b in bb_btns:
<<<<<<< HEAD
                    b_id = b.attrib.get('id', '')
                    label = ''
                    for p in b.iter('property'):
                        if p.attrib.get('name') == 'label':
                            label = p.text or ''
                            break
                    if not label:
                        for p in b.iter('property'):
                            if p.attrib.get('name') in ['tooltip-text', 'tooltip_text']:
                                label = p.text or ''
                                break
                    if not label:
                        for img in b.iter('object'):
                            if img.attrib.get('class') == 'GtkImage':
                                for p in img.iter('property'):
                                    if p.attrib.get('name') in ['icon-name', 'icon_name', 'stock']:
                                        icon_val = p.text or ''
                                        label = ICON_TO_LABEL.get(icon_val, icon_val)
                                        break
                    if not label:
                        label = ID_TO_LABEL.get(b_id, '')

                    if not label and b_id in action_map:
                        resp = action_map[b_id]
                        if resp in ['-5', '-3']:
                            label = 'OK'
                        elif resp == '-6':
                            label = 'Cancel'
                        elif resp == '-7':
                            label = 'Close'
                        elif resp == '-8':
                            label = 'Save'
                        elif resp == '-9':
                            label = 'No'
                        elif resp == '-11':
                            label = 'Help'

                    if not label:
                        label = b_id or 'Button'
=======
                    b_id = b.attrib.get("id", "")
                    label = ""
                    for p in b.iter("property"):
                        if p.attrib.get("name") == "label":
                            label = p.text or ""
                            break
                    if not label:
                        for p in b.iter("property"):
                            if p.attrib.get("name") in ["tooltip-text", "tooltip_text"]:
                                label = p.text or ""
                                break
                    if not label:
                        for img in b.iter("object"):
                            if img.attrib.get("class") == "GtkImage":
                                for p in img.iter("property"):
                                    if p.attrib.get("name") in [
                                        "icon-name",
                                        "icon_name",
                                        "stock",
                                    ]:
                                        icon_val = p.text or ""
                                        label = ICON_TO_LABEL.get(icon_val, icon_val)
                                        break
                    if not label:
                        label = ID_TO_LABEL.get(b_id, "")

                    if not label and b_id in action_map:
                        resp = action_map[b_id]
                        if resp in ["-5", "-3"]:
                            label = "OK"
                        elif resp == "-6":
                            label = "Cancel"
                        elif resp == "-7":
                            label = "Close"
                        elif resp == "-8":
                            label = "Save"
                        elif resp == "-9":
                            label = "No"
                        elif resp == "-11":
                            label = "Help"

                    if not label:
                        label = b_id or "Button"
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197

                    clean_lbl = clean_label(label)
                    buttons.append(clean_lbl)
            else:
                # Collect any buttons in window
<<<<<<< HEAD
                for b in win.iter('object'):
                    if b.attrib.get('class', '') in BUTTON_CLASSES:
                        b_id = b.attrib.get('id', '')
                        label = ''
                        for p in b.iter('property'):
                            if p.attrib.get('name') == 'label':
                                label = p.text or ''
=======
                for b in win.iter("object"):
                    if b.attrib.get("class", "") in BUTTON_CLASSES:
                        b_id = b.attrib.get("id", "")
                        label = ""
                        for p in b.iter("property"):
                            if p.attrib.get("name") == "label":
                                label = p.text or ""
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
                                break
                        if not label:
                            label = ID_TO_LABEL.get(b_id, b_id)
                        buttons.append(clean_label(label))

            if buttons:
                adheres = check_windows_adherence(buttons)
<<<<<<< HEAD
                dialogs.append({
                    'Dialog Name': dialog_name,
                    'Filename': norm_path,
                    'Button Names': ':'.join(buttons),
                    'Adheres to Windows Standard': adheres,
                    'Order Changes on Linux': 'No'
                })

    return dialogs

=======
                dialogs.append(
                    {
                        "Dialog Name": dialog_name,
                        "Filename": norm_path,
                        "Button Names": ":".join(buttons),
                        "Adheres to Windows Standard": adheres,
                        "Order Changes on Linux": "No",
                    }
                )

    return dialogs


>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
def extract_python_dialogs():
    # Curated list of all dialogs constructed programmatically in Python
    raw_list = [
        # (Dialog Name, Filename, [Buttons in left-to-right order])
<<<<<<< HEAD
        ('ErrorDialog', 'gramps/gui/dialog.py', ['Close']),
        ('RunDatabaseRepair', 'gramps/gui/dialog.py', ['Close']),
        ('DBErrorDialog', 'gramps/gui/dialog.py', ['Close']),
        ('WarningDialog', 'gramps/gui/dialog.py', ['Close']),
        ('OkDialog', 'gramps/gui/dialog.py', ['Close']),
        ('GenderDialog', 'gramps/gui/editors/editperson.py', ['Male', 'Female', 'Other', 'Unknown']),
        ('EditTagList', 'gramps/gui/editors/edittaglist.py', ['Help', 'Cancel', 'OK']),
        ('DisplayNameEditor', 'gramps/gui/configure.py', ['Close']),
        ('ConfigureDialog', 'gramps/gui/configure.py', ['Close']),
        ('Database Path Chooser', 'gramps/gui/configure.py', ['Cancel', 'Apply']),
        ('GrampsPreferences', 'gramps/gui/configure.py', ['Help', 'Cancel', 'OK']),
        ('GrampsLoginDialog', 'gramps/gui/dbloader.py', ['Cancel', 'Login']),
        ('GrampsImportFileDialog', 'gramps/gui/dbloader.py', ['Cancel', 'Import']),
        ('Information', 'gramps/gui/dbman.py', ['OK']),
        ('UndoHistory', 'gramps/gui/undohistory.py', ['Help', 'Undo', 'Redo', 'Clear', 'Close']),
        ('QuickBackup', 'gramps/gui/viewmanager.py', ['Close', 'OK']),
        ('Media Path Chooser', 'gramps/gui/viewmanager.py', ['Cancel', 'Apply']),
        ('FamilySearch Notification', 'gramps/gui/fs/actions.py', ['OK']),
        ('FamilySearch Error', 'gramps/gui/fs/actions.py', ['OK']),
        ('Link FamilySearch ID', 'gramps/gui/fs/actions.py', ['Cancel', 'OK']),
        ('Import FamilySearch Persons', 'gramps/gui/fs/actions.py', ['Cancel', 'Import selected']),
        ('Bulk Import Relatives', 'gramps/gui/fs/actions.py', ['Cancel', 'Import']),
        ('FamilySearch Match', 'gramps/gui/fs/actions.py', ['Cancel', 'Continue']),
        ('FamilySearch Tags', 'gramps/gui/fs/actions.py', ['Close', 'Retag all (Linked/NotLinked)']),
        ('FamilySearch Source Image', 'gramps/gui/fs/fs_source_image.py', ['Close']),
        ('FamilySearch Session', 'gramps/gui/fs/session.py', ['Cancel', 'Continue']),
        ('Sync to FamilySearch', 'gramps/gui/fs/sync_directions.py', ['Cancel', 'Apply Selected']),
        ('Export to FamilySearch', 'gramps/gui/fs/sync_directions.py', ['Cancel', 'Export']),
        ('FamilySearch Sources', 'gramps/gui/fs/person/mixins/sources_dialog.py', ['Cancel', 'Import selected']),
        ('Manage Images', 'gramps/gui/fs/person/mixins/sources_dialog.py', ['Close']),
        ('FamilySearch Compare', 'gramps/gui/fs/person/mixins/compare_gtk.py', ['Merge selected', 'Refresh', 'Import sources...', 'Close']),
        ('FamilySearch Tools', 'gramps/gui/fs/tools_window.py', ['Link FamilySearch ID', 'Import Parents', 'Import Spouse', 'Import Children', 'Clear Cache', 'Bulk Import Relatives', 'Tags...', 'Compare', 'Sync from FamilySearch', 'Sync to FamilySearch...', 'Export to FamilySearch']),
        ('ErrorView', 'gramps/gui/logger/_errorview.py', ['Cancel', 'Report', 'Help']),
        ('ErrorReportAssistant', 'gramps/gui/logger/_errorreportassistant.py', ['Reset', 'Clear', 'File bug report', 'Copy to clipboard']),
        ('LastNameDialog', 'gramps/gui/plug/_guioptions.py', ['Cancel', 'OK']),
        ('Option File Chooser', 'gramps/gui/plug/_guioptions.py', ['Cancel', 'Open']),
        ('PluginStatus', 'gramps/gui/plug/_windows.py', ['Refresh', 'Close', 'Help']),
        ('Addon Project Dialog', 'gramps/gui/plug/_windows.py', ['Cancel', 'OK']),
        ('PluginTrace', 'gramps/gui/plug/_windows.py', ['Close']),
        ('Install Addon File Chooser', 'gramps/gui/plug/_windows.py', ['Cancel', 'Open']),
        ('Plugin Dialog', 'gramps/gui/plug/_windows.py', ['Close']),
        ('ToolManagedWindow', 'gramps/gui/plug/_windows.py', ['Close', 'Execute']),
        ('DisplayBuf', 'gramps/gui/plug/quick/_textbufdoc.py', ['Close']),
        ('Report File Chooser', 'gramps/gui/plug/report/_fileentry.py', ['Cancel', 'Open']),
        ('ReportDialog', 'gramps/gui/plug/report/_reportdialog.py', ['Help', 'Cancel', 'OK']),
        ('BookmarksDialog', 'gramps/gui/views/bookmarks.py', ['Close', 'Help']),
        ('Export View File Chooser', 'gramps/gui/views/listview.py', ['Cancel', 'Save']),
        ('Jump to Dialog', 'gramps/gui/views/navigationview.py', ['Cancel', 'Jump to']),
        ('OrganizeTagsDialog', 'gramps/gui/views/tags.py', ['Close', 'Help']),
        ('Edit Tag Dialog', 'gramps/gui/views/tags.py', ['Help', 'Cancel', 'OK']),
        ('Add Gramplet Dialog', 'gramps/gui/widgets/grampletbar.py', ['Close', 'Help']),
        ('Add Gramplet Pane Dialog', 'gramps/gui/widgets/grampletpane.py', ['Close', 'Help']),
        ('GtkProgressDialog', 'gramps/gui/widgets/progressdialog.py', ['Cancel']),
        ('KML Export File Chooser', 'gramps/plugins/lib/maps/geography.py', ['Cancel', 'Apply']),
        ('Geography Directory Chooser', 'gramps/plugins/lib/maps/geography.py', ['Cancel', 'Apply']),
        ('PlaceSelection', 'gramps/plugins/lib/maps/placeselection.py', ['Close']),
        ('FavoriteViews', 'gramps/plugins/sidebar/favoritessidebar.py', ['Help', 'Select All', 'Clear All', 'Close']),
        ('Check Image File Chooser', 'gramps/plugins/tool/check.py', ['Cancel', 'OK']),
        ('CitationFixDialog', 'gramps/plugins/tool/citationsfixdialog.py', ['Close']),
        ('DumpGenderStats', 'gramps/plugins/tool/dumpgenderstats.py', ['Close']),
        ('Event Comparison Save File Chooser', 'gramps/plugins/tool/eventcmp.py', ['Cancel', 'Save']),
        ('GWizardCitationFix Dialog', 'gramps/plugins/tool/gwizardcitationfix.py', ['Close']),
        ('MediaManager', 'gramps/plugins/tool/mediamanager.py', ['Help']),
        ('PatchNames Winprefix', 'gramps/plugins/tool/patchnames.py', ['OK']),
        ('PopulateSources Dialog', 'gramps/plugins/tool/populatesources.py', ['Cancel', 'OK']),
        ('RepoMergeDialog', 'gramps/plugins/tool/repomergedialog.py', ['Close']),
        ('SourceFixDialog', 'gramps/plugins/tool/sourcesfixdialog.py', ['Close']),
        ('TestCaseGenerator Dialog', 'gramps/plugins/tool/testcasegenerator.py', ['Cancel', 'OK', 'Help']),
        ('FanChart2WayView MessageDialog', 'gramps/plugins/view/fanchart2wayview.py', ['Close']),
        ('FanChartDescView MessageDialog', 'gramps/plugins/view/fanchartdescview.py', ['Close']),
        ('FanChartView MessageDialog', 'gramps/plugins/view/fanchartview.py', ['Close']),
=======
        ("ErrorDialog", "gramps/gui/dialog.py", ["Close"]),
        ("RunDatabaseRepair", "gramps/gui/dialog.py", ["Close"]),
        ("DBErrorDialog", "gramps/gui/dialog.py", ["Close"]),
        ("WarningDialog", "gramps/gui/dialog.py", ["Close"]),
        ("OkDialog", "gramps/gui/dialog.py", ["Close"]),
        (
            "GenderDialog",
            "gramps/gui/editors/editperson.py",
            ["Male", "Female", "Other", "Unknown"],
        ),
        ("EditTagList", "gramps/gui/editors/edittaglist.py", ["Help", "Cancel", "OK"]),
        ("DisplayNameEditor", "gramps/gui/configure.py", ["Close"]),
        ("ConfigureDialog", "gramps/gui/configure.py", ["Close"]),
        ("Database Path Chooser", "gramps/gui/configure.py", ["Cancel", "Apply"]),
        ("GrampsPreferences", "gramps/gui/configure.py", ["Help", "Cancel", "OK"]),
        ("GrampsLoginDialog", "gramps/gui/dbloader.py", ["Cancel", "Login"]),
        ("GrampsImportFileDialog", "gramps/gui/dbloader.py", ["Cancel", "Import"]),
        ("Information", "gramps/gui/dbman.py", ["OK"]),
        (
            "UndoHistory",
            "gramps/gui/undohistory.py",
            ["Help", "Undo", "Redo", "Clear", "Close"],
        ),
        ("QuickBackup", "gramps/gui/viewmanager.py", ["Close", "OK"]),
        ("Media Path Chooser", "gramps/gui/viewmanager.py", ["Cancel", "Apply"]),
        ("FamilySearch Notification", "gramps/gui/fs/actions.py", ["OK"]),
        ("FamilySearch Error", "gramps/gui/fs/actions.py", ["OK"]),
        ("Link FamilySearch ID", "gramps/gui/fs/actions.py", ["Cancel", "OK"]),
        (
            "Import FamilySearch Persons",
            "gramps/gui/fs/actions.py",
            ["Cancel", "Import selected"],
        ),
        ("Bulk Import Relatives", "gramps/gui/fs/actions.py", ["Cancel", "Import"]),
        ("FamilySearch Match", "gramps/gui/fs/actions.py", ["Cancel", "Continue"]),
        (
            "FamilySearch Tags",
            "gramps/gui/fs/actions.py",
            ["Close", "Retag all (Linked/NotLinked)"],
        ),
        ("FamilySearch Source Image", "gramps/gui/fs/fs_source_image.py", ["Close"]),
        ("FamilySearch Session", "gramps/gui/fs/session.py", ["Cancel", "Continue"]),
        (
            "Sync to FamilySearch",
            "gramps/gui/fs/sync_directions.py",
            ["Cancel", "Apply Selected"],
        ),
        (
            "Export to FamilySearch",
            "gramps/gui/fs/sync_directions.py",
            ["Cancel", "Export"],
        ),
        (
            "FamilySearch Sources",
            "gramps/gui/fs/person/mixins/sources_dialog.py",
            ["Cancel", "Import selected"],
        ),
        ("Manage Images", "gramps/gui/fs/person/mixins/sources_dialog.py", ["Close"]),
        (
            "FamilySearch Compare",
            "gramps/gui/fs/person/mixins/compare_gtk.py",
            ["Merge selected", "Refresh", "Import sources...", "Close"],
        ),
        (
            "FamilySearch Tools",
            "gramps/gui/fs/tools_window.py",
            [
                "Link FamilySearch ID",
                "Import Parents",
                "Import Spouse",
                "Import Children",
                "Clear Cache",
                "Bulk Import Relatives",
                "Tags...",
                "Compare",
                "Sync from FamilySearch",
                "Sync to FamilySearch...",
                "Export to FamilySearch",
            ],
        ),
        ("ErrorView", "gramps/gui/logger/_errorview.py", ["Cancel", "Report", "Help"]),
        (
            "ErrorReportAssistant",
            "gramps/gui/logger/_errorreportassistant.py",
            ["Reset", "Clear", "File bug report", "Copy to clipboard"],
        ),
        ("LastNameDialog", "gramps/gui/plug/_guioptions.py", ["Cancel", "OK"]),
        ("Option File Chooser", "gramps/gui/plug/_guioptions.py", ["Cancel", "Open"]),
        ("PluginStatus", "gramps/gui/plug/_windows.py", ["Refresh", "Close", "Help"]),
        ("Addon Project Dialog", "gramps/gui/plug/_windows.py", ["Cancel", "OK"]),
        ("PluginTrace", "gramps/gui/plug/_windows.py", ["Close"]),
        (
            "Install Addon File Chooser",
            "gramps/gui/plug/_windows.py",
            ["Cancel", "Open"],
        ),
        ("Plugin Dialog", "gramps/gui/plug/_windows.py", ["Close"]),
        ("ToolManagedWindow", "gramps/gui/plug/_windows.py", ["Close", "Execute"]),
        ("DisplayBuf", "gramps/gui/plug/quick/_textbufdoc.py", ["Close"]),
        (
            "Report File Chooser",
            "gramps/gui/plug/report/_fileentry.py",
            ["Cancel", "Open"],
        ),
        (
            "ReportDialog",
            "gramps/gui/plug/report/_reportdialog.py",
            ["Help", "Cancel", "OK"],
        ),
        ("BookmarksDialog", "gramps/gui/views/bookmarks.py", ["Close", "Help"]),
        (
            "Export View File Chooser",
            "gramps/gui/views/listview.py",
            ["Cancel", "Save"],
        ),
        ("Jump to Dialog", "gramps/gui/views/navigationview.py", ["Cancel", "Jump to"]),
        ("OrganizeTagsDialog", "gramps/gui/views/tags.py", ["Close", "Help"]),
        ("Edit Tag Dialog", "gramps/gui/views/tags.py", ["Help", "Cancel", "OK"]),
        ("Add Gramplet Dialog", "gramps/gui/widgets/grampletbar.py", ["Close", "Help"]),
        (
            "Add Gramplet Pane Dialog",
            "gramps/gui/widgets/grampletpane.py",
            ["Close", "Help"],
        ),
        ("GtkProgressDialog", "gramps/gui/widgets/progressdialog.py", ["Cancel"]),
        (
            "KML Export File Chooser",
            "gramps/plugins/lib/maps/geography.py",
            ["Cancel", "Apply"],
        ),
        (
            "Geography Directory Chooser",
            "gramps/plugins/lib/maps/geography.py",
            ["Cancel", "Apply"],
        ),
        ("PlaceSelection", "gramps/plugins/lib/maps/placeselection.py", ["Close"]),
        (
            "FavoriteViews",
            "gramps/plugins/sidebar/favoritessidebar.py",
            ["Help", "Select All", "Clear All", "Close"],
        ),
        ("Check Image File Chooser", "gramps/plugins/tool/check.py", ["Cancel", "OK"]),
        ("CitationFixDialog", "gramps/plugins/tool/citationsfixdialog.py", ["Close"]),
        ("DumpGenderStats", "gramps/plugins/tool/dumpgenderstats.py", ["Close"]),
        (
            "Event Comparison Save File Chooser",
            "gramps/plugins/tool/eventcmp.py",
            ["Cancel", "Save"],
        ),
        (
            "GWizardCitationFix Dialog",
            "gramps/plugins/tool/gwizardcitationfix.py",
            ["Close"],
        ),
        ("MediaManager", "gramps/plugins/tool/mediamanager.py", ["Help"]),
        ("PatchNames Winprefix", "gramps/plugins/tool/patchnames.py", ["OK"]),
        (
            "PopulateSources Dialog",
            "gramps/plugins/tool/populatesources.py",
            ["Cancel", "OK"],
        ),
        ("RepoMergeDialog", "gramps/plugins/tool/repomergedialog.py", ["Close"]),
        ("SourceFixDialog", "gramps/plugins/tool/sourcesfixdialog.py", ["Close"]),
        (
            "TestCaseGenerator Dialog",
            "gramps/plugins/tool/testcasegenerator.py",
            ["Cancel", "OK", "Help"],
        ),
        (
            "FanChart2WayView MessageDialog",
            "gramps/plugins/view/fanchart2wayview.py",
            ["Close"],
        ),
        (
            "FanChartDescView MessageDialog",
            "gramps/plugins/view/fanchartdescview.py",
            ["Close"],
        ),
        (
            "FanChartView MessageDialog",
            "gramps/plugins/view/fanchartview.py",
            ["Close"],
        ),
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
    ]

    dialogs = []
    for dname, fname, btns in raw_list:
        adheres = check_windows_adherence(btns)
<<<<<<< HEAD
        dialogs.append({
            'Dialog Name': dname,
            'Filename': fname,
            'Button Names': ':'.join(btns),
            'Adheres to Windows Standard': adheres,
            'Order Changes on Linux': 'No'
        })

    return dialogs

=======
        dialogs.append(
            {
                "Dialog Name": dname,
                "Filename": fname,
                "Button Names": ":".join(btns),
                "Adheres to Windows Standard": adheres,
                "Order Changes on Linux": "No",
            }
        )

    return dialogs


>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
def main():
    glade_dlgs = extract_glade_dialogs()
    py_dlgs = extract_python_dialogs()
    all_dlgs = glade_dlgs + py_dlgs

<<<<<<< HEAD
    out_file = 'DialogPlacement_Windows.csv'
    fieldnames = ['Dialog Name', 'Filename', 'Button Names', 'Adheres to Windows Standard', 'Order Changes on Linux']

    with open(out_file, 'w', newline='', encoding='utf-8') as f:
=======
    out_file = "DialogPlacement_Windows.csv"
    fieldnames = [
        "Dialog Name",
        "Filename",
        "Button Names",
        "Adheres to Windows Standard",
        "Order Changes on Linux",
    ]

    with open(out_file, "w", newline="", encoding="utf-8") as f:
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in all_dlgs:
            writer.writerow(d)

<<<<<<< HEAD
    print(f"Generated {out_file} with {len(all_dlgs)} dialogs/windows (Glade: {len(glade_dlgs)}, Python: {len(py_dlgs)})")

if __name__ == '__main__':
=======
    print(
        f"Generated {out_file} with {len(all_dlgs)} dialogs/windows (Glade: {len(glade_dlgs)}, Python: {len(py_dlgs)})"
    )


if __name__ == "__main__":
>>>>>>> 82752bd77ef1bdfc244c9164d1d717f331e71197
    main()
