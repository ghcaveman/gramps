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

"""
Alternate GWizard compare window.

The left panel lists every person in the incoming file and opens at the
first detected mismatch, as the standard window does. The right panel lists
only the tree people that are a similar match for the selected incoming
person, closest first, with the closest one selected; picking another row
compares (and merges) with that person instead. Match tolerances are set in
a bar at the top of the window.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
from dataclasses import replace
from typing import Any

# -------------------------------------------------------------------------
#
# GTK/Gnome modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.display.name import displayer as name_displayer
from gramps.gen.gwizard.gwizard_base import CandidateMatcher, safe_get_person
from gramps.gen.gwizard.gwizardgedcom import EXTRA_KINDS, GedGWizard
from gramps.gen.gwizard.gwizardaltmatch import (
    SCOPE_ALL,
    SCOPE_SURNAME,
    SCOPE_SURNAME_INITIAL,
    AltCandidateFinder,
    MatchSettings,
    match_key,
    pair_greedy,
    score_percent,
)
from gramps.gen.lib import Person
from gramps.gen.types import PersonHandle
from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow, _Progress

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)

_ = glocale.translation.gettext

# Column of the panel TreeStores that the left panel shows as "Diff" and the
# right panel shows as "Match".
_MARK_COLUMN = 7


# ------------------------------------------------------------
#
# GWizardAltCompareWindow
#
# ------------------------------------------------------------
class GWizardAltCompareWindow(GWizardCompareWindow):
    """
    Compare window whose right panel lists only similar tree people.

    Reuses the standard window's panels, detail sections, Previous/Next,
    Merge, Add as New and Not a Match; only the matching and the right
    panel's contents differ.
    """

    # Settings used for the next window opened in this session; Apply
    # updates them so the user's tolerances carry over.
    _session_settings = MatchSettings()

    def __init__(
        self,
        uistate: Any,
        dbstate: Any,
        gwizard: GedGWizard,
        parent: Gtk.Window | None = None,
    ) -> None:
        """
        Initialize the window (see GWizardCompareWindow).
        """
        GWizardCompareWindow.__init__(self, uistate, dbstate, gwizard, parent=parent)
        self.set_title(_("GWizard Compare (Alt)"))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_toolbar(self) -> Gtk.Widget:
        """
        Put the match settings bar above the standard control bar.

        Called by the standard window's constructor before any people are
        loaded, so the per-window state the alternate window needs is
        set up here too.
        """
        self._settings = replace(type(self)._session_settings)
        self._finder: AltCandidateFinder | None = None
        self._ranked: dict[str, list[tuple[float, PersonHandle]]] = {}
        self._source_order: dict[str, int] = {}
        self._right_source: str | None = None
        self._right_iters: dict[str, Gtk.TreeIter] = {}

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(self._build_settings_bar(), False, False, 0)
        box.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0
        )
        box.pack_start(GWizardCompareWindow._build_toolbar(self), False, False, 0)
        return box

    def _build_settings_bar(self) -> Gtk.Widget:
        """
        Build the bar of match tolerances, with an Apply button.
        """
        settings = self._settings
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_border_width(6)
        # The settings wrap onto more lines in a narrow window instead of
        # setting the window's minimum width.
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(False)
        flow.set_max_children_per_line(10)
        flow.set_column_spacing(18)
        flow.set_row_spacing(4)
        bar.pack_start(flow, True, True, 0)

        def group(*widgets: Gtk.Widget) -> None:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            for widget in widgets:
                box.pack_start(widget, False, False, 0)
            flow.add(box)

        def spin(low: int, high: int, step: int, value: int) -> Gtk.SpinButton:
            widget = Gtk.SpinButton.new_with_range(low, high, step)
            widget.set_digits(0)
            widget.set_value(value)
            return widget

        self.spin_min_percent = spin(0, 100, 5, settings.min_percent)
        self.spin_min_percent.set_tooltip_text(
            _(
                "Lowest match score, as a percentage, for a person in the tree "
                "to be listed on the right. Name, surname and birth date each "
                "count for about a third."
            )
        )
        group(
            Gtk.Label(label=_("Minimum match:")),
            self.spin_min_percent,
            Gtk.Label(label="%"),
        )

        self.check_birth = Gtk.CheckButton(label=_("Birth years within \u00b1"))
        self.check_birth.set_active(settings.use_birth_window)
        self.check_birth.set_tooltip_text(
            _(
                "Leave out tree people born further apart than this. People "
                "with no known birth year are always considered."
            )
        )
        self.spin_birth = spin(0, 100, 1, settings.birth_window)
        self.spin_birth.set_sensitive(settings.use_birth_window)
        self.check_birth.connect(
            "toggled",
            lambda button: self.spin_birth.set_sensitive(button.get_active()),
        )
        group(self.check_birth, self.spin_birth, Gtk.Label(label=_("years")))

        self.combo_scope = Gtk.ComboBoxText()
        self.combo_scope.append(SCOPE_SURNAME, _("Similar-sounding surname"))
        self.combo_scope.append(
            SCOPE_SURNAME_INITIAL, _("Similar surname and same first initial")
        )
        self.combo_scope.append(SCOPE_ALL, _("Everyone (slow on large trees)"))
        self.combo_scope.set_active_id(settings.scope)
        self.combo_scope.set_tooltip_text(
            _(
                "Which people in the tree are considered at all. Use "
                "Everyone to find people whose surname changed, such as by "
                "marriage."
            )
        )
        group(Gtk.Label(label=_("Look in:")), self.combo_scope)

        self.spin_max_shown = spin(1, 500, 5, settings.max_shown)
        self.spin_max_shown.set_tooltip_text(
            _("Most similar people to list for one incoming person")
        )
        group(Gtk.Label(label=_("Show up to:")), self.spin_max_shown)

        self.check_one_to_one = Gtk.CheckButton(
            label=_("Pair each tree person only once")
        )
        self.check_one_to_one.set_active(settings.one_to_one)
        self.check_one_to_one.set_tooltip_text(
            _(
                "When choosing the closest match automatically, skip tree "
                "people already chosen for a closer incoming person"
            )
        )
        group(self.check_one_to_one)

        btn_apply = Gtk.Button(label=_("Apply"))
        btn_apply.set_tooltip_text(_("Match everyone again with these settings"))
        btn_apply.set_valign(Gtk.Align.START)
        btn_apply.connect("clicked", self.cb_apply_settings)
        bar.pack_end(btn_apply, False, False, 0)
        return bar

    def _read_settings(self) -> MatchSettings:
        """Return the settings currently shown in the settings bar."""
        return MatchSettings(
            min_percent=int(self.spin_min_percent.get_value()),
            use_birth_window=bool(self.check_birth.get_active()),
            birth_window=int(self.spin_birth.get_value()),
            scope=self.combo_scope.get_active_id() or SCOPE_SURNAME,
            max_shown=int(self.spin_max_shown.get_value()),
            one_to_one=bool(self.check_one_to_one.get_active()),
        )

    def _prepare_right_panel(self) -> None:
        """
        Turn the right panel into the candidate list (once).

        Its first column shows the match score instead of the Diff mark,
        and a hint above it says how to use it.
        """
        panel = self.right_panel
        if panel.get("alt_ready"):
            return
        panel["alt_ready"] = True
        panel["base_title"] = panel["frame"].get_label() or ""
        column = panel["tree"].get_column(0)
        if column is not None:
            column.set_title(_("Match"))
            column.set_min_width(60)
            column.set_max_width(110)
        hint = Gtk.Label(
            label=_(
                "Similar people in the tree, closest first. Click one to "
                "compare with it; Ctrl+click it to clear the choice. "
                "“paired”: already chosen for another incoming person."
            )
        )
        hint.set_xalign(0.0)
        hint.set_line_wrap(True)
        box = panel["frame"].get_child()
        if box is not None:
            box.pack_start(hint, False, False, 0)
            box.reorder_child(hint, 0)

    # ------------------------------------------------------------------
    # Data population
    # ------------------------------------------------------------------
    def select_category(self, category: str) -> None:
        """
        Rebuild the panels (see GWizardCompareWindow.select_category).

        The stores are emptied here first, with selection handling held
        off: emptying the right list deselects its row, which would
        otherwise read as the user clearing the match.
        """
        self._right_source = None
        self._right_iters = {}
        self._syncing = True
        try:
            self.left_panel["store"].clear()
            self.right_panel["store"].clear()
        finally:
            self._syncing = False
        GWizardCompareWindow.select_category(self, category)

    def _populate_people(
        self, left_store: Gtk.TreeStore, right_store: Gtk.TreeStore
    ) -> None:
        """
        Fill the left panel with every incoming person, match them against
        the tree with the current settings, and compute the difference
        list. The right panel is filled per selected person.
        """
        self._prepare_right_panel()
        target_db = self.dbstate.db
        source_db = self.source_db
        matcher = CandidateMatcher(target_db)
        self._source_profiles: dict[str, Any] = {}
        self._source_order = {}
        self._ranked = {}
        self._right_source = None
        self._right_iters = {}
        right_store._gwizard_row_iters = {}

        progress = _Progress(
            str(_("Loading people")),
            source_db.get_number_of_people(),
            self._progress_parent,
        )
        try:
            group_cache: dict[str, Gtk.TreeIter] = {}
            row_iters: dict[str, Gtk.TreeIter] = {}
            for handle in source_db.iter_person_handles():
                progress.step()
                person = safe_get_person(source_db, handle)
                if not person:
                    continue
                name_str = name_displayer.display(person)
                row_iters[handle] = self._add_person_row(
                    left_store, source_db, person, name_str, group_cache
                )
                self.source_index[handle] = name_str
                self._source_order[handle] = len(self._source_order)
            left_store._gwizard_row_iters = row_iters
        finally:
            progress.close()
        left_store.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        self.left_panel["tree"].expand_all()

        progress = _Progress(
            str(_("Matching people")),
            target_db.get_number_of_people() + source_db.get_number_of_people(),
            self._progress_parent,
        )
        try:
            self._build_target_index(matcher, progress)
            self._match_people(matcher, progress)
        finally:
            progress.close()
        self._compare_people(left_store, right_store)

    def _build_target_index(
        self, matcher: CandidateMatcher, progress: _Progress | None = None
    ) -> None:
        """
        Index the tree's people for candidate lookups.
        """
        finder = AltCandidateFinder(matcher, self._settings)
        db = self.dbstate.db
        for handle in db.iter_person_handles():
            if progress is not None:
                progress.step()
            person = safe_get_person(db, handle)
            if person:
                finder.add_target(PersonHandle(handle), person, db)
        self._finder = finder
        # The standard window's names for the same indexes.
        self._target_index = finder.by_key
        self._target_profiles = finder.profiles
        self._matcher = matcher

    def _rank_for(self, person: Person) -> list[tuple[float, PersonHandle]]:
        """
        Return the ranked candidates of an incoming person (cached).
        """
        ranked = self._ranked.get(person.handle)
        if ranked is None:
            if self._finder is None:
                return []
            ranked = self._finder.rank(
                self._source_profile(self._matcher, person),
                match_key(person),
                self._rejected.get(person.handle, set()),
            )
            self._ranked[person.handle] = ranked
        return ranked

    def _best_match_with_score(
        self, matcher: CandidateMatcher, source: Person
    ) -> tuple[PersonHandle | None, float]:
        """
        Return the closest candidate and its score, or (None, 0.0).
        """
        ranked = self._rank_for(source)
        if not ranked:
            return None, 0.0
        score, handle = ranked[0]
        return handle, score

    def _match_people(self, matcher: CandidateMatcher, progress: _Progress) -> None:
        """
        Rank every incoming person's candidates and choose the automatic
        matches, best scores first (see pair_greedy).
        """
        source_db = self.source_db
        for handle in source_db.iter_person_handles():
            progress.step()
            person = safe_get_person(source_db, handle)
            if person:
                self._rank_for(person)
        self._pair_map, self._pair_map_rev = pair_greedy(
            self._ranked,
            source_db.iter_person_handles(),
            one_to_one=self._settings.one_to_one,
        )
        # Shared with the apply step so relatives link to the people shown
        # as paired here (see the standard window).
        self.gwizard.context["pair_map"] = self._pair_map

    def _pair_differs(self, source_handle: str, target_handle: str | None) -> bool:
        """
        Return True when the pair has something to merge (or no target).
        """
        if target_handle is None:
            return True
        try:
            rows = self.gwizard.run_step(
                "compare",
                source_person_handle=source_handle,
                target_person_handle=target_handle,
            )
        except Exception as err:  # pylint: disable=broad-except
            LOG.warning("Comparison failed for %s: %s", source_handle, err)
            return True
        return any(
            row.status != "match"
            and not (row.status == "target_only" and row.field_type in EXTRA_KINDS)
            for row in rows
        )

    def _set_diff_entry(self, source_handle: str, target_handle: str | None) -> None:
        """
        Keep the difference list (and the left Diff mark) in step with a
        changed pairing: listed, in file order, when the pair differs;
        dropped when it does not.
        """
        differs = self._pair_differs(source_handle, target_handle)
        index = next(
            (
                i
                for i, entry in enumerate(self.diff_list)
                if entry["source_handle"] == source_handle
            ),
            None,
        )
        if differs:
            if index is not None:
                self.diff_list[index]["target_handle"] = target_handle
            else:
                order = self._source_order.get(source_handle, len(self._source_order))
                index = len(self.diff_list)
                for i, entry in enumerate(self.diff_list):
                    other = self._source_order.get(entry["source_handle"], 0)
                    if other > order:
                        index = i
                        break
                self.diff_list.insert(
                    index,
                    {"source_handle": source_handle, "target_handle": target_handle},
                )
                if index <= self.diff_index:
                    self.diff_index += 1
        elif index is not None:
            del self.diff_list[index]
            if index <= self.diff_index:
                # Next then moves on to what followed the dropped entry.
                self.diff_index -= 1
        self._mark_row(self.left_panel["store"], source_handle, "*" if differs else "o")

    # ------------------------------------------------------------------
    # The right panel: similar people for the selected incoming person
    # ------------------------------------------------------------------
    def _score_text(self, score: float, target_handle: str, source_handle: str) -> str:
        """
        Return the Match column text of a candidate row.
        """
        text = "%d%%" % score_percent(score)
        owner = self._pair_map_rev.get(target_handle)
        if owner is not None and owner != source_handle:
            text = _("%s paired") % text
        return text

    def _refresh_score_texts(self) -> None:
        """Re-render the Match column after a pairing change."""
        source_handle = self._right_source
        if not source_handle:
            return
        store = self.right_panel["store"]
        scores = dict(
            (handle, score) for score, handle in self._ranked.get(source_handle, [])
        )
        for handle, row_iter in self._right_iters.items():
            if store.iter_is_valid(row_iter):
                store.set_value(
                    row_iter,
                    _MARK_COLUMN,
                    self._score_text(scores.get(handle, 0.0), handle, source_handle),
                )

    def _clear_details(self, panel: dict[str, Any]) -> None:
        """Empty a panel's detail sections."""
        for key in ("individual", "family", "children", "events"):
            panel["detail_" + key].set_markup("")
        panel["detail_texts"] = {}
        self._apply_section_visibility(panel)

    def _update_right_title(self, count: int | None) -> None:
        """Show how many similar people are listed in the right frame."""
        panel = self.right_panel
        title = panel.get("base_title") or panel["frame"].get_label() or ""
        if count is None:
            panel["frame"].set_label(title)
        elif count == 1:
            panel["frame"].set_label(_("%s — 1 similar person") % title)
        else:
            panel["frame"].set_label(
                _("%(title)s — %(count)d similar people")
                % {"title": title, "count": count}
            )

    def _show_candidates(self, source_handle: str | None) -> None:
        """
        List the similar tree people of an incoming person on the right,
        closest first, and select its current match.
        """
        panel = self.right_panel
        store = panel["store"]
        tree = panel["tree"]
        target_db = self.dbstate.db
        self._right_source = source_handle
        self._right_iters = {}
        panel["reveal_path"] = None
        person = (
            safe_get_person(self.source_db, source_handle) if source_handle else None
        )
        ranked = self._rank_for(person) if person is not None else []
        chosen = self._pair_map.get(source_handle) if source_handle else None
        if chosen and all(handle != chosen for _s, handle in ranked):
            # Picked earlier but outside the current list: keep it shown.
            profile = self._target_profiles.get(chosen)
            score = 0.0
            if profile is not None and person is not None:
                score = self._matcher.score_profiles(
                    self._source_profile(self._matcher, person), profile
                )
            ranked = [(score, chosen)] + list(ranked)
            self._ranked[source_handle] = ranked

        self._syncing = True
        try:
            tree.get_selection().unselect_all()
            store.clear()
            for score, handle in ranked:
                target = safe_get_person(target_db, handle)
                if target is None:
                    continue
                self._right_iters[handle] = store.append(
                    None,
                    [
                        handle,
                        name_displayer.display(target),
                        self._get_born_text(target, target_db),
                        self._get_died_text(target, target_db),
                        ", ".join(self._get_parent_names(target, target_db)),
                        ", ".join(self._get_spouse_names(target, target_db)),
                        target.gramps_id or "",
                        self._score_text(score, handle, source_handle),
                    ],
                )
            store._gwizard_row_iters = self._right_iters
            row_iter = self._right_iters.get(chosen) if chosen else None
            if row_iter is not None:
                path = store.get_path(row_iter)
                tree.set_cursor(path)
                tree.scroll_to_cell(path, None, False, 0, 0)
                panel["reveal_path"] = path
            elif self._right_iters:
                tree.scroll_to_point(0, 0)
        finally:
            self._syncing = False

        self._update_right_title(len(self._right_iters) if source_handle else None)
        if source_handle:
            self._set_detail_sections(self.left_panel, source_handle)
        if chosen and chosen in self._right_iters:
            self._set_detail_sections(panel, chosen)
        else:
            self._clear_details(panel)
        self._update_diff_status()

    def _choose_target(self, source_handle: str, target_handle: str | None) -> None:
        """
        Make ``target_handle`` (or nobody) the match of an incoming person.
        """
        old = self._pair_map.get(source_handle)
        if old != target_handle:
            if old and self._pair_map_rev.get(old) == source_handle:
                del self._pair_map_rev[old]
            if target_handle:
                owner = self._pair_map_rev.get(target_handle)
                if owner and owner != source_handle and self._settings.one_to_one:
                    # The tree person moves to this incoming person.
                    self._pair_map[owner] = None
                    self._set_diff_entry(owner, None)
                self._pair_map_rev[target_handle] = source_handle
            self._pair_map[source_handle] = target_handle
            self._set_diff_entry(source_handle, target_handle)
            self._refresh_score_texts()
        self._set_detail_sections(self.left_panel, source_handle)
        if target_handle:
            self._set_detail_sections(self.right_panel, target_handle)
        else:
            self._clear_details(self.right_panel)
        self._update_diff_status()

    def _get_counterpart(
        self, handle: str, from_source: bool | None = None
    ) -> str | None:
        """
        Return the person the other panel compares ``handle`` with.

        A tree person listed on the right is compared with the incoming
        person it is listed for, even when (with "Pair each tree person
        only once" off) it is also the match of another incoming person.
        """
        if (
            from_source is False
            and self._right_source
            and self._pair_map.get(self._right_source) == handle
        ):
            return self._right_source
        return GWizardCompareWindow._get_counterpart(self, handle, from_source)

    def _sync_diff_index(self, source_handle: str) -> None:
        """Point the Differences counter at the selected incoming person."""
        for index, entry in enumerate(self.diff_list):
            if entry["source_handle"] == source_handle:
                self.diff_index = index
                return

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def cb_record_selected(self, tree_selection: Gtk.TreeSelection) -> None:
        """
        Left panel: list the selected person's similar tree people.
        Right panel: compare with the picked person instead.
        """
        if self.current_category != "person":
            GWizardCompareWindow.cb_record_selected(self, tree_selection)
            return
        if self._syncing:
            return
        is_left = tree_selection.get_tree_view() is self.left_panel["tree"]
        model, tree_iter = tree_selection.get_selected()
        handle = model.get_value(tree_iter, 0) if tree_iter else None
        if is_left:
            if not tree_iter:
                return
            if not handle:
                # Surname group row.
                self._show_candidates(None)
                self._clear_details(self.left_panel)
                return
            self._sync_diff_index(handle)
            self._show_candidates(handle)
            return
        if self._right_source:
            self._choose_target(self._right_source, handle or None)

    def _highlight_diff(self) -> None:
        """
        Select the current difference's incoming person and list its
        similar tree people.
        """
        if not (0 <= self.diff_index < len(self.diff_list)):
            return
        source_handle = self.diff_list[self.diff_index]["source_handle"]
        index = self.diff_index
        self.left_panel["reveal_path"] = None
        self._select_handle(self.left_panel, source_handle)
        # Selecting the row runs cb_record_selected unless it was already
        # selected; make sure the right panel follows either way.
        if self._right_source != source_handle:
            self._show_candidates(source_handle)
        self.diff_index = index
        self._schedule_reveal()
        self._update_diff_status()

    def select_pair(self, source_handle: str, target_handle: str | None) -> bool:
        """
        Select an incoming person and, optionally, its match in the tree.
        """
        if self.current_category != "person":
            self.select_category("person")
        found = self._select_handle(self.left_panel, source_handle)
        if self._right_source != source_handle:
            self._show_candidates(source_handle)
        if target_handle and self._pair_map.get(source_handle) != target_handle:
            self._choose_target(source_handle, target_handle)
            self._show_candidates(source_handle)
        return found

    def _reject_pair(self, source_handle: str, target_handle: str) -> None:
        """
        "Not a Match": drop the tree person from this incoming person's
        list for the rest of the session and leave it unmatched, so it can
        be added as new or another candidate picked.
        """
        self._rejected.setdefault(source_handle, set()).add(target_handle)
        ranked = self._ranked.get(source_handle)
        if ranked is not None:
            self._ranked[source_handle] = [
                item for item in ranked if item[1] != target_handle
            ]
        if self._pair_map.get(source_handle) == target_handle:
            self._pair_map[source_handle] = None
        if self._pair_map_rev.get(target_handle) == source_handle:
            del self._pair_map_rev[target_handle]
        self._set_diff_entry(source_handle, None)
        self._sync_diff_index(source_handle)
        self._show_candidates(source_handle)

    def cb_apply_settings(self, _button: Gtk.Button) -> None:
        """
        Match everyone again with the settings in the bar, staying on the
        selected incoming person.
        """
        self._settings = self._read_settings()
        type(self)._session_settings = replace(self._settings)
        selected = self._right_source
        self.select_category("person")
        if selected and safe_get_person(self.source_db, selected) is not None:
            self.select_pair(selected, None)
            self._schedule_reveal()

    # The standard window keeps both panels showing the same person; here
    # the right panel follows the left one only through cb_record_selected.
    def cb_left_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        """No panel mirroring in the alternate window."""

    def cb_right_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        """No panel mirroring in the alternate window."""

    def cb_left_vscroll_changed(self, adj: Gtk.Adjustment) -> None:
        """No scroll syncing in the alternate window."""

    def cb_right_vscroll_changed(self, adj: Gtk.Adjustment) -> None:
        """No scroll syncing in the alternate window."""

    def cb_left_hscroll_changed(self, adj: Gtk.Adjustment) -> None:
        """No scroll syncing in the alternate window."""

    def cb_right_hscroll_changed(self, adj: Gtk.Adjustment) -> None:
        """No scroll syncing in the alternate window."""
