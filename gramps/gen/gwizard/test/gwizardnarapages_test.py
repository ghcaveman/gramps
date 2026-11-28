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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Unit tests for guessing NARA page types (gwizardnarapages.py).

nara_record_pension_text.json is a real NARA response for the widow's
pension file of Mary Kreizer Smith (NAID 115768360), fetched with
includeExtractedText=true and trimmed to 12 of its 75 pages.
"""

# ------------------------------------------------------------
#
# Python modules
#
# ------------------------------------------------------------
import json
import os
import unittest
from typing import Any

# ------------------------------------------------------------
#
# Gramps modules
#
# ------------------------------------------------------------
from ..gwizardnarapages import (
    CONTINUATION,
    COVER,
    LITTLE_TEXT,
    NO_TEXT,
    UNKNOWN,
    classify_page,
    classify_pages,
    name_mentions,
    page_number,
    snippet,
)

_DATA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "nara_record_pension_text.json"
)


def _objects() -> list[dict[str, Any]]:
    """Return the trimmed pension file's digital objects."""
    with open(_DATA, encoding="utf-8") as sample:
        response = json.load(sample)
    return response["body"]["hits"]["hits"][0]["_source"]["record"]["digitalObjects"]


class TestNaraPages(unittest.TestCase):
    """Test page numbers, page types and name mentions."""

    def test_page_number(self) -> None:
        """Verify NARA's page number is read from the file name."""
        self.assertEqual(page_number("WC47795-SMITH-John-A_M_00003.jpg", 1), 3)
        self.assertEqual(page_number("WC23935-Smith-John-C_00031.jpg", 30), 31)
        self.assertEqual(page_number("2480.jpg", 0), 1)
        self.assertEqual(page_number("", 4), 5)

    def test_real_pension_pages(self) -> None:
        """Verify the real pages get the expected labels."""
        objects = _objects()
        pages = classify_pages(
            [o["objectFilename"] for o in objects],
            [o.get("extractedText", "") for o in objects],
        )
        labels = {page.page: page.label for page in pages}
        self.assertEqual(
            labels,
            {
                1: COVER,
                3: "Claim brief",
                5: "Affidavit",
                7: "Service report",
                8: "Marriage record",
                9: LITTLE_TEXT,
                21: "Marriage record",
                22: "Special examiner's report index",
                25: "Examiner's interview certificate",
                26: "Deposition",
                27: CONTINUATION,
                57: "Fee contract",
            },
        )

    def test_name_mentions_on_real_pages(self) -> None:
        """Verify name mentions find the widow and her later husband."""
        objects = _objects()
        pages = classify_pages(
            [o["objectFilename"] for o in objects],
            [o.get("extractedText", "") for o in objects],
            ["Mary", "Smith", "Kreizer", "Schleicher"],
        )
        mentions = {page.page: page.mentions for page in pages}
        self.assertEqual(mentions[1], ["Mary", "Smith"])
        self.assertIn("Schleicher", mentions[21])
        self.assertEqual(mentions[57], [])

    def test_classify_edge_cases(self) -> None:
        """Verify empty, short and unrecognised text."""
        self.assertEqual(classify_page(""), NO_TEXT)
        self.assertEqual(classify_page("   \n "), NO_TEXT)
        self.assertEqual(classify_page("Dec 20/64 april 1/65"), LITTLE_TEXT)
        self.assertEqual(classify_page("Box 123 Cert. 4567 of John Doe"), COVER)
        self.assertEqual(classify_page("word " * 40), UNKNOWN)

    def test_interior_department_alone_is_not_a_pension_form(self) -> None:
        """A National Park Service form is from Interior but not a pension."""
        text = (
            "NPS Form 10-900 United States Department of the Interior "
            "National Park Service National Register of Historic Places "
            "Registration Form. 1. Name of Property: Smith Farmstead. "
        ) * 3
        self.assertNotEqual(classify_page(text), "Pension Bureau form")

    def test_pension_forms_from_interior(self) -> None:
        self.assertEqual(
            classify_page(
                "Department of the Interior, Bureau of Pensions, Washington. "
                "Sir: Please furnish this office with the record of the soldier."
            ),
            "Pension Bureau form",
        )
        self.assertEqual(
            classify_page(
                "DEPARTMENT OF THE INTERIOR. Washington, D. C. The pension "
                "certificate of the soldier named above is enclosed herewith."
            ),
            "Pension Bureau form",
        )

    def test_continuation_needs_a_previous_deposition(self) -> None:
        """Verify a "Page" start only continues a deposition or affidavit."""
        text = "Page 2\nmy recollection is that he died not a long while after"
        self.assertEqual(classify_page(text, "Deposition"), CONTINUATION)
        self.assertEqual(classify_page(text, "Affidavit"), CONTINUATION)
        self.assertNotEqual(classify_page(text, "Claim brief"), CONTINUATION)

    def test_heading_spread_over_lines(self) -> None:
        """Verify headings broken across lines still match."""
        self.assertEqual(
            classify_page("DECLARATION\nFOR WIDOW'S\nPENSION. State of Ohio"),
            "Declaration",
        )

    def test_name_mentions_whole_words(self) -> None:
        """Verify names match whole words only and short names are skipped."""
        text = "Mary Smithson and Jo Smith"
        self.assertEqual(
            name_mentions(text, ["Smith", "Mary", "Jo"]), ["Smith", "Mary"]
        )
        self.assertEqual(name_mentions(text, ["Smithe"]), [])

    def test_snippet(self) -> None:
        """Verify the snippet joins the first non-empty lines."""
        self.assertEqual(
            snippet("\nWAR OF 1861.\n\nAct of July\nBRIEF\nmore"),
            "WAR OF 1861. / Act of July / BRIEF",
        )


if __name__ == "__main__":
    unittest.main()
