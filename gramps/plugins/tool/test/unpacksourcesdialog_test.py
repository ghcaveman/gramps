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

"""Tests for UnpackSourcesDialog."""

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
from gramps.gen.lib import Source, Repository
from gramps.plugins.tool.unpacksourcesdialog import UnpackSourcesDialog


class FakeDbState:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class UnpackSourcesDialogTest(unittest.TestCase):
    """Test UnpackSourcesDialog column layout, accept hints, and apply logic."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = FakeDbState(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_build_rows_and_accept_hints(self) -> None:
        """Test build_rows creates empty target entries and accept_hints populates them."""
        dlg = UnpackSourcesDialog.__new__(UnpackSourcesDialog)
        dlg.dbstate = self.dbstate
        dlg.row_targets = []

        entries = [
            {
                "handle": "s1",
                "gramps_id": "S0001",
                "old_title": "Ancestry.com; 1900 US Census; Roll 123",
                "repo_name": "Ancestry.com",
                "new_title": "1900 US Census",
                "moved_text": "Roll 123",
                "hint_text": "Extract repository 'Ancestry.com'\nSource title to '1900 US Census'",
            }
        ]

        grid_mock = MagicMock()
        with (
            patch(
                "gramps.plugins.tool.unpacksourcesdialog.Gtk.Grid",
                return_value=grid_mock,
            ),
            patch(
                "gramps.plugins.tool.unpacksourcesdialog.Gtk.Entry",
                side_effect=lambda: MagicMock(),
            ),
        ):
            dlg.build_rows(entries)

        self.assertEqual(len(dlg.row_targets), 1)
        target = dlg.row_targets[0]
        target["repo_entry"].set_text.assert_called_with("")
        target["title_entry"].set_text.assert_called_with("")
        target["moved_entry"].set_text.assert_called_with("")

        # Now test accept hints
        target["repo_entry"].get_text.return_value = ""
        target["title_entry"].get_text.return_value = ""
        target["moved_entry"].get_text.return_value = ""

        with patch("gramps.plugins.tool.unpacksourcesdialog.OkDialog"):
            dlg.cb_accept_hints(MagicMock())

        target["repo_entry"].set_text.assert_called_with("Ancestry.com")
        target["title_entry"].set_text.assert_called_with("1900 US Census")
        target["moved_entry"].set_text.assert_called_with("Roll 123")

    def test_cb_apply_commits_to_database(self) -> None:
        """Test applying target values updates the source and links the repository in the database."""
        with DbTxn("Create conflated source", self.db) as trans:
            src = Source()
            src.set_title("Ancestry.com; 1900 Census; Page 1")
            s_handle = self.db.add_source(src, trans)

        dlg = UnpackSourcesDialog.__new__(UnpackSourcesDialog)
        dlg.dbstate = self.dbstate
        dlg.engine = MagicMock()
        dlg.engine._create_repository.return_value = "repo_h"
        dlg.destroy = MagicMock()

        mock_repo = MagicMock()
        mock_repo.get_text.return_value = "Ancestry.com"
        mock_title = MagicMock()
        mock_title.get_text.return_value = "1900 Census"
        mock_moved = MagicMock()
        mock_moved.get_text.return_value = "Page 1"

        dlg.row_targets = [
            {
                "entry": {"handle": s_handle},
                "repo_entry": mock_repo,
                "title_entry": mock_title,
                "moved_entry": mock_moved,
            }
        ]

        with patch("gramps.plugins.tool.unpacksourcesdialog.OkDialog"):
            dlg.cb_apply(MagicMock())

        updated_source = self.db.get_source_from_handle(s_handle)
        self.assertEqual(updated_source.get_title(), "1900 Census")
        self.assertIn("Page 1", updated_source.get_publication_info())
        self.assertEqual(len(updated_source.get_reporef_list()), 1)


if __name__ == "__main__":
    unittest.main()
