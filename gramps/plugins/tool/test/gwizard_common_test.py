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

"""Tests for shared GWizard UI widgets and utilities."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock

# -------------------------------------------------------------------------
#
# GTK mock fallback when running without display or PyGObject
#
# -------------------------------------------------------------------------
if "gi" not in sys.modules:
    gi_mock = MagicMock()
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository

from gi.repository import Gtk


class _FakeDialog:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.response: Any = None

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

    def run(self) -> Any:
        if self.response is not None:
            return self.response
        return getattr(Gtk.ResponseType, "OK", 1)


class _FakeLabel:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.selectable = False
        self.can_focus = True
        self.line_wrap = False
        self.text = ""
        self.markup = ""
        self.max_width_chars: int | None = None
        self.size_request: tuple[int, int] | None = None
        self.xalign = 0.5
        self.halign: Any = None

    def set_text(self, val: str) -> None:
        self.text = val

    def set_markup(self, val: str) -> None:
        self.markup = val

    def set_use_markup(self, val: bool) -> None:
        pass

    def set_selectable(self, val: bool) -> None:
        self.selectable = val

    def set_can_focus(self, val: bool) -> None:
        self.can_focus = val

    def set_line_wrap(self, val: bool) -> None:
        self.line_wrap = val

    def set_line_wrap_mode(self, val: Any) -> None:
        pass

    def set_halign(self, val: Any) -> None:
        self.halign = val

    def set_xalign(self, val: float) -> None:
        self.xalign = val

    def set_max_width_chars(self, val: int) -> None:
        self.max_width_chars = val

    def set_size_request(self, w: int, h: int) -> None:
        self.size_request = (w, h)

    def set_hexpand(self, val: bool) -> None:
        self.hexpand = val

    def set_vexpand(self, val: bool) -> None:
        self.vexpand = val


class _FakeGrid:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.col_spacing = 0
        self.row_spacing = 0
        self.hexpand = False
        self.vexpand = False

    def set_column_spacing(self, val: int) -> None:
        self.col_spacing = val

    def set_row_spacing(self, val: int) -> None:
        self.row_spacing = val

    def set_hexpand(self, val: bool) -> None:
        self.hexpand = val

    def set_vexpand(self, val: bool) -> None:
        self.vexpand = val

    def attach(self, *args: Any, **kwargs: Any) -> None:
        pass


Gtk.Dialog = _FakeDialog
Gtk.Label = _FakeLabel
Gtk.Grid = _FakeGrid

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Media, Tag
from gramps.plugins.tool.gwizard_common import (
    SelectableLabel,
    TableLabel,
    HeaderLabel,
    create_table_grid,
    clean_path,
    is_absolute_path,
    path_key,
    to_db_path,
    unique_destination,
    relocate_file,
    build_basename_index,
    TAG_MEDIA_FIXED,
    TAG_MEDIA_FIXED_COLOR,
    TAG_LOCKED,
    TAG_LOCKED_COLOR,
    create_gwizard_tag,
    ensure_tag,
    ensure_gwizard_tags,
    is_media_locked,
    has_media_fixed_tag,
    add_media_fixed_tag,
    lock_media,
    unlock_media,
)


# ------------------------------------------------------------
#
# GWizardCommonTest
#
# ------------------------------------------------------------
class GWizardCommonTest(unittest.TestCase):
    """Test suite for GWizard common UI widgets and path utilities."""

    def test_selectable_label_defaults(self) -> None:
        """SelectableLabel initializes with selectable=True, left alignment, and wrapping."""
        lbl = SelectableLabel("Test copyable text")
        self.assertTrue(lbl.selectable)
        self.assertFalse(lbl.can_focus)
        self.assertTrue(lbl.line_wrap)
        self.assertEqual(lbl.text, "Test copyable text")

    def test_table_label(self) -> None:
        """TableLabel inherits from SelectableLabel and sets constraints."""
        tbl_lbl = TableLabel(
            "Cell text", width_chars=30, width_request=240, markup=False
        )
        self.assertIsInstance(tbl_lbl, SelectableLabel)
        self.assertTrue(tbl_lbl.selectable)
        self.assertEqual(tbl_lbl.text, "Cell text")
        self.assertEqual(tbl_lbl.max_width_chars, 30)
        self.assertEqual(tbl_lbl.size_request, (240, -1))

    def test_header_label(self) -> None:
        """HeaderLabel inherits from SelectableLabel and displays bold markup."""
        hdr = HeaderLabel("Column Title")
        self.assertIsInstance(hdr, SelectableLabel)
        self.assertTrue(hdr.selectable)
        self.assertEqual(hdr.markup, "<b>Column Title</b>")

    def test_create_table_grid(self) -> None:
        """create_table_grid sets spacing and expansion defaults."""
        grid = create_table_grid(col_spacing=8, row_spacing=4)
        self.assertEqual(grid.col_spacing, 8)
        self.assertEqual(grid.row_spacing, 4)
        self.assertTrue(grid.hexpand)
        self.assertTrue(grid.vexpand)

    def test_clean_path(self) -> None:
        """clean_path strips whitespace and matching quotes, retaining legitimate apostrophes."""
        self.assertEqual(clean_path(None), "")
        self.assertEqual(clean_path(""), "")
        self.assertEqual(clean_path("   "), "")
        self.assertEqual(clean_path('  "C:/path/file.jpg"  '), "C:/path/file.jpg")
        self.assertEqual(clean_path("  'C:/path/file.jpg'  "), "C:/path/file.jpg")
        self.assertEqual(clean_path('""nested""'), "nested")
        # Unmatched double quotes stripped
        self.assertEqual(clean_path('"file.jpg'), "file.jpg")
        self.assertEqual(clean_path('file.jpg"'), "file.jpg")
        # Legitimate trailing apostrophe retained
        self.assertEqual(clean_path("Grandma's"), "Grandma's")

    def test_is_absolute_path(self) -> None:
        """is_absolute_path identifies drive letters, posix roots, and rooted driveless paths."""
        self.assertFalse(is_absolute_path(None))
        self.assertFalse(is_absolute_path(""))
        self.assertFalse(is_absolute_path("relative/photo.jpg"))
        self.assertTrue(is_absolute_path(r"C:\photos\photo.jpg"))
        self.assertTrue(is_absolute_path("/home/user/photo.jpg"))
        self.assertTrue(is_absolute_path(r"\Users\name\photo.jpg"))

    def test_path_key(self) -> None:
        """path_key returns normalized, case-folded path for consistent mapping."""
        key1 = path_key(r"C:\Photos\Family\Pic.JPG")
        key2 = path_key(' "c:/photos/family/pic.jpg" ')
        self.assertEqual(key1, key2)

    def test_to_db_path(self) -> None:
        """to_db_path relativizes paths inside base_dir with forward slashes and preserves outside."""
        base = os.path.abspath(r"C:\Tree\Media")
        inside = os.path.join(base, "Sub", "Photo.jpg")
        outside = os.path.abspath(r"C:\Other\Photo.jpg")

        self.assertEqual(to_db_path(inside, base), "Sub/Photo.jpg")
        self.assertEqual(to_db_path(outside, base), outside)
        self.assertEqual(to_db_path("", base), "")
        self.assertEqual(to_db_path(inside, ""), inside)

    def test_unique_destination(self) -> None:
        """unique_destination appends numerical suffixes to avoid collisions on disk and in batch."""
        with tempfile.TemporaryDirectory() as temp_dir:
            f1 = os.path.join(temp_dir, "pic.jpg")
            with open(f1, "w") as f:
                f.write("content")

            claimed: set[str] = set()
            # Same file as src is allowed unchanged
            cand1 = unique_destination(f1, claimed, src=f1)
            self.assertEqual(cand1, f1)

            # Different src colliding with existing file gets _2
            claimed.clear()
            cand2 = unique_destination(f1, claimed, src=None)
            self.assertEqual(cand2, os.path.join(temp_dir, "pic_2.jpg"))
            self.assertIn(path_key(cand2), claimed)

            # Next request gets _3
            cand3 = unique_destination(f1, claimed, src=None)
            self.assertEqual(cand3, os.path.join(temp_dir, "pic_3.jpg"))

    def test_relocate_file_move_and_copy(self) -> None:
        """relocate_file safely moves or copies files and creates destination directories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            src = os.path.join(temp_dir, "source.jpg")
            with open(src, "w") as f:
                f.write("test content")

            # Copy to new subfolder
            copy_dest = os.path.join(temp_dir, "sub", "copied.jpg")
            ok, err = relocate_file(src, copy_dest, copy=True)
            self.assertTrue(ok)
            self.assertEqual(err, "")
            self.assertTrue(os.path.exists(src))
            self.assertTrue(os.path.exists(copy_dest))

            # Move to another subfolder
            move_dest = os.path.join(temp_dir, "other", "moved.jpg")
            ok, err = relocate_file(src, move_dest, copy=False)
            self.assertTrue(ok)
            self.assertEqual(err, "")
            self.assertFalse(os.path.exists(src))
            self.assertTrue(os.path.exists(move_dest))

    def test_relocate_file_overwrite_protection(self) -> None:
        """relocate_file rejects overwriting an existing destination with different content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            f1 = os.path.join(temp_dir, "file1.jpg")
            f2 = os.path.join(temp_dir, "file2.jpg")
            with open(f1, "w") as f:
                f.write("content 1")
            with open(f2, "w") as f:
                f.write("content 2")

            ok, err = relocate_file(f1, f2, copy=False)
            self.assertFalse(ok)
            self.assertIn("already exists", err)

    def test_build_basename_index(self) -> None:
        """build_basename_index indexes filenames recursively, ignoring hidden files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            sub = os.path.join(temp_dir, "nested")
            os.makedirs(sub)
            with open(os.path.join(temp_dir, "Photo.JPG"), "w") as f:
                f.write("1")
            with open(os.path.join(sub, "Doc.PDF"), "w") as f:
                f.write("2")
            with open(os.path.join(temp_dir, ".hidden"), "w") as f:
                f.write("3")

            idx = build_basename_index(temp_dir)
            self.assertIn("photo.jpg", idx)
            self.assertIn("doc.pdf", idx)
            self.assertNotIn(".hidden", idx)
            self.assertEqual(len(idx["photo.jpg"]), 1)

    def test_gwizard_tags_constants(self) -> None:
        """Standard tag names and colors match specifications."""
        self.assertEqual(TAG_MEDIA_FIXED, "GWizard: MediaFixed")
        self.assertEqual(TAG_MEDIA_FIXED_COLOR, "#2E8B57")
        self.assertEqual(TAG_LOCKED, "GWizard: Locked")
        self.assertEqual(TAG_LOCKED_COLOR, "#B22222")

    def test_create_gwizard_tag(self) -> None:
        """create_gwizard_tag creates a Tag object with name and color."""
        tag = create_gwizard_tag("TestTag", "#123456")
        self.assertIsInstance(tag, Tag)
        self.assertEqual(tag.get_name(), "TestTag")
        self.assertEqual(tag.get_color(), "#123456")

    def test_ensure_tag_and_ensure_gwizard_tags(self) -> None:
        """ensure_tag and ensure_gwizard_tags create tags in DB and are idempotent."""
        db = make_database("sqlite")
        db.load(":memory:")
        try:
            t_fixed, t_locked = ensure_gwizard_tags(db)
            self.assertIsNotNone(t_fixed)
            self.assertIsNotNone(t_locked)
            assert t_fixed is not None and t_locked is not None
            self.assertEqual(t_fixed.get_name(), TAG_MEDIA_FIXED)
            self.assertEqual(t_fixed.get_color(), TAG_MEDIA_FIXED_COLOR)
            self.assertEqual(t_locked.get_name(), TAG_LOCKED)
            self.assertEqual(t_locked.get_color(), TAG_LOCKED_COLOR)

            # Calling again returns existing tags without duplicating
            t_fixed2, t_locked2 = ensure_gwizard_tags(db)
            assert t_fixed2 is not None and t_locked2 is not None
            self.assertEqual(t_fixed.get_handle(), t_fixed2.get_handle())
            self.assertEqual(t_locked.get_handle(), t_locked2.get_handle())
        finally:
            db.close()

    def test_is_media_locked_and_lock_unlock(self) -> None:
        """is_media_locked, lock_media, and unlock_media correctly toggle locked state."""
        db = make_database("sqlite")
        db.load(":memory:")
        try:
            with DbTxn("Create media", db) as trans:
                media = Media()
                media.set_path("test.jpg")
                h = db.add_media(media, trans)

            self.assertFalse(is_media_locked(db, media))

            # Lock media
            locked_ok = lock_media(db, media, commit=True)
            self.assertTrue(locked_ok)
            self.assertTrue(is_media_locked(db, media))

            # Calling lock again returns False (already locked)
            self.assertFalse(lock_media(db, media, commit=True))
            self.assertTrue(is_media_locked(db, media))

            # Unlock media
            unlocked_ok = unlock_media(db, media, commit=True)
            self.assertTrue(unlocked_ok)
            self.assertFalse(is_media_locked(db, media))

            # Calling unlock again returns False (not locked)
            self.assertFalse(unlock_media(db, media, commit=True))
        finally:
            db.close()

    def test_add_media_fixed_tag_and_has_media_fixed_tag(self) -> None:
        """add_media_fixed_tag adds GWizard: MediaFixed tag and is idempotent."""
        db = make_database("sqlite")
        db.load(":memory:")
        try:
            with DbTxn("Create media", db) as trans:
                media = Media()
                media.set_path("test.jpg")
                h = db.add_media(media, trans)

            self.assertFalse(has_media_fixed_tag(db, media))

            # Add fixed tag
            added = add_media_fixed_tag(db, media, commit=True)
            self.assertTrue(added)
            self.assertTrue(has_media_fixed_tag(db, media))

            # Verify tag in db
            tag = db.get_tag_from_name(TAG_MEDIA_FIXED)
            self.assertIsNotNone(tag)
            self.assertEqual(tag.get_color(), TAG_MEDIA_FIXED_COLOR)
            self.assertIn(tag.get_handle(), media.get_tag_list())

            # Second call is a no-op
            self.assertFalse(add_media_fixed_tag(db, media, commit=True))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
