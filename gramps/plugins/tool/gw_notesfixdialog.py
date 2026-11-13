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

"""Dialog to review and fix note issues (import debris, empty notes, whitespace)."""

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
    is_bare_url_text,
    is_debris_text,
    note_text,
)

_ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext
LOG = logging.getLogger(__name__)


def _url_already_in_every_citation_page(db: Any, note_handle: str, url: str) -> bool:
    """True when every user of the note is a citation whose page holds ``url``."""
    users = list(db.find_backlink_handles(note_handle))
    if not users:
        return False
    for class_name, handle in users:
        if class_name != "Citation":
            return False
        citation = db.get_citation_from_handle(handle)
        if citation is None or url not in str(citation.get_page() or ""):
            return False
    return True


def build_note_fix_rows(db: Any) -> list[dict[str, Any]]:
    """Find notes with problems: import debris, empty, padded, or a repeated URL."""
    rows: list[dict[str, Any]] = []
    for note in db.iter_notes():
        n_handle = str(note.get_handle() or "")
        n_gid = str(note.get_gramps_id() or "")
        raw_text = note_text(note)
        n_type = str(note.get_type()) if hasattr(note, "get_type") else "Note"

        suggested_action = ""
        suggested_text = ""
        hint_text = ""
        problem = None

        stripped = raw_text.strip()
        if not stripped:
            # Empty note
            suggested_action = _("Purge")
            suggested_text = _("[Purge note]")
            hint_text = _("Empty note (suggest Purge)")
            problem = "empty"
        elif is_debris_text(stripped):
            # Automated migration/export debris note
            suggested_action = _("Purge")
            suggested_text = _("[Purge note]")
            hint_text = _("Import debris / migration log (suggest Purge)")
            problem = "debris"
        elif is_bare_url_text(stripped) and _url_already_in_every_citation_page(
            db, n_handle, stripped
        ):
            # The same web address is already in the Volume/Page field of
            # every citation that uses this note, so the note repeats it.
            suggested_action = _("Purge")
            suggested_text = _("[Purge note]")
            hint_text = _("Web address already in the citation page (suggest Purge)")
            problem = "duplicate_url"
        elif raw_text != stripped:
            # Leading or trailing whitespace
            suggested_action = _("Trim")
            suggested_text = stripped
            hint_text = _("Leading/trailing whitespace (suggest Trim)")
            problem = "whitespace"

        if not problem:
            continue

        display_lines = [
            f"{n_gid} ({n_type})",
            (
                stripped[:160] + ("..." if len(stripped) > 160 else "")
                if stripped
                else _("(empty)")
            ),
        ]

        rows.append(
            {
                "note_handle": n_handle,
                "gramps_id": n_gid,
                "note_type": n_type,
                "raw_text": raw_text,
                "display_text": "\n".join(display_lines),
                "suggested_action": suggested_action,
                "suggested_text": suggested_text,
                "hint_text": hint_text,
                "problem": problem,
            }
        )

    # Sort by problem type, then Gramps ID
    rows.sort(key=lambda r: (r["problem"] != "debris", r["gramps_id"]))
    return rows


# ------------------------------------------------------------
#
# NotesFixDialog
#
# ------------------------------------------------------------
class NotesFixDialog(Gtk.Dialog):
    """Review and fix notes: current text, target text box, hint, Accept and Apply."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Fix Notes"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.rows = build_note_fix_rows(dbstate.db)
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1400, 520)

        # Action buttons in dialog action bar (always visible at bottom)
        n_hints = len(self.rows)
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

        if not self.rows:
            done = Gtk.Label(label=str(_("No note problems found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(
                _("Problem notes found: {number_of}").format(number_of=len(self.rows))
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

        from_head = Gtk.Label()
        from_head.set_markup("<b>%s</b>" % str(_("Note")))
        from_head.set_halign(Gtk.Align.START)
        from_head.set_hexpand(False)

        action_head = Gtk.Label()
        action_head.set_markup("<b>%s</b>" % str(_("Action")))
        action_head.set_halign(Gtk.Align.START)
        action_head.set_hexpand(False)

        to_head = Gtk.Label()
        to_head.set_markup("<b>%s</b>" % str(_("Note")))
        to_head.set_halign(Gtk.Align.START)
        to_head.set_hexpand(False)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(from_head, 0, 0, 1, 1)
        header_grid.attach(action_head, 1, 0, 1, 1)
        header_grid.attach(to_head, 2, 0, 1, 1)
        header_grid.attach(hint_head, 3, 0, 1, 1)
        content.add(header_grid)

        # SizeGroups ensuring header columns match data columns below
        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(4)
        ]
        self.column_sizegroups[0].add_widget(from_head)
        self.column_sizegroups[1].add_widget(action_head)
        self.column_sizegroups[2].add_widget(to_head)
        self.column_sizegroups[3].add_widget(hint_head)

        content.pack_start(self.build_rows(self.rows), True, True, 0)

        desc_text = (
            description
            if description is not None
            else str(_("Remove import debris and convert bare-URL notes."))
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
        """Build the data grid for reviewing and editing notes."""
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            # Column 0: From (Current Note) - Label
            from_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            from_box.set_size_request(320, -1)
            lines = entry.get("display_text", "").splitlines()
            l1 = Gtk.Label(label=lines[0] if len(lines) > 0 else "")
            l1.set_xalign(0.0)
            l1.set_line_wrap(True)
            l1.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l1.set_max_width_chars(42)
            from_box.pack_start(l1, False, False, 0)

            l2 = Gtk.Label(label=lines[1] if len(lines) > 1 else "")
            l2.set_xalign(0.0)
            l2.set_line_wrap(True)
            l2.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            l2.set_max_width_chars(42)
            from_box.pack_start(l2, False, False, 0)

            grid.attach(from_box, 0, row_index, 1, 1)

            # Column 1: To (Action) - Entry (empty by default)
            action_entry = Gtk.Entry()
            action_entry.set_width_chars(12)
            action_entry.set_text("")
            grid.attach(action_entry, 1, row_index, 1, 1)

            # Column 2: To (New Text) - Entry (empty by default)
            text_entry = Gtk.Entry()
            text_entry.set_width_chars(32)
            text_entry.set_text("")
            grid.attach(text_entry, 2, row_index, 1, 1)

            # Column 3: Hint - Label
            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(240, -1)
            hint_label.set_max_width_chars(32)
            grid.attach(hint_label, 3, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(from_box)
                self.column_sizegroups[1].add_widget(action_entry)
                self.column_sizegroups[2].add_widget(text_entry)
                self.column_sizegroups[3].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "action_entry": action_entry,
                    "text_entry": text_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(300)
        scrolled.set_min_content_width(1200)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        """Populate suggested values into target textboxes."""
        populated_count = 0
        for target in self.row_targets:
            item = target["entry"]
            sug_action = item.get("suggested_action", "")
            sug_text = item.get("suggested_text", "")

            changed = False
            if sug_action and not target["action_entry"].get_text():
                target["action_entry"].set_text(sug_action)
                changed = True
            if sug_text and not target["text_entry"].get_text():
                target["text_entry"].set_text(sug_text)
                changed = True

            if changed:
                populated_count += 1

        OkDialog(
            str(_("Hints accepted")),
            ngettext(
                "Filled in suggested actions for {number_of} note. Review or edit "
                "them, then press Apply.",
                "Filled in suggested actions for {number_of} notes. Review or edit "
                "them, then press Apply.",
                populated_count,
            ).format(number_of=populated_count),
            parent=self,
        )

    @reports_apply_errors
    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply target column data directly into note records in the database."""
        applied_count = 0
        with DbTxn(_("Fix Notes"), self.dbstate.db) as trans:
            for target in self.row_targets:
                item = target["entry"]
                if apply_note_fix(
                    self.dbstate.db,
                    trans,
                    str(item.get("note_handle") or ""),
                    action=target["action_entry"].get_text(),
                    new_text=target["text_entry"].get_text(),
                    raw_text=item.get("raw_text", ""),
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
            str(_("Note fixes applied")),
            ngettext(
                "Updated or removed {number_of} note.",
                "Updated or removed {number_of} notes.",
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


def apply_note_fix(
    db: Any,
    trans: Any,
    note_handle: str,
    action: str = "",
    new_text: str = "",
    raw_text: str = "",
) -> bool:
    """Purge, trim or rewrite one note; the one implementation for all callers.

    ``action`` is ``purge`` or ``trim`` (any case). A purge detaches the note
    from every object that uses it, then deletes it. Returns True if the
    note was changed or removed.
    """
    act = (action or "").strip().lower()
    new_text = (new_text or "").strip()
    if not act and not new_text:
        return False
    try:
        note = db.get_note_from_handle(note_handle)
    except HandleError:
        note = None
    if note is None:
        return False
    if act == "purge" or new_text.lower() == "[purge note]":
        for class_name, parent_handle in list(db.find_backlink_handles(note_handle)):
            getter = getattr(db, "get_%s_from_handle" % class_name.lower(), None)
            commit = getattr(db, "commit_%s" % class_name.lower(), None)
            if getter and commit:
                parent = getter(parent_handle)
                if parent is not None:
                    parent.remove_handle_references("Note", [note_handle])
                    commit(parent, trans)
        db.remove_note(note_handle, trans)
        return True
    if new_text and new_text != raw_text:
        note.set(new_text)
        db.commit_note(note, trans)
        return True
    if act == "trim":
        note.set(str(note.get() or "").strip())
        db.commit_note(note, trans)
        return True
    return False


def auto_fix_notes(db: Any) -> int:
    """Accept every hint and apply it in one transaction (one undo).

    Returns the number of notes changed or removed.
    """
    changed = 0
    with DbTxn(_("Fix Notes"), db) as trans:
        for row in build_note_fix_rows(db):
            if apply_note_fix(
                db,
                trans,
                row["note_handle"],
                # Fixed codes, not the translated button text.
                action="trim" if row["problem"] == "whitespace" else "purge",
                raw_text=row["raw_text"],
            ):
                changed += 1
    return changed
