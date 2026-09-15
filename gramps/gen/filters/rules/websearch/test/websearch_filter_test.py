#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  The Gramps Project
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
# along with this program; if not, see <https://www.gnu.org/licenses/>.
#

"""
Unit tests for the web search filters: URL building, result page
filtering (parse_results), and the URL-to-filter registry.
"""

import unittest

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.filters.rules.websearch import (
    BillionGravesSearch,
    FindAGraveSearch,
    WEBSEARCH_FILTER_CLASSES,
    get_websearch_filter_for_url,
)

# -------------------------------------------------------------------------
#
# Test data
#
# -------------------------------------------------------------------------

_FINDAGRAVE_PAGE = """
<html><head><title>Find a Grave - Search Results</title></head>
<body><h1>Search Results</h1>
<p>1 matching record found for Milton White</p>
<table><thead><tr><th>Name</th><th>Birth</th><th>Death</th></tr></thead>
<tbody><tr><td><strong>Milton White</strong></td><td>1822</td><td>1898</td></tr></tbody>
</table>
<p><a href="/memorial/12345">View Memorial</a></p>
<p><a href="/search">New Search</a></p>
</body></html>
"""

_BILLIONGRAVES_PAGE = """
<html><body><h1>Search Results</h1>
<div class="result">
<h2><a href="/search/result/99887" title="Jane Doe">Jane Doe</a></h2>
<p>1820 - 1901 - Springfield Cemetery</p>
</div>
<div class="result">
<h2><a href="/search/result/99888">Sam Black</a></h2>
<p>1855 - 1930</p>
</div>
<p><a href="/search">New Search</a></p>
</body></html>
"""


# -------------------------------------------------------------------------
#
# Search URL construction tests
#
# -------------------------------------------------------------------------
class SearchUrlTest(unittest.TestCase):
    """Test search URL construction."""

    def test_findagrave_url(self):
        """FindAGrave URL contains name and year parameters."""
        web_filter = FindAGraveSearch()
        url = web_filter.get_search_url(
            {
                "first_name": "Milton",
                "surname": "White",
                "birth_date": "12 Mar 1822",
                "death_date": "1898",
            }
        )
        self.assertIn("https://www.findagrave.com/memorial/search", url)
        self.assertIn("firstname=Milton", url)
        self.assertIn("lastname=White", url)
        self.assertIn("birthyear=1822", url)
        self.assertIn("deathyear=1898", url)

    def test_findagrave_url_no_years(self):
        """FindAGrave URL omits year parameters when dates are missing."""
        web_filter = FindAGraveSearch()
        url = web_filter.get_search_url({"first_name": "Milton", "surname": "White"})
        self.assertNotIn("birthyear", url)
        self.assertNotIn("deathyear", url)

    def test_billiongraves_url(self):
        """BillionGraves URL contains name and year parameters."""
        web_filter = BillionGravesSearch()
        url = web_filter.get_search_url(
            {
                "first_name": "Milton",
                "surname": "White",
                "birth_date": "1822",
                "death_date": "4 Jun 1898",
            }
        )
        self.assertIn("https://www.billiongraves.com/search/results", url)
        self.assertIn("given_names=Milton", url)
        self.assertIn("family_names=White", url)
        self.assertIn("birth_year=1822", url)
        self.assertIn("death_year=1898", url)

    def test_extract_year(self):
        """Year extraction handles various date formats."""
        self.assertEqual(FindAGraveSearch._extract_year("12 Mar 1822"), "1822")
        self.assertEqual(FindAGraveSearch._extract_year("1822"), "1822")
        self.assertEqual(FindAGraveSearch._extract_year(""), "")
        self.assertEqual(FindAGraveSearch._extract_year("unknown date"), "")


# -------------------------------------------------------------------------
#
# Result page filtering tests
#
# -------------------------------------------------------------------------
class ParseResultsTest(unittest.TestCase):
    """Test filtering of fetched result pages into structured results."""

    def test_findagrave_parse(self):
        """FindAGrave memorial link is extracted with nearby name/years."""
        web_filter = FindAGraveSearch()
        results = web_filter.parse_results(
            _FINDAGRAVE_PAGE, "https://www.findagrave.com/memorial/search"
        )
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["url"], "https://www.findagrave.com/memorial/12345")
        self.assertEqual(result["website"], "FindAGrave")
        # The anchor text "View Memorial" is generic; name falls back to
        # the preceding text ("Milton White").
        self.assertEqual(result["name"], "Milton White")
        self.assertEqual(result["birth"], "1822")
        self.assertEqual(result["death"], "1898")

    def test_findagrave_parse_ignores_non_result_links(self):
        """Links not matching the memorial pattern are ignored."""
        web_filter = FindAGraveSearch()
        results = web_filter.parse_results(
            '<a href="/search">New Search</a>'
            '<a href="/memorial/abc">Bad</a>'
            '<a href="https://elsewhere.org/memorial/1">Ext</a>',
            "https://www.findagrave.com/memorial/search",
        )
        self.assertEqual(results, [])

    def test_billiongraves_parse(self):
        """BillionGraves record links are extracted with years."""
        web_filter = BillionGravesSearch()
        results = web_filter.parse_results(
            _BILLIONGRAVES_PAGE, "https://www.billiongraves.com/search/results"
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "Jane Doe")
        self.assertEqual(
            results[0]["url"], "https://www.billiongraves.com/search/result/99887"
        )
        self.assertEqual(results[0]["birth"], "1820")
        self.assertEqual(results[0]["death"], "1901")
        self.assertEqual(results[1]["name"], "Sam Black")
        self.assertEqual(results[1]["birth"], "1855")
        self.assertEqual(results[1]["death"], "1930")

    def test_base_class_has_no_parser(self):
        """The base filter has no result pattern and parses nothing."""
        from gramps.gen.filters.rules.websearch import WebSearchFilter

        web_filter = WebSearchFilter()
        self.assertIsNone(web_filter.RESULT_HREF_PATTERN)
        self.assertEqual(web_filter.parse_results("<p>x</p>", "http://x.test/"), [])


# -------------------------------------------------------------------------
#
# Registry tests
#
# -------------------------------------------------------------------------
class RegistryTest(unittest.TestCase):
    """Test URL-to-filter matching."""

    def test_findagrave_match(self):
        """FindAGrave URLs resolve to the FindAGrave filter."""
        web_filter = get_websearch_filter_for_url(
            "https://www.findagrave.com/memorial/search?firstname=J"
        )
        self.assertIsInstance(web_filter, FindAGraveSearch)

    def test_findagrave_www_match(self):
        """www-prefixed hosts match too."""
        web_filter = get_websearch_filter_for_url("https://www.findagrave.com/x")
        self.assertIsInstance(web_filter, FindAGraveSearch)

    def test_billiongraves_match(self):
        """BillionGraves URLs resolve to the BillionGraves filter."""
        web_filter = get_websearch_filter_for_url(
            "https://billiongraves.com/search/results?given_names=J"
        )
        self.assertIsInstance(web_filter, BillionGravesSearch)

    def test_unknown_url(self):
        """URLs of unrelated sites resolve to no filter."""
        self.assertIsNone(get_websearch_filter_for_url("https://www.example.com/page"))
        self.assertIsNone(get_websearch_filter_for_url("not a url"))

    def test_registry_contains_all_filters(self):
        """The registry lists every exported filter class."""
        self.assertIn(FindAGraveSearch, WEBSEARCH_FILTER_CLASSES)
        self.assertIn(BillionGravesSearch, WEBSEARCH_FILTER_CLASSES)
        self.assertEqual(len(WEBSEARCH_FILTER_CLASSES), 4)


if __name__ == "__main__":
    unittest.main()
