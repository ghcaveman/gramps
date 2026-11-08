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

"""Fix Media References dialog for resolving duplicate and shared media references."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
import shutil
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
from gramps.gen.db import DbTxn
from gramps.gen.merge.mergemediaquery import MergeMediaQuery
from gramps.gen.utils.file import media_path_full
from gramps.gui.dialog import OkDialog

try:
    from .gwizard_common import (
        TableLabel,
        HeaderLabel,
        create_table_grid,
    )
except (ImportError, ValueError):
    from gwizard_common import (  # type: ignore[import-not-found,no-redef]
        TableLabel,
        HeaderLabel,
        create_table_grid,
    )

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


def clean_path(path: str | None) -> str:
    """Clean a path string by stripping surrounding whitespace and quotes."""
    if not path:
        return ""
    p = str(path).strip()
    while len(p) >= 2 and (
        (p.startswith('"') and p.endswith('"'))
        or (p.startswith("'") and p.endswith("'"))
    ):
        p = p[1:-1].strip()
    if p.startswith('"') or p.startswith("'"):
        p = p[1:].strip()
    if p.endswith('"') or p.endswith("'"):
        p = p[:-1].strip()
    return p


def find_duplicate_media_groups(db: Any) -> list[dict[str, Any]]:
    """Scan database for media files referenced by multiple media records.

    Returns a list of dicts describing each shared file and its referencing media records.
    """
    if not db:
        return []

    try:
        from .gwizardmediafix import resolve_media_reference_context
    except (ImportError, ValueError):
        from gwizardmediafix import (  # type: ignore[import-not-found,no-redef]
            resolve_media_reference_context,
        )

    path_map: dict[str, list[dict[str, Any]]] = {}

    for media in db.iter_media():
        m_handle = str(media.get_handle() or "")
        m_gid = str(media.get_gramps_id() or "")
        desc = str(media.get_description() or "")
        raw_path = clean_path(str(media.get_path() or ""))
        if not raw_path:
            continue

        try:
            full_path = media_path_full(db, raw_path)
            key = os.path.normcase(os.path.normpath(full_path))
        except Exception:
            key = os.path.normcase(os.path.normpath(raw_path))

        assoc_str = ""
        try:
            ctx = resolve_media_reference_context(db, media)
            assoc_str = ctx.get("assoc", "")
        except Exception:
            pass

        backlinks = []
        if hasattr(db, "find_backlink_handles") and m_handle:
            try:
                backlinks = list(db.find_backlink_handles(m_handle))
            except Exception:
                backlinks = []

        if key not in path_map:
            path_map[key] = []

        path_map[key].append(
            {
                "handle": m_handle,
                "gramps_id": m_gid,
                "desc": desc,
                "raw_path": raw_path,
                "full_path": key,
                "backlink_count": len(backlinks),
                "assoc": assoc_str,
                "media": media,
            }
        )

    groups: list[dict[str, Any]] = []
    for file_key, records in path_map.items():
        if len(records) > 1:
            records.sort(
                key=lambda r: (
                    -r["backlink_count"],
                    bool(r["assoc"]),
                    bool(r["desc"]),
                    r["gramps_id"],
                )
            )
            keeper = records[0]
            groups.append(
                {
                    "file_key": file_key,
                    "records": records,
                    "keeper": keeper,
                    "raw_path": records[0]["raw_path"],
                }
            )

    return groups


# ------------------------------------------------------------
#
# FixMediaReferencesDialog
#
# ------------------------------------------------------------
class FixMediaReferencesDialog(Gtk.Dialog):
    """Review and resolve duplicate references where a single media file is used for multiple references."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Fix Media References"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.groups: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = []
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1360, 520)

        if dbstate and dbstate.db:
            self.groups = find_duplicate_media_groups(dbstate.db)
            self.rows = self.groups

        n_hints = len(self.groups)
        self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(len(self.groups) > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        info = Gtk.Label(
            label=str(
                _(
                    "Review duplicate references where a single media file is shared by multiple records. "
                    "You can merge duplicate media records into a single keeper or create separate file copies for each record."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not self.groups:
            done = Gtk.Label(
                label=str(_("No duplicate or shared media file references found."))
            )
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(
                _("Total duplicate media file groups: %d (affecting %d media records)")
                % (
                    len(self.groups),
                    sum(len(g["records"]) for g in self.groups),
                )
            )
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        header_grid = create_table_grid(col_spacing=6, row_spacing=0)
        header_grid.set_vexpand(False)

        file_head = HeaderLabel(str(_("File / Media Records")))
        ref_head = HeaderLabel(str(_("References")))
        action_head = HeaderLabel(str(_("Resolution")))
        action_head.set_hexpand(True)
        hint_head = HeaderLabel(str(_("Hint")))
        hint_head.set_hexpand(True)

        header_grid.attach(file_head, 0, 0, 1, 1)
        header_grid.attach(ref_head, 1, 0, 1, 1)
        header_grid.attach(action_head, 2, 0, 1, 1)
        header_grid.attach(hint_head, 3, 0, 1, 1)
        content.add(header_grid)

        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(4)
        ]
        self.column_sizegroups[0].add_widget(file_head)
        self.column_sizegroups[1].add_widget(ref_head)
        self.column_sizegroups[2].add_widget(action_head)
        self.column_sizegroups[3].add_widget(hint_head)

        content.pack_start(self.build_rows(self.groups), True, True, 0)

    def build_rows(self, groups: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        grid = create_table_grid()
        row_index = 0

        for group in groups:
            records = group["records"]
            keeper = group["keeper"]

            # Column 0: File path and records summary
            desc_lines = [group["raw_path"]]
            for r in records:
                d = r["desc"] or _("(unnamed)")
                desc_lines.append(f"  • [{r['gramps_id']}] {d}")
            file_label = TableLabel(
                "\n".join(desc_lines), width_chars=40, width_request=320
            )
            grid.attach(file_label, 0, row_index, 1, 1)

            # Column 1: References summary
            ref_parts = []
            for r in records:
                assoc = r.get("assoc") or r.get("desc") or _("(unnamed)")
                ref_parts.append(f"[{r['gramps_id']}]: {assoc}")
            ref_label = TableLabel(
                "\n".join(ref_parts), width_chars=40, width_request=300
            )
            grid.attach(ref_label, 1, row_index, 1, 1)

            # Column 2: Action ComboBox
            action_combo = Gtk.ComboBoxText()
            action_combo.append_text(
                str(_("Merge into keeper [%s]")) % keeper["gramps_id"]
            )
            action_combo.append_text(str(_("Create separate file copies")))
            action_combo.append_text(str(_("Keep shared (no change)")))
            action_combo.set_active(0)
            action_combo.set_hexpand(True)
            grid.attach(action_combo, 2, row_index, 1, 1)

            # Column 3: Hint label
            hint_str = str(_("Merge duplicate records into keeper [%(gid)s]")) % {
                "gid": keeper["gramps_id"],
            }
            hint_label = TableLabel(hint_str, width_chars=36, width_request=280)
            hint_label.set_hexpand(True)
            grid.attach(hint_label, 3, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(file_label)
                self.column_sizegroups[1].add_widget(ref_label)
                self.column_sizegroups[2].add_widget(action_combo)
                self.column_sizegroups[3].add_widget(hint_label)

            self.row_targets.append(
                {
                    "group": group,
                    "action_combo": action_combo,
                    "hint_label": hint_label,
                    "suggested_action": 0,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(280)
        scrolled.set_min_content_width(1280)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        count = 0
        for target in self.row_targets:
            combo = target["action_combo"]
            if hasattr(combo, "set_active"):
                combo.set_active(target["suggested_action"])
                count += 1
        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Populated merge suggestions for %d shared media files. Review and press Apply."
                )
                % count
            ),
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        merged_count = 0
        copied_count = 0
        errors: list[str] = []

        for target in self.row_targets:
            combo = target["action_combo"]
            choice = combo.get_active() if hasattr(combo, "get_active") else 0
            if choice == 2:  # Keep shared (no change)
                continue

            group = target["group"]
            records = group["records"]
            keeper = group["keeper"]

            if choice == 0:
                # Merge duplicate records into keeper
                keeper_media = self.dbstate.db.get_media_from_handle(keeper["handle"])
                if not keeper_media:
                    continue
                for other in records:
                    if other["handle"] == keeper["handle"]:
                        continue
                    try:
                        other_media = self.dbstate.db.get_media_from_handle(
                            other["handle"]
                        )
                        if other_media:
                            query = MergeMediaQuery(
                                self.dbstate, keeper_media, other_media
                            )
                            query.execute()
                            merged_count += 1
                    except Exception as err:
                        LOG.exception("Failed to merge media record: %s", err)
                        errors.append(str(err))

            elif choice == 1:
                # Create separate file copies for each duplicate record
                src_path = clean_path(group["raw_path"])
                try:
                    src_full = clean_path(media_path_full(self.dbstate.db, src_path))
                except Exception:
                    src_full = src_path

                base, ext = os.path.splitext(src_path)
                with DbTxn(_("Split Media References"), self.dbstate.db) as trans:
                    for idx, r in enumerate(records[1:], start=1):
                        new_rel = f"{base}_{r['gramps_id']}{ext}"
                        try:
                            dest_full = media_path_full(self.dbstate.db, new_rel)
                        except Exception:
                            dest_full = new_rel

                        if os.path.exists(src_full) and os.path.normpath(
                            src_full
                        ) != os.path.normpath(dest_full):
                            try:
                                os.makedirs(os.path.dirname(dest_full), exist_ok=True)
                                shutil.copy2(src_full, dest_full)
                                copied_count += 1
                            except Exception as err:
                                LOG.exception("Failed to copy media file: %s", err)

                        other_media = self.dbstate.db.get_media_from_handle(r["handle"])
                        if other_media:
                            other_media.set_path(new_rel)
                            self.dbstate.db.commit_media(other_media, trans)

        if merged_count == 0 and copied_count == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(
                    _(
                        "No actions selected. Choose 'Merge' or 'Create copies' for one or more files first."
                    )
                ),
                parent=self,
            )
            return

        summary = []
        if merged_count > 0:
            summary.append(str(_("Merged %d duplicate media records.") % merged_count))
        if copied_count > 0:
            summary.append(str(_("Created %d separate media files.") % copied_count))

        msg = " ".join(summary)
        if errors:
            msg += "\n\n" + "\n".join(errors)
        OkDialog(str(_("Media References Resolved")), msg, parent=self)
        self.destroy()

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


# Backward compatibility alias
ApplyFilenameStandardsDialog = FixMediaReferencesDialog
