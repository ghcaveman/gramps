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

"""Tests for the FamilySearch person search in gramps/gui/fs/actions.py.

FamilySearch rejects a single free-text 'q=...' search parameter with
HTTP 400; the search must send one 'q.<term>' parameter per search term.

python3 -m unittest gramps.gui.fs.test.actions_search_test -v
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
import unittest
from unittest.mock import MagicMock

# Protect headless / standalone CI runs from missing display.
os.environ.setdefault("GDK_BACKEND", "-")

try:
    from gramps.gui.fs import actions
except Exception as err:  # pragma: no cover - depends on the GTK install
    actions = None
    IMPORT_ERROR = err
else:
    IMPORT_ERROR = None

HEADERS = {"Accept": "application/x-gedcomx-atom+json"}


# ------------------------------------------------------------
#
# SearchParamsTest
#
# ------------------------------------------------------------
@unittest.skipIf(actions is None, f"gramps.gui.fs.actions unavailable: {IMPORT_ERROR}")
class SearchParamsTest(unittest.TestCase):
    """Free-text search becomes Tree Person Search parameters."""

    def test_given_and_surname(self):
        self.assertEqual(
            actions._search_params_from_text("John Henry Smith"),
            {"q.givenName": "John Henry", "q.surname": "Smith"},
        )

    def test_surname_only(self):
        self.assertEqual(
            actions._search_params_from_text("Smith"), {"q.surname": "Smith"}
        )

    def test_year_and_place(self):
        self.assertEqual(
            actions._search_params_from_text("John Smith 1850, Columbus, Ohio"),
            {
                "q.givenName": "John",
                "q.surname": "Smith",
                "q.birthLikeDate": "+1850",
                "q.birthLikePlace": "Columbus, Ohio",
            },
        )

    def test_blank(self):
        self.assertEqual(actions._search_params_from_text("   "), {})


# ------------------------------------------------------------
#
# SearchRequestTest
#
# ------------------------------------------------------------
@unittest.skipIf(actions is None, f"gramps.gui.fs.actions unavailable: {IMPORT_ERROR}")
class SearchRequestTest(unittest.TestCase):
    """The search request and its error reporting."""

    def test_sends_q_term_params(self):
        session = MagicMock()
        session.get_url.return_value = {"entries": []}

        self.assertEqual(
            actions._search_familysearch_people(session, "John Smith 1850"), []
        )

        session.get_url.assert_called_once_with(
            "/platform/tree/search",
            headers=HEADERS,
            params={
                "q.givenName": "John",
                "q.surname": "Smith",
                "q.birthLikeDate": "+1850",
                "count": "25",
            },
        )

    def test_blank_query_makes_no_request(self):
        session = MagicMock()
        self.assertEqual(actions._search_familysearch_people(session, ""), [])
        session.get_url.assert_not_called()

    def test_reports_familysearch_error_detail(self):
        response = MagicMock()
        response.status_code = 400
        response.json.return_value = {
            "errors": [{"code": 400, "message": "Unable to parse query."}]
        }
        session = MagicMock()
        session.get_url.return_value = response

        with self.assertRaisesRegex(
            RuntimeError, r"HTTP 400\)\. Unable to parse query\."
        ):
            actions._search_familysearch_people(session, "John Smith")


if __name__ == "__main__":
    unittest.main()
