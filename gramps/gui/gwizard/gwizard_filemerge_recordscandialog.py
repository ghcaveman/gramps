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
The GWizard Multi-Archive Record Scan window: every person in the Family Tree, with a
group of columns for each installed record source (WikiTree, NARA, ...)
counting the likely matches at three match levels.

The engine (sources, scoring, cache) is in
gramps/gen/gwizard/gwizard_filemerge_recordscan.py.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import csv
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizard_base import (
    PARENT_TIERS,
    TIER_GMSB,
    TIER_GMSB_BOTH_PARENTS,
    TIER_GSB,
    TIER_SCORE,
    RecordQuery,
)
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    DEFAULT_THRESHOLD,
    STATUS_CITED,
    STATUS_ERROR,
    STATUS_LINKED,
    STATUS_SKIPPED,
    STOP_ALLOWANCE,
    PersonScan,
    RecordScanner,
    RecordSource,
    ScanCache,
    ScanItem,
    ScoredMatch,
    build_scan_items,
    default_cache_path,
    discover_sources,
    matches_for_tier,
    score_matches,
    source_tiers,
    split_cited,
    tier_cell,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# Fixed model columns.
COL_HANDLE = 0
COL_SURNAME = 1
COL_GIVEN = 2
COL_BIRTH = 3
COL_DEATH = 4
COL_ID = 5
COL_BIRTH_SORT = 6
FIXED_COLUMNS = 7

# Cell backgrounds: a strong match and one that reaches the threshold.
STRONG_SCORE = 95.0
STRONG_COLOR = "#a5d6a7"
MATCH_COLOR = "#dcedc8"
CELL_TEXT_COLOR = "#000000"

# Fixed column widths, so columns keep their width when results arrive and
# the window can open just wide enough for the columns it has.
NAME_WIDTH = 130
YEAR_WIDTH = 60
ID_WIDTH = 80
LINKED_WIDTH = 110
TIER_WIDTH = 90
# Most of the screen width the window opens at.
MAX_SCREEN_FRACTION = 0.9

# Response ids of the action buttons that do not close the window. All
# action buttons are added with add_button(), so GTK (and Gramps' button
# order setting) arranges them in the platform's order.
RESPONSE_EXPORT = 1
RESPONSE_SEARCH = 2
RESPONSE_MERGE = 3

# Scope choices besides the custom person filters.
SCOPE_ALL = "all"
SCOPE_ACTIVE = "active"


# ------------------------------------------------------------
#
# SourceColumns
#
# ------------------------------------------------------------
@dataclass
class SourceColumns:
    """Where one source's cells are in the model."""

    source: RecordSource
    linked: int  # model column of the Linked text
    # tier -> (text column, sort column, background column)
    tiers: dict[str, tuple[int, int, int]]


def cell_values(
    scan: PersonScan | None,
    scored: list[ScoredMatch],
    tier: str,
    threshold: float,
    cited: int = 0,
) -> tuple[str, float, str | None]:
    """
    Return (text, sort value, background colour) for a tier cell:

    * empty: not scanned yet
    * "error": the search failed
    * "–": scanned, nothing found
    * "n/a": found records, but none can be compared at this level (a middle
      name or birth year is missing on one side; the tooltip says which)
    * "0 · 61%": none reaches the threshold; the best score
    * "2 · 94%": how many reach the threshold, and the best score
    * "cited": every record found (``cited`` of them) is already cited by
      the person, or the source skipped a person who cites its records
    """
    if scan is None:
        return "", -4.0, None
    if scan.status == STATUS_ERROR:
        return _("error"), -3.0, None
    if scan.status == STATUS_SKIPPED:
        return _("n/a"), -2.0, None
    if scan.status == STATUS_CITED or (not scored and cited):
        return _("cited"), -1.2, None
    if not scored:
        return "–", -1.5, None
    cell = tier_cell(scored, tier, threshold)
    if cell.best is None:
        return _("n/a"), -1.0, None
    if not cell.count:
        return f"0 · {cell.best:.0f}%", cell.best, None
    colour = STRONG_COLOR if cell.best >= STRONG_SCORE else MATCH_COLOR
    return f"{cell.count} · {cell.best:.0f}%", cell.best, colour


def tier_gap(query: RecordQuery, scored: list[ScoredMatch], tier: str) -> str:
    """
    Explain why no record could be compared at a tier: what is missing in
    the Family Tree, or on the records found.
    """
    need_middle = tier == TIER_GMSB or tier in PARENT_TIERS
    need_birth = tier in (TIER_GMSB, TIER_GSB) or tier in PARENT_TIERS
    if not (query.given and query.surnames):
        return _("This person has no given name or surname in the tree.")
    if need_middle and not query.middle:
        return _("This person has no middle name in the tree.")
    if need_birth and not query.birth_year:
        return _("This person has no birth year in the tree.")
    cands = [s.match.candidate for s in scored]
    if need_middle and not any(c.middle for c in cands):
        return _("None of the records found has a middle name.")
    if need_birth and not any(c.birth_years for c in cands):
        return _("None of the records found has a birth year.")
    if tier in PARENT_TIERS:
        both = tier == TIER_GMSB_BOTH_PARENTS
        father, mother = query.father_first_name, query.mother_first_name
        if both and not (father and mother):
            return _("This person does not have both parents in the tree.")
        if not (father or mother):
            return _("This person has no parents in the tree.")
        if both and not any(c.father_given and c.mother_given for c in cands):
            return _("None of the records found names both parents.")
        if not any(c.father_given or c.mother_given for c in cands):
            return _("None of the records found names a parent.")
    return _("No record found has every part this level compares.")


def deferred_text(scanner: RecordScanner, sources: list[RecordSource]) -> str:
    """
    Return a note on the sources a scan stopped searching because their
    request allowance ran out (see RecordScanner.deferred), or ''.
    Shared with the Multi-Archive Citation Scan.
    """
    notes: list[str] = []
    for source in sources:
        left = scanner.deferred.get(source.source_id, 0)
        if not left:
            continue
        if scanner.stopped.get(source.source_id) == STOP_ALLOWANCE:
            notes.append(
                _(
                    "%(source)s: stopped with %(left)d people left, as this "
                    "month's query allowance is used up (or kept for the "
                    "%(source)s search window)."
                )
                % {"source": source.title, "left": left}
            )
        else:
            notes.append(
                _(
                    "%(source)s: searched %(cap)d people, the most per scan; "
                    "%(left)d more are left. Scan again to continue."
                )
                % {
                    "source": source.title,
                    "cap": scanner.searched.get(source.source_id, 0),
                    "left": left,
                }
            )
    return " ".join(notes)


def tier_title(tier: str) -> str:
    """Return the column heading for a tier."""
    return _("Match") if tier == TIER_SCORE else tier


def match_label(scored: ScoredMatch) -> str:
    """Return a menu label for a match: its label and scores."""
    parts = [f"{scored.full.score:.0f}%"]
    for tier, result in scored.tiers.items():
        if tier == TIER_SCORE:
            continue  # the same as the full score shown first
        if result is not None:
            parts.append(f"{tier} {result.score:.0f}%")
    label = scored.match.label or scored.match.key
    return f"{label}  ({', '.join(parts)})"


# ------------------------------------------------------------
#
# RecordScanDialog
#
# ------------------------------------------------------------
class RecordScanDialog(Gtk.Dialog):
    """
    List every person with a column group per record source; scan the
    sources and open a source's merge window for an interesting match.
    """

    def __init__(
        self,
        dbstate: Any,
        uistate: Any = None,
        parent: Any = None,
        sources: list[RecordSource] | None = None,
        cache: ScanCache | None = None,
    ) -> None:
        """
        Build the window and show the people, with any results saved from
        an earlier scan.

        :param sources: Record sources to offer; found from the installed
            addons when None.
        :param cache: Scan cache; the Family Tree's cache file when None.
        """
        super().__init__(
            title=str(_("GWizard Multi-Archive Record Scan")),
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        # Height only: the width follows the columns (see _build_tree).
        self.set_default_size(-1, 680)
        self.set_resizable(True)
        self.dbstate = dbstate
        self.uistate = uistate
        self.db = dbstate.db
        self.sources = list(sources) if sources is not None else discover_sources()
        self.cache = (
            cache if cache is not None else ScanCache(default_cache_path(self.db))
        )
        self.scanner = RecordScanner(self.cache)
        self.items: dict[str, ScanItem] = {}
        self.rows: dict[str, Gtk.TreeIter] = {}
        self.scans: dict[tuple[str, str], PersonScan] = {}
        self.scored: dict[tuple[str, str], list[ScoredMatch]] = {}
        # (source id, handle) -> records found that the person already cites
        self.cited_found: dict[tuple[str, str], int] = {}
        self.columns: list[SourceColumns] = []
        self.column_map: dict[Gtk.TreeViewColumn, tuple[RecordSource, str | None]] = {}
        self.scan_buttons: dict[str, Gtk.Button] = {}
        self.usage_labels: dict[str, Gtk.Label] = {}
        # One "show" check box per source, and that source's list columns.
        self.show_checks: dict[str, Gtk.CheckButton] = {}
        self.source_view_columns: dict[str, list[Gtk.TreeViewColumn]] = {}
        self.scanning = False

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_border_width(12)
        content.pack_start(self._build_options(), False, False, 0)
        content.pack_start(self._build_source_bar(), False, False, 0)
        content.pack_start(self._build_show_bar(), False, False, 0)

        self.status_label = Gtk.Label()
        self.status_label.set_xalign(0.0)
        self.status_label.set_line_wrap(True)
        content.pack_start(self.status_label, False, False, 0)

        self._build_model()
        content.pack_start(self._build_tree(), True, True, 0)

        self.summary_label = Gtk.Label()
        self.summary_label.set_xalign(0.0)
        self.summary_label.set_line_wrap(True)
        self.summary_label.set_selectable(True)
        content.pack_start(self.summary_label, False, False, 0)

        self._build_actions()
        self.connect("response", self.cb_response)

        self.load_people()
        self.show_all()

    # -----------------------------------------------------------------
    # Building the window
    # -----------------------------------------------------------------
    def _build_options(self) -> Gtk.Widget:
        """Threshold, scope, cache and filter options."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(Gtk.Label(label=_("Match threshold:")), False, False, 0)
        self.threshold_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.threshold_spin.set_value(DEFAULT_THRESHOLD)
        self.threshold_spin.set_tooltip_text(
            _(
                "A record counts as a match when it scores at least this much. "
                "Changing it does not search again."
            )
        )
        self.threshold_spin.connect("value-changed", self.cb_threshold_changed)
        box.pack_start(self.threshold_spin, False, False, 0)
        box.pack_start(Gtk.Label(label="%"), False, False, 0)

        box.pack_start(Gtk.Label(label=_("People:")), False, False, 12)
        self.scope_combo = Gtk.ComboBoxText()
        self.scope_combo.append(SCOPE_ALL, _("All people"))
        self.scope_combo.append(SCOPE_ACTIVE, _("Active person only"))
        for name in self._person_filter_names():
            self.scope_combo.append("filter:" + name, _("Filter: %s") % name)
        self.scope_combo.set_active_id(SCOPE_ALL)
        self.scope_combo.set_tooltip_text(
            _("Which people a scan searches for. The list always shows everyone.")
        )
        box.pack_start(self.scope_combo, False, False, 0)

        self.cache_check = Gtk.CheckButton(
            label=_("_Reuse saved results"), use_underline=True
        )
        self.cache_check.set_active(True)
        self.cache_check.set_tooltip_text(
            _(
                "Skip people already scanned and unchanged since. Uncheck to "
                "search everyone again."
            )
        )
        box.pack_start(self.cache_check, False, False, 12)

        self.matches_only_check = Gtk.CheckButton(
            label=_("Show only people _with matches"), use_underline=True
        )
        self.matches_only_check.connect("toggled", self.cb_matches_only_toggled)
        box.pack_start(self.matches_only_check, False, False, 0)
        return box

    def _build_source_bar(self) -> Gtk.Widget:
        """One Scan button per record source, and Scan All."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(Gtk.Label(label=_("Record sources:")), False, False, 0)
        for source in self.sources:
            button = Gtk.Button(label=_("Scan %s") % source.title)
            ok, reason = self._available(source)
            button.set_sensitive(ok)
            button.set_tooltip_text(
                reason
                if not ok
                else _("Search %s for every person in scope.") % source.title
            )
            button.connect("clicked", self.cb_scan, [source])
            self.scan_buttons[source.source_id] = button
            box.pack_start(button, False, False, 0)
            if type(source).usage_text is not RecordSource.usage_text:
                usage = Gtk.Label()
                usage.get_style_context().add_class("dim-label")
                self.usage_labels[source.source_id] = usage
                box.pack_start(usage, False, False, 0)
        if len(self.sources) > 1:
            button = Gtk.Button(label=_("Scan _All"), use_underline=True)
            button.get_style_context().add_class("suggested-action")
            button.connect("clicked", self.cb_scan, None)
            self.scan_buttons[""] = button
            box.pack_start(button, False, False, 0)
        self._refresh_usage()
        if not self.sources:
            label = Gtk.Label(
                label=_(
                    "No record source is installed. Install a GWizard record "
                    "addon such as GWizard WikiTree Merge or GWizard NARA Merge."
                )
            )
            label.set_line_wrap(True)
            box.pack_start(label, False, False, 0)
        return box

    def _build_show_bar(self) -> Gtk.Widget:
        """
        One check box per record source, all on: unchecking one hides its
        columns and leaves it out of Scan All, the filters, the summary, the
        merge choices and the CSV. Its saved results are kept.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if not self.sources:
            return box
        box.pack_start(Gtk.Label(label=_("Show:")), False, False, 0)
        for source in self.sources:
            check = Gtk.CheckButton(label=source.title)
            check.set_active(True)
            check.set_tooltip_text(
                _("Show the %s columns and include %s in Scan All.")
                % (source.title, source.title)
            )
            check.connect("toggled", self.cb_show_toggled)
            self.show_checks[source.source_id] = check
            box.pack_start(check, False, False, 0)
        return box

    def shown(self, source: RecordSource) -> bool:
        """Whether a source's check box is on."""
        check = self.show_checks.get(source.source_id)
        return check is None or check.get_active()

    def shown_groups(self) -> list[SourceColumns]:
        """Return the column groups of the sources shown."""
        return [group for group in self.columns if self.shown(group.source)]

    def shown_sources(self) -> list[RecordSource]:
        """Return the sources shown."""
        return [source for source in self.sources if self.shown(source)]

    def cb_show_toggled(self, _check: Gtk.CheckButton) -> None:
        """Show or hide a source's columns, and redo what depends on them."""
        for source in self.sources:
            for view_column in self.source_view_columns.get(source.source_id, []):
                view_column.set_visible(self.shown(source))
        self.filter_model.refilter()
        self._refresh_summary()
        self._update_buttons()

    def _refresh_usage(self) -> None:
        """Show each source's request allowance used (see usage_text)."""
        for source in self.sources:
            label = self.usage_labels.get(source.source_id)
            if label is None:
                continue
            try:
                text = source.usage_text()
            except Exception:
                LOG.warning("%s usage could not be read", source.title, exc_info=True)
                text = ""
            label.set_text(f"({text})" if text else "")

    @staticmethod
    def _cites(source: RecordSource) -> bool:
        """Whether a source reports the records a person cites."""
        return type(source).cited_keys is not RecordSource.cited_keys

    def _link_text(self, group: SourceColumns, item: ScanItem) -> str:
        """Return the Linked (or Cited) cell for a person."""
        sid = group.source.source_id
        if group.source.has_links:
            linked = item.links.get(sid, "")
            scan = self.scans.get((sid, item.handle))
            scored = self.scored.get((sid, item.handle), [])
            if scan is not None and scan.status == STATUS_LINKED and not scored:
                linked = _("%s (not found)") % linked
            return linked
        count = len(item.cited.get(sid, []))
        return _("%d cited") % count if count else ""

    def _score_scan(self, item: ScanItem, scan: PersonScan) -> None:
        """Score a scan's new matches, setting aside records already cited."""
        key = (scan.source_id, item.handle)
        new, old = split_cited(scan.matches, item.cited.get(scan.source_id, []))
        self.cited_found[key] = len(old)
        self.scored[key] = score_matches(item.query, new, self._tiers(scan.source_id))

    def _tiers(self, source_id: str) -> tuple[str, ...]:
        """Return the score columns of a source."""
        for group in self.columns:
            if group.source.source_id == source_id:
                return tuple(group.tiers)
        return ()

    def _build_model(self) -> None:
        """Create the list model with the source columns."""
        types: list[type] = [str, str, str, str, str, str, int]
        for source in self.sources:
            linked = len(types)
            types.append(str)
            tiers: dict[str, tuple[int, int, int]] = {}
            for tier in source_tiers(source):
                tiers[tier] = (len(types), len(types) + 1, len(types) + 2)
                types.extend([str, float, str])
            self.columns.append(SourceColumns(source, linked, tiers))
        self.store = Gtk.ListStore(*types)
        self.filter_model = self.store.filter_new()
        self.filter_model.set_visible_func(self._row_visible)
        self.sort_model = Gtk.TreeModelSort(model=self.filter_model)
        self.sort_model.set_sort_column_id(COL_SURNAME, Gtk.SortType.ASCENDING)

    def _build_tree(self) -> Gtk.Widget:
        """Create the people list."""
        self.tree_view = Gtk.TreeView(model=self.sort_model)
        self.tree_view.set_enable_search(True)
        self.tree_view.set_search_column(COL_SURNAME)
        self.tree_view.set_has_tooltip(True)
        self.tree_view.connect("query-tooltip", self.cb_query_tooltip)
        self.tree_view.connect("row-activated", self.cb_row_activated)
        self.tree_view.connect("button-press-event", self.cb_button_press)
        self.tree_view.get_selection().connect("changed", self.cb_selection_changed)

        for title, column, sort_column, width in (
            (_("Surname"), COL_SURNAME, COL_SURNAME, NAME_WIDTH),
            (_("Given"), COL_GIVEN, COL_GIVEN, NAME_WIDTH),
            (_("Birth"), COL_BIRTH, COL_BIRTH_SORT, YEAR_WIDTH),
            (_("Death"), COL_DEATH, COL_DEATH, YEAR_WIDTH),
            (_("ID"), COL_ID, COL_ID, ID_WIDTH),
        ):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            view_column = Gtk.TreeViewColumn(title, renderer, text=column)
            view_column.set_sort_column_id(sort_column)
            self._fix_width(view_column, width)
            self.tree_view.append_column(view_column)

        for group in self.columns:
            if group.source.has_links or self._cites(group.source):
                renderer = Gtk.CellRendererText()
                view_column = Gtk.TreeViewColumn("", renderer, text=group.linked)
                view_column.set_widget(
                    self._header(
                        group.source.title,
                        _("Linked") if group.source.has_links else _("Cited"),
                    )
                )
                view_column.set_sort_column_id(group.linked)
                self._fix_width(view_column, LINKED_WIDTH)
                self.tree_view.append_column(view_column)
                self.column_map[view_column] = (group.source, None)
                self.source_view_columns.setdefault(group.source.source_id, []).append(
                    view_column
                )
            for tier, (text_col, sort_col, bg_col) in group.tiers.items():
                renderer = Gtk.CellRendererText()
                renderer.set_property("xalign", 0.5)
                view_column = Gtk.TreeViewColumn("", renderer, text=text_col)
                view_column.set_cell_data_func(renderer, self._cell_colour, bg_col)
                view_column.set_widget(
                    self._header(group.source.title, tier_title(tier))
                )
                view_column.set_sort_column_id(sort_col)
                view_column.set_alignment(0.5)
                self._fix_width(view_column, TIER_WIDTH)
                self.tree_view.append_column(view_column)
                self.column_map[view_column] = (group.source, tier)
                self.source_view_columns.setdefault(group.source.source_id, []).append(
                    view_column
                )

        # An empty last column takes any extra width when the window is made
        # wider, so the score columns keep their size.
        filler = Gtk.TreeViewColumn("", Gtk.CellRendererText())
        filler.set_expand(True)
        self.tree_view.append_column(filler)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(320)
        # Open as wide as the columns need, up to most of the screen; wider
        # than that, the list scrolls sideways.
        scrolled.set_propagate_natural_width(True)
        scrolled.set_max_content_width(self._max_content_width())
        scrolled.add(self.tree_view)
        return scrolled

    @staticmethod
    def _fix_width(view_column: Gtk.TreeViewColumn, width: int) -> None:
        """Give a column a fixed (still user-resizable) width."""
        view_column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        view_column.set_fixed_width(width)
        view_column.set_resizable(True)

    def _max_content_width(self) -> int:
        """Return the widest the list may open at, from the screen size."""
        try:
            display = Gdk.Display.get_default()
            monitor = display.get_primary_monitor() or display.get_monitor(0)
            width = monitor.get_workarea().width
        except Exception:
            width = 1280
        return max(600, int(width * MAX_SCREEN_FRACTION) - 40)

    @staticmethod
    def _header(source_title: str, sub_title: str) -> Gtk.Widget:
        """A two-line column header: the source over the match level."""
        label = Gtk.Label()
        label.set_markup(
            "<b>%s</b>\n%s"
            % (
                GLib.markup_escape_text(source_title),
                GLib.markup_escape_text(sub_title),
            )
        )
        label.set_justify(Gtk.Justification.CENTER)
        label.show()
        return label

    @staticmethod
    def _cell_colour(
        _column: Gtk.TreeViewColumn,
        renderer: Gtk.CellRenderer,
        model: Gtk.TreeModel,
        tree_iter: Gtk.TreeIter,
        bg_col: int,
    ) -> None:
        """Dark text on a coloured cell; the theme's colours otherwise."""
        colour = model.get_value(tree_iter, bg_col)
        if colour:
            renderer.set_property("cell-background", colour)
            renderer.set_property("foreground", CELL_TEXT_COLOR)
        renderer.set_property("cell-background-set", bool(colour))
        renderer.set_property("foreground-set", bool(colour))

    def _build_actions(self) -> None:
        """
        Bottom buttons. Every one is added with add_button() and a response
        id, never packed by hand, so GTK places them in the platform's order
        (gtk-alternative-button-order); cb_response handles the ones that
        keep the window open.
        """
        self.add_button(_("_Close"), Gtk.ResponseType.CLOSE)

        self.btn_export = self.add_button(_("_Export CSV..."), RESPONSE_EXPORT)
        self.btn_export.set_tooltip_text(
            _("Save the list and its scores as a CSV file.")
        )

        self.btn_search = self.add_button(_("Open _Search..."), RESPONSE_SEARCH)
        self.btn_search.set_tooltip_text(
            _("Open the record source's own search window for the selected person.")
        )

        self.btn_merge = self.add_button(_("Open _Merge..."), RESPONSE_MERGE)
        self.btn_merge.get_style_context().add_class("suggested-action")
        self.btn_merge.set_tooltip_text(
            _(
                "Open the merge window for the selected person and a record "
                "found for them. Double-click a score to do the same."
            )
        )
        self._update_buttons()

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    @staticmethod
    def _available(source: RecordSource) -> tuple[bool, str]:
        """Return source.available(), treating an error as unavailable."""
        try:
            return source.available()
        except Exception as err:
            return False, str(err)

    @staticmethod
    def _person_filters() -> list[Any]:
        """Return the custom person filters."""
        try:
            from gramps.gen import filters

            if filters.CustomFilters is None:
                filters.reload_custom_filters()
            custom: Any = filters.CustomFilters
            return list(custom.get_filters("Person"))
        except Exception:
            LOG.warning("Could not read the custom filters", exc_info=True)
            return []

    def _person_filter_names(self) -> list[str]:
        """Return the names of the custom person filters."""
        return [f.get_name() for f in self._person_filters()]

    def threshold(self) -> float:
        """Return the match threshold."""
        return float(self.threshold_spin.get_value())

    def _scope_handles(self) -> list[str]:
        """Return the handles of the people in scope, in list order."""
        scope = self.scope_combo.get_active_id() or SCOPE_ALL
        ordered = sorted(self.items.values(), key=ScanItem.sort_key)
        if scope == SCOPE_ALL:
            return [item.handle for item in ordered]
        if scope == SCOPE_ACTIVE:
            active = None
            if self.uistate is not None:
                try:
                    active = self.uistate.get_active("Person")
                except Exception:
                    active = None
            return [active] if active in self.items else []
        name = scope.split(":", 1)[1]
        wanted = None
        for person_filter in self._person_filters():
            if person_filter.get_name() == name:
                wanted = person_filter
                break
        if wanted is None:
            return []
        chosen = set(wanted.apply(self.db, [item.handle for item in ordered]))
        return [item.handle for item in ordered if item.handle in chosen]

    def _row_visible(
        self, model: Gtk.TreeModel, tree_iter: Gtk.TreeIter, _data: Any
    ) -> bool:
        """With "only people with matches", hide rows without one."""
        if not self.matches_only_check.get_active():
            return True
        for group in self.shown_groups():
            for _text, sort_col, _bg in group.tiers.values():
                value = model.get_value(tree_iter, sort_col)
                if value is not None and value >= self.threshold():
                    return True
        return False

    def _selected(self) -> tuple[str | None, Gtk.TreeViewColumn | None]:
        """Return the selected person's handle and the focused column."""
        model, tree_iter = self.tree_view.get_selection().get_selected()
        if tree_iter is None:
            return None, None
        _path, column = self.tree_view.get_cursor()
        return model.get_value(tree_iter, COL_HANDLE), column

    def _sources_with_results(self, handle: str) -> list[RecordSource]:
        """Return the sources that found something for a person."""
        return [
            group.source
            for group in self.shown_groups()
            if self.scored.get((group.source.source_id, handle))
        ]

    def _update_buttons(self) -> None:
        """Enable Open Merge and Open Search for the selection."""
        handle, _column = self._selected()
        busy = self.scanning
        self.btn_merge.set_sensitive(
            handle is not None and not busy and bool(self._sources_with_results(handle))
        )
        searchable = [
            s
            for s in self.shown_sources()
            if type(s).open_search is not RecordSource.open_search
        ]
        self.btn_search.set_sensitive(bool(handle) and not busy and bool(searchable))
        for button in self.scan_buttons.values():
            if busy:
                button.set_sensitive(False)
        if not busy:
            for source in self.sources:
                self.scan_buttons[source.source_id].set_sensitive(
                    self.shown(source) and self._available(source)[0]
                )
            if "" in self.scan_buttons:
                self.scan_buttons[""].set_sensitive(
                    any(self._available(s)[0] for s in self.shown_sources())
                )

    # -----------------------------------------------------------------
    # Filling the list
    # -----------------------------------------------------------------
    def load_people(self) -> None:
        """Read every person and show any saved results."""
        self.store.clear()
        self.rows.clear()
        self.items = {
            item.handle: item
            for item in build_scan_items(self.db, sources=self.sources)
        }
        for item in self.items.values():
            row = [
                item.handle,
                item.surname,
                item.given,
                str(item.birth_year or ""),
                str(item.death_year or ""),
                item.gramps_id,
                item.birth_year or 0,
            ]
            for group in self.columns:
                row.append("")
                for _tier in group.tiers:
                    row.extend(["", -3.0, None])
            self.rows[item.handle] = self.store.append(row)
        for item in self.items.values():
            for group in self.columns:
                scan = self.scanner.cached(group.source, item)
                if scan is not None:
                    self._store_scan(item, scan)
                else:
                    self._show_links(group, item)
        self._refresh_summary()
        if not self.status_label.get_text():
            self.status_label.set_text(
                _(
                    "%d people. Click a Scan button to search a record source; "
                    "double-click a score to open its merge window."
                )
                % len(self.items)
            )

    def _show_links(self, group: SourceColumns, item: ScanItem) -> None:
        """Show a person's existing link even before a scan."""
        tree_iter = self.rows.get(item.handle)
        if tree_iter is not None and (
            group.source.has_links or self._cites(group.source)
        ):
            self.store.set_value(tree_iter, group.linked, self._link_text(group, item))

    def _store_scan(self, item: ScanItem, scan: PersonScan) -> None:
        """Remember a scan result and show it in the person's row."""
        key = (scan.source_id, item.handle)
        self.scans[key] = scan
        self._score_scan(item, scan)
        self._refresh_row(item.handle)

    def _refresh_row(self, handle: str) -> None:
        """Redraw a person's source cells for the current threshold."""
        tree_iter = self.rows.get(handle)
        item = self.items.get(handle)
        if tree_iter is None or item is None:
            return
        threshold = self.threshold()
        for group in self.columns:
            sid = group.source.source_id
            scan = self.scans.get((sid, handle))
            scored = self.scored.get((sid, handle), [])
            cited = self.cited_found.get((sid, handle), 0)
            self.store.set_value(tree_iter, group.linked, self._link_text(group, item))
            for tier, (text_col, sort_col, bg_col) in group.tiers.items():
                text, sort, colour = cell_values(scan, scored, tier, threshold, cited)
                self.store.set(
                    tree_iter, [text_col, sort_col, bg_col], [text, sort, colour]
                )

    def _refresh_all(self) -> None:
        """Redraw every row (after the threshold changed)."""
        for handle in self.rows:
            self._refresh_row(handle)
        self.filter_model.refilter()
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        """Show, per source, how many people have matches at each level."""
        threshold = self.threshold()
        lines = []
        for group in self.shown_groups():
            sid = group.source.source_id
            scanned = sum(1 for (s, _h) in self.scans if s == sid)
            counts = []
            for tier in group.tiers:
                people = sum(
                    1
                    for (s, _h), scored in self.scored.items()
                    if s == sid and tier_cell(scored, tier, threshold).count
                )
                counts.append(f"{people} {tier_title(tier)}")
            lines.append(
                _(
                    "%(source)s: %(scanned)d of %(total)d scanned · %(counts)s (≥%(t)d%%)"
                )
                % {
                    "source": group.source.title,
                    "scanned": scanned,
                    "total": len(self.items),
                    "counts": " · ".join(counts),
                    "t": int(threshold),
                }
            )
        self.summary_label.set_text("\n".join(lines))

    def refresh_person(self, handle: str) -> None:
        """Read a person again (after a merge) and redraw the row."""
        fresh = build_scan_items(self.db, [handle], sources=self.sources)
        tree_iter = self.rows.get(handle)
        if not fresh or tree_iter is None:
            return
        item = fresh[0]
        self.items[handle] = item
        self.store.set(
            tree_iter,
            [COL_SURNAME, COL_GIVEN, COL_BIRTH, COL_DEATH, COL_ID, COL_BIRTH_SORT],
            [
                item.surname,
                item.given,
                str(item.birth_year or ""),
                str(item.death_year or ""),
                item.gramps_id,
                item.birth_year or 0,
            ],
        )
        for group in self.columns:
            key = (group.source.source_id, handle)
            scan = self.scans.get(key)
            if scan is not None:
                self._score_scan(item, scan)
        self._refresh_row(handle)
        self._refresh_summary()

    # -----------------------------------------------------------------
    # Scanning
    # -----------------------------------------------------------------
    def cb_scan(self, _button: Gtk.Button, sources: list[RecordSource] | None) -> None:
        """Scan the people in scope on one source (or all available)."""
        if self.scanning:
            return
        chosen = [s for s in (sources or self.shown_sources()) if self._available(s)[0]]
        handles = self._scope_handles()
        if not chosen or not handles:
            self.status_label.set_text(_("Nothing to scan."))
            return
        items = [self.items[h] for h in handles]
        self.run_scan(chosen, items, self.cache_check.get_active())

    def run_scan(
        self,
        sources: list[RecordSource],
        items: list[ScanItem],
        use_cache: bool,
        meter_factory: Callable[..., Any] | None = None,
    ) -> int:
        """
        Scan people on sources with a progress window. The searches run in a
        worker thread; results are shown as they arrive. Return how many
        person/source pairs were done.
        """
        if meter_factory is None:
            from gramps.gui.utils import ProgressMeter

            meter_factory = ProgressMeter
        titles = ", ".join(s.title for s in sources)
        meter = meter_factory(
            _("GWizard Multi-Archive Record Scan"), can_cancel=True, parent=self
        )
        total = len(items) * len(sources)
        meter.set_pass(_("Searching %s...") % titles, total)
        results: queue.Queue[tuple[ScanItem, PersonScan, bool]] = queue.Queue()
        cancel = threading.Event()
        finished = threading.Event()

        def cb_result(item: ScanItem, scan: PersonScan, cached: bool) -> None:
            results.put((item, scan, cached))

        def work() -> None:
            try:
                self.scanner.run(sources, items, cb_result, use_cache, cancel)
            except Exception:
                LOG.exception("Record scan failed")
            finally:
                finished.set()

        self.scanning = True
        self._update_buttons()
        worker = threading.Thread(target=work, name="gwizard-record-scan", daemon=True)
        worker.start()
        done = searched = errors = 0
        titles_by_id = {s.source_id: s.title for s in sources}
        try:
            while True:
                try:
                    item, scan, cached = results.get(timeout=0.05)
                except queue.Empty:
                    if finished.is_set() and results.empty():
                        break
                    while Gtk.events_pending():
                        Gtk.main_iteration_do(False)
                    if meter.get_cancelled():
                        cancel.set()
                    continue
                self._store_scan(item, scan)
                done += 1
                searched += 0 if cached else 1
                errors += 1 if scan.status == STATUS_ERROR else 0
                meter.set_header(
                    "%s: %s"
                    % (titles_by_id.get(scan.source_id, ""), item.display_name())
                )
                if not cached and done % 10 == 0:
                    self._refresh_usage()
                if meter.step():
                    cancel.set()
        finally:
            cancel.set()
            worker.join(timeout=5)
            meter.close()
            self.scanning = False
            self.cache.save()
            self.filter_model.refilter()
            self._refresh_summary()
            self._refresh_usage()
            self._update_buttons()
        message = _(
            "Checked %(done)d of %(total)d (person, source) pairs: %(new)d searched "
            "online, %(saved)d from saved results."
        ) % {"done": done, "total": total, "new": searched, "saved": done - searched}
        if errors:
            message += " " + _("%d searches failed; scan again to retry them.") % errors
        deferred = sum(self.scanner.deferred.values())
        if deferred:
            message += " " + deferred_text(self.scanner, sources)
        if done + deferred < total:
            message += " " + _("The scan was cancelled.")
        self.status_label.set_text(message)
        return done

    # -----------------------------------------------------------------
    # Opening a merge
    # -----------------------------------------------------------------
    def _target(
        self, handle: str, column: Gtk.TreeViewColumn | None
    ) -> tuple[RecordSource | None, str | None]:
        """Return the source (and tier) a click or the selection points at."""
        if column in self.column_map:
            return self.column_map[column]
        with_results = self._sources_with_results(handle)
        if len(with_results) == 1:
            return with_results[0], None
        return None, None

    def offer_matches(
        self,
        handle: str,
        source: RecordSource,
        tier: str | None,
        event: Any = None,
        widget: Gtk.Widget | None = None,
    ) -> None:
        """Open the one match, or offer a menu when there are several."""
        scored = self.scored.get((source.source_id, handle), [])
        candidates = matches_for_tier(scored, tier, self.threshold())
        if not candidates:
            if self.cited_found.get((source.source_id, handle)):
                self.status_label.set_text(
                    _("Every %s record found is already cited by this person.")
                    % source.title
                )
            else:
                self.status_label.set_text(
                    _("%s found nothing for this person.") % source.title
                )
            return
        if len(candidates) == 1:
            self.open_merge(handle, source, candidates[0])
            return
        menu = self._match_menu(handle, source, candidates)
        self._popup(menu, event, widget)

    def _match_menu(
        self, handle: str, source: RecordSource, candidates: list[ScoredMatch]
    ) -> Gtk.Menu:
        """A menu with one item per match."""
        menu = Gtk.Menu()
        heading = Gtk.MenuItem(label=_("Open in %s merge:") % source.title)
        heading.set_sensitive(False)
        menu.append(heading)
        for scored in candidates[:15]:
            entry = Gtk.MenuItem(label=match_label(scored))
            entry.connect("activate", self.cb_menu_merge, handle, source, scored)
            menu.append(entry)
        menu.show_all()
        return menu

    def _popup(self, menu: Gtk.Menu, event: Any, widget: Gtk.Widget | None) -> None:
        """Show a menu at the pointer or below a widget."""
        menu.attach_to_widget(self, None)
        if event is None and widget is None:
            event = Gtk.get_current_event()
        if event is not None and event.get_window() is not None:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(
                widget or self.tree_view,
                Gdk.Gravity.NORTH_WEST,
                Gdk.Gravity.SOUTH_WEST,
                None,
            )

    def cb_menu_merge(
        self,
        _item: Gtk.MenuItem,
        handle: str,
        source: RecordSource,
        scored: ScoredMatch,
    ) -> None:
        """Open the match chosen from a menu."""
        self.open_merge(handle, source, scored)

    def open_merge(
        self, handle: str, source: RecordSource, scored: ScoredMatch
    ) -> None:
        """Open a source's merge window for a match, then refresh the row."""
        self.status_label.set_text(
            _("Opening %(source)s merge for %(record)s...")
            % {"source": source.title, "record": scored.match.label or scored.match.key}
        )
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        try:
            changed = source.open_merge(
                self.dbstate, self.uistate, handle, scored.match, parent=self
            )
        except NotImplementedError:
            self.status_label.set_text(
                _("%s cannot open a merge window from here.") % source.title
            )
            return
        except Exception as err:
            LOG.exception("Opening the %s merge failed", source.title)
            self.status_label.set_text(
                _("Could not open the %(source)s merge: %(error)s")
                % {"source": source.title, "error": err}
            )
            return
        if changed:
            self.refresh_person(handle)
        self.status_label.set_text(
            _("Back from the %s merge window.") % source.title
            if changed
            else _("Nothing was changed.")
        )

    def open_search(self, handle: str, source: RecordSource) -> None:
        """Open a source's own search window for a person."""
        try:
            changed = source.open_search(
                self.dbstate, self.uistate, handle, parent=self
            )
        except NotImplementedError:
            self.status_label.set_text(
                _("%s has no search window to open.") % source.title
            )
            return
        except Exception as err:
            LOG.exception("Opening the %s search failed", source.title)
            self.status_label.set_text(str(err))
            return
        if changed:
            self.refresh_person(handle)

    # -----------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------
    def cb_threshold_changed(self, _spin: Gtk.SpinButton) -> None:
        """Redraw the scores for the new threshold."""
        self._refresh_all()

    def cb_matches_only_toggled(self, _check: Gtk.CheckButton) -> None:
        """Show or hide rows without matches."""
        self.filter_model.refilter()

    def cb_selection_changed(self, _selection: Gtk.TreeSelection) -> None:
        """Update the buttons for the selected person."""
        self._update_buttons()

    def cb_row_activated(
        self, _tree: Gtk.TreeView, path: Gtk.TreePath, column: Gtk.TreeViewColumn
    ) -> None:
        """Double-click: open the merge for the clicked source column."""
        if self.scanning:
            return
        tree_iter = self.sort_model.get_iter(path)
        handle = self.sort_model.get_value(tree_iter, COL_HANDLE)
        source, tier = self._target(handle, column)
        if source is not None:
            self.offer_matches(handle, source, tier)

    def cb_button_press(self, tree: Gtk.TreeView, event: Gdk.EventButton) -> bool:
        """Right-click: a menu of the matches and actions for that cell."""
        if event.type != Gdk.EventType.BUTTON_PRESS or event.button != 3:
            return False
        if self.scanning:
            return True
        hit = tree.get_path_at_pos(int(event.x), int(event.y))
        if hit is None:
            return False
        path, column, _x, _y = hit
        tree.get_selection().select_path(path)
        tree.set_cursor(path, column, False)
        handle = self.sort_model.get_value(self.sort_model.get_iter(path), COL_HANDLE)
        source, tier = self._target(handle, column)
        sources = [source] if source is not None else self.shown_sources()
        menu = Gtk.Menu()
        for src in sources:
            scored = self.scored.get((src.source_id, handle), [])
            for match in matches_for_tier(scored, tier, self.threshold())[:10]:
                entry = Gtk.MenuItem(
                    label=_("%(source)s merge: %(match)s")
                    % {"source": src.title, "match": match_label(match)}
                )
                entry.connect("activate", self.cb_menu_merge, handle, src, match)
                menu.append(entry)
            if type(src).open_search is not RecordSource.open_search:
                entry = Gtk.MenuItem(
                    label=_("Open %s search for this person") % src.title
                )
                entry.connect("activate", self.cb_menu_search, handle, src)
                menu.append(entry)
            if (src.source_id, handle) in self.scans:
                entry = Gtk.MenuItem(label=_("Forget saved %s results") % src.title)
                entry.connect("activate", self.cb_menu_forget, handle, src)
                menu.append(entry)
        if not menu.get_children():
            return True
        menu.show_all()
        self._popup(menu, event, None)
        return True

    def cb_menu_search(
        self, _item: Gtk.MenuItem, handle: str, source: RecordSource
    ) -> None:
        """Open a source's search window from the menu."""
        self.open_search(handle, source)

    def cb_menu_forget(
        self, _item: Gtk.MenuItem, handle: str, source: RecordSource
    ) -> None:
        """Drop a person's saved results for a source."""
        key = (source.source_id, handle)
        self.scans.pop(key, None)
        self.scored.pop(key, None)
        self.cache.forget(source.source_id, handle)
        self.cache.save()
        self._refresh_row(handle)
        self._refresh_summary()

    def cb_open_merge(self, button: Gtk.Button) -> None:
        """Open Merge: the focused source column, or the only one with results."""
        handle, column = self._selected()
        if not handle:
            return
        source, tier = self._target(handle, column)
        if source is not None:
            self.offer_matches(handle, source, tier, widget=button)
            return
        menu = Gtk.Menu()
        for src in self._sources_with_results(handle):
            scored = self.scored.get((src.source_id, handle), [])
            for match in matches_for_tier(scored, None, self.threshold())[:10]:
                entry = Gtk.MenuItem(
                    label=_("%(source)s merge: %(match)s")
                    % {"source": src.title, "match": match_label(match)}
                )
                entry.connect("activate", self.cb_menu_merge, handle, src, match)
                menu.append(entry)
        menu.show_all()
        self._popup(menu, None, button)

    def cb_open_search(self, button: Gtk.Button) -> None:
        """Open Search: the focused source, or a choice of sources."""
        handle, column = self._selected()
        if not handle:
            return
        searchable = [
            s
            for s in self.shown_sources()
            if type(s).open_search is not RecordSource.open_search
        ]
        source = self.column_map.get(column, (None, None))[0] if column else None
        if source in searchable:
            self.open_search(handle, source)
            return
        if len(searchable) == 1:
            self.open_search(handle, searchable[0])
            return
        menu = Gtk.Menu()
        for src in searchable:
            entry = Gtk.MenuItem(label=_("Open %s search") % src.title)
            entry.connect("activate", self.cb_menu_search, handle, src)
            menu.append(entry)
        menu.show_all()
        self._popup(menu, None, button)

    def cb_query_tooltip(
        self,
        tree: Gtk.TreeView,
        x: int,
        y: int,
        keyboard: bool,
        tooltip: Gtk.Tooltip,
    ) -> bool:
        """Show the best matches of the cell under the pointer."""
        found, x, y, model, path, tree_iter = tree.get_tooltip_context(x, y, keyboard)
        if not found:
            return False
        # get_tooltip_context gave bin-window coordinates already.
        hit = tree.get_path_at_pos(x, y)
        if hit is None or hit[1] not in self.column_map:
            return False
        source, tier = self.column_map[hit[1]]
        handle = model.get_value(tree_iter, COL_HANDLE)
        scan = self.scans.get((source.source_id, handle))
        if scan is None:
            text = _("Not scanned on %s yet.") % source.title
        elif scan.status == STATUS_ERROR:
            text = _("The search failed: %s") % scan.error
        elif scan.status == STATUS_CITED:
            text = (
                _(
                    "Not searched: this person already cites %s records. "
                    "Use Open Search to look for more."
                )
                % source.title
            )
        else:
            scored = self.scored.get((source.source_id, handle), [])
            best = matches_for_tier(scored, tier, self.threshold())[:5]
            item = self.items.get(handle)
            if not scored:
                text = _("%s found nothing.") % source.title
            elif tier is not None and tier_cell(scored, tier, 0).best is None:
                gap = tier_gap(item.query, scored, tier) if item else ""
                text = _("Cannot compare at %(tier)s. %(why)s") % {
                    "tier": tier_title(tier),
                    "why": gap,
                }
            else:
                text = "\n".join(match_label(match) for match in best)
            if scan.linked_key:
                text = _("Linked to %s") % scan.linked_key + "\n" + text
            cited = self.cited_found.get((source.source_id, handle), 0)
            if cited:
                text += "\n" + _(
                    "%(count)d record(s) found are already cited by this "
                    "person and are not counted."
                ) % {"count": cited}
        tooltip.set_text(text)
        tree.set_tooltip_cell(tooltip, path, hit[1], None)
        return True

    def cb_export(self, _button: Gtk.Button) -> None:
        """Save the list as CSV."""
        chooser = Gtk.FileChooserDialog(
            title=_("Export Multi-Archive Record Scan"),
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        chooser.add_buttons(
            _("_Cancel"), Gtk.ResponseType.CANCEL, _("_Save"), Gtk.ResponseType.OK
        )
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name("record_scan.csv")
        try:
            if chooser.run() != Gtk.ResponseType.OK:
                return
            path = chooser.get_filename()
        finally:
            chooser.destroy()
        try:
            count = self.export_csv(path)
        except OSError as err:
            self.status_label.set_text(
                _("Could not save %(path)s: %(error)s") % {"path": path, "error": err}
            )
            return
        self.status_label.set_text(
            _("Saved %(count)d people to %(path)s.") % {"count": count, "path": path}
        )

    def export_csv(self, path: str) -> int:
        """Write every person and their scores to a CSV file."""
        threshold = self.threshold()
        header = [_("Surname"), _("Given"), _("Birth"), _("Death"), _("ID")]
        groups = self.shown_groups()
        for group in groups:
            title = group.source.title
            if group.source.has_links:
                header.append(f"{title} {_('Linked')}")
            elif self._cites(group.source):
                header.append(f"{title} {_('Cited')}")
            header.extend(f"{title} {tier_title(tier)}" for tier in group.tiers)
            header.extend([f"{title} {_('Best match')}", f"{title} {_('Score')}"])
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            ordered = sorted(self.items.values(), key=ScanItem.sort_key)
            for item in ordered:
                row: list[Any] = [
                    item.surname,
                    item.given,
                    item.birth_year or "",
                    item.death_year or "",
                    item.gramps_id,
                ]
                for group in groups:
                    sid = group.source.source_id
                    scan = self.scans.get((sid, item.handle))
                    scored = self.scored.get((sid, item.handle), [])
                    if group.source.has_links or self._cites(group.source):
                        row.append(self._link_text(group, item))
                    cited = self.cited_found.get((sid, item.handle), 0)
                    for tier in group.tiers:
                        row.append(cell_values(scan, scored, tier, threshold, cited)[0])
                    if scored:
                        best = scored[0]
                        row.extend(
                            [
                                best.match.label or best.match.key,
                                f"{best.full.score:.0f}",
                            ]
                        )
                    else:
                        row.extend(["", ""])
                writer.writerow(row)
        return len(self.items)

    def cb_response(self, _dialog: Gtk.Dialog, response: int) -> None:
        """
        Run the action buttons without closing the window; save the cache
        when it closes.
        """
        actions = {
            RESPONSE_EXPORT: (self.cb_export, self.btn_export),
            RESPONSE_SEARCH: (self.cb_open_search, self.btn_search),
            RESPONSE_MERGE: (self.cb_open_merge, self.btn_merge),
        }
        if response in actions:
            # Keep Gtk.Dialog.run() going: these buttons are not closing ones.
            self.stop_emission_by_name("response")
            handler, button = actions[response]
            handler(button)
            return
        if response in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
            self.cache.save()


def run_gwizard_record_scan(uistate: Any, dbstate: Any, parent: Any = None) -> bool:
    """Open the Multi-Archive Record Scan window for the open Family Tree."""
    if parent is None:
        parent = getattr(uistate, "window", None)
    dialog = RecordScanDialog(dbstate, uistate, parent=parent)
    try:
        dialog.run()
    finally:
        dialog.cache.save()
        dialog.destroy()
    return True
