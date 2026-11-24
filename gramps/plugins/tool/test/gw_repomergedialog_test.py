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
from gramps.plugins.tool.gw_repomergedialog import (
    RepoMergeDialog,
    apply_repo_merges,
    auto_fix_repositories,
    build_repo_fix_rows,
)
from gramps.plugins.tool import gwizardcitationfix as fix

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
            patch(
                "gramps.plugins.tool.gw_repomergedialog.SelectableLabel"
            ) as mock_label_cls,
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
        db.load(tempfile.mkdtemp(), None)
        try:
            with DbTxn("Setup", db) as trans:
                for name in ("FamilySearch", "Family Search", "Ancestry"):
                    repo = Repository()
                    repo.set_name(name)
                    db.add_repository(repo, trans)
            plan = {"FamilySearch": ["Family Search"], "Ancestry.com": ["Ancestry"]}
            with DbTxn("Fix Repositories", db) as trans:
                merged, renamed, errors = apply_repo_merges(db, plan, trans)
            self.assertEqual((merged, renamed, errors), (1, 1, []))
            names = sorted(r.get_name() for r in db.iter_repositories())
            self.assertEqual(names, ["Ancestry.com", "FamilySearch"])
            self.assertTrue(db.undo())
            names = sorted(r.get_name() for r in db.iter_repositories())
            self.assertEqual(names, ["Ancestry", "Family Search", "FamilySearch"])
        finally:
            db.close()


class RepoFixSharedRowsTest(unittest.TestCase):
    """The dialog and Accept all hints use the same rows and hints."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(tempfile.mkdtemp(), None)

    def tearDown(self) -> None:
        self.db.close()

    def _repo(self, name: str, trans: DbTxn) -> str:
        repo = Repository()
        repo.set_name(name)
        return self.db.add_repository(repo, trans)

    def _source(self, title: str, repo_handle: str, trans: DbTxn) -> str:
        source = Source()
        source.set_title(title)
        if repo_handle:
            ref = RepoRef()
            ref.set_reference_handle(repo_handle)
            source.add_repo_reference(ref)
        return self.db.add_source(source, trans)

    def test_sources_on_golden_repositories_are_left_alone(self) -> None:
        """A source already on a gold-standard repository is not moved.

        The dialog never lists it, so Accept all hints must not move it
        either, even when same-title sources sit on another repository.
        """
        with DbTxn("Setup", self.db) as trans:
            fs_h = self._repo("FamilySearch", trans)
            anc_h = self._repo("Ancestry.com", trans)
            lone_h = self._source("Iowa, Marriages, 1809-1992", fs_h, trans)
            for _number in range(2):
                self._source("Iowa, Marriages, 1809-1992", anc_h, trans)

        rows = build_repo_fix_rows(self.db)
        self.assertEqual(rows, [])
        result = auto_fix_repositories(self.db)
        self.assertEqual(result["reassigned"], 0)
        refs = self.db.get_source_from_handle(lone_h).get_reporef_list()
        self.assertEqual([ref.get_reference_handle() for ref in refs], [fs_h])

    def test_auto_applies_exactly_the_dialog_hints(self) -> None:
        """Accept all hints changes the rows the dialog hints, and only those."""
        with DbTxn("Setup", self.db) as trans:
            misnamed_h = self._repo("familysearch.org", trans)
            self._source("1900 US Census", misnamed_h, trans)
            self._source("Smith family letters", "", trans)
            self._repo("ancestry", trans)  # no sources; plainly Ancestry.com

        rows = build_repo_fix_rows(self.db)
        hinted = sorted(
            (row["repo_name"], row["hint_target"]) for row in rows if row["hint_target"]
        )
        self.assertEqual(
            hinted, [("ancestry", "Ancestry.com"), ("familysearch.org", "FamilySearch")]
        )
        result = auto_fix_repositories(self.db)
        self.assertEqual(result["errors"], [])
        names = sorted(r.get_name() for r in self.db.iter_repositories())
        self.assertEqual(names, ["Ancestry.com", "FamilySearch"])
        # A second run finds nothing more to do.
        self.assertEqual(
            [row for row in build_repo_fix_rows(self.db) if row["hint_target"]], []
        )
        # The wizard's step runs the same function.
        self.assertIn(
            "Changed the repository of 0 sources",
            fix.run_auto_layer("repositories", self.db),
        )

    def test_empty_repository_with_similar_name_is_not_hinted(self) -> None:
        """A source-less repository is only hinted when it plainly is golden."""
        with DbTxn("Setup", self.db) as trans:
            self._repo("Local Government and Municipal Registries (Genoa, IT)", trans)
        rows = build_repo_fix_rows(self.db)
        self.assertEqual([row["hint_target"] for row in rows], [""])


# Test discovery imports every test module before running any, so take the
# fakes off Gtk again now that the GWizard modules are imported; other Gramps
# tests need the real widgets.  setUpModule puts them back for this module.
gwizard_gtk_fakes.uninstall()


if __name__ == "__main__":
    unittest.main()
