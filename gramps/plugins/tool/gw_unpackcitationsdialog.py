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

"""Dialog to review and unpack conflated citation data (pages, dates, URLs, notes)."""

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
from gramps.plugins.tool.gwizardcitationshared import (
    add_note_once,
    delete_note_if_unused,
    parse_citation_date,
    ACCESS_DATE_REGEX as _ACCESS_DATE_REGEX,
    extract_access_date as _extract_access_date,
    extract_note_entry as _extract_note_entry,
    extract_url as _extract_url,
)

_ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext
LOG = logging.getLogger(__name__)


def _clean_page_field(raw_page: str, url: str, date_val: str) -> str:
    """Strip extracted URL and access date from raw page string."""
    cleaned = raw_page
    if url:
        cleaned = cleaned.replace(url, " ")
    # Strip "accessed <date>" prefixes (and the date they carry)
    cleaned = _ACCESS_DATE_REGEX.sub(" ", cleaned)
    if date_val:
        cleaned = cleaned.replace(date_val, " ")
    # Clean whitespace and stray punctuation
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t,.;:|-()")
    return cleaned


def plan_unpack_conflated_citations(db: Any) -> list[dict[str, Any]]:
    """Scan database for citations with conflated page/date/URL/note text."""
    source_titles: dict[str, tuple[str, str, str]] = {}
    for src in db.iter_sources():
        s_handle = str(src.get_handle() or "")
        title = str(src.get_title() or "")
        gid = str(src.get_gramps_id() or "")
        pub = str(src.get_publication_info() or "")
        source_titles[s_handle] = (title, gid, pub)

    plan: list[dict[str, Any]] = []
    for cit in db.iter_citations():
        c_handle = str(cit.get_handle() or "")
        c_gid = str(cit.get_gramps_id() or "")
        raw_page = str(cit.get_page() or "").strip()
        s_handle = str(cit.get_reference_handle() or "")
        src_info = source_titles.get(s_handle, ("(no source)", "", ""))
        src_title, src_gid, src_pub = src_info

        # Extract current date
        curr_date = ""
        try:
            d_obj = cit.get_date_object()
            if d_obj and hasattr(d_obj, "is_empty") and not d_obj.is_empty():
                from gramps.gen.datehandler import get_date

                curr_date = get_date(cit) or str(d_obj)
            elif d_obj and not hasattr(d_obj, "is_empty"):
                s = str(d_obj)
                if s and s != "0000-00-00":
                    curr_date = s
        except Exception:
            pass

        # Extract notes text
        notes_list = []
        note_entries: list[tuple[str, str]] = []
        for nh in cit.get_note_list() or []:
            try:
                note = db.get_note_from_handle(nh)
                if note:
                    ntxt = str(note.get() or "").strip()
                    if ntxt:
                        notes_list.append(ntxt)
                        note_entries.append((str(nh), ntxt))
            except Exception:
                pass
        notes_text = "\n".join(notes_list)
        drop_note_handles: list[str] = []

        # Look for conflated elements in raw_page, notes, or source pub info
        extracted_date = ""
        if not curr_date:
            extracted_date = _extract_access_date(raw_page) or _extract_access_date(
                notes_text, allow_timestamp=True
            )

        # Check if raw_page mixes URL and other text or an access date
        is_conflated = False
        suggested_page = ""
        suggested_date = extracted_date
        suggested_notes = ""
        clear_page = False

        if raw_page:
            url_in_page = _extract_url(raw_page)
            date_in_page = _extract_access_date(raw_page)
            if url_in_page or date_in_page:
                cleaned = _clean_page_field(raw_page, url_in_page, date_in_page)
                if url_in_page:
                    is_conflated = True
                    suggested_page = cleaned
                    if not cleaned:
                        clear_page = True
                    if not any(url_in_page in text for text in notes_list):
                        # Move the URL to a Citation Note if no note has it yet.
                        suggested_notes = url_in_page
                elif cleaned != raw_page:
                    is_conflated = True
                    suggested_page = cleaned
                if date_in_page and not curr_date:
                    is_conflated = True
                    suggested_date = date_in_page

        # Check if source pub info contains citation-style volume/page fragments
        if not raw_page and src_pub:
            from gramps.plugins.tool.gwizardcitationshared import (
                FIELD_CITATION_PATTERNS,
            )

            if FIELD_CITATION_PATTERNS.search(src_pub):
                is_conflated = True
                suggested_page = src_pub

        # Also flag citations where an archival entry or access date is embedded in notes
        if not is_conflated and (not raw_page or not curr_date):
            if not raw_page:
                entry_in_notes = _extract_note_entry(notes_text)
                if entry_in_notes:
                    is_conflated = True
                    suggested_page = entry_in_notes
            if not curr_date and extracted_date:
                is_conflated = True
                suggested_date = extracted_date

        if not is_conflated:
            continue

        hint_parts: list[str] = []
        if suggested_page and suggested_page != raw_page:
            hint_parts.append(
                _("Clean Volume/Page to '{page}'").format(page=suggested_page)
            )
        elif not raw_page and suggested_page:
            hint_parts.append(
                _("Set Volume/Page to '{page}'").format(page=suggested_page)
            )
        elif clear_page:
            hint_parts.append(_("Move URL from Volume/Page to notes"))
        if suggested_date and suggested_date != curr_date:
            hint_parts.append(_("Extract date '{date}'").format(date=suggested_date))
        if suggested_notes:
            hint_parts.append(
                _("Move URL '{url}' to notes").format(url=suggested_notes)
            )
        if drop_note_handles:
            hint_parts.append(_("Remove the note that only repeats the URL"))

        hint_text = (
            "\n".join(hint_parts) if hint_parts else _("Unpack citation elements")
        )

        # Build citation display string for column 0
        cit_parts = []
        if raw_page:
            cit_parts.append(raw_page)
        if curr_date and curr_date not in raw_page:
            cit_parts.append(curr_date)
        if c_gid:
            cit_parts.append(f"({c_gid})")

        citation_display = " | ".join(cit_parts) if cit_parts else f"({c_gid})"
        source_display = f"{src_title} ({src_gid})" if src_gid else src_title

        plan.append(
            {
                "citation_handle": c_handle,
                "citation_gid": c_gid,
                "source_handle": s_handle,
                "source_title": src_title,
                "source_gid": src_gid,
                "raw_page": raw_page,
                "curr_date": curr_date,
                "source_display": source_display,
                "citation_display": citation_display,
                "suggested_page": suggested_page,
                "clear_page": clear_page,
                "suggested_date": suggested_date,
                "suggested_notes": suggested_notes,
                "drop_note_handles": drop_note_handles,
                "hint_text": hint_text,
            }
        )

    # Sort by source name alphabetically
    plan.sort(key=lambda r: (r["source_title"] == "(no source)", r["source_title"]))
    return plan


# ------------------------------------------------------------
#
# UnpackCitationsDialog
#
# ------------------------------------------------------------
class UnpackCitationsDialog(Gtk.Dialog):
    """Review and unpack conflated citation data into citation, volume/page/URL, date, and notes."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Unpack Conflated Citation"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.plan = plan_unpack_conflated_citations(dbstate.db)
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1180, 480)

        # Action buttons in dialog action bar (always visible at bottom)
        n_hints = len(self.plan)
        self.accept_button = Gtk.Button(
            label=_("Accept hints ({number_of})").format(number_of=n_hints)
        )
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(n_hints > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        if not self.plan:
            done = Gtk.Label(label=str(_("No conflated citations found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(
                _("Conflated citations found: {number_of}").format(
                    number_of=len(self.plan)
                )
            )
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        # Header row above the scrolled grid
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(6)
        header_grid.set_row_spacing(0)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        src_head = Gtk.Label()
        src_head.set_markup("<b>%s</b>" % str(_("Source")))
        src_head.set_halign(Gtk.Align.START)
        src_head.set_hexpand(False)

        cit_head = Gtk.Label()
        cit_head.set_markup("<b>%s</b>" % str(_("Citation")))
        cit_head.set_halign(Gtk.Align.START)
        cit_head.set_hexpand(False)

        page_head = Gtk.Label()
        page_head.set_markup("<b>%s</b>" % str(_("Volume/Page/URL")))
        page_head.set_halign(Gtk.Align.START)
        page_head.set_hexpand(False)

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

        header_grid.attach(src_head, 0, 0, 1, 1)
        header_grid.attach(cit_head, 1, 0, 1, 1)
        header_grid.attach(page_head, 2, 0, 1, 1)
        header_grid.attach(date_head, 3, 0, 1, 1)
        header_grid.attach(notes_head, 4, 0, 1, 1)
        header_grid.attach(hint_head, 5, 0, 1, 1)
        content.add(header_grid)

        # SizeGroups ensuring header columns match data columns below
        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(6)
        ]
        self.column_sizegroups[0].add_widget(src_head)
        self.column_sizegroups[1].add_widget(cit_head)
        self.column_sizegroups[2].add_widget(page_head)
        self.column_sizegroups[3].add_widget(date_head)
        self.column_sizegroups[4].add_widget(notes_head)
        self.column_sizegroups[5].add_widget(hint_head)

        content.pack_start(self.build_rows(self.plan), True, True, 0)

        desc_text = (
            description
            if description is not None
            else str(
                _(
                    "Extract dates and URLs mixed into volume/page strings or "
                    "notes, and unpack citation fields."
                )
            )
        )
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

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build the data grid for reviewing and editing unpacked citations."""
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            # Column 0: Source details (Label)
            src_text = entry.get("source_display", "")
            src_label = Gtk.Label(label=src_text)
            src_label.set_halign(Gtk.Align.START)
            src_label.set_xalign(0.0)
            src_label.set_line_wrap(True)
            src_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            src_label.set_size_request(200, -1)
            src_label.set_max_width_chars(28)
            grid.attach(src_label, 0, row_index, 1, 1)

            # Column 1: Citation details (Label)
            cit_text = entry.get("citation_display", "")
            cit_label = Gtk.Label(label=cit_text)
            cit_label.set_halign(Gtk.Align.START)
            cit_label.set_xalign(0.0)
            cit_label.set_line_wrap(True)
            cit_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            cit_label.set_size_request(240, -1)
            cit_label.set_max_width_chars(32)
            grid.attach(cit_label, 1, row_index, 1, 1)

            # Column 2: Volume/Page/URL entry (empty by default)
            page_entry = Gtk.Entry()
            page_entry.set_width_chars(24)
            page_entry.set_text("")
            grid.attach(page_entry, 2, row_index, 1, 1)

            # Column 3: Date entry (empty by default)
            date_entry = Gtk.Entry()
            date_entry.set_width_chars(14)
            date_entry.set_text("")
            grid.attach(date_entry, 3, row_index, 1, 1)

            # Column 4: Notes entry (empty by default)
            notes_entry = Gtk.Entry()
            notes_entry.set_width_chars(20)
            notes_entry.set_text("")
            grid.attach(notes_entry, 4, row_index, 1, 1)

            # Column 5: Hint label
            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(240, -1)
            hint_label.set_max_width_chars(32)
            grid.attach(hint_label, 5, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(src_label)
                self.column_sizegroups[1].add_widget(cit_label)
                self.column_sizegroups[2].add_widget(page_entry)
                self.column_sizegroups[3].add_widget(date_entry)
                self.column_sizegroups[4].add_widget(notes_entry)
                self.column_sizegroups[5].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "page_entry": page_entry,
                    "date_entry": date_entry,
                    "notes_entry": notes_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(280)
        scrolled.set_min_content_width(1120)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        """Populate suggested values into target columns."""
        populated_count = 0
        for target in self.row_targets:
            item = target["entry"]
            sug_page = item.get("suggested_page", "")
            sug_date = item.get("suggested_date", "")
            sug_notes = item.get("suggested_notes", "")

            changed = False
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

    @reports_apply_errors
    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply target column data directly into citation records."""
        applied_count = 0
        with DbTxn(_("Unpack Conflated Citation"), self.dbstate.db) as trans:
            for target in self.row_targets:
                item = target["entry"]
                new_page = target["page_entry"].get_text().strip()
                new_date = target["date_entry"].get_text().strip()
                new_notes = target["notes_entry"].get_text().strip()

                if (
                    not new_page
                    and not new_date
                    and not new_notes
                    and not item.get("clear_page")
                ):
                    continue

                # The URL-only note is dropped only when its URL really
                # became the page; if the user typed something else it stays.
                drop = (
                    item.get("drop_note_handles", [])
                    if new_page == item.get("suggested_page")
                    else []
                )
                if apply_unpack_citation(
                    self.dbstate.db,
                    trans,
                    str(item.get("citation_handle")),
                    page=new_page,
                    date=new_date,
                    notes=new_notes,
                    drop_note_handles=drop,
                    clear_page=bool(item.get("clear_page") and not new_page),
                ):
                    applied_count += 1
                    # Clear the row so pressing Apply again cannot add the
                    # same note twice.
                    target["page_entry"].set_text("")
                    target["date_entry"].set_text("")
                    target["notes_entry"].set_text("")

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
            str(_("Citation Unpacking Complete")),
            ngettext(
                "Unpacked {number_of} conflated citation.",
                "Unpacked {number_of} conflated citations.",
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


def apply_unpack_citation(
    db: Any,
    trans: Any,
    citation_handle: str,
    page: str = "",
    date: str = "",
    notes: str = "",
    drop_note_handles: list[str] | tuple[str, ...] = (),
    clear_page: bool = False,
) -> bool:
    """Write unpacked page, date and note values into one citation.

    The one implementation used by the dialog's Apply button and by the
    no-review path. A URL note is only added if the citation has no note
    containing it, an identical note elsewhere is linked instead of copied,
    and notes listed in ``drop_note_handles`` (a note that merely repeats a
    URL now held in the page) are detached and deleted once unused.
    Returns True if the citation changed.
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
    date_obj = parse_citation_date(date)
    if date_obj is not None:
        cit.set_date_object(date_obj)
        modified = True
    elif (date or "").strip():
        LOG.warning("Ignoring unparseable date '%s'", date)
    if add_note_once(db, trans, cit, notes, skip_if_contained=True):
        modified = True
    dropped = []
    for note_handle in drop_note_handles:
        if note_handle in cit.get_note_list():
            cit.remove_note(note_handle)
            dropped.append(note_handle)
            modified = True
    if modified:
        db.commit_citation(cit, trans)
        for note_handle in dropped:
            delete_note_if_unused(db, trans, note_handle)
    return modified


def auto_unpack_citations(db: Any) -> int:
    """Accept every hint and apply it in one transaction (one undo).

    Errors are raised, not swallowed, so a failed step is reported as
    failed instead of "Unpacked 0". Returns the number of citations changed.
    """
    plan = plan_unpack_conflated_citations(db)
    changed = 0
    with DbTxn(_("Unpack Conflated Citation"), db) as trans:
        for item in plan:
            if apply_unpack_citation(
                db,
                trans,
                item["citation_handle"],
                page=item["suggested_page"],
                date=item["suggested_date"],
                notes=item["suggested_notes"],
                drop_note_handles=item["drop_note_handles"],
                clear_page=bool(item.get("clear_page")),
            ):
                changed += 1
    return changed
