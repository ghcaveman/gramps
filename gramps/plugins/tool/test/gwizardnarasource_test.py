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

"""Unit tests for the NARA catalog as a GWizard Multi-Archive Record Scan source."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import json
import os
import unittest
from typing import Any
from unittest.mock import Mock, patch

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.gwizard.gwizard_base import TIER_GS, RecordQuery
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    STATUS_ERROR,
    STATUS_OK,
    STOP_ALLOWANCE,
    RecordScanner,
    ScanItem,
    SourceMatch,
    scan_item,
    score_matches,
    tier_cell,
)
from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface
from gramps.gen.gwizard.gwizardnarausage import KIND_SEARCH, NaraUsage
from gramps.plugins.tool.gwizardnaraquerybuilder import (
    build_primary_nara_query,
    name_phrases,
    primary_name_parts,
)
from gramps.plugins.tool.gwizardnarasource import (
    TIER_SCORE,
    NaraSource,
    load_on_reg,
)

_DATA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "..",
    "gen",
    "gwizard",
    "test",
    "data",
)


def _fixture(name: str) -> dict:
    """Load a saved NARA API response (core tree or addon tests/data)."""
    for folder in (
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
        os.path.normpath(_DATA),
    ):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
    raise unittest.SkipTest(f"missing fixture {name}")


# ------------------------------------------------------------------
#
# NaraSourceTest
#
# ------------------------------------------------------------------
class NaraSourceTest(unittest.TestCase):
    """Searching NARA and opening a record through NaraSource."""

    def setUp(self) -> None:
        """A source on a client that answers with a saved pension search."""
        self.client = Mock()
        self.client.search_records.return_value = _fixture("nara_search_pension.json")
        self.client.extract_hits.side_effect = NaraCatalogInterface.extract_hits
        self.source = NaraSource(client=self.client)
        self.query = RecordQuery(
            given="Mary", middle="", surnames=["Kreizer"], birth_year=1840
        )

    def test_load_on_reg_offers_nara(self) -> None:
        """The plugin offers one NARA source, without links."""
        sources = load_on_reg(None, None, None)
        self.assertEqual([s.source_id for s in sources], ["nara"])
        self.assertFalse(sources[0].has_links)

    def test_available_needs_api_key(self) -> None:
        """Without a client or NARA_API_KEY the source is unavailable."""
        with patch.dict(os.environ, {"NARA_API_KEY": ""}):
            ok, reason = NaraSource().available()
        self.assertFalse(ok)
        self.assertIn("NARA_API_KEY", reason)
        with patch.dict(os.environ, {"NARA_API_KEY": "key"}):
            self.assertTrue(NaraSource().available()[0])

    def test_search_terms(self) -> None:
        """The primary query and years bound the NARA search."""
        query = RecordQuery(
            given="John", surnames=["Smith", "Jones"], birth_year=1820, death_year=1880
        )
        self.assertEqual(
            NaraSource.search_terms(query),
            (
                '"John Smith" OR "Smith John" OR "John Jones" OR "Jones John"',
                "1820",
                "1890",
            ),
        )

    def test_search_finds_maiden_name_in_title(self) -> None:
        """Mary Kreizer is found in "Mary Kreizer Smith, Widow of ..."."""
        matches = self.source.search(self.query)
        kwargs = self.client.search_records.call_args.kwargs
        self.assertEqual(kwargs["query"], '"Mary Kreizer" OR "Kreizer Mary"')
        self.assertEqual(kwargs["start_year"], "1840")
        scored = score_matches(self.query, matches)
        self.assertEqual(scored[0].match.key, "115768360")
        self.assertIn("NAID 115768360", scored[0].match.label)
        self.assertIn("hit", scored[0].match.data)
        self.assertEqual(tier_cell(scored, TIER_GS, 80).count, 1)

    def test_failed_search_is_an_error(self) -> None:
        """A failed catalog request is an error, so it is not cached."""
        self.client.search_records.return_value = None
        item = ScanItem("h", "I1", "Kreizer", "Mary", 1840, None, 0, self.query)
        self.assertEqual(scan_item(self.source, item).status, STATUS_ERROR)

    def test_nothing_to_search(self) -> None:
        """A person without names is not searched."""
        self.assertEqual(self.source.search(RecordQuery(birth_year=1900)), [])
        self.client.search_records.assert_not_called()

    def test_scan_item_ok(self) -> None:
        """scan_item wraps the search."""
        item = ScanItem("h", "I1", "Kreizer", "Mary", 1840, None, 0, self.query)
        self.assertEqual(scan_item(self.source, item).status, STATUS_OK)

    def test_open_merge_uses_saved_hit(self) -> None:
        """Open Merge passes the saved record to the NARA window."""
        match = self.source.search(self.query)[0]
        mock_launcher = Mock()
        mock_launcher.open_nara_record.return_value = True
        with patch.dict(
            "sys.modules",
            {"gramps.gui.gwizard.gwizardnaralauncher": mock_launcher},
        ):
            self.assertTrue(self.source.open_merge("dbs", "uis", "h1", match))
        args, kwargs = mock_launcher.open_nara_record.call_args
        self.assertEqual(args[:3], ("uis", "dbs", "h1"))
        self.assertEqual(args[3], match.data["hit"])
        self.assertIs(kwargs["client"], self.client)

    def test_open_merge_without_hit(self) -> None:
        """A match without record details cannot be opened."""
        match = SourceMatch("1", "x", self.source.search(self.query)[0].candidate)
        mock_dialog = Mock()
        with patch.dict(
            "sys.modules",
            {"gramps.gui.dialog": mock_dialog},
        ):
            self.assertFalse(self.source.open_merge("dbs", "uis", "h1", match))
        mock_dialog.ErrorDialog.assert_called_once()


# ------------------------------------------------------------------
#
# NaraQueryBudgetTest
#
# ------------------------------------------------------------------
class NaraQueryBudgetTest(unittest.TestCase):
    """How many catalog requests a scan sends per person."""

    def setUp(self) -> None:
        """A client that finds nothing, so every allowed query is tried."""
        self.client = Mock()
        self.client.search_records.return_value = {"body": {"hits": {"hits": []}}}
        self.client.extract_hits.side_effect = NaraCatalogInterface.extract_hits
        self.query = RecordQuery(
            given="John",
            middle="William",
            surnames=["Smith", "Jones"],
            birth_year=1880,
            death_year=1950,
            gender="male",
            places=["Boston, Suffolk, Massachusetts, USA"],
        )

    def test_one_query_per_person_by_default(self) -> None:
        """The default sends one request: the name phrases, birth surname first."""
        source = NaraSource(client=self.client)
        self.assertEqual(source.max_queries_per_person, 1)
        self.assertEqual(source.search(self.query), [])
        self.assertEqual(self.client.search_records.call_count, 1)
        kwargs = self.client.search_records.call_args.kwargs
        self.assertEqual(
            kwargs["query"],
            '"John Smith" OR "Smith John" OR "John W Smith" OR "John William Smith"'
            ' OR "John Jones" OR "Jones John" OR "John W Jones"'
            ' OR "John William Jones"',
        )
        self.assertEqual((kwargs["start_year"], kwargs["end_year"]), ("1880", "1960"))

    def test_all_queries_when_unlimited(self) -> None:
        """max_queries_per_person 0 keeps the old every-variant search."""
        source = NaraSource(client=self.client)
        source.max_queries_per_person = 0
        source.search(self.query)
        self.assertGreater(self.client.search_records.call_count, 4)

    def test_capped_queries(self) -> None:
        """A cap above one sends at most that many requests."""
        source = NaraSource(client=self.client)
        source.max_queries_per_person = 3
        source.search(self.query)
        self.assertEqual(self.client.search_records.call_count, 3)

    def test_skipped_person_sends_nothing(self) -> None:
        """People the builder skips (born after 1955) cost no request."""
        source = NaraSource(client=self.client)
        source.search(RecordQuery(given="John", surnames=["Smith"], birth_year=1990))
        self.client.search_records.assert_not_called()

    def test_primary_query_drops_nicknames_and_initials(self) -> None:
        """The single query uses the real given name, not a nickname."""

        def ind(name: str) -> dict:
            return {
                "names": [name],
                "married_surnames": {"Jones"},
                "sex": "F",
                "birth_year": 1880,
                "death_year": 1950,
                "places": ["Boston, MA"],
                "tags": set(),
            }

        self.assertEqual(
            build_primary_nara_query(ind('Mary "Molly" Ann /Smith/'))["q"],
            '"Mary Smith" OR "Smith Mary" OR "Mary A Smith" OR "Mary Ann Smith"'
            ' OR "Mary Jones" OR "Jones Mary" OR "Mary A Jones" OR "Mary Ann Jones"',
        )
        self.assertEqual(
            build_primary_nara_query(ind("Mary (Molly) /Smith/"))["q"],
            '"Mary Smith" OR "Smith Mary" OR "Mary Jones" OR "Jones Mary"',
        )
        self.assertEqual(
            build_primary_nara_query(ind("J. Robert /Smith/"))["q"],
            '"Robert Smith" OR "Smith Robert" OR "Robert Jones" OR "Jones Robert"',
        )
        self.assertIsNone(build_primary_nara_query(ind("Unknown /Smith/")))

    def test_primary_query_keeps_middle_initial(self) -> None:
        """A middle initial is asked for as written, without a full form."""
        parts = primary_name_parts(
            {
                "names": ["John W. /Smith/"],
                "married_surnames": set(),
                "sex": "M",
                "birth_year": 1880,
                "death_year": None,
                "places": [],
                "tags": set(),
            }
        )
        self.assertEqual(parts, ("John", ["W"], ["Smith"]))
        self.assertEqual(
            name_phrases("John", ["W"], "Smith"),
            ["John Smith", "Smith John", "John W Smith"],
        )

    def test_one_score_column(self) -> None:
        """NARA shows a single overall score in the Multi-Archive Record Scan."""
        self.assertEqual(NaraSource.tiers, (TIER_SCORE,))

    def test_usage_text_from_client(self) -> None:
        """The scan shows the queries used this month."""
        usage = NaraUsage(None)
        usage.record(KIND_SEARCH, 200)
        client = NaraCatalogInterface(api_key="key", usage=usage)
        text = NaraSource(client=client).usage_text()
        self.assertIn("1 of 10,000", text)


# ------------------------------------------------------------------
#
# NaraCitedKeysTest
#
# ------------------------------------------------------------------
class NaraCitedKeysTest(unittest.TestCase):
    """NaraSource.cited_keys reads the NAIDs a person already cites."""

    def setUp(self) -> None:
        from gramps.gen.db.utils import make_database

        self.db = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        self.db.close()

    def _citation(self, trans, naid: str = "") -> str:
        """Add a citation, with a NAID attribute when given."""
        from gramps.gen.lib import Citation, Source, SrcAttribute

        source = Source()
        source.set_title("National Archives record")
        self.db.add_source(source, trans)
        citation = Citation()
        citation.set_reference_handle(source.get_handle())
        if naid:
            attribute = SrcAttribute()
            attribute.set_type("NAID")
            attribute.set_value(naid)
            citation.add_attribute(attribute)
        self.db.add_citation(citation, trans)
        return citation.get_handle()

    def test_person_event_and_family_citations(self) -> None:
        """NAIDs on the person, an event and a family event are found once."""
        from gramps.gen.db.txn import DbTxn
        from gramps.gen.lib import Event, EventRef, EventType, Family, Person

        with DbTxn("setup", self.db) as trans:
            person = Person()
            person.add_citation(self._citation(trans, "111"))
            person.add_citation(self._citation(trans, "111"))
            person.add_citation(self._citation(trans))  # no NAID: not NARA's
            event = Event()
            event.set_type(EventType(EventType.MILITARY_SERV))
            event.add_citation(self._citation(trans, "222"))
            self.db.add_event(event, trans)
            ref = EventRef()
            ref.set_reference_handle(event.get_handle())
            person.add_event_ref(ref)
            self.db.add_person(person, trans)
            marriage = Event()
            marriage.set_type(EventType(EventType.MARRIAGE))
            marriage.add_citation(self._citation(trans, "333"))
            self.db.add_event(marriage, trans)
            family = Family()
            family.set_father_handle(person.get_handle())
            family_ref = EventRef()
            family_ref.set_reference_handle(marriage.get_handle())
            family.add_event_ref(family_ref)
            self.db.add_family(family, trans)
            person.add_family_handle(family.get_handle())
            self.db.commit_person(person, trans)

        person = self.db.get_person_from_handle(person.get_handle())
        self.assertEqual(
            NaraSource().cited_keys(self.db, person), ["111", "222", "333"]
        )

    def test_nothing_cited(self) -> None:
        """A person without NARA citations cites nothing."""
        from gramps.gen.db.txn import DbTxn
        from gramps.gen.lib import Person

        with DbTxn("setup", self.db) as trans:
            person = Person()
            self.db.add_person(person, trans)
        self.assertEqual(NaraSource().cited_keys(self.db, person), [])

    def test_searched_by_default(self) -> None:
        """People who cite NARA are still searched unless skip_cited is set."""
        self.assertFalse(NaraSource.skip_cited)


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------------------
#
# NaraScanBudgetTest
#
# ------------------------------------------------------------------
class NaraScanBudgetTest(unittest.TestCase):
    """Who a scan searches on NARA, and how many queries it may use."""

    def setUp(self) -> None:
        """A source counting into an in-memory usage counter."""
        self.client = Mock()
        self.client.usage = NaraUsage(None, limit=1000)
        self.source = NaraSource(client=self.client)

    def test_scan_limits(self) -> None:
        """At most 50 people per click, with 500 queries kept back."""
        self.assertEqual(self.source.max_searches_per_scan, 50)
        self.assertEqual(self.source.reserve_requests, 500)

    def test_wants_search(self) -> None:
        """A scan skips people NARA could not tell apart or has no records for."""
        wants = self.source.wants_search
        self.assertTrue(
            wants(RecordQuery(given="John", surnames=["Smith"], birth_year=1880))
        )
        self.assertTrue(
            wants(RecordQuery(given="John", surnames=["Smith"], death_year=1900))
        )
        # No years: the search would have no date range.
        self.assertFalse(wants(RecordQuery(given="John", surnames=["Smith"])))
        # Life over before the catalog's records start.
        self.assertFalse(
            wants(RecordQuery(given="John", surnames=["Smith"], death_year=1760))
        )
        self.assertFalse(
            wants(RecordQuery(given="John", surnames=["Smith"], birth_year=1650))
        )
        self.assertTrue(
            wants(RecordQuery(given="John", surnames=["Smith"], birth_year=1700))
        )
        # Born after 1955 (the builder skips them).
        self.assertFalse(
            wants(RecordQuery(given="John", surnames=["Smith"], birth_year=1990))
        )
        # No US events among the places.
        self.assertFalse(
            wants(
                RecordQuery(
                    given="John",
                    surnames=["Smith"],
                    birth_year=1880,
                    places=["Genova, Liguria, Italia"],
                )
            )
        )

    def test_requests_left(self) -> None:
        """The allowance left, less the reserve; none once NARA refused."""
        usage = self.client.usage
        self.assertEqual(self.source.requests_left(), 500)
        for _number in range(450):
            usage.record("search", 200)
        self.assertEqual(self.source.requests_left(), 50)
        for _number in range(100):
            usage.record("search", 200)
        self.assertEqual(self.source.requests_left(), 0)
        fresh = NaraUsage(None, limit=1000)
        self.client.usage = fresh
        fresh.record("search", 429)
        self.assertEqual(self.source.requests_left(), 0)

    def test_scanner_stops_at_the_reserve(self) -> None:
        """A scan stops searching NARA once only the reserve is left."""
        self.client.search_records.return_value = {"body": {"hits": {"hits": []}}}
        self.client.extract_hits.side_effect = NaraCatalogInterface.extract_hits
        usage = self.client.usage

        def counted(**_kwargs: Any) -> dict:
            usage.record("search", 200)
            return {"body": {"hits": {"hits": []}}}

        self.client.search_records.side_effect = counted
        for _number in range(498):
            usage.record("search", 200)
        query = RecordQuery(given="John", surnames=["Smith"], birth_year=1880)
        items = [
            ScanItem(f"h{n}", f"I{n}", "Smith", "John", 1880, None, 0, query)
            for n in range(5)
        ]
        scanner = RecordScanner()
        scanner.run([self.source], items, lambda *_args: None)
        self.assertEqual(self.client.search_records.call_count, 2)
        self.assertEqual(scanner.deferred, {"nara": 3})
        self.assertEqual(scanner.stopped, {"nara": STOP_ALLOWANCE})
