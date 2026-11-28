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
Unit tests for the shared record scoring in gwizard_base (tiers) and the
GWizard Multi-Archive Record Scan engine (gwizard_filemerge_recordscan).
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import tempfile
import threading
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import (
    Date,
    Event,
    EventRef,
    EventRoleType,
    EventType,
    Family,
    Name,
    NameType,
    Person,
    Surname,
)
from gramps.gen.gwizard.gwizard_base import (
    RECORD_TIERS,
    TIER_GMSB,
    TIER_GMSB_BOTH_PARENTS,
    TIER_GMSB_ONE_PARENT,
    TIER_GS,
    TIER_GSB,
    TIER_SCORE,
    RecordCandidate,
    RecordQuery,
    record_match_text,
    score_record,
    score_record_tier,
)
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    RECORD_SOURCE_CATEGORY,
    STATUS_CITED,
    STATUS_ERROR,
    STATUS_LINKED,
    STATUS_OK,
    STATUS_SKIPPED,
    STOP_ALLOWANCE,
    STOP_SCAN_LIMIT,
    PersonScan,
    RateLimiter,
    RecordScanner,
    RecordSource,
    ScanCache,
    ScanItem,
    SourceMatch,
    build_scan_items,
    discover_sources,
    matches_for_tier,
    needs_request,
    query_for_person,
    scan_item,
    score_matches,
    source_tiers,
    split_cited,
    tier_cell,
)


def _candidate(**kwargs: Any) -> RecordCandidate:
    """Return a candidate with a surname list from ``surname``."""
    surname = kwargs.pop("surname", "")
    kwargs.setdefault("surnames", [surname] if surname else [])
    return RecordCandidate(**kwargs)


# ------------------------------------------------------------
#
# FakeSource
#
# ------------------------------------------------------------
class FakeSource(RecordSource):
    """A record source that answers from a dict, without network."""

    source_id = "fake"
    title = "Fake"
    min_interval = 0.0
    has_links = True

    def __init__(self, records: dict[str, list[SourceMatch]] | None = None) -> None:
        """Answer searches by surname from ``records``."""
        self.records = records or {}
        self.searches: list[RecordQuery] = []
        self.lookups: list[str] = []
        self.fail_for: set[str] = set()

    def linked_key(self, db: Any, person: Person) -> str:
        """Treat a person attribute-free URL description as the link."""
        for url in person.get_url_list():
            if url.get_description() == "fake":
                return url.get_path()
        return ""

    def search(self, query: RecordQuery) -> list[SourceMatch]:
        """Return the stored records for the first surname."""
        self.searches.append(query)
        surname = query.surnames[0] if query.surnames else ""
        if surname in self.fail_for:
            raise RuntimeError("site down")
        return list(self.records.get(surname, []))

    def lookup(self, key: str) -> SourceMatch | None:
        """Return a record for a linked key."""
        self.lookups.append(key)
        return SourceMatch(key, key, _candidate(given="Linked", surname="Person"))


# ------------------------------------------------------------
#
# RecordTierTest
#
# ------------------------------------------------------------
class RecordTierTest(unittest.TestCase):
    """Scoring at the three match levels."""

    QUERY = RecordQuery(
        given="Thomas",
        middle="Lee",
        surnames=["Devault"],
        birth_year=1842,
        death_year=1910,
        gender="male",
    )

    def test_full_score_uses_every_part(self) -> None:
        """A perfect candidate scores 100 and compares years."""
        cand = _candidate(
            given="Thomas",
            middle="Lee",
            surname="Devault",
            birth_years=(1842, 1842),
            death_years=(1910, 1910),
            gender="male",
        )
        result = score_record(self.QUERY, cand)
        self.assertEqual(result.score, 100.0)
        self.assertTrue(result.compared_years)
        self.assertEqual(record_match_text(result), "100%")

    def test_gs_ignores_years_and_middle(self) -> None:
        """g/s is judged on given and surname only."""
        cand = _candidate(
            given="Thomas", middle="Xavier", surname="Devault", birth_years=(1700, 1700)
        )
        result = score_record_tier(self.QUERY, cand, TIER_GS)
        assert result is not None
        self.assertEqual(result.score, 100.0)
        self.assertFalse(result.compared_years)

    def test_gsb_needs_birth_on_both_sides(self) -> None:
        """g/s/b cannot be judged without a candidate birth year."""
        cand = _candidate(given="Thomas", surname="Devault")
        self.assertIsNone(score_record_tier(self.QUERY, cand, TIER_GSB))
        cand.birth_years = (1844, 1844)
        result = score_record_tier(self.QUERY, cand, TIER_GSB)
        assert result is not None
        self.assertLess(result.score, 100.0)
        self.assertGreater(result.score, 80.0)

    def test_gmsb_needs_middle_and_penalizes_other_middle(self) -> None:
        """g/m/s/b needs middle names and a differing one lowers the score."""
        cand = _candidate(given="Thomas", surname="Devault", birth_years=(1842, 1842))
        self.assertIsNone(score_record_tier(self.QUERY, cand, TIER_GMSB))
        cand.middle = "Lee"
        same = score_record_tier(self.QUERY, cand, TIER_GMSB)
        cand.middle = "Xavier"
        other = score_record_tier(self.QUERY, cand, TIER_GMSB)
        assert same is not None and other is not None
        self.assertEqual(same.score, 100.0)
        self.assertLess(other.score, same.score)

    def test_tier_needs_names(self) -> None:
        """No tier can be judged without both a given name and a surname."""
        cand = _candidate(surname="Devault", birth_years=(1842, 1842))
        for tier in (TIER_GS, TIER_GSB, TIER_GMSB):
            self.assertIsNone(score_record_tier(self.QUERY, cand, tier))

    def test_gender_halves_every_tier(self) -> None:
        """A differing known gender halves tier scores too."""
        cand = _candidate(given="Thomas", surname="Devault", gender="female")
        result = score_record_tier(self.QUERY, cand, TIER_GS)
        assert result is not None
        self.assertEqual(result.score, 50.0)

    def test_maiden_from_middle(self) -> None:
        """The last middle name counts as a surname only when asked."""
        query = RecordQuery(given="Mary", surnames=["Kreizer"])
        plain = _candidate(given="Mary", middle="Kreizer", surname="Smith")
        maiden = _candidate(
            given="Mary", middle="Kreizer", surname="Smith", maiden_from_middle=True
        )
        self.assertGreater(
            score_record(query, maiden).score, score_record(query, plain).score
        )

    def _with_parents(self, father: str = "", mother: str = "", **kw):
        """A g/m/s/b-perfect candidate with the given parents."""
        values = dict(
            given="Thomas",
            middle="Lee",
            surname="Devault",
            birth_years=(1842, 1842),
            gender="male",
        )
        values.update(kw)
        cand = _candidate(**values)
        cand.father_given = father
        cand.mother_given = mother
        return cand

    def _query(self, father: str = "John", mother: str = "Mary") -> RecordQuery:
        return RecordQuery(
            given="Thomas",
            middle="Lee",
            surnames=["Devault"],
            birth_year=1842,
            gender="male",
            father_first_name=father,
            mother_first_name=mother,
        )

    def test_both_parents_tier(self) -> None:
        """f+m needs both parents on both sides; both count."""
        both = self._query()
        perfect = self._with_parents("John", "Mary")
        result = score_record_tier(both, perfect, TIER_GMSB_BOTH_PARENTS)
        assert result is not None
        self.assertEqual(result.score, 100.0)
        wrong_mother = self._with_parents("John", "Agnes")
        lower = score_record_tier(both, wrong_mother, TIER_GMSB_BOTH_PARENTS)
        assert lower is not None
        self.assertLess(lower.score, 100.0)
        # One parent missing on either side: cannot be judged.
        self.assertIsNone(
            score_record_tier(both, self._with_parents("John"), TIER_GMSB_BOTH_PARENTS)
        )
        self.assertIsNone(
            score_record_tier(self._query(mother=""), perfect, TIER_GMSB_BOTH_PARENTS)
        )

    def test_one_parent_tier_takes_the_better_parent(self) -> None:
        """f|m is judged with one parent, and a wrong other parent does not hurt."""
        query = self._query()
        father_only = score_record_tier(
            query, self._with_parents("John"), TIER_GMSB_ONE_PARENT
        )
        wrong_mother = score_record_tier(
            query, self._with_parents("John", "Agnes"), TIER_GMSB_ONE_PARENT
        )
        assert father_only is not None and wrong_mother is not None
        self.assertEqual(father_only.score, 100.0)
        self.assertEqual(wrong_mother.score, 100.0)
        self.assertIsNone(
            score_record_tier(query, self._with_parents(), TIER_GMSB_ONE_PARENT)
        )

    def test_parent_tiers_need_gmsb_parts(self) -> None:
        """Parent levels also need what g/m/s/b needs (a middle name here)."""
        cand = self._with_parents("John", "Mary", middle="")
        for tier in (TIER_GMSB_BOTH_PARENTS, TIER_GMSB_ONE_PARENT):
            self.assertIsNone(score_record_tier(self._query(), cand, tier))

    def test_parent_initials_and_gender(self) -> None:
        """A parent's initial counts 0.85; a differing gender halves the score."""
        query = self._query()
        initial = score_record_tier(
            query, self._with_parents("J.", "Mary"), TIER_GMSB_BOTH_PARENTS
        )
        assert initial is not None
        self.assertLess(initial.score, 100.0)
        self.assertGreater(initial.score, 90.0)
        other = score_record_tier(
            query,
            self._with_parents("John", "Mary", gender="female"),
            TIER_GMSB_BOTH_PARENTS,
        )
        assert other is not None
        self.assertEqual(other.score, 50.0)

    def test_full_score_ignores_parents(self) -> None:
        """The overall score is unchanged by parents' names."""
        query = self._query()
        self.assertEqual(
            score_record(query, self._with_parents("John", "Mary")).score,
            score_record(query, self._with_parents("Peter", "Agnes")).score,
        )

    def test_unknown_tier(self) -> None:
        """An unknown tier name is an error."""
        with self.assertRaises(ValueError):
            score_record_tier(self.QUERY, _candidate(given="T"), "x")


# ------------------------------------------------------------
#
# ScoringHelpersTest
#
# ------------------------------------------------------------
class ScoringHelpersTest(unittest.TestCase):
    """score_matches, tier_cell and matches_for_tier."""

    def setUp(self) -> None:
        """Three matches: exact, close, and one without a birth year."""
        self.query = RecordQuery(given="Kevin", surnames=["White"], birth_year=1958)
        self.matches = [
            SourceMatch("A", "a", _candidate(given="Kevin", surname="White")),
            SourceMatch(
                "B",
                "b",
                _candidate(given="Kevin", surname="White", birth_years=(1958, 1958)),
            ),
            SourceMatch(
                "C",
                "c",
                _candidate(given="Peter", surname="Brown", birth_years=(1930, 1930)),
            ),
        ]

    def test_sorted_best_first(self) -> None:
        """Matches come back best full score first."""
        scored = score_matches(self.query, self.matches)
        self.assertEqual(scored[0].match.key, "B")
        self.assertEqual(scored[-1].match.key, "C")

    def test_tier_cells(self) -> None:
        """g/s counts both exact names; g/s/b only the dated one."""
        scored = score_matches(self.query, self.matches)
        gs = tier_cell(scored, TIER_GS, 80)
        gsb = tier_cell(scored, TIER_GSB, 80)
        gmsb = tier_cell(scored, TIER_GMSB, 80)
        self.assertEqual(gs.count, 2)
        self.assertEqual(gsb.count, 1)
        self.assertEqual(gsb.best, 100.0)
        self.assertFalse(gmsb.judged)
        self.assertEqual(gmsb.count, 0)

    def test_matches_for_tier(self) -> None:
        """Passing matches are offered; with none passing, all are."""
        scored = score_matches(self.query, self.matches)
        self.assertEqual(
            [s.match.key for s in matches_for_tier(scored, TIER_GSB, 80)], ["B"]
        )
        self.assertEqual(len(matches_for_tier(scored, TIER_GSB, 101)), 3)
        self.assertEqual(matches_for_tier(scored, None, 80)[0].match.key, "B")

    def test_single_score_tier(self) -> None:
        """TIER_SCORE is the full score, judged even without a surname."""
        scored = score_matches(self.query, self.matches, (TIER_SCORE,))
        self.assertEqual(list(scored[0].tiers), [TIER_SCORE])
        for item in scored:
            tier = item.tiers[TIER_SCORE]
            assert tier is not None
            self.assertEqual(tier.score, item.full.score)
        cell = tier_cell(scored, TIER_SCORE, 80)
        self.assertTrue(cell.judged)
        self.assertEqual(cell.count, 2)
        given_only = _candidate(given="Kevin")
        self.assertIsNone(score_record_tier(self.query, given_only, TIER_GS))
        self.assertIsNotNone(score_record_tier(self.query, given_only, TIER_SCORE))

    def test_source_tiers(self) -> None:
        """A source shows its own columns; unknown or none gives the default."""

        class OneColumn(FakeSource):
            tiers = (TIER_SCORE,)

        class Unknown(FakeSource):
            tiers = ("nonsense",)

        self.assertEqual(source_tiers(FakeSource()), RECORD_TIERS)
        self.assertEqual(source_tiers(OneColumn()), (TIER_SCORE,))
        self.assertEqual(source_tiers(Unknown()), RECORD_TIERS)

    def test_usage_text_default(self) -> None:
        """A source without a request allowance reports nothing."""
        self.assertEqual(FakeSource().usage_text(), "")


# ------------------------------------------------------------
#
# SourceMatchTest
#
# ------------------------------------------------------------
class SourceMatchTest(unittest.TestCase):
    """Serialization used by the cache."""

    def test_round_trip(self) -> None:
        """A match survives to_dict/from_dict, year ranges as tuples."""
        match = SourceMatch(
            "Devault-12",
            "Thomas Devault (1842-1910)",
            _candidate(
                given="Thomas",
                surname="Devault",
                birth_years=(1840, 1849),
                gender="male",
                maiden_from_middle=True,
            ),
            url="https://example.org/Devault-12",
            data={"profile": {"Name": "Devault-12"}},
        )
        back = SourceMatch.from_dict(match.to_dict())
        self.assertEqual(back, match)
        self.assertEqual(back.candidate.birth_years, (1840, 1849))


# ------------------------------------------------------------
#
# DatabaseTestBase
#
# ------------------------------------------------------------
class DatabaseTestBase(unittest.TestCase):
    """An in-memory Family Tree with a few people."""

    def setUp(self) -> None:
        """Create the database."""
        self.db = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        """Close the database."""
        self.db.close()

    def add_person(
        self,
        given: str,
        surname: str,
        gender: int = Person.MALE,
        birth: int | None = None,
        baptism: int | None = None,
        link: str = "",
    ) -> Person:
        """Add a person with an optional birth or baptism year."""
        person = Person()
        name = Name()
        name.set_first_name(given)
        surn = Surname()
        surn.set_surname(surname)
        name.add_surname(surn)
        person.set_primary_name(name)
        person.set_gender(gender)
        if link:
            from gramps.gen.lib import Url

            url = Url()
            url.set_path(link)
            url.set_description("fake")
            person.add_url(url)
        with DbTxn("add person", self.db) as trans:
            for year, etype in ((birth, EventType.BIRTH), (baptism, EventType.BAPTISM)):
                if not year:
                    continue
                event = Event()
                event.set_type(EventType(etype))
                date = Date()
                date.set_yr_mon_day(year, 0, 0)
                event.set_date_object(date)
                self.db.add_event(event, trans)
                ref = EventRef()
                ref.set_reference_handle(event.get_handle())
                ref.set_role(EventRoleType.PRIMARY)
                person.add_event_ref(ref)
                if etype == EventType.BIRTH:
                    person.set_birth_ref(ref)
            self.db.add_person(person, trans)
        return person


# ------------------------------------------------------------
#
# QueryForPersonTest
#
# ------------------------------------------------------------
class QueryForPersonTest(DatabaseTestBase):
    """Reading a person into a RecordQuery."""

    def test_names_years_gender(self) -> None:
        """Given names split into first and middle; birth year read."""
        person = self.add_person("Thomas Lee", "Devault", birth=1842)
        query = query_for_person(self.db, person)
        self.assertEqual(query.given, "Thomas")
        self.assertEqual(query.middle, "Lee")
        self.assertEqual(query.surnames, ["Devault"])
        self.assertEqual(query.birth_year, 1842)
        self.assertEqual(query.gender, "male")

    def test_parents_given_names(self) -> None:
        """The main family's father and mother give the parents' names."""
        child = self.add_person("Peter", "Smith")
        father = self.add_person("John Paul", "Smith")
        mother = self.add_person("Mary", "Jones", Person.FEMALE)
        family = Family()
        family.set_father_handle(father.get_handle())
        family.set_mother_handle(mother.get_handle())
        with DbTxn("family", self.db) as trans:
            self.db.add_family(family, trans)
            child.add_parent_family_handle(family.get_handle())
            self.db.commit_person(child, trans)
        query = query_for_person(self.db, child)
        self.assertEqual(query.father_first_name, "John Paul")
        self.assertEqual(query.mother_first_name, "Mary")
        orphan = query_for_person(self.db, father)
        self.assertEqual((orphan.father_first_name, orphan.mother_first_name), ("", ""))

    def test_baptism_fallback(self) -> None:
        """A baptism year stands in for a missing birth."""
        person = self.add_person("Mary", "Smith", Person.FEMALE, baptism=1801)
        self.assertEqual(query_for_person(self.db, person).birth_year, 1801)

    def test_married_surnames(self) -> None:
        """A married alternate name and a husband's surname are added."""
        wife = self.add_person("Mary", "Kreizer", Person.FEMALE)
        husband = self.add_person("John", "Smith")
        alt = Name()
        alt.set_type(NameType(NameType.MARRIED))
        surn = Surname()
        surn.set_surname("Jones")
        alt.add_surname(surn)
        wife.add_alternate_name(alt)
        family = Family()
        family.set_father_handle(husband.get_handle())
        family.set_mother_handle(wife.get_handle())
        with DbTxn("family", self.db) as trans:
            self.db.add_family(family, trans)
            wife.add_family_handle(family.get_handle())
            self.db.commit_person(wife, trans)
        query = query_for_person(self.db, wife)
        self.assertEqual(query.surnames, ["Kreizer", "Jones", "Smith"])


# ------------------------------------------------------------
#
# ScanTest
#
# ------------------------------------------------------------
class ScanTest(DatabaseTestBase):
    """build_scan_items, scan_item, the cache and RecordScanner."""

    def setUp(self) -> None:
        """Three people and a source that knows one of them."""
        super().setUp()
        self.devault = self.add_person("Thomas", "Devault", birth=1842)
        self.white = self.add_person("Kevin", "White", birth=1958, link="White-7")
        self.abbot = self.add_person("Ann", "Abbot", Person.FEMALE)
        self.source = FakeSource(
            {
                "Devault": [
                    SourceMatch(
                        "Devault-1",
                        "Thomas Devault",
                        _candidate(
                            given="Thomas", surname="Devault", birth_years=(1842, 1842)
                        ),
                    )
                ]
            }
        )

    def test_cited_keys_read_and_skipped(self) -> None:
        """Cited records are read up front; skip_cited saves the search."""

        class CitingSource(FakeSource):
            source_id = "citing"
            has_links = False

            def cited_keys(self, db: Any, person: Person) -> list[str]:
                surname = person.get_primary_name().get_surname()
                return ["Devault-1"] if surname == "Devault" else []

        source = CitingSource(self.source.records)
        items = {i.surname: i for i in build_scan_items(self.db, sources=[source])}
        self.assertEqual(items["Devault"].cited, {"citing": ["Devault-1"]})
        self.assertEqual(items["Abbot"].cited, {})
        # By default the person is still searched ...
        self.assertEqual(scan_item(source, items["Devault"]).status, STATUS_OK)
        # ... and with skip_cited no request is made.
        source.skip_cited = True
        source.searches.clear()
        scan = scan_item(source, items["Devault"])
        self.assertEqual(scan.status, STATUS_CITED)
        self.assertEqual(source.searches, [])
        self.assertEqual(scan_item(source, items["Abbot"]).status, STATUS_OK)

    def test_failing_cited_keys_is_ignored(self) -> None:
        """A source that cannot read citations does not stop the scan."""

        class BrokenSource(FakeSource):
            def cited_keys(self, db: Any, person: Person) -> list[str]:
                raise RuntimeError("broken")

        items = build_scan_items(self.db, sources=[BrokenSource()])
        self.assertEqual(len(items), 3)
        self.assertTrue(all(item.cited == {} for item in items))

    def test_split_cited(self) -> None:
        """Matches split into new and already cited, order kept."""
        matches = [
            SourceMatch(key, key, _candidate(given="A", surname="B"))
            for key in ("1", "2", "3")
        ]
        new, old = split_cited(matches, ["2"])
        self.assertEqual([m.key for m in new], ["1", "3"])
        self.assertEqual([m.key for m in old], ["2"])
        self.assertEqual(split_cited(matches, [])[1], [])

    def test_items_sorted_by_surname(self) -> None:
        """People come out by surname, with links read from the person."""
        items = build_scan_items(self.db, sources=[self.source])
        self.assertEqual([i.surname for i in items], ["Abbot", "Devault", "White"])
        self.assertEqual(items[2].links, {"fake": "White-7"})
        self.assertEqual(items[0].display_name(), "Abbot, Ann")

    def test_scan_item_outcomes(self) -> None:
        """Search, linked lookup, skipped and error outcomes."""
        items = {i.surname: i for i in build_scan_items(self.db, sources=[self.source])}
        found = scan_item(self.source, items["Devault"])
        self.assertEqual(found.status, STATUS_OK)
        self.assertEqual(found.matches[0].key, "Devault-1")
        linked = scan_item(self.source, items["White"])
        self.assertEqual(linked.status, STATUS_LINKED)
        self.assertEqual(self.source.lookups, ["White-7"])
        empty = ScanItem("h", "I1", "", "", None, None, 0, RecordQuery())
        self.assertEqual(scan_item(self.source, empty).status, STATUS_SKIPPED)
        self.source.fail_for.add("Abbot")
        failed = scan_item(self.source, items["Abbot"])
        self.assertEqual(failed.status, STATUS_ERROR)
        self.assertIn("site down", failed.error)

    def test_scanner_uses_cache_until_person_changes(self) -> None:
        """A second run is served from the cache; an edit rescans."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scan.json")
            items = build_scan_items(self.db, sources=[self.source])
            scanner = RecordScanner(ScanCache(path))
            seen: list[tuple[str, bool]] = []

            def cb_result(item: ScanItem, scan: PersonScan, cached: bool) -> None:
                seen.append((item.surname, cached))

            self.assertEqual(scanner.run([self.source], items, cb_result), 3)
            scanner.cache.save()
            self.assertEqual(len(self.source.searches), 2)  # White is linked

            again = RecordScanner(ScanCache(path))
            seen.clear()
            again.run([self.source], items, cb_result)
            self.assertTrue(all(cached for _name, cached in seen))
            self.assertEqual(len(self.source.searches), 2)

            items[1].change += 1  # Devault edited
            seen.clear()
            again.run([self.source], items, cb_result)
            self.assertEqual(dict(seen)["Devault"], False)
            self.assertEqual(len(self.source.searches), 3)

            seen.clear()
            again.run([self.source], items, cb_result, use_cache=False)
            self.assertFalse(any(cached for _name, cached in seen))

    def test_errors_are_not_cached(self) -> None:
        """A failed search is tried again next time."""
        self.source.fail_for.add("Devault")
        items = build_scan_items(self.db, sources=[self.source])
        scanner = RecordScanner()
        scanner.run([self.source], items, lambda *args: None)
        self.assertIsNone(scanner.cached(self.source, items[1]))
        self.assertIsNotNone(scanner.cached(self.source, items[0]))

    def test_cancel_stops_between_people(self) -> None:
        """Setting cancel stops the run."""
        cancel = threading.Event()
        items = build_scan_items(self.db, sources=[self.source])

        def cb_result(_item: ScanItem, _scan: PersonScan, _cached: bool) -> None:
            cancel.set()

        done = RecordScanner().run([self.source], items, cb_result, cancel=cancel)
        self.assertEqual(done, 1)

    def test_unreadable_cache_is_ignored(self) -> None:
        """A corrupt cache file starts empty."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scan.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            cache = ScanCache(path)
            item = build_scan_items(self.db, sources=[self.source])[0]
            self.assertIsNone(cache.get("fake", item))


# ------------------------------------------------------------
#
# AllowanceTest
#
# ------------------------------------------------------------
class AllowanceTest(DatabaseTestBase):
    """Per-scan search caps, request allowances and wants_search."""

    def setUp(self) -> None:
        """Four people, one with no birth year, and a source knowing none."""
        super().setUp()
        for given, surname, birth in (
            ("John", "Adams", 1850),
            ("Mary", "Brown", 1860),
            ("Robert", "Clark", None),
            ("Ann", "Davis", 1870),
        ):
            self.add_person(given, surname, birth=birth)
        self.items = build_scan_items(self.db, sources=[FakeSource()])

    @staticmethod
    def _run(scanner: RecordScanner, source: RecordSource, items: Any) -> list[str]:
        """Run a scan and return the surnames reported, in order."""
        seen: list[str] = []
        scanner.run(
            [source], items, lambda item, _scan, _cached: seen.append(item.surname)
        )
        return seen

    def test_scan_limit_defers_the_rest(self) -> None:
        """At most max_searches_per_scan searches; the next run goes on."""
        source = FakeSource()
        source.max_searches_per_scan = 2
        scanner = RecordScanner()
        self.assertEqual(self._run(scanner, source, self.items), ["Adams", "Brown"])
        self.assertEqual(len(source.searches), 2)
        self.assertEqual(scanner.deferred, {"fake": 2})
        self.assertEqual(scanner.stopped, {"fake": STOP_SCAN_LIMIT})
        self.assertEqual(scanner.searched, {"fake": 2})
        # Deferred people are not cached, so the next run searches them and
        # serves the first two from the cache.
        seen = self._run(scanner, source, self.items)
        self.assertEqual(seen, ["Adams", "Brown", "Clark", "Davis"])
        self.assertEqual(len(source.searches), 4)
        self.assertEqual(scanner.deferred, {})

    def test_allowance_runs_out(self) -> None:
        """requests_left() at 0 stops the source, as checked each time."""

        class MeteredSource(FakeSource):
            left = 1

            def requests_left(self) -> int | None:
                return self.left

            def search(self, query: RecordQuery) -> list[SourceMatch]:
                self.left -= 1
                return super().search(query)

        source = MeteredSource()
        scanner = RecordScanner()
        self.assertEqual(self._run(scanner, source, self.items), ["Adams"])
        self.assertEqual(scanner.deferred, {"fake": 3})
        self.assertEqual(scanner.stopped, {"fake": STOP_ALLOWANCE})

    def test_unlimited_by_default(self) -> None:
        """A source with no cap and no allowance searches everyone."""
        source = FakeSource()
        scanner = RecordScanner()
        self.assertEqual(len(self._run(scanner, source, self.items)), 4)
        self.assertEqual(scanner.deferred, {})
        self.assertEqual(scanner.stopped, {})

    def test_wants_search_skips_without_a_request(self) -> None:
        """A person the source turns down is skipped and costs nothing."""

        class DatedSource(FakeSource):
            max_searches_per_scan = 3

            def wants_search(self, query: RecordQuery) -> bool:
                return query.birth_year is not None

        source = DatedSource()
        items = {item.surname: item for item in self.items}
        self.assertFalse(needs_request(source, items["Clark"]))
        self.assertTrue(needs_request(source, items["Adams"]))
        self.assertEqual(scan_item(source, items["Clark"]).status, STATUS_SKIPPED)
        source.searches.clear()
        scanner = RecordScanner()
        # Clark is skipped without using one of the 3 searches.
        self.assertEqual(len(self._run(scanner, source, self.items)), 4)
        self.assertEqual(len(source.searches), 3)
        self.assertEqual(scanner.deferred, {})

    def test_failing_checks_do_not_stop_the_scan(self) -> None:
        """A broken wants_search or requests_left means "go ahead"."""

        class BrokenSource(FakeSource):
            def wants_search(self, query: RecordQuery) -> bool:
                raise RuntimeError("broken")

            def requests_left(self) -> int | None:
                raise RuntimeError("broken")

        source = BrokenSource()
        scanner = RecordScanner()
        self.assertEqual(len(self._run(scanner, source, self.items)), 4)
        self.assertEqual(scanner.deferred, {})


# ------------------------------------------------------------
#
# RateLimiterTest
#
# ------------------------------------------------------------
class RateLimiterTest(unittest.TestCase):
    """Spacing requests to a site."""

    def test_waits_between_calls(self) -> None:
        """The second call sleeps until the interval has passed."""
        now = [0.0]
        slept: list[float] = []

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            now[0] += seconds

        limiter = RateLimiter(0.5, clock=lambda: now[0], sleep=sleep)
        limiter.wait()
        self.assertEqual(slept, [])
        limiter.wait()
        self.assertAlmostEqual(sum(slept), 0.5)


# ------------------------------------------------------------
#
# DiscoverSourcesTest
#
# ------------------------------------------------------------
class DiscoverSourcesTest(unittest.TestCase):
    """Collecting sources from GENERAL plugins."""

    class PluginData:
        """Stand-in for a registered GENERAL plugin."""

        def __init__(self, pid: str, data: Any) -> None:
            """Remember the id and loaded data."""
            self.id = pid
            self.data = data

    class Module:
        """Stand-in for a plugin module with load_on_reg."""

        def __init__(self, sources: list[Any]) -> None:
            """Remember what load_on_reg returns."""
            self.sources = sources

        def load_on_reg(self, _dbstate: Any, _uistate: Any, _plugin: Any) -> list[Any]:
            """Return the sources."""
            return self.sources

    class Manager:
        """Stand-in for the plugin manager."""

        def __init__(self, plugins: list[Any], modules: dict[str, Any]) -> None:
            """Remember plugins and the modules load_plugin returns."""
            self.plugins = plugins
            self.modules = modules
            self.asked: list[str | None] = []

        def get_reg_general(self, category: str | None = None) -> list[Any]:
            """Return the plugins of a category."""
            self.asked.append(category)
            return self.plugins

        def load_plugin(self, pdata: Any) -> Any:
            """Return the module of a plugin."""
            return self.modules.get(pdata.id)

    def test_loaded_and_unloaded_plugins(self) -> None:
        """Data from load_on_reg is used; unloaded plugins are loaded once."""
        first = FakeSource()
        second = FakeSource()
        second.source_id, second.title = "other", "Another"
        duplicate = FakeSource()
        manager = self.Manager(
            [
                self.PluginData("a", [first]),
                self.PluginData("b", []),
                self.PluginData("c", duplicate),
                self.PluginData("d", ["not a source"]),
            ],
            {"b": self.Module([second])},
        )
        sources = discover_sources(manager)
        self.assertEqual(manager.asked, [RECORD_SOURCE_CATEGORY])
        self.assertEqual([s.source_id for s in sources], ["other", "fake"])
        self.assertIs(sources[1], first)


if __name__ == "__main__":
    unittest.main()
