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
Unit tests for the FamilySearch side of the GWizard Citation Improvement
Scan (gwizardfscitesource).
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import unittest
from unittest import mock

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.gwizard.gwizard_filemerge_citationscan import (
    NO_MEDIA,
    RECORD_NO_MEDIA,
    SOURCE_TREE,
    CitationItem,
    build_citation_items,
)
from gramps.gen.lib import Attribute, Citation, Person, Source
from gramps.plugins.tool.gwizardfscitesource import (
    FamilySearchCitationSource,
    load_on_reg,
)

TREE_URL = "https://www.familysearch.org/tree/person/details/KWCB-QZP"
RECORD_URL = "https://www.familysearch.org/ark:/61903/1:1:MXYZ-123"


class FamilySearchCitationSourceTest(unittest.TestCase):
    """Tree persons, historical records, the checks, opening a person."""

    def setUp(self) -> None:
        """
        Citations: of the "FamilySearch Family Tree" source (page = ID), of
        a census with a tree-person link, of a census with a record ARK,
        a census whose page is a year range, and a plain census.
        """
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.handles: dict[str, str] = {}
        with DbTxn("tree", self.db) as trans:
            fstree = Source()
            fstree.set_title("FamilySearch Family Tree")
            self.db.add_source(fstree, trans)
            census = Source()
            census.set_title("1900 United States Census")
            self.db.add_source(census, trans)
            person = Person()
            for key, source, page, url in (
                ("tree", fstree, "KWCB-QZP", ""),
                ("treelink", census, "Sheet 4A, line 12", TREE_URL),
                ("record", census, "Sheet 4A, line 13", RECORD_URL),
                ("years", fstree, "1900-1910", ""),
                ("plain", census, "Sheet 4A, line 14", ""),
            ):
                citation = Citation()
                citation.set_reference_handle(source.get_handle())
                citation.set_page(page)
                if url:
                    attribute = Attribute()
                    attribute.set_type("URL")
                    attribute.set_value(url)
                    citation.add_attribute(attribute)
                self.db.add_citation(citation, trans)
                person.add_citation(citation.get_handle())
                self.handles[key] = citation.get_handle()
            self.db.add_person(person, trans)
            self.person = person.get_handle()
        self.adapter = FamilySearchCitationSource()
        self.items = {
            item.handle: item
            for item in build_citation_items(
                self.db, adapters={"familysearch": self.adapter}
            )
        }

    def tearDown(self) -> None:
        """Close the tree."""
        self.db.close()

    def _item(self, key: str) -> CitationItem:
        """Return a citation's item."""
        return self.items[self.handles[key]]

    def _codes(self, key: str) -> set[str]:
        """Return a citation's issue codes."""
        return {issue.code for issue in self._item(key).issues}

    def test_record_keys(self) -> None:
        """Tree person IDs only; a year range and a record ARK are not."""
        self.assertEqual(self._item("tree").record_keys, {"familysearch": ["KWCB-QZP"]})
        self.assertEqual(
            self._item("treelink").record_keys, {"familysearch": ["KWCB-QZP"]}
        )
        self.assertEqual(self._item("record").record_keys, {})
        self.assertEqual(self._item("years").record_keys, {})
        self.assertEqual(self._item("plain").record_keys, {})

    def test_tree_checks(self) -> None:
        """
        A tree-person citation is a family tree (flagged once, by its
        source title or by the adapter) and needs no image.
        """
        tree = [i.code for i in self._item("tree").issues]
        self.assertEqual(tree.count(SOURCE_TREE), 1)
        self.assertNotIn(NO_MEDIA, tree)
        self.assertIn(SOURCE_TREE, self._codes("treelink"))
        self.assertIn("KWCB-QZP", self._item("treelink").issue_summary())

    def test_record_ark_without_image(self) -> None:
        """A historical record without an image may have one."""
        codes = self._codes("record")
        self.assertIn(RECORD_NO_MEDIA, codes)
        self.assertNotIn(NO_MEDIA, codes)
        self.assertIn("MXYZ-123", self._item("record").issue_summary())
        self.assertIn(NO_MEDIA, self._codes("plain"))

    def test_open_record(self) -> None:
        """A cited tree person opens in the FamilySearch merge."""
        with mock.patch(
            "gramps.plugins.tool.gwizardfssource.FamilySearchSource.open_merge",
            return_value=False,
        ) as open_merge:
            self.assertFalse(
                self.adapter.open_record(None, None, self.person, "KWCB-QZP")
            )
        self.assertEqual(open_merge.call_args.args[2], self.person)
        self.assertEqual(open_merge.call_args.args[3].key, "KWCB-QZP")

    def test_registration(self) -> None:
        """load_on_reg offers one adapter for the "familysearch" source."""
        self.assertEqual(
            [a.source_id for a in load_on_reg(None, None, None)], ["familysearch"]
        )


if __name__ == "__main__":
    unittest.main()
