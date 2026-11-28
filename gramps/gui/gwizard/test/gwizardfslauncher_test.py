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
Unit tests for the GWizard FamilySearch launcher and search dialog.
"""

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
import types
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# Test environment setup
#
# -------------------------------------------------------------------------
ROOT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)


def _ensure_test_resources():
    resource_path = os.environ.get("GRAMPS_RESOURCES")
    if resource_path and os.path.exists(
        os.path.join(resource_path, "gramps", "authors.xml")
    ):
        return resource_path

    build_share = os.path.join(ROOT_DIR, "build", "share")
    if os.path.exists(os.path.join(build_share, "gramps", "authors.xml")):
        return build_share

    resource_path = tempfile.mkdtemp(prefix="gramps-resources-")
    os.makedirs(os.path.join(resource_path, "gramps", "images"), exist_ok=True)
    os.makedirs(os.path.join(resource_path, "doc", "gramps"), exist_ok=True)
    os.makedirs(os.path.join(resource_path, "locale"), exist_ok=True)

    shutil.copyfile(
        os.path.join(ROOT_DIR, "data", "authors.xml"),
        os.path.join(resource_path, "gramps", "authors.xml"),
    )
    return resource_path


os.environ["GRAMPS_RESOURCES"] = _ensure_test_resources()
os.environ["HOME"] = os.environ.get("HOME") or tempfile.mkdtemp(prefix="gramps-home-")


# -------------------------------------------------------------------------
#
# GTK stubbing for headless or non-GTK test environments
#
# -------------------------------------------------------------------------
class DummyDialog:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._content_area = MagicMock()
        self._action_area = MagicMock()
        self.default_size: tuple[int, int] | None = None
        self.resizable: bool | None = None
        self.buttons: dict[int, Any] = {}
        self.handlers: dict[str, Any] = {}
        self.destroyed = False
        self.stopped_signal: str | None = None

    def connect(self, signal: str, handler: Any) -> None:
        self.handlers[signal] = handler

    def stop_emission_by_name(self, signal: str) -> None:
        self.stopped_signal = signal

    def get_content_area(self) -> Any:
        return self._content_area

    def get_action_area(self) -> Any:
        return self._action_area

    def set_default_size(self, w: int, h: int) -> None:
        self.default_size = (w, h)

    def set_resizable(self, r: bool) -> None:
        self.resizable = r

    def add_button(self, text: str, response: int) -> Any:
        button = MagicMock()
        button.label = text
        button.get_style_context.return_value = MagicMock()
        self.buttons[response] = button
        return button

    def show_all(self) -> None:
        pass

    def run(self) -> int:
        return 1

    def destroy(self) -> None:
        self.destroyed = True


def _gtk_stub_modules() -> dict[str, Any]:
    gi = MagicMock()
    gi_repo = MagicMock()

    glib = MagicMock()
    glib.markup_escape_text = lambda s: str(s)

    gtk = MagicMock()
    gtk.Dialog = DummyDialog

    def _check_button(*_args: Any, **_kwargs: Any) -> Any:
        button = MagicMock()
        active = {"value": False}
        button.get_active.side_effect = lambda: active["value"]
        button.set_active.side_effect = lambda value: active.__setitem__("value", value)
        return button

    gtk.Entry.side_effect = lambda *a, **k: MagicMock(**{"get_text.return_value": ""})
    gtk.Label.side_effect = lambda *a, **k: MagicMock()
    gtk.Button.side_effect = lambda *a, **k: MagicMock(
        get_style_context=lambda: MagicMock()
    )
    gtk.CheckButton.side_effect = _check_button
    gtk.Box.side_effect = lambda *a, **k: MagicMock()
    gtk.Grid.side_effect = lambda *a, **k: MagicMock()
    gtk.TreeView.side_effect = lambda *a, **k: MagicMock()
    gtk.ScrolledWindow.side_effect = lambda *a, **k: MagicMock()
    gtk.ListStore.side_effect = lambda *a, **k: MagicMock()
    gtk.CellRendererText.side_effect = lambda *a, **k: MagicMock()
    gtk.TreeViewColumn.side_effect = lambda *a, **k: MagicMock()
    gtk.ResponseType.OK = 1
    gtk.ResponseType.CANCEL = 2
    gtk.ResponseType.CLOSE = 3
    gtk.ResponseType.APPLY = 5
    gtk.SelectionMode.SINGLE = 1
    gtk.PolicyType.AUTOMATIC = 1
    gtk.Orientation.HORIZONTAL = 0
    gtk.Orientation.VERTICAL = 1
    gtk.events_pending.return_value = False

    gi.repository = gi_repo
    gi_repo.GLib = glib
    gi_repo.Gtk = gtk
    return {
        "gi": gi,
        "gi.repository": gi_repo,
        "gi.repository.GLib": glib,
        "gi.repository.Gtk": gtk,
        # gramps.gui.fs.manager imports grampsgui, whose pygobject check
        # fails against these stubs and calls sys.exit(), ending the whole
        # test run. Marking it unavailable sends manager down its existing
        # no-GUI path instead.
        "gramps.gui.grampsgui": None,
    }


def _uses_gtk(name: str) -> bool:
    if ".test." in name or name.endswith(".test"):
        return False
    return (
        name in ("gi", "gramps.gui")
        or name.startswith("gi.")
        or name.startswith("gramps.gui.")
    )


_SAVED_MODULES: dict[str, Any] = {}

_extract_person_search_defaults: Any = None
FamilySearchSearchDialog: Any = None
merge_familysearch_person: Any = None
run_gwizard_familysearch_flow: Any = None
FamilySearchMergeDialog: Any = None


def setUpModule() -> None:
    global _extract_person_search_defaults, FamilySearchSearchDialog
    global merge_familysearch_person, run_gwizard_familysearch_flow
    global FamilySearchMergeDialog

    _SAVED_MODULES.clear()
    _SAVED_MODULES.update(sys.modules)
    for name in [name for name in sys.modules if _uses_gtk(name)]:
        del sys.modules[name]
    sys.modules.update(_gtk_stub_modules())

    import gramps.gui.gwizard.gwizardfslauncher as launcher
    import gramps.gui.gwizard.gwizardfsmergedialog as mergedialog

    _extract_person_search_defaults = launcher._extract_person_search_defaults
    FamilySearchSearchDialog = launcher.FamilySearchSearchDialog
    merge_familysearch_person = launcher.merge_familysearch_person
    run_gwizard_familysearch_flow = launcher.run_gwizard_familysearch_flow
    FamilySearchMergeDialog = mergedialog.FamilySearchMergeDialog


def tearDownModule() -> None:
    for name in [name for name in sys.modules if _uses_gtk(name)]:
        del sys.modules[name]
    sys.modules.update(_SAVED_MODULES)


# ------------------------------------------------------------
#
# TestFamilySearchLauncher
#
# ------------------------------------------------------------
class TestFamilySearchLauncher(unittest.TestCase):
    """
    Tests for person search defaults, search dialog, and merge launcher.
    """

    def test_extract_person_search_defaults_empty(self):
        defaults = _extract_person_search_defaults(None, None)
        self.assertEqual(defaults["first_name"], "")
        self.assertEqual(defaults["last_name"], "")
        self.assertEqual(defaults["fs_id"], "")

    def test_extract_person_search_defaults_populated(self):
        from gramps.gen.lib import Attribute, Event, EventRef, EventType, Name, Person

        p = Person()
        name = Name()
        name.set_first_name("Abraham")
        name.get_primary_surname().set_surname("Lincoln")
        p.set_primary_name(name)

        attr = Attribute()
        attr.set_type("_FSFTID")
        attr.set_value("GSVF-SGV")
        p.add_attribute(attr)

        mock_db = MagicMock()
        defaults = _extract_person_search_defaults(mock_db, p)
        self.assertEqual(defaults["first_name"], "Abraham")
        self.assertEqual(defaults["last_name"], "Lincoln")
        self.assertEqual(defaults["fs_id"], "GSVF-SGV")

    def test_search_dialog_init_and_search(self):
        mock_client = MagicMock()
        mock_client.search_person.return_value = [
            {"fsid": "GSVF-SGV", "name": "Abraham Lincoln", "life": "1809-1865"}
        ]

        dlg = FamilySearchSearchDialog(
            uistate=MagicMock(),
            dbstate=MagicMock(),
            target_handle="dummy_handle",
            client=mock_client,
        )
        self.assertIsNotNone(dlg)

        # Trigger search
        dlg.fs_id_entry.get_text.return_value = "GSVF-SGV"
        dlg.cb_search()
        self.assertIn("1", dlg.status_label.set_text.call_args[0][0])

    def test_search_by_id_shows_profile_and_keeps_dialog_open(self):
        mock_client = MagicMock()
        mock_client.search_person.return_value = [
            {"fsid": "GSVF-SGV", "name": "Abraham Lincoln", "life": "1809-1865"}
        ]
        dlg = FamilySearchSearchDialog(client=mock_client)
        dlg.fs_id_entry.get_text.return_value = "GSVF-SGV"

        dlg.cb_search()

        mock_client.search_person.assert_called_once_with(query="GSVF-SGV")
        dlg.store.append.assert_called_once_with(
            [
                "GSVF-SGV",
                "Abraham Lincoln",
                "",
                "",
                "",
                "",
                "",
                "100% (FamilySearch ID)",
                101.0,
            ]
        )
        self.assertEqual(len(dlg.buttons), 2)
        dlg.merge_button.set_sensitive.assert_any_call(False)

    def test_search_by_name_still_runs_with_prefilled_id(self):
        mock_client = MagicMock()
        mock_client.search_person.side_effect = [
            [{"fsid": "HENR-SCH", "name": "Henry Schmidt", "life": "1900-1980"}],
            [{"fsid": "GSVF-SGV", "name": "Abraham Lincoln", "life": "1809-1865"}],
        ]
        dlg = FamilySearchSearchDialog(client=mock_client)
        dlg.fs_id_entry.get_text.return_value = "GSVF-SGV"
        dlg.given_name_entry.get_text.return_value = "Henry"
        dlg.surname_entry.get_text.return_value = "Schmidt"
        dlg.birth_year_entry.get_text.return_value = "1900"

        dlg.cb_search()

        self.assertEqual(mock_client.search_person.call_count, 2)
        mock_client.search_person.assert_any_call(
            first_name="Henry",
            last_name="Schmidt",
            birth_date="1900",
            death_date="",
            gender="",
            birth_place="",
            death_place="",
            limit=25,
        )
        mock_client.search_person.assert_any_call(query="GSVF-SGV")
        rows = [call.args[0] for call in dlg.store.append.call_args_list]
        # The profile looked up by ID comes first, then the name results.
        self.assertEqual([row[0] for row in rows], ["GSVF-SGV", "HENR-SCH"])
        self.assertEqual(rows[0][7:], ["100% (FamilySearch ID)", 101.0])
        self.assertEqual(rows[1][:7], ["HENR-SCH", "Henry Schmidt", "", "", "", "", ""])

    def _henry_dialog(self, client: Any) -> Any:
        """Return a search dialog filled in for a Henry Schmidt born 1890."""
        dlg = FamilySearchSearchDialog(client=client)
        dlg.fs_id_entry.get_text.return_value = "G7LC-JRT"
        dlg.given_name_entry.get_text.return_value = "Henry"
        dlg.surname_entry.get_text.return_value = "Schmidt"
        dlg.birth_year_entry.get_text.return_value = "1890"
        dlg.term_entries["gender"].get_text.return_value = "Male"
        return dlg

    def test_results_are_listed_best_match_first(self):
        mock_client = MagicMock()
        mock_client.search_person.side_effect = [
            [
                {
                    "fsid": "AAAA-001",
                    "name": "Henry Schmidt",
                    "gender": "Female",
                    "birth_date": "11 March 1890",
                },
                {
                    "fsid": "AAAA-002",
                    "name": "Henry Schmidt",
                    "gender": "Male",
                    "birth_date": "1894",
                },
                {
                    "fsid": "AAAA-003",
                    "name": "Henry Schmidt",
                    "gender": "Male",
                    "birth_date": "2 May 1890",
                },
                {
                    "fsid": "AAAA-004",
                    "name": "Martin Henry Schmidt",
                    "gender": "Male",
                    "birth_date": "1890",
                },
            ],
            [
                {
                    "fsid": "G7LC-JRT",
                    "name": "Henry Schmidt",
                    "gender": "Male",
                    "life": "1890-1966",
                }
            ],
        ]
        dlg = self._henry_dialog(mock_client)

        dlg.cb_search()

        rows = [call.args[0] for call in dlg.store.append.call_args_list]
        self.assertEqual(
            [row[0] for row in rows],
            ["G7LC-JRT", "AAAA-003", "AAAA-004", "AAAA-002", "AAAA-001"],
        )
        self.assertEqual(rows[0][7], "100% (FamilySearch ID)")
        self.assertEqual(rows[1][7:], ["100%", 100.0])
        scores = [row[8] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertIn("best match first", dlg.status_label.set_text.call_args[0][0])

    def test_id_profile_found_by_name_is_still_first(self):
        mock_client = MagicMock()
        mock_client.search_person.side_effect = [
            [
                {"fsid": "AAAA-003", "name": "Henry Schmidt", "birth_date": "1890"},
                {"fsid": "G7LC-JRT", "name": "Hank Smith", "birth_date": "1850"},
            ],
            [{"fsid": "G7LC-JRT", "name": "Hank Smith", "birth_date": "1850"}],
        ]
        dlg = self._henry_dialog(mock_client)

        dlg.cb_search()

        rows = [call.args[0] for call in dlg.store.append.call_args_list]
        self.assertEqual([row[0] for row in rows], ["G7LC-JRT", "AAAA-003"])
        self.assertEqual(rows[0][7], "100% (FamilySearch ID)")

    def test_match_column_sorts_by_score(self):
        from gi.repository import Gtk

        Gtk.TreeViewColumn.reset_mock()
        dlg = FamilySearchSearchDialog(client=MagicMock())
        titles = [call.args[0] for call in Gtk.TreeViewColumn.call_args_list]
        self.assertEqual(titles[2], "Match")
        columns = [call.args[0] for call in dlg.tree_view.append_column.call_args_list]
        columns[2].set_sort_column_id.assert_called_once_with(8)

    def test_gender_is_searched_by_default(self):
        dlg = FamilySearchSearchDialog(client=MagicMock())
        self.assertTrue(dlg.term_checks["gender"].get_active())

    def test_middle_name_is_included_only_when_checked(self):
        mock_client = MagicMock()
        dlg = FamilySearchSearchDialog(client=mock_client)
        dlg.fs_id_entry.get_text.return_value = ""
        dlg.given_name_entry.get_text.return_value = "Henry"
        dlg.middle_name_entry.get_text.return_value = "James"
        dlg.surname_entry.get_text.return_value = "Schmidt"
        dlg.birth_year_entry.get_text.return_value = ""

        dlg.cb_search()

        mock_client.search_person.assert_called_once_with(
            first_name="Henry",
            last_name="Schmidt",
            birth_date="",
            death_date="",
            gender="",
            birth_place="",
            death_place="",
            limit=25,
        )
        mock_client.reset_mock()
        dlg.term_checks["middle_name"].set_active(True)
        dlg.cb_search()
        mock_client.search_person.assert_called_once_with(
            first_name="Henry James",
            last_name="Schmidt",
            birth_date="",
            death_date="",
            gender="",
            birth_place="",
            death_place="",
            limit=25,
        )

    def test_place_only_search_is_sent_to_familysearch(self):
        mock_client = MagicMock()
        dlg = FamilySearchSearchDialog(client=mock_client)
        dlg.fs_id_entry.get_text.return_value = ""
        dlg.term_checks["death_place"].set_active(True)
        dlg.term_entries["death_place"].get_text.return_value = "Boston"

        dlg.cb_search()

        mock_client.search_person.assert_called_once_with(
            first_name="",
            last_name="",
            birth_date="",
            death_date="",
            gender="",
            birth_place="",
            death_place="Boston",
            limit=25,
        )

    def test_search_requires_familysearch_login(self):
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = False
        dlg = FamilySearchSearchDialog(client=mock_client)
        dlg.fs_id_entry.get_text.return_value = ""
        dlg.surname_entry.get_text.return_value = "Schmidt"

        with patch("gramps.gui.gwizard.gwizardfslauncher.ErrorDialog") as error_dialog:
            dlg.cb_search()

        error_dialog.assert_called_once()
        self.assertIn("Authentication Failed", error_dialog.call_args.args[0])
        self.assertIn("Failed authentication", error_dialog.call_args.args[1])
        self.assertIn("Family Trees", error_dialog.call_args.args[1])
        self.assertIn("FamilySearch Sign in...", error_dialog.call_args.args[1])
        mock_client.search_person.assert_not_called()

    def test_api_authentication_failure_shows_popup(self):
        from gramps.gen.gwizard.gwizardfamilysearch import (
            FamilySearchAuthenticationError,
        )

        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.search_person.side_effect = FamilySearchAuthenticationError(
            "Failed authentication with FamilySearch."
        )
        dlg = FamilySearchSearchDialog(client=mock_client)
        dlg.fs_id_entry.get_text.return_value = ""
        dlg.surname_entry.get_text.return_value = "Schmidt"

        with patch("gramps.gui.gwizard.gwizardfslauncher.ErrorDialog") as error_dialog:
            dlg.cb_search()

        error_dialog.assert_called_once()
        self.assertIn("Authentication Failed", error_dialog.call_args.args[0])
        self.assertIn("Failed authentication", error_dialog.call_args.args[1])
        dlg.search_button.set_sensitive.assert_called_with(True)

    def test_compare_without_selection_keeps_dialog_open(self):
        dlg = FamilySearchSearchDialog()
        dlg.tree_view.get_selection.return_value.get_selected.return_value = (
            dlg.store,
            None,
        )

        dlg.cb_merge()

        self.assertIn(
            "select",
            dlg.status_label.set_text.call_args[0][0].lower(),
        )

    def test_compare_response_is_intercepted(self):
        dlg = FamilySearchSearchDialog()
        with patch.object(dlg, "cb_merge") as merge:
            dlg.cb_response(dlg, 1)

        self.assertEqual(dlg.stopped_signal, "response")
        merge.assert_called_once_with()

    def test_merge_familysearch_person_invalid_id(self):
        applied, msg = merge_familysearch_person(None, "", None)
        self.assertFalse(applied)
        self.assertIn("valid", msg.lower())

    def test_run_gwizard_familysearch_flow(self):
        mock_uistate = MagicMock()
        mock_uistate.get_active.return_value = "handle_123"
        mock_dbstate = MagicMock()

        with patch(
            "gramps.gui.gwizard.gwizardfslauncher.FamilySearchSearchDialog"
        ) as dialog_class:
            success = run_gwizard_familysearch_flow(mock_uistate, mock_dbstate)

        self.assertTrue(success)
        dialog = dialog_class.return_value
        dialog.show_all.assert_called_once_with()
        dialog.run.assert_called_once_with()
        dialog.destroy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
