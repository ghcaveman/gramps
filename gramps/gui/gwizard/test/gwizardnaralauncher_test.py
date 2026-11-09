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
Unit tests for the GWizard NARA launcher and search dialog.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch
from typing import Any


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
        self.title: str = ""
        self.border_width: int = 0

    def get_content_area(self) -> Any:
        return self._content_area

    def get_action_area(self) -> Any:
        return self._action_area

    def set_default_size(self, w: int, h: int) -> None:
        self.default_size = (w, h)

    def set_resizable(self, r: bool) -> None:
        self.resizable = r

    def set_title(self, title: str) -> None:
        self.title = title

    def set_border_width(self, width: int) -> None:
        self.border_width = width

    def add_button(self, text: str, response: int) -> Any:
        return MagicMock()

    def show_all(self) -> None:
        pass


_gi = sys.modules.get("gi") or MagicMock()
sys.modules["gi"] = _gi

_gi_repo = sys.modules.get("gi.repository") or MagicMock()
sys.modules["gi.repository"] = _gi_repo

_glib = sys.modules.get("gi.repository.GLib") or MagicMock()
_glib.markup_escape_text = lambda s: str(s)
sys.modules["gi.repository.GLib"] = _glib
_gi_repo.GLib = _glib

_gtk = sys.modules.get("gi.repository.Gtk") or MagicMock()
_gtk.Dialog = DummyDialog
_gtk.Entry.side_effect = lambda *a, **k: MagicMock()
_gtk.Label.side_effect = lambda *a, **k: MagicMock()
_gtk.Button.side_effect = lambda *a, **k: MagicMock()
_gtk.Box.side_effect = lambda *a, **k: MagicMock()
_gtk.Grid.side_effect = lambda *a, **k: MagicMock()
_gtk.TreeView.side_effect = lambda *a, **k: MagicMock()
_gtk.ScrolledWindow.side_effect = lambda *a, **k: MagicMock()
_gtk.ListStore.side_effect = lambda *a, **k: MagicMock()
_gtk.ComboBoxText.side_effect = lambda *a, **k: MagicMock()
_gtk.CheckButton.side_effect = lambda *a, **k: MagicMock()
_gtk.SpinButton.side_effect = lambda *a, **k: MagicMock()
_gtk.Adjustment.side_effect = lambda *a, **k: MagicMock()
_gtk.MessageDialog.side_effect = lambda *a, **k: MagicMock()
_gtk.ResponseType.OK = 1
_gtk.ResponseType.CANCEL = 2
_gtk.ResponseType.CLOSE = 3
_gtk.ResponseType.HELP = 4
_gtk.ResponseType.APPLY = 5
_gtk.ButtonsType.OK = 1
_gtk.MessageType.INFO = 1
_gtk.SelectionMode.SINGLE = 1
_gtk.PolicyType.AUTOMATIC = 1
_gtk.Orientation.HORIZONTAL = 0
_gtk.events_pending.return_value = False
sys.modules["gi.repository.Gtk"] = _gtk
_gi_repo.Gtk = _gtk

_gdk = sys.modules.get("gi.repository.Gdk") or MagicMock()
sys.modules["gi.repository.Gdk"] = _gdk
_gi_repo.Gdk = _gdk

_pango = sys.modules.get("gi.repository.Pango") or MagicMock()
sys.modules["gi.repository.Pango"] = _pango
_gi_repo.Pango = _pango

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.utils import make_database
from gramps.gen.db.txn import DbTxn
from gramps.gen.lib import (
    Date,
    Event,
    EventRef,
    EventType,
    Name,
    Person,
    Surname,
)
from gramps.gui.gwizard.gwizardnaralauncher import (
    _extract_person_search_defaults,
    NaraSearchDialog,
    ask_nara_parameters,
    load_nara_gwizard,
    run_gwizard_nara_flow,
)


# ------------------------------------------------------------
#
# TestNaraLauncher
#
# ------------------------------------------------------------
class TestNaraLauncher(unittest.TestCase):
    """Test suite for NARA search dialog and launcher utilities."""

    def setUp(self) -> None:
        """Create an in-memory database."""
        self.db = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        """Close the test database."""
        self.db.close()

    def test_extract_person_search_defaults_full(self) -> None:
        """Test defaults extraction with name and dates."""
        person = Person()
        pname = Name()
        pname.set_first_name("Abraham")
        surn = Surname()
        surn.set_surname("Lincoln")
        pname.add_surname(surn)
        person.set_primary_name(pname)

        with DbTxn("Add defaults test", self.db) as trans:
            # Birth
            b_evt = Event()
            b_evt.set_type(EventType(EventType.BIRTH))
            b_date = Date(1809, 2, 12)
            b_evt.set_date_object(b_date)
            b_h = self.db.add_event(b_evt, trans)
            b_ref = EventRef()
            b_ref.ref = b_h
            person.set_birth_ref(b_ref)

            # Death
            d_evt = Event()
            d_evt.set_type(EventType(EventType.DEATH))
            d_date = Date(1865, 4, 15)
            d_evt.set_date_object(d_date)
            d_h = self.db.add_event(d_evt, trans)
            d_ref = EventRef()
            d_ref.ref = d_h
            person.set_death_ref(d_ref)

            p_h = self.db.add_person(person, trans)

        saved_person = self.db.get_person_from_handle(p_h)
        defaults = _extract_person_search_defaults(self.db, saved_person)
        self.assertEqual(defaults["first_name"], "Abraham")
        self.assertEqual(defaults["last_name"], "Lincoln")
        self.assertEqual(defaults["query"], "Abraham Lincoln")
        self.assertEqual(defaults["birth_year"], "1809")
        self.assertEqual(defaults["death_year"], "1865")

    def test_extract_person_search_defaults_empty(self) -> None:
        """Test defaults extraction with None or empty person."""
        self.assertEqual(
            _extract_person_search_defaults(self.db, None),
            {
                "first_name": "",
                "last_name": "",
                "query": "",
                "birth_year": "",
                "death_year": "",
            },
        )

    def test_dialog_init_and_prefill(self) -> None:
        """Test NaraSearchDialog layout initialization and pre-filled fields."""
        person = Person()
        pname = Name()
        pname.set_first_name("George")
        surn = Surname()
        surn.set_surname("Washington")
        pname.add_surname(surn)
        person.set_primary_name(pname)

        with DbTxn("Add target", self.db) as trans:
            p_h = self.db.add_person(person, trans)

        dbstate = Mock()
        dbstate.db = self.db
        uistate = Mock()

        mock_client = Mock()
        dialog = NaraSearchDialog(
            uistate=uistate,
            dbstate=dbstate,
            target_handle=p_h,
            client=mock_client,
        )

        self.assertEqual(dialog.default_size, (950, 600))
        self.assertTrue(dialog.resizable)
        dialog.query_entry.set_text.assert_called_with("George Washington")

    def test_dialog_search_no_matches_keeps_open(self) -> None:
        """Verify that a search with no matches does not close the dialog and informs the user."""
        mock_client = Mock()
        mock_client.search_records.return_value = {"body": {"hits": {"hits": []}}}
        mock_client.extract_hits.return_value = []

        dialog = NaraSearchDialog(client=mock_client)
        dialog.query_entry.get_text.return_value = "NonexistentRecord123"
        dialog.key_entry.get_text.return_value = ""
        dialog.limit_spin.get_value.return_value = 25
        dialog.material_combo.get_active_id.return_value = None
        dialog.online_check.get_active.return_value = False

        dialog.cb_search()

        mock_client.search_records.assert_called_once()
        self.assertIn(
            "No matching records found", dialog.status_label.set_text.call_args[0][0]
        )
        dialog.btn_merge.set_sensitive.assert_called_with(False)

    def test_dialog_search_with_matches(self) -> None:
        """Verify that search results populate the results store table."""
        mock_client = Mock()
        mock_hit = {
            "_id": "55555",
            "_source": {
                "naId": "55555",
                "record": {
                    "title": "Abraham Lincoln Commission",
                    "authors": {
                        "creator": [{"heading": "Lincoln, Abraham, 1809-1865"}]
                    },
                    "typeOfMaterials": "textual records",
                    "dates": [{"startDate": "1861"}],
                    "digitalObjects": [{"objectUrl": "https://example.com/doc.jpg"}],
                },
            },
        }
        mock_client.search_records.return_value = {"hits": [mock_hit]}
        mock_client.extract_hits.return_value = [mock_hit]

        dialog = NaraSearchDialog(client=mock_client)
        dialog.query_entry.get_text.return_value = "Abraham Lincoln"
        dialog.key_entry.get_text.return_value = "custom_key"
        dialog.limit_spin.get_value.return_value = 10
        dialog.material_combo.get_active_id.return_value = "textual records"
        dialog.online_check.get_active.return_value = True

        dialog.cb_search()

        mock_client.search_records.assert_called_once_with(
            query="Abraham Lincoln",
            rows=10,
            material_type="textual records",
            available_online=True,
        )
        dialog.results_store.append.assert_called_once()
        appended_row = dialog.results_store.append.call_args[0][0]
        self.assertEqual(appended_row[0], "55555")
        self.assertEqual(appended_row[1], "Abraham Lincoln Commission")
        self.assertEqual(appended_row[2], "Lincoln, Abraham, 1809-1865")
        self.assertEqual(appended_row[3], "1861")
        self.assertEqual(appended_row[4], "textual records")
        self.assertIn("Yes", appended_row[5])

        dialog.btn_merge.set_sensitive.assert_called_with(True)
        self.assertIn("Found 1 matching", dialog.status_label.set_text.call_args[0][0])

    def test_dialog_merge_launches_merge_dialog(self) -> None:
        """Verify that cb_merge connects to NaraGWizard and launches GWizardMergeDialog."""
        mock_client = Mock()
        mock_hit = {
            "_id": "55555",
            "_source": {
                "naId": "55555",
                "record": {
                    "title": "Abraham Lincoln Commission",
                    "authors": {
                        "creator": [{"heading": "Lincoln, Abraham, 1809-1865"}]
                    },
                },
            },
        }

        dbstate = Mock()
        dbstate.db = self.db

        dialog = NaraSearchDialog(dbstate=dbstate, client=mock_client)

        mock_iter = Mock()
        dialog.tree_view.get_selection().get_selected.return_value = (
            dialog.results_store,
            mock_iter,
        )

        # Model returns naid at 0, hit at 6
        def get_val(_it, col):
            if col == 0:
                return "55555"
            if col == 6:
                return mock_hit
            return ""

        dialog.results_store.get_value.side_effect = get_val

        # Create dummy source_db with a person
        source_db = make_database("sqlite")
        source_db.load(":memory:")
        s_person = Person()
        pname = Name()
        pname.set_first_name("Abraham")
        surn = Surname()
        surn.set_surname("Lincoln")
        pname.add_surname(surn)
        s_person.set_primary_name(pname)
        with DbTxn("Add source person", source_db) as trans:
            source_db.add_person(s_person, trans)

        def fake_run_step(self_gw, step, **kwargs):
            if step == "connect":
                return True
            if step == "load":
                self_gw.context["source_db"] = source_db
                return [s_person]
            return True

        with (
            patch(
                "gramps.gen.gwizard.gwizardnaramerge.NaraGWizard.run_step",
                autospec=True,
                side_effect=fake_run_step,
            ),
            patch(
                "gramps.gui.gwizard.gwizardmergedialog.GWizardMergeDialog"
            ) as mock_merge_cls,
        ):
            mock_merge_instance = Mock()
            mock_merge_instance.run.return_value = 1  # Gtk.ResponseType.OK
            mock_merge_cls.return_value = mock_merge_instance

            dialog.cb_merge()

            mock_merge_instance.run.assert_called_once()
            mock_merge_instance.destroy.assert_called_once()
        source_db.close()

    def test_ask_nara_parameters_compatibility(self) -> None:
        """Verify ask_nara_parameters compatibility helper."""
        from gi.repository import Gtk

        with patch(
            "gramps.gui.gwizard.gwizardnaralauncher.NaraSearchDialog"
        ) as mock_cls:
            mock_dialog = Mock()
            mock_dialog.run.return_value = Gtk.ResponseType.OK
            mock_dialog.get_query_parameters.return_value = {
                "query": "Lincoln",
                "api_key": "",
                "limit": 25,
            }
            mock_cls.return_value = mock_dialog

            params = ask_nara_parameters(parent=None, default_query="Lincoln")
            self.assertEqual(params, {"query": "Lincoln", "api_key": "", "limit": 25})
            mock_dialog.destroy.assert_called_once()

    def test_run_gwizard_nara_flow(self) -> None:
        """Verify run_gwizard_nara_flow launches the dialog."""
        uistate = Mock()
        uistate.get_active.return_value = "handle_123"
        dbstate = Mock()

        with patch(
            "gramps.gui.gwizard.gwizardnaralauncher.NaraSearchDialog"
        ) as mock_cls:
            mock_dialog = Mock()
            mock_cls.return_value = mock_dialog

            result = run_gwizard_nara_flow(uistate, dbstate)
            self.assertTrue(result)
            mock_dialog.run.assert_called_once()
            mock_dialog.destroy.assert_called_once()

    def test_help_dialog(self) -> None:
        """Verify cb_help displays info dialog."""
        dialog = NaraSearchDialog()
        with patch("gi.repository.Gtk.MessageDialog") as mock_msg_cls:
            mock_msg = Mock()
            mock_msg_cls.return_value = mock_msg
            dialog.cb_help()
            mock_msg.run.assert_called_once()
            mock_msg.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
