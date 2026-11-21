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

"""The report's search for unreferenced files: media check and file limit.

Media files are recognised by MIME type (plus known media extensions), the
file limit is a saved setting, and when the limit stops the search the report
says so and Generate report offers to scan everything.
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

from gramps.gen.config import config
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Media
from gramps.plugins.tool import gwizardmediafix as mf

_CHOOSER = "gramps.plugins.tool.gwizardmediafix.Gtk.FileChooserDialog"
_ASK = "gramps.plugins.tool.gwizardmediafix.ask_full_scan"


def setUpModule() -> None:
    """Install the GTK fakes for this module's tests."""
    fakes.install()


def tearDownModule() -> None:
    """Restore the real GTK classes for other test modules."""
    fakes.uninstall()


class _DbState:
    """Minimal stand-in for Gramps' DbState."""

    def __init__(self, db: object) -> None:
        self.db = db


# ------------------------------------------------------------
#
# MediaFileTest
#
# ------------------------------------------------------------
class MediaFileTest(unittest.TestCase):
    """Which files count as media."""

    def tearDown(self) -> None:
        mf._extension_mime.cache_clear()

    def test_unusual_media_types_count(self) -> None:
        """Types the old fixed list skipped are now found, in any case."""
        for name in (
            "a.heic",
            "a.HEIF",
            "a.jfif",
            "a.jp2",
            "a.djvu",
            "a.3gp",
            "a.m4v",
            "a.ogv",
            "a.avif",
            "a.mts",
        ):
            self.assertTrue(mf.is_media_file(name), name)

    def test_usual_media_still_count(self) -> None:
        """The types the old list knew are still media."""
        for name in ("a.jpg", "b.PNG", "c.pdf", "d.mp3", "e.mp4", "f.docx", "g.txt"):
            self.assertTrue(mf.is_media_file(name), name)

    def test_other_files_do_not(self) -> None:
        """Trees, settings, programs, archives and web pages are not media."""
        for name in (
            "tree.gramps",
            "tree.ged",
            "gramps.ini",
            "tool.py",
            "page.html",
            "backup.zip",
            "setup.exe",
            "README",
        ):
            self.assertFalse(mf.is_media_file(name), name)

    def test_mime_type_decides_for_other_extensions(self) -> None:
        """An extension not in the list counts if its MIME type is media."""
        mf._extension_mime.cache_clear()
        types = {".xyzimg": "image/x-xyz", ".xyzdoc": "application/x-xyz"}
        with patch.object(
            mf, "get_type", side_effect=lambda n: types["." + n.split(".")[-1]]
        ):
            self.assertTrue(mf.is_media_file("scan.xyzimg"))
            self.assertFalse(mf.is_media_file("data.xyzdoc"))

    def test_broken_mime_lookup_is_not_media(self) -> None:
        """A failing MIME lookup (e.g. a bad registry entry) does not stop a scan."""
        mf._extension_mime.cache_clear()
        with patch.object(mf, "get_type", side_effect=OSError("registry")):
            self.assertFalse(mf.is_media_file("odd.qqq"))


# ------------------------------------------------------------
#
# _ScanTest
#
# ------------------------------------------------------------
class _ScanTest(unittest.TestCase):
    """A tree whose media folder holds a few files."""

    def setUp(self) -> None:
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = _DbState(self.db)
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "MediaBase")
        os.makedirs(self.base)
        self.db.set_mediapath(self.base)
        saved = config.get(mf.CONFIG_SCAN_LIMIT_KEY)
        self.addCleanup(config.set, mf.CONFIG_SCAN_LIMIT_KEY, saved)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def touch(self, *names: str) -> None:
        """Create files in the media folder."""
        for name in names:
            path = os.path.join(self.base, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(name)

    def add_media(self, path: str) -> None:
        """Add a media record."""
        with DbTxn("add media", self.db) as trans:
            media = Media()
            media.set_path(path)
            self.db.add_media(media, trans)


# ------------------------------------------------------------
#
# ScanLimitTest
#
# ------------------------------------------------------------
class ScanLimitTest(_ScanTest):
    """The file limit of the search for unreferenced files."""

    def scan(self, limit: int | None) -> tuple[list[str], dict[str, Any]]:
        """Run the search and return (files, stats)."""
        stats: dict[str, Any] = {}
        found = mf.find_unreferenced_default_path_files(
            self.db, self.base, max_scan_files=limit, stats=stats
        )
        return found, stats

    def test_new_types_found_and_others_ignored(self) -> None:
        """Unreferenced .heic/.jp2/.djvu/.m4v files are found; .ini is not."""
        self.touch("a.heic", "b.jp2", "sub/c.djvu", "d.m4v", "gramps.ini", "e.ged")
        found, stats = self.scan(0)
        self.assertEqual(found, ["a.heic", "b.jp2", "d.m4v", "sub/c.djvu"])
        self.assertEqual((stats["scanned"], stats["truncated"]), (4, False))

    def test_limit_stops_the_scan(self) -> None:
        """More media files than the limit: the scan stops and says so."""
        self.touch("a.jpg", "b.jpg", "c.jpg")
        found, stats = self.scan(2)
        self.assertEqual(len(found), 2)
        self.assertEqual(stats, {"scanned": 2, "limit": 2, "truncated": True})

    def test_exactly_the_limit_is_not_truncated(self) -> None:
        """As many media files as the limit: nothing was left out."""
        self.touch("a.jpg", "b.jpg", "notes.ini")
        found, stats = self.scan(2)
        self.assertEqual(len(found), 2)
        self.assertFalse(stats["truncated"])

    def test_zero_means_no_limit(self) -> None:
        """A limit of 0 scans every file."""
        self.touch(*["f%02d.jpg" % i for i in range(12)])
        found, stats = self.scan(0)
        self.assertEqual(len(found), 12)
        self.assertFalse(stats["truncated"])

    def test_saved_setting_is_used(self) -> None:
        """Without an explicit limit, the saved setting applies."""
        self.touch("a.jpg", "b.jpg", "c.jpg")
        config.set(mf.CONFIG_SCAN_LIMIT_KEY, 1)
        _found, stats = self.scan(None)
        self.assertEqual((stats["limit"], stats["truncated"]), (1, True))

    def test_broken_setting_falls_back(self) -> None:
        """A setting that is not a number falls back to the default."""
        # Gramps refuses to save a non-number, but gramps.ini can be edited.
        with patch.object(mf.config, "get", return_value="lots"):
            self.assertEqual(mf.scan_limit(), mf.DEFAULT_SCAN_LIMIT)
        config.set(mf.CONFIG_SCAN_LIMIT_KEY, 250)
        self.assertEqual(mf.scan_limit(), 250)


# ------------------------------------------------------------
#
# ReportScanLimitTest
#
# ------------------------------------------------------------
class ReportScanLimitTest(_ScanTest):
    """What the report and Generate report do when the limit is hit."""

    def test_report_says_where_the_scan_stopped(self) -> None:
        """The summary and the section both say the scan stopped, even with
        nothing listed."""
        self.touch("a.jpg", "b.jpg", "c.jpg")
        for name in ("a.jpg", "b.jpg", "c.jpg"):
            self.add_media(name)  # all referenced: the list itself is empty
        stats: dict[str, Any] = {}
        text = mf.generate_media_fix_report(self.db, scan_limit=2, scan_stats=stats)
        self.assertTrue(stats["truncated"])
        self.assertIn("(scan stopped at 2 files)", text)
        self.assertIn("Scan stopped at 2 media files", text)
        self.assertIn("UNREFERENCED FILES IN DEFAULT PATH (0 files", text)

    def test_full_report_has_no_stop_note(self) -> None:
        """A complete scan adds no note."""
        self.touch("a.jpg")
        text = mf.generate_media_fix_report(self.db, scan_limit=0)
        self.assertNotIn("scan stopped", text.lower())

    def generate(self, answer: str) -> tuple[str, MagicMock]:
        """Run Generate report with a limit of 2 and the given answer."""
        self.touch("a.jpg", "b.jpg", "c.jpg")
        config.set(mf.CONFIG_SCAN_LIMIT_KEY, 2)
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        tool.window = None
        tool.report_path = None
        target = os.path.join(self.tmp, "report.txt")
        chooser = MagicMock()
        chooser.run.return_value = Gtk.ResponseType.OK
        chooser.get_filename.return_value = target
        with (
            patch(_CHOOSER, return_value=chooser),
            patch(_ASK, return_value=answer) as ask,
            patch.object(mf.GWizardMediaFix, "cb_view_report"),
        ):
            tool.cb_generate_report()
        with open(target, encoding="utf-8") as handle:
            return handle.read(), ask

    def test_scan_all_this_time(self) -> None:
        """'Scan all files this time' rewrites the report from a full scan."""
        text, ask = self.generate("once")
        ask.assert_called_once_with(None, 2)
        self.assertIn("UNREFERENCED FILES IN DEFAULT PATH (3 files", text)
        self.assertNotIn("Scan stopped", text)
        self.assertEqual(config.get(mf.CONFIG_SCAN_LIMIT_KEY), 2)

    def test_always_scan_all(self) -> None:
        """'Always scan all files' also saves 'no limit'."""
        text, _ask = self.generate("always")
        self.assertIn("UNREFERENCED FILES IN DEFAULT PATH (3 files", text)
        self.assertEqual(config.get(mf.CONFIG_SCAN_LIMIT_KEY), 0)

    def test_keep_partial_report(self) -> None:
        """'Keep this report' saves the partial report with its note."""
        text, _ask = self.generate("")
        self.assertIn("UNREFERENCED FILES IN DEFAULT PATH (2 files", text)
        self.assertIn("Scan stopped at 2 media files", text)
        self.assertEqual(config.get(mf.CONFIG_SCAN_LIMIT_KEY), 2)


fakes.uninstall()

if __name__ == "__main__":
    unittest.main()
