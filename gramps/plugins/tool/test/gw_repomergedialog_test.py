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

"""Tests for RepoMergeDialog (Fix Repositories dialog)."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import sys
import tempfile
import unittest
from unittest.mock import patch

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
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Repository, Source, RepoRef
from gramps.plugins.tool.gw_repomergedialog import RepoMergeDialog

_ = glocale.translation.sgettext


class FakeDbState:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class RepoMergeDialogTest(unittest.TestCase):
    """Test suite for RepoMergeDialog (Fix Repositories)."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = FakeDbState(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_dialog_buttons_and_footer(self) -> None:
        """Verify buttons in action area next to close, and footer text at bottom."""
        with DbTxn("Create repo and source", self.db) as trans:
            r = Repository()
            r.set_name("ancestry")
            r_h = self.db.add_repository(r, trans)

            s = Source()
            s.set_title("1900 US Census")
            ref = RepoRef()
            ref.set_reference_handle(r_h)
            s.add_repo_reference(ref)
            self.db.add_source(s, trans)

        with (
            patch.object(RepoMergeDialog, "add_action_widget") as mock_action,
            patch.object(RepoMergeDialog, "add_button") as mock_add_button,
            patch("gramps.plugins.tool.gw_repomergedialog.Gtk.Label") as mock_label_cls,
        ):
            dlg = RepoMergeDialog("Fix Repositories", self.dbstate)

            # Both accept_button and apply_button added via add_action_widget
            self.assertTrue(hasattr(dlg, "accept_button"))
            self.assertTrue(hasattr(dlg, "apply_button"))
            self.assertEqual(mock_action.call_count, 2)

            # Close button added via add_button
            mock_add_button.assert_called_with(
                str(_("_Close")),
                sys.modules["gi.repository"].Gtk.ResponseType.CLOSE,
            )

            # Verify footer text includes "Create missing repositories and link orphan sources."
            labels_created = [
                call.kwargs.get("label", "") for call in mock_label_cls.call_args_list
            ]
            footer_found = any(
                "Create missing repositories and link orphan sources." in text
                for text in labels_created
            )
            self.assertTrue(footer_found)


class RepoMergeApplyTest(unittest.TestCase):
    """Fix Repositories' Apply is one undoable transaction."""

    def test_merge_and_rename_undo_together(self) -> None:
        """A merge and a rename made by one Apply are undone by one undo."""
        db: DbWriteBase = make_database("sqlite")
        db.load(tempfile.mkdtemp())
        try:
            with DbTxn("Setup", db) as trans:
                for name in ("FamilySearch", "Family Search", "Ancestry"):
                    repo = Repository()
                    repo.set_name(name)
                    db.add_repository(repo, trans)
            dialog = RepoMergeDialog.__new__(RepoMergeDialog)
            dialog.dbstate = FakeDbState(db)
            plan = {"FamilySearch": ["Family Search"], "Ancestry.com": ["Ancestry"]}
            with DbTxn("Fix Repositories", db) as trans:
                merged, renamed, errors = dialog.apply_merges(plan, trans)
            self.assertEqual((merged, renamed, errors), (1, 1, []))
            names = sorted(r.get_name() for r in db.iter_repositories())
            self.assertEqual(names, ["Ancestry.com", "FamilySearch"])
            self.assertTrue(db.undo())
            names = sorted(r.get_name() for r in db.iter_repositories())
            self.assertEqual(names, ["Ancestry", "Family Search", "FamilySearch"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
