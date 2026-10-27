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

"""Citation-fix dialog for the GWizard citation fix tool."""

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
from gramps.gen.db import DbTxn
from gramps.plugins.tool.gwizardcitationfix import collect_db_stats

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# CitationFixDialog
#
# ------------------------------------------------------------
class CitationFixDialog(Gtk.Dialog):
    """Review and fix citation problems in a dialog.

    Left column shows citation problems; the right column is a dropdown
    for the chosen target.  Auto (best guess) lowers over-confident
    FamilySearch Tree citation confidence, since a user-edited tree is
    a derivative/secondary source.  Missing page/date fields must be
    filled in manually by the user.
    """

    def __init__(
        self,
        title: str,
        dbstate: Any,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        """Build the citation-fix dialog."""
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
                    "Lower over-confident FamilySearch Tree citation confidence, "
                    "and add missing page/date detail by hand."
                )
            ),
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        stats = collect_db_stats(self.dbstate.db)
        rows = build_citation_fix_rows(stats)
        if not rows:
            done = Gtk.Label(label=str(_("No citation problems found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return
        content.add(self.build_header())
        content.add(self.build_rows(rows))
        hint = Gtk.Label(
            label=str(
                _(
                    "Lowering confidence does not delete citations; it only "
                    "records that the FamilySearch Tree is a derivative source. "
                    "Missing page/date must be entered by hand."
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
        left_head.set_markup("<b>%s</b>" % str(_("Citation problem")))
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
            self.combos.append((row["problem"], combo, row["best_guess"]))
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
            problem: self.get_choice(combo, problem)
            for problem, combo, _best in self.combos
        }

    def get_choice(self, combo: Gtk.ComboBox, fallback: str) -> str:
        active = combo.get_active_iter()
        if active is None:
            return fallback
        return str(combo.get_model()[active][0])

    def run_auto(self, parent: Gtk.Window | None = None) -> None:
        stats = collect_db_stats(self.dbstate.db)
        rows = build_citation_fix_rows(stats)
        plan = plan_citation_fixes(rows)
        owner = parent or self.get_transient_for()
        changed = apply_citation_fixes(self.dbstate, plan)
        lowered = changed.get("tree_confidence_lowered", 0)
        if lowered == 0:
            OkDialog(
                str(_("Nothing to clean")),
                str(_("No over-confident FamilySearch Tree citations to fix.")),
                parent=owner,
            )
            return
        OkDialog(
            str(_("Auto clean: citations")),
            str(_("Lowered confidence of %d FamilySearch Tree citations.") % lowered),
            parent=owner,
        )

    def show_dialog(self) -> None:
        self.show_all()
        self.run()
        self.destroy()

    def cb_set_best(self, _button: Gtk.Button) -> None:
        for problem, combo, best in self.combos:
            model = combo.get_model()
            for index, option_row in enumerate(model):
                if str(option_row[0]) == best:
                    combo.set_active(index)
                    break

    def cb_apply(self, _button: Gtk.Button) -> None:
        stats = collect_db_stats(self.dbstate.db)
        rows = build_citation_fix_rows(stats)
        plan = plan_citation_fixes(rows)
        manual = [r for r in rows if r["problem"] in ("no_page", "no_date")]
        if not plan.get("tree_conf_high"):
            OkDialog(
                str(_("Nothing to clean")),
                str(
                    _(
                        "No over-confident FamilySearch Tree citations to fix. "
                        "Page/date fixes are manual."
                    )
                ),
                parent=self,
            )
            return
        changed = apply_citation_fixes(self.dbstate, plan)
        lowered = changed.get("tree_confidence_lowered", 0)
        OkDialog(
            str(_("Citation fixes applied")),
            str(_("Lowered confidence of %d FamilySearch Tree citations.") % lowered),
            parent=self,
        )
        self.destroy()


# ------------------------------------------------------------
#
# Citation fix helpers
#
# ------------------------------------------------------------
PROBLEM_NO_PAGE = "no_page"
PROBLEM_NO_DATE = "no_date"
PROBLEM_TREE_CONFIDENCE = "tree_confidence"


def build_citation_fix_rows(stats):
    """Build per-citation-problem rows from collected database stats."""
    rows = []

    no_page = int(stats.get("citations_no_page", 0) or 0)
    if no_page:
        rows.append(
            {
                "display": _("Add page/vol/entry to %d citations") % no_page,
                "options": [_("Review in citation editor (manual)")],
                "best_guess": _("Review in citation editor (manual)"),
                "problem": PROBLEM_NO_PAGE,
                "skip": False,
            }
        )

    no_date = int(stats.get("citations_no_date", 0) or 0)
    if no_date:
        rows.append(
            {
                "display": _("Add date to %d citations") % no_date,
                "options": [_("Review in citation editor (manual)")],
                "best_guess": _("Review in citation editor (manual)"),
                "problem": PROBLEM_NO_DATE,
                "skip": False,
            }
        )

    tree_conf_high = int(stats.get("tree_conf_high", 0) or 0)
    if tree_conf_high:
        rows.append(
            {
                "display": _("Lower confidence of %d FamilySearch Tree citations")
                % tree_conf_high,
                "options": [
                    _("Lower to Confidence 1"),
                    _("Lower to Confidence 2"),
                    _("No change"),
                ],
                "best_guess": _("Lower to Confidence 1"),
                "problem": PROBLEM_TREE_CONFIDENCE,
                "skip": False,
            }
        )

    return rows


def plan_citation_fixes(rows):
    """Turn dialog rows into an apply plan (no database access)."""
    plan = {PROBLEM_NO_PAGE: [], PROBLEM_NO_DATE: [], PROBLEM_TREE_CONFIDENCE: []}
    for row in rows:
        if row.get("skip"):
            continue
        problem = row.get("problem")
        if problem in plan:
            plan[problem].append(row.get("best_guess", ""))
    return plan


def _tree_source_handles(db):
    """Return the gramps handles of FamilySearch family-tree sources."""
    handles = set()
    for src in db.iter_sources():
        try:
            title = str(src.get_title() or "").lower()
        except Exception:  # pylint: disable=broad-except
            title = ""
        if "familysearch" in title and "family tree" in title:
            handles.add(str(src.get_handle() or ""))
    return handles


def apply_citation_fixes(dbstate, plan):
    """Lower over-confident FamilySearch Tree citation confidence."""
    from gramps.gen.db import DbTxn

    db = dbstate.db
    changed = {"tree_confidence_lowered": 0}

    action = plan.get("tree_confidence", [""])
    if not action:
        return changed
    target = action[0]
    if target not in (
        _("Lower to Confidence 1"),
        _("Lower to Confidence 2"),
        _("No change"),
    ):
        return changed
    if target == _("No change"):
        return changed

    tree_handles = _tree_source_handles(db)
    target_level = 1 if target == _("Lower to Confidence 1") else 2
    for citation in db.iter_citations():
        try:
            ref = str(citation.get_reference_handle() or "")
            conf = int(citation.get_confidence_level() or 0)
        except Exception:  # pylint: disable=broad-except
            continue
        if ref in tree_handles and conf >= 3:
            citation.set_confidence_level(target_level)
            with DbTxn(_("Lower tree citation confidence"), db) as trans:
                db.commit_citation(citation, trans)
            changed["tree_confidence_lowered"] += 1

    return changed
