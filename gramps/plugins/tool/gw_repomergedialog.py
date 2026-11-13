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
from collections import defaultdict
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
from gramps.gen.db import DbTxn
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.dialog import ErrorDialog, OkDialog
from gramps.plugins.tool.gwizard_common import reports_apply_errors
from gramps.plugins.tool.gw_goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizardcitationshared import (
    build_family_titles,
    build_title_repo_index,
    suggest_repository,
)
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardcitationfix import (
    UNATTACHED_REPO_KEY,
    auto_assign_source_repositories,
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
    """Grid dialog: repository names (with merge target dropdowns) beside
    their associated sources. The header shares the grid columns with the
    rows below so they align vertically, and cell text wraps to stay inside
    its column."""

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
        # One (row info, combo) pair per grid row; Apply reads these.
        self.row_targets: list[tuple[dict[str, str], Gtk.ComboBox]] = []
        self.set_default_size(1480, 420)
        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        # Collect repository rows and associated sources.
        self.sources_by_repo = self.collect_sources_by_repo()
        self.source_rows = self.collect_source_rows()
        linked_rows = [row for row in self.source_rows if row["repo_handle"]]
        self.hint_index = build_title_repo_index(linked_rows)
        # Titles of every source, linked or not, grouped by collection so a
        # title without "U.S." can follow its "U.S." twin.
        self.family_titles = build_family_titles(
            [row["title"] for row in self.source_rows]
        )
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

        if not visible and not self.sources_by_repo.get(UNATTACHED_REPO_KEY):
            done = Gtk.Label(
                label=str(_("All repositories already match golden names."))
            )
            done.set_halign(Gtk.Align.START)
            content.add(done)
            self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % 0)
            self.accept_button.set_sensitive(False)
            self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

            self.apply_button = Gtk.Button(label=str(_("Apply")))
            self.apply_button.set_sensitive(False)
            self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

            self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
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
        self.build_header(header_grid)
        content.add(header_grid)

        content.pack_start(
            self.build_rows(visible, self.sources_by_repo), True, True, 0
        )
        desc_text = (
            description
            if description is not None
            else get_fix_description("repositories")
        )
        hint_footer = Gtk.Label(
            label=f"{desc_text} "
            + str(
                _(
                    "Golden entries show their description and URL "
                    "to help you pick the right target."
                )
            )
        )
        hint_footer.set_line_wrap(True)
        hint_footer.set_halign(Gtk.Align.START)
        hint_footer.set_size_request(-1, 45)
        content.pack_start(hint_footer, False, False, 0)

        n_hints = sum(1 for info, _combo in self.row_targets if info.get("hint_target"))
        self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        has_items = bool(visible or self.sources_by_repo.get(UNATTACHED_REPO_KEY))
        self.apply_button.set_sensitive(has_items)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

    def collect_sources_by_repo(self) -> dict[str, list[str]]:
        """Return repository name mapped to sorted source titles it references."""
        return collect_sources_by_repo(self.dbstate.db)

    def collect_source_rows(self) -> list[dict[str, str]]:
        """Return one row per source/repository pair, keeping the handles.

        Each row holds ``source_handle``, ``title``, ``repo_handle`` (empty
        when the source has no usable repository) and ``repo_name`` (the
        repository name, or ``UNATTACHED_REPO_KEY``). A source linked to
        several repositories appears once for each.
        """
        db = self.dbstate.db
        handle_to_name: dict[str, str] = {}
        for repo in db.iter_repositories():
            try:
                name = str(repo.get_name() or "")
                if name:
                    handle_to_name[str(repo.get_handle() or "")] = name
            except Exception:  # pylint: disable=broad-except
                LOG.exception("Failed to read repository")
        rows: list[dict[str, str]] = []
        for source in db.iter_sources():
            try:
                title = str(source.get_title() or "")
                source_handle = str(source.get_handle() or "")
                refs = [
                    str(ref.get_reference_handle() or "")
                    for ref in source.get_reporef_list()
                ]
                if not refs:
                    refs = [""]
                for ref_handle in refs:
                    name = handle_to_name.get(ref_handle, "")
                    rows.append(
                        {
                            "source_handle": source_handle,
                            "title": title,
                            "repo_handle": ref_handle if name else "",
                            "repo_name": name or UNATTACHED_REPO_KEY,
                        }
                    )
            except Exception:  # pylint: disable=broad-except
                LOG.exception("Failed to read source")
        return rows

    def build_header(self, grid: Gtk.Grid) -> None:
        """Add the header row to the repository/source grid.

        The header lives in the same grid as the data rows so the column
        edges line up vertically instead of being allocated by separate
        containers.  The "Sources" column is now the first column.
        """
        # Column 0: Sources (moved from position 2)
        sources_head = Gtk.Label()
        sources_head.set_markup("<b>%s</b>" % str(_("Sources")))
        sources_head.set_halign(Gtk.Align.START)
        sources_head.set_hexpand(True)
        # Column 1: Repository (moved from position 0)
        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Repository")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(True)
        # Column 2: Merge into (golden) (moved from position 1)
        mid_head = Gtk.Label()
        mid_head.set_markup("<b>%s</b>" % str(_("Merge into (golden)")))
        mid_head.set_halign(Gtk.Align.START)
        mid_head.set_hexpand(True)
        # Column 3: Hint (kept at position 3)
        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)
        for head in (sources_head, left_head, mid_head, hint_head):
            head.get_style_context().add_class("merge-cell")
        grid.attach(sources_head, 0, 0, 1, 1)
        grid.attach(left_head, 1, 0, 1, 1)
        grid.attach(mid_head, 2, 0, 1, 1)
        grid.attach(hint_head, 3, 0, 1, 1)

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
        screen = Gdk.Screen.get_default()
        if screen is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            screen,
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
        # Store the user's selection directly on the combo object so Apply
        # always reads the current value, regardless of GTK timing issues
        # with get_active().
        combo._user_target = row["name"]
        combo.connect("changed", self._on_combo_changed)
        return combo

    def _on_combo_changed(self, combo: Gtk.ComboBox) -> None:
        """Record the user's current selection on the combo object itself."""
        iter_ = combo.get_active_iter()
        if iter_ is not None:
            model = combo.get_model()
            combo._user_target = str(model.get_value(iter_, 1) or "")
        else:
            combo._user_target = ""

    def compute_hint(
        self, repo_name: str, info: dict[str, str], combo: Gtk.ComboBox
    ) -> tuple[str, str] | None:
        """Return ``(golden repository, reason)`` suggested for a grid row."""
        offered = {str(row[1]) for row in combo.get_model()}
        golden = [
            name for name in GoldStandardRepositories.get_names() if name in offered
        ]
        current = "" if repo_name == UNATTACHED_REPO_KEY else repo_name
        return suggest_repository(
            info.get("title", ""),
            info.get("source_handle", ""),
            current,
            self.hint_index,
            golden,
            self.family_titles,
        )

    def attach_hint(
        self, info: dict[str, str], repo_name: str, combo: Gtk.ComboBox
    ) -> str:
        """Record the hint on the row info and return the text to display."""
        found = self.compute_hint(repo_name, info, combo)
        if found is None:
            info["hint_target"] = ""
            return ""
        info["hint_target"], info["hint_reason"] = found
        return "%s\n(%s)" % found

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
        rows_by_repo: dict[str, list[dict[str, str]]] = defaultdict(list)
        for info in getattr(self, "source_rows", None) or self.collect_source_rows():
            rows_by_repo[info["repo_name"]].append(info)
        for infos in rows_by_repo.values():
            infos.sort(key=lambda item: item["title"].lower())

        # (repo_name, source_title, row info); info is None for a repository
        # that has no sources.
        flat_rows: list[tuple[str, str, dict[str, str] | None]] = []
        for repo_name in [r["name"] for r in sorted_rows]:
            infos = rows_by_repo.get(repo_name, [])
            if infos:
                for info in infos:
                    flat_rows.append((repo_name, info["title"], info))
            else:
                # Repo with no sources: one row showing the placeholder.
                flat_rows.append((repo_name, "(no sources)", None))

        # Append unattached sources (no repository reference) as final rows.
        for info in rows_by_repo.get(UNATTACHED_REPO_KEY, []):
            flat_rows.append((UNATTACHED_REPO_KEY, info["title"], info))

        # Row 0 is the header; data rows start below it. Each source entry
        # gets its own row with its own merge-target dropdown (Option 2).
        # Column 0: source title for this row (moved from column 2).
        # Column 1: repository name label (moved from column 0).
        # Column 2: one combo per source row, with the original name first
        #   as the bypass option, then golden repo names.
        # Column 3: hint for this row (kept at column 3).
        row_index = 1
        for repo_name, source_title, info in flat_rows:
            # Column 0: the source title for this row.
            if source_title == "(no sources)":
                placeholder = Gtk.Label(label=str(_("(no sources)")))
                placeholder.set_halign(Gtk.Align.START)
                placeholder.set_line_wrap(True)
                placeholder.set_max_width_chars(60)
                placeholder.get_style_context().add_class("merge-cell")
                grid.attach(placeholder, 0, row_index, 1, 1)
            elif source_title == "(no repository)":
                placeholder = Gtk.Label(label=str(_("(no repository)")))
                placeholder.set_halign(Gtk.Align.START)
                placeholder.set_line_wrap(True)
                placeholder.set_max_width_chars(60)
                placeholder.get_style_context().add_class("merge-cell")
                grid.attach(placeholder, 0, row_index, 1, 1)
            else:
                src_label = Gtk.Label(label=source_title)
                src_label.set_halign(Gtk.Align.START)
                src_label.set_line_wrap(True)
                src_label.set_max_width_chars(60)
                src_label.get_style_context().add_class("merge-cell")
                grid.attach(src_label, 0, row_index, 1, 1)

            # Column 1: repository name label for this row.
            repo_label = Gtk.Label(label=repo_name)
            repo_label.set_halign(Gtk.Align.START)
            repo_label.set_line_wrap(True)
            repo_label.set_max_width_chars(60)
            repo_label.get_style_context().add_class("merge-cell")
            grid.attach(repo_label, 1, row_index, 1, 1)

            # Column 2: a separate merge-target combobox for this source row.
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
            grid.attach(combo, 2, row_index, 1, 1)

            # Column 3: hint for this row (suggested repository and why).
            row_info = (
                info
                if info is not None
                else {"source_handle": "", "repo_handle": "", "repo_name": repo_name}
            )
            hint_label = Gtk.Label(label=self.attach_hint(row_info, repo_name, combo))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_line_wrap(True)
            hint_label.set_max_width_chars(40)
            hint_label.get_style_context().add_class("merge-cell")
            grid.attach(hint_label, 3, row_index, 1, 1)

            # Column 3: hint for this row (suggested repository and why).
            row_info = (
                info
                if info is not None
                else {"source_handle": "", "repo_handle": "", "repo_name": repo_name}
            )
            hint_label = Gtk.Label(label=self.attach_hint(row_info, repo_name, combo))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_line_wrap(True)
            hint_label.set_max_width_chars(40)
            hint_label.get_style_context().add_class("merge-cell")
            grid.attach(hint_label, 3, row_index, 1, 1)

            # Track the combo per grid row for later retrieval of choices.
            self.combos.append((repo_name, combo, str(row_dict["best_guess"])))
            self.row_targets.append((row_info, combo))
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
        """Return the repository action button row."""
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_homogeneous(True)
        n_hints = sum(1 for info, _combo in self.row_targets if info.get("hint_target"))
        accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        accept_button.set_sensitive(n_hints > 0)
        accept_button.connect("clicked", self.cb_accept_hints)
        apply_button = Gtk.Button(label=str(_("Apply")))
        apply_button.connect("clicked", self.cb_apply)
        buttons.pack_start(accept_button, True, True, 0)
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
        for repo in self.dbstate.db.iter_repositories():
            if str(repo.get_name() or "") == name:
                return repo
        return None

    def get_choice(self, combo: Gtk.ComboBox, fallback: str) -> str:
        """Return the golden repository name behind a dropdown row."""
        # Read the selection captured by the "changed" signal, stored on
        # the combo object itself. This avoids GTK timing issues where
        # get_active() may not reflect the user's latest choice.
        user_target = getattr(combo, "_user_target", None)
        if user_target:
            return user_target
        active = combo.get_active()
        if active < 0:
            return fallback
        model = combo.get_model()
        return str(model[active][1] or fallback)

    def get_choices(self) -> dict[str, str]:
        """Return the current original->target choice for every row."""
        return {
            name: self.get_choice(combo, name) for name, combo, _best in self.combos
        }

    def apply_merges(
        self, plan: dict[str, list[str]], trans: Any
    ) -> tuple[int, int, list[str]]:
        """Apply repository merges/renames from a target->originals plan.

        Runs inside ``trans`` so it is part of the dialog's single undo
        step. A repository that cannot be found is reported; any other
        error is raised so the whole transaction is rolled back.

        :returns: ``(merged_count, renamed_count, error_messages)``.
        """
        merged = 0
        renamed = 0
        errors: list[str] = []
        db = self.dbstate.db
        engine = GWizardCitationRepairEngine()
        for target_name, originals in plan.items():
            for original in originals:
                target = self.find_repository_by_name(target_name)
                source = self.find_repository_by_name(original)
                if source is None:
                    errors.append(
                        _("Repository '%(original)s' not found in database.")
                        % {"original": original}
                    )
                    continue
                if target is None:
                    source.set_name(target_name)
                    db.commit_repository(source, trans)
                    renamed += 1
                elif source.get_handle() != target.get_handle():
                    if engine.merge_repositories(
                        db, target.get_handle(), source.get_handle(), trans
                    ):
                        merged += 1
        return (merged, renamed, errors)

    def run_auto(self, parent: Gtk.Window | None = None) -> None:
        """Accept every hint and apply it (same code as Accept all hints)."""
        owner = parent or self.get_transient_for()
        try:
            changed, created = auto_assign_source_repositories(
                GWizardCitationRepairEngine(), self.dbstate.db
            )
        except Exception as error:  # pylint: disable=broad-except
            LOG.exception("Auto fix of repositories failed")
            ErrorDialog(str(_("Auto fix: repositories")), str(error), parent=owner)
            return
        message = str(_("Changed the repository of %d sources")) % changed
        if created:
            message += str(_(" (%d new repositories created)")) % created
        OkDialog(str(_("Auto fix: repositories")), message + ".", parent=owner)

    def show_dialog(self) -> None:
        """Show the dialog modally and destroy it afterwards.

        Accept/Apply return ``ResponseType.NONE`` and must keep the dialog
        open so the user can review and press Apply; only a close-type
        response dismisses the dialog.
        """
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

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        """Set each unchanged drop-down to its hint; Apply still has to be pressed."""
        accepted = 0
        for info, combo in self.row_targets:
            target = info.get("hint_target")
            if not target:
                continue
            original = info["repo_name"]
            # Keep any choice the user already made by hand.
            if self.get_choice(combo, original) != original:
                continue
            for index, model_row in enumerate(combo.get_model()):
                if str(model_row[1]) == target:
                    combo.set_active(index)
                    accepted += 1
                    break
        if hasattr(self, "accept_button"):
            self.accept_button.set_sensitive(False)
            self.accept_button.set_label(str(_("Accept hints (%d)")) % 0)
        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Set %d drop-downs to the suggested repository. Review "
                    "them, change any that look wrong, then press Apply."
                )
            )
            % accepted,
            parent=self,
        )

    def collect_changes(
        self,
    ) -> tuple[list[dict[str, str]], dict[str, str]]:
        """Compare every drop-down with its first entry.

        Returns ``(source_changes, repo_changes)``. ``source_changes`` lists
        the sources whose row was changed; ``repo_changes`` maps a
        repository that has no sources to its chosen golden target.
        """
        source_changes: list[dict[str, str]] = []
        repo_changes: dict[str, str] = {}
        for info, combo in self.row_targets:
            original = info["repo_name"]
            target = self.get_choice(combo, original)
            if not target or target == original:
                continue
            if info.get("source_handle"):
                source_changes.append(
                    {
                        "source_handle": info["source_handle"],
                        "old_repo_handle": info.get("repo_handle", ""),
                        "target_name": target,
                    }
                )
            else:
                repo_changes[original] = target
        return source_changes, repo_changes

    @reports_apply_errors
    def cb_apply(self, _button: Gtk.Button) -> None:
        """Change the repository of every source whose drop-down was changed."""
        source_changes, repo_changes = self.collect_changes()
        if not source_changes and not repo_changes:
            OkDialog(
                str(_("Nothing to change")),
                str(
                    _(
                        "Every drop-down is still on its first entry. Pick a "
                        "repository in one or more rows, then press Apply."
                    )
                ),
                parent=self,
            )
            return

        reassigned = created = merged = renamed = 0
        errors: list[str] = []
        # One transaction for the whole Apply, so it is one Edit > Undo and
        # a failure part way through changes nothing.
        with DbTxn(_("Fix Repositories"), self.dbstate.db) as trans:
            engine = GWizardCitationRepairEngine()
            reassigned, created = engine.reassign_source_repositories(
                self.dbstate.db, source_changes, trans
            )
            if repo_changes:
                merged, renamed, errors = self.apply_merges(
                    plan_repo_merges(repo_changes), trans
                )

        summary = str(_("Changed the repository of %d sources")) % reassigned
        if created:
            summary += str(_(" (%d new repositories created)")) % created
        summary += "."
        if merged or renamed:
            summary += "\n" + str(
                _("Merged %d empty repositories, renamed %d to golden names.")
                % (merged, renamed)
            )
        if errors:
            ErrorDialog(
                str(_("Repository changes had problems")),
                summary + "\n\n" + "\n".join(errors),
                parent=self,
            )
            return
        OkDialog(str(_("Repositories updated")), summary, parent=self)
