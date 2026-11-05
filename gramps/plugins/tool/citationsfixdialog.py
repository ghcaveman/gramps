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

"""Citation-fix dialog for the GWizard citation fix tool."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import re
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk, Pango

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.dialog import OkDialog
from gramps.gen.db import DbTxn

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

PROBLEM_TREE_CONFIDENCE = "tree_confidence"
PROBLEM_MANUAL_REVIEW = "manual_review"
PROBLEM_NONE = "none"

NO_SOURCE = "(no source)"


# ------------------------------------------------------------
#
# CitationFixDialog
#
# ------------------------------------------------------------
class CitationFixDialog(Gtk.Dialog):
    """Review and fix citation problems in a dialog.

    Four columns: Source (the source the citation references),
    Citation (combined citation details, volume/page, date, and notes),
    Conf (the confidence level from the database with its calculated QUAY
    value, shown as (Qn)), and Hint (a dropdown of fix actions).
    Citations are listed one per row, sorted by source name alphabetically,
    with citations that have no source reference listed last under "(no source)".
    """

    def __init__(
        self,
        title: str,
        dbstate: Any,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        """Build the citation-fix dialog."""
        super().__init__(
            title=title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.combos: list[tuple[str, Gtk.ComboBox, str]] = []
        self.row_targets: list[dict[str, Any]] = []
        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dlg, resp: dlg.destroy())
        self.set_default_size(1480, 560)
        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        info = Gtk.Label(
            label=(
                description
                if description is not None
                else _(
                    "Review each citation and choose a fix action.  "
                    "FamilySearch Tree citations with high confidence "
                    "can be lowered; missing page/date must be added "
                    "manually in the citation editor."
                )
            ),
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        self.rows = build_citation_fix_rows(self.dbstate.db)
        if not self.rows:
            done = Gtk.Label(label=str(_("No citations found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        total_attrs = sum(int(row.get("attr_count", 0)) for row in self.rows)
        count_label = Gtk.Label(
            label=str(
                _("Total citations: %d | Total citation attributes: %d")
                % (len(self.rows), total_attrs)
            ),
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        # Header row above the scrolled grid so it stays locked when
        # scrolling through the data rows.
        # Header row above the scrolled grid so it stays locked when scrolling
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(6)
        header_grid.set_row_spacing(0)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Source")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(False)

        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Citation")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(False)

        page_head = Gtk.Label()
        page_head.set_markup("<b>%s</b>" % str(_("Volume/Page")))
        page_head.set_halign(Gtk.Align.START)
        page_head.set_hexpand(False)

        conf_head = Gtk.Label()
        conf_head.set_markup("<b>%s</b>" % str(_("Conf")))
        conf_head.set_halign(Gtk.Align.START)
        conf_head.set_hexpand(False)

        date_head = Gtk.Label()
        date_head.set_markup("<b>%s</b>" % str(_("Date")))
        date_head.set_halign(Gtk.Align.START)
        date_head.set_hexpand(False)

        notes_head = Gtk.Label()
        notes_head.set_markup("<b>%s</b>" % str(_("Notes")))
        notes_head.set_halign(Gtk.Align.START)
        notes_head.set_hexpand(False)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(left_head, 0, 0, 1, 1)
        header_grid.attach(right_head, 1, 0, 1, 1)
        header_grid.attach(page_head, 2, 0, 1, 1)
        header_grid.attach(conf_head, 3, 0, 1, 1)
        header_grid.attach(date_head, 4, 0, 1, 1)
        header_grid.attach(notes_head, 5, 0, 1, 1)
        header_grid.attach(hint_head, 6, 0, 1, 1)
        content.add(header_grid)

        # SizeGroups to ensure each header column exactly matches the data column width below
        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(7)
        ]
        self.column_sizegroups[0].add_widget(left_head)
        self.column_sizegroups[1].add_widget(right_head)
        self.column_sizegroups[2].add_widget(page_head)
        self.column_sizegroups[3].add_widget(conf_head)
        self.column_sizegroups[4].add_widget(date_head)
        self.column_sizegroups[5].add_widget(notes_head)
        self.column_sizegroups[6].add_widget(hint_head)

        content.pack_start(self.build_rows(self.rows), True, True, 0)
        hint_footer = Gtk.Label(
            label=str(
                _(
                    "Press 'Accept hints' to populate suggested changes into "
                    "the target columns, edit any values as needed, then press 'Apply'."
                )
            )
        )
        hint_footer.set_line_wrap(True)
        hint_footer.set_halign(Gtk.Align.START)
        content.pack_start(hint_footer, False, False, 0)
        content.pack_start(self.build_buttons(), False, False, 0)

    def build_header(self, grid: Gtk.Grid) -> None:
        """Attach the header to a grid (kept for API compat)."""
        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Source")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_line_wrap(True)
        left_head.set_hexpand(False)

        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Citation")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(False)

        page_head = Gtk.Label()
        page_head.set_markup("<b>%s</b>" % str(_("Volume/Page")))
        page_head.set_halign(Gtk.Align.START)
        page_head.set_hexpand(False)

        conf_head = Gtk.Label()
        conf_head.set_markup("<b>%s</b>" % str(_("Conf")))
        conf_head.set_halign(Gtk.Align.START)
        conf_head.set_hexpand(False)

        date_head = Gtk.Label()
        date_head.set_markup("<b>%s</b>" % str(_("Date")))
        date_head.set_halign(Gtk.Align.START)
        date_head.set_hexpand(False)

        notes_head = Gtk.Label()
        notes_head.set_markup("<b>%s</b>" % str(_("Notes")))
        notes_head.set_halign(Gtk.Align.START)
        notes_head.set_hexpand(False)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        grid.attach(left_head, 0, 0, 1, 1)
        grid.attach(right_head, 1, 0, 1, 1)
        grid.attach(page_head, 2, 0, 1, 1)
        grid.attach(conf_head, 3, 0, 1, 1)
        grid.attach(date_head, 4, 0, 1, 1)
        grid.attach(notes_head, 5, 0, 1, 1)
        grid.attach(hint_head, 6, 0, 1, 1)

    def build_rows(self, rows: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build the data grid with 7 columns aligned to headers."""
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for row in rows:
            # Column 0: source name with word-wrap and fixed width
            src_label = Gtk.Label(label=row["source_name"])
            src_label.set_halign(Gtk.Align.START)
            src_label.set_xalign(0.0)
            src_label.set_line_wrap(True)
            src_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            src_label.set_size_request(130, -1)
            src_label.set_max_width_chars(16)
            grid.attach(src_label, 0, row_index, 1, 1)

            # Column 1: Citation details with 3 guaranteed separate lines, word-wrapping and fixed size
            cit_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            cit_box.set_size_request(280, -1)
            cit_lines = row["citation_display"].split("\n")
            line1_text = cit_lines[0] if len(cit_lines) > 0 else ""
            line2_text = cit_lines[1] if len(cit_lines) > 1 else ""
            line3_text = "\n".join(cit_lines[2:]) if len(cit_lines) > 2 else ""

            l1 = Gtk.Label(label=line1_text)
            l1.set_xalign(0.0)
            l1.set_line_wrap(True)
            l1.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l1.set_max_width_chars(38)
            cit_box.pack_start(l1, False, False, 0)

            l2 = Gtk.Label(label=line2_text)
            l2.set_xalign(0.0)
            l2.set_line_wrap(True)
            l2.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l2.set_max_width_chars(38)
            cit_box.pack_start(l2, False, False, 0)

            l3_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            l3 = Gtk.Label(label=line3_text)
            l3.set_xalign(0.0)
            l3.set_line_wrap(True)
            l3.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l3.set_max_width_chars(35)
            l3_box.pack_start(l3, True, True, 0)

            notes_text = row.get("notes_text", "")
            if notes_text:
                more_btn = Gtk.Button(label="\u2026")
                more_btn.set_relief(Gtk.ReliefStyle.NONE)
                more_btn.connect("clicked", self.cb_show_notes, notes_text)
                l3_box.pack_start(more_btn, False, False, 0)
            cit_box.pack_start(l3_box, False, False, 0)

            grid.attach(cit_box, 1, row_index, 1, 1)

            # Column 2: target Volume/Page entry (empty by default)
            page_entry = Gtk.Entry()
            page_entry.set_width_chars(15)
            page_entry.set_text("")
            grid.attach(page_entry, 2, row_index, 1, 1)

            # Column 3: target Conf entry (empty by default, placed before Date)
            conf_entry = Gtk.Entry()
            conf_entry.set_width_chars(6)
            conf_entry.set_text("")
            grid.attach(conf_entry, 3, row_index, 1, 1)

            # Column 4: target Date entry (empty by default)
            date_entry = Gtk.Entry()
            date_entry.set_width_chars(12)
            date_entry.set_text("")
            grid.attach(date_entry, 4, row_index, 1, 1)

            # Column 5: target Notes entry (empty by default)
            notes_entry = Gtk.Entry()
            notes_entry.set_width_chars(16)
            notes_entry.set_text("")
            grid.attach(notes_entry, 5, row_index, 1, 1)

            # Column 6: Hint label (not a text box / dropdown), hints appended on separate lines
            hint_label = Gtk.Label(
                label=row.get("hint_text", row.get("best_guess", ""))
            )
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(200, -1)
            hint_label.set_max_width_chars(28)
            grid.attach(hint_label, 6, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(src_label)
                self.column_sizegroups[1].add_widget(cit_box)
                self.column_sizegroups[2].add_widget(page_entry)
                self.column_sizegroups[3].add_widget(conf_entry)
                self.column_sizegroups[4].add_widget(date_entry)
                self.column_sizegroups[5].add_widget(notes_entry)
                self.column_sizegroups[6].add_widget(hint_label)

            self.row_targets.append(
                {
                    "row": row,
                    "page_entry": page_entry,
                    "conf_entry": conf_entry,
                    "date_entry": date_entry,
                    "notes_entry": notes_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(330)
        scrolled.set_min_content_width(1330)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def build_buttons(self) -> Gtk.Box:
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_homogeneous(True)
        n_hints = sum(
            1
            for target in self.row_targets
            if target["row"].get("hint_text") or target["row"].get("best_guess")
        )
        accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        accept_button.set_sensitive(n_hints > 0)
        apply_button = Gtk.Button(label=str(_("Apply")))
        attrs_button = Gtk.Button(label=str(_("Citation Attributes")))
        accept_button.connect("clicked", self.cb_accept_hints)
        apply_button.connect("clicked", self.cb_apply)
        attrs_button.connect("clicked", self.cb_citation_attributes)
        buttons.pack_start(accept_button, True, True, 0)
        buttons.pack_start(apply_button, True, True, 0)
        buttons.pack_start(attrs_button, True, True, 0)
        return buttons

    def cb_citation_attributes(self, _button: Gtk.Button) -> None:
        """Open the citation-attributes dialog (modal to this dialog)."""
        dlg = CitationAttributesDialog(
            title=str(_("Citation Attributes")),
            dbstate=self.dbstate,
            transient_for=self,
        )
        dlg.show_dialog()

    def get_choices(self) -> dict[str, str]:
        return {
            target["row"]["citation_handle"]: target["hint_entry"].get_text()
            for target in self.row_targets
        }

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        """Populate suggested values into target columns."""
        populated_count = 0
        for target in self.row_targets:
            row = target["row"]
            hint_text = row.get("hint_text") or row.get("best_guess", "")
            if not hint_text:
                continue

            sug_conf = row.get("suggested_conf", "")
            if not sug_conf and "Lower to Confidence" in hint_text:
                digits = "".join(c for c in hint_text if c.isdigit())
                if digits:
                    sug_conf = digits

            sug_page = row.get("suggested_page", "")
            sug_date = row.get("suggested_date", "")
            sug_notes = row.get("suggested_notes", "")

            changed = False
            if sug_conf and not target["conf_entry"].get_text():
                target["conf_entry"].set_text(sug_conf)
                changed = True
            if sug_page and not target["page_entry"].get_text():
                target["page_entry"].set_text(sug_page)
                changed = True
            if sug_date and not target["date_entry"].get_text():
                target["date_entry"].set_text(sug_date)
                changed = True
            if sug_notes and not target["notes_entry"].get_text():
                target["notes_entry"].set_text(sug_notes)
                changed = True

            if changed:
                populated_count += 1

        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Populated suggested data into target columns for %d citations. "
                    "Review or edit them, then press Apply."
                )
            )
            % populated_count,
            parent=self,
        )

    def cb_set_best(self, button: Gtk.Button) -> None:
        """Backward-compatible alias for cb_accept_hints."""
        self.cb_accept_hints(button)

    def run_auto(self, parent: Gtk.Window | None = None) -> None:
        """Apply best-guess fixes without showing the dialog."""
        rows = build_citation_fix_rows(self.dbstate.db)
        from gramps.gen.db import DbTxn

        owner = parent or self.get_transient_for()
        applied_count = 0
        with DbTxn(_("Auto-fix citations"), self.dbstate.db) as trans:
            for row in rows:
                cit_handle = row["citation_handle"]
                try:
                    cit = self.dbstate.db.get_citation_from_handle(cit_handle)
                except Exception:
                    cit = None
                if cit is None:
                    continue

                modified = False
                sug_conf = row.get("suggested_conf", "")
                if sug_conf:
                    digits = "".join(c for c in sug_conf if c.isdigit())
                    if digits:
                        cit.set_confidence_level(int(digits))
                        modified = True

                if modified:
                    self.dbstate.db.commit_citation(cit, trans)
                    applied_count += 1

        OkDialog(
            str(_("Auto clean: citations")),
            str(_("Updated %d citations.") % applied_count),
            parent=owner,
        )

    def show_dialog(self) -> None:
        self.show_all()
        self.run()
        self.destroy()

    def cb_show_notes(self, _button: Gtk.Button, notes_text: str) -> None:
        """Show the full citation notes in a dialog (selectable for copy)."""
        dlg = Gtk.Dialog(
            title=str(_("Citation notes")),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        dlg.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        dlg.connect("response", lambda d, r: d.destroy())
        content = dlg.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(150)
        scrolled.set_min_content_width(420)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_wrap_mode(Gtk.WrapMode.WORD)
        buffer_ = textview.get_buffer()
        buffer_.set_text(notes_text)
        scrolled.add(textview)
        content.add(scrolled)
        dlg.show_all()
        dlg.run()
        dlg.destroy()

    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply target column data directly into citation records in the database."""
        from gramps.gen.db import DbTxn
        from gramps.gen.lib import Note

        applied_count = 0
        with DbTxn(_("Apply citation fixes"), self.dbstate.db) as trans:
            for target in self.row_targets:
                row = target["row"]
                cit_handle = row["citation_handle"]
                try:
                    cit = self.dbstate.db.get_citation_from_handle(cit_handle)
                except Exception:
                    cit = None
                if cit is None:
                    continue

                modified = False

                # 1. Volume/Page
                new_page = target["page_entry"].get_text().strip()
                if new_page:
                    cit.set_page(new_page)
                    modified = True

                # 2. Conf
                new_conf_str = target["conf_entry"].get_text().strip()
                if new_conf_str:
                    digits = "".join(
                        c for c in new_conf_str.split("(")[0] if c.isdigit()
                    )
                    if digits:
                        conf_val = max(0, min(int(digits), 4))
                        cit.set_confidence_level(conf_val)
                        modified = True

                # 3. Date
                new_date_str = target["date_entry"].get_text().strip()
                if new_date_str:
                    try:
                        from gramps.gen.datehandler import parser as dateparser

                        d_obj = dateparser.parse(new_date_str)
                        cit.set_date_object(d_obj)
                        modified = True
                    except Exception:
                        pass

                # 4. Notes
                new_notes_str = target["notes_entry"].get_text().strip()
                if new_notes_str:
                    note = Note()
                    note.set(new_notes_str)
                    n_h = self.dbstate.db.add_note(note, trans)
                    cit.add_note(n_h)
                    modified = True

                if modified:
                    self.dbstate.db.commit_citation(cit, trans)
                    applied_count += 1

        if applied_count == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(
                    _(
                        "No target values entered. Press 'Accept hints' or type "
                        "values into the target columns first."
                    )
                ),
                parent=self,
            )
            return

        OkDialog(
            str(_("Citation fixes applied")),
            str(_("Updated %d citations in the database.") % applied_count),
            parent=self,
        )
        self.destroy()


# ------------------------------------------------------------
#
# CitationAttributesDialog
#
# ------------------------------------------------------------
class CitationAttributesDialog(Gtk.Dialog):
    """Dialog for assigning citation attributes.

    Left column: Parametric Key (values) listing Source Type, Information
    Type and Evidence Type.  Right column: Assigned Key (values) showing
    the attribute currently assigned to each.  If no attributes have been
    assigned yet, a "Create default attributes" button is shown which
    assigns them 1:1.
    """

    def __init__(
        self,
        title: str,
        dbstate: Any,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        """Build the citation-attributes dialog."""
        super().__init__(
            title=title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.assigned: dict[str, str] = {}
        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dlg, resp: dlg.destroy())
        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        # Header row: Parametric Key (values) | Assigned Key (values)
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(0)
        header_grid.set_row_spacing(0)
        header_grid.set_column_homogeneous(True)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)
        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Parametric Key (values)")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(True)
        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Assigned Key (values)")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(True)
        header_grid.attach(left_head, 0, 0, 1, 1)
        header_grid.attach(right_head, 1, 0, 1, 1)
        content.add(header_grid)

        # The three parametric keys and their possible values.
        self.param_items = [
            (_("Source Type"), _("Original or Derivative")),
            (_("Information Type"), _("Primary or Secondary")),
            (_("Evidence Type"), _("Direct or Indirect")),
        ]

        self.assigned_labels: list[Gtk.Label] = []
        grid = Gtk.Grid()
        grid.set_column_spacing(0)
        grid.set_row_spacing(0)
        grid.set_column_homogeneous(True)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        for index, (key, values) in enumerate(self.param_items):
            left_label = Gtk.Label(label="%s (%s)" % (key, values))
            left_label.set_halign(Gtk.Align.START)
            left_label.set_line_wrap(True)
            grid.attach(left_label, 0, index, 1, 1)

            right_label = Gtk.Label(label="\u2014")
            right_label.set_halign(Gtk.Align.START)
            right_label.set_line_wrap(True)
            self.assigned_labels.append(right_label)
            grid.attach(right_label, 1, index, 1, 1)
        content.add(grid)

        # If nothing assigned yet, offer to create defaults (1:1).
        self.create_button = Gtk.Button(label=str(_("Create default attributes")))
        self.create_button.connect("clicked", self.cb_create_defaults)
        content.add(self.create_button)
        self._update_create_button()

        content.add(self.build_buttons())

    def _update_create_button(self) -> None:
        """Hide the create button once defaults have been assigned."""
        if self.assigned:
            self.create_button.set_visible(False)
        else:
            self.create_button.set_visible(True)

    def cb_create_defaults(self, _button: Gtk.Button) -> None:
        """Assign default attributes 1:1 (parametric key -> same value)."""
        for key, _values in self.param_items:
            self.assigned[key] = key
        for index, (key, _values) in enumerate(self.param_items):
            self.assigned_labels[index].set_text(self.assigned.get(key, "\u2014"))
        self._update_create_button()

    def build_buttons(self) -> Gtk.Box:
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_homogeneous(True)
        close_button = Gtk.Button(label=str(_("_Close")))
        close_button.connect("clicked", lambda b: self.destroy())
        buttons.pack_start(close_button, True, True, 0)
        return buttons

    def show_dialog(self) -> None:
        self.show_all()
        self.run()
        self.destroy()


# ------------------------------------------------------------
#
# Citation fix helpers
#
# ------------------------------------------------------------
PROBLEM_TREE_CONFIDENCE = "tree_confidence"
PROBLEM_MANUAL_REVIEW = "manual_review"
PROBLEM_NONE = "none"

NO_SOURCE = "(no source)"


_URL_REGEX = re.compile(r"https?://[^\s<>\"'()]+", re.IGNORECASE)
_DATE_FULL_REGEX = re.compile(
    r"\b(?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})\b"
)
_DATE_YEAR_REGEX = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b")


def _extract_url_from_text(text: str) -> str:
    """Extract the first HTTP/HTTPS URL from text."""
    if not text:
        return ""
    match = _URL_REGEX.search(text)
    return match.group(0).rstrip(".,;:") if match else ""


def _extract_date_from_text(text: str) -> str:
    """Extract a date or 4-digit year string from text."""
    if not text:
        return ""
    full = _DATE_FULL_REGEX.search(text)
    if full:
        return full.group(0).strip()
    year = _DATE_YEAR_REGEX.search(text)
    return year.group(0) if year else ""


def build_citation_fix_rows(db) -> list[dict[str, Any]]:
    """Build per-citation rows from the database, sorted by source name.

    Citations with no source reference are listed last under ``(no source)``.
    """
    # Build source lookup: handle -> title
    source_titles: dict[str, str] = {}
    tree_handles: set[str] = set()
    try:
        for src in db.iter_sources():
            try:
                handle = str(src.get_handle() or "")
                title = str(src.get_title() or "")
                if handle:
                    source_titles[handle] = title
                    lowered = title.lower()
                    if "familysearch" in lowered and "family tree" in lowered:
                        tree_handles.add(handle)
            except Exception:
                continue
    except Exception:
        LOG.exception("Failed to iterate sources")

    rows: list[dict[str, Any]] = []
    try:
        for cit in db.iter_citations():
            try:
                cit_handle = str(cit.get_handle() or "")
                src_handle = str(cit.get_reference_handle() or "")
            except Exception:
                continue

            source_name = source_titles.get(src_handle, "")
            if not source_name:
                source_name = NO_SOURCE

            # Build citation display string
            gid = ""
            page = ""
            date_str = ""
            conf = 0
            try:
                gid = str(cit.get_gramps_id() or "")
            except Exception:
                pass
            try:
                page = str(cit.get_page() or "").strip()
            except Exception:
                pass
            try:
                date_obj = cit.get_date_object()
                if (
                    date_obj
                    and hasattr(date_obj, "is_empty")
                    and not date_obj.is_empty()
                ):
                    from gramps.gen.datehandler import get_date

                    date_str = get_date(cit) or str(date_obj)
                elif date_obj:
                    date_str = str(date_obj)
                else:
                    date_str = ""
            except Exception:
                pass
            try:
                conf = int(cit.get_confidence_level() or 0)
            except Exception:
                pass

            # Count citation attributes (media references, notes, source
            # attributes) for this citation.
            attr_count = 0
            try:
                attr_count += len(list(cit.get_media_list() or []))
            except Exception:
                pass
            try:
                attr_count += len(list(cit.get_note_list() or []))
            except Exception:
                pass
            try:
                attr_count += len(list(cit.get_attribute_list() or []))
            except Exception:
                pass

            # Resolve citation notes to text for Citation and Notes columns.
            notes_text = ""
            citation_text = ""
            try:
                from gramps.gen.lib import NoteType

                note_handles = list(cit.get_note_list() or [])
                cit_note_texts: list[str] = []
                other_note_texts: list[str] = []
                for nh in note_handles:
                    try:
                        note = db.get_note_from_handle(nh)
                        if note is not None:
                            ntxt = str(
                                note.get_styledtext() or note.get() or ""
                            ).strip()
                            if ntxt:
                                ntype = getattr(note, "type", None)
                                if ntype == NoteType.CITATION:
                                    cit_note_texts.append(ntxt)
                                else:
                                    other_note_texts.append(ntxt)
                    except Exception:
                        pass
                all_notes = cit_note_texts + other_note_texts
                notes_text = "\n\n".join(all_notes)
                preferred = cit_note_texts or other_note_texts
                if preferred:
                    first_line = preferred[0].splitlines()[0].strip()
                    citation_text = " ".join(first_line.split())
                    if len(citation_text) > 120:
                        citation_text = citation_text[:117] + "..."
            except Exception:
                pass

            # Check source attributes on the citation if no note text
            if not citation_text:
                try:
                    for attr in cit.get_attribute_list() or []:
                        val = str(attr.get_value() or "").strip()
                        if val:
                            citation_text = " ".join(val.split())
                            if len(citation_text) > 120:
                                citation_text = citation_text[:117] + "..."
                            break
                except Exception:
                    pass

            notes_preview = notes_text.replace("\n", " ")
            if len(notes_preview) > 40:
                notes_preview = notes_preview[:40] + "\u2026"

            # QUAY value mirrors the GEDCOM export mapping
            # (exportgedcom.QUALITY_MAP): CONF_VERY_HIGH/4 -> Q3,
            # CONF_HIGH/3 -> Q2, CONF_LOW/1 -> Q1,
            # CONF_VERY_LOW/0 -> Q0.
            if conf >= 4:
                quay = 3
            elif conf == 3:
                quay = 2
            elif conf == 1:
                quay = 1
            elif conf == 0:
                quay = 0
            else:
                quay = None
            if quay is None:
                confidence_display = f"{conf}(-)"
            else:
                confidence_display = f"{conf}({quay})"

            if citation_text:
                c_part = f"{citation_text} ({gid})" if gid else citation_text
            elif gid:
                c_part = f"({gid})"
            else:
                c_part = "(no details)"
            line1 = f"{c_part} |"

            page_val = page if page else "—"
            date_val = date_str if date_str else "—"
            line2 = f"{page_val} | conf:  {confidence_display} | {date_val} |"

            notes_val = notes_preview if notes_preview else "—"
            line3 = notes_val

            citation_display = f"{line1}\n{line2}\n{line3}"

            # Determine suggested actions
            options: list[str] = []
            best_guess = ""
            problem = None

            is_tree = src_handle in tree_handles
            suggested_conf = ""
            suggested_page = ""
            suggested_date = ""
            suggested_notes = ""

            if not page or not date_str:
                corpus = f"{citation_text} {notes_text}"
                if not page:
                    extracted_url = _extract_url_from_text(corpus)
                    if extracted_url:
                        suggested_page = extracted_url
                if not date_str:
                    extracted_date = _extract_date_from_text(corpus)
                    if extracted_date:
                        suggested_date = extracted_date

            hint_actions: list[str] = []
            if is_tree and conf >= 3:
                hint_actions.append(_("Lower to Confidence 1"))
                suggested_conf = "1"
                problem = PROBLEM_TREE_CONFIDENCE
                options = [
                    _("Lower to Confidence 1"),
                    _("Lower to Confidence 2"),
                    _("No change"),
                ]
                best_guess = _("Lower to Confidence 1")
            else:
                options = []
                best_guess = ""
                problem = PROBLEM_NONE

            if suggested_page:
                hint_actions.append(_("Extract URL to Page"))
            elif not page:
                hint_actions.append(_("Add page/volume (manual)"))

            if suggested_date:
                hint_actions.append(_("Extract date: %s") % suggested_date)
            elif not date_str:
                hint_actions.append(_("Add date (manual)"))

            if hint_actions:
                hint_text = "\n".join(hint_actions)
                if problem is None or problem == PROBLEM_NONE:
                    problem = PROBLEM_MANUAL_REVIEW
                if not options:
                    options = hint_actions
                    best_guess = hint_actions[0]
            else:
                hint_text = ""
                options = [_("No action needed")]
                best_guess = _("No action needed")
                problem = PROBLEM_NONE

            rows.append(
                {
                    "source_name": source_name,
                    "source_handle": src_handle,
                    "citation_handle": cit_handle,
                    "citation_display": citation_display,
                    "page": page,
                    "confidence": conf,
                    "quay": quay,
                    "confidence_display": confidence_display,
                    "attr_count": attr_count,
                    "notes_text": notes_text,
                    "notes_preview": notes_preview,
                    "options": options,
                    "best_guess": best_guess,
                    "hint_text": hint_text,
                    "suggested_conf": suggested_conf,
                    "suggested_page": suggested_page,
                    "suggested_date": suggested_date,
                    "suggested_notes": suggested_notes,
                    "problem": problem,
                }
            )
    except Exception:
        LOG.exception("Failed to iterate citations")

    # Sort: named sources first (alphabetical), then "(no source)" last
    rows.sort(key=lambda r: (r["source_name"] == NO_SOURCE, r["source_name"]))

    return rows


def plan_citation_fixes(rows):
    """Turn dialog rows into an apply plan (no database access)."""
    plan = {
        "tree_confidence": [],
        "manual_review": 0,
    }
    for row in rows:
        if row.get("skip"):
            continue
        problem = row.get("problem")
        if problem == PROBLEM_TREE_CONFIDENCE:
            choice = row.get("best_guess", "")
            if choice == _("Lower to Confidence 1"):
                plan["tree_confidence"].append(
                    {"citation_handle": row["citation_handle"], "target_level": 1}
                )
            elif choice == _("Lower to Confidence 2"):
                plan["tree_confidence"].append(
                    {"citation_handle": row["citation_handle"], "target_level": 2}
                )
        elif problem == PROBLEM_MANUAL_REVIEW:
            plan["manual_review"] += 1
    return plan


def _tree_source_handles(db):
    """Return the gramps handles of FamilySearch family-tree sources."""
    handles = set()
    for src in db.iter_sources():
        try:
            title = str(src.get_title() or "").lower()
        except Exception:  # pylint: disable=broad-except
            title = ""
        if "familysearch" in title and "family tree" in title:
            handles.add(str(src.get_handle() or ""))
    return handles


def apply_citation_fixes(dbstate, plan):
    """Lower over-confident FamilySearch Tree citation confidence."""
    from gramps.gen.db import DbTxn

    db = dbstate.db
    lowered = 0
    with DbTxn(_("Lower tree citation confidence"), db) as trans:
        for entry in plan.get("tree_confidence", []):
            cit = db.get_citation_from_handle(entry["citation_handle"])
            if cit is None:
                continue
            try:
                cit.set_confidence_level(entry["target_level"])
                db.commit_citation(cit, trans)
                lowered += 1
            except Exception:
                LOG.exception("Failed to lower citation confidence")
    return {"tree_confidence_lowered": lowered}
