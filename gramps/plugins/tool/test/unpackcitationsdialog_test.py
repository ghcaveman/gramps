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

"""Tests for UnpackCitationsDialog."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import sys
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# GTK mock fallback when running without display or PyGObject
#
# -------------------------------------------------------------------------
if "gi" not in sys.modules:
    gi_mock = MagicMock()

    class _FakeDialog:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_content_area(self) -> MagicMock:
            return MagicMock()

        def add_button(self, *args: Any, **kwargs: Any) -> None:
            pass

        def add_action_widget(self, *args: Any, **kwargs: Any) -> None:
            pass

        def connect(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_default_size(self, *args: Any, **kwargs: Any) -> None:
            pass

        def show_all(self) -> None:
            pass

    gi_mock.repository.Gtk.Dialog = _FakeDialog
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.utils import make_database
from gramps.gen.db.generic import DbWriteBase
from gramps.gen.db import DbTxn
from gramps.gen.lib import Source, Citation, Note
from gramps.plugins.tool.unpackcitationsdialog import (
    UnpackCitationsDialog,
    plan_unpack_conflated_citations,
)


class FakeDbState:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class UnpackCitationsDialogTest(unittest.TestCase):
    """Test UnpackCitationsDialog planner, column layout, accept hints, and apply logic."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = FakeDbState(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_plan_unpack_conflated_citations(self) -> None:
        """Citations with dates or URLs embedded in page/notes should be identified in the plan."""
        with DbTxn("Create conflated citation", self.db) as trans:
            src = Source()
            src.set_title("1900 US Federal Census")
            s_handle = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_handle)
            cit.set_page(
                "Roll 123; Page 4B; accessed 15 June 1905 at https://example.com/record"
            )
            c_handle = self.db.add_citation(cit, trans)

        plan = plan_unpack_conflated_citations(self.db)
        self.assertEqual(len(plan), 1)
        entry = plan[0]
        self.assertEqual(entry["citation_handle"], c_handle)
        self.assertIn("Roll 123; Page 4B", entry["suggested_page"])
        self.assertEqual(entry["suggested_date"], "15 June 1905")
        self.assertEqual(entry["suggested_notes"], "https://example.com/record")
        self.assertIn("Clean Volume/Page", entry["hint_text"])
        self.assertIn("Extract date", entry["hint_text"])

    def test_build_rows_and_accept_hints(self) -> None:
        """build_rows creates empty target entries and accept_hints populates them."""
        dlg = UnpackCitationsDialog.__new__(UnpackCitationsDialog)
        dlg.dbstate = self.dbstate
        dlg.row_targets = []

        entries = [
            {
                "citation_handle": "c1",
                "display_text": "1900 Census\nCitation: Roll 123",
                "suggested_page": "Roll 123",
                "suggested_date": "1900",
                "suggested_notes": "https://example.com",
                "hint_text": "Clean Volume/Page\nExtract date",
            }
        ]

        grid_mock = MagicMock()
        with (
            patch(
                "gramps.plugins.tool.unpackcitationsdialog.Gtk.Grid",
                return_value=grid_mock,
            ),
            patch(
                "gramps.plugins.tool.unpackcitationsdialog.Gtk.Entry",
                side_effect=lambda: MagicMock(),
            ),
        ):
            dlg.build_rows(entries)

        self.assertEqual(len(dlg.row_targets), 1)
        target = dlg.row_targets[0]
        target["page_entry"].set_text.assert_called_with("")
        target["date_entry"].set_text.assert_called_with("")
        target["notes_entry"].set_text.assert_called_with("")

        # Simulate empty entries
        target["page_entry"].get_text.return_value = ""
        target["date_entry"].get_text.return_value = ""
        target["notes_entry"].get_text.return_value = ""

        with patch("gramps.plugins.tool.unpackcitationsdialog.OkDialog"):
            dlg.cb_accept_hints(MagicMock())

        target["page_entry"].set_text.assert_called_with("Roll 123")
        target["date_entry"].set_text.assert_called_with("1900")
        target["notes_entry"].set_text.assert_called_with("https://example.com")

    def test_cb_apply_commits_to_database(self) -> None:
        """Applying target values updates the citation record in the database."""
        with DbTxn("Create citation for apply", self.db) as trans:
            src = Source()
            src.set_title("Test Source")
            s_handle = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_handle)
            cit.set_page("Conflated raw text")
            c_handle = self.db.add_citation(cit, trans)

        dlg = UnpackCitationsDialog.__new__(UnpackCitationsDialog)
        dlg.dbstate = self.dbstate
        dlg.destroy = MagicMock()

        mock_page = MagicMock()
        mock_page.get_text.return_value = "Cleaned Page 42"
        mock_date = MagicMock()
        mock_date.get_text.return_value = "1920"
        mock_notes = MagicMock()
        mock_notes.get_text.return_value = "https://example.org/record"

        dlg.row_targets = [
            {
                "entry": {"citation_handle": c_handle},
                "page_entry": mock_page,
                "date_entry": mock_date,
                "notes_entry": mock_notes,
            }
        ]

        with patch("gramps.plugins.tool.unpackcitationsdialog.OkDialog"):
            dlg.cb_apply(MagicMock())

        updated_cit = self.db.get_citation_from_handle(c_handle)
        self.assertEqual(updated_cit.get_page(), "Cleaned Page 42")
        self.assertIsNotNone(updated_cit.get_date_object())
        self.assertGreater(len(updated_cit.get_note_list()), 0)


if __name__ == "__main__":
    unittest.main()
