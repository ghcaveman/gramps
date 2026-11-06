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

"""Tool and dialog for assigning Genealogical Proof Standard (GPS) Citation Attributes."""

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
from gramps.gen.lib import SrcAttribute
from gramps.gui.plug import tool
from gramps.plugins.tool.gwizardcitationshared import note_text

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


def suggest_citation_attributes(
    src_title: str, cit_page: str, cit_text: str, curr_conf: int
) -> dict[str, str]:
    """Suggest GPS Source Type, Information Type, Evidence Type and QUAY based on evidence analysis."""
    text_corpus = f"{src_title} {cit_page} {cit_text}".lower()

    # 1. User Trees
    if any(
        k in text_corpus
        for k in [
            "family tree",
            "member tree",
            "public tree",
            "user tree",
            "wikitree",
            "geni",
        ]
    ):
        return {
            "source_type": "Authored",
            "info_type": "Secondary",
            "evidence_type": "Indirect",
            "quay": "1",
            "hint_text": _(
                "Online compiled tree (suggest Authored, Secondary, Indirect)"
            ),
        }

    # 2. Vital Certificates / Parish Originals / Firsthand Witness
    if any(
        k in text_corpus
        for k in [
            "certificate",
            "parish register",
            "bible record",
            "affidavit",
            "will and testament",
        ]
    ):
        return {
            "source_type": "Original",
            "info_type": "Primary",
            "evidence_type": "Direct",
            "quay": "3",
            "hint_text": _(
                "Firsthand vital/parish record (suggest Original, Primary, Direct)"
            ),
        }

    # 3. Census / Census Index / Federal Population Schedule
    if "census" in text_corpus:
        if any(
            k in text_corpus for k in ["index", "ancestry", "familysearch", "database"]
        ):
            return {
                "source_type": "Derivative",
                "info_type": "Secondary",
                "evidence_type": "Direct",
                "quay": "2",
                "hint_text": _(
                    "Census index/database (suggest Derivative, Secondary, Direct)"
                ),
            }
        return {
            "source_type": "Original",
            "info_type": "Primary",
            "evidence_type": "Direct",
            "quay": "3",
            "hint_text": _(
                "Census schedule record (suggest Original, Primary, Direct)"
            ),
        }

    # 4. Cemetery / Grave / Memorial
    if any(
        k in text_corpus
        for k in ["find a grave", "billiongraves", "cemetery", "headstone", "memorial"]
    ):
        return {
            "source_type": "Derivative",
            "info_type": "Secondary",
            "evidence_type": "Direct",
            "quay": "2",
            "hint_text": _(
                "Cemetery database/index (suggest Derivative, Secondary, Direct)"
            ),
        }

    # 5. Compiled Book / Genealogy / Biography
    if any(
        k in text_corpus
        for k in [
            "history",
            "biography",
            "genealogy of",
            "family history",
            "monograph",
        ]
    ):
        return {
            "source_type": "Authored",
            "info_type": "Secondary",
            "evidence_type": "Indirect",
            "quay": "2",
            "hint_text": _(
                "Compiled history/book (suggest Authored, Secondary, Indirect)"
            ),
        }

    # Fallback based on confidence level
    if curr_conf >= 3:
        return {
            "source_type": "Original",
            "info_type": "Primary",
            "evidence_type": "Direct",
            "quay": "3",
            "hint_text": _(
                "High confidence evidence (suggest Original, Primary, Direct)"
            ),
        }

    return {
        "source_type": "Derivative",
        "info_type": "Secondary",
        "evidence_type": "Direct",
        "quay": "2",
        "hint_text": _("Derivative source (suggest Derivative, Secondary, Direct)"),
    }


def build_citation_attribute_rows(db: Any) -> list[dict[str, Any]]:
    """Build citation rows for GPS attribute review and assignment."""
    source_info: dict[str, tuple[str, str]] = {}
    for src in db.iter_sources():
        s_handle = str(src.get_handle() or "")
        title = str(src.get_title() or "")
        gid = str(src.get_gramps_id() or "")
        source_info[s_handle] = (title, gid)

    rows: list[dict[str, Any]] = []
    for cit in db.iter_citations():
        c_handle = str(cit.get_handle() or "")
        c_gid = str(cit.get_gramps_id() or "")
        page = str(cit.get_page() or "").strip()
        conf = int(cit.get_confidence_level() or 2)
        s_handle = str(cit.get_reference_handle() or "")
        src_title, src_gid = source_info.get(s_handle, ("(no source)", ""))

        # Current attributes
        curr_attrs = {
            str(a.get_type() or ""): str(a.get_value() or "")
            for a in (cit.get_attribute_list() or [])
        }

        # Notes text for context
        notes_list = []
        for nh in cit.get_note_list() or []:
            try:
                note = db.get_note_from_handle(nh)
                if note:
                    ntxt = note_text(note).strip()
                    if ntxt:
                        notes_list.append(ntxt)
            except Exception:
                pass
        notes_text = " ".join(notes_list)

        sug = suggest_citation_attributes(src_title, page, notes_text, conf)

        # Check if already has complete GPS attributes
        has_all = (
            "Source Type" in curr_attrs
            and "Information Type" in curr_attrs
            and "Evidence Type" in curr_attrs
        )

        display_lines = [
            f"{src_title} ({src_gid})" if src_gid else src_title,
            f"Citation: {page if page else '—'} ({c_gid}) | Conf: {conf}",
        ]

        rows.append(
            {
                "citation_handle": c_handle,
                "citation_gid": c_gid,
                "source_title": src_title,
                "source_gid": src_gid,
                "page": page,
                "confidence": conf,
                "curr_attrs": curr_attrs,
                "display_text": "\n".join(display_lines),
                "suggested_src_type": (
                    sug["source_type"] if not curr_attrs.get("Source Type") else ""
                ),
                "suggested_info_type": (
                    sug["info_type"] if not curr_attrs.get("Information Type") else ""
                ),
                "suggested_ev_type": (
                    sug["evidence_type"] if not curr_attrs.get("Evidence Type") else ""
                ),
                "suggested_quay": sug["quay"],
                "hint_text": (
                    sug["hint_text"]
                    if not has_all
                    else _("All GPS attributes already assigned")
                ),
                "has_all": has_all,
            }
        )

    rows.sort(
        key=lambda r: (
            r["has_all"],
            r["source_title"] == "(no source)",
            r["source_title"],
        )
    )
    return rows


# ------------------------------------------------------------
#
# CitationAttributesDialog
#
# ------------------------------------------------------------
class CitationAttributesDialog(Gtk.Dialog):
    """Review and assign Genealogical Proof Standard (GPS) Citation Attributes.

    Inputs are labels (Source & Citation details).
    Outputs are text boxes (Source Type, Information Type, Evidence Type, QUAY),
    with a Hint column at the end and Accept hints and Apply buttons.
    """

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Citation Attributes"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.rows = build_citation_attribute_rows(dbstate.db)
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(950, 520)

        n_hints = sum(1 for r in self.rows if not r["has_all"])
        self.accept_button = Gtk.Button(label=str(_("Apply hints (%d)")) % n_hints)
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(len(self.rows) > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        info = Gtk.Label(
            label=description
            or str(
                _(
                    "Assign Genealogical Proof Standard (GPS) quality attributes to citations: "
                    "Source Type (Original/Derivative/Authored), Information Type (Primary/Secondary/Unknown), "
                    "Evidence Type (Direct/Indirect/Negative), and QUAY confidence rating. "
                    "Press 'Accept hints' to populate suggested attributes, edit as needed, then press 'Apply'."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not self.rows:
            done = Gtk.Label(label=str(_("No citations found in database.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(
                _("Total citations: %d | Citations needing GPS attributes: %d")
                % (len(self.rows), n_hints)
            )
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        # Header row above scrolled grid
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(6)
        header_grid.set_row_spacing(0)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        src_head = Gtk.Label()
        src_head.set_markup("<b>%s</b>" % str(_("Citation")))
        src_head.set_halign(Gtk.Align.START)
        src_head.set_hexpand(False)

        st_head = Gtk.Label()
        st_head.set_markup("<b>%s</b>" % str(_("Source Type")))
        st_head.set_halign(Gtk.Align.START)
        st_head.set_hexpand(False)

        it_head = Gtk.Label()
        it_head.set_markup("<b>%s</b>" % str(_("Information Type")))
        it_head.set_halign(Gtk.Align.START)
        it_head.set_hexpand(False)

        et_head = Gtk.Label()
        et_head.set_markup("<b>%s</b>" % str(_("Evidence Type")))
        et_head.set_halign(Gtk.Align.START)
        et_head.set_hexpand(False)

        quay_head = Gtk.Label()
        quay_head.set_markup("<b>%s</b>" % str(_("QUAY")))
        quay_head.set_halign(Gtk.Align.START)
        quay_head.set_hexpand(False)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(src_head, 0, 0, 1, 1)
        header_grid.attach(st_head, 1, 0, 1, 1)
        header_grid.attach(it_head, 2, 0, 1, 1)
        header_grid.attach(et_head, 3, 0, 1, 1)
        header_grid.attach(quay_head, 4, 0, 1, 1)
        header_grid.attach(hint_head, 5, 0, 1, 1)
        content.add(header_grid)

        # SizeGroups to lock headers to data columns below
        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(6)
        ]
        self.column_sizegroups[0].add_widget(src_head)
        self.column_sizegroups[1].add_widget(st_head)
        self.column_sizegroups[2].add_widget(it_head)
        self.column_sizegroups[3].add_widget(et_head)
        self.column_sizegroups[4].add_widget(quay_head)
        self.column_sizegroups[5].add_widget(hint_head)

        content.pack_start(self.build_rows(self.rows), True, True, 0)

        hint_footer = Gtk.Label(
            label=str(
                _(
                    "Press 'Accept hints' to populate suggested GPS attributes into the target columns, "
                    "edit any values as needed, then press 'Apply' to update citations in the database."
                )
            )
        )
        hint_footer.set_line_wrap(True)
        hint_footer.set_halign(Gtk.Align.START)
        content.pack_start(hint_footer, False, False, 0)

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build data grid with inputs as labels, outputs as text boxes, and hint labels."""
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            # Column 0: Source & Citation details (Input - Label)
            src_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            src_box.set_size_request(170, -1)
            lines = entry.get("display_text", "").splitlines()
            l1 = Gtk.Label(label=lines[0] if len(lines) > 0 else "")
            l1.set_xalign(0.0)
            l1.set_line_wrap(True)
            l1.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l1.set_max_width_chars(24)
            src_box.pack_start(l1, False, False, 0)

            l2 = Gtk.Label(label=lines[1] if len(lines) > 1 else "")
            l2.set_xalign(0.0)
            l2.set_line_wrap(True)
            l2.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l2.set_max_width_chars(24)
            src_box.pack_start(l2, False, False, 0)

            grid.attach(src_box, 0, row_index, 1, 1)

            # Column 1: Source Type - Entry (empty by default)
            st_entry = Gtk.Entry()
            st_entry.set_width_chars(11)
            st_entry.set_text("")
            grid.attach(st_entry, 1, row_index, 1, 1)

            # Column 2: Information Type - Entry (empty by default)
            it_entry = Gtk.Entry()
            it_entry.set_width_chars(11)
            it_entry.set_text("")
            grid.attach(it_entry, 2, row_index, 1, 1)

            # Column 3: Evidence Type - Entry (empty by default)
            et_entry = Gtk.Entry()
            et_entry.set_width_chars(11)
            et_entry.set_text("")
            grid.attach(et_entry, 3, row_index, 1, 1)

            # Column 4: QUAY - Entry (empty by default)
            quay_entry = Gtk.Entry()
            quay_entry.set_width_chars(4)
            quay_entry.set_text("")
            grid.attach(quay_entry, 4, row_index, 1, 1)

            # Column 5: Hint - Label
            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(160, -1)
            hint_label.set_max_width_chars(22)
            grid.attach(hint_label, 5, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(src_box)
                self.column_sizegroups[1].add_widget(st_entry)
                self.column_sizegroups[2].add_widget(it_entry)
                self.column_sizegroups[3].add_widget(et_entry)
                self.column_sizegroups[4].add_widget(quay_entry)
                self.column_sizegroups[5].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "st_entry": st_entry,
                    "it_entry": it_entry,
                    "et_entry": et_entry,
                    "quay_entry": quay_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(300)
        scrolled.set_min_content_width(720)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        """Populate suggested attributes into target textboxes."""
        populated_count = 0
        for target in self.row_targets:
            item = target["entry"]
            sug_st = item.get("suggested_src_type", "")
            sug_it = item.get("suggested_info_type", "")
            sug_et = item.get("suggested_ev_type", "")
            sug_qy = item.get("suggested_quay", "")

            changed = False
            if sug_st and not target["st_entry"].get_text():
                target["st_entry"].set_text(sug_st)
                changed = True
            if sug_it and not target["it_entry"].get_text():
                target["it_entry"].set_text(sug_it)
                changed = True
            if sug_et and not target["et_entry"].get_text():
                target["et_entry"].set_text(sug_et)
                changed = True
            if sug_qy and not target["quay_entry"].get_text():
                target["quay_entry"].set_text(sug_qy)
                changed = True

            if changed:
                populated_count += 1

        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Populated suggested GPS attributes into target columns for %d citations. "
                    "Review or edit them, then press Apply."
                )
            )
            % populated_count,
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply target column data directly into citation attributes in the database."""
        applied_count = 0
        with DbTxn(_("Update Citation Attributes"), self.dbstate.db) as trans:
            for target in self.row_targets:
                item = target["entry"]
                st = target["st_entry"].get_text().strip()
                it = target["it_entry"].get_text().strip()
                et = target["et_entry"].get_text().strip()
                qy = target["quay_entry"].get_text().strip()

                if not st and not it and not et and not qy:
                    continue

                c_handle = item.get("citation_handle")
                try:
                    cit = self.dbstate.db.get_citation_from_handle(c_handle)
                except Exception:
                    cit = None
                if cit is None:
                    continue

                attrs = list(cit.get_attribute_list() or [])
                attr_map = {str(a.get_type() or ""): a for a in attrs}

                if st:
                    if "Source Type" in attr_map:
                        attr_map["Source Type"].set_value(st)
                    else:
                        attr = SrcAttribute()
                        attr.set_type("Source Type")
                        attr.set_value(st)
                        attrs.append(attr)

                if it:
                    if "Information Type" in attr_map:
                        attr_map["Information Type"].set_value(it)
                    else:
                        attr = SrcAttribute()
                        attr.set_type("Information Type")
                        attr.set_value(it)
                        attrs.append(attr)

                if et:
                    if "Evidence Type" in attr_map:
                        attr_map["Evidence Type"].set_value(et)
                    else:
                        attr = SrcAttribute()
                        attr.set_type("Evidence Type")
                        attr.set_value(et)
                        attrs.append(attr)

                cit.set_attribute_list(attrs)

                if qy and qy.isdigit():
                    cit.set_confidence_level(int(qy))

                self.dbstate.db.commit_citation(cit, trans)
                applied_count += 1

        if applied_count == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(
                    _(
                        "No target attributes entered. Press 'Accept hints' or type "
                        "values into the target columns first."
                    )
                ),
                parent=self,
            )
            return

        OkDialog(
            str(_("Citation Attributes Updated")),
            str(_("Updated GPS attributes on %d citations in the database."))
            % applied_count,
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


# ------------------------------------------------------------
#
# Plugin Registration Classes for the Menu
#
# ------------------------------------------------------------
class CitationAttributesOptions(tool.ToolOptions):
    """Tool options for Citation Attributes menu plugin."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        super().__init__(name, person_id)


class CitationAttributesTool(tool.Tool):
    """Tool entry point launched from Gramps menu."""

    def __init__(
        self,
        dbstate: Any,
        user: Any,
        options_class: Any,
        name: str,
        callback: Any = None,
    ) -> None:
        super().__init__(dbstate, options_class, name)
        parent_window = user.uistate.window if hasattr(user, "uistate") else None
        dlg = CitationAttributesDialog(
            title=name,
            dbstate=dbstate,
            transient_for=parent_window,
        )
        dlg.show_dialog()
