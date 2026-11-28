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
import importlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
from typing import TYPE_CHECKING, Any


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
        self.buttons: dict[int, Any] = {}
        self.handlers: dict[str, Any] = {}
        self.stopped: list[str] = []

    def connect(self, signal: str, handler: Any) -> None:
        self.handlers[signal] = handler

    def stop_emission_by_name(self, signal: str) -> None:
        self.stopped.append(signal)

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
        button = MagicMock()
        button.label = text
        self.buttons[response] = button
        return button

    def show_all(self) -> None:
        pass


# Fresh stand-ins, put in sys.modules only while this module's tests run.
_STUB_MODULES: dict[str, Any] = {}
_gi: Any = MagicMock()

_gi_repo: Any = MagicMock()

_glib: Any = MagicMock()
_glib.markup_escape_text = lambda s: str(s)
_gi_repo.GLib = _glib

_gtk: Any = MagicMock()
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
_gi_repo.Gtk = _gtk

_gdk: Any = MagicMock()
_gi_repo.Gdk = _gdk

_pango: Any = MagicMock()
_gi_repo.Pango = _pango

_gi.repository = _gi_repo
_STUB_MODULES.update(
    {
        "gi": _gi,
        "gi.repository": _gi_repo,
        "gi.repository.GLib": _glib,
        "gi.repository.Gtk": _gtk,
        "gi.repository.Gdk": _gdk,
        "gi.repository.Pango": _pango,
    }
)


def _uses_gtk(name: str) -> bool:
    """
    True for modules that must be imported again under the stand-ins.

    Test modules stay put: unittest finds a module's tearDownModule through
    sys.modules, and they do not use GTK themselves.
    """
    if ".test." in name or name.endswith(".test"):
        return False
    return (
        name in ("gi", "gramps.gui")
        or name.startswith("gi.")
        or name.startswith("gramps.gui.")
    )


_SAVED_MODULES: dict[str, Any] = {}


def setUpModule() -> None:  # pylint: disable=invalid-name
    """
    Import the window under this module's own GTK stand-ins.

    Never reuse real GTK, or a stub another test module put in sys.modules:
    changing it there leaks into other tests (a real GLib whose
    markup_escape_text no longer escapes, for one). Modules that use GTK
    (gi and gramps.gui.*) are set aside and imported afresh, so neither the
    stand-ins nor anything imported with them is seen by other test
    modules; tearDownModule puts the originals back.
    """
    _SAVED_MODULES.clear()
    _SAVED_MODULES.update(sys.modules)
    for name in [name for name in sys.modules if _uses_gtk(name)]:
        del sys.modules[name]
    sys.modules.update(_STUB_MODULES)

    module = importlib.import_module("gramps.gui.gwizard.gwizardnaralauncher")
    globals().update({name: getattr(module, name) for name in _IMPORTED_NAMES})


def tearDownModule() -> None:  # pylint: disable=invalid-name
    """Put back the modules setUpModule set aside."""
    sys.modules.clear()
    sys.modules.update(_SAVED_MODULES)
    # Importing afresh re-pointed package attributes (gramps.gui, ...) at
    # the fresh modules; point them back at the originals.
    for name, module in _SAVED_MODULES.items():
        parent, _sep, child = name.rpartition(".")
        if parent and _uses_gtk(name) and parent in _SAVED_MODULES:
            try:
                setattr(_SAVED_MODULES[parent], child, module)
            except (AttributeError, TypeError):
                pass
    _SAVED_MODULES.clear()


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
from gramps.gen.gwizard.gwizardnaramerge import (
    AttachResult,
    NaraCatalogInterface,
    NaraGWizard,
    NaraRecordAttacher,
)

# Imported by setUpModule, under this module's GTK stand-ins.
if TYPE_CHECKING:
    from gramps.gui.gwizard.gwizardnaralauncher import (
        ATTACH_HIDDEN_SECTIONS,
        SEARCH_TERM_DEFAULTS,
        _extract_person_search_defaults,
        build_nara_query,
        format_size,
        NaraSearchDialog,
        ask_nara_parameters,
        load_nara_gwizard,
        run_gwizard_nara_flow,
    )

_IMPORTED_NAMES = (
    "ATTACH_HIDDEN_SECTIONS",
    "SEARCH_TERM_DEFAULTS",
    "_extract_person_search_defaults",
    "build_nara_query",
    "format_size",
    "NaraSearchDialog",
    "ask_nara_parameters",
    "load_nara_gwizard",
    "run_gwizard_nara_flow",
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
            '"Kreizer Mary"',
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
            '"Mary Ann Smith" Kreizer pension',
        )
        self.assertEqual(build_nara_query({"last_name": "Smith"}, exact=True), "Smith")
        self.assertEqual(build_nara_query({"keywords": "90361620"}), "90361620")
        self.assertEqual(build_nara_query({"first_name": " ", "keywords": ""}), "")

    def test_build_nara_query_name_forms(self) -> None:
        """Verify the name is one phrase, surname first; other terms are words."""
        self.assertEqual(
            build_nara_query(
                {"first_name": "John", "middle_name": "William", "last_name": "Smith"}
            ),
            '"Smith John William"',
        )
        self.assertEqual(
            build_nara_query(
                {"first_name": "John", "middle_name": "W", "last_name": "Smith"}
            ),
            '"Smith John W"',
        )
        # A NAID in the keywords finds that record, whatever the name says.
        self.assertEqual(
            build_nara_query(
                {"first_name": "John", "last_name": "Smith", "keywords": "90361620"}
            ),
            "90361620",
        )
        # Cities and keywords are further words a record must have.
        self.assertEqual(
            build_nara_query(
                {
                    "first_name": "John",
                    "last_name": "Smith",
                    "birth_place": "Reno",
                    "death_place": "Las Vegas",
                    "keywords": "pension",
                },
                exact=True,
            ),
            '"John Smith" Reno "Las Vegas" pension',
        )
        # One name alone stays a word.
        self.assertEqual(
            build_nara_query({"last_name": "Smith", "keywords": "pension"}),
            "Smith pension",
        )

    def test_extract_defaults_leave_out_nicknames(self) -> None:
        """Verify nicknames in quotes or brackets stay out of the names."""
        for given in ('John "Jack" William', "John (Jack) William"):
            person = Person()
            pname = Name()
            pname.set_first_name(given)
            surn = Surname()
            surn.set_surname("Smith")
            pname.add_surname(surn)
            person.set_primary_name(pname)
            defaults = _extract_person_search_defaults(self.db, person)
            self.assertEqual(defaults["first_name"], "John")
            self.assertEqual(defaults["middle_name"], "William")
            self.assertEqual(defaults["query"], "John William Smith")

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
            kwargs["query"],
            '"Mary Smith" Kreizer "New York" Baltimore pension',
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
        dialog.btn_attach.set_sensitive.assert_called_with(False)

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

        # No target person here, so Merge stays off and says why.
        dialog.btn_attach.set_sensitive.assert_called_with(False)
        self.assertIn(
            "Choose a target person", dialog.status_label.set_text.call_args[0][0]
        )

    def test_dialog_search_real_records(self) -> None:
        """Verify real agency-created records fill the table."""
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
        dialog.btn_attach.set_sensitive.assert_called_with(False)

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

    def test_search_lists_best_match_first(self) -> None:
        """Verify records are listed by Match score, not catalog order."""
        response = _load_sample_response("nara_search_pension.json")
        hits = NaraCatalogInterface.extract_hits(response)
        mock_client = Mock()
        mock_client.search_records.return_value = response
        mock_client.extract_hits.return_value = hits
        dialog = NaraSearchDialog(client=mock_client)
        _use_terms(
            dialog,
            {"first_name": "Sarah", "last_name": "Butt", "married_name": "Smith"},
        )
        dialog.limit_spin.get_value.return_value = 5
        dialog.material_combo.get_active_id.return_value = ""
        dialog.online_check.get_active.return_value = False
        rows: list[list[Any]] = []
        dialog.results_store.append.side_effect = rows.append
        dialog.results_store.get_value.side_effect = lambda _it, col: rows[0][col]

        dialog.cb_search()

        # The catalog lists Mary Kreizer Smith first; Sarah is the better match.
        self.assertEqual(rows[0][2], "Smith, Sarah Butt")
        scores = [row[10] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_selection_changed_enables_merge_with_target(self) -> None:
        """Verify Merge needs a selected record and a target person."""
        dbstate = Mock()
        dialog = NaraSearchDialog(dbstate=dbstate, client=Mock())
        model = Mock()
        selection = Mock()
        selection.get_selected.return_value = (model, Mock())

        dialog.target_handle = "I_handle"
        dialog.cb_selection_changed(selection)
        dialog.btn_attach.set_sensitive.assert_called_with(True)

        selection.get_selected.return_value = (model, None)
        dialog.cb_selection_changed(selection)
        dialog.btn_attach.set_sensitive.assert_called_with(False)

        selection.get_selected.return_value = (model, Mock())
        dialog.target_handle = None
        dialog.cb_selection_changed(selection)
        dialog.btn_attach.set_sensitive.assert_called_with(False)

    def test_action_buttons_are_response_buttons(self) -> None:
        """
        Help, Close and Merge are added as dialog response buttons (so GTK
        orders them per platform); Help and Merge keep the window open.
        """
        from gramps.gui.gwizard.gwizardnaralauncher import RESPONSE_MERGE

        dialog = NaraSearchDialog(client=Mock())
        self.assertIs(dialog.buttons[RESPONSE_MERGE], dialog.btn_attach)
        self.assertEqual(dialog.buttons[RESPONSE_MERGE].label, "_Merge...")
        self.assertIn(_gtk.ResponseType.HELP, dialog.buttons)
        self.assertIn(_gtk.ResponseType.CLOSE, dialog.buttons)
        dialog.get_action_area().pack_end.assert_not_called()
        self.assertIs(
            dialog.handlers["response"].__func__, NaraSearchDialog.cb_response
        )

        with (
            patch.object(NaraSearchDialog, "cb_help") as cb_help,
            patch.object(NaraSearchDialog, "cb_attach") as cb_attach,
        ):
            dialog.cb_response(dialog, _gtk.ResponseType.HELP)
            cb_help.assert_called_once()
            dialog.cb_response(dialog, RESPONSE_MERGE)
            cb_attach.assert_called_once()
            self.assertEqual(dialog.stopped, ["response", "response"])
            dialog.cb_response(dialog, _gtk.ResponseType.CLOSE)
            self.assertEqual(dialog.stopped, ["response", "response"])

    def test_no_separate_person_merge_button(self) -> None:
        """Verify there is one Merge button (the record review) only."""
        dialog = NaraSearchDialog(client=Mock())
        self.assertFalse(hasattr(dialog, "btn_merge"))
        self.assertFalse(hasattr(dialog, "btn_new_target"))
        self.assertFalse(hasattr(NaraSearchDialog, "cb_merge"))

    def _attach_dialog(self, target: str | None = "I_handle") -> Any:
        """
        Return a dialog with a selected row holding the naturalization record;
        target "I_handle" is replaced by a real person in the tree.
        """
        if target == "I_handle":
            person = Person()
            name = Name()
            name.set_first_name("Lyman Angus")
            surname = Surname()
            surname.set_surname("MacDonald")
            name.add_surname(surname)
            person.set_primary_name(name)
            with DbTxn("Add person", self.db) as trans:
                target = self.db.add_person(person, trans)
        dbstate = Mock()
        dbstate.db = self.db
        client = Mock()
        client.fetch_record_text.return_value = {}
        dialog = NaraSearchDialog(dbstate=dbstate, client=client)
        dialog.target_handle = target
        hit = NaraCatalogInterface.extract_hits(_load_sample_response())[0]
        model = Mock()
        model.get_value.side_effect = lambda _it, col: {7: hit, 8: False}.get(col, "")
        dialog.tree_view.get_selection().get_selected.return_value = (model, Mock())
        return dialog

    def test_attach_button_needs_target_person(self) -> None:
        """Verify Merge is enabled only with a target person."""
        dialog = self._attach_dialog(target="I_handle")
        dialog._refresh_action_buttons()
        dialog.btn_attach.set_sensitive.assert_called_with(True)

        dialog.target_handle = None
        dialog._refresh_action_buttons()
        dialog.btn_attach.set_sensitive.assert_called_with(False)
        self.assertIn(
            "Choose a target person", dialog.status_label.set_text.call_args[0][0]
        )

    def test_cb_attach_opens_merge_window(self) -> None:
        """Verify Attach opens the merge window without the family sections."""
        dialog = self._attach_dialog()
        window = Mock()
        window.run.return_value = _gtk.ResponseType.OK
        seen: dict[str, int] = {}

        def open_window(_dbstate, gwizard, handle, _target, **_kwargs):
            # The incoming database is closed once the window closes.
            incoming = gwizard.context["source_db"].get_person_from_handle(handle)
            seen["images"] = len(incoming.get_media_list())
            return window

        with (
            patch(
                "gramps.gui.gwizard.gwizardmergedialog.GWizardMergeDialog",
                side_effect=open_window,
            ) as merge_cls,
            patch.object(
                NaraSearchDialog, "_finish_attach", return_value="finished"
            ) as finish,
        ):
            dialog.cb_attach()

        args, kwargs = merge_cls.call_args
        self.assertEqual(args[3], dialog.target_handle)
        self.assertEqual(kwargs["hidden_sections"], ATTACH_HIDDEN_SECTIONS)
        self.assertIn("90361620", kwargs["incoming_title"])
        self.assertEqual(seen["images"], 2)
        window.destroy.assert_called_once()
        finish.assert_called_once()
        dialog.client.fetch_record_text.assert_called_once_with("90361620")
        self.assertEqual(dialog.status_label.set_text.call_args[0][0], "finished")
        # Nothing was copied, since the merge window was a stand-in.
        self.assertEqual(self.db.get_number_of_citations(), 0)

    def test_merge_window_rows_for_a_record(self) -> None:
        """
        Verify the merge window, given a record's incoming person, leaves out
        the family sections and offers arrows for the citation, the record's
        event and the images.
        """
        from gramps.gui.gwizard import gwizardmergedialog
        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        dialog = self._attach_dialog()
        hit = NaraCatalogInterface.extract_hits(_load_sample_response())[0]
        parsed = NaraCatalogInterface.parse_record(hit)
        gwizard = NaraGWizard(self.db)
        handle = gwizard.load_for_person(dialog.target_handle, parsed)
        source_db = gwizard.context["source_db"]
        window = Mock(spec=GWizardMergeDialog)
        window.source_person = source_db.get_person_from_handle(handle)
        window.target_person = self.db.get_person_from_handle(dialog.target_handle)
        window.source_db = source_db
        window.target_db = self.db
        window.gwizard = gwizard
        window._hidden_sections = frozenset(ATTACH_HIDDEN_SECTIONS)
        window._incoming_title = "NARA Record"
        window._grid = Mock()
        window._value_column_size_group = Mock()
        window._mergeable_count = 0
        window._format_diff_line = lambda label, a, b, show_label, is_left: a
        window._event_for = lambda db, person, kind: ("", None, None)
        window._event_display_from = lambda event: ""
        window._related_text = lambda rel, db: ""
        window._spouses = lambda db, person: []
        window._parents = lambda db, person, role: []
        window._children = lambda db, person: []
        window._sorted_relatives = lambda db, persons: persons
        headings: list[str] = []

        def label(*_args, **_kwargs):
            widget = Mock()
            widget.set_markup.side_effect = headings.append
            return widget

        try:
            with (
                patch.object(gwizardmergedialog.Gtk, "Label", side_effect=label),
                patch.object(gwizardmergedialog.Gtk, "Separator"),
                patch.object(gwizardmergedialog, "create_diff_cell"),
            ):
                GWizardMergeDialog._populate_fields(window)
        finally:
            source_db.close()

        # The test's GLib stub may not escape markup.
        self.assertEqual(
            [heading.replace("&amp;", "&") for heading in headings],
            [
                "<b>NARA Record</b>",
                "<b>Current Family Tree</b>",
                "<b>Individual Details</b>",
                "<b>Events & Other Records</b>",
                "<b>Other Details</b>",
            ],
        )
        arrows = [call.args[0] for call in window._make_arrow.call_args_list]
        # The record's event (here a Naturalization) gets a row of its own;
        # its key holds the incoming event's handle, which changes each run.
        self.assertEqual(arrows[0], "person_sources")
        self.assertEqual(len(arrows), 4)
        self.assertTrue(arrows[1].startswith("event:"), arrows[1])
        self.assertEqual(arrows[2:], ["media:0", "media:1"])

    def test_cb_attach_cancel_changes_nothing(self) -> None:
        """Verify cancelling the merge window changes nothing."""
        dialog = self._attach_dialog()
        with (
            patch(
                "gramps.gui.gwizard.gwizardmergedialog.GWizardMergeDialog"
            ) as merge_cls,
            patch.object(NaraSearchDialog, "_finish_attach") as finish,
        ):
            merge_cls.return_value.run.return_value = _gtk.ResponseType.CANCEL
            dialog.cb_attach()
        finish.assert_not_called()
        merge_cls.return_value.destroy.assert_called_once()
        self.assertEqual(
            dialog.status_label.set_text.call_args[0][0], "Nothing was changed."
        )

    def test_cb_attach_reports_window_errors(self) -> None:
        """Verify a merge window that cannot open is reported."""
        dialog = self._attach_dialog()
        with patch(
            "gramps.gui.gwizard.gwizardmergedialog.GWizardMergeDialog",
            side_effect=RuntimeError("boom"),
        ):
            dialog.cb_attach()
        self.assertIn(
            "Could not review the NARA record: boom",
            dialog.status_label.set_text.call_args[0][0],
        )

    def test_page_details_describe_pages(self) -> None:
        """Verify page text from NARA becomes descriptions and notes."""
        dialog = self._attach_dialog()
        hit = NaraCatalogInterface.extract_hits(_load_sample_response())[0]
        parsed = NaraCatalogInterface.parse_record(hit)
        first = parsed["digital_objects"][0]["object_id"]
        dialog.client.fetch_record_text.return_value = {first: "AFFIDAVIT of Lyman"}
        descriptions, texts = dialog._page_details(dialog.target_handle, parsed)
        self.assertEqual(sorted(descriptions), [0, 1])
        self.assertTrue(descriptions[0].endswith("page 1: Affidavit"))
        self.assertEqual(texts[0], "AFFIDAVIT of Lyman")
        self.assertEqual(texts[1], "")

    def test_page_details_without_text(self) -> None:
        """Verify a record with no page text gets no descriptions."""
        dialog = self._attach_dialog()
        dialog.client.fetch_record_text.return_value = None
        hit = NaraCatalogInterface.extract_hits(_load_sample_response())[0]
        parsed = NaraCatalogInterface.parse_record(hit)
        self.assertEqual(dialog._page_details(dialog.target_handle, parsed), ({}, {}))

    def test_finish_attach_without_online_images(self) -> None:
        """Verify no download question is asked when nothing is online."""
        dialog = self._attach_dialog()
        with (
            patch.object(
                NaraRecordAttacher, "merged_images", return_value=([Mock()], [])
            ),
            patch.object(
                NaraRecordAttacher, "finish_merge", return_value=AttachResult()
            ) as finish,
            patch.object(NaraSearchDialog, "_ask_download") as ask,
        ):
            message = dialog._finish_attach(dialog.target_handle, {"naid": "1"})
        ask.assert_not_called()
        self.assertFalse(finish.call_args[1]["download"])
        self.assertIn("this person has 1 of its images", message)

    def test_finish_attach_declined_download(self) -> None:
        """Verify declining the download leaves images linked online."""
        dialog = self._attach_dialog()
        self.db.set_mediapath(tempfile.gettempdir())
        online = [Mock(size=10)]
        with (
            patch.object(
                NaraRecordAttacher, "merged_images", return_value=(online, online)
            ),
            patch.object(
                NaraRecordAttacher, "finish_merge", return_value=AttachResult()
            ) as finish,
            patch.object(NaraSearchDialog, "_ask_download", return_value=False),
        ):
            message = dialog._finish_attach(dialog.target_handle, {"naid": "1"})
        self.assertFalse(finish.call_args[1]["download"])
        self.assertIn("1 images are linked by their web address", message)

    def test_finish_attach_without_base_path(self) -> None:
        """Verify images are not offered for download without a base path."""
        dialog = self._attach_dialog()
        self.db.set_mediapath("")
        online = [Mock(size=10)]
        with (
            patch.object(
                NaraRecordAttacher, "merged_images", return_value=(online, online)
            ),
            patch.object(
                NaraRecordAttacher, "finish_merge", return_value=AttachResult()
            ) as finish,
            patch.object(NaraSearchDialog, "_ask_download") as ask,
        ):
            message = dialog._finish_attach(dialog.target_handle, {"naid": "1"})
        ask.assert_not_called()
        self.assertFalse(finish.call_args[1]["download"])
        self.assertIn("Base media path", message)

    def test_merge_summary_mentions_failures_and_cancel(self) -> None:
        """Verify the summary reports downloads, failures and cancelling."""
        text = NaraSearchDialog._merge_summary(
            AttachResult(downloaded=2, failed=["u1"], cancelled=True), 3, 3, True
        )
        self.assertIn("Images downloaded: 2", text)
        self.assertIn("1 images could not be downloaded", text)
        self.assertIn("cancelled", text)

    def test_merge_summary_names_the_cited_event(self) -> None:
        """Verify the summary says which event cites the record."""
        text = NaraSearchDialog._merge_summary(
            AttachResult(event_linked=True, event_type="Military Service"), 1, 0, False
        )
        self.assertIn("Their Military Service event cites the record.", text)
        plain = NaraSearchDialog._merge_summary(AttachResult(), 1, 0, False)
        self.assertNotIn("event", plain)

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
