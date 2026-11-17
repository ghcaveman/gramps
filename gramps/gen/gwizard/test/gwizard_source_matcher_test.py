#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  GWizard Source Matcher Tests
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
Unit tests for GWizard source normalization, signature extraction,
SourceMatcher, and source match reporting.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
from typing import Any
import unittest

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.gwizard.gwizard_base import (
    SOURCE_AMBIGUOUS,
    SOURCE_MATCHED,
    SOURCE_NEW,
    SourceMatcher,
    normalize_source_text,
    source_match_report,
    source_signature,
)
from gramps.gen.lib import Source


# ------------------------------------------------------------
#
# GWizardSourceMatcherTest
#
# ------------------------------------------------------------
class GWizardSourceMatcherTest(unittest.TestCase):
    """
    Test source text normalization, signature extraction, and matching.
    """

    def setUp(self) -> None:
        """
        Create in-memory source and target databases.
        """
        self.target_db = make_database("sqlite")
        self.target_db.load(":memory:")
        self.source_db = make_database("sqlite")
        self.source_db.load(":memory:")

    def tearDown(self) -> None:
        """
        Close databases.
        """
        self.source_db.close()
        self.target_db.close()

    def _add_source(
        self, db: Any, title: str, author: str = "", pub_info: str = ""
    ) -> Source:
        """
        Helper to add a Source record with given fields.
        """
        source = Source()
        source.set_title(title)
        source.set_author(author)
        source.set_publication_info(pub_info)
        with DbTxn("Add source", db) as trans:
            db.add_source(source, trans)
        return source

    def test_normalize_source_text(self) -> None:
        """
        Verify markup stripping, whitespace collapsing, and casefolding.
        """
        # None and empty
        self.assertEqual(normalize_source_text(None), "")
        self.assertEqual(normalize_source_text(""), "")
        self.assertEqual(normalize_source_text("   \t\n  "), "")

        # HTML/XML markup stripping
        self.assertEqual(
            normalize_source_text("<b>United States</b> Census, <i>1930</i>"),
            "united states census, 1930",
        )
        self.assertEqual(
            normalize_source_text("<span color='red'>Archive</span> Record"),
            "archive record",
        )

        # Whitespace collapsing
        self.assertEqual(
            normalize_source_text("  National   Archives  \n\t  Records "),
            "national archives records",
        )

        # Casefolding and NFKC normalization
        self.assertEqual(
            normalize_source_text("PARISH REGISTERS – ST. MARY"),
            "parish registers – st. mary",
        )

    def test_source_signature_valid(self) -> None:
        """
        Verify source_signature extracts normalized title, author, and pub info.
        """
        src = Source()
        src.set_title("  <b>Census</b> Record 1880  ")
        src.set_author("Bureau of the Census")
        src.set_publication_info("Washington, D.C., 1883")

        sig = source_signature(src)
        self.assertIsNotNone(sig)
        self.assertEqual(
            sig,
            ("census record 1880", "bureau of the census", "washington, d.c., 1883"),
        )

    def test_source_signature_missing_title_returns_none(self) -> None:
        """
        Verify source_signature returns None when title is absent or markup-only.
        """
        src = Source()
        src.set_title("")
        src.set_author("Author")
        self.assertIsNone(source_signature(src))

        src.set_title("   ")
        self.assertIsNone(source_signature(src))

        src.set_title("<b></b>")
        self.assertIsNone(source_signature(src))

    def test_source_matcher_find_single_match(self) -> None:
        """
        Verify SourceMatcher matches existing sources by signature.
        """
        target_src = self._add_source(
            self.target_db,
            "1900 United States Federal Census",
            "U.S. Census Bureau",
            "Washington, D.C.: NARA",
        )
        matcher = SourceMatcher(self.target_db)

        # Exact match
        incoming = Source()
        incoming.set_title("1900 United States Federal Census")
        incoming.set_author("U.S. Census Bureau")
        incoming.set_publication_info("Washington, D.C.: NARA")
        handle, status = matcher.find(incoming)
        self.assertEqual(handle, target_src.handle)
        self.assertEqual(status, SOURCE_MATCHED)

        # Case-insensitive and whitespace-tolerant match
        incoming2 = Source()
        incoming2.set_title("  1900   United States FEDERAL Census\n")
        incoming2.set_author("U.S. CENSUS BUREAU")
        incoming2.set_publication_info("Washington, D.C.:   NARA")
        handle2, status2 = matcher.find(incoming2)
        self.assertEqual(handle2, target_src.handle)
        self.assertEqual(status2, SOURCE_MATCHED)

        # Different author -> new source
        incoming3 = Source()
        incoming3.set_title("1900 United States Federal Census")
        incoming3.set_author("Ancestry.com")
        incoming3.set_publication_info("Washington, D.C.: NARA")
        handle3, status3 = matcher.find(incoming3)
        self.assertIsNone(handle3)
        self.assertEqual(status3, SOURCE_NEW)

        # Non-existent source title -> new source
        incoming4 = Source()
        incoming4.set_title("Non-Existent Book")
        handle4, status4 = matcher.find(incoming4)
        self.assertIsNone(handle4)
        self.assertEqual(status4, SOURCE_NEW)

    def test_source_matcher_ambiguous_match(self) -> None:
        """
        Verify multiple sources with identical signature are classified as ambiguous.
        """
        self._add_source(self.target_db, "Parish Register", "Church", "London")
        self._add_source(self.target_db, "Parish Register", "Church", "London")

        matcher = SourceMatcher(self.target_db)
        incoming = Source()
        incoming.set_title("Parish Register")
        incoming.set_author("Church")
        incoming.set_publication_info("London")

        handle, status = matcher.find(incoming)
        self.assertIsNone(handle)
        self.assertEqual(status, SOURCE_AMBIGUOUS)

    def test_source_matcher_add(self) -> None:
        """
        Verify SourceMatcher.add dynamically adds sources to the lookup index.
        """
        matcher = SourceMatcher(self.target_db)
        new_src = Source()
        new_src.set_title("New Source Title")
        new_src.set_author("Author A")
        new_src.handle = "custom_handle_1"

        # Before add, matcher on empty target DB has no match
        handle, status = matcher.find(new_src)
        self.assertIsNone(handle)
        self.assertEqual(status, SOURCE_NEW)

        # Add to matcher index
        matcher.add(new_src)
        handle, status = matcher.find(new_src)
        self.assertEqual(handle, new_src.handle)
        self.assertEqual(status, SOURCE_MATCHED)

        # Calling add again with same source handle does not duplicate entries
        matcher.add(new_src)
        handle, status = matcher.find(new_src)
        self.assertEqual(handle, new_src.handle)
        self.assertEqual(status, SOURCE_MATCHED)

    def test_source_match_report(self) -> None:
        """
        Verify source_match_report compares two databases and classifies sources.
        """
        # Add shared source in target and source
        t_shared = self._add_source(
            self.target_db,
            "Shared Source",
            "Author X",
            "Publisher Y",
        )
        self._add_source(
            self.source_db,
            "Shared Source",
            "Author X",
            "Publisher Y",
        )

        # Add source-only source
        self._add_source(
            self.source_db,
            "Unique Incoming Source",
            "Author Z",
            "Publisher W",
        )

        report = source_match_report(self.source_db, self.target_db)
        self.assertEqual(len(report), 2)

        # Matched source
        matched_entry = [r for r in report if r["title"] == "Shared Source"][0]
        self.assertEqual(matched_entry["status"], SOURCE_MATCHED)
        self.assertEqual(matched_entry["target_handle"], t_shared.handle)
        self.assertEqual(matched_entry["author"], "Author X")

        # Unique source
        unique_entry = [r for r in report if r["title"] == "Unique Incoming Source"][0]
        self.assertEqual(unique_entry["status"], SOURCE_NEW)
        self.assertEqual(unique_entry["target_handle"], "")
        self.assertEqual(unique_entry["author"], "Author Z")

        # Report ordering: "matched" comes before "new"
        self.assertEqual([r["status"] for r in report], [SOURCE_MATCHED, SOURCE_NEW])


if __name__ == "__main__":
    unittest.main()
