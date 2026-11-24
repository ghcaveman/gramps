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

"""Unit tests for FamilySearch as a GWizard Multi-Archive Record Scan source."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import unittest
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.gwizard.gwizard_base import RecordQuery
from gramps.gen.lib import Attribute, Person
from gramps.plugins.tool.gwizardfssource import (
    FamilySearchSource,
    _extract_years_from_life,
    candidate_from_fs_result,
    load_on_reg,
)


# ------------------------------------------------------------------
#
# FamilySearchSourceTest
#
# ------------------------------------------------------------------
class FamilySearchSourceTest(unittest.TestCase):
    """Searching, looking up, and opening merges through FamilySearchSource."""

    def setUp(self) -> None:
        self.mock_client = MagicMock()
        self.mock_client.search_person.return_value = [
            {
                "fsid": "GSVF-SGV",
                "name": "Abraham Lincoln",
                "life": "1809 - 1865",
            }
        ]
        self.source = FamilySearchSource(client=self.mock_client)
        self.query = RecordQuery(given="Abraham", surnames=["Lincoln"], birth_year=1809)

    def test_load_on_reg_returns_source(self):
        sources = load_on_reg(None, None, None)
        self.assertEqual(len(sources), 1)
        self.assertIsInstance(sources[0], FamilySearchSource)
        self.assertEqual(sources[0].source_id, "familysearch")

    def test_extract_years_from_life(self):
        by, dy = _extract_years_from_life("1809 - 1865")
        self.assertEqual(by, (1809, 1809))
        self.assertEqual(dy, (1865, 1865))

        by2, dy2 = _extract_years_from_life("1809-")
        self.assertEqual(by2, (1809, 1809))
        self.assertIsNone(dy2)

        by3, dy3 = _extract_years_from_life("")
        self.assertIsNone(by3)
        self.assertIsNone(dy3)

    def test_candidate_from_fs_result(self):
        cand = candidate_from_fs_result(
            {
                "fsid": "GSVF-SGV",
                "name": "Abraham Lincoln",
                "life": "1809 - 1865",
            }
        )
        self.assertEqual(cand.given, "Abraham")
        self.assertEqual(cand.surnames, ["Lincoln"])
        self.assertEqual(cand.birth_years, (1809, 1809))
        self.assertEqual(cand.death_years, (1865, 1865))

    def test_linked_key(self):
        p = Person()
        self.assertEqual(self.source.linked_key(None, p), "")

        attr = Attribute()
        attr.set_type("_FSFTID")
        attr.set_value("GSVF-SGV")
        p.add_attribute(attr)
        self.assertEqual(self.source.linked_key(None, p), "GSVF-SGV")

    def test_search(self):
        matches = self.source.search(self.query)
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m.key, "GSVF-SGV")
        self.assertIn("Abraham Lincoln", m.label)
        self.assertIn(
            "https://www.familysearch.org/tree/person/details/GSVF-SGV", m.url
        )

    def test_lookup(self):
        m = self.source.lookup("GSVF-SGV")
        self.assertIsNotNone(m)
        self.assertEqual(m.key, "GSVF-SGV")
        self.assertEqual(
            m.url, "https://www.familysearch.org/tree/person/details/GSVF-SGV"
        )

    def test_open_merge(self):
        mock_launcher = MagicMock()
        mock_launcher.merge_familysearch_person.return_value = (True, "Merged")
        with patch.dict(
            "sys.modules",
            {"gramps.gui.gwizard.gwizardfslauncher": mock_launcher},
        ):
            m = self.source.lookup("GSVF-SGV")
            result = self.source.open_merge(None, None, "handle_123", m)
            self.assertTrue(result)
            mock_launcher.merge_familysearch_person.assert_called_once()


if __name__ == "__main__":
    unittest.main()
