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
from gramps.plugins.tool.gw_unpacksourcesdialog import UnpackSourcesDialog
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardcitationshared import split_conflated_title


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
                "gramps.plugins.tool.gw_unpacksourcesdialog.Gtk.Grid",
                return_value=grid_mock,
            ),
            patch(
                "gramps.plugins.tool.gw_unpacksourcesdialog.Gtk.Entry",
                side_effect=lambda: MagicMock(),
            ),
        ):
            dlg.build_rows(entries)

        self.assertEqual(len(dlg.row_targets), 1)
        target = dlg.row_targets[0]
        if hasattr(target["hint_label"], "get_size_request") and not isinstance(
            target["hint_label"].get_size_request(), MagicMock
        ):
            self.assertEqual(target["hint_label"].get_size_request(), (432, -1))
            self.assertEqual(target["hint_label"].get_max_width_chars(), 58)
        else:
            target["hint_label"].set_size_request.assert_called_with(432, -1)
            target["hint_label"].set_max_width_chars.assert_called_with(58)
        target["repo_entry"].set_text.assert_called_with("")
        target["title_entry"].set_text.assert_called_with("")
        target["moved_entry"].set_text.assert_called_with("")

        # Now test accept hints
        target["repo_entry"].get_text.return_value = ""
        target["title_entry"].get_text.return_value = ""
        target["moved_entry"].get_text.return_value = ""

        with patch("gramps.plugins.tool.gw_unpacksourcesdialog.OkDialog"):
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
        # The real engine: cb_apply hands the work to apply_unpack_entries.
        dlg.engine = GWizardCitationRepairEngine()
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

        with patch("gramps.plugins.tool.gw_unpacksourcesdialog.OkDialog"):
            dlg.cb_apply(MagicMock())

        updated_source = self.db.get_source_from_handle(s_handle)
        self.assertEqual(updated_source.get_title(), "1900 Census")
        self.assertIn("Page 1", updated_source.get_publication_info())
        self.assertEqual(len(updated_source.get_reporef_list()), 1)

    def test_dialog_dimensions_and_merged_footer(self) -> None:
        """Verify dialog is 20% wider and has merged footer text without separate header."""
        with DbTxn("Create conflated source", self.db) as trans:
            src = Source()
            src.set_title("Ancestry.com; 1900 Census; Page 1")
            self.db.add_source(src, trans)

        with (
            patch.object(UnpackSourcesDialog, "set_default_size") as mock_set_size,
            patch.object(UnpackSourcesDialog, "add_action_widget"),
            patch.object(UnpackSourcesDialog, "add_button"),
            patch.object(UnpackSourcesDialog, "get_content_area") as mock_content,
            patch(
                "gramps.plugins.tool.gw_unpacksourcesdialog.Gtk.Label"
            ) as mock_label_cls,
        ):
            mock_area = MagicMock()
            mock_content.return_value = mock_area
            UnpackSourcesDialog(dbstate=self.dbstate)
            mock_set_size.assert_called_with(1272, 520)

            # Check label calls to find merged footer text
            labels_created = [
                call.kwargs.get("label", "") for call in mock_label_cls.call_args_list
            ]
            merged_footer_found = any(
                "Parse mixed text headers" in text and "Citation-style text" in text
                for text in labels_created
            )
            self.assertTrue(merged_footer_found)


class SplitConflatedTitleTest(unittest.TestCase):
    """Splitting a mixed title is complete in one pass and loses nothing."""

    CASES = [
        (
            "Newspapers.com Obituary Index, 1800s-current "
            "(Repository: Newspapers.com, Source: Obituary Index)",
            ("Newspapers.com", "Obituary Index, 1800s-current", ""),
        ),
        (
            "Ancestry.com; 1900 Census; Page 1",
            ("Ancestry.com", "1900 Census", "Page 1"),
        ),
        (
            "1940 Census (from Ancestry.com, page 2)",
            ("Ancestry.com", "1940 Census", "page 2"),
        ),
        (
            "Census (Repository: Some Local Library, Source: State Census)",
            ("Some Local Library", "Census", "State Census"),
        ),
        (
            "https://www.familysearch.org/ark:/61903/1:1:XYZ Pennsylvania "
            "Marriages; Ancestry.com; Vol 3",
            (
                "FamilySearch",
                "Pennsylvania Marriages",
                "Ancestry.com; https://www.familysearch.org/ark:/61903/1:1:XYZ; "
                "Vol 3",
            ),
        ),
    ]

    def test_split_results(self) -> None:
        """Each title gives the expected repository, title and moved text."""
        for title, (repo, new_title, moved) in self.CASES:
            with self.subTest(title=title):
                result = split_conflated_title(title)
                assert result is not None
                self.assertEqual(result["repo_name"], repo)
                self.assertEqual(result["new_title"], new_title)
                self.assertEqual(result["moved_text"], moved)

    def test_second_split_finds_nothing(self) -> None:
        """The new title has no repository text left and no stray brackets."""
        for title, _expected in self.CASES:
            with self.subTest(title=title):
                result = split_conflated_title(title)
                assert result is not None
                self.assertIsNone(split_conflated_title(result["new_title"]))
                self.assertEqual(
                    result["new_title"].count("("), result["new_title"].count(")")
                )

    def test_unpack_step_is_stable(self) -> None:
        """Running the unpack step again changes nothing and adds no repository."""
        db: DbWriteBase = make_database("sqlite")
        db.load(":memory:")
        try:
            with DbTxn("Setup", db) as trans:
                for title, _expected in self.CASES:
                    src = Source()
                    src.set_title(title)
                    db.add_source(src, trans)
            engine = GWizardCitationRepairEngine()
            self.assertGreater(engine.unpack_conflated_sources(db), 0)
            titles = sorted(src.get_title() for src in db.iter_sources())
            repos = db.get_number_of_repositories()
            self.assertEqual(engine.unpack_conflated_sources(db), 0)
            self.assertEqual(
                sorted(src.get_title() for src in db.iter_sources()), titles
            )
            self.assertEqual(db.get_number_of_repositories(), repos)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
