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
Unit tests for the Grizard Results gramplet's pure helper functions.
"""

import unittest

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.plugins.gramplet.grizardresultsgramplet import build_result_markup


class BuildResultMarkupTest(unittest.TestCase):
    """Test the Pango markup builder for gramplet search results."""

    def test_no_results(self):
        """Empty result list shows a 'no matching records' message."""
        markup = build_result_markup("FindAGrave", [])
        self.assertIn("No matching records", markup)

    def test_results_as_links(self):
        """Each result is rendered as a link with years."""
        results = [
            {
                "name": "Milton White",
                "birth": "1822",
                "death": "1898",
                "url": "https://www.findagrave.com/memorial/252356272/milton-white",
                "website": "FindAGrave",
            }
        ]
        markup = build_result_markup("FindAGrave", results)
        self.assertIn("<a href=", markup)
        self.assertIn("Milton White", markup)
        self.assertIn("(1822–1898)", markup)
        self.assertIn("matching record(s)", markup)

    def test_missing_years_use_placeholders(self):
        """Results with partial years show '?' placeholders; without
        years, no year section is shown at all."""
        results = [{"name": "Jane Doe", "birth": "1900", "url": "https://x.test/1"}]
        markup = build_result_markup("BillionGraves", results)
        self.assertIn("(1900–?)", markup)
        markup = build_result_markup("BillionGraves", [{"name": "No Years"}])
        self.assertNotIn("(?", markup)
        self.assertIn("No Years", markup)

    def test_missing_url_is_plain_text(self):
        """Results without a URL render as plain text."""
        results = [{"name": "No Link", "birth": "1900", "death": ""}]
        markup = build_result_markup("FindAGrave", results)
        self.assertNotIn("<a href=", markup)
        self.assertIn("(1900–?)", markup)

    def test_markup_escaping(self):
        """Names and URLs are escaped so Pango markup stays valid."""
        results = [
            {
                "name": "<b>Evil & Name>",
                "birth": "1900",
                "death": "1950",
                "url": 'http://x.test/a"b&c',
            }
        ]
        markup = build_result_markup("Test", results)
        self.assertNotIn("<b>Evil", markup)
        self.assertIn("&amp;", markup)
        self.assertIn('href="http://x.test/a&quot;b&amp;c"', markup)


if __name__ == "__main__":
    unittest.main()
