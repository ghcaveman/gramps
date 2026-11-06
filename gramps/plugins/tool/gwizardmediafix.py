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

"""GWizard Media Fix tool: Find missing media, consolidate media locations, and apply filename standards."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
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
from gramps.gen.utils.file import media_path_full, relative_path, media_path
from gramps.gui.plug import tool
from gramps.gui.managedwindow import ManagedWindow

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# Helper utilities for media analysis
#
# ------------------------------------------------------------
def sanitize_standard_filename(path: str) -> str:
    """Return a sanitized standard filename (lowercase extension, clean spaces/chars)."""
    dirname, basename = os.path.split(path)
    name, ext = os.path.splitext(basename)
    # Lowercase standard extension
    ext = ext.lower()
    # Replace spaces with underscores and remove problematic filesystem characters
    clean_name = re.sub(r"[^\w\-\.]+", "_", name).strip("_")
    standard_basename = f"{clean_name}{ext}" if clean_name else f"media{ext}"
    return os.path.join(dirname, standard_basename) if dirname else standard_basename


# ------------------------------------------------------------
#
# FindMissingMediaDialog
#
# ------------------------------------------------------------
class FindMissingMediaDialog(Gtk.Dialog):
    """Review media records where the file is missing from disk."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Find Missing Media"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.rows: list[dict[str, Any]] = []
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1200, 480)

        # Scan database for missing media files
        base_dir = media_path(dbstate.db) if dbstate and dbstate.db else ""
        for media in dbstate.db.iter_media():
            m_handle = str(media.get_handle() or "")
            m_gid = str(media.get_gramps_id() or "")
            desc = str(media.get_description() or "")
            raw_path = str(media.get_path() or "")

            try:
                full_path = media_path_full(dbstate.db, raw_path)
            except Exception:
                full_path = raw_path

            if not os.path.exists(full_path):
                # Check if file exists in base media directory
                basename = os.path.basename(raw_path)
                sug_path = ""
                hint = _("File not found on disk")
                if base_dir and os.path.exists(os.path.join(base_dir, basename)):
                    sug_path = basename
                    hint = _("Found in media directory: suggest '%s'") % basename

                self.rows.append(
                    {
                        "handle": m_handle,
                        "gramps_id": m_gid,
                        "desc": desc,
                        "raw_path": raw_path,
                        "full_path": full_path,
                        "suggested_path": sug_path,
                        "hint_text": hint,
                    }
                )

        n_hints = sum(1 for r in self.rows if r.get("suggested_path"))
        self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
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
            label=str(
                _(
                    "Review media records whose files are missing on disk. "
                    "Type the updated path or click 'Accept hints' if found in the media directory, then press 'Apply'."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not self.rows:
            done = Gtk.Label(label=str(_("No missing media files found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(_("Total missing media records found: %d") % len(self.rows))
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        # Header grid
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(6)
        header_grid.set_row_spacing(0)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        media_head = Gtk.Label()
        media_head.set_markup("<b>%s</b>" % str(_("Media")))
        media_head.set_halign(Gtk.Align.START)

        path_head = Gtk.Label()
        path_head.set_markup("<b>%s</b>" % str(_("Current Path")))
        path_head.set_halign(Gtk.Align.START)

        new_path_head = Gtk.Label()
        new_path_head.set_markup("<b>%s</b>" % str(_("New Path")))
        new_path_head.set_halign(Gtk.Align.START)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(media_head, 0, 0, 1, 1)
        header_grid.attach(path_head, 1, 0, 1, 1)
        header_grid.attach(new_path_head, 2, 0, 1, 1)
        header_grid.attach(hint_head, 3, 0, 1, 1)
        content.add(header_grid)

        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(4)
        ]
        self.column_sizegroups[0].add_widget(media_head)
        self.column_sizegroups[1].add_widget(path_head)
        self.column_sizegroups[2].add_widget(new_path_head)
        self.column_sizegroups[3].add_widget(hint_head)

        content.pack_start(self.build_rows(self.rows), True, True, 0)

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            # Column 0: Media description & ID
            m_text = "%s (%s)" % (
                entry.get("desc") or _("(unnamed)"),
                entry.get("gramps_id", ""),
            )
            media_label = Gtk.Label(label=m_text)
            media_label.set_halign(Gtk.Align.START)
            media_label.set_xalign(0.0)
            media_label.set_line_wrap(True)
            media_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            media_label.set_size_request(200, -1)
            media_label.set_max_width_chars(26)
            grid.attach(media_label, 0, row_index, 1, 1)

            # Column 1: Current Path
            curr_label = Gtk.Label(label=entry.get("raw_path", ""))
            curr_label.set_halign(Gtk.Align.START)
            curr_label.set_xalign(0.0)
            curr_label.set_line_wrap(True)
            curr_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            curr_label.set_size_request(240, -1)
            curr_label.set_max_width_chars(32)
            grid.attach(curr_label, 1, row_index, 1, 1)

            # Column 2: New Path entry
            path_entry = Gtk.Entry()
            path_entry.set_width_chars(28)
            path_entry.set_text("")
            grid.attach(path_entry, 2, row_index, 1, 1)

            # Column 3: Hint label
            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(220, -1)
            hint_label.set_max_width_chars(28)
            grid.attach(hint_label, 3, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(media_label)
                self.column_sizegroups[1].add_widget(curr_label)
                self.column_sizegroups[2].add_widget(path_entry)
                self.column_sizegroups[3].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "path_entry": path_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(280)
        scrolled.set_min_content_width(960)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        count = 0
        for target in self.row_targets:
            sug = target["entry"].get("suggested_path", "")
            if sug and not target["path_entry"].get_text():
                target["path_entry"].set_text(sug)
                count += 1
        OkDialog(
            str(_("Hints accepted")),
            str(
                _("Populated paths for %d media records. Review and press Apply.")
                % count
            ),
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        applied = 0
        with DbTxn(_("Update Missing Media Paths"), self.dbstate.db) as trans:
            for target in self.row_targets:
                new_path = target["path_entry"].get_text().strip()
                if not new_path:
                    continue
                h = target["entry"].get("handle")
                try:
                    media = self.dbstate.db.get_media_from_handle(h)
                except Exception:
                    media = None
                if media is not None:
                    media.set_path(new_path)
                    self.dbstate.db.commit_media(media, trans)
                    applied += 1

        if applied == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(_("No paths entered. Press 'Accept hints' or enter paths first.")),
                parent=self,
            )
            return

        OkDialog(
            str(_("Media Paths Updated")),
            str(_("Updated %d media file paths in the database.") % applied),
            parent=self,
        )

    def show_dialog(self) -> None:
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
# ConsolidateMediaLocationDialog
#
# ------------------------------------------------------------
class ConsolidateMediaLocationDialog(Gtk.Dialog):
    """Review and consolidate absolute/scattered media paths into relative media directory paths."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Consolidate Media Location"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.rows: list[dict[str, Any]] = []
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1200, 480)

        base_dir = media_path(dbstate.db) if dbstate and dbstate.db else ""
        for media in dbstate.db.iter_media():
            m_handle = str(media.get_handle() or "")
            m_gid = str(media.get_gramps_id() or "")
            desc = str(media.get_description() or "")
            raw_path = str(media.get_path() or "")

            is_abs = os.path.isabs(raw_path)
            sug_path = ""
            hint = ""

            if is_abs and base_dir:
                try:
                    rel = relative_path(raw_path, base_dir)
                    if not os.path.isabs(rel) and not rel.startswith(".."):
                        sug_path = rel
                        hint = _("Absolute path: convert to relative '%s'") % rel
                    else:
                        hint = _("Absolute path outside base media directory")
                except Exception:
                    hint = _("Absolute path")
            elif not is_abs and ("\\" in raw_path or "/" in raw_path):
                # Standardize path separators
                std = raw_path.replace("\\", "/")
                if std != raw_path:
                    sug_path = std
                    hint = _("Standardize path separators")

            if sug_path or hint:
                self.rows.append(
                    {
                        "handle": m_handle,
                        "gramps_id": m_gid,
                        "desc": desc,
                        "raw_path": raw_path,
                        "suggested_path": sug_path,
                        "hint_text": hint,
                    }
                )

        n_hints = sum(1 for r in self.rows if r.get("suggested_path"))
        self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
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
            label=str(
                _(
                    "Review media records with hardcoded absolute or non-standard paths. "
                    "Press 'Accept hints' to convert them to relative paths within your media directory, then press 'Apply'."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not self.rows:
            done = Gtk.Label(label=str(_("All media paths are already consolidated.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(_("Total unconsolidated media paths: %d") % len(self.rows))
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(6)
        header_grid.set_row_spacing(0)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        media_head = Gtk.Label()
        media_head.set_markup("<b>%s</b>" % str(_("Media")))
        media_head.set_halign(Gtk.Align.START)

        path_head = Gtk.Label()
        path_head.set_markup("<b>%s</b>" % str(_("Current Path")))
        path_head.set_halign(Gtk.Align.START)

        new_path_head = Gtk.Label()
        new_path_head.set_markup("<b>%s</b>" % str(_("Consolidated Path")))
        new_path_head.set_halign(Gtk.Align.START)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(media_head, 0, 0, 1, 1)
        header_grid.attach(path_head, 1, 0, 1, 1)
        header_grid.attach(new_path_head, 2, 0, 1, 1)
        header_grid.attach(hint_head, 3, 0, 1, 1)
        content.add(header_grid)

        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(4)
        ]
        self.column_sizegroups[0].add_widget(media_head)
        self.column_sizegroups[1].add_widget(path_head)
        self.column_sizegroups[2].add_widget(new_path_head)
        self.column_sizegroups[3].add_widget(hint_head)

        content.pack_start(self.build_rows(self.rows), True, True, 0)

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            m_text = "%s (%s)" % (
                entry.get("desc") or _("(unnamed)"),
                entry.get("gramps_id", ""),
            )
            media_label = Gtk.Label(label=m_text)
            media_label.set_halign(Gtk.Align.START)
            media_label.set_xalign(0.0)
            media_label.set_line_wrap(True)
            media_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            media_label.set_size_request(200, -1)
            media_label.set_max_width_chars(26)
            grid.attach(media_label, 0, row_index, 1, 1)

            curr_label = Gtk.Label(label=entry.get("raw_path", ""))
            curr_label.set_halign(Gtk.Align.START)
            curr_label.set_xalign(0.0)
            curr_label.set_line_wrap(True)
            curr_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            curr_label.set_size_request(240, -1)
            curr_label.set_max_width_chars(32)
            grid.attach(curr_label, 1, row_index, 1, 1)

            path_entry = Gtk.Entry()
            path_entry.set_width_chars(28)
            path_entry.set_text("")
            grid.attach(path_entry, 2, row_index, 1, 1)

            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(220, -1)
            hint_label.set_max_width_chars(28)
            grid.attach(hint_label, 3, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(media_label)
                self.column_sizegroups[1].add_widget(curr_label)
                self.column_sizegroups[2].add_widget(path_entry)
                self.column_sizegroups[3].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "path_entry": path_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(280)
        scrolled.set_min_content_width(960)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        count = 0
        for target in self.row_targets:
            sug = target["entry"].get("suggested_path", "")
            if sug and not target["path_entry"].get_text():
                target["path_entry"].set_text(sug)
                count += 1
        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Populated consolidated paths for %d media records. Review and press Apply."
                )
                % count
            ),
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        applied = 0
        with DbTxn(_("Consolidate Media Locations"), self.dbstate.db) as trans:
            for target in self.row_targets:
                new_path = target["path_entry"].get_text().strip()
                if not new_path:
                    continue
                h = target["entry"].get("handle")
                try:
                    media = self.dbstate.db.get_media_from_handle(h)
                except Exception:
                    media = None
                if media is not None:
                    media.set_path(new_path)
                    self.dbstate.db.commit_media(media, trans)
                    applied += 1

        if applied == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(_("No paths entered. Press 'Accept hints' or enter paths first.")),
                parent=self,
            )
            return

        OkDialog(
            str(_("Media Locations Consolidated")),
            str(_("Consolidated %d media file paths in the database.") % applied),
            parent=self,
        )

    def show_dialog(self) -> None:
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
# ApplyFilenameStandardsDialog
#
# ------------------------------------------------------------
class ApplyFilenameStandardsDialog(Gtk.Dialog):
    """Review and apply standard naming conventions to media filenames."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Apply Filename Standards"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.rows: list[dict[str, Any]] = []
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1200, 480)

        for media in dbstate.db.iter_media():
            m_handle = str(media.get_handle() or "")
            m_gid = str(media.get_gramps_id() or "")
            desc = str(media.get_description() or "")
            raw_path = str(media.get_path() or "")

            if not raw_path:
                continue

            std_path = sanitize_standard_filename(raw_path)
            if std_path != raw_path:
                self.rows.append(
                    {
                        "handle": m_handle,
                        "gramps_id": m_gid,
                        "desc": desc,
                        "raw_path": raw_path,
                        "suggested_path": std_path,
                        "hint_text": _("Standardize filename to '%s'")
                        % os.path.basename(std_path),
                    }
                )

        n_hints = len(self.rows)
        self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(n_hints > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.APPLY)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        info = Gtk.Label(
            label=str(
                _(
                    "Review media filenames with irregular characters, spaces, or uppercase extensions. "
                    "Press 'Accept hints' to format standard filenames, then press 'Apply'."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not self.rows:
            done = Gtk.Label(
                label=str(_("All media filenames already meet standards."))
            )
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(_("Total non-standard media filenames: %d") % len(self.rows))
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(6)
        header_grid.set_row_spacing(0)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        media_head = Gtk.Label()
        media_head.set_markup("<b>%s</b>" % str(_("Media")))
        media_head.set_halign(Gtk.Align.START)

        curr_head = Gtk.Label()
        curr_head.set_markup("<b>%s</b>" % str(_("Current Filename")))
        curr_head.set_halign(Gtk.Align.START)

        std_head = Gtk.Label()
        std_head.set_markup("<b>%s</b>" % str(_("Standard Filename")))
        std_head.set_halign(Gtk.Align.START)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(media_head, 0, 0, 1, 1)
        header_grid.attach(curr_head, 1, 0, 1, 1)
        header_grid.attach(std_head, 2, 0, 1, 1)
        header_grid.attach(hint_head, 3, 0, 1, 1)
        content.add(header_grid)

        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(4)
        ]
        self.column_sizegroups[0].add_widget(media_head)
        self.column_sizegroups[1].add_widget(curr_head)
        self.column_sizegroups[2].add_widget(std_head)
        self.column_sizegroups[3].add_widget(hint_head)

        content.pack_start(self.build_rows(self.rows), True, True, 0)

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            m_text = "%s (%s)" % (
                entry.get("desc") or _("(unnamed)"),
                entry.get("gramps_id", ""),
            )
            media_label = Gtk.Label(label=m_text)
            media_label.set_halign(Gtk.Align.START)
            media_label.set_xalign(0.0)
            media_label.set_line_wrap(True)
            media_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            media_label.set_size_request(200, -1)
            media_label.set_max_width_chars(26)
            grid.attach(media_label, 0, row_index, 1, 1)

            curr_label = Gtk.Label(label=entry.get("raw_path", ""))
            curr_label.set_halign(Gtk.Align.START)
            curr_label.set_xalign(0.0)
            curr_label.set_line_wrap(True)
            curr_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            curr_label.set_size_request(240, -1)
            curr_label.set_max_width_chars(32)
            grid.attach(curr_label, 1, row_index, 1, 1)

            std_entry = Gtk.Entry()
            std_entry.set_width_chars(28)
            std_entry.set_text("")
            grid.attach(std_entry, 2, row_index, 1, 1)

            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(220, -1)
            hint_label.set_max_width_chars(28)
            grid.attach(hint_label, 3, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(media_label)
                self.column_sizegroups[1].add_widget(curr_label)
                self.column_sizegroups[2].add_widget(std_entry)
                self.column_sizegroups[3].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "std_entry": std_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(280)
        scrolled.set_min_content_width(960)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        count = 0
        for target in self.row_targets:
            sug = target["entry"].get("suggested_path", "")
            if sug and not target["std_entry"].get_text():
                target["std_entry"].set_text(sug)
                count += 1
        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Populated standard filenames for %d media records. Review and press Apply."
                )
                % count
            ),
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        applied = 0
        with DbTxn(_("Apply Filename Standards"), self.dbstate.db) as trans:
            for target in self.row_targets:
                new_path = target["std_entry"].get_text().strip()
                if not new_path:
                    continue
                h = target["entry"].get("handle")
                try:
                    media = self.dbstate.db.get_media_from_handle(h)
                except Exception:
                    media = None
                if media is not None:
                    media.set_path(new_path)
                    self.dbstate.db.commit_media(media, trans)
                    applied += 1

        if applied == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(
                    _(
                        "No filenames entered. Press 'Accept hints' or enter filenames first."
                    )
                ),
                parent=self,
            )
            return

        OkDialog(
            str(_("Filename Standards Applied")),
            str(_("Updated %d media filenames in the database.") % applied),
            parent=self,
        )

    def show_dialog(self) -> None:
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
# GWizardMediaFix Window Controller
#
# ------------------------------------------------------------
class GWizardMediaFixOptions(tool.ToolOptions):
    """Tool options for GWizard Media Fix."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        super().__init__(name, person_id)


class GWizardMediaFix(tool.Tool, ManagedWindow):
    """Top-level GWizard Media Fix tool window."""

    def __init__(
        self,
        dbstate: Any,
        user: Any,
        options_class: Any,
        name: str,
        callback: Any = None,
    ) -> None:
        uistate = user.uistate
        tool.Tool.__init__(self, dbstate, options_class, name)
        ManagedWindow.__init__(self, uistate, [], self.__class__, modal=True)
        self.dbstate = dbstate
        self._build_window(uistate)
        self.show()

    def _build_window(self, uistate: Any) -> None:
        dialog = Gtk.Dialog(
            title=str(_("GWizard Media Fix")),
            transient_for=uistate.window,
            modal=True,
            destroy_with_parent=True,
        )
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(8)

        desc = Gtk.Label(
            label=str(
                _(
                    "Comprehensive utility to find missing media files on disk, consolidate "
                    "media storage locations into relative paths, and enforce standardized filename formats."
                )
            )
        )
        desc.set_line_wrap(True)
        desc.set_halign(Gtk.Align.START)
        content.add(desc)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.pack_start(vbox, True, True, 0)

        specs = [
            ("find_missing", str(_("Find missing media"))),
            ("consolidate_location", str(_("Consolidate media location"))),
            ("apply_standards", str(_("Apply filename standards"))),
        ]

        self.buttons: dict[str, Gtk.Button] = {}
        for key, label in specs:
            button = Gtk.Button(label=label)
            button.set_hexpand(True)
            button.connect("clicked", self.cb_button, key)
            vbox.pack_start(button, False, False, 0)
            self.buttons[key] = button

        dialog.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        dialog.connect("response", self.cb_close)

        self.set_window(dialog, None, str(_("GWizard Media Fix")))
        self.setup_configs("interface.gwizardmediafix", 420, 240)
        dialog.show_all()

    def cb_close(self, dialog: Gtk.Dialog, response: int) -> None:
        self.close()

    def cb_button(self, button: Gtk.Button, key: str) -> None:
        if key == "find_missing":
            dlg = FindMissingMediaDialog(
                title=str(_("Find Missing Media")),
                dbstate=self.dbstate,
                transient_for=self.window,
            )
            dlg.show_dialog()
        elif key == "consolidate_location":
            dlg = ConsolidateMediaLocationDialog(
                title=str(_("Consolidate Media Location")),
                dbstate=self.dbstate,
                transient_for=self.window,
            )
            dlg.show_dialog()
        elif key == "apply_standards":
            dlg = ApplyFilenameStandardsDialog(
                title=str(_("Apply Filename Standards")),
                dbstate=self.dbstate,
                transient_for=self.window,
            )
            dlg.show_dialog()
