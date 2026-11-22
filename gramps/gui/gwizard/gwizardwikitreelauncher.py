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
Launcher and search dialog for the GWizard WikiTree Merge flow.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
from typing import Any, Callable

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
from gramps.gen.lib import NameType, Person
from gramps.gen.gwizard.gwizardwikitree import (
    WikiTreeGWizard,
    WikiTreeInterface,
    extract_wikitree_id,
    get_wikitree_id,
)
from gramps.gen.gwizard.gwizardwikitreematch import (
    MatchQuery,
    match_text,
    score_profile,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# Response id of the Merge button (a non-closing action button).
RESPONSE_MERGE = 1

# Gramps gender codes and the values WikiTree's searchPerson accepts.
_WIKITREE_GENDERS: dict[int, str] = {Person.MALE: "Male", Person.FEMALE: "Female"}

# Search terms that start checked. First name, last name and birth year are
# the most effective WikiTree search terms; the others are filled in from the
# target person but left out until checked. A WikiTree ID, when known, is an
# exact lookup and stays checked.
SEARCH_TERM_DEFAULTS: dict[str, bool] = {
    "first_name": True,
    "middle_name": False,
    "last_name": True,
    "married_name": False,
    "gender": False,
    "birth_year": True,
    "birth_location": False,
    "death_year": False,
    "death_location": False,
    "wt_id": True,
}


# ------------------------------------------------------------
#
# Helper functions
#
# ------------------------------------------------------------
def _extract_person_search_defaults(db: Any, person: Any) -> dict[str, str]:
    """
    Extract default search values (names, dates, WikiTree ID) from a Person.

    The first word of the Gramps given name is returned as 'first_name' and
    any further words as 'middle_name', so the dialog can search on the
    first given name alone.

    :param db: Active Gramps database.
    :param person: Gramps Person object.
    'married_name' comes from a Married Name alternate name, or failing that
    (for women only) from the husband's surname in the most recent family.

    :returns: Dictionary with keys 'first_name', 'middle_name', 'last_name',
        'birth_year', 'death_year', 'wt_id', 'gender', 'birth_location',
        'death_location', 'married_name'.
    """
    defaults = {
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "birth_year": "",
        "death_year": "",
        "wt_id": "",
        "gender": "",
        "birth_location": "",
        "death_location": "",
        "married_name": "",
    }
    if not person:
        return defaults

    pname = person.get_primary_name()
    if pname:
        given_names = str(pname.get_first_name() or "").split()
        if given_names:
            defaults["first_name"] = given_names[0]
            defaults["middle_name"] = " ".join(given_names[1:])
        defaults["last_name"] = str(surname_text(pname) or "").strip()

    # Look for existing WikiTree ID in attributes or Internet URLs
    defaults["wt_id"] = get_wikitree_id(person)

    # Birth year
    bref = person.get_birth_ref()
    if bref and db:
        bevt = db.get_event_from_handle(bref.ref)
        if bevt:
            bdate = bevt.get_date_object()
            if bdate and bdate.get_year() > 0:
                defaults["birth_year"] = str(bdate.get_year())

    # Death year
    dref = person.get_death_ref()
    if dref and db:
        devt = db.get_event_from_handle(dref.ref)
        if devt:
            ddate = devt.get_date_object()
            if ddate and ddate.get_year() > 0:
                defaults["death_year"] = str(ddate.get_year())
            dplace = devt.get_place_handle()
            if dplace and db:
                dplace_obj = db.get_place_from_handle(dplace)
                if dplace_obj:
                    defaults["death_location"] = str(
                        dplace_obj.get_name().get_value() or ""
                    ).strip()

    # Gender, as WikiTree spells it (Male or Female); unknown is left blank.
    defaults["gender"] = _WIKITREE_GENDERS.get(person.get_gender(), "")

    # Birth location
    bref = person.get_birth_ref()
    if bref and db:
        bevt = db.get_event_from_handle(bref.ref)
        if bevt:
            bplace = bevt.get_place_handle()
            if bplace and db:
                bplace_obj = db.get_place_from_handle(bplace)
                if bplace_obj:
                    defaults["birth_location"] = str(
                        bplace_obj.get_name().get_value() or ""
                    ).strip()

    defaults["married_name"] = _married_surname(db, person)

    return defaults


def _married_surname(db: Any, person: Any) -> str:
    """
    Return the person's married surname, or '' when none is known.

    A Married Name alternate name wins. Otherwise, for a woman, the husband's
    surname from her most recent family (the last in her family list) is
    used; this is a guess, so the dialog leaves the term unchecked.
    """
    for alt_name in person.get_alternate_names():
        if int(alt_name.get_type()) == NameType.MARRIED:
            married = surname_text(alt_name).strip()
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
            married = surname_text(husband.get_primary_name()).strip()
            if married:
                return married
    return ""


# ------------------------------------------------------------
#
# WikiTreeSearchDialog
#
# ------------------------------------------------------------
class WikiTreeSearchDialog(Gtk.Dialog):
    """
    Search and merge dialog querying WikiTree profiles with tabular results,
    allowing users to review matches and launch the side-by-side merge dialog.
    """

    def __init__(
        self,
        uistate: Any = None,
        dbstate: Any = None,
        target_handle: str | None = None,
        parent: Any = None,
        default_query: str = "",
        default_ancestors: int = 0,
        default_app_id: str = WikiTreeInterface.DEFAULT_APP_ID,
        client: Any = None,
    ) -> None:
        """
        Initialize the WikiTree search and merge dialog.

        :param uistate: Gramps UI state manager.
        :param dbstate: Gramps database state manager.
        :param target_handle: Handle of the target Gramps Person to merge into.
        :param parent: Parent GTK window for transient placement.
        :param default_query: Optional pre-filled search query or WikiTree ID.
        :param default_ancestors: Default ancestor generations count.
        :param default_app_id: App ID passed to WikiTree API.
        :param client: Optional WikiTreeInterface client for testing.
        """
        super().__init__(
            title=str(_("GWizard WikiTree Merge")),
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(950, 600)
        self.set_resizable(True)

        self.uistate = uistate
        self.dbstate = dbstate
        self.target_handle = target_handle
        self.ancestors = default_ancestors
        self.app_id = default_app_id.strip() or WikiTreeInterface.DEFAULT_APP_ID
        self.client = client or WikiTreeInterface(app_id=self.app_id)

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

        content.pack_start(header_box, False, False, 0)
        self._update_target_label()

        # -----------------------------------------------------------------
        # 2. Horizontal Search Criteria Grid
        # -----------------------------------------------------------------
        # Each search term has a check button above its entry. An unchecked
        # term keeps its text but is left out of the search, so terms can be
        # added or dropped with one click, or with Alt plus the underlined
        # letter, instead of retyping them.
        search_grid = Gtk.Grid()
        search_grid.set_column_spacing(8)
        search_grid.set_row_spacing(4)

        self.term_checks: dict[str, Any] = {}
        self.term_entries: dict[str, Any] = {}
        for column, (key, label, placeholder, tooltip, width) in enumerate(
            self._term_specs()
        ):
            check = Gtk.CheckButton(label=label, use_underline=True)
            check.set_tooltip_text(
                _(
                    "Include this term in the search. Unchecked terms are "
                    "kept but ignored."
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
        self.gender_entry = self.term_entries["gender"]
        self.birth_year_entry = self.term_entries["birth_year"]
        self.birth_location_entry = self.term_entries["birth_location"]
        self.death_year_entry = self.term_entries["death_year"]
        self.death_location_entry = self.term_entries["death_location"]
        self.wt_id_entry = self.term_entries["wt_id"]

        # Search options, in a third row under the name and date columns.
        # Each one is left out of the request at its default ("WikiTree
        # default", unchecked or 0), so WikiTree's own defaults apply.
        term_keys = [key for key, *_rest in self._term_specs()]

        # Surname options: which last name to match, and spelling variants.
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        match_label = Gtk.Label(label=_("Last name matc_h:"), use_underline=True)
        self.last_name_match_combo = Gtk.ComboBoxText()
        for match_id, match_text in self._last_name_match_options():
            self.last_name_match_combo.append(match_id, match_text)
        self.last_name_match_combo.set_active_id("")
        self.last_name_match_combo.set_tooltip_text(
            _(
                "Which WikiTree last name to match: the last name at birth, the "
                "current (often married) last name, or either."
            )
        )
        match_label.set_mnemonic_widget(self.last_name_match_combo)
        self.skip_variants_check = Gtk.CheckButton(
            label=_("_Exact spelling only"), use_underline=True
        )
        self.skip_variants_check.set_tooltip_text(
            _(
                "Match only the exact surname, skipping spelling variants "
                "(for example Smith but not Smyth)."
            )
        )
        name_box.pack_start(match_label, False, False, 0)
        name_box.pack_start(self.last_name_match_combo, False, False, 0)
        name_box.pack_start(self.skip_variants_check, False, False, 0)
        search_grid.attach(name_box, 0, 2, term_keys.index("birth_year"), 1)

        # Date options: spread of years, and profiles without dates.
        date_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        spread_label = Gtk.Label(label=_("Date s_pread (years):"), use_underline=True)
        self.date_spread_spin = Gtk.SpinButton.new_with_range(
            0, WikiTreeInterface.MAX_DATE_SPREAD, 1
        )
        self.date_spread_spin.set_value(0)
        self.date_spread_spin.set_tooltip_text(
            _(
                "How many years WikiTree may allow around the birth and death "
                "years when matching (1-20). 0 uses WikiTree's default."
            )
        )
        self.date_spread_spin.connect("activate", self.cb_entry_activate)
        spread_label.set_mnemonic_widget(self.date_spread_spin)
        include_label = Gtk.Label(label=_("Und_ated profiles:"), use_underline=True)
        self.date_include_combo = Gtk.ComboBoxText()
        for include_id, include_text in self._date_include_options():
            self.date_include_combo.append(include_id, include_text)
        self.date_include_combo.set_active_id("")
        self.date_include_combo.set_tooltip_text(
            _(
                "Whether profiles with no birth or death date may match a "
                "search that includes dates."
            )
        )
        include_label.set_mnemonic_widget(self.date_include_combo)
        date_box.pack_start(spread_label, False, False, 0)
        date_box.pack_start(self.date_spread_spin, False, False, 0)
        date_box.pack_start(include_label, False, False, 0)
        date_box.pack_start(self.date_include_combo, False, False, 0)
        date_column = term_keys.index("birth_year")
        search_grid.attach(date_box, date_column, 2, len(term_keys) - date_column, 1)

        # Reset and Search Buttons
        button_column = len(self.term_entries)
        self.btn_reset = Gtk.Button(label=_("_Reset"), use_underline=True)
        self.btn_reset.set_tooltip_text(
            _(
                "Restore the search terms taken from the target person and "
                "the default selection (first name, last name, birth year)."
            )
        )
        self.btn_reset.connect("clicked", self.cb_reset_terms)
        search_grid.attach(self.btn_reset, button_column, 1, 1, 1)

        self.btn_search = Gtk.Button(label=_("_Search"), use_underline=True)
        self.btn_search.get_style_context().add_class("suggested-action")
        self.btn_search.set_tooltip_text(
            _("Search WikiTree using the checked terms above.")
        )
        self.btn_search.connect("clicked", self.cb_search)
        search_grid.attach(self.btn_search, button_column + 1, 1, 1, 1)

        content.pack_start(search_grid, False, False, 0)

        # -----------------------------------------------------------------
        # 3. Status Message
        # -----------------------------------------------------------------
        self.status_label = Gtk.Label()
        self.status_label.set_xalign(0.0)
        self.status_label.set_line_wrap(True)
        self.status_label.set_text(
            _(
                "Check the terms to search on and click Search, or look up by "
                "WikiTree ID. Alt plus an underlined letter checks or unchecks "
                "a term."
            )
        )
        content.pack_start(self.status_label, False, False, 0)

        # -----------------------------------------------------------------
        # 4. Results Table
        # -----------------------------------------------------------------
        # Model columns:
        # 0: WikiTree ID (str)
        # 1: Full Name (str)
        # 2: Gender (str)
        # 3: Birth Date (str)
        # 4: Birth Location (str)
        # 5: Death Date (str)
        # 6: Death Location (str)
        # 7: Parents (str)
        # 8: Raw match data (object)
        # 9: Match (str), such as "92%" or "92% (name only)"
        # 10: Match score (float), for sorting the Match column
        self.results_store = Gtk.ListStore(
            str, str, str, str, str, str, str, str, object, str, float
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
        # Every action button is added with add_button() and a response id,
        # never packed by hand, so GTK places them in the platform's order
        # (gtk-alternative-button-order). Merge keeps the window open;
        # cb_response handles it.
        self.add_button(_("_Close"), Gtk.ResponseType.CLOSE)

        self.btn_merge = self.add_button(_("_Merge..."), RESPONSE_MERGE)
        self.btn_merge.get_style_context().add_class("suggested-action")
        self.btn_merge.set_tooltip_text(
            _("Open the field-by-field merge dialog for the selected WikiTree profile.")
        )
        self.btn_merge.set_sensitive(False)
        self.connect("response", self.cb_response)

        # Pre-populate search entries from target person or default query
        self.default_query = default_query
        self._prefill_entries(default_query=default_query)
        self._apply_default_terms()

        self.show_all()

    @staticmethod
    def _term_specs() -> list[tuple[str, str, str, str, int]]:
        """
        Return (key, check label, placeholder, entry tooltip, width) for each
        search term, in column order. A width of 0 lets the entry expand.

        The underlined letters must not clash with each other, with the
        search option labels (matc_h, _Exact, s_pread, Und_ated), or with
        the _Search, _Reset, _Merge and _Close buttons.
        """
        return [
            (
                "first_name",
                _("_First Name"),
                _("Given name"),
                _("First given name (supports wildcards * and ?)."),
                0,
            ),
            (
                "middle_name",
                _("M_iddle Name"),
                _("Other given names"),
                _(
                    "Other given names. When checked, they are searched "
                    "together with the first name."
                ),
                10,
            ),
            (
                "last_name",
                _("_Last Name"),
                _("Surname"),
                _("Surname at birth or current surname (supports wildcards * and ?)."),
                0,
            ),
            (
                "married_name",
                _("Married _Name"),
                _("Current surname"),
                _(
                    "Married or other current surname, searched as WikiTree's "
                    "current last name. Filled from a Married Name alternate "
                    "name, or for a woman from her husband's surname."
                ),
                14,
            ),
            (
                "gender",
                _("_Gender"),
                _("Male or Female"),
                _("Filter by gender: Male or Female."),
                10,
            ),
            (
                "birth_year",
                _("_Birth Year"),
                _("YYYY or YYYY-MM-DD"),
                _("Birth year (4 digits) or full date (YYYY-MM-DD)."),
                10,
            ),
            (
                "birth_location",
                _("Birth L_ocation"),
                _("Place"),
                _("Filter by birth place (supports wildcards * and ?)."),
                16,
            ),
            (
                "death_year",
                _("_Death Year"),
                _("YYYY or YYYY-MM-DD"),
                _("Death year (4 digits) or full date (YYYY-MM-DD)."),
                10,
            ),
            (
                "death_location",
                _("Death Loca_tion"),
                _("Place"),
                _("Filter by death place (supports wildcards * and ?)."),
                16,
            ),
            (
                "wt_id",
                _("_WikiTree ID"),
                _("Surname-number"),
                _("Exact WikiTree ID for direct lookup (e.g. 'Franklin-1')."),
                16,
            ),
        ]

    @staticmethod
    def _last_name_match_options() -> list[tuple[str, str]]:
        """
        Return (lastNameMatch value, label) choices; '' means not sent.

        WikiTree also accepts 'strict', which it does not document, so it is
        not offered.
        """
        return [
            ("", _("WikiTree default")),
            ("all", _("Birth or current")),
            ("birth", _("Birth name only")),
            ("current", _("Current name only")),
        ]

    @staticmethod
    def _date_include_options() -> list[tuple[str, str]]:
        """
        Return (dateInclude value, label) choices; '' means not sent.
        """
        return [
            ("", _("WikiTree default")),
            ("neither", _("Include")),
            ("both", _("Leave out")),
        ]

    def _search_options(self) -> dict[str, Any]:
        """
        Return the extra searchPerson options that are set, keyed by their
        WikiTree parameter names. Options at their default are left out.
        """
        options: dict[str, Any] = {}
        married = self._term_value("married_name")
        if married:
            options["LastNameCurrent"] = married
        match = self.last_name_match_combo.get_active_id()
        if match:
            options["lastNameMatch"] = str(match)
        if self.skip_variants_check.get_active():
            options["skipVariants"] = 1
        include = self.date_include_combo.get_active_id()
        if include:
            options["dateInclude"] = str(include)
        return options

    def _apply_default_terms(self) -> None:
        """
        Check the default search terms and uncheck the rest.
        """
        for key, check in self.term_checks.items():
            check.set_active(SEARCH_TERM_DEFAULTS.get(key, False))
            self._sync_term_entry(key)

    def _sync_term_entry(self, key: str) -> None:
        """
        Make a term's entry editable only while its check button is checked.
        """
        self.term_entries[key].set_sensitive(bool(self.term_checks[key].get_active()))

    def _term_value(self, key: str) -> str:
        """
        Return a term's text, or '' when the term is unchecked.
        """
        if not self.term_checks[key].get_active():
            return ""
        return str(self.term_entries[key].get_text()).strip()

    def _match_query(self) -> MatchQuery:
        """
        Return the details to score results against: the names, years and
        gender in the search boxes (filled from the target person), checked
        or not.
        """

        def text(key: str) -> str:
            return str(self.term_entries[key].get_text()).strip()

        def year(key: str) -> int | None:
            value = text(key)[:4]
            return int(value) if len(value) == 4 and value.isdigit() else None

        surnames = [name for name in (text("last_name"), text("married_name")) if name]
        return MatchQuery(
            given=text("first_name"),
            middle=text("middle_name"),
            surnames=surnames,
            birth_year=year("birth_year"),
            death_year=year("death_year"),
            gender=text("gender"),
        )

    def _date_spread(self) -> int:
        """
        Return the date spread to search with, or 0 when none is set.
        """
        return max(0, int(self.date_spread_spin.get_value_as_int()))

    def _search_first_name(self) -> str:
        """
        Return the given names to search on: the first name, followed by the
        middle name when that term is checked.
        """
        parts = [self._term_value("first_name"), self._term_value("middle_name")]
        return " ".join(part for part in parts if part)

    def cb_term_toggled(self, _check: Gtk.CheckButton, key: str) -> None:
        """
        Enable or disable a term's entry when its check button is toggled.
        """
        self._sync_term_entry(key)

    def cb_reset_terms(self, _widget: Any = None) -> None:
        """
        Restore the starting search values, the default term selection and
        the default search options.
        """
        for entry in self.term_entries.values():
            entry.set_text("")
        self._prefill_entries(default_query=self.default_query)
        self._apply_default_terms()
        self.date_spread_spin.set_value(0)
        self.date_include_combo.set_active_id("")
        self.last_name_match_combo.set_active_id("")
        self.skip_variants_check.set_active(False)

    def _build_tree_columns(self) -> None:
        """
        Create and append column headers for the search results treeview.
        """
        cols = [
            (_("WikiTree ID"), 0, False),
            (_("Name"), 1, True),
            (_("Match"), 9, False),
            (_("Gender"), 2, False),
            (_("Birth Date"), 3, False),
            (_("Birth Location"), 4, True),
            (_("Death Date"), 5, False),
            (_("Death Location"), 6, True),
            (_("Parents"), 7, True),
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
            self.first_name_entry.set_text(defaults["first_name"])
            self.middle_name_entry.set_text(defaults["middle_name"])
            self.last_name_entry.set_text(defaults["last_name"])
            self.married_name_entry.set_text(defaults["married_name"])
            self.birth_year_entry.set_text(defaults["birth_year"])
            self.death_year_entry.set_text(defaults["death_year"])
            self.wt_id_entry.set_text(defaults["wt_id"])
            self.gender_entry.set_text(defaults["gender"])
            self.birth_location_entry.set_text(defaults["birth_location"])
            self.death_location_entry.set_text(defaults["death_location"])
        elif default_query:
            query = default_query.strip()
            extracted_id = extract_wikitree_id(query)
            if extracted_id:
                self.wt_id_entry.set_text(extracted_id)
            else:
                fn, ln = WikiTreeGWizard._parse_query_names(query)
                self.first_name_entry.set_text(fn)
                self.last_name_entry.set_text(ln)

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
                        _("Merge WikiTree data into: <b>%(name)s</b> (%(id)s)")
                        % {"name": GLib.markup_escape_text(name), "id": gid}
                    )
                    return
            except Exception as err:
                LOG.warning(
                    "Could not resolve target person %s: %s", self.target_handle, err
                )

        self.target_label.set_markup(
            _("Merge WikiTree data into: <i>None (will add as a new person)</i>")
        )

    def cb_entry_activate(self, _widget: Gtk.Entry) -> None:
        """
        Trigger search when pressing Enter in any search entry box.
        """
        self.cb_search()

    def cb_search(self, _widget: Any = None) -> None:
        """
        Execute search against WikiTree and populate the results table.

        Only checked terms are used.
        """
        first_name = self._search_first_name()
        last_name = self._term_value("last_name")
        birth_year = self._term_value("birth_year")
        death_year = self._term_value("death_year")
        wt_id = self._term_value("wt_id")
        gender = self._term_value("gender")
        birth_location = self._term_value("birth_location")
        death_location = self._term_value("death_location")
        date_spread = self._date_spread()
        married_name = self._term_value("married_name")
        extracted_wt = extract_wikitree_id(wt_id)
        if extracted_wt:
            wt_id = extracted_wt

        # Handle user typing WikiTree ID into first or last name field
        if not wt_id:
            extracted_ln = extract_wikitree_id(last_name)
            if extracted_ln:
                wt_id = extracted_ln
                last_name = ""
            else:
                extracted_fn = extract_wikitree_id(first_name)
                if extracted_fn:
                    wt_id = extracted_fn
                    first_name = ""

        if not (
            first_name
            or last_name
            or married_name
            or birth_year
            or death_year
            or wt_id
            or gender
            or birth_location
            or death_location
        ):
            self.status_label.set_text(
                _("Please check and fill in a name, year, or WikiTree ID to search.")
            )
            return

        self.status_label.set_text(_("Searching WikiTree..."))
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        matches: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        try:
            # 1. Direct ID lookup if WikiTree ID was provided
            if wt_id:
                pdata = self.client.get_person(wt_id)
                if pdata:
                    matches.append(pdata)
                    p_name = str(pdata.get("Name") or "")
                    if p_name:
                        seen_ids.add(p_name)

            # 2. Search by name, dates, gender, and locations if provided
            if (
                first_name
                or last_name
                or married_name
                or birth_year
                or death_year
                or gender
                or birth_location
                or death_location
            ):
                search_matches = self.client.search_person(
                    first_name=first_name,
                    last_name=last_name,
                    birth_date=birth_year,
                    death_date=death_year,
                    Gender=gender,
                    BirthLocation=birth_location,
                    DeathLocation=death_location,
                    date_spread=date_spread,
                    limit=WikiTreeInterface.MAX_SEARCH_LIMIT,
                    **self._search_options(),
                )
                for item in search_matches:
                    m_id = str(item.get("Name") or "")
                    if not m_id or m_id not in seen_ids:
                        matches.append(item)
                        if m_id:
                            seen_ids.add(m_id)
        except Exception as err:
            LOG.error("WikiTree search failed: %s", err)
            self.status_label.set_text(_("WikiTree search failed: %s") % str(err))
            return

        self.results_store.clear()
        self.btn_merge.set_sensitive(False)

        if not matches:
            self.status_label.set_text(
                _(
                    "No matching profiles found on WikiTree. "
                    "Adjust your search terms or use wildcards (*) and try again."
                )
            )
            return

        match_query = self._match_query()
        for match in matches:
            item_wt_id = str(match.get("Name") or match.get("Id") or "")
            item_name = (
                match.get("LongName")
                or match.get("ShortName")
                or f"{match.get('FirstName', '')} {match.get('LastNameCurrent', '')}".strip()
            )
            item_gender = str(match.get("Gender") or "")
            item_bdate = WikiTreeGWizard._clean_date_str(
                str(match.get("BirthDate") or "")
            )
            item_bplace = str(match.get("BirthLocation") or "").strip()
            item_ddate = WikiTreeGWizard._clean_date_str(
                str(match.get("DeathDate") or "")
            )
            item_dplace = str(match.get("DeathLocation") or "").strip()

            parents_dict = match.get("Parents")
            parent_names: list[str] = []
            if isinstance(parents_dict, dict):
                for p in parents_dict.values():
                    if isinstance(p, dict):
                        pname = p.get("ShortName") or p.get("LongName") or p.get("Name")
                        if pname:
                            parent_names.append(str(pname))
            parents_str = ", ".join(parent_names)
            if match_query.has_name():
                result = score_profile(match_query, match)
                item_match, item_score = match_text(result), result.score
            else:
                item_match, item_score = "-", 0.0

            self.results_store.append(
                [
                    item_wt_id,
                    item_name,
                    item_gender,
                    item_bdate,
                    item_bplace,
                    item_ddate,
                    item_dplace,
                    parents_str,
                    match,
                    item_match,
                    item_score,
                ]
            )

        self.status_label.set_text(
            _(
                "Found %d matching profiles on WikiTree. Select a profile and click Merge."
            )
            % len(matches)
        )

        first_iter = self.results_store.get_iter_first()
        if first_iter:
            self.tree_view.get_selection().select_iter(first_iter)
            self.btn_merge.set_sensitive(True)

    def cb_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        """
        Enable or disable the Merge button based on table row selection.
        """
        model, tree_iter = selection.get_selected()
        self.btn_merge.set_sensitive(tree_iter is not None)

    def cb_response(self, _dialog: Any, response: int) -> None:
        """
        Run Merge without closing the window (Gtk.Dialog.run() returns on
        any other response).
        """
        if response == RESPONSE_MERGE:
            self.stop_emission_by_name("response")
            self.cb_merge()

    def cb_row_activated(self, _tree: Any, _path: Any, _col: Any) -> None:
        """
        Handle double-clicking a row to trigger merge directly.
        """
        if self.btn_merge.get_sensitive():
            self.cb_merge()

    def cb_merge(self, _widget: Any = None) -> None:
        """
        Load the selected WikiTree profile and launch the WikiTreeMergeDialog.
        """
        selection = self.tree_view.get_selection()
        model, tree_iter = selection.get_selected()
        if not tree_iter:
            return

        wt_id = model.get_value(tree_iter, 0)
        if not wt_id:
            return

        merged, message = merge_wikitree_profile(
            self.dbstate,
            wt_id,
            self.target_handle,
            parent=self,
            client=self.client,
            app_id=self.app_id,
            status=self._show_status,
        )
        if merged and self.target_handle:
            self._prefill_entries()
        if message:
            self.status_label.set_text(message)

    def _show_status(self, text: str) -> None:
        """Show a progress message right away."""
        self.status_label.set_text(text)
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

    def get_query_parameters(self) -> dict[str, Any]:
        """
        Retrieve the checked search terms from the dialog fields.

        :returns: Parameter dictionary for WikiTreeGWizard.
        :rtype: dict[str, Any]
        """
        first_name = self._search_first_name()
        last_name = self._term_value("last_name")
        birth_year = self._term_value("birth_year")
        death_year = self._term_value("death_year")
        wt_id = self._term_value("wt_id")

        query = wt_id or f"{first_name} {last_name}".strip()

        return {
            "query": query,
            "first_name": first_name,
            "last_name": last_name,
            "birth_date": birth_year,
            "death_date": death_year,
            "wt_id": wt_id,
            "date_spread": self._date_spread(),
            "ancestors": self.ancestors,
            "app_id": self.app_id,
        }


# ------------------------------------------------------------
#
# Launcher functions
#
# ------------------------------------------------------------
def merge_wikitree_profile(
    dbstate: Any,
    wt_id: str,
    target_handle: str | None,
    parent: Any = None,
    client: Any = None,
    app_id: str = WikiTreeInterface.DEFAULT_APP_ID,
    status: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """
    Load a WikiTree profile (with its relatives) and open the merge window
    against a person in the tree, or as a new person when target_handle is
    None. Used by the search window and by the GWizard Multi-Archive Record Scan.

    :param status: Called with progress messages, if given.
    :returns: (whether the merge was applied, a message for the user).
    """

    def show(text: str) -> None:
        if status is not None:
            status(text)

    show(_("Loading details for '%s' from WikiTree...") % wt_id)
    db = dbstate.db if dbstate else None
    if not db:
        return False, _("No open database available for merge.")

    try:
        gwizard = WikiTreeGWizard(db)
        if not gwizard.run_step(
            "connect",
            query=wt_id,
            app_id=app_id,
            client=client,
            include_relatives=True,
        ):
            return False, _("Could not configure connection to WikiTree.")
        gwizard.run_step("load")
    except Exception as err:
        LOG.error("Failed to load records from WikiTree for %s: %s", wt_id, err)
        return False, _("Failed to load records from WikiTree: %s") % str(err)

    source_db = gwizard.context.get("source_db")
    if not source_db or source_db.get_number_of_people() == 0:
        return False, _("No profile data found on WikiTree for '%s'.") % wt_id

    # Find source person handle
    source_handle: str | None = None
    for h in source_db.iter_person_handles():
        p = source_db.get_person_from_handle(h)
        if get_wikitree_id(p) == wt_id:
            source_handle = h
            break
    if not source_handle:
        for h in source_db.iter_person_handles():
            source_handle = h
            break

    if not source_handle:
        return False, _("Could not resolve source person for '%s'.") % wt_id

    from gramps.gui.gwizard.gwizardwikitreemergedialog import (
        WikiTreeMergeDialog,
    )

    merge_dialog = WikiTreeMergeDialog(
        dbstate,
        gwizard,
        source_handle,
        target_handle,
        parent=parent,
    )
    try:
        response = merge_dialog.run()
    finally:
        merge_dialog.destroy()

    if response != Gtk.ResponseType.OK:
        return False, ""
    target_name = ""
    if target_handle:
        tp = db.get_person_from_handle(target_handle)
        if tp:
            target_name = tp.get_primary_name().get_name()
    if target_name:
        return True, _("Successfully merged '%(wt_id)s' into '%(target)s'.") % {
            "wt_id": wt_id,
            "target": target_name,
        }
    return True, _("Successfully imported '%s' as a new person.") % wt_id


def ask_wikitree_parameters(
    parent: Any, default_query: str = ""
) -> dict[str, Any] | None:
    """
    Prompt the user with the WikiTree search dialog.

    :param parent: Parent window.
    :param default_query: Default search query string.
    :returns: Parameter dictionary if accepted, None if canceled.
    """
    dialog = WikiTreeSearchDialog(parent=parent, default_query=default_query)
    response = dialog.run()
    params = (
        dialog.get_query_parameters()
        if response in (Gtk.ResponseType.OK, Gtk.ResponseType.APPLY)
        else None
    )
    dialog.destroy()
    return params


def load_wikitree_gwizard(db: Any, params: dict[str, Any]) -> Any:
    """
    Initialize and run connect and load steps for WikiTreeGWizard.

    :param db: Active Gramps target database.
    :param params: Dictionary of parameters from WikiTreeSearchDialog.
    :returns: Loaded WikiTreeGWizard instance.
    :raises ValueError: If query is missing or connection fails.
    :raises RuntimeError: If loading/parsing records fails.
    """
    from gramps.gen.gwizard.gwizardwikitree import WikiTreeGWizard

    query = params.get("query", "").strip()
    if not query:
        raise ValueError(str(_("Search query cannot be empty.")))

    gwizard = WikiTreeGWizard(db)
    if not gwizard.run_step("connect", **params):
        raise ValueError(str(_("Could not configure connection to WikiTree.")))

    try:
        gwizard.run_step("load")
    except Exception as error:
        LOG.error("Failed to load records from WikiTree: %s", error)
        raise RuntimeError(str(error)) from error

    return gwizard


def run_gwizard_wikitree_flow(uistate: Any, dbstate: Any, parent: Any = None) -> bool:
    """
    Run the full GWizard WikiTree merge flow:
    prompt for search terms, query WikiTree, display potential matches in table,
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

    active_handle = None
    try:
        active_handle = uistate.get_active("Person")
    except Exception:
        active_handle = None

    dialog = WikiTreeSearchDialog(
        uistate=uistate,
        dbstate=dbstate,
        target_handle=active_handle,
        parent=parent,
    )
    try:
        dialog.run()
    finally:
        dialog.destroy()

    return True
