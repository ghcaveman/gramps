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
from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import Pango

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.dialog import OkDialog
from gramps.plugins.tool.goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizardcitationfix import (
    UNATTACHED_REPO_KEY,
    build_repo_merge_rows,
    collect_sources_by_repo,
    get_fix_description,
    get_golden_repo_display,
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
    """Grid dialog: repository names (with merge target dropdowns) beside\n    their associated sources. The header shares the grid columns with the\n    rows below so they align vertically, and cell text wraps to stay inside\n    its column."""

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

        # Collect repository rows and associated sources.
        self.sources_by_repo = self.collect_sources_by_repo()
        rows = build_repo_merge_rows(self.collect_repo_names())
        visible = [row for row in rows if not row["skip"]]

        # Count header in the content area.
        n_repos = len(visible)
        n_sources = sum(len(titles) for titles in self.sources_by_repo.values())
        count_label = Gtk.Label()
        count_label.set_markup(
            "<b>%s</b>"
            % str(
                _("Repositories (%d total), Sources (%d total)") % (n_repos, n_sources)
            )
        )
        count_label.set_halign(Gtk.Align.START)
        count_label.set_hexpand(True)
        content.add(count_label)

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
        if not visible:
            done = Gtk.Label(
                label=str(_("All repositories already match golden names."))
            )
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return
        # Add header row above the scrolled grid so it stays locked
        # when scrolling through the data rows.
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(0)
        header_grid.set_row_spacing(0)
        header_grid.set_column_homogeneous(True)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)
        header_grid.get_style_context().add_class("merge-grid")

        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Repository")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(True)
        mid_head = Gtk.Label()
        mid_head.set_markup("<b>%s</b>" % str(_("Merge into (golden)")))
        mid_head.set_halign(Gtk.Align.START)
        mid_head.set_hexpand(True)
        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Sources")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(True)
        for head in (left_head, mid_head, right_head):
            head.get_style_context().add_class("merge-cell")
        header_grid.attach(left_head, 0, 0, 1, 1)
        header_grid.attach(mid_head, 1, 0, 1, 1)
        header_grid.attach(right_head, 2, 0, 1, 1)
        content.add(header_grid)

        content.pack_start(
            self.build_rows(visible, self.sources_by_repo), True, True, 0
        )
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

    def collect_sources_by_repo(self) -> dict[str, list[str]]:
        """Return repository name mapped to sorted source titles it references."""
        return collect_sources_by_repo(self.dbstate.db)

    def build_header(self, grid: Gtk.Grid) -> None:
        """Add the three-column header row to the repository/source grid.

        The header lives in the same grid as the data rows so the column
        edges line up vertically instead of being allocated by separate
        containers.
        """
        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Repository")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(True)
        mid_head = Gtk.Label()
        mid_head.set_markup("<b>%s</b>" % str(_("Merge into (golden)")))
        mid_head.set_halign(Gtk.Align.START)
        mid_head.set_hexpand(True)
        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Sources")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(True)
        for head in (left_head, mid_head, right_head):
            head.get_style_context().add_class("merge-cell")
        grid.attach(left_head, 0, 0, 1, 1)
        grid.attach(mid_head, 1, 0, 1, 1)
        grid.attach(right_head, 2, 0, 1, 1)

    def _install_grid_css(self) -> None:
        """Install CSS that draws borders around every grid cell.

        Gtk.Grid has no native "show grid lines" option, so each cell
        widget gets a thin border so columns and rows are visually
        separated and line up with the header above them.
        """
        if getattr(self, "_grid_css_installed", False):
            return
        css = b"""
        .merge-grid {
            border: 1px solid #555555;
            margin: 0;
        }
        .merge-cell {
            border: none;
            margin: 0;
            padding: 2px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._grid_css_installed = True

    def _make_combo(self, row: dict[str, Any]) -> Gtk.ComboBox:
        """Create a golden-target dropdown for a repository row.

        Column 0 is the visible label; column 1 is the raw repository name
        used when applying the choice. The dropdown lists the source's
        repository name first (the bypass entry) followed by every
        golden-list entry; golden entries show their description and URL
        to help pick the right target.
        """
        store = Gtk.ListStore(str, str)
        # Bypass entry: the source's own repository name.
        store.append([row["name"], row["name"]])
        # Golden entries: show description + URL, store the raw name.
        for option in row["options"][1:]:
            store.append([get_golden_repo_display(option), option])
        combo = Gtk.ComboBox.new_with_model(store)
        combo.set_hexpand(False)
        # Narrow the combo + dropdown to ~300px so columns stay compact.
        combo.set_size_request(210, -1)
        renderer = Gtk.CellRendererText()
        renderer.set_property("wrap-mode", 2)
        # Truncate displayed entries with "..." when they exceed this many chars.
        renderer.set_property("width-chars", 40)
        renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        combo.pack_start(renderer, True)
        combo.add_attribute(renderer, "text", 0)
        combo.set_active(0)
        return combo

    def build_rows(
        self,
        visible: list[dict[str, Any]],
        sources_by_repo: dict[str, list[str]],
    ) -> Gtk.ScrolledWindow:
        """Build a grid: header row plus repositories (left) with merge
        dropdowns (middle) and associated sources (right), grouped by
        repository with empty rows last. The header shares the same grid
        columns as the cells below so they align vertically, and cell
        text wraps so long values stay inside their columns."""
        self._install_grid_css()
        grid = Gtk.Grid()
        grid.set_column_spacing(0)
        grid.set_row_spacing(0)
        grid.set_column_homogeneous(True)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        grid.get_style_context().add_class("merge-grid")

        # Sort: repositories with sources first (alphabetical), then those
        # without sources (alphabetical) so empty rows appear last.
        with_sources = [r for r in visible if sources_by_repo.get(r["name"], [])]
        without_sources = [r for r in visible if not sources_by_repo.get(r["name"], [])]
        sorted_rows = with_sources + without_sources

        # Build a flat list of (repo_name, source_title) pairs, one row per source.
        # Each repo with sources gets one row per source; repos without sources
        # get a single row with the "(no sources)" placeholder.
        flat_rows: list[tuple[str, str]] = []  # (repo_name, source_title)
        for repo_name in [r["name"] for r in sorted_rows]:
            sources = sorted(sources_by_repo.get(repo_name, []))
            if sources:
                for st in sources:
                    flat_rows.append((repo_name, st))
            else:
                # Repo with no sources: one row showing the placeholder.
                flat_rows.append((repo_name, "(no sources)"))

        # Append unattached sources (no repository reference) as final rows.
        unattached = sources_by_repo.get(UNATTACHED_REPO_KEY, [])
        for _source in unattached:
            flat_rows.append((UNATTACHED_REPO_KEY, _source))

        # Row 0 is the header; data rows start below it. Each source entry
        # gets its own row with its own merge-target dropdown (Option 2).
        # Column 0: repository name label (repeated per row).
        # Column 1: one combo per source row, with the original name first
        #   as the bypass option, then golden repo names.
        # Column 2: the source title for this row.
        row_index = 1
        for repo_name, source_title in flat_rows:
            # Column 0: repository name for this row.
            repo_label = Gtk.Label(label=repo_name)
            repo_label.set_halign(Gtk.Align.START)
            repo_label.set_line_wrap(True)
            repo_label.set_max_width_chars(24)
            repo_label.get_style_context().add_class("merge-cell")
            grid.attach(repo_label, 0, row_index, 1, 1)

            # Column 1: a separate merge-target combobox for this source row.
            # Find the row dict for this repo to build the combo.
            if repo_name == UNATTACHED_REPO_KEY:
                # Unattached sources have no repo; show golden repo names
                # so the user can assign a repository to the source.
                golden = GoldStandardRepositories.get_names()
                row_dict = {
                    "name": UNATTACHED_REPO_KEY,
                    "options": [UNATTACHED_REPO_KEY] + golden,
                    "best_guess": UNATTACHED_REPO_KEY,
                }
            else:
                row_dict = next(r for r in sorted_rows if r["name"] == repo_name)
            combo = self._make_combo(row_dict)
            combo.get_style_context().add_class("merge-cell")
            grid.attach(combo, 1, row_index, 1, 1)

            # Column 2: the source title for this row.
            if source_title == "(no sources)":
                placeholder = Gtk.Label(label=str(_("(no sources)")))
                placeholder.set_halign(Gtk.Align.START)
                placeholder.set_line_wrap(True)
                placeholder.set_max_width_chars(60)
                placeholder.get_style_context().add_class("merge-cell")
                grid.attach(placeholder, 2, row_index, 1, 1)
            elif source_title == "(no repository)":
                placeholder = Gtk.Label(label=str(_("(no repository)")))
                placeholder.set_halign(Gtk.Align.START)
                placeholder.set_line_wrap(True)
                placeholder.set_max_width_chars(60)
                placeholder.get_style_context().add_class("merge-cell")
                grid.attach(placeholder, 2, row_index, 1, 1)
            else:
                src_label = Gtk.Label(label=source_title)
                src_label.set_halign(Gtk.Align.START)
                src_label.set_line_wrap(True)
                src_label.set_max_width_chars(60)
                src_label.get_style_context().add_class("merge-cell")
                grid.attach(src_label, 2, row_index, 1, 1)

            # Track the combo per repo for later retrieval of choices.
            self.combos.append((repo_name, combo, str(row_dict["best_guess"])))
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(330)
        scrolled.set_min_content_width(1116)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
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
