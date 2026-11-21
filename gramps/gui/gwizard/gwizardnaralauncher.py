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
Launcher and search dialog for the GWizard NARA Merge flow.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizard_base import surname_text
from gramps.gen.gwizard.gwizardnaramatch import MatchQuery, best_match, match_text
from gramps.gen.lib import NameType, Person
from gramps.gen.gwizard.gwizardnaramerge import (
    AttachResult,
    format_size,
    NaraCatalogInterface,
    NaraGWizard,
    NaraRecordAttacher,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# Search terms that start checked: first name and last name. The others are
# filled in from the target person but left out until checked.
SEARCH_TERM_DEFAULTS: dict[str, bool] = {
    "first_name": True,
    "middle_name": False,
    "last_name": True,
    "married_name": False,
    "birth_year": False,
    "birth_place": False,
    "death_year": False,
    "death_place": False,
    "keywords": True,
}

# When Death Year is checked, records are searched up to this many years after
# the death year by default, because pension, estate and similar records are
# made after a death.
RECORD_YEARS_AFTER_DEATH = 10

# Merge window sections left out when attaching a record to a person: the
# record's incoming copy of the person has no family.
ATTACH_HIDDEN_SECTIONS = ("family_relations", "children", "families")


# ------------------------------------------------------------
#
# Helper functions
#
# ------------------------------------------------------------
def _extract_person_search_defaults(db: Any, person: Any) -> dict[str, str]:
    """
    Extract default search values (names, dates, query) from a Person.

    :param db: Active Gramps database.
    :param person: Gramps Person object.
    The first word of the given name is 'first_name' and any further words
    'middle_name'. 'married_name' comes from a Married Name alternate name,
    or failing that (for women only) from the husband's surname in the most
    recent family.

    'birth_place' and 'death_place' are the city (the place's own name, not
    its enclosing county or country) of the birth and death events.

    :returns: Dictionary with keys 'first_name', 'middle_name', 'last_name',
        'married_name', 'query', 'birth_year', 'birth_place', 'death_year',
        'death_place'.
    """
    defaults = {
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "married_name": "",
        "query": "",
        "birth_year": "",
        "birth_place": "",
        "death_year": "",
        "death_place": "",
    }
    if not person:
        return defaults

    pname = person.get_primary_name()
    if pname:
        fn = str(pname.get_first_name() or "").strip()
        ln = str(surname_text(pname) or "").strip()
        given_names = fn.split()
        if given_names:
            defaults["first_name"] = given_names[0]
            defaults["middle_name"] = " ".join(given_names[1:])
        defaults["last_name"] = ln
        defaults["query"] = f"{fn} {ln}".strip() or pname.get_name().strip()
    defaults["married_name"] = _married_surname(db, person)

    # Birth year
    bref = person.get_birth_ref()
    if bref and db:
        bevt = db.get_event_from_handle(bref.ref)
        if bevt:
            bdate = bevt.get_date_object()
            if bdate and bdate.get_year() > 0:
                defaults["birth_year"] = str(bdate.get_year())
            defaults["birth_place"] = _place_city(db, bevt)

    # Death year
    dref = person.get_death_ref()
    if dref and db:
        devt = db.get_event_from_handle(dref.ref)
        if devt:
            ddate = devt.get_date_object()
            if ddate and ddate.get_year() > 0:
                defaults["death_year"] = str(ddate.get_year())
            defaults["death_place"] = _place_city(db, devt)

    return defaults


def _place_city(db: Any, event: Any) -> str:
    """
    Return the city of an event's place: the place's own name, such as
    "Boston" for "Boston, Suffolk, Massachusetts, USA". '' when unknown.
    """
    handle = event.get_place_handle() if event else None
    if not handle:
        return ""
    place = db.get_place_from_handle(handle)
    if place is None:
        return ""
    name = str(place.get_name().get_value() or "").strip()
    if not name:
        # A place imported as one long title: take its first part.
        name = str(place.get_title() or "").split(",", 1)[0].strip()
    return name


def _married_surname(db: Any, person: Any) -> str:
    """
    Return the person's married surname, or '' when none is known.

    A Married Name alternate name wins. Otherwise, for a woman, the husband's
    surname from her most recent family (the last in her family list) is
    used; this is a guess, so the dialog leaves the term unchecked.
    """
    for alt_name in person.get_alternate_names():
        if int(alt_name.get_type()) == NameType.MARRIED:
            married = str(surname_text(alt_name) or "").strip()
            if married:
                return married

    if not db or person.get_gender() != Person.FEMALE:
        return ""
    for family_handle in reversed(person.get_family_handle_list()):
        family = db.get_family_from_handle(family_handle)
        if not family:
            continue
        husband_handle = family.get_father_handle()
        if not husband_handle or husband_handle == person.get_handle():
            continue
        husband = db.get_person_from_handle(husband_handle)
        if husband:
            married = str(surname_text(husband.get_primary_name()) or "").strip()
            if married:
                return married
    return ""


def _media_summary(digital_objects: list[dict[str, Any]]) -> str:
    """
    Return the Digital Media cell: 'No', the image count, or the count with
    the total size when NARA gives sizes, such as '75 (430 MB)'.
    """
    if not digital_objects:
        return _("No")
    total = sum(int(item.get("size") or 0) for item in digital_objects)
    if total:
        return _("%(count)d (%(size)s)") % {
            "count": len(digital_objects),
            "size": format_size(total),
        }
    return str(len(digital_objects))


def build_nara_query(terms: dict[str, str], exact: bool = False) -> str:
    """
    Combine search terms into one NARA keyword query.

    :param terms: The checked terms' text, keyed by term ('first_name',
        'middle_name', 'last_name', 'married_name', 'birth_place',
        'death_place', 'keywords'); empty or missing terms are skipped. Years
        are not part of the query; they filter by record date.
    :param exact: Put the given names and last name in quotes as one phrase.
        The married name and keywords are always added as they are.
    :returns: The query, for example '"Mary Kreizer" Smith pension'.
    """
    name = " ".join(
        part
        for part in (
            terms.get("first_name", "").strip(),
            terms.get("middle_name", "").strip(),
            terms.get("last_name", "").strip(),
        )
        if part
    )
    if exact and len(name.split()) > 1:
        name = f'"{name}"'
    places = []
    for key in ("birth_place", "death_place"):
        place = terms.get(key, "").strip()
        if place and place not in places:
            places.append(f'"{place}"' if " " in place else place)
    parts = [
        name,
        terms.get("married_name", "").strip(),
        *places,
        terms.get("keywords", "").strip(),
    ]
    return " ".join(part for part in parts if part)


# ------------------------------------------------------------
#
# NaraSearchDialog
#
# ------------------------------------------------------------
class NaraSearchDialog(Gtk.Dialog):
    """
    Search and merge dialog querying National Archives (NARA) Catalog records
    with tabular results, allowing users to review matches and launch the
    side-by-side merge dialog.
    """

    MATERIAL_TYPES: list[tuple[str, str]] = [
        ("", _("All Materials")),
        ("textual records", _("Textual Records")),
        ("photographs", _("Photographs / Graphic Materials")),
        ("sound recordings", _("Sound Recordings")),
        ("moving images", _("Moving Images / Film")),
        ("maps", _("Maps / Cartographic")),
        (
            "architectural and engineering drawings",
            _("Architectural and Engineering Drawings"),
        ),
    ]

    def __init__(
        self,
        uistate: Any = None,
        dbstate: Any = None,
        target_handle: str | None = None,
        parent: Any = None,
        default_query: str = "",
        client: Any = None,
    ) -> None:
        """
        Initialize the NARA search and merge dialog.

        :param uistate: Gramps UI state manager.
        :param dbstate: Gramps database state manager.
        :param target_handle: Handle of the target Gramps Person to merge into.
        :param parent: Parent GTK window for transient placement.
        :param default_query: Optional pre-filled search query.
        :param client: Optional NaraCatalogInterface client for testing.
        """
        super().__init__(
            title=str(_("GWizard NARA Merge")),
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(950, 600)
        self.set_resizable(True)

        self.uistate = uistate
        self.dbstate = dbstate
        self.target_handle = target_handle

        self.api_key = _get_nara_api_key()
        self.client = client or NaraCatalogInterface(api_key=self.api_key)

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_border_width(12)

        # -----------------------------------------------------------------
        # 1. Target Person Header
        # -----------------------------------------------------------------
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.target_label = Gtk.Label()
        self.target_label.set_xalign(0.0)
        self.target_label.set_hexpand(True)
        header_box.pack_start(self.target_label, True, True, 0)

        self.btn_change_target = Gtk.Button(
            label=_("Change Tar_get..."), use_underline=True
        )
        self.btn_change_target.set_tooltip_text(
            _("Select a different person in your Family Tree as the merge target.")
        )
        self.btn_change_target.connect("clicked", self.cb_change_target)
        header_box.pack_start(self.btn_change_target, False, False, 0)

        self.btn_new_target = Gtk.Button(label=_("Add as Ne_w"), use_underline=True)
        self.btn_new_target.set_tooltip_text(
            _(
                "Import selected NARA record as a new person rather than merging into an existing record."
            )
        )
        self.btn_new_target.connect("clicked", self.cb_set_target_none)
        header_box.pack_start(self.btn_new_target, False, False, 0)

        content.pack_start(header_box, False, False, 0)
        self._update_target_label()

        # -----------------------------------------------------------------
        # 2. Horizontal Search Criteria Grid
        # -----------------------------------------------------------------
        search_grid = Gtk.Grid()
        search_grid.set_column_spacing(8)
        search_grid.set_row_spacing(4)

        # Rows 0-1: checkable search terms. Each term has a check button
        # above its entry; an unchecked term keeps its text but is left out
        # of the query, so terms can be added or dropped with one click or
        # Alt plus the underlined letter. The checked names and the keywords
        # are combined into NARA's keyword query ("q").
        self.term_checks: dict[str, Any] = {}
        self.term_entries: dict[str, Any] = {}
        for column, (key, label, placeholder, tooltip, width) in enumerate(
            self._term_specs()
        ):
            check = Gtk.CheckButton(label=label, use_underline=True)
            check.set_tooltip_text(
                _(
                    "Include this term in the search. Unchecked terms are kept "
                    "but ignored."
                )
            )
            check.connect("toggled", self.cb_term_toggled, key)
            search_grid.attach(check, column, 0, 1, 1)

            entry = Gtk.Entry()
            if width:
                entry.set_width_chars(width)
            else:
                entry.set_hexpand(True)
            entry.set_placeholder_text(placeholder)
            entry.set_tooltip_text(tooltip)
            entry.connect("activate", self.cb_entry_activate)
            search_grid.attach(entry, column, 1, 1, 1)

            self.term_checks[key] = check
            self.term_entries[key] = entry

        self.first_name_entry = self.term_entries["first_name"]
        self.middle_name_entry = self.term_entries["middle_name"]
        self.last_name_entry = self.term_entries["last_name"]
        self.married_name_entry = self.term_entries["married_name"]
        self.query_entry = self.term_entries["keywords"]

        button_column = len(self.term_entries)
        self.btn_reset = Gtk.Button(label=_("_Reset"), use_underline=True)
        self.btn_reset.set_tooltip_text(
            _(
                "Restore the search terms taken from the target person and "
                "the default selection (first name and last name)."
            )
        )
        self.btn_reset.connect("clicked", self.cb_reset_terms)
        search_grid.attach(self.btn_reset, button_column, 1, 1, 1)

        self.btn_search = Gtk.Button(label=_("_Search"), use_underline=True)
        self.btn_search.get_style_context().add_class("suggested-action")
        self.btn_search.set_tooltip_text(
            _("Search the National Archives Catalog using the checked terms.")
        )
        self.btn_search.connect("clicked", self.cb_search)
        search_grid.attach(self.btn_search, button_column + 1, 1, 1, 1)

        # Row 2: options under the name and date columns, as on the WikiTree
        # dialog: Exact name under the names, the years after death under
        # the death columns.
        term_keys = [key for key, *_rest in self._term_specs()]
        self.exact_check = Gtk.CheckButton(label=_("E_xact name"), use_underline=True)
        self.exact_check.set_tooltip_text(
            _(
                "Search the given and last names as one phrase in quotes, for "
                'example "Lyman Angus MacDonald". A married name is still '
                "searched as a separate word."
            )
        )
        search_grid.attach(self.exact_check, 0, 2, term_keys.index("birth_year"), 1)

        after_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        after_label = Gtk.Label(label=_("Records up to"))
        after_box.pack_start(after_label, False, False, 0)
        self.after_death_spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        self.after_death_spin.set_value(RECORD_YEARS_AFTER_DEATH)
        self.after_death_spin.set_tooltip_text(
            _(
                "With Death Year checked, find records dated up to this many "
                "years after the death year (pensions and estate papers come "
                "after a death)."
            )
        )
        after_box.pack_start(self.after_death_spin, False, False, 0)
        after_box.pack_start(Gtk.Label(label=_("years after death")), False, False, 0)
        search_grid.attach(after_box, term_keys.index("death_year"), 2, 2, 1)

        # Row 3: material type and online only
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        filter_box.pack_start(Gtk.Label(label=_("Material Type:")), False, False, 0)
        self.material_combo = Gtk.ComboBoxText()
        for code, label in self.MATERIAL_TYPES:
            self.material_combo.append(code, label)
        self.material_combo.set_active(0)
        filter_box.pack_start(self.material_combo, False, False, 0)
        self.online_check = Gtk.CheckButton(label=_("Online only"))
        self.online_check.set_tooltip_text(
            _("Restrict results to records with digitized online assets.")
        )
        self.online_check.set_active(False)
        filter_box.pack_start(self.online_check, False, False, 0)
        search_grid.attach(filter_box, 0, 3, button_column + 2, 1)

        # Row 4: maximum number of records
        adv_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        limit_label = Gtk.Label(label=_("Max Records:"))
        adv_box.pack_start(limit_label, False, False, 0)

        limit_adj = Gtk.Adjustment(value=25, lower=1, upper=100, step_increment=5)
        self.limit_spin = Gtk.SpinButton(adjustment=limit_adj, climb_rate=1, digits=0)
        adv_box.pack_start(self.limit_spin, False, False, 0)

        search_grid.attach(adv_box, 0, 4, button_column + 2, 1)

        content.pack_start(search_grid, False, False, 0)

        # -----------------------------------------------------------------
        # 3. Status Message
        # -----------------------------------------------------------------
        self.status_label = Gtk.Label()
        self.status_label.set_xalign(0.0)
        self.status_label.set_line_wrap(True)
        self.status_label.set_text(
            _(
                "Check the terms to search on and click Search, or enter a "
                "NAID as the only keyword. Alt plus an underlined letter "
                "checks or unchecks a term."
            )
        )
        content.pack_start(self.status_label, False, False, 0)

        # -----------------------------------------------------------------
        # 4. Results Table
        # -----------------------------------------------------------------
        # Model columns:
        # 0: NAID (str)
        # 1: Title (str)
        # 2: Person creator(s), or a dash (str)
        # 3: Creator(s), own or the nearest ancestor's (str)
        # 4: Date (str)
        # 5: Material Type (str)
        # 6: Digital Media (str)
        # 7: Raw match data / hit (object)
        # 8: Can merge as a person (bool)
        # 9: Match text, such as "92%" (str)
        # 10: Match score, for sorting (float)
        self.results_store = Gtk.ListStore(
            str, str, str, str, str, str, str, object, bool, str, float
        )
        self.tree_view = Gtk.TreeView(model=self.results_store)
        self.tree_view.set_rules_hint(True)
        self.tree_view.set_enable_search(True)
        self.tree_view.set_search_column(1)

        self._build_tree_columns()

        selection = self.tree_view.get_selection()
        selection.set_mode(Gtk.SelectionMode.SINGLE)
        selection.connect("changed", self.cb_selection_changed)
        self.tree_view.connect("row-activated", self.cb_row_activated)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(280)
        scrolled.add(self.tree_view)
        content.pack_start(scrolled, True, True, 0)

        # -----------------------------------------------------------------
        # 5. Action Bar
        # -----------------------------------------------------------------
        btn_action_help = self.add_button(_("_Help"), Gtk.ResponseType.HELP)
        btn_action_help.connect("clicked", self.cb_help)

        self.add_button(_("_Close"), Gtk.ResponseType.CLOSE)

        self.btn_merge = Gtk.Button(label=_("_Merge..."), use_underline=True)
        self.btn_merge.set_tooltip_text(
            _(
                "Open the field-by-field merge dialog for the selected NARA "
                "record. Only for records that name a person as their creator."
            )
        )
        self.btn_merge.set_sensitive(False)
        self.btn_merge.connect("clicked", self.cb_merge)
        action_area = self.get_action_area()
        action_area.pack_end(self.btn_merge, False, False, 0)

        self.btn_attach = Gtk.Button(label=_("A_ttach to Person"), use_underline=True)
        self.btn_attach.get_style_context().add_class("suggested-action")
        self.btn_attach.set_tooltip_text(
            _(
                "Add the selected NARA record to the target person as a source "
                "and citation, with its images."
            )
        )
        self.btn_attach.set_sensitive(False)
        self.btn_attach.connect("clicked", self.cb_attach)
        action_area.pack_end(self.btn_attach, False, False, 0)

        # Pre-populate search entries from target person or default query
        self.default_query = default_query
        self._prefill_entries(default_query=default_query)
        self._apply_default_terms()

        self.show_all()

    def _build_tree_columns(self) -> None:
        """
        Create and append column headers for the search results treeview.
        """
        cols = [
            (_("NAID"), 0, False),
            (_("Title"), 1, True),
            (_("Match"), 9, False),
            (_("Person"), 2, False),
            (_("Creator"), 3, True),
            (_("Date"), 4, False),
            (_("Material Type"), 5, False),
            (_("Digital Media"), 6, False),
        ]
        for title, col_id, is_expand in cols:
            renderer = Gtk.CellRendererText()
            if is_expand:
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(title, renderer, text=col_id)
            # The Match column sorts by its numeric score.
            col.set_sort_column_id(10 if col_id == 9 else col_id)
            col.set_resizable(True)
            if is_expand:
                col.set_expand(True)
            self.tree_view.append_column(col)

    def _prefill_entries(self, default_query: str = "") -> None:
        """
        Pre-fill the search criteria entries from the target Person or query string.

        :param default_query: Fallback query string if no target person is set.
        """
        target_person = None
        db = self.dbstate.db if self.dbstate else None
        if self.target_handle and db:
            try:
                target_person = db.get_person_from_handle(self.target_handle)
            except Exception:
                target_person = None

        if target_person:
            defaults = _extract_person_search_defaults(db, target_person)
            for key in self.term_entries:
                if key != "keywords":
                    self.term_entries[key].set_text(defaults.get(key, ""))
            self.query_entry.set_text("")
        elif default_query:
            self.query_entry.set_text(default_query.strip())

    @staticmethod
    def _term_specs() -> list[tuple[str, str, str, str, int]]:
        """
        Return (key, check label, placeholder, entry tooltip, width) for each
        search term, in column order. A width of 0 lets the entry expand.

        The underlined letters must not clash with each other, with E_xact
        name, or with the dialog's buttons (Change Tar_get, Add as Ne_w,
        _Reset, _Search, A_ttach to Person, _Merge, _Help, _Close).
        """
        return [
            (
                "first_name",
                _("_First Name"),
                _("Given name"),
                _("First given name (wildcard * allowed)."),
                0,
            ),
            (
                "middle_name",
                _("Mi_ddle Name"),
                _("Other given names"),
                _("Other given names, searched after the first name."),
                10,
            ),
            (
                "last_name",
                _("_Last Name"),
                _("Surname"),
                _("Last name at birth (wildcard * allowed)."),
                0,
            ),
            (
                "married_name",
                _("Married _Name"),
                _("Married surname"),
                _(
                    "Married or other later surname, searched as an extra word. "
                    "Filled from a Married Name alternate name, or for a woman "
                    "from her husband's surname. Pension files for widows often "
                    "name both surnames."
                ),
                12,
            ),
            (
                "birth_year",
                _("_Birth Year"),
                _("YYYY"),
                _(
                    "Birth year. When checked, only records dated in or after "
                    "this year are found (the record's date, not the person's)."
                ),
                6,
            ),
            (
                "birth_place",
                _("Birth Cit_y"),
                _("City"),
                _("Birth city, searched as a word in the records."),
                12,
            ),
            (
                "death_year",
                _("D_eath Year"),
                _("YYYY"),
                _(
                    "Death year. When checked, only records dated up to the "
                    "chosen number of years after it are found."
                ),
                6,
            ),
            (
                "death_place",
                _("De_ath City"),
                _("City"),
                _("Death city, searched as a word in the records."),
                12,
            ),
            (
                "keywords",
                _("_Keywords"),
                _("Other words, or a NAID"),
                _(
                    "Other words to search for, such as pension, naturalization "
                    "or a regiment. NARA accepts AND, OR, NOT, * and "
                    '"exact phrases". A National Archives Identifier (NAID) '
                    "alone finds that record."
                ),
                0,
            ),
        ]

    def _apply_default_terms(self) -> None:
        """Check the default search terms and uncheck the rest."""
        for key, check in self.term_checks.items():
            check.set_active(SEARCH_TERM_DEFAULTS.get(key, False))
            self._sync_term_entry(key)
        self.exact_check.set_active(False)
        self.after_death_spin.set_value(RECORD_YEARS_AFTER_DEATH)

    def _sync_term_entry(self, key: str) -> None:
        """Make a term's entry editable only while it is checked."""
        self.term_entries[key].set_sensitive(bool(self.term_checks[key].get_active()))

    def _term_value(self, key: str) -> str:
        """Return a term's text, or '' when the term is unchecked."""
        if not self.term_checks[key].get_active():
            return ""
        return str(self.term_entries[key].get_text()).strip()

    def _search_query(self) -> str:
        """Return the NARA keyword query built from the checked terms."""
        terms = {key: self._term_value(key) for key in self.term_entries}
        return build_nara_query(terms, exact=bool(self.exact_check.get_active()))

    def _record_years(self) -> tuple[str, str]:
        """
        Return the (start, end) record years to filter on, each a 4-digit
        year or '': the checked birth year, and the checked death year plus
        the years after death.
        """

        def year(key: str) -> int | None:
            text = self._term_value(key)
            return int(text) if len(text) == 4 and text.isdigit() else None

        birth = year("birth_year")
        death = year("death_year")
        start = str(birth) if birth else ""
        end = ""
        if death:
            end = str(death + max(0, int(self.after_death_spin.get_value_as_int())))
        return start, end

    def cb_term_toggled(self, _check: Any, key: str) -> None:
        """Enable or disable a term's entry when its check button is toggled."""
        self._sync_term_entry(key)

    def cb_reset_terms(self, _widget: Any = None) -> None:
        """Restore the starting search values and the default selection."""
        for entry in self.term_entries.values():
            entry.set_text("")
        self._prefill_entries(default_query=self.default_query)
        self._apply_default_terms()

    def _update_target_label(self) -> None:
        """
        Update the target person header label to reflect the current target handle.
        """
        db = self.dbstate.db if self.dbstate else None
        if self.target_handle and db:
            try:
                person = db.get_person_from_handle(self.target_handle)
                if person:
                    name = person.get_primary_name().get_name()
                    gid = person.get_gramps_id()
                    self.target_label.set_markup(
                        _("Merge NARA data into: <b>%(name)s</b> (%(id)s)")
                        % {"name": GLib.markup_escape_text(name), "id": gid}
                    )
                    return
            except Exception as err:
                LOG.warning(
                    "Could not resolve target person %s: %s", self.target_handle, err
                )

        self.target_label.set_markup(
            _("Merge NARA data into: <i>None (will add as a new person)</i>")
        )

    def cb_change_target(self, _widget: Any = None) -> None:
        """
        Prompt the user to choose a different target person from the Family Tree.
        """
        if not self.dbstate or not self.dbstate.db:
            return
        try:
            from gramps.gui.selectors.selectperson import SelectPerson

            sel = SelectPerson(
                self.dbstate,
                self.uistate,
                track=[],
                title=_("Select Merge Target Person"),
            )
            handle = sel.run()
            if handle:
                self.target_handle = handle
                self._update_target_label()
                self._prefill_entries()
                self._refresh_action_buttons()
        except Exception as err:
            LOG.error("Failed to select target person: %s", err)

    def cb_set_target_none(self, _widget: Any = None) -> None:
        """
        Set target person to None so selected profile will be added as new.
        """
        self.target_handle = None
        self._update_target_label()
        self._refresh_action_buttons()

    def cb_entry_activate(self, _widget: Gtk.Entry) -> None:
        """
        Trigger search when pressing Enter in any search entry box.
        """
        self.cb_search()

    def cb_search(self, _widget: Any = None) -> None:
        """
        Execute search against NARA Catalog API and populate the results table.
        """
        query = self._search_query()
        start_year, end_year = self._record_years()
        limit = int(self.limit_spin.get_value())
        selected_mat = self.material_combo.get_active_id() or None
        online_only = self.online_check.get_active()

        if not query:
            self.status_label.set_text(
                _("Please check and fill in a name, keyword, or NAID to search.")
            )
            return

        self.status_label.set_text(_("Searching National Archives Catalog..."))
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        try:
            response = self.client.search_records(
                query=query,
                rows=limit,
                material_type=selected_mat,
                available_online=bool(online_only),
                start_year=start_year,
                end_year=end_year,
            )
            hits = self.client.extract_hits(response)
        except Exception as err:
            LOG.error("NARA search failed: %s", err)
            self.status_label.set_text(_("NARA search failed: %s") % str(err))
            return

        self._show_hits(hits, query)

    def _show_hits(self, hits: list[dict[str, Any]], query: str) -> None:
        """
        Fill the results table with NARA search hits and select the first.

        :param query: The query the hits came from, for the status message.
        """
        self.results_store.clear()
        self.btn_merge.set_sensitive(False)

        if not hits:
            self.status_label.set_text(
                _(
                    "No matching records found in the National Archives Catalog for '%s'. "
                    "Adjust your search terms and try again."
                )
                % query
            )
            return

        mergeable_count = 0
        match_query = self._match_query()
        for hit in hits:
            parsed = NaraCatalogInterface.parse_record(hit)
            people = parsed["person_creators"]
            mergeable_count += 1 if people else 0
            digital_str = _media_summary(parsed["digital_objects"])
            match = best_match(match_query, parsed)
            if people:
                person_text = "; ".join(people)
            elif match.candidate is not None:
                person_text = match.candidate.display()
            else:
                person_text = "-"

            self.results_store.append(
                [
                    parsed["naid"],
                    parsed["title"],
                    person_text,
                    self._with_level(
                        "; ".join(parsed["creators"]), parsed["creators_from"]
                    ),
                    self._with_level(parsed["date_str"], parsed["date_from"]),
                    parsed["material_type"] or "-",
                    digital_str,
                    hit,
                    bool(people),
                    match_text(match) if self._has_query(match_query) else "-",
                    match.score if self._has_query(match_query) else -1.0,
                ]
            )

        self.status_label.set_text(
            _(
                "Found %(found)d matching records in the National Archives "
                "Catalog; %(people)d name a person and can be merged."
            )
            % {"found": len(hits), "people": mergeable_count}
        )

        first_iter = self.results_store.get_iter_first()
        if first_iter:
            self.tree_view.get_selection().select_iter(first_iter)
            self._update_merge_button(self.results_store, first_iter)

    def cb_help(self, _widget: Any = None) -> None:
        """
        Display information explaining NARA search features and filters.
        """
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=_("National Archives (NARA) Search Help"),
        )
        help_text = _(
            "<b>Search Criteria:</b>\n"
            "• <b>Search terms:</b> Names, birth and death years and cities come from "
            "the target person, laid out as on the WikiTree dialog. Check or uncheck a "
            "term (or press Alt plus its underlined letter) to add it to or drop it "
            "from the search; First and Last start checked. <b>Reset</b> restores "
            "them.\n"
            "• <b>Keywords:</b> Other words such as pension, naturalization or a "
            "regiment, or a National Archives Identifier (NAID) on its own.\n"
            "• <b>Exact name:</b> Searches the given and last names as one phrase.\n"
            "• <b>Birth and Death Year:</b> Filter by the records' dates, not the "
            "person's: from the birth year, and up to the chosen number of years after "
            "the death year (ten by default).\n"
            "• <b>Birth and Death City:</b> Searched as words in the records.\n"
            "• <b>Material Type:</b> Narrow records to textual files, photographs, maps, etc.\n"
            "• <b>Online Only:</b> Restrict results to records with digitized online assets (images/documents).\n"
            "• Set the <b>NARA_API_KEY</b> environment variable before launching Gramps to authenticate with the catalog.\n\n"
            "<b>Attach to Person:</b>\n"
            "Select a record and click <b>Attach to Person</b> to review it: the left side "
            "shows the NARA citations the person already has, the right side this record's "
            "citation and images with their sizes and whether your tree already has them. "
            "Check the images you want (Preview downloads just one to look at) and click "
            "<b>Attach</b>: NARA becomes the repository, the record's series the source, "
            "and the record a citation with its catalog link. New images are saved under "
            "the NARA folder of your media base path (one folder per NAID) and linked to "
            "the citation. Images already in your tree are linked, never added twice.\n\n"
            "<b>Merging:</b>\n"
            "Most NARA records are created by agencies, so the Person column shows a dash "
            "and Merge is unavailable. For a record that names a person as its creator, "
            "click <b>Merge...</b> (or double-click the row) to open the side-by-side "
            "merge dialog."
        )
        dialog.format_secondary_markup(help_text)
        dialog.run()
        dialog.destroy()

    def _match_query(self) -> MatchQuery:
        """
        Return the details to score results against: the names and years in
        the search boxes (filled from the target person), checked or not.
        """

        def text(key: str) -> str:
            return str(self.term_entries[key].get_text()).strip()

        def year(key: str) -> int | None:
            value = text(key)
            return int(value) if len(value) == 4 and value.isdigit() else None

        surnames = [name for name in (text("last_name"), text("married_name")) if name]
        return MatchQuery(
            given=text("first_name"),
            middle=text("middle_name"),
            surnames=surnames,
            birth_year=year("birth_year"),
            death_year=year("death_year"),
        )

    @staticmethod
    def _has_query(query: MatchQuery) -> bool:
        """Return True when there is a name to match against."""
        return bool(query.given or query.surnames)

    @staticmethod
    def _with_level(text: str, level: str) -> str:
        """
        Return text for a results cell, noting the ancestor level (such as
        "series") it was taken from; '-' when there is no text.
        """
        if not text:
            return "-"
        if not level:
            return text
        return _("%(text)s (from %(level)s)") % {"text": text, "level": level}

    def _has_target(self) -> bool:
        """Return True when a target person is set and the tree is open."""
        return bool(self.target_handle and self.dbstate and self.dbstate.db)

    def _update_merge_button(self, model: Any, tree_iter: Any) -> None:
        """
        Enable Merge only for a record that names a person as its creator,
        and Attach to Person for any record when a target person is set; say
        why Merge is disabled.
        """
        mergeable = tree_iter is not None and bool(model.get_value(tree_iter, 8))
        self.btn_merge.set_sensitive(mergeable)
        self.btn_attach.set_sensitive(tree_iter is not None and self._has_target())
        if tree_iter is not None and not mergeable:
            if self._has_target():
                text = _(
                    "This record names no person as its creator, so it cannot "
                    "be merged as a person. Use Attach to Person to add it to "
                    "the target person as a source."
                )
            else:
                text = _(
                    "This record names no person as its creator, so it cannot "
                    "be merged as a person. Choose a target person to attach "
                    "it to instead."
                )
            self.status_label.set_text(text)

    def _refresh_action_buttons(self) -> None:
        """Update Merge and Attach to Person for the current selection."""
        model, tree_iter = self.tree_view.get_selection().get_selected()
        self._update_merge_button(model, tree_iter)

    def _page_details(
        self, person_handle: str, parsed: dict[str, Any]
    ) -> tuple[dict[int, str], dict[int, str]]:
        """
        Read the record's page text from NARA (one API call) and return a
        description ("<title>, page 3: Claim brief") and the text of each
        page, by image index. Both are empty when there is no text.
        """
        from gramps.gen.gwizard.gwizardnarapages import classify_pages
        from gramps.gui.gwizard.gwizardnaraattachdialog import (
            page_description,
            person_names,
        )

        objects = parsed.get("digital_objects") or []
        naid = str(parsed.get("naid") or "")
        if not objects or not naid or self.client is None:
            return {}, {}
        try:
            texts = self.client.fetch_record_text(naid)
        except Exception as err:
            LOG.warning("NARA page text for %s failed: %s", naid, err)
            texts = None
        if not texts:
            return {}, {}
        person = self.dbstate.db.get_person_from_handle(person_handle)
        infos = classify_pages(
            [str(item.get("filename") or "") for item in objects],
            [texts.get(str(item.get("object_id") or ""), "") for item in objects],
            person_names(person),
        )
        title = str(parsed.get("title") or naid)
        descriptions = {
            index: page_description(title, info) for index, info in enumerate(infos)
        }
        page_texts = {index: info.text for index, info in enumerate(infos)}
        return descriptions, page_texts

    def cb_attach(self, _widget: Any = None) -> None:
        """
        Open the GWizard merge window for the selected NARA record: the
        record (as an incoming copy of the target person, with its citation
        and images) on the left, the target person on the right. Arrows copy
        the citation and the chosen images; afterwards the new images can
        be downloaded.
        """
        model, tree_iter = self.tree_view.get_selection().get_selected()
        target = self.target_handle
        if tree_iter is None or not target or not self._has_target():
            return
        hit = model.get_value(tree_iter, 7)
        if not hit:
            return
        parsed = NaraCatalogInterface.parse_record(hit)

        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        self.status_label.set_text(_("Reading the record's pages from NARA..."))
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        descriptions, page_texts = self._page_details(target, parsed)

        gwizard = NaraGWizard(self.dbstate.db)
        try:
            source_handle = gwizard.load_for_person(
                target, parsed, descriptions, page_texts
            )
        except Exception as err:
            LOG.warning("Failed to load NARA record %s: %s", parsed.get("naid"), err)
            self.status_label.set_text(
                _("Could not review the NARA record: %s") % str(err)
            )
            return
        source_db = gwizard.context["source_db"]
        try:
            try:
                merge_dialog = GWizardMergeDialog(
                    self.dbstate,
                    gwizard,
                    source_handle,
                    target,
                    parent=self,
                    hidden_sections=ATTACH_HIDDEN_SECTIONS,
                    incoming_title=_("NARA Record: NAID %s") % parsed.get("naid", ""),
                )
            except Exception as err:
                LOG.warning("Failed to open the NARA merge window: %s", err)
                self.status_label.set_text(
                    _("Could not review the NARA record: %s") % str(err)
                )
                return
            merge_dialog.set_title(_("GWizard NARA Merge"))
            try:
                response = merge_dialog.run()
            finally:
                merge_dialog.destroy()
        finally:
            source_db.close()

        if response != Gtk.ResponseType.OK:
            self.status_label.set_text(_("Nothing was changed."))
            return
        self.status_label.set_text(self._finish_attach(target, parsed))

    def _finish_attach(self, person_handle: str, parsed: dict[str, Any]) -> str:
        """
        After the merge window copied a record over, offer to download the
        new images, link them to the record's citation, and return the
        status message.
        """
        attacher = NaraRecordAttacher(self.dbstate.db)
        images, online = attacher.merged_images(person_handle, parsed)
        download = bool(online) and self._ask_download(online)

        from gramps.gui.utils import ProgressMeter

        meter = None
        if download:
            meter = ProgressMeter(_("Attach NARA Record"), can_cancel=True, parent=self)
            meter.set_pass(
                _("Downloading %d images from NARA...") % len(online), len(online)
            )

        def progress(_done: int, _total: int) -> bool:
            if meter is None:
                return True
            meter.step()
            return not meter.get_cancelled()

        try:
            result = attacher.finish_merge(
                person_handle, parsed, download=download, progress=progress
            )
        except Exception as err:
            LOG.warning("Finishing NARA record %s failed: %s", parsed.get("naid"), err)
            return _(
                "The NARA record was merged, but its images could not be "
                "downloaded or linked to its citation: %s"
            ) % str(err)
        finally:
            if meter is not None:
                meter.close()
        return self._merge_summary(result, len(images), len(online), download)

    def _ask_download(self, online: list[Any]) -> bool:
        """Ask whether to download the images now linked by web address."""
        size = format_size(sum(image.size for image in online))
        question = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Download the NARA images?"),
        )
        question.format_secondary_text(
            _(
                "%(count)d images from this record are linked by their web "
                "address (%(size)s). Download them into your media folder now? "
                "Otherwise they stay linked to NARA's web site."
            )
            % {"count": len(online), "size": size or _("size unknown")}
        )
        try:
            return question.run() == Gtk.ResponseType.YES
        finally:
            question.destroy()

    @staticmethod
    def _merge_summary(
        result: AttachResult, images: int, online: int, download: bool
    ) -> str:
        """Return the status message after merging a record."""
        parts = [
            _("The NARA record was merged; this person has %d of its images.") % images
        ]
        if result.downloaded or result.already_downloaded:
            parts.append(
                _("Images downloaded: %(new)d (already there: %(old)d).")
                % {"new": result.downloaded, "old": result.already_downloaded}
            )
        if online and not download:
            parts.append(_("%d images are linked by their web address.") % online)
        if result.failed:
            parts.append(
                _(
                    "%d images could not be downloaded and are linked by their "
                    "web address instead."
                )
                % len(result.failed)
            )
        if result.cancelled:
            parts.append(_("Downloading was cancelled; the rest were skipped."))
        return " ".join(parts)

    def cb_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        """
        Enable or disable the Merge button based on table row selection.
        """
        model, tree_iter = selection.get_selected()
        self._update_merge_button(model, tree_iter)

    def cb_row_activated(self, _tree: Any, _path: Any, _col: Any) -> None:
        """
        Handle double-clicking a row to trigger merge directly.
        """
        if self.btn_merge.get_sensitive():
            self.cb_merge()
        elif self.btn_attach.get_sensitive():
            self.cb_attach()

    def cb_merge(self, _widget: Any = None) -> None:
        """
        Load the selected NARA record and launch the GWizardMergeDialog.
        """
        selection = self.tree_view.get_selection()
        model, tree_iter = selection.get_selected()
        if not tree_iter:
            return

        naid = model.get_value(tree_iter, 0)
        hit = model.get_value(tree_iter, 7)
        if not hit:
            return

        self.status_label.set_text(
            _("Loading details for NAID '%s' from NARA...") % naid
        )
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        from gramps.gen.gwizard.gwizardnaramerge import NaraGWizard

        db = self.dbstate.db if self.dbstate else None
        if not db:
            self.status_label.set_text(_("No open database available for merge."))
            return

        try:
            gwizard = NaraGWizard(db)
            if not gwizard.run_step(
                "connect",
                query=naid,
                api_key=self.api_key,
                hits=[hit],
                client=self.client,
            ):
                self.status_label.set_text(_("Could not configure connection to NARA."))
                return
            gwizard.run_step("load")
        except Exception as err:
            LOG.warning("Failed to load records from NARA for NAID %s: %s", naid, err)
            self.status_label.set_text(
                _("Failed to load records from NARA: %s") % str(err)
            )
            return

        source_db = gwizard.context.get("source_db")
        if not source_db or source_db.get_number_of_people() == 0:
            self.status_label.set_text(
                _("No person data found in NARA record for NAID '%s'.") % naid
            )
            return

        # Find source person handle
        source_handle: str | None = None
        for h in source_db.iter_person_handles():
            source_handle = h
            break

        if not source_handle:
            self.status_label.set_text(
                _("Could not resolve source person for NAID '%s'.") % naid
            )
            return

        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        merge_dialog = GWizardMergeDialog(
            self.dbstate,
            gwizard,
            source_handle,
            self.target_handle,
            parent=self,
        )
        try:
            response = merge_dialog.run()
        finally:
            merge_dialog.destroy()

        if response == Gtk.ResponseType.OK:
            target_name = ""
            if self.target_handle and self.dbstate and self.dbstate.db:
                tp = self.dbstate.db.get_person_from_handle(self.target_handle)
                if tp:
                    target_name = tp.get_primary_name().get_name()
                    self._prefill_entries()
            if target_name:
                self.status_label.set_text(
                    _("Successfully merged NAID '%(naid)s' into '%(target)s'.")
                    % {"naid": naid, "target": target_name}
                )
            else:
                self.status_label.set_text(
                    _("Successfully imported NAID '%s' as a new person.") % naid
                )

    def get_query_parameters(self) -> dict[str, Any]:
        """
        Retrieve user-entered parameters from the dialog fields.

        :returns: Parameter dictionary for NaraGWizard.
        :rtype: dict[str, Any]
        """
        query = self._search_query()
        start_year, end_year = self._record_years()
        limit = int(self.limit_spin.get_value())
        selected_mat = self.material_combo.get_active_id() or None
        online_only = self.online_check.get_active()

        params: dict[str, Any] = {
            "query": query,
            "limit": limit,
        }
        if start_year:
            params["start_year"] = start_year
        if end_year:
            params["end_year"] = end_year
        if selected_mat:
            params["material_type"] = selected_mat
        if online_only:
            params["available_online"] = True
        return params


# ------------------------------------------------------------
#
# Launcher functions
#
# ------------------------------------------------------------
def _get_nara_api_key() -> str:
    """Return the NARA API key configured in the process environment."""
    return os.environ.get("NARA_API_KEY", "").strip()


def _show_nara_api_error(parent: Any, message: str) -> None:
    """Display an API key configuration or validation error."""
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.OK,
        text=_("Unable to validate NARA API key"),
    )
    dialog.format_secondary_text(message)
    dialog.run()
    dialog.destroy()


def open_nara_record(
    uistate: Any,
    dbstate: Any,
    person_handle: str,
    hit: dict[str, Any],
    parent: Any = None,
    client: Any = None,
) -> bool:
    """
    Open the NARA window for a person with one record already listed and
    selected, and go straight to its Attach to Person review (the merge
    window with the record on the left and the person on the right). The
    NARA window stays open afterwards, so Merge is still there for a record
    that names a person as its creator. Used by the GWizard Record Scan.

    :param hit: The record as the NARA search returned it.
    :returns: True (the person may have changed).
    """
    dialog = NaraSearchDialog(
        uistate=uistate,
        dbstate=dbstate,
        target_handle=person_handle,
        parent=parent,
        client=client,
    )
    parsed = NaraCatalogInterface.parse_record(hit)
    dialog._show_hits([hit], str(parsed.get("naid") or ""))

    def cb_open() -> bool:
        if dialog.btn_attach.get_sensitive():
            dialog.cb_attach()
        return False

    GLib.idle_add(cb_open)
    try:
        dialog.run()
    finally:
        dialog.destroy()
    return True


def ask_nara_parameters(parent: Any, default_query: str = "") -> dict[str, Any] | None:
    """
    Prompt the user with the NARA search dialog.

    :param parent: Parent window.
    :param default_query: Default search query string.
    :returns: Parameter dictionary if accepted, None if canceled.
    """
    dialog = NaraSearchDialog(parent=parent, default_query=default_query)
    response = dialog.run()
    params = (
        dialog.get_query_parameters()
        if response in (Gtk.ResponseType.OK, Gtk.ResponseType.APPLY)
        else None
    )
    dialog.destroy()
    return params


def load_nara_gwizard(db: Any, params: dict[str, Any]) -> Any:
    """
    Initialize and run connect and load steps for NaraGWizard.

    :param db: Active Gramps target database.
    :param params: Dictionary of parameters from NaraSearchDialog.
    :returns: Loaded NaraGWizard instance.
    :raises ValueError: If query is missing or connection fails.
    :raises RuntimeError: If loading/parsing records fails.
    """
    from gramps.gen.gwizard.gwizardnaramerge import NaraGWizard

    query = params.get("query", "").strip()
    if not query:
        raise ValueError(str(_("Search query cannot be empty.")))

    gwizard = NaraGWizard(db)
    if not gwizard.run_step("connect", **params):
        raise ValueError(str(_("Could not configure connection to NARA.")))

    try:
        gwizard.run_step("load")
    except Exception as error:
        LOG.error("Failed to load records from NARA: %s", error)
        raise RuntimeError(str(error)) from error

    return gwizard


def run_gwizard_nara_flow(uistate: Any, dbstate: Any, parent: Any = None) -> bool:
    """
    Run the full GWizard NARA merge flow:
    prompt for search terms, query NARA, display potential matches in table,
    and open field merge dialog for selected record.

    :param uistate: Active Gramps UI state manager.
    :param dbstate: Active Gramps database state manager.
    :param parent: Optional parent GTK window.
    :returns: True if the dialog completed.
    """
    if parent is None:
        try:
            parent = uistate.window
        except Exception:
            parent = None

    api_key = _get_nara_api_key()
    if not api_key:
        _show_nara_api_error(
            parent,
            _(
                "Set the NARA_API_KEY environment variable and restart Gramps "
                "before opening the NARA Merge tool."
            ),
        )
        return False

    client = NaraCatalogInterface(api_key=api_key)
    error = client.validate_api_key()
    if error:
        _show_nara_api_error(parent, error)
        return False

    active_handle = None
    try:
        active_handle = uistate.get_active("Person")
    except Exception:
        active_handle = None

    dialog = NaraSearchDialog(
        uistate=uistate,
        dbstate=dbstate,
        target_handle=active_handle,
        parent=parent,
        client=client,
    )
    try:
        dialog.run()
    finally:
        dialog.destroy()

    return True
