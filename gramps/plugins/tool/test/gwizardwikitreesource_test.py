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

"""Unit tests for WikiTree as a GWizard Record Scan source."""

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
from gramps.gen.gwizard.gwizard_base import TIER_GMSB, TIER_GS, TIER_GSB, RecordQuery
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

    def test_search_with_and_without_birth_year(self) -> None:
        """A dated search and a names-only search; results combined once."""
        matches = self.source.search(self.query)
        self.assertEqual(self._first_names(), [("Benjamin", "1706"), ("Benjamin", "")])
        first, second = self.client.search_person.call_args_list
        self.assertEqual(first.kwargs["last_name"], "Franklin")
        self.assertEqual(first.kwargs["date_spread"], 2)
        self.assertEqual(second.kwargs["date_spread"], 0)
        self.assertTrue(first.kwargs["raise_errors"])
        self.assertIn("MiddleName", first.kwargs["fields"])
        self.assertEqual([m.key for m in matches], ["Franklin-1"])
        self.assertEqual(matches[0].label, "Benjamin Franklin (1706–1790) [Franklin-1]")
        self.assertEqual(matches[0].url, "https://www.wikitree.com/wiki/Franklin-1")

    def test_other_birth_year_still_found(self) -> None:
        """A name match born years away comes from the names-only search."""
        other = dict(FRANKLIN, Name="Franklin-9", BirthDate="1650-01-01")
        self.client.search_person.side_effect = [[FRANKLIN], [FRANKLIN, other]]
        scored = score_matches(self.query, self.source.search(self.query))
        self.assertEqual({s.match.key for s in scored}, {"Franklin-1", "Franklin-9"})
        self.assertEqual(tier_cell(scored, TIER_GS, 80).count, 2)
        self.assertEqual(tier_cell(scored, TIER_GSB, 80).count, 1)

    def test_no_birth_year_one_search(self) -> None:
        """Without a birth year only the names-only search is made."""
        query = RecordQuery(given="Benjamin", surnames=["Franklin"])
        self.source.search(query)
        self.assertEqual(self._first_names(), [("Benjamin", "")])

    def test_middle_name_tried_first(self) -> None:
        """ "Given Middle" is tried, then "Given", then names only."""
        query = RecordQuery(
            given="Benjamin", middle="Lee", surnames=["Franklin"], birth_year=1706
        )
        self.client.search_person.side_effect = [[], [FRANKLIN], []]
        self.source.search(query)
        self.assertEqual(
            self._first_names(),
            [("Benjamin Lee", "1706"), ("Benjamin", "1706"), ("Benjamin", "")],
        )

    def test_middle_name_hit_skips_first_name_retry(self) -> None:
        """When "Given Middle" finds profiles, the dated retry is skipped."""
        query = RecordQuery(
            given="Benjamin", middle="Lee", surnames=["Franklin"], birth_year=1706
        )
        self.source.search(query)
        self.assertEqual(
            self._first_names(), [("Benjamin Lee", "1706"), ("Benjamin", "")]
        )

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


if __name__ == "__main__":
    unittest.main()
