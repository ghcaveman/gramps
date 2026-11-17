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
Tests for the candidate matching of the alternate (Alt) compare window.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.gwizard.gwizard_base import CandidateMatcher
from gramps.gen.gwizard.gwizardaltmatch import (
    MAX_SCORE,
    SCOPE_ALL,
    SCOPE_SURNAME,
    SCOPE_SURNAME_INITIAL,
    AltCandidateFinder,
    MatchSettings,
    match_key,
    pair_greedy,
    rank_candidates,
    score_percent,
)
from gramps.gen.lib import Date, Event, EventRef, EventType, Name, Person, Surname


def make_person(
    db: Any,
    given: str,
    surname: str,
    gender: int = Person.UNKNOWN,
    birth_year: int | None = None,
) -> Person:
    """Add a person (with an optional birth year) to ``db``."""
    person = Person()
    name = Name()
    name.set_first_name(given)
    sur = Surname()
    sur.set_surname(surname)
    name.add_surname(sur)
    person.set_primary_name(name)
    person.set_gender(gender)
    with DbTxn("person", db) as trans:
        if birth_year:
            event = Event()
            event.set_type(EventType.BIRTH)
            date = Date()
            date.set_yr_mon_day(birth_year, 0, 0)
            event.set_date_object(date)
            db.add_event(event, trans)
            ref = EventRef()
            ref.ref = event.handle
            person.set_birth_ref(ref)
        db.add_person(person, trans)
    return person


def memory_db() -> Any:
    """Return an empty in-memory database."""
    db = make_database("sqlite")
    db.load(":memory:")
    return db


class _Base(unittest.TestCase):
    """A source and a target database with a finder over the target."""

    def setUp(self) -> None:
        self.source_db = memory_db()
        self.target_db = memory_db()
        self.matcher = CandidateMatcher(self.target_db)

    def tearDown(self) -> None:
        self.source_db.close()
        self.target_db.close()

    def finder(self, **settings: Any) -> AltCandidateFinder:
        finder = AltCandidateFinder(self.matcher, MatchSettings(**settings))
        for handle in self.target_db.iter_person_handles():
            person = self.target_db.get_person_from_handle(handle)
            finder.add_target(handle, person, self.target_db)
        return finder

    def rank(self, finder: AltCandidateFinder, person: Person, **kw: Any) -> list:
        profile = self.matcher.profile(person, self.source_db)
        return finder.rank(profile, match_key(person), **kw)

    def handles(self, ranked: list) -> list:
        return [handle for _score, handle in ranked]


# ------------------------------------------------------------
#
# Settings and helpers
#
# ------------------------------------------------------------
class SettingsTest(unittest.TestCase):
    """MatchSettings and the percentage helpers."""

    def test_min_score_is_a_share_of_the_maximum(self) -> None:
        self.assertAlmostEqual(MatchSettings(min_percent=50).min_score, 1.5)
        self.assertEqual(MatchSettings(min_percent=0).min_score, 0.0)
        self.assertAlmostEqual(MatchSettings(min_percent=100).min_score, MAX_SCORE)

    def test_min_score_clamps_out_of_range_percentages(self) -> None:
        self.assertEqual(MatchSettings(min_percent=-10).min_score, 0.0)
        self.assertAlmostEqual(MatchSettings(min_percent=250).min_score, MAX_SCORE)

    def test_score_percent(self) -> None:
        self.assertEqual(score_percent(MAX_SCORE), 100)
        self.assertEqual(score_percent(1.5), 50)
        self.assertEqual(score_percent(0.0), 0)
        self.assertEqual(score_percent(-1.0), 0)
        self.assertEqual(score_percent(9.0), 100)


# ------------------------------------------------------------
#
# Ranking
#
# ------------------------------------------------------------
class RankTest(_Base):
    """Candidates are listed closest first, within the tolerances."""

    def test_closest_first(self) -> None:
        exact = make_person(self.target_db, "John", "Smith", Person.MALE, 1900)
        near = make_person(self.target_db, "John", "Smith", Person.MALE, 1903)
        other = make_person(self.target_db, "Jim", "Smith", Person.MALE, 1950)
        source = make_person(self.source_db, "John", "Smith", Person.MALE, 1900)
        ranked = self.rank(self.finder(min_percent=0, use_birth_window=False), source)
        self.assertEqual(
            self.handles(ranked), [exact.handle, near.handle, other.handle]
        )
        scores = [score for score, _h in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_minimum_match_leaves_out_weak_candidates(self) -> None:
        exact = make_person(self.target_db, "John", "Smith", Person.MALE, 1900)
        make_person(self.target_db, "Zachary", "Smith", Person.MALE)
        source = make_person(self.source_db, "John", "Smith", Person.MALE, 1900)
        ranked = self.rank(self.finder(min_percent=60), source)
        self.assertEqual(self.handles(ranked), [exact.handle])

    def test_birth_window_leaves_out_people_born_too_far_apart(self) -> None:
        close = make_person(self.target_db, "John", "Smith", Person.MALE, 1905)
        make_person(self.target_db, "John", "Smith", Person.MALE, 1930)
        unknown = make_person(self.target_db, "John", "Smith", Person.MALE)
        source = make_person(self.source_db, "John", "Smith", Person.MALE, 1900)
        ranked = self.rank(self.finder(min_percent=0, birth_window=10), source)
        self.assertEqual(set(self.handles(ranked)), {close.handle, unknown.handle})

    def test_birth_window_off_keeps_everyone(self) -> None:
        make_person(self.target_db, "John", "Smith", Person.MALE, 1930)
        source = make_person(self.source_db, "John", "Smith", Person.MALE, 1900)
        on = self.rank(self.finder(min_percent=0, birth_window=5), source)
        off = self.rank(
            self.finder(min_percent=0, use_birth_window=False, birth_window=5),
            source,
        )
        self.assertEqual(on, [])
        self.assertEqual(len(off), 1)

    def test_source_without_birth_is_not_limited_by_the_window(self) -> None:
        make_person(self.target_db, "John", "Smith", Person.MALE, 1930)
        source = make_person(self.source_db, "John", "Smith", Person.MALE)
        ranked = self.rank(self.finder(min_percent=0, birth_window=0), source)
        self.assertEqual(len(ranked), 1)

    def test_other_gender_is_never_a_candidate(self) -> None:
        make_person(self.target_db, "John", "Smith", Person.FEMALE, 1900)
        source = make_person(self.source_db, "John", "Smith", Person.MALE, 1900)
        self.assertEqual(self.rank(self.finder(min_percent=0), source), [])

    def test_rejected_people_are_left_out(self) -> None:
        first = make_person(self.target_db, "John", "Smith", Person.MALE, 1900)
        second = make_person(self.target_db, "John", "Smith", Person.MALE, 1901)
        source = make_person(self.source_db, "John", "Smith", Person.MALE, 1900)
        ranked = self.rank(self.finder(), source, rejected={first.handle})
        self.assertEqual(self.handles(ranked), [second.handle])

    def test_show_up_to_limits_the_list(self) -> None:
        for year in range(1900, 1906):
            make_person(self.target_db, "John", "Smith", Person.MALE, year)
        source = make_person(self.source_db, "John", "Smith", Person.MALE, 1900)
        self.assertEqual(len(self.rank(self.finder(max_shown=3), source)), 3)

    def test_duplicate_pool_entries_are_listed_once(self) -> None:
        person = make_person(self.target_db, "John", "Smith", Person.MALE, 1900)
        source = make_person(self.source_db, "John", "Smith", Person.MALE, 1900)
        finder = self.finder()
        ranked = rank_candidates(
            self.matcher.profile(source, self.source_db),
            [person.handle, person.handle],
            finder.profiles,
            finder.settings,
        )
        self.assertEqual(len(ranked), 1)


# ------------------------------------------------------------
#
# Where candidates are looked for
#
# ------------------------------------------------------------
class ScopeTest(_Base):
    """The Look in setting decides which tree people are considered."""

    def setUp(self) -> None:
        super().setUp()
        self.same = make_person(self.target_db, "Mary", "Smith", Person.FEMALE, 1900)
        self.sounds = make_person(self.target_db, "Molly", "Smyth", Person.FEMALE, 1900)
        self.married = make_person(self.target_db, "Mary", "Jones", Person.FEMALE, 1900)
        self.source = make_person(self.source_db, "Mary", "Smith", Person.FEMALE, 1900)

    def test_similar_sounding_surname_ignores_the_initial(self) -> None:
        ranked = self.rank(self.finder(scope=SCOPE_SURNAME, min_percent=0), self.source)
        self.assertEqual(
            set(self.handles(ranked)), {self.same.handle, self.sounds.handle}
        )

    def test_surname_and_initial_needs_both(self) -> None:
        make_person(self.target_db, "Anne", "Smith", Person.FEMALE, 1900)
        ranked = self.rank(
            self.finder(scope=SCOPE_SURNAME_INITIAL, min_percent=0), self.source
        )
        self.assertEqual(
            set(self.handles(ranked)), {self.same.handle, self.sounds.handle}
        )

    def test_everyone_finds_a_changed_surname(self) -> None:
        ranked = self.rank(self.finder(scope=SCOPE_ALL, min_percent=0), self.source)
        self.assertIn(self.married.handle, self.handles(ranked))
        self.assertEqual(self.handles(ranked)[0], self.same.handle)


# ------------------------------------------------------------
#
# Automatic pairing
#
# ------------------------------------------------------------
class PairGreedyTest(unittest.TestCase):
    """The automatic match of every incoming person."""

    def test_best_scores_are_paired_first(self) -> None:
        ranked = {
            "s1": [(2.0, "t1"), (1.0, "t2")],
            "s2": [(2.5, "t1")],
        }
        pairs, rev = pair_greedy(ranked, ["s1", "s2"])
        self.assertEqual(pairs, {"s2": "t1", "s1": "t2"})
        self.assertEqual(rev, {"t1": "s2", "t2": "s1"})

    def test_falls_back_to_the_next_candidate(self) -> None:
        ranked = {"s1": [(3.0, "t1")], "s2": [(2.0, "t1"), (1.5, "t2")]}
        pairs, _rev = pair_greedy(ranked, ["s1", "s2"])
        self.assertEqual(pairs["s2"], "t2")

    def test_unmatched_when_every_candidate_is_taken(self) -> None:
        ranked = {"s1": [(3.0, "t1")], "s2": [(2.0, "t1")], "s3": []}
        pairs, _rev = pair_greedy(ranked, ["s1", "s2", "s3"])
        self.assertIsNone(pairs["s2"])
        self.assertIsNone(pairs["s3"])

    def test_without_one_to_one_a_tree_person_can_be_shared(self) -> None:
        ranked = {"s1": [(3.0, "t1")], "s2": [(2.0, "t1")]}
        pairs, rev = pair_greedy(ranked, ["s1", "s2"], one_to_one=False)
        self.assertEqual(pairs, {"s1": "t1", "s2": "t1"})
        self.assertEqual(rev, {"t1": "s1"})

    def test_ties_go_to_the_earlier_person(self) -> None:
        ranked = {"s2": [(2.0, "t1")], "s1": [(2.0, "t1")]}
        pairs, _rev = pair_greedy(ranked, ["s1", "s2"])
        self.assertEqual(pairs["s1"], "t1")
        self.assertIsNone(pairs["s2"])


if __name__ == "__main__":
    unittest.main()
