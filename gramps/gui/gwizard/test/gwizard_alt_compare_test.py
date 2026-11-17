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
Tests for the alternate (Alt) GWizard compare window: the candidate list on
the right, picking another candidate, Not a Match, and the difference list.

The window's logic is run against real databases without building any
widgets: its methods are bound to a plain object whose panels hold fake
stores and mock tree views.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except (ImportError, ValueError):
    import html
    import types
    from unittest.mock import MagicMock

    class _DummyBase:
        pass

    class _DummyClass:
        FILL = 0
        START = 0
        END = 0
        CENTER = 0

        def __init__(self, *args, **kwargs):
            self._name = ""

        def __call__(self, *args, **kwargs):
            return self

        def __getattr__(self, name):
            if name == "get_default":
                return lambda: None
            return self

        def __int__(self):
            return 0

        def __mro_entries__(self, bases):
            return (type(f"_DummyBase_{id(self)}", (), {}),)

        def set_name(self, name):
            self._name = name

        def get_name(self):
            return self._name

        def add_pattern(self, pattern):
            pass

    class _GtkModule(types.ModuleType):
        def __getattr__(self, name):
            return _DummyClass()

    _gtk = _GtkModule("gi.repository.Gtk")
    _glib = MagicMock()
    _glib.MAJOR_VERSION = 2
    _glib.MINOR_VERSION = 80
    _glib.MICRO_VERSION = 0
    _glib.markup_escape_text = html.escape

    _repo = types.ModuleType("gi.repository")
    _repo.Gtk = _gtk
    _repo.GLib = _glib
    _repo.Gio = MagicMock()
    _repo.Gdk = _DummyClass()
    _repo.Pango = MagicMock()
    _repo.PangoCairo = MagicMock()
    _repo.GObject = _DummyClass()
    _repo.GdkPixbuf = MagicMock()

    _gi = types.ModuleType("gi")
    _gi.repository = _repo
    _gi.require_version = lambda *args: None

    sys.modules["gi"] = _gi
    sys.modules["gi.repository"] = _repo
    sys.modules["gi.repository.Gtk"] = _gtk
    sys.modules["gi.repository.GLib"] = _glib
    sys.modules["gi.repository.Gio"] = _repo.Gio
    sys.modules["gi.repository.Gdk"] = _repo.Gdk
    sys.modules["gi.repository.Pango"] = _repo.Pango
    sys.modules["gi.repository.PangoCairo"] = _repo.PangoCairo
    sys.modules["gi.repository.GObject"] = _repo.GObject
    sys.modules["gi.repository.GdkPixbuf"] = _repo.GdkPixbuf

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.gwizard.gwizardaltmatch import MatchSettings
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.lib import Date, Event, EventRef, EventType, Name, Person, Surname
from gramps.gui.gwizard.gwizardaltcompare import GWizardAltCompareWindow
from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow

SOURCE_GED = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME John /Smith/
1 SEX M
1 BIRT
2 DATE 1900
0 @I2@ INDI
1 NAME Johnny /Smith/
1 SEX M
1 BIRT
2 DATE 1901
0 @I3@ INDI
1 NAME Mary /Jones/
1 SEX F
1 BIRT
2 DATE 1920
0 TRLR
"""


# ------------------------------------------------------------
#
# Fakes
#
# ------------------------------------------------------------
class _Row:
    def __init__(self, parent: Any, values: list[str]) -> None:
        self.parent = parent
        self.values = list(values)
        self.children: list[_Row] = []


class FakeStore:
    """Just enough of Gtk.TreeStore for the alternate window."""

    def __init__(self) -> None:
        self.roots: list[_Row] = []
        self.live: set[int] = set()

    def append(self, parent: _Row | None, values: list[str]) -> _Row:
        row = _Row(parent, values)
        (parent.children if parent else self.roots).append(row)
        self.live.add(id(row))
        return row

    def clear(self) -> None:
        self.roots = []
        self.live = set()

    def get_path(self, row: _Row) -> tuple[int, ...]:
        siblings = row.parent.children if row.parent else self.roots
        index = siblings.index(row)
        return (self.get_path(row.parent) if row.parent else ()) + (index,)

    def iter_is_valid(self, row: _Row) -> bool:
        return id(row) in self.live

    def set_value(self, row: _Row, column: int, value: str) -> None:
        row.values[column] = value

    def get_value(self, row: _Row, column: int) -> str:
        return row.values[column]

    def get_iter_first(self) -> _Row | None:
        return self.roots[0] if self.roots else None

    def iter_children(self, row: _Row) -> _Row | None:
        return row.children[0] if row.children else None

    def iter_next(self, row: _Row) -> _Row | None:
        siblings = row.parent.children if row.parent else self.roots
        index = siblings.index(row)
        return siblings[index + 1] if index + 1 < len(siblings) else None

    def set_sort_column_id(self, column: int, order: Any) -> None:
        pass

    def rows(self) -> list[list[str]]:
        return [row.values for row in self.roots]


def _panel() -> dict[str, Any]:
    return {
        "store": FakeStore(),
        "tree": MagicMock(),
        "frame": MagicMock(get_label=MagicMock(return_value="Tree")),
        "detail_texts": {},
        "alt_ready": True,
        "base_title": "Tree",
    }


def _harness_class() -> type:
    """A plain class carrying the compare windows' methods, no widgets."""
    members: dict[str, Any] = {}
    for cls in (GWizardCompareWindow, GWizardAltCompareWindow):
        for key, value in vars(cls).items():
            if not key.startswith("__"):
                members[key] = value
    # Widget-only work is not under test here.
    members["_set_detail_sections"] = lambda self, panel, handle: None
    members["_clear_details"] = lambda self, panel: None
    members["_update_diff_status"] = lambda self: None
    members["_schedule_reveal"] = lambda self: None
    return type("AltHarness", (), members)


def make_person(db: Any, given: str, surname: str, gender: int, year: int) -> Person:
    """Add a person born in ``year`` to ``db``."""
    person = Person()
    name = Name()
    name.set_first_name(given)
    sur = Surname()
    sur.set_surname(surname)
    name.add_surname(sur)
    person.set_primary_name(name)
    person.set_gender(gender)
    with DbTxn("person", db) as trans:
        event = Event()
        event.set_type(EventType.BIRTH)
        date = Date()
        date.set_yr_mon_day(year, 0, 0)
        event.set_date_object(date)
        db.add_event(event, trans)
        ref = EventRef()
        ref.ref = event.handle
        person.set_birth_ref(ref)
        db.add_person(person, trans)
    return person


# ------------------------------------------------------------
#
# Tests
#
# ------------------------------------------------------------
class AltCompareWindowTest(unittest.TestCase):
    """The alternate window's matching and right-panel behaviour."""

    def setUp(self) -> None:
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.t_exact = make_person(self.db, "John", "Smith", Person.MALE, 1900)
        self.t_near = make_person(self.db, "John", "Smith", Person.MALE, 1902)
        self.t_other = make_person(self.db, "Peter", "Brown", Person.MALE, 1850)

        handle = tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        )
        handle.write(SOURCE_GED)
        handle.close()
        self._path = handle.name
        self.gwizard = GedGWizard(self.db)
        self.assertTrue(self.gwizard.run_step("connect", gedcom_path=self._path))
        self.gwizard.run_step("load")
        self.source_db = self.gwizard.context["source_db"]
        self.by_name = {}
        for source_handle in self.source_db.iter_person_handles():
            person = self.source_db.get_person_from_handle(source_handle)
            self.by_name[person.get_primary_name().first_name] = source_handle
        self.window = self._window(MatchSettings())

    def tearDown(self) -> None:
        os.unlink(self._path)
        try:
            self.source_db.close()
        except Exception:  # pylint: disable=broad-except
            pass
        self.db.close()

    def _window(self, settings: MatchSettings) -> Any:
        window = _harness_class()()
        window.dbstate = MagicMock(db=self.db)
        window.gwizard = self.gwizard
        window.source_db = self.source_db
        window._progress_parent = None
        window._settings = settings
        window._rejected = {}
        window._syncing = False
        window.source_index = {}
        window.target_index = {}
        window.current_category = "person"
        window.diff_list = []
        window.diff_index = -1
        window.left_panel = _panel()
        window.right_panel = _panel()
        # Fill the left panel and match, as select_category does.
        GWizardAltCompareWindow._populate_people(
            window, window.left_panel["store"], window.right_panel["store"]
        )
        return window

    def candidates(self) -> list[str]:
        return [row[0] for row in self.window.right_panel["store"].rows()]

    def diff_sources(self) -> list[str]:
        return [entry["source_handle"] for entry in self.window.diff_list]

    def test_left_panel_lists_every_incoming_person(self) -> None:
        self.assertEqual(
            set(self.window._source_order), set(self.source_db.iter_person_handles())
        )

    def test_closest_match_is_chosen_and_the_next_one_when_taken(self) -> None:
        pairs = self.window._pair_map
        self.assertEqual(pairs[self.by_name["John"]], self.t_exact.handle)
        self.assertEqual(pairs[self.by_name["Johnny"]], self.t_near.handle)
        self.assertIsNone(pairs[self.by_name["Mary"]])
        self.assertIs(self.gwizard.context["pair_map"], pairs)

    def test_differences_are_listed_in_file_order(self) -> None:
        self.assertIn(self.by_name["Johnny"], self.diff_sources())
        self.assertIn(self.by_name["Mary"], self.diff_sources())
        order = self.window._source_order
        positions = [order[handle] for handle in self.diff_sources()]
        self.assertEqual(positions, sorted(positions))

    def test_right_panel_lists_only_similar_people_closest_first(self) -> None:
        self.window._show_candidates(self.by_name["John"])
        self.assertEqual(self.candidates(), [self.t_exact.handle, self.t_near.handle])
        texts = [row[7] for row in self.window.right_panel["store"].rows()]
        # Same names, same birth year (no month known): 2.75 of 3.
        self.assertEqual(texts[0], "92%")
        self.assertTrue(texts[1].endswith("paired"))

    def test_closest_match_is_selected(self) -> None:
        tree = self.window.right_panel["tree"]
        self.window._show_candidates(self.by_name["John"])
        tree.set_cursor.assert_called_with((0,))

    def test_no_similar_people_leaves_nothing_selected(self) -> None:
        tree = self.window.right_panel["tree"]
        self.window._show_candidates(self.by_name["Mary"])
        self.assertEqual(self.candidates(), [])
        tree.set_cursor.assert_not_called()

    def test_picking_another_candidate_pairs_with_it(self) -> None:
        john = self.by_name["John"]
        johnny = self.by_name["Johnny"]
        self.window._show_candidates(john)
        self.window._choose_target(john, self.t_near.handle)
        pairs = self.window._pair_map
        self.assertEqual(pairs[john], self.t_near.handle)
        self.assertEqual(self.window._pair_map_rev[self.t_near.handle], john)
        # The tree person moved, so the other incoming person lost it.
        self.assertIsNone(pairs[johnny])
        self.assertNotIn(self.t_exact.handle, self.window._pair_map_rev)
        entry = next(e for e in self.window.diff_list if e["source_handle"] == john)
        self.assertEqual(entry["target_handle"], self.t_near.handle)
        johnny_entry = next(
            e for e in self.window.diff_list if e["source_handle"] == johnny
        )
        self.assertIsNone(johnny_entry["target_handle"])

    def test_clearing_the_choice_leaves_the_person_unmatched(self) -> None:
        john = self.by_name["John"]
        self.window._show_candidates(john)
        selection = MagicMock()
        selection.get_tree_view.return_value = self.window.right_panel["tree"]
        selection.get_selected.return_value = (None, None)
        self.window.cb_record_selected(selection)
        self.assertIsNone(self.window._pair_map[john])
        self.assertIn(john, self.diff_sources())

    def test_not_a_match_drops_the_candidate(self) -> None:
        john = self.by_name["John"]
        self.window._show_candidates(john)
        self.window._reject_pair(john, self.t_exact.handle)
        self.assertNotIn(self.t_exact.handle, self.candidates())
        self.assertIsNone(self.window._pair_map[john])
        self.assertIn(self.t_exact.handle, self.window._rejected[john])
        entry = next(e for e in self.window.diff_list if e["source_handle"] == john)
        self.assertIsNone(entry["target_handle"])

    def test_a_pair_without_differences_leaves_the_list(self) -> None:
        johnny = self.by_name["Johnny"]
        self.window.diff_index = len(self.window.diff_list) - 1
        before = self.window.diff_index
        self.window._pair_differs = lambda source, target: False
        self.window._set_diff_entry(johnny, self.t_near.handle)
        self.assertNotIn(johnny, self.diff_sources())
        self.assertEqual(self.window.diff_index, before - 1)

    def test_birth_window_setting_hides_people_born_too_far_apart(self) -> None:
        self.window = self._window(MatchSettings(birth_window=1))
        self.window._show_candidates(self.by_name["John"])
        self.assertEqual(self.candidates(), [self.t_exact.handle])

    def test_without_one_to_one_both_get_the_closest(self) -> None:
        self.window = self._window(MatchSettings(one_to_one=False))
        pairs = self.window._pair_map
        self.assertEqual(pairs[self.by_name["John"]], self.t_exact.handle)
        self.assertEqual(pairs[self.by_name["Johnny"]], self.t_exact.handle)


class LauncherTest(unittest.TestCase):
    """The (Alt) menu entry opens the alternate window."""

    def _open(self, alternate: bool) -> tuple[MagicMock, MagicMock]:
        from unittest import mock

        from gramps.gui.gwizard import gwizardlauncher

        with (
            mock.patch(
                "gramps.gui.gwizard.gwizardaltcompare.GWizardAltCompareWindow"
            ) as alt,
            mock.patch(
                "gramps.gui.gwizard.gwizardcompare.GWizardCompareWindow"
            ) as standard,
        ):
            gwizardlauncher.open_compare_window(
                "uistate", "dbstate", "gwizard", parent=None, alternate=alternate
            )
        return alt, standard

    def test_alternate_opens_the_alternate_window(self) -> None:
        alt, standard = self._open(True)
        alt.assert_called_once_with("uistate", "dbstate", "gwizard", parent=None)
        alt.return_value.show.assert_called_once_with()
        standard.assert_not_called()

    def test_default_opens_the_standard_window(self) -> None:
        alt, standard = self._open(False)
        standard.assert_called_once_with("uistate", "dbstate", "gwizard", parent=None)
        alt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
