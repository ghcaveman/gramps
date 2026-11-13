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
from gramps.plugins.tool.gwizard_common import reports_apply_errors
from gramps.gen.db import DbTxn
from gramps.gen.errors import HandleError
from gramps.plugins.tool.gwizardcitationshared import (
    add_note_once,
    extract_access_date,
    extract_url,
    parse_citation_date,
)

_ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext
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
        self.set_default_size(1280, 560)
        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        self.rows = build_citation_fix_rows(self.dbstate.db)
        if not self.rows:
            done = Gtk.Label(label=str(_("No citations found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            self.accept_button = Gtk.Button(
                label=_("Accept hints ({number_of})").format(number_of=0)
            )
            self.accept_button.set_sensitive(False)
            self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

            self.apply_button = Gtk.Button(label=str(_("Apply")))
            self.apply_button.set_sensitive(False)
            self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

            self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
            return

        total_attrs = sum(int(row.get("attr_count", 0)) for row in self.rows)
        count_label = Gtk.Label(
            label=str(
                _("Citations: {citations} | Citation attributes: {attributes}").format(
                    citations=len(self.rows), attributes=total_attrs
                )
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
        conf_head.set_markup("<b>%s</b>" % str(_("Conf(Q)")))
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

        # SizeGroups keep each header column as wide as its data column
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
        desc_text = (
            description
            if description is not None
            else str(_("Clean tree page/date and confidence."))
        )
        desc_text = (
            desc_text.replace("PAGE/DATE", "page/date")
            .replace("PAGE", "page")
            .replace("DATE", "date")
            .replace("Tree", "tree")
        )
        if not desc_text.endswith("."):
            desc_text += "."
        hint_footer = Gtk.Label(
            label=f"{desc_text} "
            + str(
                _(
                    "Press 'Accept hints' to populate suggested changes into "
                    "the target columns, edit any values as needed, then press 'Apply'."
                )
            )
        )
        hint_footer.set_line_wrap(True)
        hint_footer.set_halign(Gtk.Align.START)
        hint_footer.set_size_request(-1, 45)
        content.pack_start(hint_footer, False, False, 0)

        # Action area buttons (sized the same as Close and placed to its left)
        n_hints = sum(
            1
            for target in self.row_targets
            if bool(
                target["row"].get("suggested_conf")
                or target["row"].get("suggested_page")
                or target["row"].get("suggested_date")
                or target["row"].get("suggested_notes")
            )
        )
        self.accept_button = Gtk.Button(
            label=_("Accept hints ({number_of})").format(number_of=n_hints)
        )
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(len(self.rows) > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

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
        conf_head.set_markup("<b>%s</b>" % str(_("Conf(Q)")))
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
            src_label.set_size_request(210, -1)
            src_label.set_max_width_chars(26)
            grid.attach(src_label, 0, row_index, 1, 1)

            # Column 1: citation details on three wrapped lines, fixed size
            cit_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            cit_box.set_size_request(225, -1)
            cit_lines = row["citation_display"].split("\n")
            line1_text = cit_lines[0] if len(cit_lines) > 0 else ""
            line2_text = cit_lines[1] if len(cit_lines) > 1 else ""
            line3_text = "\n".join(cit_lines[2:]) if len(cit_lines) > 2 else ""

            l1 = Gtk.Label(label=line1_text)
            l1.set_xalign(0.0)
            l1.set_line_wrap(True)
            l1.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l1.set_max_width_chars(30)
            cit_box.pack_start(l1, False, False, 0)

            l2 = Gtk.Label(label=line2_text)
            l2.set_xalign(0.0)
            l2.set_line_wrap(True)
            l2.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l2.set_max_width_chars(30)
            cit_box.pack_start(l2, False, False, 0)

            l3_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            l3 = Gtk.Label(label=line3_text)
            l3.set_xalign(0.0)
            l3.set_line_wrap(True)
            l3.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l3.set_max_width_chars(28)
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
            page_entry.set_width_chars(24)
            page_entry.set_text("")
            grid.attach(page_entry, 2, row_index, 1, 1)

            # Column 3: target Conf entry (empty by default, placed before Date)
            conf_entry = Gtk.Entry()
            conf_entry.set_width_chars(5)
            conf_entry.set_text("")
            grid.attach(conf_entry, 3, row_index, 1, 1)

            # Column 4: target Date entry (empty by default)
            date_entry = Gtk.Entry()
            date_entry.set_width_chars(10)
            date_entry.set_text("")
            grid.attach(date_entry, 4, row_index, 1, 1)

            # Column 5: target Notes entry (empty by default)
            notes_entry = Gtk.Entry()
            notes_entry.set_width_chars(25)
            notes_entry.set_text("")
            grid.attach(notes_entry, 5, row_index, 1, 1)

            # Column 6: hint label, one hint per line
            hint_label = Gtk.Label(
                label=row.get("hint_text", row.get("best_guess", ""))
            )
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(160, -1)
            hint_label.set_max_width_chars(22)
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
        scrolled.set_min_content_width(1060)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

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
            ngettext(
                "Filled in suggested values for {number_of} citation. Review or edit "
                "them, then press Apply.",
                "Filled in suggested values for {number_of} citations. Review or edit "
                "them, then press Apply.",
                populated_count,
            ).format(number_of=populated_count),
            parent=self,
        )

    def show_dialog(self) -> None:
        """Display the modal dialog until user explicitly closes it."""
        self.show_all()
        while True:
            resp = self.run()
            if resp in (
                Gtk.ResponseType.CLOSE,
                Gtk.ResponseType.CANCEL,
                Gtk.ResponseType.DELETE_EVENT,
            ):
                break
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

    @reports_apply_errors
    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply target column data directly into citation records in the database."""
        applied_count = 0
        with DbTxn(_("Fix Citations"), self.dbstate.db) as trans:
            for target in self.row_targets:
                new_page = target["page_entry"].get_text()
                if apply_citation_values(
                    self.dbstate.db,
                    trans,
                    target["row"]["citation_handle"],
                    page=new_page,
                    conf=target["conf_entry"].get_text(),
                    date=target["date_entry"].get_text(),
                    notes=target["notes_entry"].get_text(),
                    clear_page=bool(
                        target["row"].get("clear_page") and not new_page.strip()
                    ),
                ):
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
            str(
                ngettext(
                    "Updated {number_of} citation.",
                    "Updated {number_of} citations.",
                    applied_count,
                ).format(number_of=applied_count)
            ),
            parent=self,
        )


# ------------------------------------------------------------
#
# Citation fix helpers
#
# ------------------------------------------------------------
PROBLEM_TREE_CONFIDENCE = "tree_confidence"
PROBLEM_MANUAL_REVIEW = "manual_review"
PROBLEM_NONE = "none"

NO_SOURCE = "(no source)"


def _extract_url_from_text(text: str) -> str:
    """Extract the first HTTP/HTTPS URL from text."""
    return extract_url(text)


def _extract_date_from_text(text: str) -> str:
    """Extract an access date from text.

    Only a date after "accessed" or "retrieved" (or a FamilySearch timestamp)
    counts. A bare year or any other date in a note describes the record, not
    when it was viewed, so it is never taken as the citation date.
    """
    return extract_access_date(text, allow_timestamp=True)


def build_citation_fix_rows(db: Any) -> list[dict[str, Any]]:
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

            # Determine suggested actions
            options: list[str] = []
            best_guess = ""
            problem = None

            is_tree = src_handle in tree_handles
            suggested_conf = ""
            suggested_page = ""
            suggested_date = ""
            suggested_notes = ""
            clear_page = False

            if page:
                url_in_page = _extract_url_from_text(page)
                if url_in_page:
                    if url_in_page not in notes_text:
                        suggested_notes = url_in_page
                    cleaned_page = page.replace(url_in_page, " ").strip(" ,;.")
                    if cleaned_page:
                        suggested_page = cleaned_page
                    else:
                        clear_page = True

            if not date_str:
                corpus = f"{citation_text} {notes_text}"
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

            if suggested_notes and clear_page:
                hint_actions.append(_("Move URL from Volume/Page to notes"))
            elif suggested_notes:
                hint_actions.append(_("Move URL to notes"))

            if suggested_page:
                hint_actions.append(_("Clean Volume/Page"))

            if suggested_date:
                hint_actions.append(
                    _("Extract date: {date}").format(date=suggested_date)
                )

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
                    "clear_page": clear_page,
                    "problem": problem,
                }
            )
    except Exception:
        LOG.exception("Failed to iterate citations")

    # Sort: named sources first (alphabetical), then "(no source)" last
    rows.sort(key=lambda r: (r["source_name"] == NO_SOURCE, r["source_name"]))

    return rows


def apply_citation_values(
    db: Any,
    trans: Any,
    citation_handle: str,
    page: str = "",
    conf: str = "",
    date: str = "",
    notes: str = "",
    clear_page: bool = False,
) -> bool:
    """Write the given values into one citation; blank values are skipped.

    This is the one place citation fixes are applied, for the dialog's Apply
    button and for the no-review path. ``conf`` may be text such as ``"1"``
    or ``"1(1)"``. Unparseable dates are ignored. A note whose text the
    citation already has is not added twice. Returns True if the citation
    changed.
    """
    try:
        cit = db.get_citation_from_handle(citation_handle)
    except HandleError:
        cit = None
    if cit is None:
        return False
    modified = False
    page = (page or "").strip()
    if page and page != str(cit.get_page() or ""):
        cit.set_page(page)
        modified = True
    elif clear_page and cit.get_page():
        cit.set_page("")
        modified = True
    conf = (conf or "").strip()
    if conf:
        digits = "".join(c for c in conf.split("(")[0] if c.isdigit())
        if digits:
            level = max(0, min(int(digits), 4))
            if level != cit.get_confidence_level():
                cit.set_confidence_level(level)
                modified = True
    date_obj = parse_citation_date(date)
    if date_obj is not None:
        cit.set_date_object(date_obj)
        modified = True
    elif (date or "").strip():
        LOG.warning("Ignoring unparseable date '%s'", date)
    if add_note_once(db, trans, cit, notes):
        modified = True
    if modified:
        db.commit_citation(cit, trans)
    return modified


def auto_fix_citations(db: Any) -> int:
    """Accept every hint and apply it in one transaction (one undo).

    Applies the suggested confidence, Volume/Page and date that the Fix
    Citations dialog fills in when you press Accept hints. Returns the
    number of citations changed.
    """
    rows = build_citation_fix_rows(db)
    applied = 0
    with DbTxn(_("Fix Citations"), db) as trans:
        for row in rows:
            if apply_citation_values(
                db,
                trans,
                row["citation_handle"],
                page=row.get("suggested_page", ""),
                conf=row.get("suggested_conf", ""),
                date=row.get("suggested_date", ""),
                notes=row.get("suggested_notes", ""),
                clear_page=bool(row.get("clear_page")),
            ):
                applied += 1
    return applied
