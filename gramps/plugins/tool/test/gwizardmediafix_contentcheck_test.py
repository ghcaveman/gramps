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

"""The report's optional "content changed since checksum" check.

When asked (a check box in the report's Save dialog, remembered between
runs), Generate report reads every file that has a stored checksum and lists
those whose content no longer matches: edited or replaced files.
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

from gramps.gen.config import config
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Media
from gramps.plugins.tool import gwizard_mediafix_common as gc
from gramps.plugins.tool import gwizardmediafix as mf

_CHOOSER = "gramps.plugins.tool.gwizardmediafix.Gtk.FileChooserDialog"
_SECTION = "CONTENT CHANGED SINCE CHECKSUM"


def setUpModule() -> None:
    """Install the GTK fakes for this module's tests."""
    fakes.install()


def tearDownModule() -> None:
    """Restore the real GTK classes for other test modules."""
    fakes.uninstall()


def md5(text: str) -> str:
    """Return the MD5 of some text."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class _DbState:
    """Minimal stand-in for Gramps' DbState."""

    def __init__(self, db: object) -> None:
        self.db = db


class ContentCheckTest(unittest.TestCase):
    """Edited or replaced files are listed when the check is on."""

    def setUp(self) -> None:
        gc._CHECKSUM_CACHE.clear()
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = _DbState(self.db)
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "MediaBase")
        os.makedirs(self.base)
        self.db.set_mediapath(self.base)
        saved = config.get(mf.CONFIG_CHECK_CONTENT_KEY)
        self.addCleanup(config.set, mf.CONFIG_CHECK_CONTENT_KEY, saved)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        gc._CHECKSUM_CACHE.clear()

    def add(self, name: str, content: str | None, checksum: str) -> str:
        """Add a record (and its file, unless content is None); return its ID."""
        if content is not None:
            with open(os.path.join(self.base, name), "w", encoding="utf-8") as fh:
                fh.write(content)
        with DbTxn("add media", self.db) as trans:
            media = Media()
            media.set_path(name)
            media.set_description(name)
            media.set_checksum(checksum)
            self.db.add_media(media, trans)
            return media.get_gramps_id()

    def tree(self) -> dict[str, str]:
        """An edited file, an unchanged one, one never checksummed, one missing."""
        return {
            "edited": self.add("edited.jpg", "rotated photo", md5("original photo")),
            "same": self.add("same.jpg", "unchanged", md5("unchanged")),
            "none": self.add("none.jpg", "no checksum yet", ""),
            "gone": self.add("gone.jpg", None, md5("gone")),
        }

    def test_edited_file_listed(self) -> None:
        """Only the edited file is listed; the summary counts it."""
        ids = self.tree()
        text = mf.generate_media_fix_report(self.db, check_content=True)
        self.assertIn("%s (1 items" % _SECTION, text)
        # The section runs from its heading to the next heading's ruler.
        rule = "-" * 72
        start = text.index(_SECTION)
        end = text.find(rule, text.index(rule, start) + len(rule))
        section = text[start : end if end != -1 else len(text)]
        self.assertIn("[%s] edited.jpg" % ids["edited"], section)
        for other in ("same", "none", "gone"):
            self.assertNotIn("[%s]" % ids[other], section)
        self.assertRegex(text, r"Content changed:\s+1\n")
        self.assertIn("offered to store the new checksums", text)

    def test_off_reads_no_files(self) -> None:
        """With the check off, no file is read and the summary says so."""
        self.tree()
        with patch.object(mf, "file_checksum") as reader:
            text = mf.generate_media_fix_report(self.db, check_content=False)
        reader.assert_not_called()
        self.assertNotIn(_SECTION, text)
        self.assertIn("not checked (option in the report's Save dialog)", text)

    def test_nothing_changed_no_section(self) -> None:
        """When every file matches, there is no section and the count is 0."""
        self.add("same.jpg", "unchanged", md5("unchanged"))
        text = mf.generate_media_fix_report(self.db, check_content=True)
        self.assertNotIn(_SECTION, text)
        self.assertRegex(text, r"Content changed:\s+0\n")

    def test_saved_setting_used_by_default(self) -> None:
        """Without an explicit choice, the saved setting applies."""
        self.tree()
        config.set(mf.CONFIG_CHECK_CONTENT_KEY, True)
        self.assertIn(_SECTION, mf.generate_media_fix_report(self.db))
        config.set(mf.CONFIG_CHECK_CONTENT_KEY, False)
        self.assertNotIn(_SECTION, mf.generate_media_fix_report(self.db))

    def save_report(self, tick: bool, update: bool = False) -> tuple[str, Any]:
        """Run Generate report, setting the Save dialog's check box.

        :param update: The answer to the offer to update changed checksums.
        """
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        tool.window = None
        tool.report_path = None
        target = os.path.join(self.tmp, "report.txt")
        chooser = MagicMock()
        chooser.get_filename.return_value = target
        shown: dict[str, Any] = {}

        def run() -> Any:
            box = chooser.set_extra_widget.call_args[0][0]
            shown["was_ticked"] = box.get_active()
            box.set_active(tick)
            return Gtk.ResponseType.OK

        chooser.run.side_effect = run
        question = MagicMock()
        question.return_value.run.return_value = update
        with (
            patch(_CHOOSER, return_value=chooser),
            patch.object(mf.GWizardMediaFix, "cb_view_report"),
            patch.object(mf, "QuestionDialog2", question),
            patch.object(mf, "OkDialog"),
        ):
            tool.cb_generate_report()
        shown["asked"] = question.called
        self.asked = shown["asked"]
        with open(target, encoding="utf-8") as handle:
            return handle.read(), shown["was_ticked"]

    def checksum_of(self, gid: str) -> str:
        """The stored checksum of a record."""
        return self.db.get_media_from_gramps_id(gid).get_checksum()

    def test_report_returns_changed_records(self) -> None:
        """scan_stats names the records whose content changed."""
        ids = self.tree()
        stats: dict[str, Any] = {}
        mf.generate_media_fix_report(self.db, scan_stats=stats, check_content=True)
        edited = self.db.get_media_from_gramps_id(ids["edited"]).get_handle()
        self.assertEqual(stats["changed_handles"], [edited])

    def test_update_changed_checksums(self) -> None:
        """Only the edited record gets its new checksum; the rest are kept."""
        ids = self.tree()
        edited = self.db.get_media_from_gramps_id(ids["edited"]).get_handle()
        self.assertEqual(mf.update_changed_checksums(self.db, [edited]), 1)
        self.assertEqual(self.checksum_of(ids["edited"]), md5("rotated photo"))
        self.assertEqual(self.checksum_of(ids["gone"]), md5("gone"))
        text = mf.generate_media_fix_report(self.db, check_content=True)
        self.assertNotIn(_SECTION, text)

    def test_report_offers_update_after_saving(self) -> None:
        """Saving a checked report asks to update; yes stores, no keeps."""
        ids = self.tree()
        self.save_report(tick=True, update=False)
        self.assertTrue(self.asked)
        self.assertEqual(self.checksum_of(ids["edited"]), md5("original photo"))

        self.save_report(tick=True, update=True)
        self.assertEqual(self.checksum_of(ids["edited"]), md5("rotated photo"))

    def test_no_offer_without_content_check(self) -> None:
        """With the check off nothing is asked."""
        self.tree()
        self.save_report(tick=False, update=True)
        self.assertFalse(self.asked)

    def test_save_dialog_box_applies_and_is_remembered(self) -> None:
        """The check box drives this report and is shown ticked next time."""
        self.tree()
        config.set(mf.CONFIG_CHECK_CONTENT_KEY, False)
        text, was_ticked = self.save_report(tick=True)
        self.assertFalse(was_ticked)
        self.assertIn(_SECTION, text)
        self.assertTrue(config.get(mf.CONFIG_CHECK_CONTENT_KEY))

        text, was_ticked = self.save_report(tick=False)
        self.assertTrue(was_ticked)
        self.assertNotIn(_SECTION, text)
        self.assertFalse(config.get(mf.CONFIG_CHECK_CONTENT_KEY))


fakes.uninstall()

if __name__ == "__main__":
    unittest.main()
