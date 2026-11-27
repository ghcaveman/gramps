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

"""
Tests for gwizard_mediafix_basepath: the question a GWizard tool asks
before it opens when the family tree has no base media path.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import shutil
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.plugins.tool.test import gwizard_gtk_fakes as fakes

Gtk = fakes.install()

from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Media
from gramps.plugins.tool import gwizard_mediafix_basepath as bp
from gramps.plugins.tool import gwizardmediafix as mf


def setUpModule() -> None:
    """Install the GTK fakes for this module's tests."""
    fakes.install()


def tearDownModule() -> None:
    """Restore the real GTK classes for other test modules."""
    fakes.uninstall()


class _DbState:
    """Minimal stand-in for Gramps' DbState."""

    def __init__(self, db: Any, is_open: bool = True) -> None:
        self.db = db
        self._open = is_open

    def is_open(self) -> bool:
        return self._open


class EnsureBaseMediaPathTest(unittest.TestCase):
    """ensure_base_media_path asks only when no base media path is set."""

    def setUp(self) -> None:
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.tmp = tempfile.mkdtemp()
        self.folder = os.path.join(self.tmp, "FamilyTree")
        os.makedirs(self.folder)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ensure(self, choose: bool, folder: str = "", is_open: bool = True) -> Any:
        """Run ensure_base_media_path with the given answers."""
        question = MagicMock()
        question.return_value.run.return_value = choose
        chooser = MagicMock()
        chooser.run.return_value = (
            Gtk.ResponseType.OK if folder else Gtk.ResponseType.CANCEL
        )
        chooser.get_filename.return_value = folder or None
        with (
            patch.object(bp, "QuestionDialog2", question),
            patch.object(bp.Gtk, "FileChooserDialog", return_value=chooser),
            patch.object(bp, "OkDialog"),
        ):
            result = bp.ensure_base_media_path(
                _DbState(self.db, is_open), None, "GWizard Test Tool"
            )
        self.question = question
        return result

    def test_set_path_asks_nothing(self) -> None:
        self.db.set_mediapath(self.folder)
        self.assertTrue(self.ensure(choose=True, folder=self.folder))
        self.question.assert_not_called()

    def test_no_tree_open_asks_nothing(self) -> None:
        self.assertFalse(self.ensure(choose=True, folder=self.folder, is_open=False))
        self.question.assert_not_called()

    def test_declined_leaves_it_unset(self) -> None:
        self.assertFalse(self.ensure(choose=False))
        self.question.assert_called_once()
        message = self.question.call_args[0][1]
        self.assertIn("GWizard Test Tool", message)
        self.assertIn("Base media path", message)
        self.assertFalse((self.db.get_mediapath() or "").strip())

    def test_cancelled_chooser_leaves_it_unset(self) -> None:
        self.assertFalse(self.ensure(choose=True, folder=""))
        self.assertFalse((self.db.get_mediapath() or "").strip())

    def test_chosen_folder_is_saved(self) -> None:
        self.assertTrue(self.ensure(choose=True, folder=self.folder))
        self.assertEqual(os.path.normpath(self.db.get_mediapath()), self.folder)

    def test_existing_records_keep_their_files(self) -> None:
        """Setting the path repoints relative records that found their file."""
        old = os.path.join(self.tmp, "old")
        os.makedirs(old)
        with open(os.path.join(old, "a.jpg"), "w", encoding="utf-8") as out:
            out.write("a")
        self.db.set_mediapath(old)
        with DbTxn("add", self.db) as trans:
            media = Media()
            media.set_path("a.jpg")
            self.db.add_media(media, trans)
        # The record is found through the old setting; treat the tree as
        # having none so the question is asked, then choose a new folder.
        with (
            patch.object(bp, "QuestionDialog2") as question,
            patch.object(bp.Gtk, "FileChooserDialog") as chooser_cls,
            patch.object(bp, "OkDialog"),
            patch.object(bp, "base_media_path_set", return_value=False),
        ):
            question.return_value.run.return_value = True
            chooser = chooser_cls.return_value
            chooser.run.return_value = Gtk.ResponseType.OK
            chooser.get_filename.return_value = self.folder
            self.assertTrue(
                bp.ensure_base_media_path(_DbState(self.db), None, "GWizard Test")
            )
        (media,) = list(self.db.iter_media())
        self.assertEqual(
            os.path.normpath(
                os.path.join(mf.get_media_base_path(self.db), media.get_path())
            ),
            os.path.normpath(os.path.join(old, "a.jpg")),
        )

    def test_for_tool_never_raises(self) -> None:
        with patch.object(bp, "ensure_base_media_path", side_effect=RuntimeError):
            self.assertFalse(bp.ensure_base_media_path_for(None, None, "GWizard X"))


class MediaFixOpensAfterAskingTest(unittest.TestCase):
    """GWizard Media Fix asks before it builds its window."""

    def test_init_asks_then_builds(self) -> None:
        calls: list[str] = []
        with (
            patch.object(mf.tool.Tool, "__init__", return_value=None),
            patch.object(mf.ManagedWindow, "__init__", return_value=None),
            patch.object(
                bp,
                "ensure_base_media_path_for",
                side_effect=lambda *a: calls.append("ask"),
            ),
            patch.object(
                mf.GWizardMediaFix,
                "_build_window",
                side_effect=lambda *a: calls.append("build"),
            ),
            patch.object(mf.GWizardMediaFix, "show"),
        ):
            mf.GWizardMediaFix(MagicMock(), MagicMock(), MagicMock(), "name")
        self.assertEqual(calls, ["ask", "build"])


if __name__ == "__main__":
    unittest.main()
