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

"""Unit tests for WikiTree as a GWizard Multi-Archive Record Scan source."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import unittest
from unittest.mock import Mock, patch

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.gwizard.gwizard_base import (
    TIER_GMSB,
    TIER_GMSB_BOTH_PARENTS,
    TIER_GMSB_ONE_PARENT,
    TIER_GS,
    TIER_GSB,
    RecordQuery,
)
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    STATUS_ERROR,
    STATUS_LINKED,
    ScanItem,
    scan_item,
    score_matches,
    tier_cell,
)
from gramps.gen.gwizard.gwizardwikitree import WikiTreeInterface
from gramps.gen.lib import Attribute, AttributeType, Person
from gramps.plugins.tool.gwizardwikitreesource import WikiTreeSource, load_on_reg

FRANKLIN = {
    "Id": 388,
    "Name": "Franklin-1",
    "FirstName": "Benjamin",
    "LastNameAtBirth": "Franklin",
    "LongName": "Benjamin Franklin",
    "BirthDate": "1706-01-17",
    "DeathDate": "1790-04-17",
    "Gender": "Male",
}


# ------------------------------------------------------------------
#
# WikiTreeSourceTest
#
# ------------------------------------------------------------------
class WikiTreeSourceTest(unittest.TestCase):
    """Searching, looking up and opening merges through WikiTreeSource."""

    def setUp(self) -> None:
        """A source on a mock WikiTree client."""
        self.client = Mock()
        self.client.search_person.return_value = [FRANKLIN, {"Name": ""}]
        self.client.get_person.return_value = FRANKLIN
        self.source = WikiTreeSource(client=self.client)
        self.query = RecordQuery(
            given="Benjamin", surnames=["Franklin", "Read"], birth_year=1706
        )

    def test_load_on_reg_offers_wikitree(self) -> None:
        """The plugin offers one WikiTree source."""
        sources = load_on_reg(None, None, None)
        self.assertEqual([s.source_id for s in sources], ["wikitree"])
        self.assertTrue(sources[0].has_links)

    def _first_names(self) -> list[tuple[str, str]]:
        """(first_name, birth_date) of each search made."""
        return [
            (c.kwargs["first_name"], c.kwargs["birth_date"])
            for c in self.client.search_person.call_args_list
        ]

    def test_dated_hit_skips_names_only_search(self) -> None:
        """A dated search that finds profiles is the only search made."""
        matches = self.source.search(self.query)
        self.assertEqual(self._first_names(), [("Benjamin", "1706")])
        (first,) = self.client.search_person.call_args_list
        self.assertEqual(first.kwargs["last_name"], "Franklin")
        self.assertEqual(first.kwargs["date_spread"], 2)
        self.assertTrue(first.kwargs["raise_errors"])
        self.assertIn("MiddleName", first.kwargs["fields"])
        self.assertEqual([m.key for m in matches], ["Franklin-1"])
        self.assertEqual(matches[0].label, "Benjamin Franklin (1706–1790) [Franklin-1]")
        self.assertEqual(matches[0].url, "https://www.wikitree.com/wiki/Franklin-1")

    def test_names_only_search_when_dated_searches_find_nobody(self) -> None:
        """
        When no dated search finds anyone, the names-only search is made
        last, and can find profiles born a few years away or with no birth
        date; namesakes born far away are dropped.
        """
        near = dict(FRANKLIN, Name="Franklin-9", BirthDate="1712-01-01")
        undated = dict(FRANKLIN, Name="Franklin-12", BirthDate="0000-00-00")
        far = dict(FRANKLIN, Name="Franklin-30", BirthDate="1650-01-01")

        def search_person(**kwargs: object) -> list[dict[str, object]]:
            return [] if kwargs["birth_date"] else [FRANKLIN, near, undated, far]

        self.client.search_person.side_effect = search_person
        scored = score_matches(self.query, self.source.search(self.query))
        last = self.client.search_person.call_args_list[-1]
        self.assertEqual(last.kwargs["birth_date"], "")
        self.assertEqual(last.kwargs["date_spread"], 0)
        self.assertEqual(
            {s.match.key for s in scored}, {"Franklin-1", "Franklin-9", "Franklin-12"}
        )
        self.assertEqual(tier_cell(scored, TIER_GS, 80).count, 3)
        self.assertEqual(tier_cell(scored, TIER_GSB, 80).count, 1)

    def test_death_year_searched_before_names_only(self) -> None:
        """With a death year, a death-dated search comes before names only."""
        query = RecordQuery(
            given="Benjamin", surnames=["Franklin"], birth_year=1706, death_year=1790
        )

        def search_person(**kwargs: object) -> list[dict[str, object]]:
            return [FRANKLIN] if kwargs.get("death_date") else []

        self.client.search_person.side_effect = search_person
        matches = self.source.search(query)
        self.assertEqual([m.key for m in matches], ["Franklin-1"])
        last = self.client.search_person.call_args_list[-1]
        self.assertEqual(last.kwargs["death_date"], "1790")
        self.assertEqual(last.kwargs["birth_date"], "")
        self.assertEqual(last.kwargs["date_spread"], 2)

    def test_death_year_without_birth_year(self) -> None:
        """A person with only a death year is searched by it first."""
        query = RecordQuery(given="Benjamin", surnames=["Franklin"], death_year=1790)
        self.source.search(query)
        (first,) = self.client.search_person.call_args_list
        self.assertEqual(first.kwargs["death_date"], "1790")
        self.assertEqual(first.kwargs["date_spread"], 2)

    def test_no_birth_year_one_search(self) -> None:
        """Without a birth year only the names-only search is made."""
        query = RecordQuery(given="Benjamin", surnames=["Franklin"])
        self.source.search(query)
        self.assertEqual(self._first_names(), [("Benjamin", "")])

    def test_middle_name_tried_first(self) -> None:
        """ "Given Middle" is tried, then "Given"; a dated hit ends the search."""
        query = RecordQuery(
            given="Benjamin", middle="Lee", surnames=["Franklin"], birth_year=1706
        )
        self.client.search_person.side_effect = [[], [FRANKLIN]]
        self.source.search(query)
        self.assertEqual(
            self._first_names(),
            [("Benjamin Lee", "1706"), ("Benjamin", "1706")],
        )

    def test_middle_name_hit_skips_first_name_retry(self) -> None:
        """When "Given Middle" finds profiles, the dated retry is skipped."""
        query = RecordQuery(
            given="Benjamin", middle="Lee", surnames=["Franklin"], birth_year=1706
        )
        self.source.search(query)
        self.assertEqual(self._first_names(), [("Benjamin Lee", "1706")])

    def test_middle_initial_counts_as_middle(self) -> None:
        """A profile with only MiddleInitial can be judged at g/m/s/b."""
        profile = dict(FRANKLIN, MiddleInitial="L")
        query = RecordQuery(
            given="Benjamin", middle="Lee", surnames=["Franklin"], birth_year=1706
        )
        scored = score_matches(query, [self.source.to_match(profile)])
        self.assertEqual(tier_cell(scored, TIER_GMSB, 80).count, 1)

    def test_matches_score_at_every_tier(self) -> None:
        """A WikiTree profile scores through the shared scoring."""
        scored = score_matches(self.query, self.source.search(self.query))
        self.assertEqual(tier_cell(scored, TIER_GSB, 80).count, 1)

    def test_linked_person_is_looked_up(self) -> None:
        """A person with a WikiTree ID is looked up, not searched."""
        person = Person()
        attr = Attribute()
        attr.set_type(AttributeType("WikiTree ID"))
        attr.set_value("Franklin-1")
        person.add_attribute(attr)
        self.assertEqual(self.source.linked_key(None, person), "Franklin-1")
        item = ScanItem(
            "h",
            "I1",
            "Franklin",
            "Benjamin",
            1706,
            None,
            0,
            self.query,
            {"wikitree": "Franklin-1"},
        )
        scan = scan_item(self.source, item)
        self.assertEqual(scan.status, STATUS_LINKED)
        self.client.get_person.assert_called_once_with("Franklin-1", raise_errors=True)
        self.client.search_person.assert_not_called()

    def test_failed_search_is_an_error(self) -> None:
        """A failed request is reported as an error (and so not cached)."""
        self.client.search_person.side_effect = RuntimeError("HTTP 503")
        item = ScanItem("h", "I1", "Franklin", "Benjamin", 1706, None, 0, self.query)
        scan = scan_item(self.source, item)
        self.assertEqual(scan.status, STATUS_ERROR)
        self.assertIn("503", scan.error)

    def test_open_merge_uses_launcher(self) -> None:
        """Open Merge loads the profile into the WikiTree merge window."""
        match = self.source.to_match(FRANKLIN)
        with patch(
            "gramps.gui.gwizard.gwizardwikitreelauncher.merge_wikitree_profile",
            return_value=(True, "done"),
        ) as merge:
            changed = self.source.open_merge("dbstate", None, "h1", match, parent=None)
        self.assertTrue(changed)
        args, kwargs = merge.call_args
        self.assertEqual(args, ("dbstate", "Franklin-1", "h1"))
        self.assertIs(kwargs["client"], self.client)


# ------------------------------------------------------------------
#
# WikiTreeRaiseErrorsTest
#
# ------------------------------------------------------------------
class WikiTreeRaiseErrorsTest(unittest.TestCase):
    """WikiTreeInterface reports failures only when asked to."""

    @patch("requests.get")
    def test_raise_errors(self, mock_get: Mock) -> None:
        """HTTP errors raise with raise_errors and return empty without."""
        mock_get.return_value = Mock(status_code=503)
        client = WikiTreeInterface()
        self.assertEqual(client.search_person(last_name="Franklin"), [])
        self.assertIsNone(client.get_person("Franklin-1"))
        with self.assertRaises(RuntimeError):
            client.search_person(last_name="Franklin", raise_errors=True)
        with self.assertRaises(RuntimeError):
            client.get_person("Franklin-1", raise_errors=True)


# ------------------------------------------------------------------
#
# WikiTreeParentsTest
#
# ------------------------------------------------------------------
class WikiTreeParentsTest(unittest.TestCase):
    """The parent score columns and reading parents' names."""

    PETER = {
        "Id": 501,
        "Name": "Smith-501",
        "FirstName": "Peter",
        "MiddleName": "James",
        "LastNameAtBirth": "Smith",
        "BirthDate": "1850-03-01",
        "Gender": "Male",
        "Father": 601,
        "Mother": 602,
    }

    def setUp(self) -> None:
        self.client = Mock()
        self.source = WikiTreeSource(client=self.client)
        self.query = RecordQuery(
            given="Peter",
            middle="James",
            surnames=["Smith"],
            birth_year=1850,
            gender="male",
            father_first_name="John",
            mother_first_name="Mary Ann",
        )

    def test_parent_columns_first(self) -> None:
        """WikiTree shows both-parents, then either-parent, then the usual levels."""
        self.assertEqual(
            WikiTreeSource.tiers,
            (
                TIER_GMSB_BOTH_PARENTS,
                TIER_GMSB_ONE_PARENT,
                TIER_GMSB,
                TIER_GSB,
                TIER_GS,
            ),
        )

    def test_parents_asked_for_in_search(self) -> None:
        """The search asks WikiTree for parent Ids and profiles."""
        self.client.search_person.return_value = []
        self.source.search(self.query)
        fields = self.client.search_person.call_args.kwargs["fields"]
        for field in ("Father", "Mother", "Parents"):
            self.assertIn(field, fields.split(","))

    def test_parents_in_search_result_need_no_lookup(self) -> None:
        """Parents included in the result are used directly."""
        peter = dict(
            self.PETER,
            Parents={
                "601": {"Id": 601, "FirstName": "John"},
                "602": {"Id": 602, "FirstName": "Mary"},
            },
        )
        self.client.search_person.return_value = [peter]
        (match,) = self.source.search(self.query)
        self.client.get_people.assert_not_called()
        self.assertEqual(match.candidate.father_given, "John")
        self.assertEqual(match.candidate.mother_given, "Mary")
        scored = score_matches(self.query, [match], WikiTreeSource.tiers)
        self.assertEqual(tier_cell(scored, TIER_GMSB_BOTH_PARENTS, 80).count, 1)
        self.assertEqual(tier_cell(scored, TIER_GMSB_ONE_PARENT, 80).count, 1)

    def test_missing_parents_looked_up_once(self) -> None:
        """Parents given only by Id are read with one getPeople request."""
        other = dict(self.PETER, Id=502, Name="Smith-502", Father=601, Mother=0)
        self.client.search_person.return_value = [dict(self.PETER), other]
        self.client.get_people.return_value = {
            "601": {"Id": 601, "FirstName": "John", "Gender": "Male"},
            "602": {"Id": 602, "FirstName": "Mary", "Gender": "Female"},
        }
        matches = {m.key: m for m in self.source.search(self.query)}
        self.client.get_people.assert_called_once()
        self.assertEqual(self.client.get_people.call_args.args[0], ["601", "602"])
        peter = matches["Smith-501"].candidate
        self.assertEqual((peter.father_given, peter.mother_given), ("John", "Mary"))
        lone = matches["Smith-502"].candidate
        self.assertEqual((lone.father_given, lone.mother_given), ("John", ""))
        scored = {
            s.match.key: s
            for s in score_matches(self.query, matches.values(), WikiTreeSource.tiers)
        }
        self.assertIsNone(scored["Smith-502"].tiers[TIER_GMSB_BOTH_PARENTS])
        self.assertIsNotNone(scored["Smith-502"].tiers[TIER_GMSB_ONE_PARENT])

    def test_failed_lookup_leaves_parents_out(self) -> None:
        """When the parents cannot be read, the search still returns matches."""
        self.client.search_person.return_value = [dict(self.PETER)]
        self.client.get_people.side_effect = RuntimeError("down")
        (match,) = self.source.search(self.query)
        self.assertEqual(match.candidate.father_given, "")

    def test_linked_lookup_reads_parents(self) -> None:
        """A linked profile gets its parents' names too."""
        self.client.get_person.return_value = dict(self.PETER)
        self.client.get_people.return_value = {
            "601": {"Id": 601, "FirstName": "John"},
        }
        match = self.source.lookup("Smith-501")
        assert match is not None
        self.assertEqual(match.candidate.father_given, "John")


if __name__ == "__main__":
    unittest.main()
