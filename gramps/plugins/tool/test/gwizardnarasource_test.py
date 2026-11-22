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

"""Unit tests for the NARA catalog as a GWizard Record Scan source."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import json
import os
import unittest
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
    ScanItem,
    SourceMatch,
    scan_item,
    score_matches,
    tier_cell,
)
from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface
from gramps.plugins.tool.gwizardnarasource import NaraSource, load_on_reg

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
        """Keywords are the given name and birth surname; years bound records."""
        query = RecordQuery(
            given="John", surnames=["Smith", "Jones"], birth_year=1820, death_year=1880
        )
        self.assertEqual(NaraSource.search_terms(query), ("John Smith", "1820", "1890"))

    def test_search_finds_maiden_name_in_title(self) -> None:
        """Mary Kreizer is found in "Mary Kreizer Smith, Widow of ..."."""
        matches = self.source.search(self.query)
        kwargs = self.client.search_records.call_args.kwargs
        self.assertEqual(kwargs["query"], "Mary Kreizer")
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
        with patch(
            "gramps.gui.gwizard.gwizardnaralauncher.open_nara_record",
            return_value=True,
        ) as opener:
            self.assertTrue(self.source.open_merge("dbs", "uis", "h1", match))
        args, kwargs = opener.call_args
        self.assertEqual(args[:3], ("uis", "dbs", "h1"))
        self.assertEqual(args[3], match.data["hit"])
        self.assertIs(kwargs["client"], self.client)

    def test_open_merge_without_hit(self) -> None:
        """A match without record details cannot be opened."""
        match = SourceMatch("1", "x", self.source.search(self.query)[0].candidate)
        with patch("gramps.gui.dialog.ErrorDialog") as error:
            self.assertFalse(self.source.open_merge("dbs", "uis", "h1", match))
        error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
