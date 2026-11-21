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
import json
import os
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
from gramps.gen.gwizard.gwizardnaramerge import AttachResult, NaraCatalogInterface
from gramps.gui.gwizard.gwizardnaralauncher import (
    SEARCH_TERM_DEFAULTS,
    _extract_person_search_defaults,
    build_nara_query,
    format_size,
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
def _load_sample_response(name: str = "nara_record_naturalization.json") -> Any:
    """Load a real NARA response from the engine's test data folder."""
    sample = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "gen",
        "gwizard",
        "test",
        "data",
        name,
    )
    with open(sample, encoding="utf-8") as handle:
        return json.load(handle)


def _use_terms(
    dialog: Any,
    values: dict[str, str] | None = None,
    checked: dict[str, bool] | None = None,
    exact: bool = False,
    after_death: int = 10,
) -> None:
    """
    Make a dialog's mocked search widgets return the given term text, the
    default checks (overridden by 'checked'), the Exact name setting and the
    years-after-death setting.
    """
    values = values or {}
    checked = {**SEARCH_TERM_DEFAULTS, **(checked or {})}
    for key, entry in dialog.term_entries.items():
        entry.get_text.return_value = values.get(key, "")
    for key, check in dialog.term_checks.items():
        check.get_active.return_value = checked[key]
    dialog.exact_check.get_active.return_value = exact
    dialog.after_death_spin.get_value_as_int.return_value = after_death


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
                "middle_name": "",
                "last_name": "",
                "married_name": "",
                "query": "",
                "birth_year": "",
                "birth_place": "",
                "death_year": "",
                "death_place": "",
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
        with patch.dict(os.environ, {"NARA_API_KEY": "environment_key"}):
            dialog = NaraSearchDialog(
                uistate=uistate,
                dbstate=dbstate,
                target_handle=p_h,
                client=mock_client,
            )

        self.assertEqual(dialog.default_size, (950, 600))
        self.assertTrue(dialog.resizable)
        self.assertEqual(dialog.api_key, "environment_key")
        dialog.first_name_entry.set_text.assert_called_with("George")
        dialog.last_name_entry.set_text.assert_called_with("Washington")
        dialog.query_entry.set_text.assert_called_with("")
        for key, check in dialog.term_checks.items():
            check.set_active.assert_called_with(SEARCH_TERM_DEFAULTS[key])

    def test_format_size(self) -> None:
        """Verify file sizes are shown in readable units."""
        self.assertEqual(format_size(0), "")
        self.assertEqual(format_size(512), "512 B")
        self.assertEqual(format_size(870_000), "850 KB")
        self.assertEqual(format_size(6_009_258), "5.7 MB")
        self.assertEqual(format_size(451_000_000), "430 MB")
        self.assertEqual(format_size(1_300_000_000), "1.2 GB")

    def test_build_nara_query(self) -> None:
        """Verify checked terms combine into one NARA keyword query."""
        self.assertEqual(
            build_nara_query({"first_name": "Mary", "last_name": "Kreizer"}),
            "Mary Kreizer",
        )
        self.assertEqual(
            build_nara_query(
                {
                    "first_name": "Mary",
                    "middle_name": "Ann",
                    "last_name": "Kreizer",
                    "married_name": "Smith",
                    "keywords": "pension",
                },
                exact=True,
            ),
            '"Mary Ann Kreizer" Smith pension',
        )
        self.assertEqual(build_nara_query({"last_name": "Smith"}, exact=True), "Smith")
        self.assertEqual(build_nara_query({"keywords": "90361620"}), "90361620")
        self.assertEqual(build_nara_query({"first_name": " ", "keywords": ""}), "")

    def test_extract_defaults_middle_and_married_names(self) -> None:
        """Verify given names split and a Married Name alternate name is used."""
        from gramps.gen.lib import NameType

        person = Person()
        pname = Name()
        pname.set_first_name("Mary Ann")
        surn = Surname()
        surn.set_surname("Kreizer")
        pname.add_surname(surn)
        person.set_primary_name(pname)
        alt = Name()
        alt.set_type(NameType(NameType.MARRIED))
        alt_surn = Surname()
        alt_surn.set_surname("Smith")
        alt.add_surname(alt_surn)
        person.add_alternate_name(alt)

        defaults = _extract_person_search_defaults(self.db, person)
        self.assertEqual(defaults["first_name"], "Mary")
        self.assertEqual(defaults["middle_name"], "Ann")
        self.assertEqual(defaults["last_name"], "Kreizer")
        self.assertEqual(defaults["married_name"], "Smith")

    def test_married_name_from_husband_for_women_only(self) -> None:
        """Verify the husband's-surname fallback applies to women only."""
        from gramps.gen.lib import Family

        wife = Person()
        wife.set_gender(Person.FEMALE)
        husband = Person()
        husband.set_gender(Person.MALE)
        h_name = Name()
        h_surn = Surname()
        h_surn.set_surname("Smith")
        h_name.add_surname(h_surn)
        husband.set_primary_name(h_name)
        with DbTxn("Add couple", self.db) as trans:
            self.db.add_person(wife, trans)
            h_handle = self.db.add_person(husband, trans)
            family = Family()
            family.set_father_handle(h_handle)
            family.set_mother_handle(wife.get_handle())
            f_handle = self.db.add_family(family, trans)
            wife.add_family_handle(f_handle)
            husband.add_family_handle(f_handle)
            self.db.commit_person(wife, trans)
            self.db.commit_person(husband, trans)

        self.assertEqual(
            _extract_person_search_defaults(self.db, wife)["married_name"], "Smith"
        )
        self.assertEqual(
            _extract_person_search_defaults(self.db, husband)["married_name"], ""
        )

    def test_prefill_record_years_from_life_span(self) -> None:
        """Verify the record years default to birth through death plus ten."""
        person = Person()
        pname = Name()
        pname.set_first_name("Abraham")
        surn = Surname()
        surn.set_surname("Lincoln")
        pname.add_surname(surn)
        person.set_primary_name(pname)
        from gramps.gen.lib import Place, PlaceName

        birth = Event()
        birth.set_type(EventType.BIRTH)
        birth.set_date_object(Date(1809, 2, 12))
        death = Event()
        death.set_type(EventType.DEATH)
        death.set_date_object(Date(1865, 4, 15))
        with DbTxn("Add Lincoln", self.db) as trans:
            hodgenville = Place()
            hodgenville.set_name(PlaceName(value="Hodgenville"))
            birth.set_place_handle(self.db.add_place(hodgenville, trans))
            washington = Place()
            washington.set_title("Washington, District of Columbia, USA")
            death.set_place_handle(self.db.add_place(washington, trans))
            b_h = self.db.add_event(birth, trans)
            d_h = self.db.add_event(death, trans)
            b_ref = EventRef()
            b_ref.set_reference_handle(b_h)
            d_ref = EventRef()
            d_ref.set_reference_handle(d_h)
            person.add_event_ref(b_ref)
            person.set_birth_ref(b_ref)
            person.add_event_ref(d_ref)
            person.set_death_ref(d_ref)
            p_h = self.db.add_person(person, trans)

        dbstate = Mock()
        dbstate.db = self.db
        dialog = NaraSearchDialog(dbstate=dbstate, target_handle=p_h, client=Mock())
        dialog.term_entries["birth_year"].set_text.assert_called_with("1809")
        dialog.term_entries["birth_place"].set_text.assert_called_with("Hodgenville")
        dialog.term_entries["death_year"].set_text.assert_called_with("1865")
        dialog.term_entries["death_place"].set_text.assert_called_with("Washington")
        for key in ("birth_year", "birth_place", "death_year", "death_place"):
            dialog.term_checks[key].set_active.assert_called_with(False)

    def test_search_uses_checked_terms_exact_and_years(self) -> None:
        """Verify the query and record years follow the checked terms."""
        mock_client = Mock()
        mock_client.extract_hits.return_value = []
        dialog = NaraSearchDialog(client=mock_client)
        _use_terms(
            dialog,
            {
                "first_name": "Mary",
                "middle_name": "Ann",
                "last_name": "Kreizer",
                "married_name": "Smith",
                "birth_year": "1840",
                "birth_place": "New York",
                "death_year": "1925",
                "death_place": "Baltimore",
                "keywords": "pension",
            },
            checked={
                "married_name": True,
                "birth_year": True,
                "birth_place": True,
                "death_year": True,
                "death_place": True,
            },
            exact=True,
        )
        dialog.limit_spin.get_value.return_value = 25
        dialog.material_combo.get_active_id.return_value = None
        dialog.online_check.get_active.return_value = False

        dialog.cb_search()

        kwargs = mock_client.search_records.call_args.kwargs
        self.assertEqual(
            kwargs["query"], '"Mary Kreizer" Smith "New York" Baltimore pension'
        )
        self.assertEqual(kwargs["start_year"], "1840")
        self.assertEqual(kwargs["end_year"], "1935")

    def test_record_years_follow_checks_and_after_death(self) -> None:
        """Verify each year applies only when checked, with the after-death span."""
        dialog = NaraSearchDialog(client=Mock())
        values = {"birth_year": "1840", "death_year": "1925"}
        _use_terms(dialog, values, checked={"death_year": True}, after_death=25)
        self.assertEqual(dialog._record_years(), ("", "1950"))
        _use_terms(dialog, values, checked={"birth_year": True})
        self.assertEqual(dialog._record_years(), ("1840", ""))
        _use_terms(dialog, values)
        self.assertEqual(dialog._record_years(), ("", ""))

    def test_search_ignores_unchecked_terms_and_bad_years(self) -> None:
        """Verify unchecked terms and non-year text are left out."""
        mock_client = Mock()
        mock_client.extract_hits.return_value = []
        dialog = NaraSearchDialog(client=mock_client)
        _use_terms(
            dialog,
            {
                "first_name": "Mary",
                "last_name": "Kreizer",
                "keywords": "pension",
                "birth_year": "18",
                "death_year": "abcd",
                "birth_place": "Baltimore",
            },
            checked={"first_name": False, "keywords": False, "death_year": True},
        )
        dialog.limit_spin.get_value.return_value = 25
        dialog.material_combo.get_active_id.return_value = None
        dialog.online_check.get_active.return_value = False

        dialog.cb_search()

        kwargs = mock_client.search_records.call_args.kwargs
        self.assertEqual(kwargs["query"], "Kreizer")
        self.assertEqual(kwargs["start_year"], "")
        self.assertEqual(kwargs["end_year"], "")

    def test_search_with_nothing_checked_asks_for_terms(self) -> None:
        """Verify an empty query does not call NARA."""
        mock_client = Mock()
        dialog = NaraSearchDialog(client=mock_client)
        _use_terms(dialog, {"first_name": "Mary"}, checked={"first_name": False})

        dialog.cb_search()

        mock_client.search_records.assert_not_called()
        self.assertIn(
            "Please check and fill in", dialog.status_label.set_text.call_args[0][0]
        )

    def test_term_toggle_and_reset(self) -> None:
        """Verify toggling greys entries and Reset restores the defaults."""
        dialog = NaraSearchDialog(client=Mock(), default_query="pension")
        check = dialog.term_checks["middle_name"]
        entry = dialog.term_entries["middle_name"]
        check.get_active.return_value = True
        dialog.cb_term_toggled(check, "middle_name")
        entry.set_sensitive.assert_called_with(True)
        check.get_active.return_value = False
        dialog.cb_term_toggled(check, "middle_name")
        entry.set_sensitive.assert_called_with(False)

        for item in dialog.term_checks.values():
            item.set_active.reset_mock()
        dialog.cb_reset_terms()
        dialog.query_entry.set_text.assert_called_with("pension")
        for key, item in dialog.term_checks.items():
            item.set_active.assert_called_once_with(SEARCH_TERM_DEFAULTS[key])
        dialog.after_death_spin.set_value.assert_called_with(10)

    def test_terms_in_wikitree_order(self) -> None:
        """Verify the search terms run in the WikiTree dialog's order."""
        self.assertEqual(
            [spec[0] for spec in NaraSearchDialog._term_specs()],
            [
                "first_name",
                "middle_name",
                "last_name",
                "married_name",
                "birth_year",
                "birth_place",
                "death_year",
                "death_place",
                "keywords",
            ],
        )

    def test_term_labels_have_unique_mnemonics(self) -> None:
        """Verify the term shortcuts differ from each other and the buttons."""
        letters = []
        for _key, label, _ph, _tip, _width in NaraSearchDialog._term_specs():
            self.assertEqual(label.count("_"), 1, label)
            letters.append(label[label.index("_") + 1].lower())
        # Exact name, Change Tar_get, Add as Ne_w, Reset, Search, Attach,
        # Merge, Help, Close
        letters.extend(["x", "g", "w", "r", "s", "t", "m", "h", "c"])
        self.assertEqual(len(letters), len(set(letters)), letters)

    def test_dialog_search_no_matches_keeps_open(self) -> None:
        """Verify that a search with no matches does not close the dialog and informs the user."""
        mock_client = Mock()
        mock_client.search_records.return_value = {"body": {"hits": {"hits": []}}}
        mock_client.extract_hits.return_value = []

        dialog = NaraSearchDialog(client=mock_client)

        _use_terms(dialog)
        dialog.query_entry.get_text.return_value = "NonexistentRecord123"
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
                    "creators": [
                        {
                            "heading": "Lincoln, Abraham, 1809-1865",
                            "authorityType": "person",
                        }
                    ],
                    "generalRecordsTypes": ["Textual Records"],
                    "inclusiveStartDate": {"year": 1861, "logicalDate": "1861-01-01"},
                    "digitalObjects": [{"objectUrl": "https://example.com/doc.jpg"}],
                },
            },
        }
        mock_client.search_records.return_value = {"hits": [mock_hit]}
        mock_client.extract_hits.return_value = [mock_hit]

        dialog = NaraSearchDialog(client=mock_client)

        _use_terms(dialog)
        dialog.query_entry.get_text.return_value = "Abraham Lincoln"
        dialog.limit_spin.get_value.return_value = 10
        dialog.material_combo.get_active_id.return_value = "textual records"
        dialog.online_check.get_active.return_value = True

        dialog.cb_search()

        mock_client.search_records.assert_called_once_with(
            query="Abraham Lincoln",
            rows=10,
            material_type="textual records",
            available_online=True,
            start_year="",
            end_year="",
        )
        dialog.results_store.append.assert_called_once()
        appended_row = dialog.results_store.append.call_args[0][0]
        self.assertEqual(appended_row[0], "55555")
        self.assertEqual(appended_row[1], "Abraham Lincoln Commission")
        self.assertEqual(appended_row[2], "Lincoln, Abraham, 1809-1865")
        self.assertEqual(appended_row[3], "Lincoln, Abraham, 1809-1865")
        self.assertEqual(appended_row[4], "1861")
        self.assertEqual(appended_row[5], "Textual Records")
        self.assertEqual(appended_row[6], "1")
        self.assertIs(appended_row[8], True)

        dialog.btn_merge.set_sensitive.assert_called_with(True)
        self.assertIn("Found 1 matching", dialog.status_label.set_text.call_args[0][0])

    def test_dialog_search_real_records_disable_merge(self) -> None:
        """Verify real agency-created records show a dash and disable Merge."""
        sample = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "..",
            "gen",
            "gwizard",
            "test",
            "data",
            "nara_search_pension.json",
        )
        with open(sample, encoding="utf-8") as handle:
            response = json.load(handle)
        hits = NaraCatalogInterface.extract_hits(response)
        mock_client = Mock()
        mock_client.search_records.return_value = response
        mock_client.extract_hits.return_value = hits

        dialog = NaraSearchDialog(client=mock_client)

        _use_terms(dialog)
        dialog.query_entry.get_text.return_value = "john smith pension"
        dialog.limit_spin.get_value.return_value = 5
        dialog.material_combo.get_active_id.return_value = ""
        dialog.online_check.get_active.return_value = False
        rows: list[list[Any]] = []
        dialog.results_store.append.side_effect = rows.append
        dialog.results_store.get_value.side_effect = lambda _it, col: rows[0][col]

        dialog.cb_search()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][2], "Smith, Mary Kreizer")
        self.assertEqual(rows[0][9], "-")
        self.assertTrue(rows[0][3].endswith("(from series)"), rows[0][3])
        self.assertEqual(rows[0][4], "1861-1934 (from series)")
        self.assertEqual(rows[0][5], "Textual Records")
        self.assertRegex(rows[0][6], r"^2 \(\d+(\.\d)? MB\)$")
        self.assertIs(rows[0][8], False)
        dialog.btn_merge.set_sensitive.assert_called_with(False)
        self.assertIn("names no person", dialog.status_label.set_text.call_args[0][0])

    def test_search_scores_matches_against_the_person(self) -> None:
        """Verify the Match column scores each record's named person."""
        response = _load_sample_response("nara_search_pension.json")
        hits = NaraCatalogInterface.extract_hits(response)
        mock_client = Mock()
        mock_client.search_records.return_value = response
        mock_client.extract_hits.return_value = hits
        dialog = NaraSearchDialog(client=mock_client)
        _use_terms(
            dialog,
            {"first_name": "Mary", "last_name": "Kreizer", "married_name": "Smith"},
        )
        dialog.limit_spin.get_value.return_value = 5
        dialog.material_combo.get_active_id.return_value = ""
        dialog.online_check.get_active.return_value = False
        rows: list[list[Any]] = []
        dialog.results_store.append.side_effect = rows.append
        dialog.results_store.get_value.side_effect = lambda _it, col: rows[0][col]

        dialog.cb_search()

        self.assertEqual(rows[0][9], "100% (name only)")
        self.assertEqual(rows[0][10], 100.0)
        self.assertLess(rows[1][10], rows[0][10])
        self.assertEqual(rows[1][2], "Smith, Sarah Butt")

    def test_selection_changed_enables_merge_for_person_records(self) -> None:
        """Verify Merge follows whether the selected record names a person."""
        dialog = NaraSearchDialog(client=Mock())
        model = Mock()
        selection = Mock()
        selection.get_selected.return_value = (model, Mock())

        model.get_value.return_value = True
        dialog.cb_selection_changed(selection)
        dialog.btn_merge.set_sensitive.assert_called_with(True)

        model.get_value.return_value = False
        dialog.cb_selection_changed(selection)
        dialog.btn_merge.set_sensitive.assert_called_with(False)

        selection.get_selected.return_value = (model, None)
        dialog.cb_selection_changed(selection)
        dialog.btn_merge.set_sensitive.assert_called_with(False)

    def _attach_dialog(self, target: str | None = "I_handle") -> Any:
        """Return a dialog with a selected row holding the naturalization record."""
        dbstate = Mock()
        dbstate.db = self.db
        dialog = NaraSearchDialog(dbstate=dbstate, client=Mock())
        dialog.target_handle = target
        hit = NaraCatalogInterface.extract_hits(_load_sample_response())[0]
        model = Mock()
        model.get_value.side_effect = lambda _it, col: {7: hit, 8: False}.get(col, "")
        dialog.tree_view.get_selection().get_selected.return_value = (model, Mock())
        return dialog

    def test_attach_button_needs_target_person(self) -> None:
        """Verify Attach to Person is enabled only with a target person."""
        dialog = self._attach_dialog(target="I_handle")
        dialog._refresh_action_buttons()
        dialog.btn_attach.set_sensitive.assert_called_with(True)
        dialog.btn_merge.set_sensitive.assert_called_with(False)
        self.assertIn("Attach to Person", dialog.status_label.set_text.call_args[0][0])

        dialog.cb_set_target_none()
        dialog.btn_attach.set_sensitive.assert_called_with(False)
        self.assertIn(
            "Choose a target person", dialog.status_label.set_text.call_args[0][0]
        )

    def test_cb_attach_opens_review_window(self) -> None:
        """Verify Attach opens the review window and reports what it did."""
        dialog = self._attach_dialog()
        result = AttachResult(citation_created=True, downloaded=1, media_added=1)
        with patch(
            "gramps.gui.gwizard.gwizardnaraattachdialog.NaraAttachDialog"
        ) as review_cls:
            review = review_cls.return_value
            review.run.return_value = _gtk.ResponseType.OK
            review.run_attach.return_value = result
            dialog.cb_attach()

        args = review_cls.call_args[0]
        self.assertEqual(args[3], "I_handle")
        self.assertEqual(args[4]["naid"], "90361620")
        review.run_attach.assert_called_once()
        review.destroy.assert_called_once()
        message = dialog.status_label.set_text.call_args[0][0]
        self.assertIn("attached as a new citation", message)
        self.assertIn("Images downloaded: 1", message)

    def test_cb_attach_cancel_changes_nothing(self) -> None:
        """Verify cancelling the review window attaches nothing."""
        dialog = self._attach_dialog()
        with patch(
            "gramps.gui.gwizard.gwizardnaraattachdialog.NaraAttachDialog"
        ) as review_cls:
            review_cls.return_value.run.return_value = _gtk.ResponseType.CANCEL
            dialog.cb_attach()
        review_cls.return_value.run_attach.assert_not_called()
        review_cls.return_value.destroy.assert_called_once()

    def test_cb_attach_failure_keeps_window_open(self) -> None:
        """Verify a failed attach returns to the review window."""
        dialog = self._attach_dialog()
        with patch(
            "gramps.gui.gwizard.gwizardnaraattachdialog.NaraAttachDialog"
        ) as review_cls:
            review = review_cls.return_value
            review.run.side_effect = [_gtk.ResponseType.OK, _gtk.ResponseType.CANCEL]
            review.run_attach.return_value = None
            dialog.cb_attach()
        self.assertEqual(review.run.call_count, 2)
        review.destroy.assert_called_once()

    def test_cb_attach_reports_window_errors(self) -> None:
        """Verify a review window that cannot open is reported."""
        dialog = self._attach_dialog()
        with patch(
            "gramps.gui.gwizard.gwizardnaraattachdialog.NaraAttachDialog",
            side_effect=RuntimeError("boom"),
        ):
            dialog.cb_attach()
        self.assertIn(
            "Could not review the NARA record: boom",
            dialog.status_label.set_text.call_args[0][0],
        )

    def test_attach_summary_mentions_failures_and_cancel(self) -> None:
        """Verify the summary reports failed downloads, relinks and cancelling."""
        text = NaraSearchDialog._attach_summary(
            AttachResult(
                person_linked=True,
                failed=["u1", "u2"],
                cancelled=True,
                media_added=2,
                media_linked=3,
            )
        )
        self.assertIn("existing citation", text)
        self.assertIn("2 images could not be downloaded", text)
        self.assertIn("now linked: 1", text)
        self.assertIn("cancelled", text)

    def test_dialog_merge_launches_merge_dialog(self) -> None:
        """Verify that cb_merge connects to NaraGWizard and launches GWizardMergeDialog."""
        mock_client = Mock()
        mock_hit = {
            "_id": "55555",
            "_source": {
                "naId": "55555",
                "record": {
                    "title": "Abraham Lincoln Commission",
                    "creators": [
                        {
                            "heading": "Lincoln, Abraham, 1809-1865",
                            "authorityType": "person",
                        }
                    ],
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

        # Model returns naid at 0, hit at 7
        def get_val(_it, col):
            if col == 0:
                return "55555"
            if col == 7:
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
                "limit": 25,
            }
            mock_cls.return_value = mock_dialog

            params = ask_nara_parameters(parent=None, default_query="Lincoln")
            self.assertEqual(params, {"query": "Lincoln", "limit": 25})
            mock_dialog.destroy.assert_called_once()

    def test_run_gwizard_nara_flow(self) -> None:
        """Verify run_gwizard_nara_flow launches the dialog."""
        uistate = Mock()
        uistate.get_active.return_value = "handle_123"
        dbstate = Mock()

        with (
            patch.dict(os.environ, {"NARA_API_KEY": "test-key"}),
            patch(
                "gramps.gui.gwizard.gwizardnaralauncher.NaraCatalogInterface.validate_api_key",
                return_value=None,
            ) as mock_validate,
            patch(
                "gramps.gui.gwizard.gwizardnaralauncher.NaraSearchDialog"
            ) as mock_cls,
        ):
            mock_dialog = Mock()
            mock_cls.return_value = mock_dialog

            result = run_gwizard_nara_flow(uistate, dbstate)
            self.assertTrue(result)
            mock_validate.assert_called_once()
            mock_dialog.run.assert_called_once()
            mock_dialog.destroy.assert_called_once()

    def test_run_gwizard_nara_flow_requires_api_key(self) -> None:
        """Do not open search UI if NARA_API_KEY is unset."""
        uistate = Mock()
        dbstate = Mock()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "gramps.gui.gwizard.gwizardnaralauncher.NaraSearchDialog"
            ) as mock_search,
            patch(
                "gramps.gui.gwizard.gwizardnaralauncher.Gtk.MessageDialog"
            ) as mock_msg,
        ):
            result = run_gwizard_nara_flow(uistate, dbstate)

        self.assertFalse(result)
        mock_search.assert_not_called()
        mock_msg.return_value.run.assert_called_once()
        mock_msg.return_value.destroy.assert_called_once()

    def test_run_gwizard_nara_flow_rejects_invalid_api_key(self) -> None:
        """Do not open search UI if NARA rejects the configured API key."""
        uistate = Mock()
        dbstate = Mock()

        with (
            patch.dict(os.environ, {"NARA_API_KEY": "invalid-key"}),
            patch(
                "gramps.gui.gwizard.gwizardnaralauncher.NaraCatalogInterface.validate_api_key",
                return_value="NARA rejected the API key.",
            ) as mock_validate,
            patch(
                "gramps.gui.gwizard.gwizardnaralauncher.NaraSearchDialog"
            ) as mock_search,
            patch(
                "gramps.gui.gwizard.gwizardnaralauncher.Gtk.MessageDialog"
            ) as mock_msg,
        ):
            result = run_gwizard_nara_flow(uistate, dbstate)

        self.assertFalse(result)
        mock_validate.assert_called_once()
        mock_search.assert_not_called()
        mock_msg.return_value.format_secondary_text.assert_called_once_with(
            "NARA rejected the API key."
        )
        mock_msg.return_value.destroy.assert_called_once()

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
