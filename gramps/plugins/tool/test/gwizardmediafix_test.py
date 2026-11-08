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
from __future__ import annotations
import os
import shutil
import sys
import tempfile
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

    class _FakeEntry:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._text = ""
            self._callbacks: list[Any] = []

        def set_text(self, val: str) -> None:
            self._text = val
            for cb in self._callbacks:
                try:
                    cb()
                except Exception:
                    pass

        def get_text(self) -> str:
            return self._text

        def set_width_chars(self, val: int) -> None:
            pass

        def set_hexpand(self, val: bool) -> None:
            pass

        def connect(self, signal: str, callback: Any, *args: Any) -> None:
            if signal == "changed":
                self._callbacks.append(callback)

    class _FakeRadioButton:
        def __init__(self, group: Any = None, label: str = "") -> None:
            self._active = False
            self.group = group if group is not None else self
            self._peers = [self]
            if group is not None and hasattr(group, "_peers"):
                group._peers.append(self)
                self._peers = group._peers
            self.label = label
            self._callbacks: list[Any] = []

        @classmethod
        def new_with_label_from_widget(
            cls, group: Any = None, label: str = ""
        ) -> _FakeRadioButton:
            btn = cls(group, label)
            if group is None:
                btn._active = True
            return btn

        def set_active(self, val: bool) -> None:
            self._active = val
            if val:
                for peer in self._peers:
                    if peer is not self:
                        peer._active = False
            for cb in self._callbacks:
                try:
                    cb(self)
                except Exception:
                    pass

        def get_active(self) -> bool:
            return self._active

        def connect(self, signal: str, callback: Any, *args: Any) -> None:
            if signal == "toggled":
                self._callbacks.append(callback)

    class _FakeComboBoxText:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._active = 0
            self._items: list[str] = []
            self._child = _FakeEntry()

        @classmethod
        def new_with_entry(cls) -> _FakeComboBoxText:
            return cls()

        def get_child(self) -> _FakeEntry:
            return self._child

        def append_text(self, text: str) -> None:
            self._items.append(text)

        def set_active(self, val: int) -> None:
            self._active = val

        def get_active(self) -> int:
            return self._active

        def set_hexpand(self, val: bool) -> None:
            pass

        def connect(self, *args: Any, **kwargs: Any) -> None:
            pass

    gi_mock.repository.Gtk.Dialog = _FakeDialog
    gi_mock.repository.Gtk.Label = _FakeLabel
    gi_mock.repository.Gtk.Grid = _FakeGrid
    gi_mock.repository.Gtk.Entry = _FakeEntry
    gi_mock.repository.Gtk.RadioButton = _FakeRadioButton
    gi_mock.repository.Gtk.ComboBoxText = _FakeComboBoxText
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository

from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import USER_HOME
from gramps.gen.db.utils import make_database
from gramps.gen.db.generic import DbWriteBase
from gramps.gen.db import DbTxn
from gramps.gen.errors import HandleError
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
    Citation,
    Source,
)
from gramps.plugins.tool.gwizardmediafix import (
    GWizardMediaFix,
    FindMissingMediaDialog,
    ConsolidateMediaLocationDialog,
    FixMediaReferencesDialog,
    ApplyFilenameStandardsDialog,
    MediaFixReportDialog,
    get_media_base_path,
    is_in_default_path,
    find_unreferenced_default_path_files,
    sanitize_standard_filename,
    generate_media_fix_report,
    resolve_media_reference_context,
    format_standard_filename,
    find_duplicate_media_references,
    DEFAULT_FILENAME_TEMPLATE,
    FILENAME_PRESETS,
    check_path_permission,
    get_path_ancestors,
)
from gramps.plugins.tool.fixmediareferencesdialog import (
    find_duplicate_media_groups,
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
        expected_sug = os.path.normpath(
            os.path.join(dlg.base_dir, f"{m.get_gramps_id()}-Scattered_photo.jpg")
        )
        self.assertEqual(os.path.normpath(row["suggested_path"]), expected_sug)

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
        """FixMediaReferencesDialog resolves duplicate references where a single media file is used for multiple references."""
        with DbTxn("Create duplicate media", self.db) as trans:
            m1 = Media()
            m1.set_description("Photo 1")
            m1.set_path("shared/file.jpg")
            m1_h = self.db.add_media(m1, trans)

            m2 = Media()
            m2.set_description("Photo 2")
            m2.set_path("shared/file.jpg")
            m2_h = self.db.add_media(m2, trans)

            p1 = Person()
            mr1 = MediaRef()
            mr1.set_reference_handle(m1_h)
            p1.add_media_reference(mr1)
            self.db.add_person(p1, trans)

        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        self.assertEqual(len(dlg.groups), 1)
        group = dlg.groups[0]
        self.assertEqual(group["keeper"]["handle"], m1_h)
        self.assertEqual(len(group["records"]), 2)

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
        self.assertIn("fix_references", tool_instance.buttons)
        self.assertNotIn("apply_standards", tool_instance.buttons)
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
        self.assertIn("Duplicate file references:", report)

    def test_citation_backlink_deep_traversal(self) -> None:
        """Citation backlinks traverse through Event to Person to extract surname and event type."""
        with DbTxn("Create citation hierarchy", self.db) as trans:
            s = Source()
            s.set_title("FamilySearch")
            s_h = self.db.add_source(s, trans)

            c = Citation()
            c.set_page("p. 42")
            c.set_reference_handle(s_h)
            c_h = self.db.add_citation(c, trans)

            m = Media()
            m.set_path("C:/gramps_dev/Fuller, Harry Jay - 1910Census.jpg")
            m.set_description("1910 Census scan")
            m_h = self.db.add_media(m, trans)

            mref = MediaRef()
            mref.set_reference_handle(m_h)
            c.add_media_reference(mref)
            self.db.commit_citation(c, trans)

            e = Event()
            e.set_type(EventType.CENSUS)
            e.set_description("1910 Census")
            d = Date()
            d.set_year(1910)
            e.set_date_object(d)
            e.add_citation(c_h)
            e_h = self.db.add_event(e, trans)

            p = Person()
            n = Name()
            sur = Surname()
            sur.set_surname("Fuller")
            n.add_surname(sur)
            n.set_first_name("Harry Jay")
            p.set_primary_name(n)
            eref = EventRef()
            eref.set_reference_handle(e_h)
            p.add_event_ref(eref)
            p_h = self.db.add_person(p, trans)

        media = self.db.get_media_from_handle(m_h)
        ctx = resolve_media_reference_context(self.db, media)
        self.assertEqual(ctx["surname"], "Fuller")
        self.assertEqual(ctx["given"], "Harry Jay")
        self.assertEqual(ctx["doc_type"], "Census_scan")
        self.assertEqual(ctx["year"], "1910")
        self.assertIn("Citation:", ctx["assoc"])
        self.assertIn("Event: Census 1910", ctx["assoc"])
        self.assertIn("Fuller, Harry Jay", ctx["assoc"])

        std = sanitize_standard_filename(media.get_path(), db=self.db, media=media)
        self.assertEqual(
            std,
            os.path.join(
                "C:/gramps_dev",
                f"{ctx['ref_id']}_Fuller_Harry_Jay-Census_scan-1910.jpg",
            ),
        )

    def test_deduplicate_name_and_document_year(self) -> None:
        """Redundant names in descriptions are stripped and document year takes precedence over birth year."""
        with DbTxn("Create Duvault media", self.db) as trans:
            m = Media()
            m.set_description("Duvault, Nettie - 1900Census")
            m.set_path("Media/Duvault, Nettie - 1900Census.jpg")
            m_h = self.db.add_media(m, trans)

            p = Person()
            n = Name()
            s = Surname()
            s.set_surname("Devault")
            n.add_surname(s)
            n.set_first_name("Nettie")
            p.set_primary_name(n)

            # Person's birth event is 1885
            d = Date()
            d.set_year(1885)
            e = Event()
            e.set_type(EventType.BIRTH)
            e.set_date_object(d)
            e_h = self.db.add_event(e, trans)
            eref = EventRef()
            eref.set_reference_handle(e_h)
            p.add_event_ref(eref)

            mref = MediaRef()
            mref.set_reference_handle(m_h)
            p.add_media_reference(mref)
            p_h = self.db.add_person(p, trans)

        media = self.db.get_media_from_handle(m_h)
        ctx = resolve_media_reference_context(self.db, media)
        self.assertEqual(ctx["surname"], "Devault")
        self.assertEqual(ctx["given"], "Nettie")
        # Document year 1900 from description overrides birth year 1885
        self.assertEqual(ctx["year"], "1900")
        self.assertEqual(ctx["doc_type"], "Census")

        std = sanitize_standard_filename(media.get_path(), db=self.db, media=media)
        self.assertEqual(
            std,
            os.path.join(
                "Media",
                f"{ctx['ref_id']}_Devault_Nettie-Census-1900.jpg",
            ),
        )

    def test_duplicate_media_references_detection_and_sync(self) -> None:
        """Duplicate media records pointing to the same file are detected and synchronized."""
        with DbTxn("Create duplicate media", self.db) as trans:
            for i in range(3):
                m = Media()
                m.set_description("Fuller 1910 Census")
                m.set_path("C:/gramps_dev/Fuller, Harry Jay - 1910Census.jpg")
                self.db.add_media(m, trans)

        dups = find_duplicate_media_references(self.db)
        self.assertEqual(len(dups), 1)
        records = list(dups.values())[0]
        self.assertEqual(len(records), 3)

        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        self.assertEqual(len(dlg.groups), 1)
        self.assertEqual(len(dlg.groups[0]["records"]), 3)

        report = generate_media_fix_report(self.db)
        self.assertIn("DUPLICATE FILE REFERENCES", report)
        self.assertIn("Referenced by 3 media records", report)

    def test_get_media_base_path(self) -> None:
        """get_media_base_path retrieves configured database media path or falls back to USER_HOME."""
        # Unconfigured / None fallback to USER_HOME
        self.db.set_mediapath(None)
        self.assertEqual(
            get_media_base_path(self.db), os.path.normpath(os.path.abspath(USER_HOME))
        )

        # Empty string fallback to USER_HOME
        self.db.set_mediapath("   ")
        self.assertEqual(
            get_media_base_path(self.db), os.path.normpath(os.path.abspath(USER_HOME))
        )

        # None db fallback to USER_HOME
        self.assertEqual(
            get_media_base_path(None), os.path.normpath(os.path.abspath(USER_HOME))
        )

        # Configured path is returned normalized
        custom_path = os.path.join(USER_HOME, "CustomFamilyMedia")
        self.db.set_mediapath(custom_path)
        self.assertEqual(
            get_media_base_path(self.db), os.path.normpath(os.path.abspath(custom_path))
        )

    def test_media_fix_report_dialog_displays_base_path(self) -> None:
        """MediaFixReportDialog displays the media base path near the top."""
        custom_path = os.path.join(USER_HOME, "TestReportMediaPath")
        self.db.set_mediapath(custom_path)
        dlg = MediaFixReportDialog(
            report_text="Sample report content",
            dbstate=self.dbstate,
        )
        self.assertEqual(dlg.base_dir, os.path.normpath(os.path.abspath(custom_path)))
        self.assertTrue(hasattr(dlg, "base_path_label"))
        self.assertIn(
            os.path.normpath(os.path.abspath(custom_path)),
            dlg.base_path_label.markup or dlg.base_path_label.text,
        )
        self.assertEqual(dlg.report_text, "Sample report content")

    def test_consolidate_media_location_base_path_display(self) -> None:
        """ConsolidateMediaLocationDialog displays the media base path near the top and suggests relative paths."""
        custom_path = os.path.join(USER_HOME, "ConsolidateTestMedia")
        self.db.set_mediapath(custom_path)

        with DbTxn("Create media in custom path", self.db) as trans:
            m = Media()
            m.set_description("Absolute inside base")
            target_file = os.path.join(custom_path, "sub", "photo.jpg")
            m.set_path(target_file)
            self.db.add_media(m, trans)

        dlg = ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        self.assertEqual(dlg.base_dir, os.path.normpath(os.path.abspath(custom_path)))
        self.assertTrue(hasattr(dlg, "base_path_label"))
        self.assertIn(
            os.path.normpath(os.path.abspath(custom_path)),
            dlg.base_path_label.markup or dlg.base_path_label.text,
        )
        self.assertEqual(len(dlg.rows), 1)
        # Value in Hint should be base media path plus filename with naming standard
        std_fname = f"{m.get_gramps_id()}-Absolute_inside_base.jpg"
        expected_std = os.path.normpath(os.path.join(custom_path, std_fname))
        self.assertEqual(
            os.path.normpath(dlg.rows[0]["suggested_path"]),
            expected_std,
        )
        self.assertEqual(
            os.path.normpath(dlg.rows[0]["hint_text"]),
            expected_std,
        )

        # Switch to Keep original filename radio button
        dlg.radio_keep_original.set_active(True)
        dlg._recompute_hints()
        expected_orig = os.path.normpath(os.path.join(custom_path, "photo.jpg"))
        self.assertEqual(
            os.path.normpath(dlg.rows[0]["suggested_path"]),
            expected_orig,
        )
        self.assertEqual(
            os.path.normpath(dlg.rows[0]["hint_text"]),
            expected_orig,
        )

        # Accept hints copies to Consolidated Path textbox
        with patch("gramps.plugins.tool.gwizardmediafix.OkDialog"):
            dlg.cb_accept_hints(MagicMock())
        self.assertEqual(
            os.path.normpath(dlg.row_targets[0]["path_entry"].get_text()),
            expected_orig,
        )

    def test_consolidate_media_location_path_selector_widget(self) -> None:
        """ConsolidateMediaLocationDialog provides a path selector widget that sets database media path."""
        custom_path = os.path.join(USER_HOME, "SelectorTestMedia")
        self.db.set_mediapath(custom_path)

        dlg = ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        self.assertTrue(hasattr(dlg, "path_entry"))
        self.assertTrue(hasattr(dlg, "path_button"))
        self.assertEqual(dlg.path_entry.get_text(), custom_path)

        # Changing path_entry directly updates db mediapath and recomputes base_dir
        new_path = os.path.join(USER_HOME, "NewMediaFolder")
        dlg.path_entry.set_text(new_path)
        dlg.cb_set_mediapath()
        self.assertEqual(self.db.get_mediapath(), new_path)
        self.assertEqual(dlg.base_dir, os.path.normpath(os.path.abspath(new_path)))

        # Selecting folder from chooser dialog sets path on entry and database
        chosen_folder = os.path.join(USER_HOME, "ChosenFolder")
        mock_chooser = MagicMock()
        mock_chooser.run.return_value = Gtk.ResponseType.OK
        mock_chooser.get_filename.return_value = chosen_folder

        with patch(
            "gramps.plugins.tool.gwizardmediafix.Gtk.FileChooserDialog",
            return_value=mock_chooser,
        ):
            dlg.cb_select_mediapath()
            self.assertEqual(self.db.get_mediapath(), chosen_folder)
            self.assertEqual(dlg.path_entry.get_text(), chosen_folder)

    def test_consolidate_media_location_radio_buttons_move_vs_copy(self) -> None:
        """ConsolidateMediaLocationDialog provides radio buttons for move files vs make a copy."""
        dlg = ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        self.assertTrue(hasattr(dlg, "radio_move"))
        self.assertTrue(hasattr(dlg, "radio_copy"))
        self.assertTrue(dlg.radio_move.get_active())
        self.assertFalse(dlg.radio_copy.get_active())

        with DbTxn("Create media for move", self.db) as trans:
            m = Media()
            m.set_description("Test Move")
            m.set_path("/path/to/test.jpg")
            m_h = self.db.add_media(m, trans)

        mock_entry = MagicMock()
        mock_entry.get_text.return_value = "new_folder/test.jpg"
        dlg.row_targets = [
            {
                "entry": {"handle": m_h, "raw_path": "/path/to/test.jpg"},
                "path_entry": mock_entry,
            }
        ]

        with (
            patch(
                "gramps.plugins.tool.gwizardmediafix.os.path.exists", return_value=True
            ),
            patch("gramps.plugins.tool.gwizardmediafix.os.makedirs"),
            patch("gramps.plugins.tool.gwizardmediafix.shutil.move") as mock_move,
            patch("gramps.plugins.tool.gwizardmediafix.shutil.copy2") as mock_copy,
            patch("gramps.plugins.tool.gwizardmediafix.OkDialog"),
        ):
            dlg.cb_apply(MagicMock())
            mock_move.assert_called_once()
            mock_copy.assert_not_called()

        dlg.radio_copy.set_active(True)
        with (
            patch(
                "gramps.plugins.tool.gwizardmediafix.os.path.exists", return_value=True
            ),
            patch("gramps.plugins.tool.gwizardmediafix.os.makedirs"),
            patch("gramps.plugins.tool.gwizardmediafix.shutil.move") as mock_move,
            patch("gramps.plugins.tool.gwizardmediafix.shutil.copy2") as mock_copy,
            patch("gramps.plugins.tool.gwizardmediafix.OkDialog"),
        ):
            dlg.cb_apply(MagicMock())
            mock_copy.assert_called_once()
            mock_move.assert_not_called()

    def test_find_and_consolidate_quotes_and_spaces(self) -> None:
        """Find Media and Consolidate operations handle paths enclosed in quotes and containing spaces."""
        temp_dir = tempfile.mkdtemp()
        try:
            # File with spaces on disk
            real_file = os.path.join(temp_dir, "My Photo File 1920.jpg")
            with open(real_file, "w") as f:
                f.write("content")

            with DbTxn("Create media with missing path", self.db) as trans:
                m = Media()
                m.set_description("Photo with spaces")
                m.set_path("missing/old photo.jpg")
                m_h = self.db.add_media(m, trans)

            dlg_find = FindMissingMediaDialog(dbstate=self.dbstate)
            self.assertEqual(len(dlg_find.rows), 1)

            # User enters/pastes path enclosed in quotes (e.g. copied from Windows Explorer)
            quoted_input = f'"{real_file}"'
            mock_entry = MagicMock()
            mock_entry.get_text.return_value = quoted_input
            dlg_find.row_targets = [
                {"entry": dlg_find.rows[0], "path_entry": mock_entry}
            ]

            with patch("gramps.plugins.tool.gwizardmediafix.OkDialog"):
                dlg_find.cb_apply(MagicMock())

            # Path stored in database must be stripped of quotes
            updated = self.db.get_media_from_handle(m_h)
            self.assertEqual(updated.get_path(), real_file)
            self.assertFalse(updated.get_path().startswith('"'))

            # Report should now find the file on disk instead of reporting it missing
            report = generate_media_fix_report(self.db)
            self.assertIn("Files found on disk:       1", report)
            self.assertIn("Files missing on disk:     0", report)

            # Consolidate media location with spaces and quotes in base path
            base_dir = os.path.join(temp_dir, "Consolidated Media Base")
            os.makedirs(base_dir, exist_ok=True)
            self.db.set_mediapath(f'"{base_dir}"')

            dlg_cons = ConsolidateMediaLocationDialog(dbstate=self.dbstate)
            self.assertEqual(
                dlg_cons.base_dir, os.path.normpath(os.path.abspath(base_dir))
            )

            # User accepts hints or inputs path
            hint_sug = dlg_cons.rows[0]["suggested_path"]
            self.assertIn("Photo_with_spaces.jpg", hint_sug)
            self.assertIn("Consolidated Media Base", hint_sug)

            mock_cons_entry = MagicMock()
            mock_cons_entry.get_text.return_value = f'"{hint_sug}"'
            dlg_cons.row_targets[0]["path_entry"] = mock_cons_entry

            with patch("gramps.plugins.tool.gwizardmediafix.OkDialog"):
                dlg_cons.cb_apply(MagicMock())

            # File should be moved to destination and updated in DB without quotes
            updated_cons = self.db.get_media_from_handle(m_h)
            self.assertEqual(
                os.path.normpath(updated_cons.get_path()), os.path.normpath(hint_sug)
            )
            self.assertTrue(os.path.exists(hint_sug))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_media_fix_report_includes_base_path(self) -> None:
        """generate_media_fix_report includes Media Base Path in summary metrics."""
        custom_path = os.path.join(USER_HOME, "ReportMetricsMedia")
        self.db.set_mediapath(custom_path)
        report = generate_media_fix_report(self.db)
        self.assertIn("Media Base Path:", report)
        self.assertIn(os.path.normpath(os.path.abspath(custom_path)), report)

    def test_is_in_default_path(self) -> None:
        """is_in_default_path detects relative and absolute paths within base_dir."""
        base = os.path.join(USER_HOME, "MediaBase")
        self.assertTrue(is_in_default_path("photos/family.jpg", base))
        self.assertTrue(is_in_default_path("simple.png", base))
        self.assertTrue(
            is_in_default_path(os.path.join(base, "photos", "family.jpg"), base)
        )
        self.assertFalse(
            is_in_default_path(os.path.join(USER_HOME, "OtherDir", "pic.jpg"), base)
        )
        self.assertFalse(is_in_default_path("", base))
        self.assertFalse(is_in_default_path("photos/family.jpg", ""))

    def test_find_unreferenced_default_path_files(self) -> None:
        """find_unreferenced_default_path_files finds files on disk not connected to database media objects."""
        temp_dir = tempfile.mkdtemp()
        try:
            # Create two files on disk
            ref_file = os.path.join(temp_dir, "referenced.jpg")
            with open(ref_file, "w") as f:
                f.write("content")
            unref_file = os.path.join(temp_dir, "unreferenced.png")
            with open(unref_file, "w") as f:
                f.write("content")

            # Reference only ref_file in the database
            with DbTxn("Add referenced media", self.db) as trans:
                m = Media()
                m.set_path(ref_file)
                self.db.add_media(m, trans)

            unref_list = find_unreferenced_default_path_files(self.db, temp_dir)
            self.assertEqual(len(unref_list), 1)
            self.assertEqual(unref_list[0], "unreferenced.png")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_media_multiple_and_zero_database_references(self) -> None:
        """generate_media_fix_report detects media records with multiple links and zero links."""
        with DbTxn("Create media with various references", self.db) as trans:
            # Media 1: referenced by 2 people (multiple references)
            m1 = Media()
            m1.set_description("Shared Photo")
            m1.set_path("shared.jpg")
            m1_handle = self.db.add_media(m1, trans)

            p1 = Person()
            mr1 = MediaRef()
            mr1.set_reference_handle(m1_handle)
            p1.add_media_reference(mr1)
            self.db.add_person(p1, trans)

            p2 = Person()
            mr2 = MediaRef()
            mr2.set_reference_handle(m1_handle)
            p2.add_media_reference(mr2)
            self.db.add_person(p2, trans)

            # Media 2: unreferenced (0 backlinks)
            m2 = Media()
            m2.set_description("Orphan Media")
            m2.set_path("orphan.jpg")
            self.db.add_media(m2, trans)

        report = generate_media_fix_report(self.db)
        self.assertIn("Multiple database links:   1", report)
        self.assertIn("Unreferenced image tags:   1", report)
        self.assertIn("MEDIA RECORDS WITH MULTIPLE DATABASE REFERENCES", report)
        self.assertIn("Shared Photo", report)
        self.assertIn("References: 2 (Person: 2)", report)
        self.assertIn("UNREFERENCED IMAGE TAGS / MEDIA RECORDS", report)
        self.assertIn("Orphan Media", report)

    def test_report_default_path_counts(self) -> None:
        """generate_media_fix_report accurately reports default path and outside default path counts."""
        temp_dir = tempfile.mkdtemp()
        try:
            self.db.set_mediapath(temp_dir)
            with DbTxn("Add inside and outside media", self.db) as trans:
                # Media inside default path (relative)
                m_rel = Media()
                m_rel.set_path("inside/photo.jpg")
                self.db.add_media(m_rel, trans)

                # Media outside default path (absolute to other folder)
                other_dir = tempfile.mkdtemp()
                try:
                    m_outside = Media()
                    m_outside.set_path(os.path.join(other_dir, "outside.jpg"))
                    self.db.add_media(m_outside, trans)

                    report = generate_media_fix_report(self.db)
                    self.assertIn("Files in default path:     1", report)
                    self.assertIn("Files outside default path:1", report)
                    self.assertIn("FILES OUTSIDE DEFAULT PATH", report)
                finally:
                    shutil.rmtree(other_dir, ignore_errors=True)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_find_duplicate_media_groups(self) -> None:
        """find_duplicate_media_groups detects duplicate media records pointing to the same file."""
        with DbTxn("Create duplicate media records", self.db) as trans:
            m1 = Media()
            m1.set_description("Photo 1")
            m1.set_path("shared/sample.jpg")
            m1_h = self.db.add_media(m1, trans)

            m2 = Media()
            m2.set_description("Photo 2")
            m2.set_path("shared/sample.jpg")
            m2_h = self.db.add_media(m2, trans)

            # Person links to m1
            p = Person()
            mref = MediaRef()
            mref.set_reference_handle(m1_h)
            p.add_media_reference(mref)
            self.db.add_person(p, trans)

        groups = find_duplicate_media_groups(self.db)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(len(g["records"]), 2)
        # Keeper should be m1 because it has a backlink from Person
        self.assertEqual(g["keeper"]["handle"], m1_h)

    def test_fix_media_references_dialog_merge(self) -> None:
        """FixMediaReferencesDialog merges duplicate records into keeper."""
        with DbTxn("Create duplicate media for merge", self.db) as trans:
            m1 = Media()
            m1.set_description("Primary Photo")
            m1.set_path("shared/test.jpg")
            m1_h = self.db.add_media(m1, trans)

            p1 = Person()
            mr1 = MediaRef()
            mr1.set_reference_handle(m1_h)
            p1.add_media_reference(mr1)
            self.db.add_person(p1, trans)

            m2 = Media()
            m2.set_description("Duplicate Photo")
            m2.set_path("shared/test.jpg")
            m2_h = self.db.add_media(m2, trans)

            p2 = Person()
            mref = MediaRef()
            mref.set_reference_handle(m2_h)
            p2.add_media_reference(mref)
            p2_h = self.db.add_person(p2, trans)

        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        self.assertEqual(len(dlg.groups), 1)

        # Select option 0: merge into keeper
        mock_combo = MagicMock()
        mock_combo.get_active.return_value = 0
        dlg.row_targets = [
            {
                "group": dlg.groups[0],
                "action_combo": mock_combo,
            }
        ]

        with patch("gramps.plugins.tool.fixmediareferencesdialog.OkDialog"):
            dlg.cb_apply(MagicMock())

        # m2 should be merged into m1 and removed
        self.assertIsNotNone(self.db.get_media_from_handle(m1_h))
        with self.assertRaises(HandleError):
            self.db.get_media_from_handle(m2_h)

        # Person p2's media reference should now point to m1
        person = self.db.get_person_from_handle(p2_h)
        self.assertEqual(person.get_media_list()[0].get_reference_handle(), m1_h)

    def test_fix_media_references_dialog_copy(self) -> None:
        """FixMediaReferencesDialog creates separate copies of files for duplicate records."""
        with DbTxn("Create duplicate media for copy", self.db) as trans:
            m1 = Media()
            m1.set_description("Photo A")
            m1.set_path("shared/picture.jpg")
            m1_h = self.db.add_media(m1, trans)

            m2 = Media()
            m2.set_description("Photo B")
            m2.set_path("shared/picture.jpg")
            m2_h = self.db.add_media(m2, trans)

        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        mock_combo = MagicMock()
        mock_combo.get_active.return_value = 1  # Create copies
        dlg.row_targets = [
            {
                "group": dlg.groups[0],
                "action_combo": mock_combo,
            }
        ]

        with (
            patch(
                "gramps.plugins.tool.fixmediareferencesdialog.os.path.exists",
                return_value=True,
            ),
            patch("gramps.plugins.tool.fixmediareferencesdialog.os.makedirs"),
            patch(
                "gramps.plugins.tool.fixmediareferencesdialog.shutil.copy2"
            ) as mock_copy,
            patch("gramps.plugins.tool.fixmediareferencesdialog.OkDialog"),
        ):
            dlg.cb_apply(MagicMock())
            mock_copy.assert_called_once()

        # m2 path should now be updated to a distinct file path
        updated_m2 = self.db.get_media_from_handle(m2_h)
        self.assertNotEqual(updated_m2.get_path(), "shared/picture.jpg")
        self.assertIn("picture", updated_m2.get_path())

    def test_report_zero_unreferenced_image_tags(self) -> None:
        """Report explicitly notes when zero unreferenced image tags are found."""
        with DbTxn("Create referenced media", self.db) as trans:
            m = Media()
            m.set_path("referenced/photo.jpg")
            m_h = self.db.add_media(m, trans)

            p = Person()
            mref = MediaRef()
            mref.set_reference_handle(m_h)
            p.add_media_reference(mref)
            self.db.add_person(p, trans)

        report = generate_media_fix_report(self.db)
        self.assertIn("Unreferenced image tags:   0", report)
        self.assertIn("0 unreferenced image tags found", report)

    def test_fix_media_references_dialog_delete_unreferenced(self) -> None:
        """FixMediaReferencesDialog detects and deletes unreferenced image tags."""
        with DbTxn("Create unreferenced media", self.db) as trans:
            m = Media()
            m.set_description("Orphan Image Tag")
            m.set_path("orphan/image.jpg")
            m_h = self.db.add_media(m, trans)

        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        unref_groups = [g for g in dlg.groups if g.get("type") == "unreferenced"]
        self.assertEqual(len(unref_groups), 1)
        self.assertEqual(unref_groups[0]["keeper"]["handle"], m_h)

        # Apply deletion (choice 0)
        with patch("gramps.plugins.tool.fixmediareferencesdialog.OkDialog"):
            dlg.cb_apply(MagicMock())

        # Media record should now be deleted from database
        with self.assertRaises(HandleError):
            self.db.get_media_from_handle(m_h)

    def test_check_path_permission_ancestors(self) -> None:
        """check_path_permission identifies the highest-level directory that cannot be read."""
        temp_dir = tempfile.mkdtemp()
        try:
            restricted_dir = os.path.join(temp_dir, "RestrictedDir")
            os.makedirs(restricted_dir)
            test_file = os.path.join(restricted_dir, "nested", "photo.jpg")

            orig_scandir = os.scandir

            def mock_scandir(p: Any) -> Any:
                if os.path.normcase(str(p)) == os.path.normcase(restricted_dir):
                    raise PermissionError(13, "Access is denied", restricted_dir)
                return orig_scandir(p)

            with patch(
                "gramps.plugins.tool.gwizardmediafix.os.scandir",
                side_effect=mock_scandir,
            ):
                has_issue, inaccess = check_path_permission(test_file)
                self.assertTrue(has_issue)
                self.assertEqual(
                    os.path.normcase(inaccess or ""),
                    os.path.normcase(restricted_dir),
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_report_permission_denied_file(self) -> None:
        """generate_media_fix_report lists permission-denied files with the highest inaccessible directory."""
        temp_dir = tempfile.mkdtemp()
        try:
            restricted_dir = os.path.join(temp_dir, "RestrictedVault")
            os.makedirs(restricted_dir)
            test_file = os.path.join(restricted_dir, "secret_photo.jpg")

            with DbTxn("Create media in restricted folder", self.db) as trans:
                m = Media()
                m.set_description("Vault Photo")
                m.set_path(test_file)
                self.db.add_media(m, trans)

            orig_scandir = os.scandir

            def mock_scandir(p: Any) -> Any:
                if os.path.normcase(str(p)) == os.path.normcase(restricted_dir):
                    raise PermissionError(13, "Access is denied", restricted_dir)
                return orig_scandir(p)

            with patch(
                "gramps.plugins.tool.gwizardmediafix.os.scandir",
                side_effect=mock_scandir,
            ):
                report = generate_media_fix_report(self.db)
                self.assertIn("Permission denied files:   1", report)
                self.assertIn("PERMISSION DENIED FILES (1 files inaccessible", report)
                self.assertIn("Inaccessible at:", report)
                self.assertIn("RestrictedVault", report)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_find_missing_media_hint_permission_denied(self) -> None:
        """FindMissingMediaDialog displays permission denial in Hint column."""
        temp_dir = tempfile.mkdtemp()
        try:
            no_access_dir = os.path.join(temp_dir, "NoAccessFolder")
            os.makedirs(no_access_dir)
            test_file = os.path.join(no_access_dir, "pic.jpg")

            with DbTxn("Create media in no-access folder", self.db) as trans:
                m = Media()
                m.set_description("No Access Pic")
                m.set_path(test_file)
                self.db.add_media(m, trans)

            orig_scandir = os.scandir

            def mock_scandir(p: Any) -> Any:
                if os.path.normcase(str(p)) == os.path.normcase(no_access_dir):
                    raise PermissionError(13, "Access is denied", no_access_dir)
                return orig_scandir(p)

            with patch(
                "gramps.plugins.tool.gwizardmediafix.os.scandir",
                side_effect=mock_scandir,
            ):
                dlg = FindMissingMediaDialog(dbstate=self.dbstate)
                self.assertEqual(len(dlg.rows), 1)
                self.assertTrue(dlg.rows[0]["perm_denied"])
                self.assertIn("Permission denied", dlg.rows[0]["hint_text"])
                self.assertIn("NoAccessFolder", dlg.rows[0]["hint_text"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
