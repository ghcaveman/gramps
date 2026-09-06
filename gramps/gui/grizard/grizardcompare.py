#
# Gramps - a GTK+/GNOME based genealogy program
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
Large top-level comparison window showing the existing Gramps tree side by
side with the incoming GEDCOM tree.
"""

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
# GTK/Gnome modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk
from gi.repository import GLib

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.lib import Person
from gramps.gen.grizard.gedcom import GedGrizard
from gramps.gen.grizard.grizard import CandidateMatcher
from gramps.gen.soundex import soundex
from gramps.gen.types import PersonHandle
from gramps.gen.display.name import displayer as name_displayer
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.managedwindow import ManagedWindow
from gramps.gui.dialog import ErrorDialog

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)

_ = glocale.translation.gettext

# Category definitions: (key, title, iter method)
CATEGORIES = [
    ("person", _("People"), "iter_person_handles"),
    ("family", _("Families"), "iter_family_handles"),
    ("event", _("Events"), "iter_event_handles"),
    ("place", _("Places"), "iter_place_handles"),
    ("source", _("Sources"), "iter_source_handles"),
    ("repository", _("Repositories"), "iter_repository_handles"),
    ("media", _("Media"), "iter_media_handles"),
    ("note", _("Notes"), "iter_note_handles"),
]


# ------------------------------------------------------------
#
# GrizardCompareWindow
#
# ------------------------------------------------------------
class GrizardCompareWindow(ManagedWindow, Gtk.Window):
    """
    Side-by-side comparison of the current Gramps tree (left) against a
    loaded GEDCOM tree (right), with Previous/Next navigation between
    records that contain differences and a Merge button that opens the
    existing "Compare Differences" merge wizard.
    """

    def __init__(
        self,
        uistate: Any,
        dbstate: Any,
        grizard: GedGrizard,
        parent: Gtk.Window | None = None,
    ) -> None:
        """
        Initialize the comparison window.

        :param uistate: Active Gramps UI state manager.
        :param dbstate: Active Gramps DB state manager.
        :param grizard: A GedGrizard instance whose connect and load steps
            have already been run (source_db present in its context).
        :param parent: Parent window.
        """
        Gtk.Window.__init__(self)
        ManagedWindow.__init__(self, uistate, [], self.__class__)
        self.set_window(self, None, _("Grizard Compare"), isWindow=True)

        self.dbstate = dbstate
        self.grizard = grizard
        self.source_db = grizard.context.get("source_db")
        self.current_category = "person"
        self.diff_list: list[dict[str, Any]] = []
        self.diff_index = -1
        self.left_index: dict[str, str] = {}
        self.right_index: dict[str, str] = {}

        self.set_title(_("Grizard Compare"))
        self.set_default_size(1400, 900)
        if parent:
            self.set_transient_for(parent)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(outer)

        outer.pack_start(self._build_toolbar(), False, False, 0)

        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        main_box.set_border_width(6)
        outer.pack_start(main_box, True, True, 0)

        main_box.pack_start(self._build_sidebar(), False, False, 0)

        self.paned = Gtk.HPaned()
        main_box.pack_start(self.paned, True, True, 0)

        self.left_panel = self._build_panel(_("Current Family Tree"))
        self.right_panel = self._build_panel(_("Incoming GEDCOM Tree"))
        self.paned.pack1(self.left_panel["frame"], True, False)
        self.paned.pack2(self.right_panel["frame"], True, False)
        # Split the two panels exactly in half once the window has been
        # allocated its real size.
        self._paned_positioned = False
        self.paned.connect("size-allocate", self.cb_paned_size_allocate)

        self.select_category("person")

    # ------------------------------------------------------------------
    # Data population
    # ------------------------------------------------------------------
    def select_category(self, category: str) -> None:
        """
        Switch both panels to the given category and repopulate them.

        :param category: One of the category keys in CATEGORIES.
        """
        self.current_category = category
        self.diff_list = []
        self.diff_index = -1

        left_store = self.left_panel["store"]
        right_store = self.right_panel["store"]
        left_store.clear()
        right_store.clear()

        try:
            if category == "person":
                self._populate_people(left_store, right_store)
            else:
                self._populate_generic(category, left_store, right_store)
        except Exception as e:
            LOG.error("Failed to populate category %s: %s", category, e)
            ErrorDialog(_("Populate Failed"), str(e), parent=self)

        self._update_diff_status()
        # Note: the first difference is intentionally NOT auto-selected.
        # Selecting a row makes GTK scroll it into view as soon as the
        # widget is laid out, which would override showing the top of the
        # tree. Navigation via Next/Previous (or clicking a row) will
        # select the difference records instead.
        GLib.idle_add(self._scroll_trees_top)

    def _scroll_trees_top(self) -> bool:
        """
        Scroll both panel tree views back to the top row.

        If the tree views are not realized yet (window still being
        mapped), reschedule until they are.

        :returns: False when done, True to reschedule the idle callback.
        """
        all_realized = True
        for panel in (self.left_panel, self.right_panel):
            tree = panel["tree"]
            if not tree.get_realized():
                all_realized = False
                continue
            try:
                tree.scroll_to_point(0, 0)
            except Exception:
                LOG.debug("scroll_to_point failed", exc_info=True)
        return not all_realized

    def cb_paned_size_allocate(
        self, widget: Gtk.Widget, allocation: Any
    ) -> None:
        """
        Centre the paned divider so both panels get the same width.
        """
        if not self._paned_positioned and allocation is not None:
            self._paned_positioned = True
            self.paned.set_position(allocation.width // 2)

    def _populate_people(
        self, left_store: Gtk.TreeStore, right_store: Gtk.TreeStore
    ) -> None:
        """
        Populate both people lists as surname-grouped trees (like the
        main Gramps People view) and compute the difference list.
        """
        target_db = self.dbstate.db
        source_db = self.source_db
        matcher = CandidateMatcher(target_db)

        for handle in source_db.iter_person_handles():
            person = source_db.get_person_from_handle(handle)
            if not person:
                continue
            name_str = name_displayer.display(person)
            birth_year = self._get_birth_year(person, source_db)
            self._add_person_row(right_store, source_db, person, name_str)
            self.right_index[handle] = name_str

        for handle in target_db.iter_person_handles():
            person = target_db.get_person_from_handle(handle)
            if not person:
                continue
            name_str = name_displayer.display(person)
            birth_year = self._get_birth_year(person, target_db)
            self._add_person_row(left_store, target_db, person, name_str)
            self.left_index.setdefault(handle, name_str)

        for store, tree in (
            (left_store, self.left_panel["tree"]),
            (right_store, self.right_panel["tree"]),
        ):
            store.set_sort_column_id(1, Gtk.SortType.ASCENDING)
            tree.expand_all()

        # Build a surname index over target people so that matching is
        # near-linear instead of a full scan per source person.
        self._build_target_index(matcher)

        # Compute records with differences: matched pairs where compare
        # produces non-matching rows, plus source-only (new) people.
        for handle in source_db.iter_person_handles():
            person = source_db.get_person_from_handle(handle)
            if not person:
                continue
            target_handle = self._best_match(matcher, person)
            try:
                if target_handle is None:
                    self.diff_list.append(
                        {"source_handle": handle, "target_handle": None}
                    )
                else:
                    rows = self.grizard.run_step(
                        "compare",
                        source_person_handle=handle,
                        target_person_handle=target_handle,
                    )
                    if any(r.status != "match" for r in rows):
                        self.diff_list.append(
                            {
                                "source_handle": handle,
                                "target_handle": target_handle,
                            }
                        )
            except Exception as e:
                LOG.warning("Comparison failed for %s: %s", handle, e)

    def _build_target_index(self, matcher: CandidateMatcher) -> None:
        """
        Index target people by soundex of surname plus first initial so
        that candidate lookup avoids scanning the whole database.
        """
        self._target_index: dict[tuple[str, str], list[PersonHandle]] = {}
        for handle in self.dbstate.db.iter_person_handles():
            person = self.dbstate.db.get_person_from_handle(handle)
            if not person:
                continue
            key = self._match_key(person)
            self._target_index.setdefault(key, []).append(
                PersonHandle(handle)
            )
        self._matcher = matcher

    @staticmethod
    def _match_key(person: Person) -> tuple[str, str]:
        """
        Return the (soundex surname, first initial) lookup key of a person.
        """
        name = person.get_primary_name()
        surname = ""
        if name.surname_list:
            surname = name.surname_list[0].surname or ""
        try:
            sdx = soundex(surname)
        except Exception:
            sdx = ""
        initial = (name.first_name or " ").strip()[:1].lower()
        return (sdx, initial)

    def _best_match(
        self, matcher: CandidateMatcher, source: Person
    ) -> PersonHandle | None:
        """
        Return the handle of the best matching target person, or None.
        """
        key = self._match_key(source)
        candidate_handles = self._target_index.get(key, [])
        # Also consider a soundex-less fallback bucket keyed on initial only
        if not candidate_handles:
            candidate_handles = self._target_index.get(("", key[1]), [])
        best_handle: PersonHandle | None = None
        best_score = 0.5
        for handle in candidate_handles:
            target = self.dbstate.db.get_person_from_handle(handle)
            if not target:
                continue
            score = matcher.score_match(source, target)
            if score > best_score:
                best_score = score
                best_handle = handle
        return best_handle


    @staticmethod
    def _add_person_row(
        store: Gtk.TreeStore, db: Any, person: Person, name_str: str
    ) -> None:
        """
        Add a person row under its "Group As" surname group row, the same
        way the main Gramps People view groups people.

        :param store: The panel's TreeStore.
        :param db: Database the person belongs to.
        :param person: The person object.
        :param name_str: Display name of the person.
        """
        try:
            group = name_displayer.name_grouping_data(db, person.primary_name)
        except Exception:
            group = ""
        if not group:
            surname_list = person.get_primary_name().surname_list
            group = surname_list[0].surname if surname_list else "???"
        birth_year = GrizardCompareWindow._get_birth_year(person, db)

        # Find or create the group row (group rows carry handle '')
        group_iter = None
        for row in store:
            if row[0] == "" and row[1] == group:
                group_iter = store.get_iter(row.path)
                break
        if group_iter is None:
            group_iter = store.append(None, ["", group, ""])
        store.append(group_iter, [person.handle, name_str, birth_year])

    def _populate_generic(
        self, category: str, left_store: Gtk.TreeStore, right_store: Gtk.TreeStore
    ) -> None:
        """
        Populate both panels with generic records for the given category.
        """
        iter_methods = dict((key, method) for key, _t, method in CATEGORIES)
        method = iter_methods[category]
        for db, store in (
            (self.dbstate.db, left_store),
            (self.source_db, right_store),
        ):
            for handle in getattr(db, method)():
                obj = self._get_object(db, category, handle)
                if obj is None:
                    continue
                store.append(
                    None, [handle, self._describe_object(obj), obj.gramps_id or ""]
                )

    def show(self, *args) -> None:
        """
        Show the window and all of its child widgets.
        """
        self.show_all()
        # Once mapped, make sure both trees display their top rows rather
        # than the initially-selected difference row.
        GLib.idle_add(self._scroll_trees_top)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_toolbar(self) -> Gtk.Widget:
        """
        Build the top control bar with Previous, Next, Merge and Close.
        """
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_border_width(6)

        self.diff_label = Gtk.Label(label="")
        bar.pack_start(self.diff_label, True, True, 0)

        # pack_end adds from the right edge, so declare in reverse visual
        # order: Close (rightmost), then Merge, Next and Previous.
        btn_close = Gtk.Button(label=_("Close"))
        btn_close.connect("clicked", self.cb_close)
        bar.pack_end(btn_close, False, False, 0)

        self.btn_merge = Gtk.Button(label=_("Merge"))
        self.btn_merge.connect("clicked", self.cb_merge)
        bar.pack_end(self.btn_merge, False, False, 0)

        self.btn_next = Gtk.Button(label=_("Next"))
        self.btn_next.connect("clicked", self.cb_next)
        bar.pack_end(self.btn_next, False, False, 0)

        self.btn_prev = Gtk.Button(label=_("Previous"))
        self.btn_prev.connect("clicked", self.cb_previous)
        bar.pack_end(self.btn_prev, False, False, 0)

        return bar

    def _build_sidebar(self) -> Gtk.Widget:
        """
        Build the left-hand category sidebar.
        """
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_size_request(160, -1)

        self.category_listbox = Gtk.ListBox()
        self.category_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for key, title, _iter in CATEGORIES:
            row = Gtk.ListBoxRow()
            row.category = key
            label = Gtk.Label(label=title, xalign=0.0)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            label.set_margin_start(10)
            row.add(label)
            self.category_listbox.add(row)
        self.category_listbox.connect("row-selected", self.cb_category_selected)

        scrolled.add(self.category_listbox)
        return scrolled

    def _build_panel(self, title: str) -> dict[str, Any]:
        """
        Build one side-by-side comparison panel.

        :param title: Panel heading.
        :returns: Dict with keys 'frame', 'store', 'tree', 'detail'.
        """
        frame = Gtk.Frame(label=title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(4)
        frame.add(box)

        # Record rows: handle, summary, extra. Group rows use handle ''.
        # A TreeStore is used for all categories: flat for generic
        # categories, two-level (surname group -> person) for people.
        store = Gtk.TreeStore(str, str, str)
        tree = Gtk.TreeView(model=store)
        col_main = Gtk.TreeViewColumn(_("Record"), Gtk.CellRendererText(), text=1)
        col_main.set_resizable(True)
        col_main.set_min_width(280)
        col_extra = Gtk.TreeViewColumn(_("Detail"), Gtk.CellRendererText(), text=2)
        col_extra.set_resizable(True)
        tree.append_column(col_main)
        tree.append_column(col_extra)
        tree.get_selection().connect("changed", self.cb_record_selected)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_size_request(-1, 500)
        scrolled.add(tree)
        box.pack_start(scrolled, True, True, 0)

        detail = Gtk.Label(label="")
        detail.set_xalign(0.0)
        detail.set_line_wrap(True)
        detail.set_selectable(True)
        detail_scrolled = Gtk.ScrolledWindow()
        detail_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        detail_scrolled.set_size_request(-1, 180)
        detail_scrolled.add(detail)
        box.pack_start(detail_scrolled, False, False, 0)

        return {"frame": frame, "store": store, "tree": tree, "detail": detail}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_object(db: Any, category: str, handle: str) -> Any:
        """
        Fetch an object of the given category from the database by handle.
        """
        getters = {
            "family": "get_family_from_handle",
            "event": "get_event_from_handle",
            "place": "get_place_from_handle",
            "source": "get_source_from_handle",
            "repository": "get_repository_from_handle",
            "media": "get_media_from_handle",
            "note": "get_note_from_handle",
        }
        getter = getters.get(category)
        if getter is None:
            return None
        try:
            return getattr(db, getter)(handle)
        except Exception:
            return None

    @staticmethod
    def _describe_object(obj: Any) -> str:
        """
        Produce a short display string for any non-person primary object.
        """
        if hasattr(obj, "get_description"):
            return obj.get_description() or ""
        if hasattr(obj, "get_title"):
            return obj.get_title() or ""
        if hasattr(obj, "get_name"):
            name = obj.get_name()
            if name is None:
                return ""
            if isinstance(name, str):
                return name
            return name.get_name() if hasattr(name, "get_name") else str(name)
        return obj.__class__.__name__

    @staticmethod
    def _get_birth_year(person: Person, db: Any) -> str:
        """
        Return the birth year of the person as a string, or ''.
        """
        birth_ref = person.get_birth_ref()
        if not birth_ref:
            return ""
        try:
            event = db.get_event_from_handle(birth_ref.ref)
            if event:
                return str(event.get_date_object().get_year() or "")
        except Exception:
            pass
        return ""

    def _update_diff_status(self) -> None:
        """
        Update the diff position label and button sensitivity.
        """
        is_people = self.current_category == "person"
        has_diffs = is_people and bool(self.diff_list)
        self.btn_prev.set_sensitive(has_diffs)
        self.btn_next.set_sensitive(has_diffs)
        self.btn_merge.set_sensitive(
            is_people and self._get_selected_pair() is not None
        )
        if is_people:
            total = len(self.diff_list)
            pos = (self.diff_index + 1) if has_diffs else 0
            self.diff_label.set_text(_("Differences: %d of %d") % (pos, total))
        else:
            self.diff_label.set_text("")

    def _select_first_diff(self) -> None:
        """
        Select the first difference record when available.
        """
        if self.current_category == "person" and self.diff_list:
            self.diff_index = 0
            self._highlight_diff()

    def _highlight_diff(self) -> None:
        """
        Select the rows in both panels corresponding to the current diff.
        """
        if not (0 <= self.diff_index < len(self.diff_list)):
            return
        entry = self.diff_list[self.diff_index]
        self._select_handle(self.right_panel, entry["source_handle"])
        if entry["target_handle"]:
            self._select_handle(self.left_panel, entry["target_handle"])
        self._update_diff_status()

    def _select_handle(self, panel: dict[str, Any], handle: str) -> None:
        """
        Select the row with the given handle in a panel's tree view,
        searching depth-first through any group rows.
        """

        def visit(store: Gtk.TreeStore, parent: Gtk.TreeIter | None) -> bool:
            iter_ = store.iter_children(parent) if parent else store.get_iter_first()
            while iter_:
                if store.get_value(iter_, 0) == handle:
                    path = store.get_path(iter_)
                    panel["tree"].set_cursor(path)
                    panel["tree"].scroll_to_cell(path, None, False, 0, 0)
                    return True
                if visit(store, iter_):
                    return True
                iter_ = store.iter_next(iter_)
            return False

        visit(panel["store"], None)

    def _get_selected_pair(self) -> tuple[str, str | None] | None:
        """
        Return (source_handle, target_handle) for the current selection,
        or None if nothing valid is selected.
        """
        model, tree_iter = self.right_panel["tree"].get_selection().get_selected()
        if not tree_iter:
            return None
        source_handle = model.get_value(tree_iter, 0)
        target_handle = None
        lmodel, ltree_iter = self.left_panel["tree"].get_selection().get_selected()
        if ltree_iter:
            target_handle = lmodel.get_value(ltree_iter, 0)
        return source_handle, target_handle

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def cb_category_selected(
        self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        """
        Handle a sidebar category selection.
        """
        if row is None:
            return
        category = getattr(row, "category", None)
        if category and category != self.current_category:
            self.select_category(category)

    def cb_record_selected(self, tree_selection: Gtk.TreeSelection) -> None:
        """
        Handle a record selection change; update the detail pane and buttons.
        """
        model, tree_iter = tree_selection.get_selected()
        if not tree_iter:
            return
        handle = model.get_value(tree_iter, 0)
        if not handle:
            # Group header row (surname group); nothing to show
            return
        tree = tree_selection.get_tree_view()
        panel = (
            self.left_panel if tree is self.left_panel["tree"] else self.right_panel
        )
        panel["detail"].set_text(self._get_detail_text(handle))
        self._update_diff_status()

    def _get_detail_text(self, handle: str) -> str:
        """
        Build the detail text shown beneath the record lists.
        """
        if self.current_category != "person":
            return ""
        db = self.source_db if handle in self.right_index else self.dbstate.db
        person = db.get_person_from_handle(handle)
        if not person:
            return ""
        lines = [name_displayer.display(person)]
        gender = {
            Person.MALE: _("Male"),
            Person.FEMALE: _("Female"),
        }.get(person.get_gender(), _("Unknown"))
        lines.append(_("Gender: %s") % gender)
        for label, get_ref in (
            (_("Birth"), person.get_birth_ref),
            (_("Death"), person.get_death_ref),
        ):
            ref = get_ref()
            if ref:
                try:
                    event = db.get_event_from_handle(ref.ref)
                    if event:
                        date_str = glocale.date_displayer.display(
                            event.get_date_object()
                        )
                        place = ""
                        place_handle = event.get_place_handle()
                        if place_handle:
                            place_obj = db.get_place_from_handle(place_handle)
                            if place_obj:
                                place = ", " + place_obj.get_name().get_name()
                        lines.append(_("%s: %s%s") % (label, date_str, place))
                except Exception as e:
                    LOG.warning("Detail lookup failed: %s", e)
        return "\n".join(lines)

    def cb_previous(self, _button: Gtk.Button) -> None:
        """
        Move to the previous record that has differences.
        """
        if not self.diff_list:
            return
        if self.diff_index <= 0:
            self.diff_index = len(self.diff_list) - 1
        else:
            self.diff_index -= 1
        self._highlight_diff()

    def cb_next(self, _button: Gtk.Button) -> None:
        """
        Move to the next record that has differences.
        """
        if not self.diff_list:
            return
        self.diff_index = (self.diff_index + 1) % len(self.diff_list)
        self._highlight_diff()

    def cb_merge(self, _button: Gtk.Button) -> None:
        """
        Open the existing Compare Differences merge wizard for the
        currently selected record pair.
        """
        pair = self._get_selected_pair()
        if pair is None:
            return
        source_handle, target_handle = pair

        from .grizardassistant import GrizardAssistant

        assistant = GrizardAssistant(
            self.uistate,
            self.dbstate,
            parent=self.get_transient_for(),
        )
        assistant.show()
        assistant.open_at_compare(
            source_handle, target_handle, grizard=self.grizard
        )

    def cb_close(self, _button: Gtk.Button) -> None:
        """
        Handle window close button.
        """
        self.close()
