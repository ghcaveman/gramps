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
Unit tests for the GWizard WikiTree launcher and search dialog.
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
_gtk.ResponseType.OK = 1
_gtk.ResponseType.CANCEL = 2
_gtk.ResponseType.CLOSE = 3
_gtk.ResponseType.HELP = 4
_gtk.ResponseType.APPLY = 5
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
    Attribute,
    AttributeType,
    Date,
    Event,
    EventRef,
    EventType,
    Name,
    Person,
    Surname,
    Url,
    UrlType,
)
from gramps.gui.gwizard.gwizardwikitreelauncher import (
    _extract_person_search_defaults,
    WikiTreeSearchDialog,
    ask_wikitree_parameters,
    load_wikitree_gwizard,
    run_gwizard_wikitree_flow,
)


# ------------------------------------------------------------
#
# TestWikiTreeLauncher
#
# ------------------------------------------------------------
class TestWikiTreeLauncher(unittest.TestCase):
    """
    Test cases for search defaults extraction, dialog interactions,
    WikiTree search execution, and merge dialog launching.
    """

    def setUp(self) -> None:
        """Create a fresh in-memory database for testing."""
        self.db = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        """Close the test database."""
        self.db.close()

    def test_extract_person_search_defaults_full(self) -> None:
        """Test defaults extraction with name, dates, and WikiTree ID attribute."""
        person = Person()
        pname = Name()
        pname.set_first_name("Benjamin")
        surn = Surname()
        surn.set_surname("Franklin")
        pname.add_surname(surn)
        person.set_primary_name(pname)

        with DbTxn("Add defaults test", self.db) as trans:
            # Birth
            b_evt = Event()
            b_evt.set_type(EventType(EventType.BIRTH))
            b_date = Date(1706, 1, 17)
            b_evt.set_date_object(b_date)
            b_h = self.db.add_event(b_evt, trans)
            b_ref = EventRef()
            b_ref.ref = b_h
            person.set_birth_ref(b_ref)

            # Death
            d_evt = Event()
            d_evt.set_type(EventType(EventType.DEATH))
            d_date = Date(1790, 4, 17)
            d_evt.set_date_object(d_date)
            d_h = self.db.add_event(d_evt, trans)
            d_ref = EventRef()
            d_ref.ref = d_h
            person.set_death_ref(d_ref)

            # WikiTree ID attribute
            attr = Attribute()
            attr.set_type(AttributeType("WikiTree ID"))
            attr.set_value("Franklin-1")
            person.add_attribute(attr)

            p_h = self.db.add_person(person, trans)

        saved_person = self.db.get_person_from_handle(p_h)
        defaults = _extract_person_search_defaults(self.db, saved_person)
        self.assertEqual(defaults["first_name"], "Benjamin")
        self.assertEqual(defaults["last_name"], "Franklin")
        self.assertEqual(defaults["birth_year"], "1706")
        self.assertEqual(defaults["death_year"], "1790")
        self.assertEqual(defaults["wt_id"], "Franklin-1")

    def test_extract_person_search_defaults_empty(self) -> None:
        """Test defaults extraction with None or empty person."""
        self.assertEqual(
            _extract_person_search_defaults(self.db, None),
            {
                "first_name": "",
                "last_name": "",
                "birth_year": "",
                "death_year": "",
                "wt_id": "",
            },
        )

    def test_extract_person_search_defaults_from_url(self) -> None:
        """Verify recalling WikiTree ID stored in Internet tab URL."""
        person = Person()
        pname = Name()
        pname.set_first_name("George")
        surn = Surname()
        surn.set_surname("Washington")
        pname.add_surname(surn)
        person.set_primary_name(pname)

        # Add Internet Web Home URL as created by GEDCOM import
        url = Url()
        url.set_path("https://www.wikitree.com/wiki/Washington-11")
        url.set_type(UrlType(UrlType.WEB_HOME))
        person.add_url(url)

        with DbTxn("Add person with url", self.db) as trans:
            p_h = self.db.add_person(person, trans)

        saved = self.db.get_person_from_handle(p_h)
        defaults = _extract_person_search_defaults(self.db, saved)
        self.assertEqual(defaults["first_name"], "George")
        self.assertEqual(defaults["last_name"], "Washington")
        self.assertEqual(defaults["wt_id"], "Washington-11")

    def test_extract_person_search_defaults_from_url_with_fragment(self) -> None:
        """Verify recalling WikiTree ID from URL with fragment/query parameters."""
        person = Person()
        url = Url()
        url.set_path("https://www.WikiTree.com/wiki/Washington-11#Biography")
        url.set_type(UrlType(UrlType.WEB_HOME))
        person.add_url(url)

        with DbTxn("Add person with fragment url", self.db) as trans:
            p_h = self.db.add_person(person, trans)

        saved = self.db.get_person_from_handle(p_h)
        defaults = _extract_person_search_defaults(self.db, saved)
        self.assertEqual(defaults["wt_id"], "Washington-11")

    def test_dialog_init_and_prefill(self) -> None:
        """Test WikiTreeSearchDialog layout initialization and pre-filled fields."""
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
        dialog = WikiTreeSearchDialog(
            uistate=uistate,
            dbstate=dbstate,
            target_handle=p_h,
            client=mock_client,
        )

        self.assertEqual(dialog.default_size, (950, 600))
        self.assertTrue(dialog.resizable)
        dialog.first_name_entry.set_text.assert_called_with("George")
        dialog.last_name_entry.set_text.assert_called_with("Washington")

    def test_dialog_search_no_matches_keeps_open(self) -> None:
        """Verify that a search with no matches does not close the dialog and informs the user."""
        mock_client = Mock()
        mock_client.search_person.return_value = []
        mock_client.get_person.return_value = None

        dbstate = Mock()
        dbstate.db = self.db
        dialog = WikiTreeSearchDialog(dbstate=dbstate, client=mock_client)

        dialog.first_name_entry.get_text.return_value = "Unknown"
        dialog.last_name_entry.get_text.return_value = "Person"
        dialog.birth_year_entry.get_text.return_value = ""
        dialog.death_year_entry.get_text.return_value = ""
        dialog.wt_id_entry.get_text.return_value = ""

        dialog.cb_search()

        mock_client.search_person.assert_called_once()
        dialog.results_store.clear.assert_called()
        dialog.btn_merge.set_sensitive.assert_called_with(False)
        self.assertIn(
            "No matching profiles found",
            dialog.status_label.set_text.call_args[0][0],
        )

    def test_dialog_search_with_matches(self) -> None:
        """Verify that search results populate the table and enable the merge button."""
        mock_client = Mock()
        mock_client.get_person.return_value = None
        mock_client.search_person.return_value = [
            {
                "Id": 388,
                "Name": "Franklin-1",
                "FirstName": "Benjamin",
                "LastNameCurrent": "Franklin",
                "Gender": "Male",
                "BirthDate": "1706-01-17",
                "BirthLocation": "Boston, MA",
                "DeathDate": "1790-04-17",
                "DeathLocation": "Philadelphia, PA",
                "Parents": {
                    "1": {"ShortName": "Josiah Franklin"},
                    "2": {"ShortName": "Abiah Folger"},
                },
            }
        ]

        dbstate = Mock()
        dbstate.db = self.db
        dialog = WikiTreeSearchDialog(dbstate=dbstate, client=mock_client)

        dialog.first_name_entry.get_text.return_value = "Benjamin"
        dialog.last_name_entry.get_text.return_value = "Franklin"
        dialog.birth_year_entry.get_text.return_value = "1706"
        dialog.death_year_entry.get_text.return_value = "1790"
        dialog.wt_id_entry.get_text.return_value = ""

        first_iter = Mock()
        dialog.results_store.get_iter_first.return_value = first_iter

        dialog.cb_search()

        dialog.results_store.append.assert_called_once()
        appended_row = dialog.results_store.append.call_args[0][0]
        self.assertEqual(appended_row[0], "Franklin-1")
        self.assertEqual(appended_row[1], "Benjamin Franklin")
        self.assertEqual(appended_row[2], "Male")
        self.assertEqual(appended_row[3], "1706-01-17")
        self.assertEqual(appended_row[4], "Boston, MA")
        self.assertEqual(appended_row[5], "1790-04-17")
        self.assertEqual(appended_row[6], "Philadelphia, PA")
        self.assertEqual(appended_row[7], "Josiah Franklin, Abiah Folger")

        dialog.btn_merge.set_sensitive.assert_called_with(True)
        self.assertIn("Found 1 matching", dialog.status_label.set_text.call_args[0][0])

    def test_dialog_search_with_url_in_entry(self) -> None:
        """Verify searching when a full WikiTree URL is entered in the ID field."""
        mock_client = Mock()
        mock_client.get_person.return_value = {
            "Id": 11,
            "Name": "Washington-11",
            "FirstName": "George",
            "LastNameCurrent": "Washington",
            "Gender": "Male",
        }

        dialog = WikiTreeSearchDialog(client=mock_client)
        dialog.wt_id_entry.get_text.return_value = (
            "https://www.wikitree.com/wiki/Washington-11"
        )
        dialog.first_name_entry.get_text.return_value = ""
        dialog.last_name_entry.get_text.return_value = ""
        dialog.birth_year_entry.get_text.return_value = ""
        dialog.death_year_entry.get_text.return_value = ""

        dialog.cb_search()

        mock_client.get_person.assert_called_with("Washington-11")
        dialog.results_store.append.assert_called_once()
        appended_row = dialog.results_store.append.call_args[0][0]
        self.assertEqual(appended_row[0], "Washington-11")

    def test_dialog_merge_launches_merge_dialog(self) -> None:
        """Verify that cb_merge connects to WikiTreeGWizard and launches GWizardMergeDialog."""
        mock_client = Mock()
        mock_client.get_person.return_value = {
            "Id": 388,
            "Name": "Franklin-1",
            "FirstName": "Benjamin",
            "LastNameCurrent": "Franklin",
            "Gender": "Male",
        }

        dbstate = Mock()
        dbstate.db = self.db

        dialog = WikiTreeSearchDialog(dbstate=dbstate, client=mock_client)

        mock_iter = Mock()
        dialog.tree_view.get_selection().get_selected.return_value = (
            dialog.results_store,
            mock_iter,
        )
        dialog.results_store.get_value.return_value = "Franklin-1"

        # Create dummy source_db with a person having WikiTree ID attribute
        source_db = make_database("sqlite")
        source_db.load(":memory:")
        s_person = Person()
        s_attr = Attribute()
        s_attr.set_type(AttributeType("WikiTree ID"))
        s_attr.set_value("Franklin-1")
        s_person.add_attribute(s_attr)
        with DbTxn("Add source person", source_db) as trans:
            s_handle = source_db.add_person(s_person, trans)

        def fake_run_step(self_gw, step, **kwargs):
            if step == "connect":
                return True
            if step == "load":
                self_gw.context["source_db"] = source_db
                return [s_person]
            return True

        with (
            patch(
                "gramps.gen.gwizard.gwizardwikitree.WikiTreeGWizard.run_step",
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

    def test_ask_wikitree_parameters_compatibility(self) -> None:
        """Verify ask_wikitree_parameters compatibility helper."""
        from gi.repository import Gtk

        with patch(
            "gramps.gui.gwizard.gwizardwikitreelauncher.WikiTreeSearchDialog"
        ) as mock_cls:
            mock_dialog = Mock()
            mock_dialog.run.return_value = Gtk.ResponseType.OK
            mock_dialog.get_query_parameters.return_value = {
                "query": "Franklin-1",
                "ancestors": 0,
                "app_id": "TestApp",
            }
            mock_cls.return_value = mock_dialog

            params = ask_wikitree_parameters(parent=None, default_query="Franklin-1")
            self.assertEqual(
                params, {"query": "Franklin-1", "ancestors": 0, "app_id": "TestApp"}
            )
            mock_dialog.destroy.assert_called_once()

    def test_merge_dialog_displays_wtid_row(self) -> None:
        """Verify GWizardMergeDialog creates the wtid row when source has WikiTree ID."""
        source_db = make_database("sqlite")
        source_db.load(":memory:")
        s_person = Person()
        pname = Name()
        pname.set_first_name("Benjamin")
        s_person.set_primary_name(pname)
        url = Url()
        url.set_path("https://www.wikitree.com/wiki/Franklin-1")
        url.set_type(UrlType(UrlType.WEB_HOME))
        s_person.add_url(url)

        with DbTxn("Add source", source_db) as trans:
            s_handle = source_db.add_person(s_person, trans)

        t_person = Person()
        tpname = Name()
        tpname.set_first_name("Benjamin")
        t_person.set_primary_name(tpname)

        with DbTxn("Add target", self.db) as trans:
            t_handle = self.db.add_person(t_person, trans)

        from gramps.gen.gwizard.gwizardwikitree import WikiTreeGWizard
        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        gw = WikiTreeGWizard(self.db)
        gw.context["source_db"] = source_db

        dbstate = Mock()
        dbstate.db = self.db

        dialog = GWizardMergeDialog(dbstate, gw, s_handle, t_handle, parent=None)
        # Should have detected the WikiTree ID on the left and empty on the right
        self.assertGreater(dialog._mergeable_count, 0)
        source_db.close()

    def test_run_gwizard_wikitree_flow(self) -> None:
        """Verify run_gwizard_wikitree_flow launches the dialog."""
        uistate = Mock()
        uistate.get_active.return_value = "handle_123"
        dbstate = Mock()

        with patch(
            "gramps.gui.gwizard.gwizardwikitreelauncher.WikiTreeSearchDialog"
        ) as mock_cls:
            mock_dialog = Mock()
            mock_cls.return_value = mock_dialog

            result = run_gwizard_wikitree_flow(uistate, dbstate)
            self.assertTrue(result)
            mock_dialog.run.assert_called_once()
            mock_dialog.destroy.assert_called_once()
