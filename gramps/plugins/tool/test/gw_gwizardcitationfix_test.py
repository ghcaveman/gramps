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
            self.assertIn("consolidate duplicate repositories and sources", msg)
            self.assertIn("unpack conflated citations", msg)
            self.assertIn("refine citations", msg)
            self.assertIn("assign citation attributes", msg)
            self.assertIn("permanently delete import debris notes", msg)
            self.assertIn("1. Unpack Conflated Source", msg)
            self.assertIn("2. Repository Consolidate", msg)
            self.assertIn("3. Fix Repositories", msg)
            self.assertIn("4. Fix Sources", msg)
            self.assertIn("5. Unpack Conflated Citation", msg)
            self.assertIn("6. Fix Citations", msg)
            self.assertIn("7. Citation Attributes", msg)
            self.assertIn("8. Fix Notes", msg)
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
            self.assertIn("8. Fix Notes:", report)
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


def format_analysis(stats: dict[str, Any]) -> str:
    """Format the collected stats as the report body."""
    get = stats.get
    lines: list[str] = []
    lines.append(
        str(
            (
                "Database totals: %d people, %d families, %d sources, "
                "%d repositories, %d citations, %d notes, %d media."
            )
            % (
                get("people", 0),
                get("families", 0),
                get("sources", 0),
                get("repositories", 0),
                get("citations", 0),
                get("notes", 0),
                get("media", 0),
            )
        )
    )
    lines.append("")
    lines.append(str(("Where it matches best practice")))
    lines.append(
        str(
            (
                "Most sources are collection-level with specifics in "
                "citations (the Evidence Explained 'split' approach). "
                "Orphan sources: %d."
            )
            % len(get("orphan_sources", []))
        )
    )
    lines.append("")
    lines.append(str(("Where it falls short")))
    lines.append(
        str(
            _("Sources without a repository: %d of %d.")
            % (len(get("sources_no_repo", [])), get("sources", 0))
        )
    )
    for row in get("repo_rows", []):
        lines.append(
            "- %s (%s)"
            % (row.get("name") or _("Unnamed repository"), row.get("gramps_id") or "?")
        )
    conflated = get("conflated_sources", [])
    lines.append("")
    lines.append(
        str(
            _(
                "Conflated Fields: %d sources contain mixed Repository/Source/Citation data."
            )
            % len(conflated)
        )
    )
    for row in conflated[:10]:
        lines.append(
            "  - %s: '%s'\n    ↳ Detected elements: %s"
            % (
                row.get("gramps_id"),
                row.get("title"),
                ", ".join(row.get("elements_detected", [])),
            )
        )
    lines.append("")
    lines.append(
        str(
            ("Citations with no Volume/Page: %d of %d.")
            % (get("citations_no_page", 0), get("citations", 0))
        )
    )
    if get("tree_citations"):
        lines.append(
            str(
                (
                    "FamilySearch Family Tree citations: %d, rated "
                    "confidence 3+: %d. A user-edited tree is "
                    "derivative/secondary, so lower the confidence."
                )
                % (get("tree_citations", 0), get("tree_conf_high", 0))
            )
        )
    lines.append(
        str(
            ("People with no directly-attached source: %d of %d.")
            % (get("people_unsourced", 0), get("people", 0))
        )
    )
    dupes = get("near_duplicates", [])
    lines.append(str(("Near-duplicate source groups: %d.") % len(dupes)))
    for group in dupes[:7]:
        joined = "; ".join(
            "%s '%s'" % (r.get("gramps_id"), r.get("title")) for r in group[:4]
        )
        lines.append("  - " + joined)
    for row in get("non_source_like", [])[:10]:
        lines.append(
            str(
                ("Not really a source: %s '%s' (%d citations).")
                % (row.get("gramps_id"), row.get("title"), row.get("citations"))
            )
        )
    for row in get("generic_sources", [])[:10]:
        lines.append(
            str(
                ("Generic source: %s '%s' by '%s'.")
                % (row.get("gramps_id"), row.get("title"), row.get("author"))
            )
        )
    lines.append(
        str(
            ("Notes that are bare URLs: %d of %d; unreferenced: %d; duplicated: %d.")
            % (
                get("notes_bare_url", 0),
                get("notes", 0),
                get("notes_unreferenced", 0),
                get("notes_duplicated", 0),
            )
        )
    )
    for row in get("notes_debris", [])[:10]:
        lines.append(
            str(
                ("Import debris note %s: %s")
                % (row.get("gramps_id"), row.get("preview"))
            )
        )
    for row in get("notes_long", [])[:5]:
        lines.append(
            str(
                ("Long narrative note %s (%d chars): %s...")
                % (row.get("gramps_id"), row.get("length"), row.get("preview"))
            )
        )
    lines.append(
        str(
            ("Media with absolute paths: %d of %d. Citations with images: %d.")
            % (
                get("media_absolute_count", 0),
                get("media", 0),
                get("citations_with_media", 0),
            )
        )
    )
    for base, count in list(get("media_dup_basenames", {}).items())[:5]:
        lines.append(str(("Media filename imported %dx: %s") % (count, base)))
    if get("custom_events_total"):
        lines.append(
            str(("Custom leftover events: %d.") % get("custom_events_total", 0))
        )
    lines.append("")
    lines.append(str(("Suggested order of fixes:")))
    lines.append(str(("1. Run Unpack and Split Conflated Source Fields.")))
    lines.append(str(("2. Merge the duplicate sources.")))
    lines.append(
        str(("3. Clean up the FamilySearch Tree source and lower the confidence."))
    )
    lines.append(
        str(("4. Add Ancestry and FamilySearch as repositories and link the sources."))
    )
    lines.append(str(("5. Delete the import-log notes.")))
    lines.append(
        str(_("6. Add page/entry details to census and death-record citations."))
    )
    lines.append("")
    return "\n".join(lines)


def parse_report_header(text: str) -> tuple[str, str]:
    """Split the first report line into (title, timestamp) parts."""
    first = text.splitlines() if text else ""
    chunks = first.rsplit(None, 2)
    if len(chunks) >= 3 and len(chunks[-2]) == 10 and len(chunks[-1]) == 8:
        timestamp = f"{chunks[-2]} {chunks[-1]}"
        title = first[: len(first) - len(timestamp)].rstrip()
        return (title, timestamp)
    return (first.strip(), "")


# ------------------------------------------------------------
#
#
# GWizardCitationFixProgressMeter
#
#
# ------------------------------------------------------------


class GWizardCitationFixProgressMeter(ProgressMeter):
    """Wait/hourglass progress dialog for the citation fix report flow."""


def init(self, parent: Any = None) -> None:
    """Initialize the meter in activity mode like the GWizard flow."""
    ProgressMeter.init(
        self,
        str(("Loading Citation Fix")),
        str(("Starting analysis...")),
        parent=parent,
    )
    self.set_pass(
        str(_("Starting analysis...")),
        mode=ProgressMeter.MODE_ACTIVITY,
    )


def show_stage(self, text: str) -> None:
    """Update the header text and pulse the meter for a stage."""
    self.set_header(text)
    self.step()


# ------------------------------------------------------------
#
#
# Fix layer specs
#
#
# ------------------------------------------------------------


def get_fix_layer_specs() -> list[tuple[str, str, str]]:
    """Return (layer, title, description) specs for the fix dialogs."""
    return [
        (
            "repositories",
            str(("Fix Repositories")),
            str(("Create missing repositories and link orphan sources.")),
        ),
        (
            "sources",
            str(("Fix Sources")),
            str(("Merge near-duplicates and quarantine non-sources.")),
        ),
        (
            "citations",
            str(("Fix Citations")),
            str(("Clean Tree PAGE/DATE and confidence.")),
        ),
        (
            "notes",
            str(("Fix Notes")),
            str(("Remove import debris and convert bare-URL notes.")),
        ),
    ]


def get_fix_layer_titles() -> dict[str, str]:
    """Return a mapping of layer key to dialog title."""
    return {layer: title for layer, title, _desc in get_fix_layer_specs()}


def get_fix_description(layer: str) -> str:
    """Return the description text for a fix layer."""
    for spec_layer, _title, desc in get_fix_layer_specs():
        if spec_layer == layer:
            return desc
    return layer


# ------------------------------------------------------------
#
#
# GWizardCitationFixOptions
#
#
# ------------------------------------------------------------


class GWizardCitationFixOptions(tool.ToolOptions):
    """Defines options and provides handling interface."""


def init(self, name: str, person_id: str | None = None) -> None:
    """Initialize the options."""
    tool.ToolOptions.init(self, name, person_id)
    self.options_dict = {}
    self.options_help = {}


# ------------------------------------------------------------
#
#
# GWizardCitationFix
#

# ------------------------------------------------------------


class GWizardCitationFix(tool.Tool, ManagedWindow):
    """Show the GWizard citation fix dialog."""

    def __init__(
        self,
        dbstate: Any,
        user: Any,
        options_class: Any,
        name: str,
        callback: Any = None,
    ) -> None:
        """Initialize the tool and open the modal dialog."""
        uistate = user.uistate
        tool.Tool.__init__(self, dbstate, options_class, name)
        ManagedWindow.__init__(self, uistate, [], self.__class__, modal=True)
        self.dbstate = dbstate
        self.report_path: str | None = None
        self.report_datetime: str | None = None
        self._build_window(uistate)
        self.update_view_button()
        self.show()


def build_window(self, uistate: Any) -> None:
    """Build the modal dialog layout."""
    dialog = Gtk.Dialog(
        title=str(("GWizard citation fix")),
        transient_for=uistate.window,
        modal=True,
        destroy_with_parent=True,
    )
    dialog.add_button(str(_("Close")), Gtk.ResponseType.CLOSE)
    dialog.connect("response", self.cb_close)
    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(6)
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    content.add(vbox)
    specs = get_button_specs()
    top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    top_row.set_homogeneous(True)
    vbox.pack_start(top_row, False, False, 0)
    self.buttons: dict[str, Gtk.Button] = {}
    for key, label, sensitive in specs[:2]:
        button = Gtk.Button(label=label)
    button.set_sensitive(sensitive)
    button.set_hexpand(True)
    button.connect("clicked", self.cb_button, key)
    top_row.pack_start(button, True, True, 0)
    self.buttons[key] = button
    for key, label, sensitive in specs[2:]:
        button = Gtk.Button(label=label)
    button.set_sensitive(sensitive)
    button.set_hexpand(True)
    button.connect("clicked", self.cb_button, key)
    vbox.pack_start(button, False, False, 0)
    self.buttons[key] = button
    self.set_window(dialog, None, str(("GWizard citation fix")))
    self.setup_configs("interface.gwizardcitationfix", 420, 260)
    dialog.show_all()


def build_menu_names(self, obj: Any) -> tuple[str, str]:
    """Return the menu labels for the managed window."""
    return (_("GWizard citation fix"), " ")


def cb_close(self, dialog: Gtk.Dialog, response: int) -> None:
    """Close the dialog."""
    self.close()


def cb_button(self, button: Gtk.Button, key: str) -> None:
    """Dispatch dialog button clicks."""
    if key == "generate":
        self.cb_generate_report()
    elif key == "view":
        self.cb_view_report()
    elif key == "consolidate_repositories":
        from gramps.plugins.tool.gw_repoconsolidatedialog import RepoConsolidateDialog

        RepoConsolidateDialog(self.dbstate, transient_for=self.window).run()
    elif key == "fix_repositories":
        self.cb_fix_layer("repositories")
    elif key == "fix_sources":
        self.cb_fix_layer("sources")
    elif key == "unpack_citations":
        self.cb_fix_layer("unpack_citations")
    elif key == "fix_citations":
        self.cb_fix_layer("citations")
    elif key == "citation_attributes":
        self.cb_fix_layer("citation_attributes")
    elif key == "fix_notes":
        self.cb_fix_layer("notes")
    elif key == "auto_all":
        self.cb_auto_all()
    else:
        LOG.debug("Unknown button pressed: %s", key)


def cb_fix_layer(self, layer: str) -> None:
    """Open the fix dialog for one GEDCOM layer."""
    titles = get_fix_layer_titles()
    title = titles.get(layer, layer)
    self.show_fix_dialog(layer, title)


def show_fix_dialog(self, layer: str, title: str) -> None:
    """Show a per-layer dialog with an Auto best-guess button."""
    if layer == "repositories":
        self.show_repo_merge_dialog()
        return
    if layer == "sources":
        self.show_source_fix_dialog()
        return
    if layer == "citations":
        self.show_citation_fix_dialog()
        return
    dialog = Gtk.Dialog(
        title=title,
        transient_for=self.window,
        modal=True,
        destroy_with_parent=True,
    )
    dialog.add_button(str(_("Close")), Gtk.ResponseType.CLOSE)
    dialog.connect("response", lambda dlg, resp: dlg.destroy())
    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(6)
    label = Gtk.Label(label=self.get_fix_description(layer))
    label.set_line_wrap(True)
    label.set_halign(Gtk.Align.START)
    content.add(label)
    auto_button = Gtk.Button(label=str(("Auto (best guess)")))
    auto_button.connect("clicked", self.cb_fix_auto, layer)
    content.add(auto_button)
    dialog.show_all()
    dialog.run()
    dialog.destroy()


def show_repo_merge_dialog(self) -> None:
    """Open the standalone merge-repositories dialog."""
    from gramps.plugins.tool.gw_repomergedialog import RepoMergeDialog

    titles = get_fix_layer_titles()
    dialog = RepoMergeDialog(
        title=titles.get("repositories", "repositories"),
        dbstate=self.dbstate,
        transient_for=self.window,
    )
    dialog.show_dialog()


def show_citation_fix_dialog(self) -> None:
    """Open the standalone citation-fix dialog."""
    from gramps.plugins.tool.gw_citationsfixdialog import CitationFixDialog

    title = get_fix_layer_titles().get("citations", "citations")
    dialog = CitationFixDialog(
        title=title,
        dbstate=self.dbstate,
        description=self.get_fix_description("citations"),
        transient_for=self.window,
    )
    dialog.show_dialog()


def show_source_fix_dialog(self) -> None:
    """Open the standalone source-record fix dialog."""
    from gramps.plugins.tool.gw_sourcesfixdialog import SourceFixDialog

    title = get_fix_layer_titles().get("sources", "sources")
    dialog = SourceFixDialog(
        title=title,
        dbstate=self.dbstate,
        description=self.get_fix_description("sources"),
        transient_for=self.window,
    )
    dialog.show_dialog()


def get_fix_description(self, layer: str) -> str:
    """Return the description text for a fix layer."""
    return get_fix_description(layer)


def cb_repo_auto(self) -> None:
    """Apply best-guess golden merges for all non-golden repositories."""
    from gramps.plugins.tool.gw_repomergedialog import RepoMergeDialog

    dialog = RepoMergeDialog(
        title="",
        dbstate=self.dbstate,
        transient_for=self.window,
    )
    dialog.run_auto(parent=self.window)
    dialog.destroy()


def cb_fix_auto(self, button: Gtk.Button, layer: str) -> None:
    """Run the best-guess auto fix for one layer (preview-first)."""
    if layer == "repositories":
        self.cb_repo_auto()
        return
    try:
        stats = collect_db_stats(self.dbstate.db)
    except Exception:  # pylint: disable=broad-except
        LOG.exception("Failed to analyze database for %s", layer)
    stats = None
    summary = self.summarize_auto_fix(layer, stats)
    OkDialog(
        str(_("Auto fix preview: %s") % layer),
        summary,
        parent=self.window,
    )


def summarize_auto_fix(self, layer: str, stats: dict[str, Any] | None) -> str:
    """Return a preview summary of what auto fix would do."""
    if not stats:
        return str(("No analysis available. Generate a report first."))
    if layer == "repositories":
        count = len(stats.get("sources_no_repo", []))
        return str(("Best guess would link %d sources to repositories.") % count)
    if layer == "sources":
        count = len(stats.get("near_duplicates", []))
        return str(("Best guess would merge %d duplicate groups.") % count)
    if layer == "citations":
        count = int(stats.get("tree_citations", 0))
        return str(("Best guess would clean %d FamilySearch Tree citations.") % count)
    if layer == "notes":
        count = len(stats.get("notes_debris", []))
        return str(("Best guess would remove %d debris notes.") % count)
    return str(("Unknown layer: %s") % layer)


def cb_auto_all(self) -> None:
    """Run best-guess auto fixes across all layers in order."""
    try:
        stats = collect_db_stats(self.dbstate.db)
    except Exception:  # pylint: disable=broad-except
        LOG.exception("Failed to analyze database for auto all")
    stats = None
    parts = [
        self.summarize_auto_fix(layer, stats) for layer, _t, d in get_fix_layer_specs()
    ]
    OkDialog(
        str(("Auto fix preview (all layers)")),
        "\n".join(parts),
        parent=self.window,
    )


def update_view_button(self) -> None:
    """Enable View report only when the report file exists."""
    button = self.buttons.get("view")
    if button is None:
        return
    path = self.report_path or get_report_path()
    button.set_sensitive(report_exists(path))


def _pump_events(self) -> None:
    """Let pending GTK events run so the meter stays responsive."""
    while Gtk.events_pending():
        Gtk.main_iteration()

    def cb_generate_report(self) -> None:
        """Generates the CitationFixReport.txt using the report engine class."""
        stages = get_report_stages()
        meter = GWizardCitationFixProgressMeter(parent=self.window)
        engine = GWizardCitationReport()  # Call the separate report module

        try:
            meter.show_stage(stages[0])
            stats = engine.collect_db_stats(self.dbstate.db)

            self.report_datetime = datetime.now().strftime("%Y-%m-%d %H:%M")
            report_body = engine.format_analysis(stats)

            # Simple wrapper to construct header lines
            text = (
                f"Citation analysis file\t\t\t{self.report_datetime}\n"
                + ("=" * 78)
                + "\n\n"
                + report_body
            )

            self.report_path = get_report_path()
            os.makedirs(os.path.dirname(self.report_path), exist_ok=True)
            with open(self.report_path, "w", encoding="utf-8") as handle:
                handle.write(text)

        except OSError as error:
            ErrorDialog(str(_("Report Failed")), str(error), parent=self.window)
            return
        finally:
            meter.close()

        if self.report_path:
            self.update_view_button()
            self.cb_view_report()


def cb_view_report(self) -> None:
    """Open the generated CitationFixReport.txt in a report window."""
    path = self.report_path or get_report_path()
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        OkDialog(
            str(("No report yet")),
            str(("Please choose Generate report first.")),
            parent=self.window,
        )
        return
    title, timestamp = parse_report_header(text)
    if not timestamp and self.report_datetime:
        timestamp = self.report_datetime
    dialog = Gtk.Dialog(
        title=str(("GWizard citation fix report")),
        transient_for=self.window,
        modal=True,
        destroy_with_parent=True,
    )
    dialog.add_button(str(("_Close")), Gtk.ResponseType.CLOSE)
    dialog.connect("response", lambda dlg, resp: dlg.destroy())
    content = dialog.get_content_area()
    content.set_border_width(12)
    content.set_spacing(6)
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    title_label = Gtk.Label()
    title_label.set_markup("%s" % title)
    title_label.set_halign(Gtk.Align.START)
    title_label.set_hexpand(True)
    header.pack_start(title_label, True, True, 0)
    date_label = Gtk.Label()
    date_label.set_markup("%s" % timestamp)
    date_label.set_halign(Gtk.Align.END)
    header.pack_start(date_label, False, False, 0)
    content.add(header)
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_min_content_height(300)
    scrolled.set_min_content_width(1080)
    textview = Gtk.TextView()
    textview.set_editable(False)
    textview.set_wrap_mode(Gtk.WrapMode.WORD)
    textview.set_vexpand(True)
    textview.set_hexpand(True)
    textview.get_buffer().set_text(text)
    scrolled.add(textview)
    content.pack_start(scrolled, True, True, 0)
    scrolled.set_vexpand(True)
    dialog.show_all()
    dialog.run()
    dialog.destroy()
