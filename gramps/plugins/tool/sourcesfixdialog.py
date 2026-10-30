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
import logging
from collections import defaultdict
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

from gramps.gen.db import DbTxn
from gramps.gen.lib import Repository, RepoRef
from gramps.gen.merge import MergeSourceQuery
from gramps.plugins.tool.gwizardcitationfix import collect_db_stats

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# SourceFixDialog
#
# ------------------------------------------------------------
class SourceFixDialog(Gtk.Dialog):
    """Review and fix source-record problems in a dialog."""

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
        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dlg, resp: dlg.destroy())
        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

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

        stats = collect_db_stats(self.dbstate.db)
        rows = build_source_fix_rows(stats)
        if not rows:
            done = Gtk.Label(label=str(_("No source-record problems found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return
        content.add(self.build_header())
        content.add(self.build_rows(rows))
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

    def build_header(self) -> Gtk.Box:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Source problem")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(True)
        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Fix into (target)")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(True)
        header.pack_start(left_head, True, True, 0)
        header.pack_start(right_head, True, True, 0)
        return header

    def build_rows(self, rows: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(220)
        scrolled.set_min_content_width(560)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scrolled.add(listbox)
        for row in rows:
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            left = Gtk.Label(label=row["display"])
            left.set_halign(Gtk.Align.START)
            left.set_hexpand(True)
            left.set_line_wrap(True)
            left.set_max_width_chars(44)
            line.pack_start(left, True, True, 0)
            combo = Gtk.ComboBoxText()
            combo.set_hexpand(True)
            for option in row["options"]:
                combo.append_text(option)
            combo.set_active(0)
            line.pack_start(combo, True, True, 0)
            listbox.pack_start(line, False, False, 0)
            self.combos.append(
                (
                    row.get("keeper_handle") or row.get("quarantine_handle") or "",
                    combo,
                    row["best_guess"],
                )
            )
        return scrolled

    def build_buttons(self) -> Gtk.Box:
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_homogeneous(True)
        auto_button = Gtk.Button(label=str(_("Auto (best guess)")))
        apply_button = Gtk.Button(label=str(_("Apply")))
        auto_button.connect("clicked", self.cb_set_best)
        apply_button.connect("clicked", self.cb_apply)
        buttons.pack_start(auto_button, True, True, 0)
        buttons.pack_start(apply_button, True, True, 0)
        return buttons

    def get_choices(self) -> dict[str, str]:
        return {
            handle: self.get_choice(combo, handle)
            for handle, combo, _best in self.combos
        }

    def get_choice(self, combo: Gtk.ComboBox, fallback: str) -> str:
        active = combo.get_active_iter()
        if active is None:
            return fallback
        return str(combo.get_model()[active][0])

    def run_auto(self, parent: Gtk.Window | None = None) -> None:
        stats = collect_db_stats(self.dbstate.db)
        rows = build_source_fix_rows(stats)
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
        self.show_all()
        self.run()
        self.destroy()

    def cb_set_best(self, _button: Gtk.Button) -> None:
        for handle, combo, best in self.combos:
            model = combo.get_model()
            for index, option_row in enumerate(model):
                if str(option_row[0]) == best:
                    combo.set_active(index)
                    break

    def cb_apply(self, _button: Gtk.Button) -> None:
        rows = build_source_fix_rows(collect_db_stats(self.dbstate.db))
        plan = plan_source_fixes(rows)
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


# ------------------------------------------------------------
#
# Source fix dialog helpers
#
# ------------------------------------------------------------
_QUARANTINE_REPO_NAME = "Quarantine"


def _source_display(row):
    """Human-readable label for a source row."""
    title = row.get("title") or _("(unnamed source)")
    if row.get("citations", 0) == 0:
        title = _("No citations: ") + title
    if row.get("repo_count", 0) == 0:
        title = _("No repository: ") + title
    return title + " (%s)" % row.get("gramps_id", "??")


def _dedupe_handles(handles):
    """De-duplicate repository handles, preserving order."""
    seen = set()
    out = []
    for handle in handles:
        if handle and handle not in seen:
            seen.add(handle)
            out.append(handle)
    return out


def _pick_keeper(group):
    """Pick the preferred keeper for a duplicate group."""
    return sorted(
        group,
        key=lambda r: (r.get("repo_count", 0), r.get("citations", 0)),
        reverse=True,
    )[0]


def build_source_fix_rows(stats):
    """Build per-source fix rows from collected database stats."""
    rows = []

    # 1) near-duplicate groups -> merge action
    for group in stats.get("near_duplicates", []):
        group = [r for r in group if r.get("handle")]
        if len(group) < 2:
            continue
        keeper = _pick_keeper(group)
        handles = _dedupe_handles([r["handle"] for r in group])
        title = keeper.get("title") or _("unnamed source")
        display = _("Merge %d near-duplicate sources of '%s'") % (len(group), title)
        options = [_source_display(member) for member in group]
        rows.append(
            {
                "display": display,
                "options": options,
                "best_guess": _source_display(keeper),
                "problem": "merge",
                "keeper_handle": keeper["handle"],
                "discard_handles": [h for h in handles if h != keeper["handle"]],
                "skip": False,
            }
        )

    # 2) orphan / no-repository sources -> quarantine action (only if not
    #    already fixed by a merge row above).
    merged = set()
    for group in stats.get("near_duplicates", []):
        for member in group:
            handle = member.get("handle")
            if handle:
                merged.add(handle)
    for row in stats.get("source_rows", []):
        handle = row.get("handle")
        if not handle or handle in merged:
            continue
        reasons = []
        if row.get("citations", 0) == 0:
            reasons.append("orphan")
        if row.get("repo_count", 0) == 0:
            reasons.append("no_repo")
        if not reasons:
            continue
        title = row.get("title") or _("unnamed source")
        display = _("Quarantine source '%s' (%s)") % (title, ", ".join(reasons))
        rows.append(
            {
                "display": display,
                "options": [_("Quarantine new repository")],
                "best_guess": _("Quarantine new repository"),
                "problem": "quarantine",
                "quarantine_handle": handle,
                "skip": False,
            }
        )

    return rows


def plan_source_fixes(rows):
    """Turn dialog rows into an apply plan without touching the database."""
    plan = {"merge": [], "quarantine": []}
    for row in rows:
        if row.get("skip"):
            continue
        if row["problem"] == "merge":
            plan["merge"].append(
                {
                    "keeper_handle": row["keeper_handle"],
                    "discard_handles": row["discard_handles"],
                }
            )
        elif row["problem"] == "quarantine":
            plan["quarantine"].append(
                {
                    "source_handle": row["quarantine_handle"],
                    "target_repo_name": _QUARANTINE_REPO_NAME,
                }
            )
    return plan


def _get_or_create_quarantine_repo(db):
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


def apply_source_fixes(dbstate, plan):
    """Apply a source-fix plan against the database."""
    from gramps.gen.db import DbTxn
    from gramps.gen.lib import RepoRef
    from gramps.gen.merge import MergeSourceQuery

    db = dbstate.db
    merged = 0
    quarantined = 0

    quarantine_handle = _get_or_create_quarantine_repo(db)

    for entry in plan.get("merge", []):
        keeper = entry["keeper_handle"]
        for discard in entry["discard_handles"]:
            try:
                MergeSourceQuery(dbstate, keeper, discard).execute()
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
