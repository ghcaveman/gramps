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

"""Tests for 'Look in folder...' in Find missing media.

The user picks a folder; missing files are found there by the old folder
layout (a verified folder remap), by content, or by file name, previewed,
and filled in only where a matching file exists.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import hashlib
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
from gramps.gen.lib import Media, MediaRef, Person
from gramps.plugins.tool import gwizard_mediafix_common as gc
from gramps.plugins.tool import gwizardmediafix as mf

_CHOOSER = "gramps.plugins.tool.gwizardmediafix.Gtk.FileChooserDialog"
_CONFIRM = "gramps.plugins.tool.gwizardmediafix.confirm_text"
_OK = "gramps.plugins.tool.gwizardmediafix.OkDialog"


def setUpModule() -> None:
    """Install the GTK fakes for this module's tests."""
    fakes.install()


def tearDownModule() -> None:
    """Restore the real GTK classes for other test modules."""
    fakes.uninstall()


def md5(content: str) -> str:
    """Return the MD5 of some text, as a stored checksum."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()


class _DbState:
    """Minimal stand-in for Gramps' DbState."""

    def __init__(self, db: object) -> None:
        self.db = db


# ------------------------------------------------------------
#
# _FolderTest
#
# ------------------------------------------------------------
class _FolderTest(unittest.TestCase):
    """A tree, a media base folder and a folder to look in."""

    def setUp(self) -> None:
        gc._CHECKSUM_CACHE.clear()
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = _DbState(self.db)
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "MediaBase")
        os.makedirs(self.base)
        self.db.set_mediapath(self.base)
        self.look = os.path.join(self.tmp, "Backup", "Pictures")
        os.makedirs(self.look)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        gc._CHECKSUM_CACHE.clear()

    def write(self, rel: str, content: str = "", root: str | None = None) -> str:
        """Write a file below *root* (the folder to look in) and return it."""
        path = os.path.join(root or self.look, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content or rel)
        return path

    def add_media(self, path: str, checksum: str = "") -> str:
        """Add a referenced media record and return its handle."""
        with DbTxn("add media", self.db) as trans:
            media = Media()
            media.set_path(path)
            media.set_checksum(checksum)
            handle = self.db.add_media(media, trans)
            person = Person()
            ref = MediaRef()
            ref.set_reference_handle(handle)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)
        return handle

    def search(self, *records: tuple[str, str, str]) -> dict[str, dict[str, str]]:
        """Run find_in_chosen_folder for (handle, path, checksum) rows."""
        index = gc.build_basename_index(self.look)
        files = [p for paths in index.values() for p in paths]
        content = mf.missing_content_index(files, [(r, c) for _h, r, c in records])
        return mf.find_in_chosen_folder(list(records), self.look, index, content)


# ------------------------------------------------------------
#
# FolderSegmentsTest
#
# ------------------------------------------------------------
class FolderSegmentsTest(unittest.TestCase):
    """Old paths are split into a root and folder names."""

    def test_roots(self) -> None:
        """Drives, Unix roots, shares and relative paths."""
        cases = {
            "D:/OldPC/Pictures/a.jpg": ("D:", ["OldPC", "Pictures"]),
            "C:\\Users\\Ann\\scan.tif": ("C:", ["Users", "Ann"]),
            "/home/ann/a.jpg": ("/", ["home", "ann"]),
            "\\\\server\\share\\a.jpg": ("//", ["server", "share"]),
            "photos/1910/a.jpg": ("", ["photos", "1910"]),
            "a.jpg": ("", []),
        }
        for raw, expected in cases.items():
            self.assertEqual(mf._folder_segments(raw), expected, raw)
        self.assertEqual(mf._join_old_folder("D:", ["Old"]), "D:/Old")
        self.assertEqual(mf._join_old_folder("//", ["srv", "x"]), "//srv/x")
        self.assertEqual(mf._join_old_folder("", []), ".")


# ------------------------------------------------------------
#
# FindInChosenFolderTest
#
# ------------------------------------------------------------
class FindInChosenFolderTest(_FolderTest):
    """How files are matched in the chosen folder."""

    def test_folder_layout_remap(self) -> None:
        """A moved folder is found with its subfolders, case-insensitively."""
        a = self.write("1910/a.jpg")
        b = self.write("1920/b.jpg")
        c = self.write("c.jpg")
        res = self.search(
            ("h1", "D:/OldPC/Pictures/1910/a.jpg", ""),
            ("h2", "D:/OLDPC/PICTURES/1920/B.JPG", ""),
            ("h3", "D:/OldPC/Pictures/c.jpg", ""),
        )
        self.assertEqual([res[h]["file"] for h in ("h1", "h2", "h3")], [a, b, c])
        self.assertTrue(all(res[h]["how"] == "folder" for h in res))
        self.assertEqual(res["h1"]["mapped_from"], "D:/OldPC/Pictures")

    def test_layout_follows_the_majority(self) -> None:
        """When a file could map two ways, the layout most records share wins."""
        self.write("a.jpg", "decoy")
        deep = self.write("1910/a.jpg")
        self.write("1910/b.jpg")
        self.write("1910/c.jpg")
        res = self.search(
            ("h1", "D:/Old/Pictures/1910/a.jpg", ""),
            ("h2", "D:/Old/Pictures/1910/b.jpg", ""),
            ("h3", "D:/Old/Pictures/1910/c.jpg", ""),
        )
        self.assertEqual(res["h1"]["file"], deep)
        self.assertEqual(res["h1"]["mapped_from"], "D:/Old/Pictures")

    def test_tie_is_not_used(self) -> None:
        """Two equally likely layouts: no file, and the reason is given."""
        self.write("a.jpg")
        self.write("1910/a.jpg")
        res = self.search(("h1", "D:/Old/1910/a.jpg", ""))
        self.assertEqual(res["h1"]["file"], "")
        self.assertIn("2 files with this name", res["h1"]["note"])

    def test_found_by_content(self) -> None:
        """A renamed file is found from the record's checksum."""
        renamed = self.write("people/Smith_John.jpg", "john")
        res = self.search(("h1", "D:/Old/IMG_0492.JPG", md5("john")))
        self.assertEqual((res["h1"]["file"], res["h1"]["how"]), (renamed, "content"))

    def test_found_by_unique_name(self) -> None:
        """A file in an unrelated subfolder is found by its unique name."""
        other = self.write("sorted/misc/z.jpg")
        res = self.search(("h1", "D:/X/Y/z.jpg", ""))
        self.assertEqual((res["h1"]["file"], res["h1"]["how"]), (other, "name"))

    def test_checksum_rejects_wrong_content(self) -> None:
        """A layout or name match with other content is not used."""
        self.write("1910/a.jpg", "someone else")
        res = self.search(("h1", "D:/Old/Pictures/1910/a.jpg", md5("original")))
        self.assertEqual(res["h1"]["file"], "")
        self.assertIn("different content", res["h1"]["note"])

    def test_same_file_for_different_records_held_back(self) -> None:
        """One file found for two different records is given to neither."""
        self.write("z.jpg")
        res = self.search(("h1", "D:/A/z.jpg", ""), ("h2", "E:/B/z.jpg", ""))
        for handle in ("h1", "h2"):
            self.assertEqual(res[handle]["file"], "")
            self.assertIn("other records", res[handle]["note"])

    def test_preview_text(self) -> None:
        """The preview groups by old folder and counts what is not found."""
        self.write("1910/a.jpg")
        self.write("1910/b.jpg")
        self.write("renamed.jpg", "c")
        res = self.search(
            ("h1", "D:/OldPC/Pictures/1910/a.jpg", ""),
            ("h2", "D:/OldPC/Pictures/1910/b.jpg", ""),
            ("h3", "D:/OldPC/Pictures/c.jpg", md5("c")),
            ("h4", "D:/OldPC/Docs/letter.pdf", ""),
            ("h5", "D:/OldPC/Docs/will.pdf", ""),
        )
        text, count = mf.format_folder_search(res, self.look, {})
        self.assertEqual(count, 3)
        self.assertIn("D:/OldPC/Pictures  ->  %s: 2 records" % self.look, text)
        self.assertIn("Found by content (renamed or moved files): 1", text)
        self.assertIn("Not found in this folder (2), by old folder:", text)
        self.assertIn("D:/OldPC/Docs: 2", text)
        self.assertIn("Nothing is saved until you press 'Apply'", text)


# ------------------------------------------------------------
#
# LookInFolderDialogTest
#
# ------------------------------------------------------------
class LookInFolderDialogTest(_FolderTest):
    """The 'Look in folder...' button in Find missing media."""

    def dialog(self) -> mf.FindMissingMediaDialog:
        """Open Find missing media on the test tree."""
        return mf.FindMissingMediaDialog(dbstate=self.dbstate)

    def target(self, dlg: Any, handle: str) -> dict[str, Any]:
        """Return the dialog row for a media handle."""
        return next(t for t in dlg.row_targets if t["entry"]["handle"] == handle)

    def look_in(self, dlg: Any, folder: str | None, accept: bool = True) -> Any:
        """Press 'Look in folder...', choose *folder*, answer the preview."""
        chooser = MagicMock()
        chooser.run.return_value = (
            Gtk.ResponseType.OK if folder else Gtk.ResponseType.CANCEL
        )
        chooser.get_filename.return_value = folder
        with (
            patch(_CHOOSER, return_value=chooser),
            patch(_CONFIRM, return_value=accept) as confirm,
            patch(_OK) as ok_dialog,
        ):
            dlg.cb_look_in_folder(MagicMock())
        return confirm, ok_dialog

    def test_fills_found_rows_and_apply_saves(self) -> None:
        """Found files fill empty rows only; Apply stores them with checksums."""
        found = self.write("1910/a.jpg", "a photo")
        h_found = self.add_media("D:/OldPC/Pictures/1910/a.jpg")
        h_typed = self.add_media("D:/OldPC/Pictures/1910/b.jpg")
        h_none = self.add_media("D:/OldPC/Docs/will.pdf")
        dlg = self.dialog()
        self.target(dlg, h_typed)["path_entry"].set_text("typed/by/user.jpg")
        confirm, _ok = self.look_in(dlg, self.look)
        confirm.assert_called_once()
        self.assertIn("1 file", confirm.call_args[0][3])
        row = self.target(dlg, h_found)
        self.assertEqual(row["picked"], found)
        self.assertIn("same folder layout", row["hint_label"].text)
        self.assertEqual(
            self.target(dlg, h_typed)["path_entry"].get_text(), "typed/by/user.jpg"
        )
        self.assertEqual(self.target(dlg, h_none)["path_entry"].get_text(), "")

        with patch(_OK):
            dlg.cb_apply(MagicMock())
        media = self.db.get_media_from_handle(h_found)
        self.assertEqual(media.get_path(), found)  # outside the base: absolute
        self.assertEqual(media.get_checksum(), md5("a photo"))

    def test_inside_base_path_stored_relative(self) -> None:
        """A file found inside the media base path is shown relative to it."""
        inside = self.write("Pictures/1910/a.jpg", root=self.base)
        handle = self.add_media("D:/OldPC/Pictures/1910/a.jpg")
        dlg = self.dialog()
        self.look_in(dlg, self.base)
        row = self.target(dlg, handle)
        self.assertEqual(row["picked"], inside)
        self.assertEqual(row["path_entry"].get_text(), "Pictures/1910/a.jpg")

    def test_cancelled_preview_changes_nothing(self) -> None:
        """Cancelling the preview fills nothing."""
        self.write("1910/a.jpg")
        handle = self.add_media("D:/OldPC/Pictures/1910/a.jpg")
        dlg = self.dialog()
        self.look_in(dlg, self.look, accept=False)
        self.assertEqual(self.target(dlg, handle)["path_entry"].get_text(), "")

    def test_nothing_found_says_so(self) -> None:
        """When nothing is found, a message replaces the preview."""
        self.add_media("D:/OldPC/Docs/will.pdf")
        dlg = self.dialog()
        confirm, ok_dialog = self.look_in(dlg, self.look)
        confirm.assert_not_called()
        ok_dialog.assert_called_once()
        self.assertIn("D:/OldPC/Docs: 1", ok_dialog.call_args[0][1])

    def test_copy_from_folder_removed(self) -> None:
        """'Look in folder...' replaced 'Copy from folder...'."""
        self.add_media("D:/OldPC/Docs/will.pdf")
        dlg = self.dialog()
        # The fake dialog answers any attribute, so look at what was set.
        self.assertIn("look_button", vars(dlg))
        self.assertNotIn("copy_button", vars(dlg))
        self.assertFalse(hasattr(mf.FindMissingMediaDialog, "cb_copy_from_folder"))

    def test_no_folder_chosen(self) -> None:
        """Cancelling the folder chooser does nothing."""
        self.add_media("D:/OldPC/Docs/will.pdf")
        dlg = self.dialog()
        confirm, ok_dialog = self.look_in(dlg, None)
        confirm.assert_not_called()
        ok_dialog.assert_not_called()


fakes.uninstall()

if __name__ == "__main__":
    unittest.main()
