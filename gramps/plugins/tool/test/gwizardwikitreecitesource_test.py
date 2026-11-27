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
Unit tests for the WikiTree side of the GWizard Citation Improvement Scan
(gwizardwikitreecitesource).
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
    SOURCE_TREE,
    build_citation_items,
)
from gramps.gen.lib import Citation, Note, Person, Source
from gramps.plugins.tool.gwizardwikitreecitesource import (
    WikiTreeCitationSource,
    load_on_reg,
)


class WikiTreeCitationSourceTest(unittest.TestCase):
    """Finding cited profiles, the checks, and opening a profile."""

    def setUp(self) -> None:
        """
        Citations: one of the "WikiTree" source (page = profile ID), one of
        a census whose note links a profile, and a plain census citation.
        """
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.handles: dict[str, str] = {}
        with DbTxn("tree", self.db) as trans:
            wikitree = Source()
            wikitree.set_title("WikiTree")
            self.db.add_source(wikitree, trans)
            census = Source()
            census.set_title("1900 United States Census")
            self.db.add_source(census, trans)
            note = Note()
            note.set("Also at https://www.wikitree.com/wiki/Smith-12345 (profile)")
            self.db.add_note(note, trans)
            person = Person()
            for key, source, page, notes in (
                ("profile", wikitree, "Smith-12345", []),
                ("linked", census, "Sheet 4A, line 12", [note.get_handle()]),
                ("plain", census, "Sheet 4A, line 13", []),
                ("badpage", wikitree, "not an id", []),
            ):
                citation = Citation()
                citation.set_reference_handle(source.get_handle())
                citation.set_page(page)
                for handle in notes:
                    citation.add_note(handle)
                self.db.add_citation(citation, trans)
                person.add_citation(citation.get_handle())
                self.handles[key] = citation.get_handle()
            self.db.add_person(person, trans)
            self.person = person.get_handle()
        self.adapter = WikiTreeCitationSource()
        self.items = {
            item.handle: item
            for item in build_citation_items(
                self.db, adapters={"wikitree": self.adapter}
            )
        }

    def tearDown(self) -> None:
        """Close the tree."""
        self.db.close()

    def _codes(self, key: str) -> set[str]:
        """Return a citation's issue codes."""
        return {issue.code for issue in self.items[self.handles[key]].issues}

    def test_record_keys(self) -> None:
        """The page of a WikiTree citation, and profile links anywhere."""
        self.assertEqual(
            self.items[self.handles["profile"]].record_keys,
            {"wikitree": ["Smith-12345"]},
        )
        self.assertEqual(
            self.items[self.handles["linked"]].record_keys,
            {"wikitree": ["Smith-12345"]},
        )
        self.assertEqual(self.items[self.handles["plain"]].record_keys, {})
        self.assertEqual(self.items[self.handles["badpage"]].record_keys, {})

    def test_profile_citation_checks(self) -> None:
        """A profile citation is a family tree and needs no image."""
        self.assertIn(SOURCE_TREE, self._codes("profile"))
        self.assertNotIn(NO_MEDIA, self._codes("profile"))
        self.assertIn(NO_MEDIA, self._codes("plain"))
        self.assertNotIn(SOURCE_TREE, self._codes("plain"))
        text = self.items[self.handles["profile"]].issue_summary()
        self.assertIn("Smith-12345", text)

    def test_open_record(self) -> None:
        """A cited profile opens in the WikiTree merge for the person."""
        with mock.patch(
            "gramps.plugins.tool.gwizardwikitreesource.WikiTreeSource.open_merge",
            return_value=True,
        ) as open_merge:
            self.assertTrue(
                self.adapter.open_record(None, None, self.person, "Smith-12345")
            )
        self.assertEqual(open_merge.call_args.args[2], self.person)
        self.assertEqual(open_merge.call_args.args[3].key, "Smith-12345")

    def test_registration(self) -> None:
        """load_on_reg offers one adapter for the "wikitree" record source."""
        self.assertEqual(
            [a.source_id for a in load_on_reg(None, None, None)], ["wikitree"]
        )


if __name__ == "__main__":
    unittest.main()
