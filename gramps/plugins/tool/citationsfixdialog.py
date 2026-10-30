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

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

PROBLEM_TREE_CONFIDENCE = "tree_confidence"
PROBLEM_MANUAL_REVIEW = "manual_review"
PROBLEM_NONE = "none"

NO_SOURCE = "(no source)"


# ------------------------------------------------------------
#
# CitationFixDialog
#
# ------------------------------------------------------------
class CitationFixDialog(Gtk.Dialog):
    """Review and fix citation problems in a dialog.

    Three columns: Source (the source the citation references),
    Suggested (a dropdown of fix actions), and Citation (citation
    details such as page, date, confidence).  Citations are listed one
    per row, sorted by source name alphabetically, with citations that
    have no source reference listed last under "(no source)".
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
                    "Review each citation and choose a fix action.  "
                    "FamilySearch Tree citations with high confidence "
                    "can be lowered; missing page/date must be added "
                    "manually in the citation editor."
                )
            ),
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        self.rows = build_citation_fix_rows(self.dbstate.db)
        if not self.rows:
            done = Gtk.Label(label=str(_("No citations found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(_("Total citations: %d") % len(self.rows)),
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        # Header row above the scrolled grid so it stays locked when
        # scrolling through the data rows.
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(0)
        header_grid.set_row_spacing(0)
        header_grid.set_column_homogeneous(True)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Source")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(True)
        mid_head = Gtk.Label()
        mid_head.set_markup("<b>%s</b>" % str(_("Suggested")))
        mid_head.set_halign(Gtk.Align.START)
        mid_head.set_hexpand(True)
        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Citation")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(True)
        header_grid.attach(left_head, 0, 0, 1, 1)
        header_grid.attach(mid_head, 1, 0, 1, 1)
        header_grid.attach(right_head, 2, 0, 1, 1)
        content.add(header_grid)

        content.add(self.build_rows(self.rows))
        hint = Gtk.Label(
            label=str(
                _(
                    "Lowering confidence does not delete citations; it only "
                    "records that the FamilySearch Tree is a derivative "
                    "source.  Missing page/date must be entered by hand."
                )
            )
        )
        hint.set_line_wrap(True)
        hint.set_halign(Gtk.Align.START)
        content.add(hint)
        content.add(self.build_buttons())

    def build_header(self, grid: Gtk.Grid) -> None:
        """Attach the three-column header to a grid (kept for API compat)."""
        left_head = Gtk.Label()
        left_head.set_markup("<b>%s</b>" % str(_("Source")))
        left_head.set_halign(Gtk.Align.START)
        left_head.set_hexpand(True)
        mid_head = Gtk.Label()
        mid_head.set_markup("<b>%s</b>" % str(_("Suggested")))
        mid_head.set_halign(Gtk.Align.START)
        mid_head.set_hexpand(True)
        right_head = Gtk.Label()
        right_head.set_markup("<b>%s</b>" % str(_("Citation")))
        right_head.set_halign(Gtk.Align.START)
        right_head.set_hexpand(True)
        grid.attach(left_head, 0, 0, 1, 1)
        grid.attach(mid_head, 1, 0, 1, 1)
        grid.attach(right_head, 2, 0, 1, 1)

    def build_rows(self, rows: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build a 3-column grid: Source | Suggested | Citation."""
        grid = Gtk.Grid()
        grid.set_column_spacing(0)
        grid.set_row_spacing(0)
        grid.set_column_homogeneous(True)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for row in rows:
            # Column 0: source name
            src_label = Gtk.Label(label=row["source_name"])
            src_label.set_halign(Gtk.Align.START)
            src_label.set_line_wrap(True)
            grid.attach(src_label, 0, row_index, 1, 1)

            # Column 1: suggested fix dropdown
            combo = Gtk.ComboBoxText()
            combo.set_hexpand(False)
            combo.set_size_request(210, -1)
            for option in row["options"]:
                combo.append_text(option)
            combo.set_active(0)
            grid.attach(combo, 1, row_index, 1, 1)

            # Column 2: citation details
            cit_label = Gtk.Label(label=row["citation_display"])
            cit_label.set_halign(Gtk.Align.START)
            cit_label.set_line_wrap(True)
            grid.attach(cit_label, 2, row_index, 1, 1)

            self.combos.append((row["citation_handle"], combo, row["best_guess"]))
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
            citation_handle: self.get_choice(combo, citation_handle)
            for citation_handle, combo, _best in self.combos
        }

    def get_choice(self, combo: Gtk.ComboBox, fallback: str) -> str:
        active = combo.get_active_iter()
        if active is None:
            return fallback
        return str(combo.get_model()[active][0])

    def run_auto(self, parent: Gtk.Window | None = None) -> None:
        """Apply best-guess fixes without showing the dialog."""
        rows = build_citation_fix_rows(self.dbstate.db)
        plan = plan_citation_fixes(rows)
        owner = parent or self.get_transient_for()
        if not plan.get("tree_confidence") and not plan.get("manual_review"):
            OkDialog(
                str(_("Nothing to clean")),
                str(_("No citation problems found.")),
                parent=owner,
            )
            return
        changed = apply_citation_fixes(self.dbstate, plan)
        lowered = changed.get("tree_confidence_lowered", 0)
        manual = plan.get("manual_review", 0)
        OkDialog(
            str(_("Auto clean: citations")),
            str(
                _("Lowered confidence of %d citations, %d need manual review.")
                % (lowered, manual)
            ),
            parent=owner,
        )

    def show_dialog(self) -> None:
        self.show_all()
        self.run()
        self.destroy()

    def cb_set_best(self, _button: Gtk.Button) -> None:
        for citation_handle, combo, best in self.combos:
            model = combo.get_model()
            for index in range(len(model)):
                if str(model[index][0]) == best:
                    combo.set_active(index)
                    break

    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply the user choices as citation fixes."""
        rows = build_citation_fix_rows(self.dbstate.db)
        plan = plan_citation_fixes(rows)
        if not plan.get("tree_confidence") and not plan.get("manual_review"):
            OkDialog(
                str(_("Nothing to clean")),
                str(_("No citation problems found.")),
                parent=self,
            )
            return
        changed = apply_citation_fixes(self.dbstate, plan)
        lowered = changed.get("tree_confidence_lowered", 0)
        manual = plan.get("manual_review", 0)
        OkDialog(
            str(_("Citation fixes applied")),
            str(
                _("Lowered confidence of %d citations, %d need manual review.")
                % (lowered, manual)
            ),
            parent=self,
        )
        self.destroy()


# ------------------------------------------------------------
#
# Citation fix helpers
#
# ------------------------------------------------------------
PROBLEM_TREE_CONFIDENCE = "tree_confidence"
PROBLEM_MANUAL_REVIEW = "manual_review"
PROBLEM_NONE = "none"

NO_SOURCE = "(no source)"


def build_citation_fix_rows(db) -> list[dict[str, Any]]:
    """Build per-citation rows from the database, sorted by source name.

    Citations with no source reference are listed last under ``(no source)``.
    """
    # Build source lookup: handle -> title
    source_titles: dict[str, str] = {}
    tree_handles: set[str] = set()
    try:
        for src in db.iter_sources():
            try:
                handle = str(src.get_handle() or "")
                title = str(src.get_title() or "")
                if handle:
                    source_titles[handle] = title
                    lowered = title.lower()
                    if "familysearch" in lowered and "family tree" in lowered:
                        tree_handles.add(handle)
            except Exception:
                continue
    except Exception:
        LOG.exception("Failed to iterate sources")

    rows: list[dict[str, Any]] = []
    try:
        for cit in db.iter_citations():
            try:
                cit_handle = str(cit.get_handle() or "")
                src_handle = str(cit.get_reference_handle() or "")
            except Exception:
                continue

            source_name = source_titles.get(src_handle, "")
            if not source_name:
                source_name = NO_SOURCE

            # Build citation display string
            gid = ""
            page = ""
            date_str = ""
            conf = 0
            try:
                gid = str(cit.get_gramps_id() or "")
            except Exception:
                pass
            try:
                page = str(cit.get_page() or "").strip()
            except Exception:
                pass
            try:
                date_obj = cit.get_date_object()
                date_str = str(date_obj) if date_obj else ""
            except Exception:
                pass
            try:
                conf = int(cit.get_confidence_level() or 0)
            except Exception:
                pass

            parts = []
            if gid:
                parts.append(gid)
            if page:
                parts.append("p. %s" % page)
            if date_str:
                parts.append(date_str)
            if conf >= 3:
                parts.append("Confidence %d" % conf)
            citation_display = " | ".join(parts) if parts else "(no details)"

            # Determine suggested actions
            options: list[str] = []
            best_guess = ""
            problem = None

            is_tree = src_handle in tree_handles
            if is_tree and conf >= 3:
                options = [
                    _("Lower to Confidence 1"),
                    _("Lower to Confidence 2"),
                    _("No change"),
                ]
                best_guess = _("Lower to Confidence 1")
                problem = PROBLEM_TREE_CONFIDENCE
            else:
                manual_actions: list[str] = []
                if not page:
                    manual_actions.append(_("Add page/volume (manual)"))
                if not date_str:
                    manual_actions.append(_("Add date (manual)"))
                if manual_actions:
                    options = manual_actions
                    best_guess = manual_actions[0]
                    problem = PROBLEM_MANUAL_REVIEW
                else:
                    options = [_("No action needed")]
                    best_guess = _("No action needed")
                    problem = PROBLEM_NONE

            rows.append(
                {
                    "source_name": source_name,
                    "source_handle": src_handle,
                    "citation_handle": cit_handle,
                    "citation_display": citation_display,
                    "options": options,
                    "best_guess": best_guess,
                    "problem": problem,
                }
            )
    except Exception:
        LOG.exception("Failed to iterate citations")

    # Sort: named sources first (alphabetical), then "(no source)" last
    rows.sort(key=lambda r: (r["source_name"] == NO_SOURCE, r["source_name"]))

    return rows


def plan_citation_fixes(rows):
    """Turn dialog rows into an apply plan (no database access)."""
    plan = {
        "tree_confidence": [],
        "manual_review": 0,
    }
    for row in rows:
        if row.get("skip"):
            continue
        problem = row.get("problem")
        if problem == PROBLEM_TREE_CONFIDENCE:
            choice = row.get("best_guess", "")
            if choice == _("Lower to Confidence 1"):
                plan["tree_confidence"].append(
                    {"citation_handle": row["citation_handle"], "target_level": 1}
                )
            elif choice == _("Lower to Confidence 2"):
                plan["tree_confidence"].append(
                    {"citation_handle": row["citation_handle"], "target_level": 2}
                )
        elif problem == PROBLEM_MANUAL_REVIEW:
            plan["manual_review"] += 1
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
    lowered = 0
    with DbTxn(_("Lower tree citation confidence"), db) as trans:
        for entry in plan.get("tree_confidence", []):
            cit = db.get_citation_from_handle(entry["citation_handle"])
            if cit is None:
                continue
            try:
                cit.set_confidence_level(entry["target_level"])
                db.commit_citation(cit, trans)
                lowered += 1
            except Exception:
                LOG.exception("Failed to lower citation confidence")
    return {"tree_confidence_lowered": lowered}
