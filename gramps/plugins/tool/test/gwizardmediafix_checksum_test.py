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

"""Tests for media checksums in GWizard Media Fix.

1.1 Content-hash matching: a missing file is found by its stored MD5
    checksum after it was renamed or moved, ranked above a file-name match,
    with the ambiguity rule kept.
1.2 Checksum maintenance: every relink, copy, move, merge, split and undo
    leaves the record's checksum describing its file, and a checksum is
    never cleared because a file cannot be read.
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
from gramps.plugins.tool import gwizard_common as gc
from gramps.plugins.tool import gwizardmediafix as mf
from gramps.plugins.tool.gw_fixmediareferencesdialog import (
    FixMediaReferencesDialog,
    fill_merged_checksum,
)

_CHOOSER = "gramps.plugins.tool.gwizardmediafix.Gtk.FileChooserDialog"
_MF_DLG = "gramps.plugins.tool.gwizardmediafix.OkDialog"
_REF_DLG = "gramps.plugins.tool.gw_fixmediareferencesdialog.OkDialog"


def setUpModule() -> None:
    """Install the GTK fakes for this module's tests."""
    fakes.install()


def tearDownModule() -> None:
    """Restore the real GTK classes for other test modules."""
    fakes.uninstall()


def md5_of(path: str) -> str:
    """Return the MD5 hex digest of a file."""
    with open(path, "rb") as handle:
        return hashlib.md5(handle.read()).hexdigest()


class _DbState:
    """Minimal stand-in for Gramps' DbState."""

    def __init__(self, db: object) -> None:
        self.db = db


# ------------------------------------------------------------
#
# _ChecksumDbTest
#
# ------------------------------------------------------------
class _ChecksumDbTest(unittest.TestCase):
    """In-memory database, a media base folder and an outside folder."""

    def setUp(self) -> None:
        gc._CHECKSUM_CACHE.clear()
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = _DbState(self.db)
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "MediaBase")
        os.makedirs(self.base)
        self.db.set_mediapath(self.base)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        gc._CHECKSUM_CACHE.clear()

    def write(self, rel: str, content: str, root: str | None = None) -> str:
        """Write a file below *root* (the media base) and return its path."""
        path = os.path.join(root or self.base, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def add_media(self, path: str, checksum: str = "", desc: str = "") -> str:
        """Add a media record (optionally with a checksum); return its handle."""
        with DbTxn("add media", self.db) as trans:
            media = Media()
            media.set_path(path)
            media.set_description(desc)
            media.set_checksum(checksum)
            return self.db.add_media(media, trans)

    def media(self, handle: str) -> Media:
        """Return the media record for a handle."""
        return self.db.get_media_from_handle(handle)

    def link_to_person(self, *handles: str) -> None:
        """Reference media records from a new person (so they are not orphans)."""
        with DbTxn("add person", self.db) as trans:
            person = Person()
            for handle in handles:
                ref = MediaRef()
                ref.set_reference_handle(handle)
                person.add_media_reference(ref)
            self.db.add_person(person, trans)

    def tool(self) -> mf.GWizardMediaFix:
        """Return the tool without building its window."""
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        return tool

    def row(self, dlg: mf.FindMissingMediaDialog, handle: str) -> dict[str, Any]:
        """Return the Find-missing row for a media handle."""
        for row in dlg.rows:
            if row["handle"] == handle:
                return row
        raise AssertionError("no row for %s" % handle)

    def target(self, dlg: mf.FindMissingMediaDialog, handle: str) -> dict[str, Any]:
        """Return the Find-missing table row (widgets) for a media handle."""
        for target in dlg.row_targets:
            if target["entry"]["handle"] == handle:
                return target
        raise AssertionError("no target for %s" % handle)


# ------------------------------------------------------------
#
# ChecksumHelperTest
#
# ------------------------------------------------------------
class ChecksumHelperTest(_ChecksumDbTest):
    """The pure checksum helpers in gwizard_common."""

    def test_file_checksum_is_gramps_md5(self) -> None:
        """file_checksum gives the same MD5 Gramps stores, "" when unreadable."""
        path = self.write("a.jpg", "alpha")
        self.assertEqual(gc.file_checksum(path), md5_of(path))
        self.assertEqual(gc.file_checksum(os.path.join(self.tmp, "nope.jpg")), "")
        self.assertEqual(gc.file_checksum(self.base), "")  # a folder
        self.assertEqual(gc.file_checksum(""), "")

    def test_cache_reused_and_invalidated(self) -> None:
        """A file is read once, and again after it changes."""
        path = self.write("a.jpg", "alpha")
        cache: gc.ChecksumCache = {}
        with patch.object(gc, "create_checksum", wraps=gc.create_checksum) as spy:
            first = gc.file_checksum(path, cache)
            self.assertEqual(gc.file_checksum(path, cache), first)
            self.assertEqual(spy.call_count, 1)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("a longer, different content")
            self.assertNotEqual(gc.file_checksum(path, cache), first)
            self.assertEqual(spy.call_count, 2)

    def test_refresh_checksum(self) -> None:
        """refresh_checksum sets, respects only_if_missing, never clears."""
        path = self.write("a.jpg", "alpha")
        media = Media()
        self.assertTrue(gc.refresh_checksum(media, path))
        self.assertEqual(media.get_checksum(), md5_of(path))
        self.assertFalse(gc.refresh_checksum(media, path))  # unchanged

        media.set_checksum("stale")
        self.assertFalse(gc.refresh_checksum(media, path, only_if_missing=True))
        self.assertEqual(media.get_checksum(), "stale")
        self.assertTrue(gc.refresh_checksum(media, path))
        self.assertEqual(media.get_checksum(), md5_of(path))

        media.set_checksum("remembered")
        missing = os.path.join(self.tmp, "gone.jpg")
        self.assertFalse(gc.refresh_checksum(media, missing))
        self.assertEqual(media.get_checksum(), "remembered")

    def test_extension_key_families(self) -> None:
        """.jpeg and .JPG compare equal; other kinds do not."""
        self.assertEqual(gc.extension_key("C:\\x\\IMG.JPEG"), ".jpg")
        self.assertEqual(gc.extension_key("a.jpg"), gc.extension_key("b.JFIF"))
        self.assertEqual(gc.extension_key("scan.TIF"), ".tif")
        self.assertNotEqual(gc.extension_key("a.png"), gc.extension_key("a.jpg"))
        self.assertEqual(gc.extension_key("README"), "")

    def test_index_reads_only_wanted_extensions(self) -> None:
        """Files of another kind are not read; nothing is read with no target."""
        photo = self.write("p.jpeg", "photo")
        video = self.write("v.mp4", "video")
        with patch.object(gc, "create_checksum", wraps=gc.create_checksum) as spy:
            index = gc.build_checksum_index(
                [photo, video], {md5_of(photo)}, extensions={".jpg"}
            )
            self.assertEqual(index, {md5_of(photo): [photo]})
            self.assertEqual(spy.call_count, 1)
            self.assertEqual(gc.build_checksum_index([photo, video], set()), {})
            self.assertEqual(spy.call_count, 1)

    def test_pick_content_match(self) -> None:
        """One copy wins; several are resolved only by a unique file name."""
        self.assertEqual(gc.pick_content_match(["/m/x.jpg"], "a.jpg"), "/m/x.jpg")
        self.assertEqual(
            gc.pick_content_match(["/m/x.jpg", "/n/A.JPG"], "a.jpg"), "/n/A.JPG"
        )
        self.assertEqual(gc.pick_content_match(["/m/x.jpg", "/n/y.jpg"], "a.jpg"), "")
        self.assertEqual(gc.pick_content_match(["/m/a.jpg", "/n/a.jpg"], "a.jpg"), "")


# ------------------------------------------------------------
#
# ContentMatchTest (1.1)
#
# ------------------------------------------------------------
class ContentMatchTest(_ChecksumDbTest):
    """Find missing media matches renamed or moved files by content."""

    def test_renamed_file_found_by_content(self) -> None:
        """A renamed, moved file is suggested from the stored checksum."""
        path = self.write("people/Smith_John_1910.jpg", "john's photo")
        handle = self.add_media("C:/Old/IMG_0492.JPG", md5_of(path))
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        row = self.row(dlg, handle)
        self.assertEqual(row["suggested_path"], "people/Smith_John_1910.jpg")
        self.assertEqual(row["match"], "content")
        self.assertIn("Same content", row["hint_text"])

    def test_content_beats_file_name(self) -> None:
        """A same-name file with other content loses to the renamed original."""
        original = self.write("renamed.jpg", "the real photo")
        self.write("IMG_0001.jpg", "a different camera's IMG_0001")
        handle = self.add_media("D:/Cam/IMG_0001.jpg", md5_of(original))
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        self.assertEqual(self.row(dlg, handle)["suggested_path"], "renamed.jpg")

    def test_same_name_different_content_not_suggested(self) -> None:
        """With a checksum, a same-name file with other content is held back."""
        self.write("IMG_0001.jpg", "someone else's photo")
        handle = self.add_media("D:/Cam/IMG_0001.jpg", md5_of(self.write("x", "orig")))
        os.remove(os.path.join(self.base, "x"))
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        row = self.row(dlg, handle)
        self.assertEqual(row["suggested_path"], "")
        self.assertIn("different content", row["hint_text"])

    def test_accept_all_skips_same_name_different_content(self) -> None:
        """Accept all hints neither plans nor makes a same-name, other-content match."""
        other = self.write("IMG_0001.jpg", "a different camera's IMG_0001")
        stored = hashlib.md5(b"the original photo").hexdigest()
        handle = self.add_media("D:/Cam/IMG_0001.jpg", stored)
        self.link_to_person(handle)  # else it would be removed as an orphan

        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertEqual(plan["find"], [])
        gid = self.media(handle).gramps_id
        self.assertIn(gid, [row[0] for row in plan["missing"]])

        resolved, unresolved, _denied = self.tool()._auto_find_missing(self.db)
        self.assertEqual(resolved, 0)
        self.assertEqual([row[0] for row in unresolved], [gid])
        media = self.media(handle)
        self.assertEqual(media.get_path(), "D:/Cam/IMG_0001.jpg")
        self.assertEqual(media.get_checksum(), stored)
        self.assertNotEqual(md5_of(other), stored)

    def test_name_match_without_checksum_unchanged(self) -> None:
        """A record without a checksum is still matched by file name."""
        self.write("scan.jpg", "scan")
        handle = self.add_media("E:/Old/scan.jpg")
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        row = self.row(dlg, handle)
        self.assertEqual(row["suggested_path"], "scan.jpg")
        self.assertEqual(row["match"], "name")

    def test_identical_copies_need_a_choice(self) -> None:
        """Two identical copies with new names: no automatic hint."""
        self.write("one.jpg", "same bytes")
        self.write("two.jpg", "same bytes")
        handle = self.add_media(
            "C:/Old/orig.jpg", md5_of(self.write("one.jpg", "same bytes"))
        )
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        row = self.row(dlg, handle)
        self.assertEqual(row["suggested_path"], "")
        self.assertIn("Same content in 2 files", row["hint_text"])

    def test_identical_copies_resolved_by_name(self) -> None:
        """Of identical copies, the one with the record's name is chosen."""
        self.write("copy.jpg", "same bytes")
        self.write("sub/orig.jpg", "same bytes")
        handle = self.add_media(
            "C:/Old/orig.jpg", md5_of(self.write("copy.jpg", "same bytes"))
        )
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        self.assertEqual(self.row(dlg, handle)["suggested_path"], "sub/orig.jpg")

    def test_ambiguity_rule_kept_for_content(self) -> None:
        """Two different records with one checksum are not both repointed."""
        path = self.write("found.jpg", "shared content")
        h_a = self.add_media("C:/Smith/a.jpg", md5_of(path))
        h_b = self.add_media("D:/Jones/b.jpg", md5_of(path))
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        for handle in (h_a, h_b):
            row = self.row(dlg, handle)
            self.assertEqual(row["suggested_path"], "")
            self.assertIn("also matches", row["hint_text"])
        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertEqual(plan["find"], [])
        self.assertEqual(len(plan["ambiguous"]), 2)

    def test_extension_family_searched(self) -> None:
        """A .jpg record finds its file renamed to .jpeg."""
        path = self.write("Smith.JPEG", "photo")
        handle = self.add_media("C:/Old/IMG_7.jpg", md5_of(path))
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        self.assertEqual(self.row(dlg, handle)["suggested_path"], "Smith.JPEG")

    def test_no_base_path_no_content_search(self) -> None:
        """Without a configured base path, folders are not walked or hashed."""
        self.db.set_mediapath(None)
        self.add_media("C:/Old/IMG_1.jpg", "0" * 32)
        with patch.object(mf, "build_checksum_index") as index:
            mf.FindMissingMediaDialog(dbstate=self.dbstate)
        index.assert_not_called()

    def test_apply_content_match_stores_path_and_checksum(self) -> None:
        """Accept hints + Apply repoints the record; the checksum still fits."""
        path = self.write("people/Smith.jpg", "photo")
        handle = self.add_media("C:/Old/IMG_1.jpg", md5_of(path))
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        with patch(_MF_DLG):
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())
        media = self.media(handle)
        self.assertEqual(media.get_path(), "people/Smith.jpg")
        self.assertEqual(media.get_checksum(), md5_of(path))

    def test_accept_all_finds_by_content(self) -> None:
        """Preview and run agree on a content match; preview marks it."""
        path = self.write("Smith.jpg", "photo")
        handle = self.add_media("C:/Old/IMG_1.jpg", md5_of(path))
        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertEqual(
            plan["find"],
            [(self.media(handle).gramps_id, "C:/Old/IMG_1.jpg", "Smith.jpg")],
        )
        self.assertIn("(same content)", mf.format_plan(plan))
        resolved, unresolved, _denied = self.tool()._auto_find_missing(self.db)
        self.assertEqual((resolved, unresolved), (1, []))
        self.assertEqual(self.media(handle).get_path(), "Smith.jpg")

    def test_fill_same_name_checks_content(self) -> None:
        """Picking a file fills same-name rows only when the content agrees."""
        picked = self.write("chosen/photo.jpg", "the photo", root=self.tmp)
        h_src = self.add_media("C:/A/photo.jpg")
        h_same = self.add_media("C:/B/photo.jpg", md5_of(picked))
        h_other = self.add_media("C:/C/photo.jpg", "e" * 32)
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        chooser = MagicMock()
        chooser.run.return_value = Gtk.ResponseType.OK
        chooser.get_filename.return_value = picked
        with patch(_CHOOSER, return_value=chooser):
            dlg.cb_pick_file(MagicMock(), self.target(dlg, h_src))
        self.assertEqual(self.target(dlg, h_same).get("picked"), picked)
        self.assertIsNone(self.target(dlg, h_other).get("picked"))


# ------------------------------------------------------------
#
# ChecksumMaintenanceTest (1.2)
#
# ------------------------------------------------------------
class ChecksumMaintenanceTest(_ChecksumDbTest):
    """Every change to a record's file keeps its checksum right."""

    def test_find_missing_by_name_stores_checksum(self) -> None:
        """A record without a checksum gets one when it is relinked."""
        path = self.write("scan.jpg", "scan")
        handle = self.add_media("E:/Old/scan.jpg")
        self.tool()._auto_find_missing(self.db)
        self.assertEqual(self.media(handle).get_checksum(), md5_of(path))

    def test_consolidate_fills_missing_checksum(self) -> None:
        """A moved file's record gets a checksum it lacked; others are kept."""
        outside = os.path.join(self.tmp, "Elsewhere")
        p_new = self.write("new.jpg", "new photo", root=outside)
        p_kept = self.write("kept.jpg", "kept photo", root=outside)
        h_new = self.add_media(p_new)
        h_kept = self.add_media(p_kept, "c" * 32)
        self.link_to_person(h_new, h_kept)
        moved, _not = self.tool()._auto_consolidate_location(self.db)
        self.assertEqual(moved, 2)
        self.assertEqual(
            self.media(h_new).get_checksum(), hashlib.md5(b"new photo").hexdigest()
        )
        self.assertEqual(self.media(h_kept).get_checksum(), "c" * 32)

    def test_store_checksums_never_clears(self) -> None:
        """Storing checksums fills, updates changed files, keeps missing ones."""
        p_a = self.write("a.jpg", "a")
        p_b = self.write("b.jpg", "b")
        h_a = self.add_media("a.jpg")
        h_b = self.add_media("b.jpg", "0" * 32)  # file changed since
        h_gone = self.add_media("gone.jpg", "9" * 32)

        added, updated, unreadable = mf.store_media_checksums(self.db)
        self.assertEqual((added, updated, unreadable), (1, 0, 0))
        self.assertEqual(self.media(h_a).get_checksum(), md5_of(p_a))
        self.assertEqual(self.media(h_b).get_checksum(), "0" * 32)

        added, updated, unreadable = mf.store_media_checksums(
            self.db, only_missing=False
        )
        self.assertEqual((added, updated, unreadable), (0, 1, 1))
        self.assertEqual(self.media(h_b).get_checksum(), md5_of(p_b))
        self.assertEqual(self.media(h_gone).get_checksum(), "9" * 32)

    def test_plan_lists_records_without_checksum(self) -> None:
        """The preview lists records that will get a checksum, and the run does it."""
        self.write("a.jpg", "a")
        h_a = self.add_media("a.jpg")
        h_gone = self.add_media("gone.jpg")  # unreadable: not listed
        self.link_to_person(h_a, h_gone)  # else they would be deleted as orphans
        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertEqual(plan["checksums"], [(self.media(h_a).gramps_id, "a.jpg")])
        self.assertTrue(mf.plan_has_changes(plan))
        self.assertIn("Checksums: 1 record has none yet", mf.format_plan(plan))
        self.assertEqual(self.tool()._auto_store_checksums(self.db), 1)

    def test_split_copies_get_checksum(self) -> None:
        """Fix references 'Create copies' gives each copy's record a checksum."""
        path = self.write("shared.jpg", "shared")
        h_1 = self.add_media("shared.jpg")
        h_2 = self.add_media("shared.jpg")
        self.link_to_person(h_1, h_2)
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        target = dlg.row_targets[0]
        target["action_combo"] = MagicMock()
        target["action_combo"].get_active.return_value = 1  # Create copies
        with patch(_REF_DLG):
            dlg.cb_apply(MagicMock())
        copies = [
            self.media(h)
            for h in (h_1, h_2)
            if self.media(h).get_path() != "shared.jpg"
        ]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].get_checksum(), md5_of(path))

    def test_merge_keeps_a_checksum(self) -> None:
        """A merged keeper takes the other record's checksum when it has none."""
        path = self.write("shared.jpg", "shared")
        keeper = self.media(self.add_media("shared.jpg"))
        other = self.media(self.add_media("shared.jpg", md5_of(path)))
        fill_merged_checksum(self.db, keeper, other)
        self.assertEqual(self.media(keeper.handle).get_checksum(), md5_of(path))

        bare = self.media(self.add_media("shared.jpg"))
        fill_merged_checksum(self.db, bare, None)  # read from the file
        self.assertEqual(self.media(bare.handle).get_checksum(), md5_of(path))

    def test_undo_moves_keeps_checksum_right(self) -> None:
        """Undoing a logged move leaves the record's checksum on its file."""
        outside = os.path.join(self.tmp, "Elsewhere")
        src = self.write("p.jpg", "photo", root=outside)
        handle = self.add_media(src)
        self.link_to_person(handle)
        self.tool()._auto_consolidate_location(self.db)
        self.assertNotEqual(self.media(handle).get_path(), src)
        log = os.path.join(mf.get_media_base_path(self.db), gc.MOVE_LOG_NAME)
        gc.undo_logged_run(self.db, log)
        media = self.media(handle)
        self.assertEqual(media.get_path(), src)
        self.assertEqual(media.get_checksum(), md5_of(src))

    def test_report_shows_checksum_metrics(self) -> None:
        """The report counts records with checksums and matchable missing files."""
        self.write("a.jpg", "a")
        self.add_media("a.jpg", "1" * 32)
        self.add_media("gone.jpg", "2" * 32)
        self.add_media("gone2.jpg")
        text = mf.generate_media_fix_report(self.db)
        self.assertIn("Records with checksum:", text)
        self.assertIn("2 of 3", text)
        self.assertIn("1 of 2 (can be found by content)", text)


fakes.uninstall()

if __name__ == "__main__":
    unittest.main()
