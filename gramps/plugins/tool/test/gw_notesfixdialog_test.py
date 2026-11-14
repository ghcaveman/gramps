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

"""Tests for NotesFixDialog."""

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
from gramps.gen.lib import Note, Person
from gramps.gen.errors import HandleError
from gramps.plugins.tool.gw_notesfixdialog import (
    NotesFixDialog,
    build_note_fix_rows,
)

_ = glocale.translation.sgettext


class FakeDbState:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class NotesFixDialogTest(unittest.TestCase):
    """Test NotesFixDialog row detection, column layout, hints, and apply logic."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = FakeDbState(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_build_note_fix_rows_detection(self) -> None:
        """Debris notes, empty notes, and whitespace notes should be detected."""
        with DbTxn("Create notes", self.db) as trans:
            # 1. Debris note
            n1 = Note()
            n1.set("Records not imported into repo: TAG_XYZ")
            h1 = self.db.add_note(n1, trans)

            # 2. Empty note
            n2 = Note()
            n2.set("   ")
            h2 = self.db.add_note(n2, trans)

            # 3. Whitespace note
            n3 = Note()
            n3.set("  Valid note with padding  ")
            h3 = self.db.add_note(n3, trans)

            # 4. Clean note (should NOT be in fix rows)
            n4 = Note()
            n4.set("Clean valid note.")
            self.db.add_note(n4, trans)

        rows = build_note_fix_rows(self.db)
        self.assertEqual(len(rows), 3)

        r1 = next(r for r in rows if r["note_handle"] == h1)
        self.assertEqual(r1["suggested_action"], "Purge")
        self.assertIn("Import debris", r1["hint_text"])

        r2 = next(r for r in rows if r["note_handle"] == h2)
        self.assertEqual(r2["suggested_action"], "Purge")
        self.assertIn("Empty note", r2["hint_text"])

        r3 = next(r for r in rows if r["note_handle"] == h3)
        self.assertEqual(r3["suggested_action"], "Trim")
        self.assertEqual(r3["suggested_text"], "Valid note with padding")

    def test_build_rows_and_accept_hints(self) -> None:
        """build_rows creates empty target textboxes and accept_hints populates them."""
        dlg = NotesFixDialog.__new__(NotesFixDialog)
        dlg.dbstate = self.dbstate
        dlg.row_targets = []

        entries = [
            {
                "note_handle": "n1",
                "display_text": "N0001 (General Note)\nDebris text",
                "suggested_action": "Purge",
                "suggested_text": "[Purge note]",
                "hint_text": "Import debris",
            }
        ]

        grid_mock = MagicMock()
        with (
            patch(
                "gramps.plugins.tool.gw_notesfixdialog.Gtk.Grid",
                return_value=grid_mock,
            ),
            patch(
                "gramps.plugins.tool.gw_notesfixdialog.Gtk.Entry",
                side_effect=lambda: MagicMock(),
            ),
        ):
            dlg.build_rows(entries)

        self.assertEqual(len(dlg.row_targets), 1)
        target = dlg.row_targets[0]
        target["action_entry"].set_text.assert_called_with("")
        target["text_entry"].set_text.assert_called_with("")
        self.assertIsNotNone(target["hint_label"])

        # Simulate empty entries
        target["action_entry"].get_text.return_value = ""
        target["text_entry"].get_text.return_value = ""

        with patch("gramps.plugins.tool.gw_notesfixdialog.OkDialog"):
            dlg.cb_accept_hints(MagicMock())

        target["action_entry"].set_text.assert_called_with("Purge")
        target["text_entry"].set_text.assert_called_with("[Purge note]")

    def test_cb_apply_purge_and_update(self) -> None:
        """Applying target entries executes purge on debris and updates trimmed text."""
        with DbTxn("Create notes for apply", self.db) as trans:
            p = Person()
            p_h = self.db.add_person(p, trans)

            n_debris = Note()
            n_debris.set("tag recognized but not supported: ABC")
            h_debris = self.db.add_note(n_debris, trans)
            p.add_note(h_debris)
            self.db.commit_person(p, trans)

            n_trim = Note()
            n_trim.set("  Padded text  ")
            h_trim = self.db.add_note(n_trim, trans)

        dlg = NotesFixDialog.__new__(NotesFixDialog)
        dlg.dbstate = self.dbstate
        dlg.destroy = MagicMock()

        mock_act_purge = MagicMock()
        mock_act_purge.get_text.return_value = "Purge"
        mock_txt_purge = MagicMock()
        mock_txt_purge.get_text.return_value = "[Purge note]"

        mock_act_trim = MagicMock()
        mock_act_trim.get_text.return_value = "Trim"
        mock_txt_trim = MagicMock()
        mock_txt_trim.get_text.return_value = "Padded text"

        dlg.row_targets = [
            {
                "entry": {
                    "note_handle": h_debris,
                    "raw_text": "tag recognized but not supported: ABC",
                },
                "action_entry": mock_act_purge,
                "text_entry": mock_txt_purge,
            },
            {
                "entry": {"note_handle": h_trim, "raw_text": "  Padded text  "},
                "action_entry": mock_act_trim,
                "text_entry": mock_txt_trim,
            },
        ]

        with patch("gramps.plugins.tool.gw_notesfixdialog.OkDialog"):
            dlg.cb_apply(MagicMock())

        # Debris note should be purged from database and detached from person
        with self.assertRaises(HandleError):
            self.db.get_note_from_handle(h_debris)
        updated_p = self.db.get_person_from_handle(p_h)
        self.assertNotIn(h_debris, updated_p.get_note_list())

        # Trimmed note should have cleaned text
        updated_trim = self.db.get_note_from_handle(h_trim)
        self.assertEqual(updated_trim.get(), "Padded text")

    def test_dialog_buttons_and_footer(self) -> None:
        """Verify buttons in action area next to close, and footer text at bottom."""
        with DbTxn("Create note for dialog test", self.db) as trans:
            n = Note()
            n.set("Records not imported into repo: TAG_XYZ")
            self.db.add_note(n, trans)

        with (
            patch.object(NotesFixDialog, "add_action_widget") as mock_action,
            patch.object(NotesFixDialog, "add_button") as mock_add_button,
            patch("gramps.plugins.tool.gw_notesfixdialog.Gtk.Label") as mock_label_cls,
        ):
            dlg = NotesFixDialog(dbstate=self.dbstate)
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
                "Remove import debris and convert bare-URL notes." in text
                for text in labels_created
            )
            self.assertTrue(footer_found)


if __name__ == "__main__":
    unittest.main()
