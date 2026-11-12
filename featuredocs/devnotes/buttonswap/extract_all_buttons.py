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
    'GtkButton', 'GtkToggleButton', 'GtkColorButton',
    'GtkToolButton', 'GtkToggleToolButton', 'GtkMenuButton'
}

# Verbs explicitly designated as positive actions (Commitment & Selection)
POSITIVE_VERBS = {'set', 'select', 'tag', 'invoke'}

POSITIVE_KEYWORDS = {
    'ok', 'yes', 'save', 'load', 'confirm', 'accept', 'apply', 'add',
    'forward', 'next', 'import', 'execute', 'run', 'merge', 'jump',
    'jump to', 'login', 'connect', 'continue', 'retag', 'check',
    'reorder', 'convert', 'repair', 'archive', 'test', 'install',
    'install addon', 'install all addons', 'keep reference', 'export',
    'report', 'calculate previews', 'file bug report', 'copy to clipboard',
    'change order', 'new', 'clone', 'help', 'perform'
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
    'multsurnamebtn': 'Multiple Surnames',
    'editnamebtn': 'Edit Name',
    'tag_button': 'Tag',
    'private': 'Set person as private data',
    'date_stat': 'Date Status',
    'new_btn': 'New',
    'info_btn': 'Info',
    'remove_btn': 'Delete',
    'rename_btn': 'Rename',
    'convert_btn': 'Convert',
    'repair_btn': 'Repair',
    'rcs_btn': 'Archive',
    'btn_link': 'Link FamilySearch ID',
    'btn_cmp': 'Compare',
    'btn_sync': 'Sync from FamilySearch',
    'btn_sync_to': 'Sync to FamilySearch...',
    'btn_export_basic': 'Export to FamilySearch',
    'btn_bulk_import': 'Bulk Import Relatives',
    'btn_tags': 'Tags...',
    'btn_clear_cache': 'Clear Cache',
    'btn_imp_par': 'Import Parents',
    'btn_imp_spo': 'Import Spouse',
    'btn_imp_chi': 'Import Children',
}

def clean_label(text):
    if not text:
        return ''
    text = html.unescape(text)
    text = re.sub(r'_(?=\w)', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('…', '...').strip()
    return text

def classify_action(label_clean):
    lbl = label_clean.lower().strip()
    if not lbl:
        return 'Unknown'

    # Help is explicitly Positive per user instruction
    if 'help' in lbl:
        return 'Positive'

    # Deletions / Removals / Cancellations take precedence
    if any(lbl.startswith(p) for p in ['delete', 'remove', 'cancel', 'close', 'clear', 'abort', 'reject', 'undo', 'reset']):
        return 'Negative'
    for kw in ['delete the selected', 'remove currently selected', 'close without saving', 'clear all', 'close window', 'abandon changes', 'remove object']:
        if kw in lbl:
            return 'Negative'
    if re.search(r'\bno\b', lbl):
        return 'Negative'

    # Commitment Actions (Set, Tag, Invoke) and Selection Actions (Select) act exactly like OK (Positive)
    for v in POSITIVE_VERBS:
        if re.search(rf'\b{v}\b', lbl):
            return 'Positive'
    if any(k in lbl for k in ['selectsource', 'adddelsource', 'adddelperson', 'adddelmatchtest', 'adddelsubjecttest', 'shareplace']):
        return 'Positive'

    # Edits without set/select/tag/invoke are Unknown
    if lbl.startswith('edit'):
        return 'Unknown'

    if lbl in POSITIVE_KEYWORDS:
        return 'Positive'

    for kw in ['ok', 'yes', 'save', 'load', 'confirm', 'accept', 'apply', 'add', 'next', 'forward', 'run', 'import', 'execute', 'merge', 'install', 'connect', 'login', 'repair', 'reorder', 'new', 'clone', 'test']:
        if re.search(rf'\b{kw}\b', lbl):
            return 'Positive'

    return 'Unknown'

def extract_glade():
    results = []
    glade_files = sorted(glob.glob('gramps/**/*.glade', recursive=True) + glob.glob('gramps/**/*.ui', recursive=True))

    for gf in glade_files:
        norm_path = gf.replace('\\', '/')
        try:
            tree = ET.parse(gf)
            root = tree.getroot()
        except Exception:
            continue

        parent_map = {c: p for p in root.iter() for c in p}

        top_windows = []
        for elem in root:
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

            action_map = {}
            for aw in win.iter('action-widget'):
                resp = aw.attrib.get('response', '')
                widget_id = aw.text.strip() if aw.text else ''
                if widget_id:
                    action_map[widget_id] = resp

            btn_boxes = {}
            for bb in win.iter('object'):
                if bb.attrib.get('class') == 'GtkButtonBox':
                    btn_boxes[bb] = []

            all_btns = []
            for b in win.iter('object'):
                if b.attrib.get('class', '') in BUTTON_CLASSES:
                    all_btns.append(b)

            for b in all_btns:
                curr = b
                while curr in parent_map:
                    curr = parent_map[curr]
                    if curr in btn_boxes:
                        btn_boxes[curr].append(b)
                        break

            for bb, bb_btns in btn_boxes.items():
                if not bb_btns:
                    continue

                def get_pos(btn_elem):
                    child_elem = parent_map.get(btn_elem)
                    if child_elem is not None:
                        packing = child_elem.find('packing')
                        if packing is not None:
                            for p in packing.iter('property'):
                                if p.attrib.get('name') == 'position':
                                    return int(p.text) if p.text else 0
                    return 0

                bb_btns.sort(key=get_pos)

                ori = 'horizontal'
                for p in bb.iter('property'):
                    if p.attrib.get('name') == 'orientation':
                        ori = p.text or 'horizontal'

                parsed_bb_btns = []
                for idx, b in enumerate(bb_btns):
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

                    clean_lbl = clean_label(label)
                    action = classify_action(clean_lbl)
                    parsed_bb_btns.append({
                        'elem': b,
                        'id': b_id,
                        'label': clean_lbl,
                        'action': action,
                        'index': idx
                    })

                num_bb = len(parsed_bb_btns)
                has_pos = any(b['action'] == 'Positive' for b in parsed_bb_btns)
                has_neg = any(b['action'] == 'Negative' for b in parsed_bb_btns)

                # Separate primary action pair from Help
                non_help_pos = [i for i, b in enumerate(parsed_bb_btns) if b['action'] == 'Positive' and 'help' not in b['label'].lower()]
                neg_indices = [i for i, b in enumerate(parsed_bb_btns) if b['action'] == 'Negative']

                for b in parsed_bb_btns:
                    if ori == 'vertical':
                        bb_child = parent_map.get(bb)
                        pos_in_parent = 0
                        if bb_child is not None:
                            packing = bb_child.find('packing')
                            if packing is not None:
                                for p in packing.iter('property'):
                                    if p.attrib.get('name') == 'position':
                                        pos_in_parent = int(p.text) if p.text else 0
                        placement = 'right' if pos_in_parent > 0 else 'left'
                        standard = 'Unknown'
                    else:
                        if num_bb == 1:
                            placement = 'right'
                        elif num_bb == 2:
                            placement = 'left' if b['index'] == 0 else 'right'
                        else:
                            if non_help_pos and neg_indices:
                                first_pos = min(non_help_pos)
                                if b['index'] < first_pos:
                                    placement = 'left'
                                else:
                                    placement = 'right'
                            else:
                                placement = 'left' if b['index'] < (num_bb / 2) else 'right'

                        # Determine standard adherence according to user notes
                        lbl_lower = b['label'].lower()
                        if 'help' in lbl_lower:
                            # GNOME / GTK Convention: Help placed on far left (pos 0)
                            # Windows Convention: Help placed on far right (last pos)
                            if b['index'] == 0:
                                standard = 'Linux'
                            elif b['index'] == num_bb - 1:
                                standard = 'Windows'
                            else:
                                standard = 'Unknown'
                        elif non_help_pos and neg_indices:
                            first_pos = min(non_help_pos)
                            first_neg = min(neg_indices)
                            if first_neg < first_pos:
                                standard = 'Linux' if b['action'] in ['Positive', 'Negative'] else 'Unknown'
                            else:
                                standard = 'Windows' if b['action'] in ['Positive', 'Negative'] else 'Unknown'
                        elif (has_pos and not has_neg) or (has_neg and not has_pos):
                            if num_bb == 1 and placement == 'right':
                                standard = 'Linux'
                            else:
                                standard = 'Unknown'
                        else:
                            standard = 'Unknown'

                    results.append({
                        'Button Name': b['label'],
                        'Dialog Name': dialog_name,
                        'Filename': norm_path,
                        'Action': b['action'],
                        'Default Placement': placement,
                        'Standard': standard
                    })

            for b in all_btns:
                in_bb = False
                for bb, bb_btns in btn_boxes.items():
                    if b in bb_btns:
                        in_bb = True
                        break
                if in_bb:
                    continue

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

                if not label:
                    label = b_id or 'Button'

                clean_lbl = clean_label(label)
                action = classify_action(clean_lbl)

                child_elem = parent_map.get(b)
                placement = 'right'

                if child_elem is not None:
                    packing = child_elem.find('packing')
                    if packing is not None:
                        left_attach = None
                        pos = None
                        pack_type = 'start'
                        for p in packing.iter('property'):
                            if p.attrib.get('name') == 'left-attach':
                                left_attach = int(p.text) if p.text else 0
                            elif p.attrib.get('name') == 'position':
                                pos = int(p.text) if p.text else 0
                            elif p.attrib.get('name') == 'pack-type':
                                pack_type = p.text or 'start'

                        if left_attach is not None:
                            placement = 'left' if left_attach == 0 else 'right'
                        elif pack_type == 'end':
                            placement = 'right'
                        elif pos is not None and pos == 0:
                            placement = 'left'
                        else:
                            placement = 'right'

                results.append({
                    'Button Name': clean_lbl,
                    'Dialog Name': dialog_name,
                    'Filename': norm_path,
                    'Action': action,
                    'Default Placement': placement,
                    'Standard': 'Unknown'
                })

    return results

def extract_python():
    results = [
        # gramps/gui/columnorder.py
        {'Button Name': 'Apply', 'Dialog Name': 'ColumnOrderDialog', 'Filename': 'gramps/gui/columnorder.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/configure.py
        {'Button Name': 'Close', 'Dialog Name': 'DisplayNameEditor', 'Filename': 'gramps/gui/configure.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'ConfigureDialog', 'Filename': 'gramps/gui/configure.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Color Button', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Reset Color', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Help', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Windows'},
        {'Button Name': 'Restore to defaults', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Add', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Edit', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Remove', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Edit Format', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Edit Date Format', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Database Path Chooser', 'Filename': 'gramps/gui/configure.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Apply', 'Dialog Name': 'Database Path Chooser', 'Filename': 'gramps/gui/configure.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Reset Symbol', 'Dialog Name': 'GrampsPreferences', 'Filename': 'gramps/gui/configure.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/dbloader.py
        {'Button Name': 'Cancel', 'Dialog Name': 'GrampsLoginDialog', 'Filename': 'gramps/gui/dbloader.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Login', 'Dialog Name': 'GrampsLoginDialog', 'Filename': 'gramps/gui/dbloader.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Cancel', 'Dialog Name': 'GrampsImportFileDialog', 'Filename': 'gramps/gui/dbloader.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Import', 'Dialog Name': 'GrampsImportFileDialog', 'Filename': 'gramps/gui/dbloader.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/dbman.py
        {'Button Name': 'OK', 'Dialog Name': 'Information', 'Filename': 'gramps/gui/dbman.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/dialog.py
        {'Button Name': 'Close', 'Dialog Name': 'ErrorDialog', 'Filename': 'gramps/gui/dialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'RunDatabaseRepair', 'Filename': 'gramps/gui/dialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'DBErrorDialog', 'Filename': 'gramps/gui/dialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'WarningDialog', 'Filename': 'gramps/gui/dialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'OkDialog', 'Filename': 'gramps/gui/dialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/editors/displaytabs/backreflist.py
        {'Button Name': 'Edit', 'Dialog Name': 'BackRefList (Embedded Editor Tab)', 'Filename': 'gramps/gui/editors/displaytabs/backreflist.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/editors/displaytabs/buttontab.py
        {'Button Name': 'Add', 'Dialog Name': 'ButtonTab (Embedded Editor Tab)', 'Filename': 'gramps/gui/editors/displaytabs/buttontab.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Edit', 'Dialog Name': 'ButtonTab (Embedded Editor Tab)', 'Filename': 'gramps/gui/editors/displaytabs/buttontab.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Delete', 'Dialog Name': 'ButtonTab (Embedded Editor Tab)', 'Filename': 'gramps/gui/editors/displaytabs/buttontab.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Share', 'Dialog Name': 'ButtonTab (Embedded Editor Tab)', 'Filename': 'gramps/gui/editors/displaytabs/buttontab.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Up', 'Dialog Name': 'ButtonTab (Embedded Editor Tab)', 'Filename': 'gramps/gui/editors/displaytabs/buttontab.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Down', 'Dialog Name': 'ButtonTab (Embedded Editor Tab)', 'Filename': 'gramps/gui/editors/displaytabs/buttontab.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Jump', 'Dialog Name': 'ButtonTab (Embedded Editor Tab)', 'Filename': 'gramps/gui/editors/displaytabs/buttontab.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/editors/editperson.py
        {'Button Name': 'Male', 'Dialog Name': 'GenderDialog', 'Filename': 'gramps/gui/editors/editperson.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Female', 'Dialog Name': 'GenderDialog', 'Filename': 'gramps/gui/editors/editperson.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Other', 'Dialog Name': 'GenderDialog', 'Filename': 'gramps/gui/editors/editperson.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Unknown', 'Dialog Name': 'GenderDialog', 'Filename': 'gramps/gui/editors/editperson.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/editors/edittaglist.py
        {'Button Name': 'Help', 'Dialog Name': 'EditTagList', 'Filename': 'gramps/gui/editors/edittaglist.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Cancel', 'Dialog Name': 'EditTagList', 'Filename': 'gramps/gui/editors/edittaglist.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'EditTagList', 'Filename': 'gramps/gui/editors/edittaglist.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/editors/filtereditor.py
        {'Button Name': 'Add Rule Parameter', 'Dialog Name': 'EditRule Dialog', 'Filename': 'gramps/gui/editors/filtereditor.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/filters/_searchbar.py
        {'Button Name': 'Find', 'Dialog Name': 'Search Bar', 'Filename': 'gramps/gui/filters/_searchbar.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Clear', 'Dialog Name': 'Search Bar', 'Filename': 'gramps/gui/filters/_searchbar.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/filters/sidebar/_sidebarfilter.py
        {'Button Name': 'Find', 'Dialog Name': 'Sidebar Filter', 'Filename': 'gramps/gui/filters/sidebar/_sidebarfilter.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Clear', 'Dialog Name': 'Sidebar Filter', 'Filename': 'gramps/gui/filters/sidebar/_sidebarfilter.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Define filter', 'Dialog Name': 'Sidebar Filter', 'Filename': 'gramps/gui/filters/sidebar/_sidebarfilter.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Edit', 'Dialog Name': 'Sidebar Filter', 'Filename': 'gramps/gui/filters/sidebar/_sidebarfilter.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/fs/actions.py
        {'Button Name': 'OK', 'Dialog Name': 'FamilySearch Notification', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'FamilySearch Error', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Link FamilySearch ID', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'Link FamilySearch ID', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Import FamilySearch Persons', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Import selected', 'Dialog Name': 'Import FamilySearch Persons', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Select none', 'Dialog Name': 'Import FamilySearch Persons', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Select all new', 'Dialog Name': 'Import FamilySearch Persons', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Bulk Import Relatives', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Import', 'Dialog Name': 'Bulk Import Relatives', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Cancel', 'Dialog Name': 'FamilySearch Match', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Continue', 'Dialog Name': 'FamilySearch Match', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Search', 'Dialog Name': 'FamilySearch Match', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Close', 'Dialog Name': 'FamilySearch Tags', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Retag all (Linked/NotLinked)', 'Dialog Name': 'FamilySearch Tags', 'Filename': 'gramps/gui/fs/actions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/fs/fs_source_image.py
        {'Button Name': 'Close', 'Dialog Name': 'FamilySearch Source Image', 'Filename': 'gramps/gui/fs/fs_source_image.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Pick folder', 'Dialog Name': 'FamilySearch Source Image', 'Filename': 'gramps/gui/fs/fs_source_image.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Pick files', 'Dialog Name': 'FamilySearch Source Image', 'Filename': 'gramps/gui/fs/fs_source_image.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Open browser', 'Dialog Name': 'FamilySearch Source Image', 'Filename': 'gramps/gui/fs/fs_source_image.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Reload', 'Dialog Name': 'FamilySearch Source Image', 'Filename': 'gramps/gui/fs/fs_source_image.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/fs/person/mixins/compare_gtk.py
        {'Button Name': 'Merge selected', 'Dialog Name': 'FamilySearch Compare', 'Filename': 'gramps/gui/fs/person/mixins/compare_gtk.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Refresh', 'Dialog Name': 'FamilySearch Compare', 'Filename': 'gramps/gui/fs/person/mixins/compare_gtk.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Import sources...', 'Dialog Name': 'FamilySearch Compare', 'Filename': 'gramps/gui/fs/person/mixins/compare_gtk.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Close', 'Dialog Name': 'FamilySearch Compare', 'Filename': 'gramps/gui/fs/person/mixins/compare_gtk.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/fs/person/mixins/sources_dialog.py
        {'Button Name': 'Cancel', 'Dialog Name': 'FamilySearch Sources', 'Filename': 'gramps/gui/fs/person/mixins/sources_dialog.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Import selected', 'Dialog Name': 'FamilySearch Sources', 'Filename': 'gramps/gui/fs/person/mixins/sources_dialog.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'Manage Images', 'Filename': 'gramps/gui/fs/person/mixins/sources_dialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Add from source...', 'Dialog Name': 'Manage Images', 'Filename': 'gramps/gui/fs/person/mixins/sources_dialog.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Choose file...', 'Dialog Name': 'Manage Images', 'Filename': 'gramps/gui/fs/person/mixins/sources_dialog.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Rename files', 'Dialog Name': 'Manage Images', 'Filename': 'gramps/gui/fs/person/mixins/sources_dialog.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/fs/session.py
        {'Button Name': 'Cancel', 'Dialog Name': 'FamilySearch Session', 'Filename': 'gramps/gui/fs/session.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Continue', 'Dialog Name': 'FamilySearch Session', 'Filename': 'gramps/gui/fs/session.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/fs/sync_directions.py
        {'Button Name': 'Cancel', 'Dialog Name': 'Sync to FamilySearch', 'Filename': 'gramps/gui/fs/sync_directions.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Apply Selected', 'Dialog Name': 'Sync to FamilySearch', 'Filename': 'gramps/gui/fs/sync_directions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Select all', 'Dialog Name': 'Sync to FamilySearch', 'Filename': 'gramps/gui/fs/sync_directions.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Select none', 'Dialog Name': 'Sync to FamilySearch', 'Filename': 'gramps/gui/fs/sync_directions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Export to FamilySearch', 'Filename': 'gramps/gui/fs/sync_directions.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Export', 'Dialog Name': 'Export to FamilySearch', 'Filename': 'gramps/gui/fs/sync_directions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Select all missing', 'Dialog Name': 'Export to FamilySearch', 'Filename': 'gramps/gui/fs/sync_directions.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Select none', 'Dialog Name': 'Export to FamilySearch', 'Filename': 'gramps/gui/fs/sync_directions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/fs/tools_window.py
        {'Button Name': 'Link FamilySearch ID', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Import Parents', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Import Spouse', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Import Children', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Clear Cache', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Bulk Import Relatives', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Tags...', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Compare', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Sync from FamilySearch', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Sync to FamilySearch...', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Export to FamilySearch', 'Dialog Name': 'FamilySearch Tools', 'Filename': 'gramps/gui/fs/tools_window.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/logger/_errorreportassistant.py
        {'Button Name': 'Reset', 'Dialog Name': 'ErrorReportAssistant', 'Filename': 'gramps/gui/logger/_errorreportassistant.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Clear', 'Dialog Name': 'ErrorReportAssistant', 'Filename': 'gramps/gui/logger/_errorreportassistant.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'File bug report', 'Dialog Name': 'ErrorReportAssistant', 'Filename': 'gramps/gui/logger/_errorreportassistant.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Copy to clipboard', 'Dialog Name': 'ErrorReportAssistant', 'Filename': 'gramps/gui/logger/_errorreportassistant.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/logger/_errorview.py
        {'Button Name': 'Cancel', 'Dialog Name': 'ErrorView', 'Filename': 'gramps/gui/logger/_errorview.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Report', 'Dialog Name': 'ErrorView', 'Filename': 'gramps/gui/logger/_errorview.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Help', 'Dialog Name': 'ErrorView', 'Filename': 'gramps/gui/logger/_errorview.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Windows'},

        # gramps/gui/plug/_guioptions.py
        {'Button Name': 'Cancel', 'Dialog Name': 'LastNameDialog', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'LastNameDialog', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Select Person', 'Dialog Name': 'PersonOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Select Family', 'Dialog Name': 'FamilyOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Select Note', 'Dialog Name': 'NoteOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Select Media', 'Dialog Name': 'MediaOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Add Person', 'Dialog Name': 'PersonListOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Remove Person', 'Dialog Name': 'PersonListOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Add Place', 'Dialog Name': 'PlaceListOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Remove Place', 'Dialog Name': 'PlaceListOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Add Surname', 'Dialog Name': 'SurnameListOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Remove Surname', 'Dialog Name': 'SurnameListOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Browse Destination', 'Dialog Name': 'DestinationOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Option File Chooser', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Open', 'Dialog Name': 'Option File Chooser', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Style Editor', 'Dialog Name': 'StyleSheetOption', 'Filename': 'gramps/gui/plug/_guioptions.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/plug/_windows.py
        {'Button Name': 'Install', 'Dialog Name': 'AddonManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Wiki', 'Dialog Name': 'AddonManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Requires', 'Dialog Name': 'AddonManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Update', 'Dialog Name': 'AddonManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Refresh', 'Dialog Name': 'PluginStatus', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Close', 'Dialog Name': 'PluginStatus', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Help', 'Dialog Name': 'PluginStatus', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Windows'},
        {'Button Name': 'Clear', 'Dialog Name': 'PluginStatus', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Add Project', 'Dialog Name': 'AddonManager Settings', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Remove Project', 'Dialog Name': 'AddonManager Settings', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Move Up', 'Dialog Name': 'AddonManager Settings', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Move Down', 'Dialog Name': 'AddonManager Settings', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Restore Defaults', 'Dialog Name': 'AddonManager Settings', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Check for updated addons now', 'Dialog Name': 'AddonManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Addon Project Dialog', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'Addon Project Dialog', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'PluginTrace', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Info', 'Dialog Name': 'PluginManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Hide/Unhide', 'Dialog Name': 'PluginManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Edit', 'Dialog Name': 'PluginManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Load', 'Dialog Name': 'PluginManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Install Addon', 'Dialog Name': 'AddonManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Install All Addons', 'Dialog Name': 'AddonManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Refresh Addon List', 'Dialog Name': 'AddonManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Reload', 'Dialog Name': 'AddonManager', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Install Addon File Chooser', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Open', 'Dialog Name': 'Install Addon File Chooser', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'Plugin Dialog', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'ToolManagedWindow', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Execute', 'Dialog Name': 'ToolManagedWindow', 'Filename': 'gramps/gui/plug/_windows.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/plug/export/_exportoptions.py
        {'Button Name': 'Change order', 'Dialog Name': 'ExportOptions Dialog', 'Filename': 'gramps/gui/plug/export/_exportoptions.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Calculate Previews', 'Dialog Name': 'ExportOptions Dialog', 'Filename': 'gramps/gui/plug/export/_exportoptions.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Move Up', 'Dialog Name': 'ExportOptions Dialog', 'Filename': 'gramps/gui/plug/export/_exportoptions.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Move Down', 'Dialog Name': 'ExportOptions Dialog', 'Filename': 'gramps/gui/plug/export/_exportoptions.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/plug/quick/_textbufdoc.py
        {'Button Name': 'Close', 'Dialog Name': 'DisplayBuf', 'Filename': 'gramps/gui/plug/quick/_textbufdoc.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/plug/report/_fileentry.py
        {'Button Name': 'Browse File', 'Dialog Name': 'FileEntry', 'Filename': 'gramps/gui/plug/report/_fileentry.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Report File Chooser', 'Filename': 'gramps/gui/plug/report/_fileentry.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Open', 'Dialog Name': 'Report File Chooser', 'Filename': 'gramps/gui/plug/report/_fileentry.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/plug/report/_reportdialog.py
        {'Button Name': 'Help', 'Dialog Name': 'ReportDialog', 'Filename': 'gramps/gui/plug/report/_reportdialog.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Cancel', 'Dialog Name': 'ReportDialog', 'Filename': 'gramps/gui/plug/report/_reportdialog.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'ReportDialog', 'Filename': 'gramps/gui/plug/report/_reportdialog.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Style Editor', 'Dialog Name': 'ReportDialog', 'Filename': 'gramps/gui/plug/report/_reportdialog.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/undohistory.py
        {'Button Name': 'Help', 'Dialog Name': 'UndoHistory', 'Filename': 'gramps/gui/undohistory.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Undo', 'Dialog Name': 'UndoHistory', 'Filename': 'gramps/gui/undohistory.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Redo', 'Dialog Name': 'UndoHistory', 'Filename': 'gramps/gui/undohistory.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Clear', 'Dialog Name': 'UndoHistory', 'Filename': 'gramps/gui/undohistory.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'UndoHistory', 'Filename': 'gramps/gui/undohistory.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/utils.py
        {'Button Name': 'Cancel', 'Dialog Name': 'CLIDialog Progress Cancel', 'Filename': 'gramps/gui/utils.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'CLIDialog Message Area OK', 'Filename': 'gramps/gui/utils.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/viewmanager.py
        {'Button Name': 'Close', 'Dialog Name': 'QuickBackup', 'Filename': 'gramps/gui/viewmanager.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'QuickBackup', 'Filename': 'gramps/gui/viewmanager.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Open Path Chooser', 'Dialog Name': 'QuickBackup', 'Filename': 'gramps/gui/viewmanager.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Media Path Chooser', 'Filename': 'gramps/gui/viewmanager.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Apply', 'Dialog Name': 'Media Path Chooser', 'Filename': 'gramps/gui/viewmanager.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/views/bookmarks.py
        {'Button Name': 'Up', 'Dialog Name': 'BookmarksDialog', 'Filename': 'gramps/gui/views/bookmarks.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Down', 'Dialog Name': 'BookmarksDialog', 'Filename': 'gramps/gui/views/bookmarks.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Remove', 'Dialog Name': 'BookmarksDialog', 'Filename': 'gramps/gui/views/bookmarks.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Close', 'Dialog Name': 'BookmarksDialog', 'Filename': 'gramps/gui/views/bookmarks.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Help', 'Dialog Name': 'BookmarksDialog', 'Filename': 'gramps/gui/views/bookmarks.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Windows'},

        # gramps/gui/views/listview.py
        {'Button Name': 'Cancel', 'Dialog Name': 'Export View File Chooser', 'Filename': 'gramps/gui/views/listview.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Save', 'Dialog Name': 'Export View File Chooser', 'Filename': 'gramps/gui/views/listview.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/views/navigationview.py
        {'Button Name': 'Cancel', 'Dialog Name': 'Jump to Dialog', 'Filename': 'gramps/gui/views/navigationview.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Jump to', 'Dialog Name': 'Jump to Dialog', 'Filename': 'gramps/gui/views/navigationview.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/views/tags.py
        {'Button Name': 'Up', 'Dialog Name': 'OrganizeTagsDialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Down', 'Dialog Name': 'OrganizeTagsDialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Add', 'Dialog Name': 'OrganizeTagsDialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Edit', 'Dialog Name': 'OrganizeTagsDialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Remove', 'Dialog Name': 'OrganizeTagsDialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Close', 'Dialog Name': 'OrganizeTagsDialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Help', 'Dialog Name': 'OrganizeTagsDialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Windows'},
        {'Button Name': 'Tag Color', 'Dialog Name': 'Edit Tag Dialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Help', 'Dialog Name': 'Edit Tag Dialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Edit Tag Dialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'Edit Tag Dialog', 'Filename': 'gramps/gui/views/tags.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/widgets/dateentry.py & placeentry.py
        {'Button Name': 'Calendar Picker', 'Dialog Name': 'DateEntry Widget', 'Filename': 'gramps/gui/widgets/dateentry.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Place Picker', 'Dialog Name': 'PlaceEntry Widget', 'Filename': 'gramps/gui/widgets/placeentry.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/widgets/grampletbar.py
        {'Button Name': 'Gramplet Menu', 'Dialog Name': 'GrampletBar', 'Filename': 'gramps/gui/widgets/grampletbar.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Close', 'Dialog Name': 'Add Gramplet Dialog', 'Filename': 'gramps/gui/widgets/grampletbar.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Help', 'Dialog Name': 'Add Gramplet Dialog', 'Filename': 'gramps/gui/widgets/grampletbar.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Windows'},
        {'Button Name': 'Close Tab', 'Dialog Name': 'GrampletBar', 'Filename': 'gramps/gui/widgets/grampletbar.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/gui/widgets/grampletpane.py
        {'Button Name': 'Close', 'Dialog Name': 'Add Gramplet Pane Dialog', 'Filename': 'gramps/gui/widgets/grampletpane.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Help', 'Dialog Name': 'Add Gramplet Pane Dialog', 'Filename': 'gramps/gui/widgets/grampletpane.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Windows'},
        {'Button Name': 'Save', 'Dialog Name': 'Gramplet Pane Config', 'Filename': 'gramps/gui/widgets/grampletpane.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/widgets/progressdialog.py
        {'Button Name': 'Cancel', 'Dialog Name': 'GtkProgressDialog', 'Filename': 'gramps/gui/widgets/progressdialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/gui/widgets/statusbar.py
        {'Button Name': 'FamilySearch Status', 'Dialog Name': 'Statusbar', 'Filename': 'gramps/gui/widgets/statusbar.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Gramps Version', 'Dialog Name': 'Statusbar', 'Filename': 'gramps/gui/widgets/statusbar.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/plugins/gramplet/
        {'Button Name': 'Run', 'Dialog Name': 'AgeOnDateGramplet', 'Filename': 'gramps/plugins/gramplet/ageondategramplet.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Apply', 'Dialog Name': 'EvalGramplet', 'Filename': 'gramps/plugins/gramplet/eval.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Clear', 'Dialog Name': 'EvalGramplet', 'Filename': 'gramps/plugins/gramplet/eval.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Refresh', 'Dialog Name': 'LeakGramplet', 'Filename': 'gramps/plugins/gramplet/leak.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Previous', 'Dialog Name': 'NotesGramplet', 'Filename': 'gramps/plugins/gramplet/notes.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Next', 'Dialog Name': 'NotesGramplet', 'Filename': 'gramps/plugins/gramplet/notes.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Edit', 'Dialog Name': 'NotesGramplet', 'Filename': 'gramps/plugins/gramplet/notes.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Previous', 'Dialog Name': 'ToDoGramplet', 'Filename': 'gramps/plugins/gramplet/todo.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Next', 'Dialog Name': 'ToDoGramplet', 'Filename': 'gramps/plugins/gramplet/todo.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Edit', 'Dialog Name': 'ToDoGramplet', 'Filename': 'gramps/plugins/gramplet/todo.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'New', 'Dialog Name': 'ToDoGramplet', 'Filename': 'gramps/plugins/gramplet/todo.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/plugins/lib/maps/geography.py
        {'Button Name': 'Cancel', 'Dialog Name': 'KML Export File Chooser', 'Filename': 'gramps/plugins/lib/maps/geography.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Apply', 'Dialog Name': 'KML Export File Chooser', 'Filename': 'gramps/plugins/lib/maps/geography.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Cancel', 'Dialog Name': 'Geography Directory Chooser', 'Filename': 'gramps/plugins/lib/maps/geography.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Apply', 'Dialog Name': 'Geography Directory Chooser', 'Filename': 'gramps/plugins/lib/maps/geography.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/plugins/lib/maps/placeselection.py
        {'Button Name': 'Close', 'Dialog Name': 'PlaceSelection', 'Filename': 'gramps/plugins/lib/maps/placeselection.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/plugins/sidebar/
        {'Button Name': 'Category Toggle', 'Dialog Name': 'CategorySidebar', 'Filename': 'gramps/plugins/sidebar/categorysidebar.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Dropdown Toggle', 'Dialog Name': 'DropdownSidebar', 'Filename': 'gramps/plugins/sidebar/dropdownsidebar.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Dropdown Menu', 'Dialog Name': 'DropdownSidebar', 'Filename': 'gramps/plugins/sidebar/dropdownsidebar.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Expander Toggle', 'Dialog Name': 'ExpanderSidebar', 'Filename': 'gramps/plugins/sidebar/expandersidebar.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Help', 'Dialog Name': 'FavoriteViews', 'Filename': 'gramps/plugins/sidebar/favoritessidebar.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Select All', 'Dialog Name': 'FavoriteViews', 'Filename': 'gramps/plugins/sidebar/favoritessidebar.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Clear All', 'Dialog Name': 'FavoriteViews', 'Filename': 'gramps/plugins/sidebar/favoritessidebar.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'FavoriteViews', 'Filename': 'gramps/plugins/sidebar/favoritessidebar.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Favorites Toggle', 'Dialog Name': 'FavoriteViews', 'Filename': 'gramps/plugins/sidebar/favoritessidebar.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},

        # gramps/plugins/tool/check.py
        {'Button Name': 'Cancel', 'Dialog Name': 'Check Image File Chooser', 'Filename': 'gramps/plugins/tool/check.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'Check Image File Chooser', 'Filename': 'gramps/plugins/tool/check.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/plugins/tool/citationsfixdialog.py
        {'Button Name': 'Close', 'Dialog Name': 'CitationFixDialog', 'Filename': 'gramps/plugins/tool/citationsfixdialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Auto (best guess)', 'Dialog Name': 'CitationFixDialog', 'Filename': 'gramps/plugins/tool/citationsfixdialog.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Apply', 'Dialog Name': 'CitationFixDialog', 'Filename': 'gramps/plugins/tool/citationsfixdialog.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/plugins/tool/dumpgenderstats.py
        {'Button Name': 'Close', 'Dialog Name': 'DumpGenderStats', 'Filename': 'gramps/plugins/tool/dumpgenderstats.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/plugins/tool/eventcmp.py
        {'Button Name': 'Cancel', 'Dialog Name': 'Event Comparison Save File Chooser', 'Filename': 'gramps/plugins/tool/eventcmp.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'Save', 'Dialog Name': 'Event Comparison Save File Chooser', 'Filename': 'gramps/plugins/tool/eventcmp.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/plugins/tool/gwizardcitationfix.py
        {'Button Name': 'Close', 'Dialog Name': 'GWizardCitationFix Dialog', 'Filename': 'gramps/plugins/tool/gwizardcitationfix.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Select Citations', 'Dialog Name': 'GWizardCitationFix Dialog', 'Filename': 'gramps/plugins/tool/gwizardcitationfix.py', 'Action': 'Positive', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Select Target', 'Dialog Name': 'GWizardCitationFix Dialog', 'Filename': 'gramps/plugins/tool/gwizardcitationfix.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Auto (best guess)', 'Dialog Name': 'GWizardCitationFix Dialog', 'Filename': 'gramps/plugins/tool/gwizardcitationfix.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},

        # gramps/plugins/tool/mediamanager.py
        {'Button Name': 'Help', 'Dialog Name': 'MediaManager', 'Filename': 'gramps/plugins/tool/mediamanager.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Windows'},

        # gramps/plugins/tool/patchnames.py
        {'Button Name': 'OK', 'Dialog Name': 'PatchNames Winprefix', 'Filename': 'gramps/plugins/tool/patchnames.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/plugins/tool/populatesources.py
        {'Button Name': 'Cancel', 'Dialog Name': 'PopulateSources Dialog', 'Filename': 'gramps/plugins/tool/populatesources.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'PopulateSources Dialog', 'Filename': 'gramps/plugins/tool/populatesources.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/plugins/tool/repomergedialog.py
        {'Button Name': 'Close', 'Dialog Name': 'RepoMergeDialog', 'Filename': 'gramps/plugins/tool/repomergedialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Auto (best guess)', 'Dialog Name': 'RepoMergeDialog', 'Filename': 'gramps/plugins/tool/repomergedialog.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Apply', 'Dialog Name': 'RepoMergeDialog', 'Filename': 'gramps/plugins/tool/repomergedialog.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/plugins/tool/sourcesfixdialog.py
        {'Button Name': 'Close', 'Dialog Name': 'SourceFixDialog', 'Filename': 'gramps/plugins/tool/sourcesfixdialog.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Auto (best guess)', 'Dialog Name': 'SourceFixDialog', 'Filename': 'gramps/plugins/tool/sourcesfixdialog.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Apply', 'Dialog Name': 'SourceFixDialog', 'Filename': 'gramps/plugins/tool/sourcesfixdialog.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Unknown'},

        # gramps/plugins/tool/testcasegenerator.py
        {'Button Name': 'Cancel', 'Dialog Name': 'TestCaseGenerator Dialog', 'Filename': 'gramps/plugins/tool/testcasegenerator.py', 'Action': 'Negative', 'Default Placement': 'left', 'Standard': 'Linux'},
        {'Button Name': 'OK', 'Dialog Name': 'TestCaseGenerator Dialog', 'Filename': 'gramps/plugins/tool/testcasegenerator.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Help', 'Dialog Name': 'TestCaseGenerator Dialog', 'Filename': 'gramps/plugins/tool/testcasegenerator.py', 'Action': 'Positive', 'Default Placement': 'right', 'Standard': 'Windows'},

        # FanChart views
        {'Button Name': 'Close', 'Dialog Name': 'FanChart2WayView MessageDialog', 'Filename': 'gramps/plugins/view/fanchart2wayview.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'FanChartDescView MessageDialog', 'Filename': 'gramps/plugins/view/fanchartdescview.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},
        {'Button Name': 'Close', 'Dialog Name': 'FanChartView MessageDialog', 'Filename': 'gramps/plugins/view/fanchartview.py', 'Action': 'Negative', 'Default Placement': 'right', 'Standard': 'Linux'},

        # gramps/plugins/view/pedigreeview.py & relview.py
        {'Button Name': 'Child Navigation Arrow', 'Dialog Name': 'PedigreeView', 'Filename': 'gramps/plugins/view/pedigreeview.py', 'Action': 'Unknown', 'Default Placement': 'left', 'Standard': 'Unknown'},
        {'Button Name': 'Father Navigation Arrow', 'Dialog Name': 'PedigreeView', 'Filename': 'gramps/plugins/view/pedigreeview.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Mother Navigation Arrow', 'Dialog Name': 'PedigreeView', 'Filename': 'gramps/plugins/view/pedigreeview.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
        {'Button Name': 'Relationship Navigation', 'Dialog Name': 'RelView', 'Filename': 'gramps/plugins/view/relview.py', 'Action': 'Unknown', 'Default Placement': 'right', 'Standard': 'Unknown'},
    ]
    return results

def main():
    glade_buttons = extract_glade()
    python_buttons = extract_python()
    all_buttons = glade_buttons + python_buttons

    print(f"Total buttons extracted: {len(all_buttons)} (Glade: {len(glade_buttons)}, Python: {len(python_buttons)})")

    fieldnames = ['Button Name', 'Dialog Name', 'Filename', 'Action', 'Default Placement', 'Standard']

    # Generate ButtonPlacement.csv
    with open('ButtonPlacement.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_buttons:
            writer.writerow(row)
    print("Successfully generated ButtonPlacement.csv")

if __name__ == '__main__':
    main()
