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
Unit tests for the GWizard Citation Improvement Scan engine
(gwizardcitescanengine) and the NARA citation adapter (gwizardnaracitesource).
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
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.gwizard.gwizard_base import RecordCandidate, RecordQuery
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    STATUS_OK,
    PersonScan,
    RecordSource,
    SourceMatch,
)
from gramps.gen.lib import (
    Attribute,
    Citation,
    Date,
    Event,
    EventRef,
    EventType,
    Family,
    Media,
    MediaRef,
    Name,
    Note,
    Person,
    RepoRef,
    Repository,
    Source,
    Surname,
)
from gramps.plugins.tool.gwizardcitescanengine import (
    CITED_CONFIDENCE,
    NO_DATE,
    NO_MEDIA,
    NO_PAGE,
    NO_SOURCE,
    NOT_USED,
    RECORD_NO_MEDIA,
    SOURCE_NO_REPO,
    SOURCE_NOT_TITLE,
    SOURCE_PLACEHOLDER,
    SOURCE_TREE,
    CitationItem,
    CitationSource,
    GenericCitationSource,
    build_citation_items,
    confidence,
    discover_citation_sources,
    match_citation,
    people_to_search,
    text_relevance,
    work_band,
)
from gramps.plugins.tool.gwizardnaracitesource import NaraCitationSource


def _person(db: Any, trans: DbTxn, given: str, surname: str) -> Person:
    """Add a person."""
    person = Person()
    name = Name()
    name.set_first_name(given)
    surn = Surname()
    surn.set_surname(surname)
    name.add_surname(surn)
    person.set_primary_name(name)
    person.set_gender(Person.MALE)
    db.add_person(person, trans)
    return person


def _source(db: Any, trans: DbTxn, title: str, repo: Repository | None) -> Source:
    """Add a source, held by ``repo`` when given."""
    source = Source()
    source.set_title(title)
    source.set_author("Census Office")
    if repo is not None:
        ref = RepoRef()
        ref.set_reference_handle(repo.get_handle())
        source.add_repo_reference(ref)
    db.add_source(source, trans)
    return source


def _citation(
    db: Any,
    trans: DbTxn,
    source: Source | None,
    page: str = "",
    year: int = 0,
    naid: str = "",
) -> Citation:
    """Add a citation."""
    citation = Citation()
    if source is not None:
        citation.set_reference_handle(source.get_handle())
    citation.set_page(page)
    if year:
        date = Date()
        date.set_yr_mon_day(year, 0, 0)
        citation.set_date_object(date)
    if naid:
        attribute = Attribute()
        attribute.set_type("NAID")
        attribute.set_value(naid)
        citation.add_attribute(attribute)
    db.add_citation(citation, trans)
    return citation


def _match(key: str, label: str, given: str, surname: str, birth: int) -> SourceMatch:
    """Return a record found for a person."""
    return SourceMatch(
        key=key,
        label=label,
        candidate=RecordCandidate(
            given=given, surnames=[surname], birth_years=(birth, birth)
        ),
    )


class _Source(RecordSource):
    """A record source stand-in."""

    source_id = "nara"
    title = "NARA"

    def search(self, query: RecordQuery) -> list[SourceMatch]:
        """Never called here."""
        return []


# ------------------------------------------------------------
#
# Reading citations
#
# ------------------------------------------------------------
class CitationChecksTest(unittest.TestCase):
    """Checks, people and the work score on a small tree."""

    def setUp(self) -> None:
        """
        A tree with John Smith and Mary Jones (a couple), and citations:

        good    a census citation with page, date, image and note, on John
        poor    no page, no date, no image, source is a web address, on John
        event   cites John's birth event only (no page)
        family  cites the couple's marriage
        orphan  cited by nothing, no source at all
        nara    a NARA citation (NAID) with no image, on Mary
        """
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.c: dict[str, str] = {}
        with DbTxn("tree", self.db) as trans:
            repo = Repository()
            repo.set_name("National Archives")
            self.db.add_repository(repo, trans)
            census = _source(self.db, trans, "1900 United States Census", repo)
            web = _source(self.db, trans, "https://example.com/record/1", None)
            tree = _source(self.db, trans, "Ancestry Member Trees", repo)
            nara = _source(self.db, trans, "Pension Files", repo)

            note = Note()
            note.set("Transcription: John Smith, head, age 30.")
            self.db.add_note(note, trans)
            media = Media()
            media.set_path("https://example.com/census.jpg")
            self.db.add_media(media, trans)

            good = _citation(
                self.db, trans, census, "Sheet 4A, line 12, entry for John Smith", 1900
            )
            ref = MediaRef()
            ref.set_reference_handle(media.get_handle())
            good.add_media_reference(ref)
            good.add_note(note.get_handle())
            good.set_confidence_level(Citation.CONF_HIGH)
            self.db.commit_citation(good, trans)
            poor = _citation(self.db, trans, web)
            poor.set_confidence_level(Citation.CONF_VERY_LOW)
            self.db.commit_citation(poor, trans)
            event_cit = _citation(self.db, trans, census, "", 1901)
            family_cit = _citation(self.db, trans, tree, "Smith family", 1925)
            orphan = _citation(self.db, trans, None)
            nara_cit = _citation(
                self.db, trans, nara, "Pension file of Mary Jones", 1930, "123456"
            )

            self.john = _person(self.db, trans, "John", "Smith")
            self.mary = _person(self.db, trans, "Mary", "Jones")
            self.john.add_citation(good.get_handle())
            self.john.add_citation(poor.get_handle())
            self.mary.add_citation(nara_cit.get_handle())
            birth = Event()
            birth.set_type(EventType.BIRTH)
            birth.add_citation(event_cit.get_handle())
            self.db.add_event(birth, trans)
            eref = EventRef()
            eref.set_reference_handle(birth.get_handle())
            self.john.add_event_ref(eref)
            self.db.commit_person(self.john, trans)
            self.db.commit_person(self.mary, trans)

            family = Family()
            family.set_father_handle(self.john.get_handle())
            family.set_mother_handle(self.mary.get_handle())
            marriage = Event()
            marriage.set_type(EventType.MARRIAGE)
            marriage.add_citation(family_cit.get_handle())
            self.db.add_event(marriage, trans)
            fref = EventRef()
            fref.set_reference_handle(marriage.get_handle())
            family.add_event_ref(fref)
            self.db.add_family(family, trans)

            for key, cit in (
                ("good", good),
                ("poor", poor),
                ("event", event_cit),
                ("family", family_cit),
                ("orphan", orphan),
                ("nara", nara_cit),
            ):
                self.c[key] = cit.get_handle()
        self.adapters = {"nara": NaraCitationSource()}
        self.items = {
            item.handle: item
            for item in build_citation_items(self.db, adapters=self.adapters)
        }

    def tearDown(self) -> None:
        """Close the tree."""
        self.db.close()

    def _codes(self, key: str) -> set[str]:
        """Return the issue codes of a citation."""
        return {issue.code for issue in self.items[self.c[key]].issues}

    def test_good_citation_needs_little(self) -> None:
        """A complete citation has little work; only the web-only image."""
        item = self.items[self.c["good"]]
        self.assertLess(item.work, 15)
        self.assertEqual(work_band(item.work), "none")
        self.assertEqual(item.person_text(), "Smith, John")

    def test_poor_citation(self) -> None:
        """Missing page, date and image, a web address as title, no repo."""
        codes = self._codes("poor")
        for code in (NO_PAGE, NO_DATE, NO_MEDIA, SOURCE_NOT_TITLE, SOURCE_NO_REPO):
            self.assertIn(code, codes)
        self.assertGreaterEqual(self.items[self.c["poor"]].work, 60)

    def test_worst_first(self) -> None:
        """build_citation_items lists the most work first."""
        works = [
            item.work for item in build_citation_items(self.db, adapters=self.adapters)
        ]
        self.assertEqual(works, sorted(works, reverse=True))

    def test_people_through_events_and_families(self) -> None:
        """Event citations find the person; family ones find both parents."""
        self.assertEqual(
            [h for h, _n in self.items[self.c["event"]].people],
            [self.john.get_handle()],
        )
        self.assertEqual(
            [h for h, _n in self.items[self.c["family"]].people],
            [self.john.get_handle(), self.mary.get_handle()],
        )
        self.assertEqual(self.items[self.c["family"]].person_text(), "Smith, John (+1)")
        self.assertIn(SOURCE_TREE, self._codes("family"))

    def test_orphan(self) -> None:
        """A citation nothing uses, with no source."""
        codes = self._codes("orphan")
        self.assertIn(NOT_USED, codes)
        self.assertIn(NO_SOURCE, codes)
        self.assertEqual(self.items[self.c["orphan"]].person_handle, "")

    def test_nara_adapter(self) -> None:
        """The NAID is read; a NARA citation without images says so."""
        item = self.items[self.c["nara"]]
        self.assertEqual(item.record_keys, {"nara": ["123456"]})
        codes = self._codes("nara")
        self.assertIn(RECORD_NO_MEDIA, codes)
        self.assertNotIn(NO_MEDIA, codes)
        self.assertIn("123456", item.issue_summary())

    def test_placeholder_title(self) -> None:
        """A placeholder source title is flagged."""
        with DbTxn("placeholder", self.db) as trans:
            source = _source(self.db, trans, "Unknown", None)
            citation = _citation(self.db, trans, source, "p. 1", 1900)
            self.john.add_citation(citation.get_handle())
            self.db.commit_person(self.john, trans)
        items = build_citation_items(self.db, [citation.get_handle()])
        self.assertIn(SOURCE_PLACEHOLDER, {i.code for i in items[0].issues})


# ------------------------------------------------------------
#
# Confidence and planning
#
# ------------------------------------------------------------
class ConfidenceTest(unittest.TestCase):
    """Relevance, confidence and match_citation, without a tree."""

    def setUp(self) -> None:
        """A census citation for John Smith, 1900."""
        self.item = CitationItem(
            handle="c1",
            gramps_id="C0001",
            source_title="1900 United States Census",
            page="Sheet 4A, Kent County",
            year=1900,
            people=[("p1", "Smith, John")],
        )
        self.query = RecordQuery(given="John", surnames=["Smith"], birth_year=1870)

    def test_text_relevance(self) -> None:
        """Shared words and a year in range raise it; a far year lowers it."""
        self.assertGreater(
            text_relevance(self.item, "Census of Kent County 1900", [1900]), 0.5
        )
        self.assertLess(text_relevance(self.item, "Pension file", [1950, 1955]), 0)
        self.assertEqual(text_relevance(self.item, "Something else"), 0.0)

    def test_confidence_bounds(self) -> None:
        """Confidence is the person score moved by the fit, within 0..100."""
        self.assertEqual(confidence(90, 1), 100.0)
        self.assertEqual(confidence(80, -1), 65.0)
        self.assertEqual(confidence(5, -1), 0.0)

    def test_match_citation(self) -> None:
        """
        Cited records come first at 100; records the person cites elsewhere
        are dropped; poor matches below the minimum are dropped.
        """
        self.item.record_keys = {"nara": ["N1"]}
        scan = PersonScan(
            "nara",
            "p1",
            STATUS_OK,
            matches=[
                _match("N2", "Kent County census 1900", "John", "Smith", 1870),
                _match("N1", "Cited record", "John", "Smith", 1870),
                _match("N3", "Already cited elsewhere", "John", "Smith", 1870),
                _match("N4", "Pension 1950", "Peter", "Brown", 1820),
            ],
        )
        judged = match_citation(
            self.item, scan, self.query, GenericCitationSource("nara"), ["N1", "N3"]
        )
        self.assertEqual([m.match.key for m in judged], ["N1", "N2"])
        self.assertTrue(judged[0].cited)
        self.assertEqual(judged[0].confidence, CITED_CONFIDENCE)
        self.assertGreater(judged[1].confidence, 90)
        self.assertIn("%", judged[1].label())

    def test_people_to_search_budget(self) -> None:
        """
        Worst citations first; low-work citations and repeat people are
        skipped; saved people are free; new people stop at the limit.
        """
        items = [
            CitationItem("a", "C1", people=[("p1", "A")]),
            CitationItem("b", "C2", people=[("p2", "B")]),
            CitationItem("c", "C3", people=[("p1", "A")]),
            CitationItem("d", "C4", people=[("p3", "C")]),
            CitationItem("e", "C5", people=[("p4", "D")]),
            CitationItem("f", "C6"),
        ]
        from gramps.plugins.tool.gwizardcitescanengine import Issue

        for item, work in zip(items, (90, 80, 70, 60, 5, 90)):
            item.issues = [Issue("x", "x", "citation", work)]
        handles, skipped = people_to_search(items, 20, 1, lambda h: h == "p2")
        self.assertEqual(handles, ["p1", "p2"])
        self.assertEqual(skipped, 1)  # p3; p4 needs too little work
        handles, skipped = people_to_search(items, 20, 0, lambda h: False)
        self.assertEqual(handles, ["p1", "p2", "p3"])
        self.assertEqual(skipped, 0)

    def test_discover_falls_back_to_generic(self) -> None:
        """A record source with no registered adapter gets a generic one."""

        class Manager:
            def get_reg_general(self, category: str) -> list[Any]:
                class PData:
                    id = "x"
                    data = [NaraCitationSource()]

                return [PData()]

        class Other(_Source):
            source_id = "wikitree"

        found = discover_citation_sources([_Source(), Other()], Manager())
        self.assertIsInstance(found["nara"], NaraCitationSource)
        self.assertIsInstance(found["wikitree"], GenericCitationSource)
        self.assertIsInstance(found["wikitree"], CitationSource)

    def test_nara_relevance_uses_record_dates(self) -> None:
        """NARA judges a record by its title and date range."""
        hit = {
            "_source": {
                "record": {
                    "naId": 99,
                    "title": "Kent County census schedules",
                    "coverageStartDate": {"year": 1900},
                    "coverageEndDate": {"year": 1900},
                }
            }
        }
        match = SourceMatch("99", "x", RecordCandidate(), data={"hit": hit})
        fit = NaraCitationSource().relevance(self.item, match)
        self.assertGreater(fit, 0)


# ------------------------------------------------------------
#
# NaraCatalogInterface.fetch_record
#
# ------------------------------------------------------------
class FetchRecordTest(unittest.TestCase):
    """Fetching one NARA record by its NAID (used to open a cited record)."""

    def test_fetch_record(self) -> None:
        """The hit with the asked NAID is returned; failures give None."""
        from unittest import mock

        from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface
        from gramps.gen.gwizard.gwizardnarausage import NaraUsage

        class Response:
            status_code = 200
            headers: dict[str, str] = {}

            def json(self) -> dict[str, Any]:
                return {
                    "body": {
                        "hits": {
                            "hits": [
                                {"_source": {"record": {"naId": 1, "title": "A"}}},
                                {"_source": {"record": {"naId": 2, "title": "B"}}},
                            ]
                        }
                    }
                }

        usage = mock.MagicMock(spec=NaraUsage)
        client = NaraCatalogInterface(api_key="k", usage=usage)
        with mock.patch(
            "gramps.gen.gwizard.gwizardnaramerge.requests.get",
            return_value=Response(),
        ) as get:
            hit = client.fetch_record("2")
        assert hit is not None
        self.assertEqual(NaraCatalogInterface.parse_record(hit)["title"], "B")
        self.assertEqual(get.call_args.kwargs["params"], {"naId": "2"})
        usage.record.assert_called_once()
        failed = Response()
        failed.status_code = 500
        with mock.patch(
            "gramps.gen.gwizard.gwizardnaramerge.requests.get", return_value=failed
        ):
            self.assertIsNone(client.fetch_record("2"))


if __name__ == "__main__":
    unittest.main()
