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

"""Tests for RepoConsolidateDialog, hint generation, and repository consolidations."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import tempfile
import unittest
from typing import Any
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
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.gen.errors import HandleError
from gramps.gen.lib import Address, Repository, Source, RepoRef
from gramps.plugins.tool.gw_repoconsolidatedialog import (
    RepoConsolidateDialog,
    apply_repo_consolidations,
    auto_consolidate_repositories,
    build_repo_consolidate_rows,
    classify_repo_street,
)


class FakeDbState:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class RepoConsolidateDialogTest(unittest.TestCase):
    """Test suite for repository consolidate dialog row building and hints."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = FakeDbState(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_classify_repo_street(self) -> None:
        """Street repeating name should be dropped; extra detail should be moved."""
        self.assertEqual(classify_repo_street("Ancestry", "Ancestry"), ("drop", ""))
        self.assertEqual(
            classify_repo_street("The National Archives", "The National Archives"),
            ("drop", ""),
        )
        act, detail = classify_repo_street(
            "State Archives", "State Archives (Microfilm Room)"
        )
        self.assertEqual(act, "move")
        self.assertEqual(detail, "Microfilm Room")
        self.assertEqual(classify_repo_street("Ancestry", "123 Main St")[0], "keep")

    def test_build_repo_consolidate_rows_duplicates(self) -> None:
        """Duplicate repositories should produce rows where keeper has blank hint and duplicate points to keeper."""
        with DbTxn("Create repos", self.db) as trans:
            r1 = Repository()
            r1.set_name("FamilySearch")
            r1_handle = self.db.add_repository(r1, trans)

            r2 = Repository()
            r2.set_name("FamilySearch.org")
            r2_handle = self.db.add_repository(r2, trans)

            # Link a source to r1
            s = Source()
            s.set_title("Test Source")
            ref = RepoRef()
            ref.set_reference_handle(r1_handle)
            s.add_repo_reference(ref)
            self.db.add_source(s, trans)

        rows = build_repo_consolidate_rows(self.db)
        self.assertEqual(len(rows), 2)

        # r1 should be keeper (is_golden name FamilySearch + 1 source)
        keeper_row = next(r for r in rows if r["handle"] == r1_handle)
        dup_row = next(r for r in rows if r["handle"] == r2_handle)

        self.assertTrue(keeper_row["is_keeper"])
        self.assertEqual(keeper_row["hint_target"], "")
        self.assertEqual(keeper_row["options"][0][1], r1_handle)

        self.assertFalse(dup_row["is_keeper"])
        self.assertEqual(dup_row["hint_target"], r1_handle)
        self.assertIn("FamilySearch", dup_row["hint_display"])

    def test_build_repo_consolidate_rows_golden_match(self) -> None:
        """Repository with golden-standard match should suggest the golden name."""
        with DbTxn("Create repo", self.db) as trans:
            r = Repository()
            r.set_name("FindAGrave")  # Matches "Find a Grave"
            r_handle = self.db.add_repository(r, trans)

        rows = build_repo_consolidate_rows(self.db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["handle"], r_handle)
        self.assertIn("Find a Grave", row["hint_display"])
        self.assertIn("Gold-standard match", row["hint_reason"])

    def test_repo_consolidate_dialog_structure_and_accept_hints(self) -> None:
        """Dialog initializes with Accept hints, Apply, and Close buttons; accept hints works."""
        with DbTxn("Create repos", self.db) as trans:
            r1 = Repository()
            r1.set_name("Ancestry.com")
            r1_h = self.db.add_repository(r1, trans)

            r2 = Repository()
            r2.set_name("ancestry")
            r2_h = self.db.add_repository(r2, trans)

        dlg = RepoConsolidateDialog(self.dbstate)

        # Verify buttons exist
        self.assertTrue(hasattr(dlg, "accept_button"))
        self.assertTrue(hasattr(dlg, "apply_button"))

        # Accept hints
        mock_button = MagicMock()
        with patch("gramps.plugins.tool.gw_repoconsolidatedialog.OkDialog"):
            dlg.cb_accept_hints(mock_button)

        choices = dlg.get_choices()
        self.assertEqual(choices[r2_h], r1_h)

    def test_repo_consolidate_apply_merges_and_tidies(self) -> None:
        """Apply merges duplicate repository into keeper and cleans up address."""
        with DbTxn("Create repos and source", self.db) as trans:
            r1 = Repository()
            r1.set_name("Library of Congress")
            r1_h = self.db.add_repository(r1, trans)

            r2 = Repository()
            r2.set_name("library of congress")
            addr = Address()
            addr.set_street("Library of Congress")  # Redundant street
            r2.set_address_list([addr])
            r2_h = self.db.add_repository(r2, trans)

            s = Source()
            s.set_title("LOC Book")
            ref = RepoRef()
            ref.set_reference_handle(r2_h)
            s.add_repo_reference(ref)
            s_h = self.db.add_source(s, trans)

        dlg = RepoConsolidateDialog(self.dbstate)
        # Set r2 to merge into r1
        for row, combo in dlg.row_combos:
            if row["handle"] == r2_h:
                combo._user_target = r1_h

        with patch("gramps.plugins.tool.gw_repoconsolidatedialog.OkDialog"):
            dlg.cb_apply(MagicMock())

        # Verify r2 was merged into r1
        with self.assertRaises(HandleError):
            self.db.get_repository_from_handle(r2_h)
        self.assertIsNotNone(self.db.get_repository_from_handle(r1_h))

        # Verify source now points to r1
        updated_s = self.db.get_source_from_handle(s_h)
        self.assertIsNotNone(updated_s)
        self.assertEqual(updated_s.get_reporef_list()[0].get_reference_handle(), r1_h)


class RepoConsolidateSafetyTest(unittest.TestCase):
    """Only sure duplicates are merged without asking; failures change nothing."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(tempfile.mkdtemp())

    def tearDown(self) -> None:
        self.db.close()

    def _add(self, *names: str) -> list[str]:
        handles = []
        with DbTxn("Setup", self.db) as trans:
            for name in names:
                repo = Repository()
                repo.set_name(name)
                handles.append(self.db.add_repository(repo, trans))
        return handles

    def _names(self) -> list[str]:
        return sorted(r.get_name() for r in self.db.iter_repositories())

    def test_similar_names_are_not_merged_automatically(self) -> None:
        """Different places with similar names stay separate."""
        names = (
            "Ohio County Courthouse",
            "Iowa County Courthouse",
            "St Marys Church",
            "St Marks Church",
            "Pennsylvania State Archives",
            "Archives",
            "National Archives of Ireland",
        )
        self._add(*names)
        rows = build_repo_consolidate_rows(self.db)
        self.assertTrue(rows)
        self.assertFalse(any(row["confident"] for row in rows))
        hinted = [row for row in rows if row["hint_target"]]
        self.assertTrue(hinted)
        for row in hinted:
            self.assertIn("check before merging", row["hint_display"])
        self.assertEqual(auto_consolidate_repositories(self.db)["merged"], 0)
        self.assertEqual(self._names(), sorted(names))

    def test_same_repository_names_are_merged(self) -> None:
        """Spellings of the same golden repository are merged without asking."""
        self._add(
            "Ancestry",
            "ancestry.com",
            "NARA",
            "The National Archives and Records Administration (NARA)",
        )
        result = auto_consolidate_repositories(self.db)
        self.assertEqual(result["merged"], 2)
        self.assertEqual(self.db.get_number_of_repositories(), 2)

    def test_failed_merge_rolls_back_everything(self) -> None:
        """An error part way through leaves the database as it was."""
        keep, gone1, keep2, gone2 = self._add("A", "B", "C", "D")
        before = self._names()
        engine = GWizardCitationRepairEngine()
        real_merge = engine.merge_repositories
        calls = []

        def merge_then_fail(*args: Any, **kwargs: Any) -> bool:
            calls.append(args)
            if len(calls) == 2:
                raise RuntimeError("disk full")
            return real_merge(*args, **kwargs)

        engine.merge_repositories = merge_then_fail  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            apply_repo_consolidations(self.db, [(gone1, keep), (gone2, keep2)], engine)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self._names(), before)


if __name__ == "__main__":
    unittest.main()
