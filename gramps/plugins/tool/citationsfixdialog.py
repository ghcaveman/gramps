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
        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dlg, resp: dlg.destroy())
        self.set_default_size(1480, 450)
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
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(0)
        header_grid.set_row_spacing(0)
        header_grid.set_column_homogeneous(True)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Source")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(True)
        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Citation")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(True)
        conf_head = Gtk.Label()
        conf_head.set_markup("<b>%s</b>" % str(_("Conf")))
        conf_head.set_halign(Gtk.Align.START)
        conf_head.set_hexpand(True)
        date_head = Gtk.Label()
        date_head.set_markup("<b>%s</b>" % str(_("Date")))
        date_head.set_halign(Gtk.Align.START)
        date_head.set_hexpand(True)
        mid_head = Gtk.Label()
        mid_head.set_markup("<b>%s</b>" % str(_("Hint")))
        mid_head.set_halign(Gtk.Align.START)
        mid_head.set_hexpand(True)
        header_grid.attach(left_head, 0, 0, 3, 1)
        header_grid.attach(right_head, 3, 0, 12, 1)
        header_grid.attach(conf_head, 15, 0, 2, 1)
        header_grid.attach(date_head, 17, 0, 2, 1)
        header_grid.attach(mid_head, 19, 0, 5, 1)
        content.add(header_grid)

        content.add(self.build_rows(self.rows))
        hint = Gtk.Label(
            label=str(
                _(
                    "Lowering confidence does not delete citations; it only "
                    "records that the FamilySearch Tree is a derivative "
                    "source.  Missing page/date must be entered by hand."
                )
            )
        )
        hint.set_line_wrap(True)
        hint.set_halign(Gtk.Align.START)
        content.add(hint)
        content.add(self.build_buttons())

    def build_header(self, grid: Gtk.Grid) -> None:
        """Attach the header to a grid (kept for API compat)."""
        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Source")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_line_wrap(True)
        left_head.set_hexpand(True)
        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Citation")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(True)
        conf_head = Gtk.Label()
        conf_head.set_markup("<b>%s</b>" % str(_("Conf")))
        conf_head.set_halign(Gtk.Align.START)
        conf_head.set_hexpand(True)
        date_head = Gtk.Label()
        date_head.set_markup("<b>%s</b>" % str(_("Date")))
        date_head.set_halign(Gtk.Align.START)
        date_head.set_hexpand(True)
        mid_head = Gtk.Label()
        mid_head.set_markup("<b>%s</b>" % str(_("Hint")))
        mid_head.set_halign(Gtk.Align.START)
        mid_head.set_hexpand(True)
        grid.attach(left_head, 0, 0, 3, 1)
        grid.attach(right_head, 3, 0, 12, 1)
        grid.attach(conf_head, 15, 0, 2, 1)
        grid.attach(date_head, 17, 0, 2, 1)
        grid.attach(mid_head, 19, 0, 5, 1)

    def build_rows(self, rows: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build a 5-column grid with proportional spans: Source (3) | Citation (12) | Conf (2) | Date (2) | Hint (5)."""
        grid = Gtk.Grid()
        grid.set_column_spacing(0)
        grid.set_row_spacing(0)
        grid.set_column_homogeneous(True)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for row in rows:
            # Column 0 (span 3): source name with word-wrap
            src_label = Gtk.Label(label=row["source_name"])
            src_label.set_halign(Gtk.Align.START)
            src_label.set_line_wrap(True)
            src_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            src_label.set_max_width_chars(24)
            grid.attach(src_label, 0, row_index, 3, 1)

            # Column 1 (span 12): combined citation details
            cit_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            cit_label = Gtk.Label(label=row["citation_display"])
            cit_label.set_halign(Gtk.Align.START)
            cit_label.set_line_wrap(True)
            cit_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            cit_box.pack_start(cit_label, True, True, 0)
            notes_text = row.get("notes_text", "")
            if notes_text:
                more_btn = Gtk.Button(label="\u2026")
                more_btn.set_relief(Gtk.ReliefStyle.NONE)
                more_btn.connect("clicked", self.cb_show_notes, notes_text)
                cit_box.pack_start(more_btn, False, False, 0)
            grid.attach(cit_box, 3, row_index, 12, 1)

            # Column 2 (span 2): confidence / QUAY (placed before Date)
            conf_label = Gtk.Label(label=row["confidence_display"])
            conf_label.set_halign(Gtk.Align.START)
            conf_label.set_line_wrap(True)
            grid.attach(conf_label, 15, row_index, 2, 1)

            # Column 3 (span 2): date
            date_text = row.get("date", "")
            date_label = Gtk.Label(label=date_text if date_text else "\u2014")
            date_label.set_halign(Gtk.Align.START)
            date_label.set_line_wrap(True)
            date_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            grid.attach(date_label, 17, row_index, 2, 1)

            # Column 4 (span 5): hint dropdown (last column)
            combo = Gtk.ComboBoxText()
            combo.set_hexpand(True)
            for option in row["options"]:
                combo.append_text(option)
            combo.set_active(0)
            grid.attach(combo, 19, row_index, 5, 1)

            self.combos.append((row["citation_handle"], combo, row["best_guess"]))
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
        auto_button = Gtk.Button(label=str(_("Auto (best guess)")))
        apply_button = Gtk.Button(label=str(_("Apply")))
        attrs_button = Gtk.Button(label=str(_("Citation Attributes")))
        auto_button.connect("clicked", self.cb_set_best)
        apply_button.connect("clicked", self.cb_apply)
        attrs_button.connect("clicked", self.cb_citation_attributes)
        buttons.pack_start(auto_button, True, True, 0)
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
            citation_handle: self.get_choice(combo, citation_handle)
            for citation_handle, combo, _best in self.combos
        }

    def get_choice(self, combo: Gtk.ComboBox, fallback: str) -> str:
        active = combo.get_active_iter()
        if active is None:
            return fallback
        return str(combo.get_model()[active][0])

    def run_auto(self, parent: Gtk.Window | None = None) -> None:
        """Apply best-guess fixes without showing the dialog."""
        rows = build_citation_fix_rows(self.dbstate.db)
        plan = plan_citation_fixes(rows)
        owner = parent or self.get_transient_for()
        if not plan.get("tree_confidence") and not plan.get("manual_review"):
            OkDialog(
                str(_("Nothing to clean")),
                str(_("No citation problems found.")),
                parent=owner,
            )
            return
        changed = apply_citation_fixes(self.dbstate, plan)
        lowered = changed.get("tree_confidence_lowered", 0)
        manual = plan.get("manual_review", 0)
        OkDialog(
            str(_("Auto clean: citations")),
            str(
                _("Lowered confidence of %d citations, %d need manual review.")
                % (lowered, manual)
            ),
            parent=owner,
        )

    def show_dialog(self) -> None:
        self.show_all()
        self.run()
        self.destroy()

    def cb_set_best(self, _button: Gtk.Button) -> None:
        for citation_handle, combo, best in self.combos:
            model = combo.get_model()
            for index in range(len(model)):
                if str(model[index][0]) == best:
                    combo.set_active(index)
                    break

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
        """Apply the user choices as citation fixes."""
        rows = build_citation_fix_rows(self.dbstate.db)
        plan = plan_citation_fixes(rows)
        if not plan.get("tree_confidence") and not plan.get("manual_review"):
            OkDialog(
                str(_("Nothing to clean")),
                str(_("No citation problems found.")),
                parent=self,
            )
            return
        changed = apply_citation_fixes(self.dbstate, plan)
        lowered = changed.get("tree_confidence_lowered", 0)
        manual = plan.get("manual_review", 0)
        OkDialog(
            str(_("Citation fixes applied")),
            str(
                _("Lowered confidence of %d citations, %d need manual review.")
                % (lowered, manual)
            ),
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
            if is_tree and conf >= 3:
                options = [
                    _("Lower to Confidence 1"),
                    _("Lower to Confidence 2"),
                    _("No change"),
                ]
                best_guess = _("Lower to Confidence 1")
                problem = PROBLEM_TREE_CONFIDENCE
            else:
                manual_actions: list[str] = []
                if not page:
                    manual_actions.append(_("Add page/volume (manual)"))
                if not date_str:
                    manual_actions.append(_("Add date (manual)"))
                if manual_actions:
                    options = manual_actions
                    best_guess = manual_actions[0]
                    problem = PROBLEM_MANUAL_REVIEW
                else:
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
