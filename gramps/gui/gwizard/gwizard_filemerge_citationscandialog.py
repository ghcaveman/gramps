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
The GWizard Multi-Archive Citation Scan window: every citation in the Family
Tree, the work it needs (worst first), the person it is about, and for each
installed record source (NARA, WikiTree, ...) the confidence of the best
record found that could improve it.

The engine (checks, work score, confidence) is in
gramps/gen/gwizard/gwizard_filemerge_citationscan.py;
the record searches are the Multi-Archive Record Scan's
(gwizard_filemerge_recordscan), sharing its saved results.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import csv
import functools
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
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    DEFAULT_THRESHOLD,
    STATUS_ERROR,
    STATUS_SKIPPED,
    PersonScan,
    RecordScanner,
    RecordSource,
    ScanCache,
    ScanItem,
    build_scan_items,
    default_cache_path,
    discover_sources,
)
from gramps.gen.utils.string import conf_strings
from gramps.gui.gwizard.gwizard_filemerge_recordscandialog import deferred_text
from gramps.gen.gwizard.gwizard_filemerge_citationscan import (
    DEFAULT_MAX_PEOPLE,
    DEFAULT_MIN_WORK,
    CitationItem,
    CitationMatch,
    CitationSource,
    build_citation_items,
    discover_citation_sources,
    match_citation,
    people_to_search,
    read_citation,
    work_band,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

TITLE = "GWizard Multi-Archive Citation Scan"

# Fixed model columns.
COL_HANDLE = 0
COL_WORK = 1
COL_WORK_BG = 2
COL_ID = 3
COL_PERSON = 4
COL_SOURCE = 5
COL_PAGE = 6
COL_DATE = 7
COL_YEAR = 8
COL_CONF = 9
COL_CONF_SORT = 10
COL_MEDIA = 11
COL_ISSUES = 12
COL_PERSON_HANDLE = 13
FIXED_COLUMNS = 14

# Work score backgrounds, by work_band().
WORK_COLORS = {
    "high": "#ef9a9a",
    "medium": "#ffcc80",
    "low": "#fff59d",
    "none": "#c8e6c9",
}
# Confidence backgrounds: cited, strong, reaching the threshold.
CITED_COLOR = "#90caf9"
STRONG_SCORE = 90.0
STRONG_COLOR = "#a5d6a7"
MATCH_COLOR = "#dcedc8"
CELL_TEXT_COLOR = "#000000"

WORK_WIDTH = 55
ID_WIDTH = 70
PERSON_WIDTH = 170
SOURCE_WIDTH = 230
PAGE_WIDTH = 170
DATE_WIDTH = 85
CONF_WIDTH = 80
MEDIA_WIDTH = 50
ISSUES_WIDTH = 260
RECORD_WIDTH = 90
MATCH_WIDTH = 90
MAX_SCREEN_FRACTION = 0.92

# Response ids of the action buttons that keep the window open.
RESPONSE_EXPORT = 1
RESPONSE_EDIT = 2
RESPONSE_SEARCH = 3
RESPONSE_MERGE = 4

SCOPE_ALL = "all"
SCOPE_ACTIVE = "active"


# ------------------------------------------------------------
#
# SourceColumns
#
# ------------------------------------------------------------
@dataclass
class SourceColumns:
    """Where one record source's cells are in the model."""

    source: RecordSource
    adapter: CitationSource
    record: int  # the record(s) the citation already cites
    text: int  # the confidence cell
    sort: int
    background: int


def confidence_cell(
    item: CitationItem,
    source_id: str,
    scan: PersonScan | None,
    judged: list[CitationMatch],
    threshold: float,
) -> tuple[str, float, str | None]:
    """
    Return (text, sort value, background) for a confidence cell:

    * "cited": the citation already cites a record of this source
    * empty: the person has not been searched on this source
    * "no person", "error", "n/a": nothing could be searched
    * "–": searched, nothing worth offering
    * "0 · 55%": nothing reaches the threshold; the best confidence
    * "2 · 88%": how many reach the threshold, and the best confidence
    """
    if item.record_keys.get(source_id):
        return _("cited"), 101.0, CITED_COLOR
    if not item.person_handle:
        return _("no person"), -5.0, None
    if scan is None:
        return "", -4.0, None
    if scan.status == STATUS_ERROR:
        return _("error"), -3.0, None
    if scan.status == STATUS_SKIPPED:
        return _("n/a"), -2.0, None
    if not judged:
        return "–", -1.0, None
    best = judged[0].confidence
    count = sum(1 for match in judged if match.confidence >= threshold)
    if not count:
        return f"0 · {best:.0f}%", best, None
    colour = STRONG_COLOR if best >= STRONG_SCORE else MATCH_COLOR
    return f"{count} · {best:.0f}%", best, colour


def confidence_text(level: int) -> str:
    """Return the name of a Gramps citation confidence level."""
    try:
        return str(_(conf_strings[level]))
    except (KeyError, IndexError, TypeError):
        return str(level)


# ------------------------------------------------------------
#
# CitationScanDialog
#
# ------------------------------------------------------------
class CitationScanDialog(Gtk.Dialog):
    """
    List every citation, worst first, with the work it needs and the best
    record each record source found for its person. Not modal, so citations
    can be edited while it is open.
    """

    def __init__(
        self,
        dbstate: Any,
        uistate: Any = None,
        parent: Any = None,
        sources: list[RecordSource] | None = None,
        adapters: dict[str, CitationSource] | None = None,
        cache: ScanCache | None = None,
    ) -> None:
        """
        Build the window and list the citations with any saved results.

        :param sources: Record sources; the installed ones when None.
        :param adapters: Citation adapters by source id; the installed ones
            (or generic ones) when None.
        :param cache: Scan cache; the Family Tree's Multi-Archive Record Scan
            cache when None, so both windows share results.
        """
        super().__init__(
            title=str(_(TITLE)),
            transient_for=parent,
            modal=False,
            destroy_with_parent=True,
        )
        self.set_default_size(-1, 700)
        self.set_resizable(True)
        self.dbstate = dbstate
        self.uistate = uistate
        self.db = dbstate.db
        self.sources = list(sources) if sources is not None else discover_sources()
        self.adapters = dict(adapters or {})
        for source_id, adapter in discover_citation_sources(
            [s for s in self.sources if s.source_id not in self.adapters]
        ).items():
            self.adapters[source_id] = adapter
        self.cache = (
            cache if cache is not None else ScanCache(default_cache_path(self.db))
        )
        self.scanner = RecordScanner(self.cache)
        self.items: dict[str, CitationItem] = {}
        self.rows: dict[str, Gtk.TreeIter] = {}
        self.people: dict[str, ScanItem] = {}
        # person handle -> citation handles about that person (first person)
        self.by_person: dict[str, list[str]] = {}
        self.scans: dict[tuple[str, str], PersonScan] = {}
        self.judged: dict[tuple[str, str], list[CitationMatch]] = {}
        self.columns: list[SourceColumns] = []
        self.column_map: dict[Gtk.TreeViewColumn, SourceColumns] = {}
        self.scan_buttons: dict[str, Gtk.Button] = {}
        self.usage_labels: dict[str, Gtk.Label] = {}
        # One "show" check box per source, and that source's list columns.
        self.show_checks: dict[str, Gtk.CheckButton] = {}
        self.source_view_columns: dict[str, list[Gtk.TreeViewColumn]] = {}
        self.scanning = False
        self._signal_keys: list[Any] = []

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
        self.connect("destroy", self.cb_destroy)
        self._connect_db()

        self.load_citations()
        self.show_all()

    # -----------------------------------------------------------------
    # Building the window
    # -----------------------------------------------------------------
    def _build_options(self) -> Gtk.Widget:
        """Work, threshold, scope and filter options."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(Gtk.Label(label=_("Work at least:")), False, False, 0)
        self.work_spin = Gtk.SpinButton.new_with_range(0, 100, 5)
        self.work_spin.set_value(DEFAULT_MIN_WORK)
        self.work_spin.set_tooltip_text(
            _(
                "A scan searches only for the people of citations needing at "
                "least this much work (0 to 100). With 'Hide the rest' the list "
                "shows only those citations."
            )
        )
        self.work_spin.connect("value-changed", self.cb_filter_changed)
        box.pack_start(self.work_spin, False, False, 0)
        self.hide_check = Gtk.CheckButton(label=_("_Hide the rest"), use_underline=True)
        self.hide_check.connect("toggled", self.cb_filter_changed)
        box.pack_start(self.hide_check, False, False, 0)

        box.pack_start(Gtk.Label(label=_("Confidence threshold:")), False, False, 12)
        self.threshold_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.threshold_spin.set_value(DEFAULT_THRESHOLD)
        self.threshold_spin.set_tooltip_text(
            _(
                "A record counts as a likely improvement when its confidence is "
                "at least this much. Changing it does not search again."
            )
        )
        self.threshold_spin.connect("value-changed", self.cb_threshold_changed)
        box.pack_start(self.threshold_spin, False, False, 0)
        box.pack_start(Gtk.Label(label="%"), False, False, 0)

        box.pack_start(Gtk.Label(label=_("Citations:")), False, False, 12)
        self.scope_combo = Gtk.ComboBoxText()
        self.scope_combo.append(SCOPE_ALL, _("All citations"))
        self.scope_combo.append(SCOPE_ACTIVE, _("Active person's citations"))
        self.scope_combo.set_active_id(SCOPE_ALL)
        self.scope_combo.connect("changed", self.cb_filter_changed)
        box.pack_start(self.scope_combo, False, False, 0)

        self.found_only_check = Gtk.CheckButton(
            label=_("Only with records _found"), use_underline=True
        )
        self.found_only_check.connect("toggled", self.cb_filter_changed)
        box.pack_start(self.found_only_check, False, False, 12)
        return box

    def _build_source_bar(self) -> Gtk.Widget:
        """Scan buttons, the request limit and the reuse option."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(Gtk.Label(label=_("Record sources:")), False, False, 0)
        for source in self.sources:
            button = Gtk.Button(label=_("Scan %s") % source.title)
            ok, reason = self._available(source)
            button.set_sensitive(ok)
            button.set_tooltip_text(
                reason
                if not ok
                else _(
                    "Search %s for the people of the worst citations, from the "
                    "top of the list down."
                )
                % source.title
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
        if not self.sources:
            label = Gtk.Label(
                label=_(
                    "No record source is installed; the list still shows the "
                    "work each citation needs."
                )
            )
            label.set_line_wrap(True)
            box.pack_start(label, False, False, 0)

        box.pack_start(Gtk.Label(label=_("New people per scan:")), False, False, 12)
        self.max_people_spin = Gtk.SpinButton.new_with_range(0, 10000, 5)
        self.max_people_spin.set_value(DEFAULT_MAX_PEOPLE)
        self.max_people_spin.set_tooltip_text(
            _(
                "At most this many people not searched before are searched "
                "online per click (0: no limit), so one click cannot use up a "
                "site's request allowance. People with saved results are free."
            )
        )
        box.pack_start(self.max_people_spin, False, False, 0)
        self.cache_check = Gtk.CheckButton(
            label=_("_Reuse saved results"), use_underline=True
        )
        self.cache_check.set_active(True)
        self.cache_check.set_tooltip_text(
            _(
                "Use results saved by this window or the Multi-Archive Record "
                "Scan for people unchanged since. Uncheck to search again."
            )
        )
        box.pack_start(self.cache_check, False, False, 12)
        self._refresh_usage()
        return box

    def _build_show_bar(self) -> Gtk.Widget:
        """
        One check box per record source, all on: unchecking one hides its
        columns and leaves it out of Scan All, the filters, the summary, the
        record choices and the CSV. Its saved results are kept.
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

    def _build_model(self) -> None:
        """Create the list model with the source columns."""
        types: list[type] = [
            str,
            int,
            str,
            str,
            str,
            str,
            str,
            str,
            int,
            str,
            int,
            int,
            str,
            str,
        ]
        for source in self.sources:
            base = len(types)
            types.extend([str, str, float, str])
            self.columns.append(
                SourceColumns(
                    source,
                    self.adapters[source.source_id],
                    base,
                    base + 1,
                    base + 2,
                    base + 3,
                )
            )
        self.store = Gtk.ListStore(*types)
        self.filter_model = self.store.filter_new()
        self.filter_model.set_visible_func(self._row_visible)
        self.sort_model = Gtk.TreeModelSort(model=self.filter_model)
        self.sort_model.set_sort_column_id(COL_WORK, Gtk.SortType.DESCENDING)

    def _build_tree(self) -> Gtk.Widget:
        """Create the citation list."""
        self.tree_view = Gtk.TreeView(model=self.sort_model)
        self.tree_view.set_enable_search(True)
        self.tree_view.set_search_column(COL_PERSON)
        self.tree_view.set_has_tooltip(True)
        self.tree_view.connect("query-tooltip", self.cb_query_tooltip)
        self.tree_view.connect("row-activated", self.cb_row_activated)
        self.tree_view.connect("button-press-event", self.cb_button_press)
        self.tree_view.get_selection().connect("changed", self.cb_selection_changed)

        renderer = Gtk.CellRendererText()
        renderer.set_property("xalign", 0.5)
        column = Gtk.TreeViewColumn(_("Work"), renderer, text=COL_WORK)
        column.set_cell_data_func(renderer, self._cell_colour, COL_WORK_BG)
        column.set_sort_column_id(COL_WORK)
        column.set_alignment(0.5)
        self._fix_width(column, WORK_WIDTH)
        self.tree_view.append_column(column)

        for title, col, sort_col, width in (
            (_("ID"), COL_ID, COL_ID, ID_WIDTH),
            (_("Person"), COL_PERSON, COL_PERSON, PERSON_WIDTH),
            (_("Source"), COL_SOURCE, COL_SOURCE, SOURCE_WIDTH),
            (_("Page"), COL_PAGE, COL_PAGE, PAGE_WIDTH),
            (_("Date"), COL_DATE, COL_YEAR, DATE_WIDTH),
            (_("Citation\nconfidence"), COL_CONF, COL_CONF_SORT, CONF_WIDTH),
            (_("Images"), COL_MEDIA, COL_MEDIA, MEDIA_WIDTH),
            (_("Needs"), COL_ISSUES, COL_ISSUES, ISSUES_WIDTH),
        ):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            column = Gtk.TreeViewColumn(title, renderer, text=col)
            column.set_sort_column_id(sort_col)
            self._fix_width(column, width)
            self.tree_view.append_column(column)

        for group in self.columns:
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            column = Gtk.TreeViewColumn("", renderer, text=group.record)
            column.set_widget(self._header(group.source.title, _("Cited")))
            column.set_sort_column_id(group.record)
            self._fix_width(column, RECORD_WIDTH)
            self.tree_view.append_column(column)
            self.column_map[column] = group
            self.source_view_columns.setdefault(group.source.source_id, []).append(
                column
            )

            renderer = Gtk.CellRendererText()
            renderer.set_property("xalign", 0.5)
            column = Gtk.TreeViewColumn("", renderer, text=group.text)
            column.set_cell_data_func(renderer, self._cell_colour, group.background)
            column.set_widget(self._header(group.source.title, _("Confidence")))
            column.set_sort_column_id(group.sort)
            column.set_alignment(0.5)
            self._fix_width(column, MATCH_WIDTH)
            self.tree_view.append_column(column)
            self.column_map[column] = group
            self.source_view_columns.setdefault(group.source.source_id, []).append(
                column
            )

        filler = Gtk.TreeViewColumn("", Gtk.CellRendererText())
        filler.set_expand(True)
        self.tree_view.append_column(filler)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(320)
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

    @staticmethod
    def _max_content_width() -> int:
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
        """A two-line column header: the source over the column."""
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
        Bottom buttons, all added with add_button() so GTK places them in
        the platform's order; cb_response runs the ones that keep the window
        open.
        """
        self.add_button(_("_Close"), Gtk.ResponseType.CLOSE)
        self.btn_export = self.add_button(_("_Export CSV..."), RESPONSE_EXPORT)
        self.btn_export.set_tooltip_text(_("Save the list as a CSV file."))
        self.btn_edit = self.add_button(_("_Edit Citation..."), RESPONSE_EDIT)
        self.btn_edit.set_tooltip_text(
            _("Open the selected citation in the citation editor.")
        )
        self.btn_search = self.add_button(_("Open _Search..."), RESPONSE_SEARCH)
        self.btn_search.set_tooltip_text(
            _("Open a record source's own search window for the citation's person.")
        )
        self.btn_merge = self.add_button(_("Open _Record..."), RESPONSE_MERGE)
        self.btn_merge.get_style_context().add_class("suggested-action")
        self.btn_merge.set_tooltip_text(
            _(
                "Open a record found for the citation's person (or the record "
                "the citation already cites) in the record source's merge "
                "window. Double-click a confidence to do the same."
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

    def _refresh_usage(self) -> None:
        """Show each source's request allowance used."""
        for source in self.sources:
            label = self.usage_labels.get(source.source_id)
            if label is None:
                continue
            try:
                text = source.usage_text()
            except Exception:
                text = ""
            label.set_text(f"({text})" if text else "")

    def threshold(self) -> float:
        """Return the confidence threshold."""
        return float(self.threshold_spin.get_value())

    def min_work(self) -> int:
        """Return the work a citation needs to be searched for."""
        return int(self.work_spin.get_value())

    def _active_person(self) -> str | None:
        """Return the active person's handle, if any."""
        if self.uistate is None:
            return None
        try:
            return self.uistate.get_active("Person")
        except Exception:
            return None

    def _in_scope(self, item: CitationItem) -> bool:
        """Whether a citation is in the chosen scope."""
        if (self.scope_combo.get_active_id() or SCOPE_ALL) == SCOPE_ACTIVE:
            active = self._active_person()
            return bool(active) and any(h == active for h, _n in item.people)
        return True

    def _row_visible(
        self, model: Gtk.TreeModel, tree_iter: Gtk.TreeIter, _data: Any
    ) -> bool:
        """Apply the work, scope and "only with records found" filters."""
        item = self.items.get(model.get_value(tree_iter, COL_HANDLE))
        if item is None:
            return True
        if self.hide_check.get_active() and item.work < self.min_work():
            return False
        if not self._in_scope(item):
            return False
        if self.found_only_check.get_active():
            return any(
                self.judged.get((g.source.source_id, item.handle))
                or item.record_keys.get(g.source.source_id)
                for g in self.shown_groups()
            )
        return True

    def _selected(self) -> tuple[str | None, Gtk.TreeViewColumn | None]:
        """Return the selected citation's handle and the focused column."""
        model, tree_iter = self.tree_view.get_selection().get_selected()
        if tree_iter is None:
            return None, None
        _path, column = self.tree_view.get_cursor()
        return model.get_value(tree_iter, COL_HANDLE), column

    def _openable(self, item: CitationItem) -> list[SourceColumns]:
        """Return the source groups with a record to open for a citation."""
        return [
            g
            for g in self.shown_groups()
            if item.record_keys.get(g.source.source_id)
            or self.judged.get((g.source.source_id, item.handle))
        ]

    def _update_buttons(self) -> None:
        """Enable the action buttons for the selection."""
        handle, _column = self._selected()
        item = self.items.get(handle) if handle else None
        busy = self.scanning
        self.btn_edit.set_sensitive(item is not None and self.uistate is not None)
        self.btn_merge.set_sensitive(
            item is not None and not busy and bool(self._openable(item))
        )
        searchable = [
            s
            for s in self.shown_sources()
            if type(s).open_search is not RecordSource.open_search
        ]
        self.btn_search.set_sensitive(
            item is not None
            and bool(item.person_handle)
            and not busy
            and bool(searchable)
        )
        for source in self.sources:
            button = self.scan_buttons.get(source.source_id)
            if button is not None:
                button.set_sensitive(
                    not busy and self.shown(source) and self._available(source)[0]
                )
        if "" in self.scan_buttons:
            self.scan_buttons[""].set_sensitive(
                not busy and any(self._available(s)[0] for s in self.shown_sources())
            )

    # -----------------------------------------------------------------
    # Filling the list
    # -----------------------------------------------------------------
    def load_citations(self) -> None:
        """Read every citation and show any saved search results."""
        self.store.clear()
        self.rows.clear()
        items = build_citation_items(self.db, adapters=self.adapters)
        self.items = {item.handle: item for item in items}
        self.by_person = {}
        for item in items:
            if item.person_handle:
                self.by_person.setdefault(item.person_handle, []).append(item.handle)
        self.people = {
            person.handle: person
            for person in build_scan_items(
                self.db, list(self.by_person), sources=self.sources
            )
        }
        for item in items:
            self.rows[item.handle] = self.store.append(self._row_values(item))
        for person in self.people.values():
            for group in self.columns:
                scan = self.scanner.cached(group.source, person)
                if scan is not None:
                    self.scans[(group.source.source_id, person.handle)] = scan
        for item in items:
            self._judge(item)
            self._refresh_row(item.handle)
        self.filter_model.refilter()
        self._refresh_summary()
        self.status_label.set_text(
            _(
                "%d citations, worst first. Click a Scan button to look for "
                "records for the people of the worst ones; double-click a "
                "citation to edit it, or a confidence to open the record."
            )
            % len(items)
        )

    def _row_values(self, item: CitationItem) -> list[Any]:
        """Return the fixed and (empty) source cells of a row."""
        row: list[Any] = [
            item.handle,
            item.work,
            WORK_COLORS[work_band(item.work)],
            item.gramps_id,
            item.person_text(),
            item.source_title,
            item.page,
            item.date_text,
            item.year or 0,
            confidence_text(item.confidence),
            item.confidence,
            item.media_count,
            item.issue_summary(),
            item.person_handle,
        ]
        for _group in self.columns:
            row.extend(["", "", -4.0, None])
        return row

    def _judge(self, item: CitationItem) -> None:
        """Judge the records found for a citation's person, per source."""
        person = self.people.get(item.person_handle)
        for group in self.columns:
            sid = group.source.source_id
            scan = self.scans.get((sid, item.person_handle))
            if scan is None or person is None:
                self.judged.pop((sid, item.handle), None)
                continue
            self.judged[(sid, item.handle)] = match_citation(
                item, scan, person.query, group.adapter, person.cited.get(sid, [])
            )

    def _refresh_row(self, handle: str) -> None:
        """Redraw a citation's source cells for the current threshold."""
        tree_iter = self.rows.get(handle)
        item = self.items.get(handle)
        if tree_iter is None or item is None:
            return
        threshold = self.threshold()
        for group in self.columns:
            sid = group.source.source_id
            scan = self.scans.get((sid, item.person_handle))
            judged = self.judged.get((sid, item.handle), [])
            text, sort, colour = confidence_cell(item, sid, scan, judged, threshold)
            self.store.set(
                tree_iter,
                [group.record, group.text, group.sort, group.background],
                [", ".join(item.record_keys.get(sid, [])), text, sort, colour],
            )

    def _refresh_all(self) -> None:
        """Redraw every row and the summary."""
        for handle in self.rows:
            self._refresh_row(handle)
        self.filter_model.refilter()
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        """Count citations by work band, and per source what was found."""
        bands = {"high": 0, "medium": 0, "low": 0, "none": 0}
        for item in self.items.values():
            bands[work_band(item.work)] += 1
        lines = [
            _(
                "Work needed: %(high)d high (60+), %(medium)d medium (35-59), "
                "%(low)d low (15-34), %(none)d little or none."
            )
            % bands
        ]
        threshold = self.threshold()
        for group in self.shown_groups():
            sid = group.source.source_id
            searched = sum(1 for h in self.people if (sid, h) in self.scans)
            likely = sum(
                1
                for (s, _h), judged in self.judged.items()
                if s == sid and any(m.confidence >= threshold for m in judged)
            )
            cited = sum(1 for item in self.items.values() if item.record_keys.get(sid))
            lines.append(
                _(
                    "%(source)s: %(searched)d of %(people)d people searched · "
                    "%(likely)d citations with a likely record (≥%(t)d%%) · "
                    "%(cited)d citations already cite a record"
                )
                % {
                    "source": group.source.title,
                    "searched": searched,
                    "people": len(self.people),
                    "likely": likely,
                    "t": int(threshold),
                    "cited": cited,
                }
            )
        self.summary_label.set_text("\n".join(lines))

    def refresh_citation(self, handle: str) -> None:
        """Read one citation again (after an edit) and redraw its row."""
        item = read_citation(self.db, handle, self.adapters)
        tree_iter = self.rows.get(handle)
        if item is None:
            if tree_iter is not None:
                self.store.remove(tree_iter)
                self.rows.pop(handle, None)
            self.items.pop(handle, None)
            self._refresh_summary()
            return
        self.items[handle] = item
        if item.person_handle and item.person_handle not in self.people:
            for person in build_scan_items(
                self.db, [item.person_handle], sources=self.sources
            ):
                self.people[person.handle] = person
        if item.person_handle:
            listed = self.by_person.setdefault(item.person_handle, [])
            if handle not in listed:
                listed.append(handle)
        if tree_iter is None:
            self.rows[handle] = self.store.append(self._row_values(item))
        else:
            self.store.set(
                tree_iter,
                list(range(FIXED_COLUMNS)),
                self._row_values(item)[:FIXED_COLUMNS],
            )
        self._judge(item)
        self._refresh_row(handle)
        self.filter_model.refilter()
        self._refresh_summary()

    def refresh_person(self, person_handle: str) -> None:
        """
        Read a person and their citations again (after a merge, which may
        add citations) and redraw them.
        """
        for person in build_scan_items(self.db, [person_handle], sources=self.sources):
            self.people[person.handle] = person
        known = set(self.items)
        handles = set(self.by_person.get(person_handle, []))
        try:
            for citation_handle in self.db.iter_citation_handles():
                if citation_handle not in known:
                    handles.add(citation_handle)
        except Exception:
            LOG.warning("Could not look for new citations", exc_info=True)
        for handle in handles:
            self.refresh_citation(handle)

    # -----------------------------------------------------------------
    # Watching the database
    # -----------------------------------------------------------------
    def _connect_db(self) -> None:
        """Redraw citations edited or added while the window is open."""
        connect = getattr(self.db, "connect", None)
        if connect is None:
            return
        for signal in ("citation-update", "citation-add"):
            try:
                self._signal_keys.append(connect(signal, self.cb_citations_changed))
            except Exception:
                LOG.debug("Could not watch %s", signal, exc_info=True)
        try:
            self._signal_keys.append(connect("citation-delete", self.cb_citations_gone))
        except Exception:
            LOG.debug("Could not watch citation-delete", exc_info=True)

    def cb_citations_changed(self, handles: list[str]) -> None:
        """Redraw citations the database says changed."""
        for handle in handles:
            self.refresh_citation(handle)

    def cb_citations_gone(self, handles: list[str]) -> None:
        """Drop deleted citations from the list."""
        for handle in handles:
            tree_iter = self.rows.pop(handle, None)
            if tree_iter is not None:
                self.store.remove(tree_iter)
            self.items.pop(handle, None)
        self._refresh_summary()

    def cb_destroy(self, _widget: Gtk.Widget) -> None:
        """Stop watching the database and save the cache."""
        disconnect = getattr(self.db, "disconnect", None)
        for key in self._signal_keys:
            try:
                if disconnect is not None:
                    disconnect(key)
            except Exception:
                pass
        self._signal_keys = []
        self.cache.save()

    # -----------------------------------------------------------------
    # Scanning
    # -----------------------------------------------------------------
    def scan_plan(self, sources: list[RecordSource]) -> tuple[list[ScanItem], int]:
        """
        Return the people to search for (worst citations first) and how many
        were left out by the "new people per scan" limit.
        """
        use_cache = self.cache_check.get_active()

        def is_cached(handle: str) -> bool:
            person = self.people.get(handle)
            return (
                use_cache
                and person is not None
                and all(self.scanner.cached(s, person) is not None for s in sources)
            )

        items = [i for i in self.items.values() if self._in_scope(i)]
        handles, skipped = people_to_search(
            items, self.min_work(), int(self.max_people_spin.get_value()), is_cached
        )
        return [self.people[h] for h in handles if h in self.people], skipped

    def cb_scan(self, _button: Gtk.Button, sources: list[RecordSource] | None) -> None:
        """Scan one source (or all available) for the worst citations."""
        if self.scanning:
            return
        chosen = [s for s in (sources or self.shown_sources()) if self._available(s)[0]]
        people, skipped = self.scan_plan(chosen)
        if not chosen or not people:
            self.status_label.set_text(
                _("No citation with a person needs that much work.")
            )
            return
        self.run_scan(chosen, people, self.cache_check.get_active(), skipped=skipped)

    def run_scan(
        self,
        sources: list[RecordSource],
        people: list[ScanItem],
        use_cache: bool,
        meter_factory: Callable[..., Any] | None = None,
        skipped: int = 0,
    ) -> int:
        """
        Search the sources for people with a progress window, in a worker
        thread; rows update as results arrive. Return how many
        (person, source) pairs were done.
        """
        if meter_factory is None:
            from gramps.gui.utils import ProgressMeter

            meter_factory = ProgressMeter
        titles = ", ".join(s.title for s in sources)
        meter = meter_factory(_(TITLE), can_cancel=True, parent=self)
        total = len(people) * len(sources)
        meter.set_pass(_("Searching %s...") % titles, total)
        results: queue.Queue[tuple[ScanItem, PersonScan, bool]] = queue.Queue()
        cancel = threading.Event()
        finished = threading.Event()

        def cb_result(person: ScanItem, scan: PersonScan, cached: bool) -> None:
            results.put((person, scan, cached))

        def work() -> None:
            try:
                self.scanner.run(sources, people, cb_result, use_cache, cancel)
            except Exception:
                LOG.exception("Multi-Archive Citation Scan failed")
            finally:
                finished.set()

        self.scanning = True
        self._update_buttons()
        worker = threading.Thread(target=work, name="gwizard-cite-scan", daemon=True)
        worker.start()
        done = searched = errors = 0
        try:
            while True:
                try:
                    person, scan, cached = results.get(timeout=0.05)
                except queue.Empty:
                    if finished.is_set() and results.empty():
                        break
                    while Gtk.events_pending():
                        Gtk.main_iteration_do(False)
                    if meter.get_cancelled():
                        cancel.set()
                    continue
                self.store_scan(person, scan)
                done += 1
                searched += 0 if cached else 1
                errors += 1 if scan.status == STATUS_ERROR else 0
                meter.set_header(person.display_name())
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
            "Checked %(done)d of %(total)d (person, source) pairs: %(new)d "
            "searched online, %(saved)d from saved results."
        ) % {"done": done, "total": total, "new": searched, "saved": done - searched}
        if skipped:
            message += (
                " "
                + _(
                    "%d more people were left for the next scan (new people per "
                    "scan limit)."
                )
                % skipped
            )
        if errors:
            message += " " + _("%d searches failed; scan again to retry them.") % errors
        deferred = sum(self.scanner.deferred.values())
        if deferred:
            message += " " + deferred_text(self.scanner, sources)
        if done + deferred < total:
            message += " " + _("The scan was cancelled.")
        self.status_label.set_text(message)
        return done

    def store_scan(self, person: ScanItem, scan: PersonScan) -> None:
        """Remember a person's results and redraw that person's citations."""
        self.scans[(scan.source_id, person.handle)] = scan
        for handle in self.by_person.get(person.handle, []):
            item = self.items.get(handle)
            if item is not None:
                self._judge(item)
                self._refresh_row(handle)

    # -----------------------------------------------------------------
    # Opening records and citations
    # -----------------------------------------------------------------
    def edit_citation(self, handle: str) -> None:
        """Open a citation in the Gramps citation editor."""
        if self.uistate is None:
            return
        citation = self.db.get_citation_from_handle(handle)
        if citation is None:
            return
        from gramps.gui.editors import EditCitation
        from gramps.gen.errors import WindowActiveError

        try:
            EditCitation(
                self.dbstate,
                self.uistate,
                [],
                citation,
                callback=lambda _obj: self.refresh_citation(handle),
            )
        except WindowActiveError:
            pass

    def offer_records(
        self,
        handle: str,
        group: SourceColumns | None,
        event: Any = None,
        widget: Gtk.Widget | None = None,
    ) -> None:
        """Open the one record for a citation, or offer a menu of them."""
        item = self.items.get(handle)
        if item is None:
            return
        groups = [group] if group is not None else self._openable(item)
        entries = self._record_entries(item, groups)
        if not entries:
            self.status_label.set_text(_("No record has been found for this citation."))
            return
        if len(entries) == 1:
            entries[0][1]()
            return
        menu = Gtk.Menu()
        for label, action in entries[:20]:
            entry = Gtk.MenuItem(label=label)
            entry.connect("activate", lambda _w, act=action: act())
            menu.append(entry)
        menu.show_all()
        self._popup(menu, event, widget)

    def _record_entries(
        self, item: CitationItem, groups: list[SourceColumns]
    ) -> list[tuple[str, Callable[[], None]]]:
        """Return (menu label, action) for each record to open."""
        entries: list[tuple[str, Callable[[], None]]] = []
        threshold = self.threshold()
        for group in groups:
            sid = group.source.source_id
            title = group.source.title
            if type(group.adapter).open_record is not CitationSource.open_record:
                for key in item.record_keys.get(sid, []):
                    entries.append(
                        (
                            _("%(source)s: open cited record %(key)s")
                            % {"source": title, "key": key},
                            functools.partial(self.open_cited, item.handle, group, key),
                        )
                    )
            judged = [m for m in self.judged.get((sid, item.handle), []) if not m.cited]
            likely = [m for m in judged if m.confidence >= threshold] or judged
            for match in likely[:10]:
                entries.append(
                    (
                        _("%(source)s merge: %(match)s")
                        % {"source": title, "match": match.label()},
                        functools.partial(self.open_merge, item.handle, group, match),
                    )
                )
        return entries

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

    def open_merge(
        self, handle: str, group: SourceColumns, match: CitationMatch
    ) -> None:
        """Open the source's merge window for a record and the person."""
        item = self.items.get(handle)
        if item is None or not item.person_handle:
            return
        source = group.source
        self.status_label.set_text(
            _("Opening %(source)s merge for %(record)s...")
            % {"source": source.title, "record": match.match.label or match.match.key}
        )
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        try:
            changed = source.open_merge(
                self.dbstate, self.uistate, item.person_handle, match.match, parent=self
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
        self._after_open(item.person_handle, changed, source.title)

    def open_cited(self, handle: str, group: SourceColumns, key: str) -> None:
        """Open a record the citation already cites (to add its images)."""
        item = self.items.get(handle)
        if item is None:
            return
        try:
            changed = group.adapter.open_record(
                self.dbstate, self.uistate, item.person_handle, key, parent=self
            )
        except NotImplementedError:
            self.status_label.set_text(
                _("%s cannot open a cited record.") % group.source.title
            )
            return
        except Exception as err:
            LOG.exception("Opening %s record %s failed", group.source.title, key)
            self.status_label.set_text(str(err))
            return
        self._refresh_usage()
        self._after_open(item.person_handle, changed, group.source.title)

    def _after_open(self, person_handle: str, changed: bool, title: str) -> None:
        """Refresh a person's citations after a merge window closed."""
        if changed and person_handle:
            self.refresh_person(person_handle)
        self.status_label.set_text(
            _("Back from the %s window.") % title
            if changed
            else _("Nothing was changed.")
        )

    def open_search(self, handle: str, source: RecordSource) -> None:
        """Open a source's own search window for a citation's person."""
        item = self.items.get(handle)
        if item is None or not item.person_handle:
            return
        try:
            changed = source.open_search(
                self.dbstate, self.uistate, item.person_handle, parent=self
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
        self._after_open(item.person_handle, changed, source.title)

    # -----------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------
    def cb_threshold_changed(self, _spin: Gtk.SpinButton) -> None:
        """Redraw the confidences for the new threshold."""
        self._refresh_all()

    def cb_filter_changed(self, _widget: Gtk.Widget) -> None:
        """Apply the list filters."""
        self.filter_model.refilter()

    def cb_selection_changed(self, _selection: Gtk.TreeSelection) -> None:
        """Update the buttons for the selected citation."""
        self._update_buttons()

    def cb_row_activated(
        self, _tree: Gtk.TreeView, path: Gtk.TreePath, column: Gtk.TreeViewColumn
    ) -> None:
        """Double-click: a source column opens a record; others edit."""
        if self.scanning:
            return
        handle = self.sort_model.get_value(self.sort_model.get_iter(path), COL_HANDLE)
        group = self.column_map.get(column)
        if group is not None:
            self.offer_records(handle, group)
        else:
            self.edit_citation(handle)

    def cb_button_press(self, tree: Gtk.TreeView, event: Gdk.EventButton) -> bool:
        """Right-click: the records and actions for that citation."""
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
        item = self.items.get(handle)
        if item is None:
            return True
        menu = Gtk.Menu()
        if self.uistate is not None:
            entry = Gtk.MenuItem(label=_("Edit citation %s") % item.gramps_id)
            entry.connect("activate", lambda _w: self.edit_citation(handle))
            menu.append(entry)
        group = self.column_map.get(column)
        groups = [group] if group is not None else self.shown_groups()
        for label, action in self._record_entries(item, groups)[:15]:
            entry = Gtk.MenuItem(label=label)
            entry.connect("activate", lambda _w, act=action: act())
            menu.append(entry)
        if item.person_handle:
            for grp in groups:
                src = grp.source
                if type(src).open_search is not RecordSource.open_search:
                    entry = Gtk.MenuItem(
                        label=_("Open %s search for %s")
                        % (src.title, item.people[0][1])
                    )
                    entry.connect(
                        "activate", lambda _w, s=src: self.open_search(handle, s)
                    )
                    menu.append(entry)
        if not menu.get_children():
            return True
        menu.show_all()
        self._popup(menu, event, None)
        return True

    def cb_edit(self, _button: Gtk.Button) -> None:
        """Edit Citation: the selected citation."""
        handle, _column = self._selected()
        if handle:
            self.edit_citation(handle)

    def cb_open_merge(self, button: Gtk.Button) -> None:
        """Open Record: the focused source column, or every source."""
        handle, column = self._selected()
        if handle:
            self.offer_records(handle, self.column_map.get(column), widget=button)

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
        group = self.column_map.get(column)
        if group is not None and group.source in searchable:
            self.open_search(handle, group.source)
            return
        if len(searchable) == 1:
            self.open_search(handle, searchable[0])
            return
        menu = Gtk.Menu()
        for src in searchable:
            entry = Gtk.MenuItem(label=_("Open %s search") % src.title)
            entry.connect("activate", lambda _w, s=src: self.open_search(handle, s))
            menu.append(entry)
        menu.show_all()
        self._popup(menu, None, button)

    def tooltip_text(self, handle: str, group: SourceColumns | None) -> str:
        """Return the tooltip for a citation's cell."""
        item = self.items.get(handle)
        if item is None:
            return ""
        if group is None:
            lines = [
                _("Work %(work)d (quality %(quality)d of 100):")
                % {"work": item.work, "quality": item.quality}
            ]
            for issue in sorted(item.issues, key=lambda i: -i.weight):
                lines.append(f"  +{issue.weight}  {issue.text}")
            if not item.issues:
                lines.append("  " + _("Nothing to improve."))
            if len(item.people) > 1:
                lines.append(
                    _("People: %s") % ", ".join(name for _h, name in item.people[:8])
                )
            return "\n".join(lines)
        sid = group.source.source_id
        title = group.source.title
        keys = item.record_keys.get(sid, [])
        lines = []
        if keys:
            lines.append(
                _("Cites %(source)s %(keys)s.")
                % {"source": title, "keys": ", ".join(keys)}
            )
        scan = self.scans.get((sid, item.person_handle))
        if not item.person_handle:
            lines.append(_("Not attached to a person, so nothing can be searched."))
        elif scan is None:
            lines.append(_("%s has not been searched for this person yet.") % title)
        elif scan.status == STATUS_ERROR:
            lines.append(_("The search failed: %s") % scan.error)
        else:
            judged = [m for m in self.judged.get((sid, item.handle), []) if not m.cited]
            if not judged:
                lines.append(_("%s found no record worth offering.") % title)
            for match in judged[:5]:
                lines.append(match.label())
        return "\n".join(lines)

    def cb_query_tooltip(
        self,
        tree: Gtk.TreeView,
        x: int,
        y: int,
        keyboard: bool,
        tooltip: Gtk.Tooltip,
    ) -> bool:
        """Show the issues, or the records found, of the cell under the pointer."""
        found, x, y, model, path, tree_iter = tree.get_tooltip_context(x, y, keyboard)
        if not found:
            return False
        hit = tree.get_path_at_pos(x, y)
        if hit is None:
            return False
        text = self.tooltip_text(
            model.get_value(tree_iter, COL_HANDLE), self.column_map.get(hit[1])
        )
        if not text:
            return False
        tooltip.set_text(text)
        tree.set_tooltip_cell(tooltip, path, hit[1], None)
        return True

    def cb_export(self, _button: Gtk.Button) -> None:
        """Save the list as CSV."""
        chooser = Gtk.FileChooserDialog(
            title=_("Export Multi-Archive Citation Scan"),
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        chooser.add_buttons(
            _("_Cancel"), Gtk.ResponseType.CANCEL, _("_Save"), Gtk.ResponseType.OK
        )
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name("citation_scan.csv")
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
            _("Saved %(count)d citations to %(path)s.") % {"count": count, "path": path}
        )

    def export_csv(self, path: str) -> int:
        """Write every citation, worst first, to a CSV file."""
        threshold = self.threshold()
        header = [
            _("Work"),
            _("ID"),
            _("Person"),
            _("Source"),
            _("Page"),
            _("Date"),
            _("Citation confidence"),
            _("Images"),
            _("Needs"),
        ]
        groups = self.shown_groups()
        for group in groups:
            title = group.source.title
            header.extend(
                [
                    f"{title} {_('Cited')}",
                    f"{title} {_('Confidence')}",
                    f"{title} {_('Best record')}",
                ]
            )
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            ordered = sorted(self.items.values(), key=CitationItem.sort_key)
            for item in ordered:
                row: list[Any] = [
                    item.work,
                    item.gramps_id,
                    item.person_text(),
                    item.source_title,
                    item.page,
                    item.date_text,
                    confidence_text(item.confidence),
                    item.media_count,
                    item.issue_summary(),
                ]
                for group in groups:
                    sid = group.source.source_id
                    scan = self.scans.get((sid, item.person_handle))
                    judged = self.judged.get((sid, item.handle), [])
                    text = confidence_cell(item, sid, scan, judged, threshold)[0]
                    best = next((m for m in judged if not m.cited), None)
                    row.extend(
                        [
                            ", ".join(item.record_keys.get(sid, [])),
                            text,
                            best.match.label or best.match.key if best else "",
                        ]
                    )
                writer.writerow(row)
        return len(ordered)

    def cb_response(self, _dialog: Gtk.Dialog, response: int) -> None:
        """Run the action buttons without closing; close on Close."""
        actions = {
            RESPONSE_EXPORT: (self.cb_export, self.btn_export),
            RESPONSE_EDIT: (self.cb_edit, self.btn_edit),
            RESPONSE_SEARCH: (self.cb_open_search, self.btn_search),
            RESPONSE_MERGE: (self.cb_open_merge, self.btn_merge),
        }
        if response in actions:
            self.stop_emission_by_name("response")
            handler, button = actions[response]
            handler(button)
            return
        if response in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
            self.destroy()


def run_gwizard_citation_scan(
    uistate: Any, dbstate: Any, parent: Any = None
) -> CitationScanDialog:
    """
    Open the Multi-Archive Citation Scan window for the open Family Tree. The
    window is not modal (citations can be edited while it is open); it
    closes itself.
    """
    if parent is None:
        parent = getattr(uistate, "window", None)
    return CitationScanDialog(dbstate, uistate, parent=parent)
