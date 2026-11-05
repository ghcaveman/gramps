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
from gramps.gen.db import DbTxn
from gramps.gen.lib import Repository, RepoRef
from gramps.plugins.tool.gwizardcitationreport import collect_db_stats
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)

_ = glocale.translation.sgettext
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
        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dlg, resp: dlg.destroy())
        self.set_default_size(1480, 420)
        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        stats = collect_db_stats(self.dbstate.db)
        rows = build_source_fix_rows(stats, self.dbstate.db)

        n_sources = len(rows)
        count_label = Gtk.Label()
        count_label.set_markup(
            "<b>%s</b>" % str(_("Problem sources (%d total)") % n_sources)
        )
        count_label.set_halign(Gtk.Align.START)
        count_label.set_hexpand(True)
        content.add(count_label)

        info = Gtk.Label(
            label=(
                description
                if description is not None
                else _(
                    "Merge near-duplicate sources into a single source, and "
                    "quarantine orphan, non-source, and unrepositoryed records."
                )
            ),
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not rows:
            done = Gtk.Label(label=str(_("No source-record problems found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            content.add(self.build_buttons())
            return

        # Add locked header row above the scrolled data grid
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(0)
        header_grid.set_row_spacing(0)
        header_grid.set_column_homogeneous(True)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)
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

        hint = Gtk.Label(
            label=str(
                _(
                    "Merging combines the duplicate sources into one; "
                    "quarantine moves the problem source to a review "
                    "repository and keeps its citations."
                )
            )
        )
        hint.set_line_wrap(True)
        hint.set_halign(Gtk.Align.START)
        content.add(hint)
        content.add(self.build_buttons())

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

    def build_buttons(self) -> Gtk.Box:
        """Return the action button row with Accept hints and Apply."""
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_homogeneous(True)
        n_hints = sum(1 for row, _combo in self.row_combos if row.get("hint_target"))
        accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        accept_button.set_sensitive(n_hints > 0)
        accept_button.connect("clicked", self.cb_accept_hints)
        apply_button = Gtk.Button(label=str(_("Apply")))
        apply_button.connect("clicked", self.cb_apply)
        buttons.pack_start(accept_button, True, True, 0)
        buttons.pack_start(apply_button, True, True, 0)
        return buttons

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
            str(
                _(
                    "Set %d drop-downs to the suggested source. Review "
                    "them, change any that look wrong, then press Apply."
                )
            )
            % accepted,
            parent=self,
        )

    def cb_set_best(self, button: Gtk.Button) -> None:
        """Backward-compatible alias for accepting hints."""
        self.cb_accept_hints(button)

    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply chosen source merges and quarantines."""
        plan: dict[str, Any] = {"merge": [], "quarantine": []}
        merges_by_keeper: dict[str, list[str]] = defaultdict(list)

        for row, combo in self.row_combos:
            source_handle = row["handle"]
            chosen = self.get_choice(combo, source_handle)
            if chosen == source_handle:
                # Kept as-is
                continue
            if chosen == "quarantine":
                plan["quarantine"].append(
                    {
                        "source_handle": source_handle,
                        "target_repo_name": _QUARANTINE_REPO_NAME,
                    }
                )
            else:
                # Merge into chosen keeper handle
                merges_by_keeper[chosen].append(source_handle)

        for keeper, discards in merges_by_keeper.items():
            plan["merge"].append(
                {
                    "keeper_handle": keeper,
                    "discard_handles": [h for h in discards if h != keeper],
                }
            )

        if not plan.get("merge") and not plan.get("quarantine"):
            OkDialog(
                str(_("Nothing to fix")),
                str(_("No source-record problems to fix.")),
                parent=self,
            )
            return

        merged, quarantined = apply_source_fixes(self.dbstate, plan)
        OkDialog(
            str(_("Source fixes applied")),
            str(
                _("Merged %d duplicate sources, quarantined %d.")
                % (merged, quarantined)
            ),
            parent=self,
        )
        self.destroy()

    def run_auto(self, parent: Gtk.Window | None = None) -> None:
        """Run the best-guess auto fix by accepting all hints and applying."""
        stats = collect_db_stats(self.dbstate.db)
        rows = build_source_fix_rows(stats, self.dbstate.db)
        plan = plan_source_fixes(rows)
        owner = parent or self.get_transient_for()
        merged, quarantined = apply_source_fixes(self.dbstate, plan)
        OkDialog(
            str(_("Auto fix: sources")),
            str(
                _("Merged %d duplicate sources, quarantined %d.")
                % (merged, quarantined)
            ),
            parent=owner,
        )

    def show_dialog(self) -> None:
        """Show and run the modal dialog."""
        self.show_all()
        self.run()
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
    cite_str = (
        glocale.translation.ngettext("%d citation", "%d citations", cites) % cites
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


def _pick_keeper(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the preferred keeper for a duplicate group."""
    return sorted(
        group,
        key=lambda r: (r.get("repo_count", 0), r.get("citations", 0)),
        reverse=True,
    )[0]


def build_source_fix_rows(
    stats: dict[str, Any], db: Any = None
) -> list[dict[str, Any]]:
    """Build per-source fix rows from collected database stats."""
    rows: list[dict[str, Any]] = []

    repo_name_by_handle: dict[str, str] = {}
    if db:
        try:
            for src_h in db.iter_source_handles():
                src = db.get_source_from_handle(src_h)
                if src:
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
                        _("Keeper has %d citations") % keeper.get("citations", 0)
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

    # 2) Orphan / no-repository sources -> quarantine action
    merged_handles = {
        m["handle"]
        for g in stats.get("near_duplicates", [])
        for m in g
        if m.get("handle")
    }
    for row in stats.get("source_rows", []):
        handle = row.get("handle")
        if not handle or handle in merged_handles:
            continue
        reasons = []
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


def plan_source_fixes(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Turn dialog rows into an apply plan without touching the database."""
    plan: dict[str, list[dict[str, Any]]] = {"merge": [], "quarantine": []}
    merges_by_keeper: dict[str, list[str]] = defaultdict(list)

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
                plan["quarantine"].append(
                    {
                        "source_handle": row["quarantine_handle"],
                        "target_repo_name": _QUARANTINE_REPO_NAME,
                    }
                )
            continue

        if chosen == "quarantine":
            plan["quarantine"].append(
                {
                    "source_handle": handle,
                    "target_repo_name": _QUARANTINE_REPO_NAME,
                }
            )
        elif chosen != handle:
            merges_by_keeper[chosen].append(handle)

    for keeper, discards in merges_by_keeper.items():
        plan["merge"].append(
            {
                "keeper_handle": keeper,
                "discard_handles": [h for h in discards if h != keeper],
            }
        )
    return plan


def _get_or_create_quarantine_repo(db: Any) -> str:
    """Return the handle of an existing or newly created Quarantine repository."""
    for repo in db.iter_repositories():
        try:
            if str(repo.get_name() or "").strip().lower() == "quarantine":
                return str(repo.get_handle() or "")
        except Exception:  # pylint: disable=broad-except
            continue
    repo = Repository()
    repo.set_name(_QUARANTINE_REPO_NAME)
    with DbTxn(_("Add quarantine repository"), db) as trans:
        db.add_repository(repo, trans)
    return str(repo.get_handle() or "")


def apply_source_fixes(dbstate: Any, plan: dict[str, Any]) -> tuple[int, int]:
    """Apply a source-fix plan against the database."""
    db = dbstate.db
    engine = GWizardCitationRepairEngine()
    merged = 0
    quarantined = 0

    quarantine_handle = _get_or_create_quarantine_repo(db)

    for entry in plan.get("merge", []):
        keeper = entry["keeper_handle"]
        for discard in entry.get("discard_handles", []):
            if discard == keeper:
                continue
            try:
                if engine.merge_sources(db, keeper, discard):
                    merged += 1
            except Exception:  # pylint: disable=broad-except
                LOG.exception("Failed to merge source %s into %s", discard, keeper)

    for entry in plan.get("quarantine", []):
        src_handle = entry["source_handle"]
        try:
            source = db.get_source_from_handle(src_handle)
            if source is None:
                continue
            source.remove_repo_references([r.ref for r in source.get_reporef_list()])
            ref = RepoRef()
            ref.set_reference_handle(quarantine_handle)
            source.add_repo_reference(ref)
            with DbTxn(_("Move source to quarantine repository"), db) as trans:
                db.commit_source(source, trans)
            quarantined += 1
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to quarantine source %s", src_handle)

    return merged, quarantined
