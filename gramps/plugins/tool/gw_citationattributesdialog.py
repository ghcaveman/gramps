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

"""Tool and dialog for assigning GPS citation attributes."""

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
from gramps.plugins.tool.gwizard_common import reports_apply_errors
from gramps.gen.db import DbTxn
from gramps.gen.errors import HandleError
from gramps.gen.lib import SrcAttribute
from gramps.gui.plug import tool
from gramps.plugins.tool.gwizardcitationshared import note_text

_ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext
LOG = logging.getLogger(__name__)


_CONF_TO_QUAY = {0: "0(0)", 1: "1(1)", 2: "2(-)", 3: "3(2)", 4: "4(3)"}


def limit_quay_to_current(suggested: str, current_conf: int) -> str:
    """Return the QUAY text to apply, never raising an existing confidence.

    Confidence set earlier (for example lowered on tree citations) is not
    overwritten, and a suggestion equal to the current level returns "" so
    the citation is not rewritten for nothing.
    """
    digits = "".join(ch for ch in (suggested or "").split("(")[0] if ch.isdigit())
    if not digits:
        return ""
    level = max(0, min(int(digits), 4))
    if level >= current_conf:
        return ""
    return _CONF_TO_QUAY[level]


def suggest_citation_attributes(
    src_title: str, cit_page: str, cit_text: str, curr_conf: int
) -> dict[str, str]:
    """Suggest GPS Source, Information and Evidence Type and QUAY for a citation."""
    text_corpus = f"{src_title} {cit_page} {cit_text}".lower()

    # 1. User Trees ("geni" must be a whole word, not part of "genealogy")
    if re.search(r"\bgeni(?:\.com)?\b", text_corpus) or any(
        k in text_corpus
        for k in [
            "family tree",
            "member tree",
            "public tree",
            "user tree",
            "wikitree",
        ]
    ):
        return {
            "source_type": "Authored",
            "info_type": "Secondary",
            "evidence_type": "Indirect",
            "quay": "1(1)",
            "hint_text": _(
                "Online compiled tree (suggest Authored, Secondary, Indirect)"
            ),
        }

    # 1b. Indexes and databases are derivative, even of a certificate
    if (
        any(k in text_corpus for k in ["index", "database", "abstract", "transcri"])
        and "census" not in text_corpus
    ):
        return {
            "source_type": "Derivative",
            "info_type": "Secondary",
            "evidence_type": "Direct",
            "quay": "2(-)",
            "hint_text": _("Index/database (suggest Derivative, Secondary, Direct)"),
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
            "draft registration",
            "draft cards",
            "naturalization",
            "church and town records",
            "church records",
            "passenger",
            "manifest",
            "border crossing",
            "compensation application",
        ]
    ):
        return {
            "source_type": "Original",
            "info_type": "Primary",
            "evidence_type": "Direct",
            "quay": "4(3)",
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
                "quay": "2(-)",
                "hint_text": _(
                    "Census index/database (suggest Derivative, Secondary, Direct)"
                ),
            }
        return {
            "source_type": "Original",
            "info_type": "Primary",
            "evidence_type": "Direct",
            "quay": "4(3)",
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
            "quay": "2(-)",
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
            "quay": "2(-)",
            "hint_text": _(
                "Compiled history/book (suggest Authored, Secondary, Indirect)"
            ),
        }

    return {
        "source_type": "",
        "info_type": "",
        "evidence_type": "",
        "quay": "",
        "hint_text": _("No keywords matched to infer GPS attributes"),
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
        raw_conf = cit.get_confidence_level()
        conf = 2 if raw_conf is None else int(raw_conf)
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
            _("Citation: {page} ({gramps_id}) | Confidence: {confidence}").format(
                page=page or "—", gramps_id=c_gid, confidence=conf
            ),
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
                "suggested_quay": limit_quay_to_current(sug["quay"], conf),
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
        self.set_default_size(1285, 520)

        n_hints = sum(1 for r in self.rows if not r["has_all"])
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

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        if not self.rows:
            done = Gtk.Label(label=str(_("No citations found in database.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(
                _("Citations: {citations} | Needing GPS attributes: {needing}").format(
                    citations=len(self.rows), needing=n_hints
                )
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

        curr_st_head = Gtk.Label()
        curr_st_head.set_markup("<b>%s</b>" % str(_("Source")))
        curr_st_head.set_halign(Gtk.Align.START)
        curr_st_head.set_hexpand(False)

        curr_it_head = Gtk.Label()
        curr_it_head.set_markup("<b>%s</b>" % str(_("Information")))
        curr_it_head.set_halign(Gtk.Align.START)
        curr_it_head.set_hexpand(False)

        curr_et_head = Gtk.Label()
        curr_et_head.set_markup("<b>%s</b>" % str(_("Evidence")))
        curr_et_head.set_halign(Gtk.Align.START)
        curr_et_head.set_hexpand(False)

        curr_conf_head = Gtk.Label()
        curr_conf_head.set_markup("<b>%s</b>" % str(_("Conf(Q)")))
        curr_conf_head.set_halign(Gtk.Align.START)
        curr_conf_head.set_hexpand(False)

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
        quay_head.set_markup("<b>%s</b>" % str(_("Conf(Q)")))
        quay_head.set_halign(Gtk.Align.START)
        quay_head.set_hexpand(False)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(src_head, 0, 0, 1, 1)
        header_grid.attach(curr_st_head, 1, 0, 1, 1)
        header_grid.attach(curr_it_head, 2, 0, 1, 1)
        header_grid.attach(curr_et_head, 3, 0, 1, 1)
        header_grid.attach(curr_conf_head, 4, 0, 1, 1)
        header_grid.attach(st_head, 5, 0, 1, 1)
        header_grid.attach(it_head, 6, 0, 1, 1)
        header_grid.attach(et_head, 7, 0, 1, 1)
        header_grid.attach(quay_head, 8, 0, 1, 1)
        header_grid.attach(hint_head, 9, 0, 1, 1)
        content.add(header_grid)

        # SizeGroups to lock headers to data columns below
        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(10)
        ]
        self.column_sizegroups[0].add_widget(src_head)
        self.column_sizegroups[1].add_widget(curr_st_head)
        self.column_sizegroups[2].add_widget(curr_it_head)
        self.column_sizegroups[3].add_widget(curr_et_head)
        self.column_sizegroups[4].add_widget(curr_conf_head)
        self.column_sizegroups[5].add_widget(st_head)
        self.column_sizegroups[6].add_widget(it_head)
        self.column_sizegroups[7].add_widget(et_head)
        self.column_sizegroups[8].add_widget(quay_head)
        self.column_sizegroups[9].add_widget(hint_head)

        content.pack_start(self.build_rows(self.rows), True, True, 0)

        hint_footer = Gtk.Label(
            label=str(
                _(
                    "Press 'Accept hints' to populate suggested Genealogical Proof "
                    "Standard (GPS) attributes into the target columns, "
                    "edit any values as needed, then press 'Apply' to update "
                    "citations in the database."
                )
            )
        )
        hint_footer.set_line_wrap(True)
        hint_footer.set_halign(Gtk.Align.START)
        hint_footer.set_size_request(-1, 45)
        content.pack_start(hint_footer, False, False, 0)

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build the grid: current values as labels, targets as text boxes, hints."""
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            # Column 0: Source & Citation details (Input - Label)
            src_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            src_box.set_size_request(220, -1)
            lines = entry.get("display_text", "").splitlines()
            l1 = Gtk.Label(label=lines[0] if len(lines) > 0 else "")
            l1.set_xalign(0.0)
            l1.set_line_wrap(True)
            l1.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l1.set_max_width_chars(30)
            src_box.pack_start(l1, False, False, 0)

            l2 = Gtk.Label(label=lines[1] if len(lines) > 1 else "")
            l2.set_xalign(0.0)
            l2.set_line_wrap(True)
            l2.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l2.set_max_width_chars(30)
            src_box.pack_start(l2, False, False, 0)

            grid.attach(src_box, 0, row_index, 1, 1)

            # Column 1: Existing Source Type
            curr_st = entry.get("curr_attrs", {}).get("Source Type", "") or "—"
            curr_st_label = Gtk.Label(label=curr_st)
            curr_st_label.set_halign(Gtk.Align.START)
            curr_st_label.set_xalign(0.0)
            curr_st_label.set_max_width_chars(12)
            curr_st_label.set_size_request(85, -1)
            grid.attach(curr_st_label, 1, row_index, 1, 1)

            # Column 2: Existing Information Type
            curr_it = entry.get("curr_attrs", {}).get("Information Type", "") or "—"
            curr_it_label = Gtk.Label(label=curr_it)
            curr_it_label.set_halign(Gtk.Align.START)
            curr_it_label.set_xalign(0.0)
            curr_it_label.set_max_width_chars(12)
            curr_it_label.set_size_request(85, -1)
            grid.attach(curr_it_label, 2, row_index, 1, 1)

            # Column 3: Existing Evidence Type
            curr_et = entry.get("curr_attrs", {}).get("Evidence Type", "") or "—"
            curr_et_label = Gtk.Label(label=curr_et)
            curr_et_label.set_halign(Gtk.Align.START)
            curr_et_label.set_xalign(0.0)
            curr_et_label.set_max_width_chars(12)
            curr_et_label.set_size_request(85, -1)
            grid.attach(curr_et_label, 3, row_index, 1, 1)

            # Column 4: Existing Conf(Q)
            curr_quay = entry.get("curr_attrs", {}).get("QUAY", "")
            conf_val = entry.get("confidence", 2)
            if curr_quay:
                curr_conf_text = (
                    curr_quay if "(" in curr_quay else f"{conf_val}({curr_quay})"
                )
            else:
                curr_conf_text = _CONF_TO_QUAY.get(conf_val, f"{conf_val}(-)")
            curr_conf_label = Gtk.Label(label=curr_conf_text)
            curr_conf_label.set_halign(Gtk.Align.START)
            curr_conf_label.set_xalign(0.0)
            curr_conf_label.set_max_width_chars(8)
            curr_conf_label.set_size_request(60, -1)
            grid.attach(curr_conf_label, 4, row_index, 1, 1)

            # Column 5: Source Type - Entry (empty by default)
            st_entry = Gtk.Entry()
            st_entry.set_width_chars(14)
            st_entry.set_text("")
            grid.attach(st_entry, 5, row_index, 1, 1)

            # Column 6: Information Type - Entry (empty by default)
            it_entry = Gtk.Entry()
            it_entry.set_width_chars(14)
            it_entry.set_text("")
            grid.attach(it_entry, 6, row_index, 1, 1)

            # Column 7: Evidence Type - Entry (empty by default)
            et_entry = Gtk.Entry()
            et_entry.set_width_chars(14)
            et_entry.set_text("")
            grid.attach(et_entry, 7, row_index, 1, 1)

            # Column 8: QUAY - Entry (empty by default)
            quay_entry = Gtk.Entry()
            quay_entry.set_width_chars(6)
            quay_entry.set_text("")
            grid.attach(quay_entry, 8, row_index, 1, 1)

            # Column 9: Hint - Label
            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(220, -1)
            hint_label.set_max_width_chars(30)
            grid.attach(hint_label, 9, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(src_box)
                self.column_sizegroups[1].add_widget(curr_st_label)
                self.column_sizegroups[2].add_widget(curr_it_label)
                self.column_sizegroups[3].add_widget(curr_et_label)
                self.column_sizegroups[4].add_widget(curr_conf_label)
                self.column_sizegroups[5].add_widget(st_entry)
                self.column_sizegroups[6].add_widget(it_entry)
                self.column_sizegroups[7].add_widget(et_entry)
                self.column_sizegroups[8].add_widget(quay_entry)
                self.column_sizegroups[9].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "curr_st_label": curr_st_label,
                    "curr_it_label": curr_it_label,
                    "curr_et_label": curr_et_label,
                    "curr_conf_label": curr_conf_label,
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
        scrolled.set_min_content_width(1220)
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
            ngettext(
                "Filled in suggested GPS attributes for {number_of} citation. Review "
                "or edit them, then press Apply.",
                "Filled in suggested GPS attributes for {number_of} citations. Review "
                "or edit them, then press Apply.",
                populated_count,
            ).format(number_of=populated_count),
            parent=self,
        )

    @reports_apply_errors
    def cb_apply(self, _button: Gtk.Button) -> None:
        """Write the target column values into the citations' attributes."""
        applied_count = 0
        with DbTxn(_("Update Citation Attributes"), self.dbstate.db) as trans:
            for target in self.row_targets:
                item = target["entry"]
                if apply_citation_attributes(
                    self.dbstate.db,
                    trans,
                    str(item.get("citation_handle") or ""),
                    src_type=target["st_entry"].get_text(),
                    info_type=target["it_entry"].get_text(),
                    ev_type=target["et_entry"].get_text(),
                    quay=target["quay_entry"].get_text(),
                ):
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
            ngettext(
                "Updated GPS attributes on {number_of} citation.",
                "Updated GPS attributes on {number_of} citations.",
                applied_count,
            ).format(number_of=applied_count),
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


_ATTRIBUTE_NAMES = (
    ("src_type", "Source Type"),
    ("info_type", "Information Type"),
    ("ev_type", "Evidence Type"),
)


def apply_citation_attributes(
    db: Any,
    trans: Any,
    citation_handle: str,
    src_type: str = "",
    info_type: str = "",
    ev_type: str = "",
    quay: str = "",
) -> bool:
    """Set GPS attributes and confidence on one citation; blanks are skipped.

    The one implementation used by the dialog's Apply button and by the
    no-review path. QUAY is the citation's confidence level, not a separate
    attribute. Returns True only when something actually changed.
    """
    try:
        cit = db.get_citation_from_handle(citation_handle)
    except HandleError:
        cit = None
    if cit is None:
        return False
    values = {"src_type": src_type, "info_type": info_type, "ev_type": ev_type}
    attrs = list(cit.get_attribute_list() or [])
    attr_map = {str(a.get_type() or ""): a for a in attrs}
    modified = False
    for key, name in _ATTRIBUTE_NAMES:
        value = (values[key] or "").strip()
        if not value:
            continue
        if name in attr_map:
            if attr_map[name].get_value() != value:
                attr_map[name].set_value(value)
                modified = True
        else:
            attr = SrcAttribute()
            attr.set_type(name)
            attr.set_value(value)
            attrs.append(attr)
            modified = True
    if modified:
        cit.set_attribute_list(attrs)
    digits = "".join(c for c in (quay or "").strip().split("(")[0] if c.isdigit())
    if digits:
        level = max(0, min(int(digits), 4))
        if level != cit.get_confidence_level():
            cit.set_confidence_level(level)
            modified = True
    if modified:
        db.commit_citation(cit, trans)
    return modified


def auto_citation_attributes(db: Any) -> int:
    """Accept every hint and apply it in one transaction (one undo).

    Returns the number of citations that changed.
    """
    changed = 0
    with DbTxn(_("Update Citation Attributes"), db) as trans:
        for item in build_citation_attribute_rows(db):
            if apply_citation_attributes(
                db,
                trans,
                str(item.get("citation_handle") or ""),
                src_type=item.get("suggested_src_type", ""),
                info_type=item.get("suggested_info_type", ""),
                ev_type=item.get("suggested_ev_type", ""),
                quay=item.get("suggested_quay", ""),
            ):
                changed += 1
    return changed
