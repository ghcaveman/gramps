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

"""Source-record fix dialog for the GWizard citation fix tool."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
from collections import defaultdict
import logging
import re
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gdk, Gtk, Pango

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.dialog import OkDialog
from gramps.plugins.tool.gwizard_common import reports_apply_errors
from gramps.gen.db import DbReadBase, DbTxn, DbWriteBase
from gramps.gen.lib import Repository, RepoRef
from gramps.plugins.tool.gwizardcitationreport import (
    collect_db_stats,
    kind_of_non_title,
)
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardcitationshared import (
    suggest_source_merge_target,
)

_ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext
LOG = logging.getLogger(__name__)

_QUARANTINE_REPO_NAME = "Quarantine"


# ------------------------------------------------------------
#
# SourceFixDialog
#
# ------------------------------------------------------------
class SourceFixDialog(Gtk.Dialog):
    """Review and fix source-record problems in a grid dialog."""

    def __init__(
        self,
        title: str,
        dbstate: Any,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        """Build the source-fix dialog."""
        super().__init__(
            title=title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.combos: list[tuple[str, Gtk.ComboBox, str]] = []
        self.row_combos: list[tuple[dict[str, Any], Gtk.ComboBox]] = []
        self.set_default_size(1480, 520)
        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        stats = collect_db_stats(self.dbstate.db)
        rows = build_source_fix_rows(stats, self.dbstate.db)

        n_sources = len(rows)
        count_label = Gtk.Label()
        count_label.set_markup(
            "<b>%s</b>"
            % str(_("Problem sources ({number_of} total)").format(number_of=n_sources))
        )
        count_label.set_halign(Gtk.Align.START)
        count_label.set_hexpand(True)
        content.add(count_label)

        if not rows:
            done = Gtk.Label(label=str(_("No source-record problems found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            self.accept_button = Gtk.Button(
                label=_("Accept hints ({number_of})").format(number_of=0)
            )
            self.accept_button.set_sensitive(False)
            self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

            self.apply_button = Gtk.Button(label=str(_("Apply")))
            self.apply_button.set_sensitive(False)
            self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

            self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
            return

        # Add locked header row above the scrolled data grid
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(0)
        header_grid.set_row_spacing(0)
        if hasattr(header_grid, "set_column_homogeneous"):
            header_grid.set_column_homogeneous(True)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)
        if hasattr(header_grid, "get_style_context"):
            header_grid.get_style_context().add_class("merge-grid")

        # Column 0: Repository
        repo_head = Gtk.Label()
        repo_head.set_markup("<b>%s</b>" % str(_("Repository")))
        repo_head.set_halign(Gtk.Align.START)
        repo_head.set_hexpand(True)

        # Column 1: Source
        source_head = Gtk.Label()
        source_head.set_markup("<b>%s</b>" % str(_("Source")))
        source_head.set_halign(Gtk.Align.START)
        source_head.set_hexpand(True)

        # Column 2: Fix into (target)
        mid_head = Gtk.Label()
        mid_head.set_markup("<b>%s</b>" % str(_("Fix into (target)")))
        mid_head.set_halign(Gtk.Align.START)
        mid_head.set_hexpand(True)

        # Column 3: Hint
        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        for head in (repo_head, source_head, mid_head, hint_head):
            head.get_style_context().add_class("merge-cell")
        header_grid.attach(repo_head, 0, 0, 1, 1)
        header_grid.attach(source_head, 1, 0, 1, 1)
        header_grid.attach(mid_head, 2, 0, 1, 1)
        header_grid.attach(hint_head, 3, 0, 1, 1)
        content.add(header_grid)

        content.pack_start(self.build_rows(rows), True, True, 0)

        desc_text = (
            description
            if description is not None
            else str(_("Merge near-duplicates and quarantine non-sources."))
        )
        hint_footer = Gtk.Label(
            label=f"{desc_text} "
            + str(
                _(
                    "Merging combines duplicate sources into one; trimming "
                    "removes leading/trailing whitespace; quarantine moves "
                    "problem sources to a review repository."
                )
            )
        )
        hint_footer.set_line_wrap(True)
        hint_footer.set_halign(Gtk.Align.START)
        hint_footer.set_size_request(-1, 45)
        content.pack_start(hint_footer, False, False, 0)

        # Action area buttons (Accept hints and Apply placed to the left of Close)
        n_hints = sum(1 for row, _combo in self.row_combos if row.get("hint_target"))
        self.accept_button = Gtk.Button(
            label=_("Accept hints ({number_of})").format(number_of=n_hints)
        )
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(len(rows) > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

    def _install_grid_css(self) -> None:
        """Install CSS that draws borders around every grid cell."""
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
        """
        Create a target dropdown for a source row.

        Column 0 is the visible label; column 1 is the handle or target value.
        Option 0 is the source's own database value (bypass / default choice).
        """
        store = Gtk.ListStore(str, str)
        for opt_label, opt_val in row.get("options", []):
            store.append([opt_label, opt_val])

        combo = Gtk.ComboBox.new_with_model(store)
        combo.set_hexpand(False)
        combo.set_size_request(240, -1)
        renderer = Gtk.CellRendererText()
        renderer.set_property("wrap-mode", 2)
        renderer.set_property("width-chars", 40)
        renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        combo.pack_start(renderer, True)
        combo.add_attribute(renderer, "text", 0)
        combo.set_active(0)
        combo._user_target = row["handle"]
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

    def build_rows(self, rows: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build the data grid inside a scrolled window."""
        self._install_grid_css()
        grid = Gtk.Grid()
        grid.set_column_spacing(0)
        grid.set_row_spacing(0)
        grid.set_column_homogeneous(True)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        grid.get_style_context().add_class("merge-grid")

        row_index = 0
        for row in rows:
            # Column 0: Repository name
            repo_label = Gtk.Label(label=row.get("repo_name", _("(no repository)")))
            repo_label.set_halign(Gtk.Align.START)
            repo_label.set_line_wrap(True)
            repo_label.set_max_width_chars(35)
            repo_label.get_style_context().add_class("merge-cell")
            grid.attach(repo_label, 0, row_index, 1, 1)

            # Column 1: Source display (title, gramps_id)
            src_label = Gtk.Label(label=row["display"])
            src_label.set_halign(Gtk.Align.START)
            src_label.set_line_wrap(True)
            src_label.set_max_width_chars(50)
            src_label.get_style_context().add_class("merge-cell")
            grid.attach(src_label, 1, row_index, 1, 1)

            # Column 2: Target dropdown
            combo = self._make_combo(row)
            combo.get_style_context().add_class("merge-cell")
            grid.attach(combo, 2, row_index, 1, 1)

            # Column 3: Hint (blank if no hint)
            hint_text = row.get("hint_display", "")
            hint_label = Gtk.Label(label=hint_text)
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_line_wrap(True)
            hint_label.set_max_width_chars(40)
            hint_label.get_style_context().add_class("merge-cell")
            grid.attach(hint_label, 3, row_index, 1, 1)

            self.combos.append((row["handle"], combo, str(row.get("hint_target", ""))))
            self.row_combos.append((row, combo))
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(330)
        scrolled.set_min_content_width(1330)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def get_choice(self, combo: Gtk.ComboBox, fallback: str) -> str:
        """Return the target handle/value behind a dropdown row."""
        user_target = getattr(combo, "_user_target", None)
        if user_target:
            return user_target
        active = combo.get_active()
        if active < 0:
            return fallback
        model = combo.get_model()
        return str(model[active][1] or fallback)

    def get_choices(self) -> dict[str, str]:
        """Return mapping of source handle to chosen target value."""
        return {
            row["handle"]: self.get_choice(combo, row["handle"])
            for row, combo in self.row_combos
        }

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        """Set each unchanged drop-down to its hint target."""
        accepted = 0
        for row, combo in self.row_combos:
            target = row.get("hint_target")
            if not target:
                continue
            original = row["handle"]
            if self.get_choice(combo, original) != original:
                continue
            for index, model_row in enumerate(combo.get_model()):
                if str(model_row[1]) == target:
                    combo.set_active(index)
                    combo._user_target = target
                    accepted += 1
                    break
        OkDialog(
            str(_("Hints accepted")),
            ngettext(
                "Set {number_of} drop-down to the suggested source. Review it, change "
                "it if it looks wrong, then press Apply.",
                "Set {number_of} drop-downs to the suggested source. Review them, "
                "change any that look wrong, then press Apply.",
                accepted,
            ).format(number_of=accepted),
            parent=self,
        )

    @reports_apply_errors
    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply chosen source merges, trims, and quarantines."""
        rows_with_choices = [
            dict(row, chosen_target=self.get_choice(combo, row["handle"]))
            for row, combo in self.row_combos
        ]
        plan = plan_source_fixes(rows_with_choices)

        if (
            not plan.get("merge")
            and not plan.get("quarantine")
            and not plan.get("trim")
        ):
            OkDialog(
                str(_("Nothing to fix")),
                str(_("No source-record problems to fix.")),
                parent=self,
            )
            return

        merged, quarantined, trimmed = apply_source_fixes(self.dbstate, plan)
        msg = source_fix_summary(merged, quarantined, trimmed)
        OkDialog(
            str(_("Source fixes applied")),
            msg,
            parent=self,
        )

    def show_dialog(self) -> None:
        """Show and run the modal dialog until user explicitly closes it."""
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
# Source fix dialog helpers
#
# ------------------------------------------------------------
def _source_display(row: dict[str, Any]) -> str:
    """Human-readable label for a source row."""
    title = row.get("title") or _("(unnamed source)")
    cites = row.get("citations", 0)
    cite_str = ngettext("{number_of} citation", "{number_of} citations", cites).format(
        number_of=cites
    )
    if cites == 0:
        title = _("No citations: ") + title
    if row.get("repo_count", 0) == 0:
        title = _("No repository: ") + title
    return "%s (%s, %s)" % (title, row.get("gramps_id", "??"), cite_str)


def _dedupe_handles(handles: list[str]) -> list[str]:
    """De-duplicate handles, preserving order."""
    seen = set()
    out = []
    for handle in handles:
        if handle and handle not in seen:
            seen.add(handle)
            out.append(handle)
    return out


def _title_rank(title: Any) -> int:
    """Return 1 for a title containing "U.S.", the newer database naming."""
    return 1 if re.search(r"\bU\.S\.", str(title or "")) else 0


def _pick_keeper(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the preferred keeper for a duplicate group.

    A source with a repository wins, then the title with the newer "U.S."
    wording, then the one with more citations.
    """
    return sorted(
        group,
        key=lambda r: (
            r.get("repo_count", 0),
            _title_rank(r.get("title")),
            r.get("citations", 0),
        ),
        reverse=True,
    )[0]


def build_source_fix_rows(
    stats: dict[str, Any], db: DbReadBase | None = None
) -> list[dict[str, Any]]:
    """Build per-source fix rows from collected database stats."""
    rows: list[dict[str, Any]] = []
    handled_handles: set[str] = set()

    repo_name_by_handle: dict[str, str] = {}
    clean_sources_by_title: dict[str, dict[str, Any]] = {}
    if db:
        try:
            for src_h in db.iter_source_handles():
                src = db.get_source_from_handle(src_h)
                if src:
                    s_title = str(src.get_title() or "")
                    if s_title and s_title == s_title.strip():
                        clean_sources_by_title[s_title.strip().lower()] = {
                            "handle": src_h,
                            "title": s_title,
                            "gramps_id": str(src.get_gramps_id() or ""),
                        }
                    refs = list(src.get_reporef_list())
                    if refs:
                        r_h = refs[0].get_reference_handle()
                        if r_h:
                            repo = db.get_repository_from_handle(r_h)
                            if repo:
                                repo_name_by_handle[src_h] = str(
                                    repo.get_name() or ""
                                ).strip()
        except Exception:  # pylint: disable=broad-except
            pass

    # 1) Near-duplicate groups -> merge action
    for group in stats.get("near_duplicates", []):
        group = [r for r in group if r.get("handle")]
        if len(group) < 2:
            continue
        keeper = _pick_keeper(group)
        keeper_disp = _source_display(keeper)

        for member in group:
            m_handle = member["handle"]
            handled_handles.add(m_handle)
            m_disp = _source_display(member)
            is_keeper = m_handle == keeper["handle"]

            # Dropdown options: Option 0 is current database value (default)
            options = [(m_disp, m_handle)]
            for other in group:
                if other["handle"] != m_handle:
                    options.append((_source_display(other), other["handle"]))

            if is_keeper:
                hint_target = ""
                hint_reason = ""
                hint_display = ""
            else:
                hint_target = keeper["handle"]
                if keeper.get("repo_count", 0) > 0 and member.get("repo_count", 0) == 0:
                    hint_reason = str(_("Keeper has repository"))
                elif keeper.get("citations", 0) > member.get("citations", 0):
                    hint_reason = str(
                        ngettext(
                            "Keeper has {number_of} citation",
                            "Keeper has {number_of} citations",
                            keeper.get("citations", 0),
                        ).format(number_of=keeper.get("citations", 0))
                    )
                else:
                    hint_reason = str(_("Preferred keeper"))
                hint_display = "%s\n(%s)" % (keeper_disp, hint_reason)

            repo_name = repo_name_by_handle.get(m_handle) or (
                str(_("(no repository)"))
                if member.get("repo_count", 0) == 0
                else str(_("Repository"))
            )

            rows.append(
                {
                    "handle": m_handle,
                    "title": member.get("title", ""),
                    "gramps_id": member.get("gramps_id", ""),
                    "display": m_disp,
                    "repo_name": repo_name,
                    "citations": member.get("citations", 0),
                    "options": options,
                    "best_guess": m_disp,
                    "hint_target": hint_target,
                    "hint_reason": hint_reason,
                    "hint_display": hint_display,
                    "problem": "merge",
                    "is_keeper": is_keeper,
                    "skip": False,
                }
            )

    # 2) Fuzzy title & heuristic similarity matching
    if db:
        all_handles: list[str] = []
        if hasattr(db, "iter_source_handles"):
            try:
                all_handles = list(db.iter_source_handles())
            except Exception:
                all_handles = []
        if not all_handles:
            all_handles = [
                r["handle"] for r in stats.get("source_rows", []) if r.get("handle")
            ]

        cites_by_source = {
            r["handle"]: r.get("citations", 0)
            for r in stats.get("source_rows", [])
            if r.get("handle")
        }

        keeper_rows_by_handle: dict[str, dict[str, Any]] = {
            r["handle"]: r for r in rows if r.get("is_keeper")
        }

        for handle in all_handles:
            if handle in handled_handles:
                continue
            match = suggest_source_merge_target(
                handle, all_handles, db, cites_by_source
            )
            if not match:
                continue

            target_handle, reason = match
            if target_handle == handle:
                continue

            target_src = None
            try:
                target_src = db.get_source_from_handle(target_handle)
            except Exception:
                pass
            if target_src is None:
                continue

            t_disp = _source_display(
                {
                    "title": target_src.get_title(),
                    "gramps_id": target_src.get_gramps_id(),
                    "citations": cites_by_source.get(target_handle, 0),
                    "repo_count": len(list(target_src.get_reporef_list() or [])),
                }
            )

            src_obj = None
            try:
                src_obj = db.get_source_from_handle(handle)
            except Exception:
                pass
            if src_obj is None:
                continue

            s_disp = _source_display(
                {
                    "title": src_obj.get_title(),
                    "gramps_id": src_obj.get_gramps_id(),
                    "citations": cites_by_source.get(handle, 0),
                    "repo_count": len(list(src_obj.get_reporef_list() or [])),
                }
            )

            # Between handle and target_handle, determine the preferred keeper
            src_score = (
                len(list(src_obj.get_reporef_list() or [])),
                _title_rank(src_obj.get_title()),
                cites_by_source.get(handle, 0),
            )
            target_score = (
                len(list(target_src.get_reporef_list() or [])),
                _title_rank(target_src.get_title()),
                cites_by_source.get(target_handle, 0),
            )
            if src_score >= target_score:
                k_handle = handle
                k_src = src_obj
                k_disp = s_disp
                d_handle = target_handle
                d_src = target_src
                d_disp = t_disp
            else:
                k_handle = target_handle
                k_src = target_src
                k_disp = t_disp
                d_handle = handle
                d_src = src_obj
                d_disp = s_disp

            # 1. Add/update keeper row (hint is blank)
            if k_handle not in handled_handles:
                k_repo_name = repo_name_by_handle.get(k_handle) or (
                    str(_("(no repository)"))
                    if not list(k_src.get_reporef_list() or [])
                    else str(_("Repository"))
                )
                k_row = {
                    "handle": k_handle,
                    "title": str(k_src.get_title() or ""),
                    "gramps_id": str(k_src.get_gramps_id() or ""),
                    "display": k_disp,
                    "repo_name": k_repo_name,
                    "citations": cites_by_source.get(k_handle, 0),
                    "options": [(k_disp, k_handle), (d_disp, d_handle)],
                    "best_guess": k_disp,
                    "hint_target": "",
                    "hint_reason": "",
                    "hint_display": "",
                    "problem": "merge",
                    "is_keeper": True,
                    "skip": False,
                }
                rows.append(k_row)
                handled_handles.add(k_handle)
                keeper_rows_by_handle[k_handle] = k_row
            else:
                if k_handle in keeper_rows_by_handle:
                    k_row = keeper_rows_by_handle[k_handle]
                    if (d_disp, d_handle) not in k_row["options"]:
                        k_row["options"].append((d_disp, d_handle))

            # 2. Add duplicate row (hint points to keeper)
            d_repo_name = repo_name_by_handle.get(d_handle) or (
                str(_("(no repository)"))
                if not list(d_src.get_reporef_list() or [])
                else str(_("Repository"))
            )
            d_row = {
                "handle": d_handle,
                "title": str(d_src.get_title() or ""),
                "gramps_id": str(d_src.get_gramps_id() or ""),
                "display": d_disp,
                "repo_name": d_repo_name,
                "citations": cites_by_source.get(d_handle, 0),
                "options": [(d_disp, d_handle), (k_disp, k_handle)],
                "best_guess": d_disp,
                "hint_target": k_handle,
                "hint_reason": reason,
                "hint_display": "%s\n(%s)" % (k_disp, reason),
                "problem": "merge",
                "is_keeper": False,
                "skip": False,
            }
            rows.append(d_row)
            handled_handles.add(d_handle)

    # 3) Sources with leading or trailing whitespace
    for row in stats.get("source_rows", []):
        handle = row.get("handle")
        if not handle or handle in handled_handles:
            continue

        title = str(row.get("title") or "")
        author = str(row.get("author") or "")
        pub = str(row.get("publication") or row.get("publication_info") or "")
        abbr = str(row.get("abbreviation") or "")

        # Also check db object if fields not in row dict
        if db and not author and not pub and not abbr:
            try:
                src_obj = db.get_source_from_handle(handle)
                if src_obj:
                    title = str(src_obj.get_title() or "")
                    author = str(src_obj.get_author() or "")
                    pub = str(src_obj.get_publication_info() or "")
                    abbr = str(src_obj.get_abbreviation() or "")
            except Exception:  # pylint: disable=broad-except
                pass

        ws_fields = []
        if title != title.strip():
            ws_fields.append("title")
        if author != author.strip():
            ws_fields.append("author")
        if pub != pub.strip():
            ws_fields.append("publication")
        if abbr != abbr.strip():
            ws_fields.append("abbreviation")

        if not ws_fields:
            continue

        handled_handles.add(handle)
        s_disp = _source_display(row)
        options = [(s_disp, handle)]

        # Check if an existing source with the clean title already exists
        clean_match = clean_sources_by_title.get(title.strip().lower())
        if clean_match and clean_match["handle"] != handle:
            match_disp = "%s (%s)" % (clean_match["title"], clean_match["gramps_id"])
            options.append(
                (
                    _("Merge into '{source}'").format(source=match_disp),
                    clean_match["handle"],
                )
            )
            options.append((str(_("Trim whitespace")), "trim"))
            hint_target = clean_match["handle"]
            hint_reason = str(_("Duplicate with clean title"))
            hint_display = "%s\n(%s)" % (match_disp, hint_reason)
        else:
            options.append((str(_("Trim whitespace")), "trim"))
            hint_target = "trim"
            hint_reason = str(_("Leading/trailing whitespace"))
            hint_display = "%s\n(%s)" % (str(_("Trim whitespace")), hint_reason)

        if row.get("repo_count", 0) == 0:
            options.append((str(_("Quarantine (new repository)")), "quarantine"))

        repo_name = repo_name_by_handle.get(handle) or str(_("(no repository)"))

        rows.append(
            {
                "handle": handle,
                "title": title,
                "gramps_id": row.get("gramps_id", ""),
                "display": s_disp,
                "repo_name": repo_name,
                "citations": row.get("citations", 0),
                "options": options,
                "best_guess": s_disp,
                "hint_target": hint_target,
                "hint_reason": hint_reason,
                "hint_display": hint_display,
                "problem": "trim",
                "is_keeper": False,
                "skip": False,
            }
        )

    # 4) Orphan / no-repository sources -> quarantine action
    quarantine_handles = (
        {
            str(repo.get_handle())
            for repo in db.iter_repositories()
            if str(repo.get_name() or "").strip().lower()
            == _QUARANTINE_REPO_NAME.lower()
        }
        if db is not None and hasattr(db, "iter_repositories")
        else set()
    )
    for row in stats.get("source_rows", []):
        handle = row.get("handle")
        if not handle or handle in handled_handles:
            continue
        if (
            quarantine_handles
            and db is not None
            and hasattr(db, "get_source_from_handle")
        ):
            src_obj = db.get_source_from_handle(handle)
            if src_obj is not None and any(
                str(ref.get_reference_handle()) in quarantine_handles
                for ref in src_obj.get_reporef_list()
            ):
                continue  # already quarantined; nothing more to decide
        reasons = []
        # A title that is really a file name (for example a scanned family
        # tree image) is a media object, not a source.
        if kind_of_non_title(str(row.get("title") or "")) == "filename":
            reasons.append(str(_("title is a file name")))
        if row.get("citations", 0) == 0:
            reasons.append(str(_("orphan")))
        if row.get("repo_count", 0) == 0:
            reasons.append(str(_("no repository")))
        if not reasons:
            continue
        reason_str = ", ".join(reasons)
        s_disp = _source_display(row)
        options = [
            (s_disp, handle),
            (str(_("Quarantine (new repository)")), "quarantine"),
        ]
        hint_target = "quarantine"
        hint_reason = reason_str
        hint_display = "%s\n(%s)" % (str(_("Quarantine")), hint_reason)

        repo_name = repo_name_by_handle.get(handle) or str(_("(no repository)"))

        rows.append(
            {
                "handle": handle,
                "title": row.get("title", ""),
                "gramps_id": row.get("gramps_id", ""),
                "display": s_disp,
                "repo_name": repo_name,
                "citations": row.get("citations", 0),
                "options": options,
                "best_guess": s_disp,
                "hint_target": hint_target,
                "hint_reason": hint_reason,
                "hint_display": hint_display,
                "problem": "quarantine",
                "is_keeper": False,
                "skip": False,
            }
        )

    return rows


def _resolve_merge_target(handle: str, merge_targets: dict[str, str]) -> str:
    """Follow merge chains to find the final target, detecting cycles."""
    visited = set()
    curr = handle
    while curr in merge_targets:
        if curr in visited:
            break
        visited.add(curr)
        curr = merge_targets[curr]
    return curr


def plan_source_fixes(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Turn dialog rows into an apply plan without touching the database."""
    plan: dict[str, list[dict[str, Any]]] = {
        "merge": [],
        "quarantine": [],
        "trim": [],
    }
    merge_targets: dict[str, str] = {}
    quarantine_handles: set[str] = set()
    trim_handles: set[str] = set()

    for row in rows:
        if row.get("skip"):
            continue
        # Support chosen_target (explicitly selected), or fallback to hint_target
        chosen = row.get("chosen_target") or row.get("hint_target")
        handle = row.get("handle")
        if not chosen or not handle:
            # Fallback for old dictionary format
            if row.get("problem") == "merge" and "keeper_handle" in row:
                plan["merge"].append(
                    {
                        "keeper_handle": row["keeper_handle"],
                        "discard_handles": row.get("discard_handles", []),
                    }
                )
            elif row.get("problem") == "quarantine" and "quarantine_handle" in row:
                quarantine_handles.add(row["quarantine_handle"])
            continue

        if chosen == "trim":
            trim_handles.add(handle)
        elif chosen == "quarantine":
            quarantine_handles.add(handle)
        elif chosen != handle:
            merge_targets[handle] = chosen

    # Follow merge chains (and stop at cycles) so each discard names the final keeper
    merges_by_keeper: dict[str, set[str]] = defaultdict(set)
    for src_h in merge_targets:
        final_keeper = _resolve_merge_target(src_h, merge_targets)
        if final_keeper != src_h:
            merges_by_keeper[final_keeper].add(src_h)

    for keeper, discards in merges_by_keeper.items():
        clean_discards = [h for h in discards if h != keeper]
        if clean_discards:
            plan["merge"].append(
                {
                    "keeper_handle": keeper,
                    "discard_handles": clean_discards,
                }
            )

    for handle in trim_handles:
        if handle not in merge_targets:
            plan["trim"].append({"source_handle": handle})

    for handle in quarantine_handles:
        if handle not in merge_targets:
            plan["quarantine"].append(
                {
                    "source_handle": handle,
                    "target_repo_name": _QUARANTINE_REPO_NAME,
                }
            )

    return plan


def _get_or_create_quarantine_repo(db: DbWriteBase, trans: Any) -> str:
    """Return the handle of an existing or newly created Quarantine repository."""
    for repo in db.iter_repositories():
        if str(repo.get_name() or "").strip().lower() == "quarantine":
            return str(repo.get_handle() or "")
    repo = Repository()
    repo.set_name(_QUARANTINE_REPO_NAME)
    db.add_repository(repo, trans)
    return str(repo.get_handle() or "")


def apply_source_fixes(
    dbstate: Any, plan: dict[str, Any], trans: Any = None
) -> tuple[int, int, int]:
    """Apply a source-fix plan in one transaction (one Edit > Undo).

    ``dbstate`` may be a DbState or a database. Returns
    ``(merged, quarantined, trimmed)``. A quarantined source keeps any
    repository it already has and gains the Quarantine repository, so no
    existing repository link is lost.
    """
    db = getattr(dbstate, "db", dbstate)
    if trans is None:
        with DbTxn(_("Fix Sources"), db) as new_trans:
            return apply_source_fixes(db, plan, new_trans)
    engine = GWizardCitationRepairEngine()
    merged = 0
    quarantined = 0
    trimmed = 0

    already_merged_or_deleted: set[str] = set()
    # Create the Quarantine repository only when a source needs it, so an
    # unused empty repository is not left behind.
    quarantine_handle = (
        _get_or_create_quarantine_repo(db, trans) if plan.get("quarantine") else ""
    )

    # Errors are not caught here: one failure aborts the whole transaction,
    # so the database is never left half-fixed, and the caller reports it.
    for entry in plan.get("trim", []):
        source = db.get_source_from_handle(entry["source_handle"])
        if source is None:
            continue
        changed = False
        for getter, setter in (
            (source.get_title, source.set_title),
            (source.get_author, source.set_author),
            (source.get_publication_info, source.set_publication_info),
            (source.get_abbreviation, source.set_abbreviation),
        ):
            value = str(getter() or "")
            if value != value.strip():
                setter(value.strip())
                changed = True
        if changed:
            db.commit_source(source, trans)
            trimmed += 1

    for entry in plan.get("merge", []):
        keeper = entry["keeper_handle"]
        if keeper in already_merged_or_deleted:
            LOG.warning("Keeper %s was already merged; skipping", keeper)
            continue
        for discard in entry.get("discard_handles", []):
            if discard == keeper or discard in already_merged_or_deleted:
                continue
            if engine.merge_sources(db, keeper, discard, trans):
                merged += 1
                already_merged_or_deleted.add(discard)

    for entry in plan.get("quarantine", []):
        src_handle = entry["source_handle"]
        if src_handle in already_merged_or_deleted:
            continue
        source = db.get_source_from_handle(src_handle)
        if source is None:
            continue
        if any(
            ref.get_reference_handle() == quarantine_handle
            for ref in source.get_reporef_list()
        ):
            continue
        ref = RepoRef()
        ref.set_reference_handle(quarantine_handle)
        source.add_repo_reference(ref)
        db.commit_source(source, trans)
        quarantined += 1

    return merged, quarantined, trimmed


def source_fix_summary(merged: int, quarantined: int, trimmed: int) -> str:
    """Return translated sentences describing the result of the source fixes.

    :returns: One sentence per kind of change, or a single "nothing" line.
    """
    sentences = []
    if merged:
        sentences.append(
            ngettext(
                "Merged {number_of} duplicate source.",
                "Merged {number_of} duplicate sources.",
                merged,
            ).format(number_of=merged)
        )
    if quarantined:
        sentences.append(
            ngettext(
                "Quarantined {number_of} source.",
                "Quarantined {number_of} sources.",
                quarantined,
            ).format(number_of=quarantined)
        )
    if trimmed:
        sentences.append(
            ngettext(
                "Trimmed spaces in {number_of} source.",
                "Trimmed spaces in {number_of} sources.",
                trimmed,
            ).format(number_of=trimmed)
        )
    if not sentences:
        return _("No sources needed fixing.")
    return " ".join(sentences)


def auto_fix_sources(db: DbWriteBase) -> tuple[int, int, int]:
    """Accept every hint and apply it, exactly as the Fix Sources dialog does.

    This is the single no-review implementation, shared by the per-step
    Auto button and Accept all hints. Returns
    ``(merged, quarantined, trimmed)``.
    """
    stats = collect_db_stats(db)
    rows = build_source_fix_rows(stats, db)
    return apply_source_fixes(db, plan_source_fixes(rows))
