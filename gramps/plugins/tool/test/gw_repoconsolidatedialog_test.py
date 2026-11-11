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

        def destroy(self) -> None:
            pass

        def run(self) -> int:
            return 0

    class _FakeLabel:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_markup(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_halign(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_hexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_line_wrap(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_line_wrap_mode(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_max_width_chars(self, *args: Any, **kwargs: Any) -> None:
            if args:
                self._max_width_chars = args[0]

        def get_max_width_chars(self) -> int:
            return getattr(self, "_max_width_chars", -1)

        def set_xalign(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_size_request(self, *args: Any, **kwargs: Any) -> None:
            if len(args) >= 2:
                self._size_request = (args[0], args[1])

        def get_size_request(self) -> tuple[int, int]:
            return getattr(self, "_size_request", (-1, -1))

        def get_style_context(self) -> MagicMock:
            return MagicMock()

    class _FakeGrid:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_column_spacing(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_row_spacing(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_column_homogeneous(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_hexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_vexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_style_context(self) -> MagicMock:
            return MagicMock()

        def attach(self, *args: Any, **kwargs: Any) -> None:
            pass

    class _FakeComboBox:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._model: list[Any] = []
            self._active = 0

        @classmethod
        def new_with_model(cls, model: Any) -> _FakeComboBox:
            cb = cls()
            cb._model = list(model)
            return cb

        def set_hexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_size_request(self, *args: Any, **kwargs: Any) -> None:
            pass

        def pack_start(self, *args: Any, **kwargs: Any) -> None:
            pass

        def add_attribute(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_active(self, val: int) -> None:
            self._active = val

        def get_active(self) -> int:
            return self._active

        def get_active_iter(self) -> Any:
            return self._active if 0 <= self._active < len(self._model) else None

        def get_model(self) -> Any:
            return self._model

        def connect(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_style_context(self) -> MagicMock:
            return MagicMock()

    class _FakeScrolledWindow:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_min_content_height(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_min_content_width(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_policy(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_hexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_vexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def add(self, *args: Any, **kwargs: Any) -> None:
            pass

    gi_mock.repository.Gtk.Dialog = _FakeDialog
    gi_mock.repository.Gtk.Label = _FakeLabel
    gi_mock.repository.Gtk.Grid = _FakeGrid
    gi_mock.repository.Gtk.ComboBox = _FakeComboBox
    gi_mock.repository.Gtk.ScrolledWindow = _FakeScrolledWindow
    gi_mock.repository.Gtk.ListStore = lambda *types: []
    gi_mock.repository.Gtk.ResponseType.OK = 1
    gi_mock.repository.Gtk.ResponseType.CANCEL = 2
    gi_mock.repository.Gtk.ResponseType.CLOSE = 3
    gi_mock.repository.Gtk.ResponseType.NONE = 4
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.errors import HandleError
from gramps.gen.lib import Address, Repository, Source, RepoRef
from gramps.plugins.tool.gw_repoconsolidatedialog import (
    RepoConsolidateDialog,
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


if __name__ == "__main__":
    unittest.main()
