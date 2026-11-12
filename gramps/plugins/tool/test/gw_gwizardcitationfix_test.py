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

"""Tests for GWizardCitationFix and its report generation feature."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
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


class _FakeFileChooserDialog(_FakeDialog):
    def set_current_name(self, name: str) -> None:
        pass

    def set_current_folder(self, folder: str) -> None:
        pass

    def get_filename(self) -> str | None:
        return None


class _FakeBox:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def pack_start(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_homogeneous(self, *args: Any, **kwargs: Any) -> None:
        pass


class _FakeButton:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.sensitive = True

    def set_sensitive(self, val: bool) -> None:
        self.sensitive = val

    def set_hexpand(self, val: bool) -> None:
        pass

    def connect(self, *args: Any, **kwargs: Any) -> None:
        pass


if "gi" not in sys.modules:
    gi_mock = MagicMock()
    gi_mock.repository.Gtk.Dialog = _FakeDialog
    gi_mock.repository.Gtk.FileChooserDialog = _FakeFileChooserDialog
    gi_mock.repository.Gtk.Box = _FakeBox
    gi_mock.repository.Gtk.Button = _FakeButton
    gi_mock.repository.Gtk.ResponseType.OK = 1
    gi_mock.repository.Gtk.ResponseType.CANCEL = 2
    gi_mock.repository.Gtk.ResponseType.CLOSE = 3
    gi_mock.repository.Gtk.ResponseType.NONE = 4
    gi_mock.repository.Gtk.FileChooserAction.SAVE = 1
    gi_mock.repository.Gtk.Orientation.VERTICAL = 1
    gi_mock.repository.Gtk.Orientation.HORIZONTAL = 2
    gi_mock.repository.Gtk.events_pending.return_value = False
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository
else:
    gtk_mod = sys.modules["gi.repository"].Gtk
    gtk_mod.FileChooserDialog = _FakeFileChooserDialog
    gtk_mod.ResponseType.OK = 1
    gtk_mod.ResponseType.CANCEL = 2
    gtk_mod.ResponseType.CLOSE = 3
    gtk_mod.ResponseType.NONE = 4
    gtk_mod.FileChooserAction.SAVE = 1
    gtk_mod.Orientation.VERTICAL = 1
    gtk_mod.Orientation.HORIZONTAL = 2
    gtk_mod.events_pending.return_value = False


# -------------------------------------------------------------------------
#
# GTK mock fallback when running without display or PyGObject
#
# -------------------------------------------------------------------------
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


class _FakeFileChooserDialog(_FakeDialog):
    def set_current_name(self, name: str) -> None:
        pass

    def set_current_folder(self, folder: str) -> None:
        pass

    def get_filename(self) -> str | None:
        return None


class _FakeBox:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def pack_start(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_homogeneous(self, *args: Any, **kwargs: Any) -> None:
        pass


class _FakeButton:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.sensitive = True

    def set_sensitive(self, val: bool) -> None:
        self.sensitive = val

    def set_hexpand(self, val: bool) -> None:
        pass

    def connect(self, *args: Any, **kwargs: Any) -> None:
        pass


if "gi" not in sys.modules:
    gi_mock = MagicMock()
    gi_mock.repository.Gtk.Dialog = _FakeDialog
    gi_mock.repository.Gtk.FileChooserDialog = _FakeFileChooserDialog
    gi_mock.repository.Gtk.Box = _FakeBox
    gi_mock.repository.Gtk.Button = _FakeButton
    gi_mock.repository.Gtk.ResponseType.OK = 1
    gi_mock.repository.Gtk.ResponseType.CANCEL = 2
    gi_mock.repository.Gtk.ResponseType.CLOSE = 3
    gi_mock.repository.Gtk.ResponseType.NONE = 4
    gi_mock.repository.Gtk.FileChooserAction.SAVE = 1
    gi_mock.repository.Gtk.Orientation.VERTICAL = 1
    gi_mock.repository.Gtk.Orientation.HORIZONTAL = 2
    gi_mock.repository.Gtk.events_pending.return_value = False
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository
else:
    gtk_mod = sys.modules["gi.repository"].Gtk
    gtk_mod.FileChooserDialog = _FakeFileChooserDialog
    gtk_mod.ResponseType.OK = 1
    gtk_mod.ResponseType.CANCEL = 2
    gtk_mod.ResponseType.CLOSE = 3
    gtk_mod.ResponseType.NONE = 4
    gtk_mod.FileChooserAction.SAVE = 1
    gtk_mod.Orientation.VERTICAL = 1
    gtk_mod.Orientation.HORIZONTAL = 2
    gtk_mod.events_pending.return_value = False

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.utils import make_database
from gramps.gen.db.generic import DbWriteBase
from gramps.plugins.tool.gwizardcitationfix import (
    GWizardCitationFix,
    get_button_specs,
    REPORT_FILENAME,
)

REPORT_FILENAME = "CitationFixReport.txt"
REPORT_TITLE = "Citation analysis file"
REPORT_LINE_WIDTH = 78


class FakeDbState:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class GWizardCitationFixTest(unittest.TestCase):
    """Test suite for GWizardCitationFix tool."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = FakeDbState(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_get_button_specs(self) -> None:
        """Button specs contain generate but not view."""
        specs = get_button_specs()
        keys = [key for key, _label, _sensitive in specs]
        self.assertIn("generate", keys)
        self.assertNotIn("view", keys)
        self.assertIn("unpack_sources", keys)
        self.assertIn("auto_all", keys)

    def test_gwizard_citation_fix_window_buttons(self) -> None:
        """GWizardCitationFix controller initializes with generate and without view."""
        mock_user = MagicMock()
        mock_user.uistate.window = MagicMock()

        tool_instance = GWizardCitationFix.__new__(GWizardCitationFix)
        tool_instance.dbstate = self.dbstate
        tool_instance.buttons = {}
        setattr(tool_instance, "close", MagicMock())
        setattr(tool_instance, "set_window", MagicMock())
        setattr(tool_instance, "setup_configs", MagicMock())

        tool_instance._build_window(mock_user.uistate)

        self.assertIn("generate", tool_instance.buttons)
        self.assertNotIn("view", tool_instance.buttons)
        self.assertIn("unpack_sources", tool_instance.buttons)
        self.assertIn("consolidate_repositories", tool_instance.buttons)
        self.assertIn("fix_repositories", tool_instance.buttons)
        self.assertIn("fix_sources", tool_instance.buttons)
        self.assertIn("unpack_citations", tool_instance.buttons)
        self.assertIn("fix_citations", tool_instance.buttons)
        self.assertIn("citation_attributes", tool_instance.buttons)
        self.assertIn("link_citation_media", tool_instance.buttons)
        self.assertIn("fix_notes", tool_instance.buttons)
        self.assertIn("auto_all", tool_instance.buttons)

    def test_cb_generate_report_cancel(self) -> None:
        """When file chooser is cancelled, no report is generated."""
        tool_instance = GWizardCitationFix.__new__(GWizardCitationFix)
        tool_instance.dbstate = self.dbstate
        tool_instance.window = MagicMock()
        tool_instance.report_path = None

        mock_chooser = MagicMock()
        mock_chooser.run.return_value = 2  # Gtk.ResponseType.CANCEL

        with (
            patch(
                "gramps.plugins.tool.gwizardcitationfix.Gtk.FileChooserDialog",
                return_value=mock_chooser,
            ),
            patch("gramps.plugins.tool.gwizardcitationfix.OkDialog") as mock_ok,
            patch.object(tool_instance, "cb_view_report") as mock_view,
        ):
            tool_instance.cb_generate_report()
            mock_ok.assert_not_called()
            mock_view.assert_not_called()
            self.assertIsNone(tool_instance.report_path)

    def test_cb_generate_report_save(self) -> None:
        """When file chooser saves, report is written, and view report is invoked."""
        tool_instance = GWizardCitationFix.__new__(GWizardCitationFix)
        tool_instance.dbstate = self.dbstate
        tool_instance.window = MagicMock()
        tool_instance.report_path = None
        setattr(tool_instance, "_pump_events", MagicMock())

        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = os.path.join(tmpdir, REPORT_FILENAME)

            mock_chooser = MagicMock()
            mock_chooser.run.return_value = 1  # Gtk.ResponseType.OK
            mock_chooser.get_filename.return_value = target_path

            mock_engine = MagicMock()
            mock_engine.collect_db_stats.return_value = {"total_citations": 0}
            mock_engine.format_analysis.return_value = "Test Report Content"

            mock_meter = MagicMock()

            with (
                patch(
                    "gramps.plugins.tool.gwizardcitationfix.Gtk.FileChooserDialog",
                    return_value=mock_chooser,
                ),
                patch(
                    "gramps.plugins.tool.gwizardcitationfix.GWizardCitationFixProgressMeter",
                    return_value=mock_meter,
                ),
                patch(
                    "gramps.plugins.tool.gwizardcitationfix.GWizardCitationReport",
                    return_value=mock_engine,
                ),
                patch("gramps.plugins.tool.gwizardcitationfix.OkDialog") as mock_ok,
                patch.object(tool_instance, "cb_view_report") as mock_view,
            ):
                tool_instance.cb_generate_report()

                self.assertTrue(os.path.isfile(target_path))
                with open(target_path, "r", encoding="utf-8") as handle:
                    content = handle.read()
                self.assertIn("Test Report Content", content)
                self.assertEqual(tool_instance.report_path, target_path)
                mock_ok.assert_called_once()
                mock_view.assert_called_once()

    def test_cb_view_report(self) -> None:
        """cb_view_report displays report text in dialog without extra header widget."""
        tool_instance = GWizardCitationFix.__new__(GWizardCitationFix)
        tool_instance.window = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, REPORT_FILENAME)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("Report Line 1\nReport Line 2\n")
            tool_instance.report_path = path

            with (
                patch(
                    "gramps.plugins.tool.gwizardcitationfix.Gtk.Dialog"
                ) as mock_dlg_cls,
                patch(
                    "gramps.plugins.tool.gwizardcitationfix.Gtk.TextView"
                ) as mock_tv_cls,
            ):
                mock_dlg = MagicMock()
                mock_dlg_cls.return_value = mock_dlg
                mock_tv = MagicMock()
                mock_tv_cls.return_value = mock_tv

                tool_instance.cb_view_report()
                mock_dlg.show_all.assert_called_once()
                mock_dlg.run.assert_called_once()
                mock_dlg.destroy.assert_called_once()
                mock_tv.get_buffer().set_text.assert_called_with(
                    "Report Line 1\nReport Line 2\n"
                )

    def test_cb_auto_all_dialog_title_and_text(self) -> None:
        """cb_auto_all prompts QuestionDialog2 with Accept all hints and all steps described."""
        tool_instance = GWizardCitationFix.__new__(GWizardCitationFix)
        tool_instance.dbstate = self.dbstate
        tool_instance.window = MagicMock()

        mock_question = MagicMock()
        mock_question.run.return_value = False

        with patch(
            "gramps.plugins.tool.gwizardcitationfix.QuestionDialog2",
            return_value=mock_question,
        ) as mock_q_cls:
            tool_instance.cb_auto_all()
            mock_q_cls.assert_called_once()
            args, kwargs = mock_q_cls.call_args
            title, msg, btn_ok, btn_cancel = args
            self.assertEqual(title, "Accept all hints")
            self.assertIn("This accepts all hints and applies them without review", msg)
            self.assertIn("unpack source titles", msg)
            self.assertIn("merge duplicate repositories into gold-standard ones", msg)
            self.assertIn("extract dates and URLs from volume/page fields", msg)
            self.assertIn("lower the confidence of user-tree citations", msg)
            self.assertIn("assign Genealogical Proof Standard attributes", msg)
            self.assertIn("delete import debris and empty notes", msg)
            self.assertIn("1. Unpack Conflated Source", msg)
            self.assertIn("2. Repository Consolidate", msg)
            self.assertIn("3. Fix Repositories", msg)
            self.assertIn("4. Fix Sources", msg)
            self.assertIn("5. Unpack Conflated Citation", msg)
            self.assertIn("6. Fix Citations", msg)
            self.assertIn("7. Citation Attributes", msg)
            self.assertIn("8. Link Citation Media", msg)
            self.assertIn("9. Fix Notes", msg)
            self.assertEqual(btn_ok, "_Accept all")

    def test_cb_auto_all_execution_and_human_intervention_report(self) -> None:
        """cb_auto_all runs pipeline and details both automated changes and human intervention items."""
        tool_instance = GWizardCitationFix.__new__(GWizardCitationFix)
        tool_instance.dbstate = self.dbstate
        tool_instance.window = MagicMock()

        mock_question = MagicMock()
        mock_question.run.return_value = True

        mock_dialog = MagicMock()
        mock_dialog.get_content_area.return_value = MagicMock()
        mock_label = MagicMock()

        with (
            patch(
                "gramps.plugins.tool.gwizardcitationfix.Gtk.Dialog",
                return_value=mock_dialog,
            ) as mock_dlg_cls,
            patch(
                "gramps.plugins.tool.gwizardcitationfix.SelectableLabel",
                return_value=mock_label,
            ) as mock_label_cls,
            patch(
                "gramps.plugins.tool.gwizardcitationfix.QuestionDialog2",
                return_value=mock_question,
            ),
        ):
            tool_instance.cb_auto_all()
            mock_dialog.run.assert_called_once()
            _label_args, label_kwargs = mock_label_cls.call_args
            report = label_kwargs["label"]
            self.assertIsInstance(report, str)
            # Dialog title is "Accept All Hints Complete"
            _args, kwargs = mock_dlg_cls.call_args
            self.assertEqual(kwargs["title"], "Accept All Hints Complete")
            self.assertIn("AUTOMATED CHANGES PERFORMED:", report)
            self.assertIn("1. Unpack Conflated Source:", report)
            self.assertIn("2. Repository Consolidate:", report)
            self.assertIn("3. Fix Repositories:", report)
            self.assertIn("4. Fix Sources:", report)
            self.assertIn("5. Unpack Conflated Citation:", report)
            self.assertIn("6. Fix Citations:", report)
            self.assertIn("7. Citation Attributes:", report)
            self.assertIn("8. Link Citation Media:", report)
            self.assertIn("9. Fix Notes:", report)
            # Without unresolved items in an empty DB, reports no human intervention needed
            self.assertIn("No human intervention required", report)

    def test_cb_auto_all_with_human_intervention_items(self) -> None:
        """cb_auto_all lists layers requiring human intervention when items cannot be automatically resolved."""
        from gramps.gen.db import DbTxn
        from gramps.gen.lib import Source, Citation

        with DbTxn("Create unresolved source and citation", self.db) as trans:
            # Orphan source with mysterious title that cannot be linked to any golden repository
            s = Source()
            s.set_title("Mysterious Unknown Handwritten Scrapbook 1899")
            s_handle = self.db.add_source(s, trans)

            # Citation without keywords for GPS attribute inference
            c = Citation()
            c.set_reference_handle(s_handle)
            c.set_page("Page 42")
            self.db.add_citation(c, trans)

        tool_instance = GWizardCitationFix.__new__(GWizardCitationFix)
        tool_instance.dbstate = self.dbstate
        tool_instance.window = MagicMock()

        mock_question = MagicMock()
        mock_question.run.return_value = True

        mock_dialog = MagicMock()
        mock_dialog.get_content_area.return_value = MagicMock()
        mock_label = MagicMock()

        with (
            patch(
                "gramps.plugins.tool.gwizardcitationfix.Gtk.Dialog",
                return_value=mock_dialog,
            ) as mock_dlg_cls,
            patch(
                "gramps.plugins.tool.gwizardcitationfix.SelectableLabel",
                return_value=mock_label,
            ) as mock_label_cls,
            patch(
                "gramps.plugins.tool.gwizardcitationfix.QuestionDialog2",
                return_value=mock_question,
            ),
        ):
            tool_instance.cb_auto_all()
            mock_dialog.run.assert_called_once()
            _label_args, label_kwargs = mock_label_cls.call_args
            report = label_kwargs["label"]
            self.assertIsInstance(report, str)
            _args, kwargs = mock_dlg_cls.call_args
            self.assertEqual(kwargs["title"], "Accept All Hints Complete")
            self.assertIn("AUTOMATED CHANGES PERFORMED:", report)
            self.assertIn("CHANGES REQUIRING HUMAN INTERVENTION:", report)
            self.assertIn("Fix Repositories", report)
            self.assertIn("Citation Attributes", report)


if __name__ == "__main__":
    unittest.main()
