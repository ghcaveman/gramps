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

"""Separate merge-repositories dialog for the GWizard citation fix tool."""

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
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.dialog import OkDialog
from gramps.plugins.tool.goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizardcitationfix import (
    build_repo_merge_rows,
    get_fix_description,
    plan_repo_merges,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# RepoMergeDialog
#
# ------------------------------------------------------------
class RepoMergeDialog(Gtk.Dialog):
    """Left-list/right-dropdown dialog for merging repositories."""

    def __init__(
        self,
        title: str,
        dbstate: Any,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        """Build the merge dialog for repositories needing fixes."""
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
        self.set_default_size(1260, 420)
        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        info = Gtk.Label(
            label=(
                description
                if description is not None
                else get_fix_description("repositories")
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)
        rows = build_repo_merge_rows(self.collect_repo_names())
        visible = [row for row in rows if not row["skip"]]
        if not visible:
            done = Gtk.Label(
                label=str(_("All repositories already match golden names."))
            )
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return
        content.add(self.build_header())
        content.pack_start(self.build_rows(visible), True, True, 0)
        hint = Gtk.Label(
            label=str(
                _(
                    "Golden entries show their description and URL "
                    "to help you pick the right target."
                )
            )
        )
        hint.set_line_wrap(True)
        hint.set_halign(Gtk.Align.START)
        content.add(hint)
        content.add(self.build_buttons())

    def build_header(self) -> Gtk.Box:
        """Return the two-column header for the merge rows."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Current repository")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(True)
        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Merge into (golden)")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(True)
        header.pack_start(left_head, True, True, 0)
        column_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        column_sep.set_size_request(4, -1)
        header.pack_start(column_sep, False, False, 0)
        header.pack_start(right_head, True, True, 0)
        return header

    def build_rows(self, visible: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build the scrolled left-list/right-dropdown rows."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(330)
        scrolled.set_min_content_width(1116)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scrolled.add(listbox)
        for row in visible:
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            left = Gtk.Label(label=row["name"])
            left.set_halign(Gtk.Align.START)
            left.set_hexpand(False)
            left.set_line_wrap(True)
            left.set_max_width_chars(24)
            left.set_size_request(540, -1)
            line.pack_start(left, False, False, 0)
            sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            sep.set_size_request(4, -1)
            line.pack_start(sep, False, False, 0)
            store = Gtk.ListStore(str, str)
            store.append([row["name"], row["name"]])
            for option in row["options"][1:]:
                store.append(
                    [
                        GoldStandardRepositories.get_display_label(option),
                        option,
                    ]
                )
            combo = Gtk.ComboBox.new_with_model(store)
            combo.set_hexpand(False)
            # Dropdown is limited to at most half the window width (1260 / 2 = 630).
            combo.set_size_request(630, -1)
            renderer = Gtk.CellRendererText()
            renderer.set_property("wrap-mode", 2)
            # Keep the dropdown list width capped so it stays compact.
            renderer.set_property("width-chars", 80)
            combo.pack_start(renderer, True)
            combo.add_attribute(renderer, "text", 0)
            combo.set_active(0)
            line.pack_start(combo, False, False, 0)
            listbox.pack_start(line, False, False, 0)
            self.combos.append((row["name"], combo, str(row["best_guess"])))
        return scrolled

    def build_buttons(self) -> Gtk.Box:
        """Return the Auto/Apply button row."""
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_homogeneous(True)
        auto_button = Gtk.Button(label=str(_("Auto (best guess)")))
        apply_button = Gtk.Button(label=str(_("Apply")))
        auto_button.connect("clicked", self.cb_set_best)
        apply_button.connect("clicked", self.cb_apply)
        buttons.pack_start(auto_button, True, True, 0)
        buttons.pack_start(apply_button, True, True, 0)
        return buttons

    def collect_repo_names(self) -> list[str]:
        """Return sorted repository names from the database."""
        names: list[str] = []
        try:
            for repo in self.dbstate.db.iter_repositories():
                try:
                    name = str(repo.get_name() or "")
                except Exception:  # pylint: disable=broad-except
                    name = ""
                names.append(name or str(_("Unnamed repository")))
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to collect repositories")
        return sorted(names)

    def find_repository_by_name(self, name: str) -> Any | None:
        """Return the first repository matching a name, or None."""
        try:
            for repo in self.dbstate.db.iter_repositories():
                try:
                    if str(repo.get_name() or "") == name:
                        return repo
                except Exception:  # pylint: disable=broad-except
                    continue
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to find repository %s", name)
        return None

    def get_choice(self, combo: Gtk.ComboBox, fallback: str) -> str:
        """Return the golden repository name behind a dropdown row."""
        active = combo.get_active_iter()
        if active is None:
            return fallback
        return str(combo.get_model()[active][1] or fallback)

    def get_choices(self) -> dict[str, str]:
        """Return the current original->target choice for every row."""
        return {
            name: self.get_choice(combo, name) for name, combo, _best in self.combos
        }

    def apply_merges(self, plan: dict[str, list[str]]) -> tuple[int, int]:
        """Apply repository merges/renames from a target->originals plan."""
        from gramps.gen.db import DbTxn
        from gramps.gen.merge import MergeRepositoryQuery

        merged = 0
        renamed = 0
        db = self.dbstate.db
        for target_name, originals in plan.items():
            for original in originals:
                try:
                    target = self.find_repository_by_name(target_name)
                    source = self.find_repository_by_name(original)
                    if source is None:
                        continue
                    if target is None:
                        with DbTxn(
                            str(_("Rename Repository")), db, batch=True
                        ) as trans:
                            source.set_name(target_name)
                            db.commit_repository(source, trans)
                        renamed += 1
                    else:
                        if source.get_handle() == target.get_handle():
                            continue
                        query = MergeRepositoryQuery(self.dbstate, target, source)
                        query.execute()
                        merged += 1
                except Exception:  # pylint: disable=broad-except
                    LOG.exception("Failed to merge repository %s", original)
        return (merged, renamed)

    def run_auto(self, parent: Gtk.Window | None = None) -> None:
        """Apply best-guess golden merges without showing the dialog."""
        rows = build_repo_merge_rows(self.collect_repo_names())
        choices = {
            row["name"]: str(row["best_guess"]) for row in rows if not row["skip"]
        }
        plan = plan_repo_merges(choices)
        owner = parent or self.get_transient_for()
        if not plan:
            OkDialog(
                str(_("Nothing to merge")),
                str(_("All repositories already match golden names.")),
                parent=owner,
            )
            return
        merged, renamed = self.apply_merges(plan)
        OkDialog(
            str(_("Auto fix: repositories")),
            str(
                _("Merged %d repositories, renamed %d to golden names.")
                % (merged, renamed)
            ),
            parent=owner,
        )

    def show_dialog(self) -> None:
        """Show the dialog modally and destroy it afterwards."""
        self.show_all()
        self.run()
        self.destroy()

    def cb_set_best(self, _button: Gtk.Button) -> None:
        """Select the best-guess golden name in every dropdown."""
        for _name, combo, best in self.combos:
            model = combo.get_model()
            for index, option_row in enumerate(model):
                if str(option_row[1]) == best:
                    combo.set_active(index)
                    break

    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply the user choices as repository merges/renames."""
        plan = plan_repo_merges(self.get_choices())
        if not plan:
            OkDialog(
                str(_("Nothing to merge")),
                str(_("All rows are set to bypass (keep current name).")),
                parent=self,
            )
            return
        merged, renamed = self.apply_merges(plan)
        OkDialog(
            str(_("Repositories merged")),
            str(
                _("Merged %d repositories, renamed %d to golden names.")
                % (merged, renamed)
            ),
            parent=self,
        )
        self.destroy()
