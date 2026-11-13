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
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# GTK test doubles (shared with the Media Fix tests)
#
# -------------------------------------------------------------------------
from gramps.plugins.tool.test import gwizard_gtk_fakes

# Install before importing a GWizard module, so its dialogs subclass the fakes.
Gtk = gwizard_gtk_fakes.install()


def setUpModule() -> None:  # pylint: disable=invalid-name
    """Put the fake widgets back on Gtk for this module's tests."""
    gwizard_gtk_fakes.install()


def tearDownModule() -> None:  # pylint: disable=invalid-name
    """Restore Gtk so other Gramps tests see the real widgets."""
    gwizard_gtk_fakes.uninstall()


# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db.utils import make_database
from gramps.gen.db.generic import DbWriteBase
from gramps.gen.db import DbTxn
from gramps.gen.lib import Source, Citation, Note
from gramps.plugins.tool.gw_unpackcitationsdialog import (
    UnpackCitationsDialog,
    plan_unpack_conflated_citations,
)

_ = glocale.translation.sgettext


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

    def test_plan_bare_url_in_page_moves_to_note(self) -> None:
        """A bare URL in Volume/Page should be moved to Citation Note and cleared from page."""
        with DbTxn("Create citation with bare URL", self.db) as trans:
            src = Source()
            src.set_title("1900 US Federal Census")
            s_handle = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_handle)
            cit.set_page("https://example.com/record")
            c_handle = self.db.add_citation(cit, trans)

        plan = plan_unpack_conflated_citations(self.db)
        self.assertEqual(len(plan), 1)
        entry = plan[0]
        self.assertEqual(entry["citation_handle"], c_handle)
        self.assertEqual(entry["suggested_page"], "")
        self.assertTrue(entry["clear_page"])
        self.assertEqual(entry["suggested_notes"], "https://example.com/record")

        with DbTxn("Apply unpack bare URL", self.db) as trans:
            from gramps.plugins.tool.gw_unpackcitationsdialog import (
                apply_unpack_citation,
            )

            applied = apply_unpack_citation(
                self.db,
                trans,
                c_handle,
                page=entry["suggested_page"],
                notes=entry["suggested_notes"],
                clear_page=entry["clear_page"],
            )
            self.assertTrue(applied)

        updated_cit = self.db.get_citation_from_handle(c_handle)
        self.assertEqual(updated_cit.get_page(), "")
        self.assertEqual(len(updated_cit.get_note_list()), 1)
        note = self.db.get_note_from_handle(updated_cit.get_note_list()[0])
        self.assertEqual(note.get(), "https://example.com/record")

    def test_url_in_note_not_moved_to_page_and_not_dropped(self) -> None:
        """A URL in Citation Note must stay in the note and not be moved to Volume/Page."""
        with DbTxn("Create citation with note URL", self.db) as trans:
            src = Source()
            src.set_title("1900 US Federal Census")
            s_handle = self.db.add_source(src, trans)

            note = Note()
            note.set("https://example.com/record")
            n_handle = self.db.add_note(note, trans)

            cit = Citation()
            cit.set_reference_handle(s_handle)
            cit.set_page("")
            cit.add_note(n_handle)
            self.db.add_citation(cit, trans)

        plan = plan_unpack_conflated_citations(self.db)
        # Should not flag this citation as conflated just because note has a URL
        self.assertEqual(len(plan), 0)

    def test_build_rows_and_accept_hints(self) -> None:
        """build_rows creates empty target entries and accept_hints populates them."""
        dlg = UnpackCitationsDialog.__new__(UnpackCitationsDialog)
        dlg.dbstate = self.dbstate
        dlg.row_targets = []
        dlg.column_sizegroups = [MagicMock() for _ in range(6)]

        entries = [
            {
                "citation_handle": "c1",
                "source_display": "1900 Census (S0001)",
                "citation_display": "Roll 123 (C0001)",
                "suggested_page": "Roll 123",
                "suggested_date": "1900",
                "suggested_notes": "https://example.com",
                "hint_text": "Clean Volume/Page\nExtract date",
            }
        ]

        grid_mock = MagicMock()
        with (
            patch(
                "gramps.plugins.tool.gw_unpackcitationsdialog.Gtk.Grid",
                return_value=grid_mock,
            ),
            patch(
                "gramps.plugins.tool.gw_unpackcitationsdialog.Gtk.Entry",
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

        with patch("gramps.plugins.tool.gw_unpackcitationsdialog.OkDialog"):
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
        mock_page.get_text.return_value = "Page 42"
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

        with patch("gramps.plugins.tool.gw_unpackcitationsdialog.OkDialog"):
            dlg.cb_apply(MagicMock())

        updated_cit = self.db.get_citation_from_handle(c_handle)
        self.assertEqual(updated_cit.get_page(), "Page 42")
        self.assertIsNotNone(updated_cit.get_date_object())
        self.assertGreater(len(updated_cit.get_note_list()), 0)

    def test_dialog_buttons_and_footer(self) -> None:
        """Verify buttons in action area next to close, and footer text at bottom."""
        with DbTxn("Create citation for dialog test", self.db) as trans:
            src = Source()
            src.set_title("Census 1900")
            s_h = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_h)
            cit.set_page("https://example.com/record accessed 12 Jan 1900")
            self.db.add_citation(cit, trans)

        with (
            patch.object(UnpackCitationsDialog, "add_action_widget") as mock_action,
            patch.object(UnpackCitationsDialog, "add_button") as mock_add_button,
            patch(
                "gramps.plugins.tool.gw_unpackcitationsdialog.Gtk.Label"
            ) as mock_label_cls,
        ):
            dlg = UnpackCitationsDialog(dbstate=self.dbstate)
            self.assertTrue(hasattr(dlg, "accept_button"))
            self.assertTrue(hasattr(dlg, "apply_button"))
            self.assertEqual(mock_action.call_count, 2)
            mock_add_button.assert_called_with(
                str(_("_Close")),
                sys.modules["gi.repository"].Gtk.ResponseType.CLOSE,
            )

            labels_created = [
                call.kwargs.get("label", "") for call in mock_label_cls.call_args_list
            ]
            footer_found = any(
                "Extract dates and URLs mixed into volume/page strings or notes" in text
                for text in labels_created
            )
            self.assertTrue(footer_found)


if __name__ == "__main__":
    unittest.main()
