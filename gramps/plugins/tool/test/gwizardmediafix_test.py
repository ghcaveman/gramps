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

"""Tests for GWizardMediaFix and its dialogs."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
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
from gramps.gen.lib import (
    Media,
    Person,
    Name,
    Surname,
    Event,
    EventType,
    EventRef,
    MediaRef,
    Date,
)
from gramps.plugins.tool.gwizardmediafix import (
    GWizardMediaFix,
    FindMissingMediaDialog,
    ConsolidateMediaLocationDialog,
    ApplyFilenameStandardsDialog,
    sanitize_standard_filename,
    generate_media_fix_report,
    resolve_media_reference_context,
    format_standard_filename,
    DEFAULT_FILENAME_TEMPLATE,
    FILENAME_PRESETS,
)


class FakeDbState:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class GWizardMediaFixTest(unittest.TestCase):
    """Test suite for GWizardMediaFix and its media inspection dialogs."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = FakeDbState(self.db)
        from gramps.gen.config import config
        from gramps.plugins.tool.gwizardmediafix import (
            CONFIG_TEMPLATE_KEY,
            DEFAULT_FILENAME_TEMPLATE,
        )

        config.set(CONFIG_TEMPLATE_KEY, DEFAULT_FILENAME_TEMPLATE)

    def tearDown(self) -> None:
        from gramps.gen.config import config
        from gramps.plugins.tool.gwizardmediafix import (
            CONFIG_TEMPLATE_KEY,
            DEFAULT_FILENAME_TEMPLATE,
        )

        config.set(CONFIG_TEMPLATE_KEY, DEFAULT_FILENAME_TEMPLATE)
        self.db.close()

    def test_sanitize_standard_filename(self) -> None:
        """Filenames should be sanitized with lowercase extensions and clean names."""
        res1 = sanitize_standard_filename("Photo of John Smith (1880).JPEG")
        self.assertEqual(res1, "Photo_of_John_Smith_1880.jpeg")

        res2 = sanitize_standard_filename(
            os.path.join("documents", "My Census Record#1.PNG")
        )
        self.assertEqual(res2, os.path.join("documents", "My_Census_Record_1.png"))

        # Separator with hyphen should not turn into '_-_'
        res3 = sanitize_standard_filename("Smith - John - 1920.jpg")
        self.assertEqual(res3, "Smith-John-1920.jpg")

        res4 = sanitize_standard_filename("1920 Census - Smith, John.jpg")
        self.assertEqual(res4, "1920_Census-Smith_John.jpg")

        res5 = sanitize_standard_filename("Photo_-_John.JPG")
        self.assertEqual(res5, "Photo-John.jpg")

    def test_find_missing_media_detection_and_apply(self) -> None:
        """FindMissingMediaDialog detects missing files and applies updated paths."""
        with DbTxn("Create media", self.db) as trans:
            m = Media()
            m.set_description("Missing photo")
            m.set_path("nonexistent_path/fake_image.jpg")
            m_handle = self.db.add_media(m, trans)

        dlg = FindMissingMediaDialog(dbstate=self.dbstate)
        self.assertEqual(len(dlg.rows), 1)
        row = dlg.rows[0]
        self.assertEqual(row["handle"], m_handle)
        self.assertIn("File not found", row["hint_text"])

        # Test apply
        mock_entry = MagicMock()
        mock_entry.get_text.return_value = "new_folder/found_image.jpg"
        dlg.row_targets = [{"entry": row, "path_entry": mock_entry}]

        with patch("gramps.plugins.tool.gwizardmediafix.OkDialog"):
            dlg.cb_apply(MagicMock())

        updated = self.db.get_media_from_handle(m_handle)
        self.assertEqual(
            os.path.normpath(updated.get_path()),
            os.path.normpath("new_folder/found_image.jpg"),
        )

    def test_consolidate_media_location_apply(self) -> None:
        """ConsolidateMediaLocationDialog detects non-standard/absolute paths and applies."""
        with DbTxn("Create media", self.db) as trans:
            m = Media()
            m.set_description("Scattered photo")
            m.set_path("subfolder\\backslashes.jpg")
            m_handle = self.db.add_media(m, trans)

        dlg = ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        self.assertEqual(len(dlg.rows), 1)
        row = dlg.rows[0]
        self.assertEqual(row["suggested_path"], "subfolder/backslashes.jpg")

        mock_entry = MagicMock()
        mock_entry.get_text.return_value = "subfolder/backslashes.jpg"
        dlg.row_targets = [{"entry": row, "path_entry": mock_entry}]

        with patch("gramps.plugins.tool.gwizardmediafix.OkDialog"):
            dlg.cb_apply(MagicMock())

        updated = self.db.get_media_from_handle(m_handle)
        self.assertEqual(
            os.path.normpath(updated.get_path()),
            os.path.normpath("subfolder/backslashes.jpg"),
        )

    def test_apply_filename_standards(self) -> None:
        """ApplyFilenameStandardsDialog sanitizes names and applies updates."""
        with DbTxn("Create media", self.db) as trans:
            m = Media()
            m.set_description("Irregular filename")
            m.set_path("My File (2020).JPG")
            m_handle = self.db.add_media(m, trans)

        dlg = ApplyFilenameStandardsDialog(dbstate=self.dbstate)
        self.assertEqual(len(dlg.rows), 1)
        row = dlg.rows[0]
        # Default template is {ref_id}_{surname}_{given}-{doc_type}-{year}.{ext}
        # Without references, it falls back cleanly to {id}-{doc_type}.ext
        self.assertEqual(
            row["suggested_path"], f"{m.get_gramps_id()}-Irregular_filename.jpg"
        )

        # Switch to {orig}.{ext} preset
        dlg.apply_template("{orig}.{ext}")
        self.assertEqual(dlg.rows[0]["suggested_path"], "My_File_2020.jpg")

        mock_entry = MagicMock()
        mock_entry.get_text.return_value = "My_File_2020.jpg"
        dlg.row_targets = [{"entry": dlg.rows[0], "std_entry": mock_entry}]

        with patch("gramps.plugins.tool.gwizardmediafix.OkDialog"):
            dlg.cb_apply(MagicMock())

        updated = self.db.get_media_from_handle(m_handle)
        self.assertEqual(updated.get_path(), "My_File_2020.jpg")

    def test_resolve_media_reference_context_person(self) -> None:
        """Resolve context for media referenced by a Person."""
        with DbTxn("Create person media", self.db) as trans:
            m = Media()
            m.set_description("Headstone")
            m.set_path("photos/raw_scan.JPG")
            m_handle = self.db.add_media(m, trans)

            p = Person()
            n = Name()
            s = Surname()
            s.set_surname("Doe")
            n.add_surname(s)
            n.set_first_name("Mary")
            p.set_primary_name(n)

            d = Date()
            d.set_year(1985)
            e = Event()
            e.set_type(EventType.DEATH)
            e.set_date_object(d)
            e_h = db_add_e = self.db.add_event(e, trans)
            eref = EventRef()
            eref.set_reference_handle(e_h)
            p.add_event_ref(eref)

            mref = MediaRef()
            mref.set_reference_handle(m_handle)
            p.add_media_reference(mref)
            p_handle = self.db.add_person(p, trans)

        media = self.db.get_media_from_handle(m_handle)
        ctx = resolve_media_reference_context(self.db, media)
        self.assertEqual(ctx["surname"], "Doe")
        self.assertEqual(ctx["given"], "Mary")
        self.assertEqual(ctx["doc_type"], "Headstone")
        self.assertEqual(ctx["year"], "1985")

        std_path = sanitize_standard_filename(media.get_path(), db=self.db, media=media)
        self.assertEqual(
            std_path,
            os.path.join("photos", f"{ctx['ref_id']}_Doe_Mary-Headstone-1985.jpg"),
        )

    def test_resolve_media_reference_context_event(self) -> None:
        """Resolve context for media referenced by an Event with a Person participant."""
        with DbTxn("Create event media", self.db) as trans:
            m = Media()
            m.set_description("Birth Certificate")
            m.set_path("documents/cert_scan.PNG")
            m_handle = self.db.add_media(m, trans)

            d = Date()
            d.set_year(1920)
            e = Event()
            e.set_type(EventType.BIRTH)
            e.set_date_object(d)
            mref = MediaRef()
            mref.set_reference_handle(m_handle)
            e.add_media_reference(mref)
            e_handle = self.db.add_event(e, trans)

            p = Person()
            n = Name()
            s = Surname()
            s.set_surname("Smith")
            n.add_surname(s)
            n.set_first_name("John")
            p.set_primary_name(n)
            eref = EventRef()
            eref.set_reference_handle(e_handle)
            p.add_event_ref(eref)
            p_handle = self.db.add_person(p, trans)

        media = self.db.get_media_from_handle(m_handle)
        ctx = resolve_media_reference_context(self.db, media)
        self.assertEqual(ctx["surname"], "Smith")
        self.assertEqual(ctx["given"], "John")
        self.assertEqual(ctx["year"], "1920")

        std_path = sanitize_standard_filename(media.get_path(), db=self.db, media=media)
        self.assertEqual(
            std_path,
            os.path.join(
                "documents",
                f"{ctx['ref_id']}_Smith_John-Birth_Certificate-1920.png",
            ),
        )

    def test_format_standard_filename_presets(self) -> None:
        """All filename presets produce platform-safe filenames without invalid characters."""
        context = {
            "ref_id": "I0042",
            "surname": "Smith",
            "given": "John",
            "doc_type": "Birth Certificate",
            "year": "1920",
            "id": "O0001",
            "orig": "scan#1 (original)",
            "ext": "JPEG",
        }
        for tmpl, _desc in FILENAME_PRESETS:
            formatted = format_standard_filename(tmpl, context)
            self.assertTrue(formatted.endswith(".jpeg"))
            self.assertNotIn(" ", formatted)
            self.assertNotIn(",", formatted)
            self.assertNotIn("_-_", formatted)
            self.assertNotIn("--", formatted)
            self.assertNotIn("__", formatted)
            self.assertLessEqual(len(formatted), 90)

    def test_gwizard_media_fix_window_buttons(self) -> None:
        """GWizardMediaFix controller initializes with the required buttons."""
        mock_user = MagicMock()
        mock_user.uistate.window = MagicMock()

        tool_instance = GWizardMediaFix.__new__(GWizardMediaFix)
        tool_instance.dbstate = self.dbstate
        tool_instance.buttons = {}
        setattr(tool_instance, "close", MagicMock())
        setattr(tool_instance, "set_window", MagicMock())
        setattr(tool_instance, "setup_configs", MagicMock())

        tool_instance._build_window(mock_user.uistate)

        self.assertIn("generate", tool_instance.buttons)
        self.assertIn("find_missing", tool_instance.buttons)
        self.assertIn("consolidate_location", tool_instance.buttons)
        self.assertIn("apply_standards", tool_instance.buttons)
        self.assertNotIn("view", tool_instance.buttons)

    def test_generate_media_fix_report(self) -> None:
        """Report generation counts missing, found, absolute, and non-standard files."""
        with DbTxn("Create media for report", self.db) as trans:
            m1 = Media()
            m1.set_description("Test Missing")
            m1.set_path("some/missing/file.png")
            self.db.add_media(m1, trans)

        report = generate_media_fix_report(self.db)
        self.assertIn("GWIZARD MEDIA FIX REPORT", report)
        self.assertIn("Total media records:       1", report)
        self.assertIn("Files missing on disk:     1", report)
        self.assertIn("Test Missing", report)


if __name__ == "__main__":
    unittest.main()
