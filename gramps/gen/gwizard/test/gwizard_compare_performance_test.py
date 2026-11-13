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
Tests for the matching and row-handling speedups of the GWizard compare
window: scoring from profiles, shared surname group rows and remembered row
iters.
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
import types
import unittest
from types import SimpleNamespace
from typing import Any

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
from gramps.gen.db.utils import import_as_dict, make_database
from gramps.gen.display.name import displayer as name_displayer
from gramps.gen.gwizard.gwizard_base import CandidateMatcher
from gramps.gen.lib import Date, Event, EventRef, EventType, Name, Person, Surname
from gramps.gen.user import User
from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow


def make_person(
    db: Any,
    given: str,
    surname: str,
    gender: int = Person.UNKNOWN,
    birth: tuple[int, int, int] | None = None,
) -> Person:
    """Add a person (with an optional birth date) to ``db``."""
    person = Person()
    name = Name()
    name.set_first_name(given)
    sur = Surname()
    sur.set_surname(surname)
    name.add_surname(sur)
    person.set_primary_name(name)
    person.set_gender(gender)
    with DbTxn("person", db) as trans:
        if birth:
            event = Event()
            event.set_type(EventType.BIRTH)
            date = Date()
            date.set_yr_mon_day(*birth)
            event.set_date_object(date)
            db.add_event(event, trans)
            ref = EventRef()
            ref.ref = event.handle
            person.set_birth_ref(ref)
        db.add_person(person, trans)
    return person


def memory_db() -> Any:
    db = make_database("sqlite")
    db.load(":memory:")
    return db


# ------------------------------------------------------------
#
# Scoring from profiles gives the same numbers as before
#
# ------------------------------------------------------------
class ProfileScoringTest(unittest.TestCase):
    """score_match, now built on profiles, keeps its exact scores."""

    def setUp(self) -> None:
        self.db = memory_db()
        self.matcher = CandidateMatcher(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def _score(self, first: Person, second: Person) -> float:
        score = self.matcher.score_match(first, second)
        # The profile route must give the very same number.
        self.assertEqual(
            score,
            self.matcher.score_profiles(
                self.matcher.profile(first, self.db),
                self.matcher.profile(second, self.db),
            ),
        )
        return score

    def test_scores_match_the_values_the_old_code_gave(self) -> None:
        """Reference values were produced by the previous implementation."""
        smith = lambda **kw: make_person(self.db, "John", "Smith", Person.MALE, **kw)
        cases = [
            (smith(birth=(1850, 3, 4)), smith(birth=(1850, 3, 4)), 3.0),
            (smith(birth=(1850, 0, 0)), smith(birth=(1850, 5, 6)), 2.75),
            (smith(birth=(1850, 1, 1)), smith(birth=(1852, 1, 1)), 2.5),
            (smith(birth=(1850, 1, 1)), smith(birth=(1854, 1, 1)), 2.25),
            (
                make_person(self.db, "John", "Smith"),
                make_person(self.db, "John", "Smith"),
                2.0,
            ),
            (
                make_person(self.db, "John", "Smith"),
                make_person(self.db, "John", "Smyth"),
                1.75,
            ),
            (
                make_person(self.db, "Alice", "Smith"),
                make_person(self.db, "Bob", "Smith"),
                0.25,
            ),
            (
                make_person(self.db, "Pat", "Doe", Person.MALE),
                make_person(self.db, "Pat", "Doe", Person.FEMALE),
                -1.0,
            ),
            (
                make_person(self.db, "Marta", "Ericsdotter"),
                make_person(self.db, "Martha", "Ericsdotter"),
                1.6,
            ),
        ]
        for first, second, expected in cases:
            self.assertEqual(self._score(first, second), expected)

    def test_profile_reads_the_fields_scoring_needs(self) -> None:
        person = make_person(
            self.db, " Anna ", "Hansdotter", Person.FEMALE, (1900, 2, 3)
        )
        profile = self.matcher.profile(person, self.db)
        self.assertEqual(profile.given, "Anna")
        self.assertEqual(profile.first_name, "anna")
        self.assertEqual(profile.first_surname, "hansdotter")
        self.assertEqual(profile.surnames, "hansdotter")
        self.assertEqual(profile.birth, (1900, 2, 3))
        self.assertEqual(profile.gender, Person.FEMALE)

    def test_profile_without_birth_has_none(self) -> None:
        profile = self.matcher.profile(make_person(self.db, "A", "B"), self.db)
        self.assertIsNone(profile.birth)


# ------------------------------------------------------------
#
# Best match uses the profiles
#
# ------------------------------------------------------------
class BestMatchTest(unittest.TestCase):
    """The compare window picks the same match, reading each person once."""

    def setUp(self) -> None:
        self.target_db = memory_db()
        self.source_db = memory_db()
        self.matcher = CandidateMatcher(self.target_db)
        self.window = SimpleNamespace(
            dbstate=SimpleNamespace(db=self.target_db),
            source_db=self.source_db,
            _rejected={},
            match_threshold=0.7,
            _source_profiles={},
            _match_key=GWizardCompareWindow._match_key,
        )
        for name in ("_best_match_with_score", "_source_profile"):
            method = getattr(GWizardCompareWindow, name)
            setattr(self.window, name, types.MethodType(method, self.window))

    def tearDown(self) -> None:
        self.target_db.close()
        self.source_db.close()

    def _best(self, source: Person) -> tuple[Any, float]:
        GWizardCompareWindow._build_target_index(self.window, self.matcher)
        return self.window._best_match_with_score(self.matcher, source)

    def test_exact_name_and_birth_wins_over_a_namesake(self) -> None:
        make_person(self.target_db, "John", "Smith", birth=(1800, 1, 1))
        right = make_person(self.target_db, "John", "Smith", birth=(1850, 3, 4))
        source = make_person(self.source_db, "John", "Smith", birth=(1850, 3, 4))
        handle, score = self._best(source)
        self.assertEqual(handle, right.handle)
        self.assertEqual(score, 3.0)

    def test_shared_surname_alone_is_not_a_match(self) -> None:
        make_person(self.target_db, "Bob", "Smith")
        source = make_person(self.source_db, "Zed", "Smith")
        handle, _score = self._best(source)
        self.assertIsNone(handle)

    def test_birth_year_alone_justifies_considering_a_candidate(self) -> None:
        """Different surname spelling and given name, but the same birth date."""
        target = make_person(self.target_db, "Zack", "Smyth", birth=(1850, 3, 4))
        same_year = make_person(self.source_db, "Zed", "Smith", birth=(1850, 3, 4))
        handle, _score = self._best(same_year)
        self.assertEqual(handle, target.handle)
        # Without the shared birth year nothing links the two.
        other_year = make_person(self.source_db, "Zed", "Smith", birth=(1900, 1, 1))
        handle, _score = self._best(other_year)
        self.assertIsNone(handle)

    def test_rejected_candidate_is_skipped(self) -> None:
        target = make_person(self.target_db, "John", "Smith")
        source = make_person(self.source_db, "John", "Smith")
        self.window._rejected = {source.handle: {target.handle}}
        handle, _score = self._best(source)
        self.assertIsNone(handle)

    def test_source_profile_is_read_once(self) -> None:
        make_person(self.target_db, "John", "Smith")
        source = make_person(self.source_db, "John", "Smith")
        self._best(source)
        first = self.window._source_profiles[source.handle]
        self._best(source)
        self.assertIs(self.window._source_profiles[source.handle], first)


# ------------------------------------------------------------
#
# Group rows and row marking without searching every row
#
# ------------------------------------------------------------
class _Node:
    def __init__(self, parent: Any, values: list[str]) -> None:
        self.parent = parent
        self.values = list(values)
        self.children: list[_Node] = []


class _Row:
    def __init__(self, node: _Node, path: tuple[int, ...]) -> None:
        self.node = node
        self.path = path

    def __getitem__(self, index: int) -> str:
        return self.node.values[index]


class FakeTreeStore:
    """Just enough of Gtk.TreeStore for the compare window's row code."""

    def __init__(self) -> None:
        self.roots: list[_Node] = []
        self.valid: set[int] = set()
        self.reads = 0
        self.searches = 0

    def append(self, parent: _Node | None, values: list[str]) -> _Node:
        node = _Node(parent, values)
        (parent.children if parent else self.roots).append(node)
        self.valid.add(id(node))
        return node

    def __iter__(self) -> Any:
        self.searches += 1
        for index, node in enumerate(self.roots):
            yield _Row(node, (index,))

    def get_iter(self, path: tuple[int, ...]) -> _Node:
        return self.roots[path[0]]

    def iter_is_valid(self, node: _Node) -> bool:
        return id(node) in self.valid

    def set_value(self, node: _Node, column: int, value: str) -> None:
        node.values[column] = value

    def get_value(self, node: _Node, column: int) -> str:
        self.reads += 1
        return node.values[column]

    def get_iter_first(self) -> _Node | None:
        return self.roots[0] if self.roots else None

    def iter_children(self, node: _Node) -> _Node | None:
        return node.children[0] if node.children else None

    def iter_next(self, node: _Node) -> _Node | None:
        siblings = node.parent.children if node.parent else self.roots
        index = siblings.index(node)
        return siblings[index + 1] if index + 1 < len(siblings) else None


PEOPLE_GED = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Dad /Smith/
0 @I2@ INDI
1 NAME Mom /Smith/
0 @I3@ INDI
1 NAME Kid /Smith/
0 @I4@ INDI
1 NAME Ann /Jones/
0 @I5@ INDI
1 NAME Bob /Jones/
0 @I6@ INDI
1 NAME Zed /Doe/
0 TRLR
"""


class RowHandlingTest(unittest.TestCase):
    """Adding rows and marking differences."""

    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        )
        handle.write(PEOPLE_GED)
        handle.close()
        self._path = handle.name
        self.db = import_as_dict(self._path, User())
        self.people = [
            self.db.get_person_from_handle(h) for h in self.db.iter_person_handles()
        ]

    def tearDown(self) -> None:
        self.db.close()
        os.remove(self._path)

    def _fill(self, cache: bool) -> tuple[FakeTreeStore, dict[str, _Node]]:
        store = FakeTreeStore()
        groups: dict[str, Any] | None = {} if cache else None
        rows = {}
        for person in self.people:
            rows[person.handle] = GWizardCompareWindow._add_person_row(
                store, self.db, person, name_displayer.display(person), groups
            )
        return store, rows

    @staticmethod
    def _shape(store: FakeTreeStore) -> list[tuple[str, list[str]]]:
        return sorted(
            (r.values[1], sorted(c.values[1] for c in r.children)) for r in store.roots
        )

    def test_cache_gives_the_same_tree_as_searching(self) -> None:
        cached, _rows = self._fill(cache=True)
        searched, _rows = self._fill(cache=False)
        self.assertEqual(self._shape(cached), self._shape(searched))
        self.assertEqual(len(cached.roots), 3)  # Smith, Jones, Doe

    def test_cache_means_group_rows_are_never_searched(self) -> None:
        cached, _rows = self._fill(cache=True)
        searched, _rows = self._fill(cache=False)
        self.assertEqual(cached.searches, 0)
        self.assertEqual(searched.searches, len(self.people))

    def test_returned_iter_is_the_person_row(self) -> None:
        _store, rows = self._fill(cache=True)
        for handle, node in rows.items():
            self.assertEqual(node.values[0], handle)

    def test_marking_with_remembered_iters_does_not_search(self) -> None:
        store, rows = self._fill(cache=True)
        store._gwizard_row_iters = rows
        target = self.people[3].handle
        GWizardCompareWindow._mark_row(store, target)
        self.assertEqual(rows[target].values[7], "*")
        self.assertEqual(store.reads, 0)

    def test_marking_falls_back_to_searching(self) -> None:
        store, rows = self._fill(cache=True)
        target = self.people[4].handle
        GWizardCompareWindow._mark_row(store, target, "o")
        self.assertEqual(rows[target].values[7], "o")
        self.assertGreater(store.reads, 0)

    def test_stale_iter_falls_back_to_searching(self) -> None:
        store, rows = self._fill(cache=True)
        store._gwizard_row_iters = rows
        target = self.people[2].handle
        store.valid.discard(id(rows[target]))  # as if the row was removed
        GWizardCompareWindow._mark_row(store, target)
        self.assertGreater(store.reads, 0)

    def test_unremembered_handle_is_still_found(self) -> None:
        store, rows = self._fill(cache=True)
        target = self.people[5].handle
        store._gwizard_row_iters = {k: v for k, v in rows.items() if k != target}
        GWizardCompareWindow._mark_row(store, target)
        self.assertEqual(rows[target].values[7], "*")


if __name__ == "__main__":
    unittest.main()
