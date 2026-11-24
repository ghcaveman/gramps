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

    def connect(self, signal: str, handler: Any) -> None:
        self.handlers[signal] = handler

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
    gtk.Entry.side_effect = lambda *a, **k: MagicMock(**{"get_text.return_value": ""})
    gtk.Label.side_effect = lambda *a, **k: MagicMock()
    gtk.Button.side_effect = lambda *a, **k: MagicMock(
        get_style_context=lambda: MagicMock()
    )
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

    def test_merge_familysearch_person_invalid_id(self):
        applied, msg = merge_familysearch_person(None, "", None)
        self.assertFalse(applied)
        self.assertIn("valid", msg.lower())

    def test_run_gwizard_familysearch_flow(self):
        mock_uistate = MagicMock()
        mock_uistate.get_active.return_value = "handle_123"
        mock_dbstate = MagicMock()

        success = run_gwizard_familysearch_flow(mock_uistate, mock_dbstate)
        self.assertTrue(success)


if __name__ == "__main__":
    unittest.main()
