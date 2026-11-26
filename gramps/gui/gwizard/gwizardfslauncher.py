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
Launcher and search dialog for the GWizard FamilySearch Merge flow.
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
# GTK/Gnome modules
#
# -------------------------------------------------------------------------
from gi.repository import GLib
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizard_base import surname_text
from gramps.gen.gwizard.gwizardfamilysearch import (
    FamilySearchAuthenticationError,
    FamilySearchGWizard,
    FamilySearchInterface,
    extract_familysearch_id,
    get_familysearch_id,
    is_familysearch_id,
)
from gramps.gen.lib import NameType, Person
from gramps.gui.dialog import ErrorDialog

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .gwizardfsmergedialog import FamilySearchMergeDialog

from gramps.gui.fs.manager import get_session

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

RESPONSE_MERGE = 1

SEARCH_TERM_DEFAULTS: dict[str, bool] = {
    "first_name": True,
    "middle_name": False,
    "last_name": True,
    "gender": False,
    "birth_year": True,
    "birth_place": False,
    "death_year": False,
    "death_place": False,
    "fs_id": True,
}


# ------------------------------------------------------------
#
# Helper functions
#
# ------------------------------------------------------------
def _extract_person_search_defaults(db: Any, person: Any) -> dict[str, str]:
    """
    Extract default search values (names, dates, FSID) from a Person.

    :param db: Active Gramps database.
    :param person: Gramps Person object.
    :returns: Dictionary with search keys.
    """
    defaults = {
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "gender": "",
        "birth_year": "",
        "death_year": "",
        "fs_id": "",
        "birth_place": "",
        "death_place": "",
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

    defaults["fs_id"] = get_familysearch_id(person)
    defaults["gender"] = {
        Person.MALE: "Male",
        Person.FEMALE: "Female",
    }.get(person.get_gender(), "")

    bref = person.get_birth_ref()
    if bref and db:
        try:
            bevt = db.get_event_from_handle(bref.ref)
            if bevt:
                bdate = bevt.get_date_object()
                if bdate:
                    try:
                        byear = int(bdate.get_year())
                        if byear > 0:
                            defaults["birth_year"] = str(byear)
                    except (TypeError, ValueError):
                        pass
                bplace = bevt.get_place_handle()
                if bplace:
                    bplace_obj = db.get_place_from_handle(bplace)
                    if bplace_obj:
                        defaults["birth_place"] = str(
                            bplace_obj.get_name().get_value() or ""
                        ).strip()
        except Exception:
            pass

    dref = person.get_death_ref()
    if dref and db:
        try:
            devt = db.get_event_from_handle(dref.ref)
            if devt:
                ddate = devt.get_date_object()
                if ddate:
                    try:
                        dyear = int(ddate.get_year())
                        if dyear > 0:
                            defaults["death_year"] = str(dyear)
                    except (TypeError, ValueError):
                        pass
                dplace = devt.get_place_handle()
                if dplace:
                    dplace_obj = db.get_place_from_handle(dplace)
                    if dplace_obj:
                        defaults["death_place"] = str(
                            dplace_obj.get_name().get_value() or ""
                        ).strip()
        except Exception:
            pass

    return defaults


# ------------------------------------------------------------
#
# merge_familysearch_person
#
# ------------------------------------------------------------
def merge_familysearch_person(
    dbstate: Any,
    fsid: str,
    target_handle: str | None,
    parent: Any = None,
    client: Any = None,
    session: Any = None,
    status: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """
    Load a FamilySearch profile and open the side-by-side merge dialog.

    :param dbstate: Active Gramps database state.
    :param fsid: FamilySearch person ID.
    :param target_handle: Handle of target person in tree (or None to add new).
    :param parent: Parent window.
    :param client: Optional FamilySearchInterface client.
    :param session: Optional Session instance.
    :param status: Callback for status updates.
    :returns: Tuple of (applied, message).
    """

    def show(text: str) -> None:
        if status is not None:
            status(text)

    clean_fsid = extract_familysearch_id(fsid) or fsid.strip().upper()
    if not clean_fsid:
        return False, _("A valid FamilySearch ID is required.")

    show(_("Loading details for '%s' from FamilySearch...") % clean_fsid)
    db = dbstate.db if dbstate else None
    if not db:
        return False, _("No open database available for merge.")

    try:
        gwizard = FamilySearchGWizard(db)
        if not gwizard.run_step(
            "connect",
            query=clean_fsid,
            fsid=clean_fsid,
            client=client,
            session=session,
            include_spouses=True,
            include_notes=True,
            include_sources=True,
        ):
            return False, _("Could not configure connection to FamilySearch.")
        gwizard.run_step("load")
    except Exception as err:
        LOG.error(
            "Failed to load records from FamilySearch for %s: %s", clean_fsid, err
        )
        return False, _("Failed to load records from FamilySearch: %s") % str(err)

    source_db = gwizard.context.get("source_db")
    if not source_db or source_db.get_number_of_people() == 0:
        return False, _("No profile data found on FamilySearch for '%s'.") % clean_fsid

    source_handle: str | None = None
    for h in source_db.iter_person_handles():
        p = source_db.get_person_from_handle(h)
        if get_familysearch_id(p) == clean_fsid:
            source_handle = h
            break

    if not source_handle:
        handles = list(source_db.iter_person_handles())
        if handles:
            source_handle = handles[0]

    if not source_handle:
        return False, _("No matching incoming person found in staging database.")

    # Target candidate resolution
    resolved_target: str | None = target_handle
    if resolved_target:
        try:
            if not db.get_person_from_handle(resolved_target):
                resolved_target = None
        except Exception:
            resolved_target = None

    if not resolved_target:
        matches = gwizard.match(source_handle)
        if matches:
            resolved_target = matches[0].get("handle")

    dialog = FamilySearchMergeDialog(
        dbstate=dbstate,
        gwizard=gwizard,
        source_handle=source_handle,
        target_handle=resolved_target,
        parent=parent,
    )

    try:
        dialog.show_all()
        response = dialog.run()
        if response in (Gtk.ResponseType.OK, Gtk.ResponseType.APPLY):
            resolutions = dialog.get_resolutions()
            chosen_target = dialog.target_handle
            applied = gwizard.run_step(
                "apply",
                source_person_handle=source_handle,
                target_person_handle=chosen_target,
                resolutions=resolutions,
            )
            if applied:
                return True, _("Successfully merged FamilySearch data.")
            return False, _("Merge operation did not apply changes.")
        return False, ""
    finally:
        dialog.destroy()


# ------------------------------------------------------------
#
# FamilySearchSearchDialog
#
# ------------------------------------------------------------
class FamilySearchSearchDialog(Gtk.Dialog):
    """
    Search and merge dialog querying FamilySearch profiles with tabular results.
    """

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
        Initialize the FamilySearch search and merge dialog.
        """
        super().__init__(
            title=str(_("GWizard FamilySearch Merge")),
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(950, 600)
        self.set_resizable(True)

        self.uistate = uistate
        self.dbstate = dbstate
        self.target_handle = target_handle
        self.client = client or FamilySearchInterface()

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_border_width(12)

        # 1. Target person header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.target_label = Gtk.Label()
        self.target_label.set_xalign(0.0)
        self.target_label.set_hexpand(True)
        header_box.pack_start(self.target_label, True, True, 0)
        content.pack_start(header_box, False, False, 0)
        self._update_target_label()

        # 2. Search terms
        search_grid = Gtk.Grid()
        search_grid.set_column_spacing(8)
        search_grid.set_row_spacing(4)
        self.term_checks: dict[str, Any] = {}
        self.term_entries: dict[str, Any] = {}
        for index, (key, label, placeholder, tooltip, width) in enumerate(
            self._term_specs()
        ):
            check = Gtk.CheckButton(label=label, use_underline=True)
            check.set_tooltip_text(
                _("Include this term in the search. Unchecked terms are kept.")
            )
            check.connect("toggled", self.cb_term_toggled, key)

            entry = Gtk.Entry()
            if width:
                entry.set_width_chars(width)
            else:
                entry.set_hexpand(True)
            entry.set_placeholder_text(placeholder)
            entry.set_tooltip_text(tooltip)
            entry.connect("activate", self.cb_entry_activate)

            field_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            field_box.set_hexpand(True)
            field_box.pack_start(check, False, False, 0)
            field_box.pack_start(entry, False, False, 0)
            search_grid.attach(field_box, index % 3, index // 3, 1, 1)

            self.term_checks[key] = check
            self.term_entries[key] = entry

        self.given_name_entry = self.term_entries["first_name"]
        self.middle_name_entry = self.term_entries["middle_name"]
        self.surname_entry = self.term_entries["last_name"]
        self.birth_year_entry = self.term_entries["birth_year"]
        self.fs_id_entry = self.term_entries["fs_id"]

        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions_box.set_halign(Gtk.Align.END)

        self.reset_button = Gtk.Button(label=_("_Reset"), use_underline=True)
        self.reset_button.set_tooltip_text(
            _("Restore the search terms and default selections.")
        )
        self.reset_button.connect("clicked", self.cb_reset_terms)
        actions_box.pack_start(self.reset_button, False, False, 0)

        self.search_button = Gtk.Button(label=_("_Search"), use_underline=True)
        self.search_button.get_style_context().add_class("suggested-action")
        self.search_button.set_tooltip_text(
            _("Search FamilySearch using the checked terms above.")
        )
        self.search_button.connect("clicked", self.cb_search)
        actions_box.pack_start(self.search_button, False, False, 0)
        search_grid.attach(actions_box, 0, 3, 3, 1)

        content.pack_start(search_grid, False, False, 0)

        # 3. Search status and help
        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0.0)
        self.status_label.set_line_wrap(True)
        self.status_label.set_text(
            _(
                "Check the terms to search on and click Search, or look up "
                "directly by FamilySearch ID."
            )
        )
        content.pack_start(self.status_label, False, False, 0)

        # 4. Search results
        self.store = Gtk.ListStore(str, str, str, str, str, str, str)
        self.tree_view = Gtk.TreeView(model=self.store)
        self.tree_view.set_headers_visible(True)
        self.tree_view.set_vexpand(True)
        self.tree_view.set_enable_search(True)
        self.tree_view.set_search_column(1)
        self.tree_view.connect("row-activated", self.cb_row_activated)

        for col_idx, (col_title, width) in enumerate(
            [
                (_("FamilySearch ID"), 130),
                (_("Name"), 200),
                (_("Gender"), 75),
                (_("Birth Date"), 120),
                (_("Birth Place"), 160),
                (_("Death Date"), 120),
                (_("Death Place"), 160),
            ]
        ):
            renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(col_title, renderer, text=col_idx)
            col.set_min_width(width)
            col.set_resizable(True)
            col.set_expand(col_idx in (1, 4, 6))
            self.tree_view.append_column(col)

        selection = self.tree_view.get_selection()
        selection.set_mode(Gtk.SelectionMode.SINGLE)
        selection.connect("changed", self.cb_selection_changed)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.add(self.tree_view)
        scroll.set_min_content_height(280)
        content.pack_start(scroll, True, True, 0)

        # 5. Action bar
        self.add_button(_("_Close"), Gtk.ResponseType.CLOSE)
        self.merge_button = self.add_button(_("Compare / _Merge..."), RESPONSE_MERGE)
        self.merge_button.get_style_context().add_class("suggested-action")
        self.merge_button.set_tooltip_text(
            _("Open the field-by-field merge dialog for the selected profile.")
        )
        self.merge_button.set_sensitive(False)
        self.connect("response", self.cb_response)

        self.default_query = default_query
        self._prefill_entries(default_query=default_query)
        self._apply_default_terms()
        self.show_all()

    @staticmethod
    def _term_specs() -> list[tuple[str, str, str, str, int]]:
        """Return the FamilySearch search fields and their entry hints."""
        return [
            (
                "first_name",
                _("_First Name"),
                _("Given name"),
                _("First given name."),
                0,
            ),
            (
                "middle_name",
                _("M_iddle Name"),
                _("Other given names"),
                _("Other given names, searched with the first name."),
                12,
            ),
            (
                "last_name",
                _("_Last Name"),
                _("Surname"),
                _("Surname."),
                0,
            ),
            (
                "gender",
                _("_Gender"),
                _("Male or Female"),
                _("Filter by gender."),
                10,
            ),
            (
                "birth_year",
                _("_Birth Year"),
                _("YYYY or YYYY-MM-DD"),
                _("Birth year or date."),
                14,
            ),
            (
                "birth_place",
                _("Birth L_ocation"),
                _("Place"),
                _("Filter by birth place."),
                16,
            ),
            (
                "death_year",
                _("_Death Year"),
                _("YYYY or YYYY-MM-DD"),
                _("Filter by death year or date."),
                14,
            ),
            (
                "death_place",
                _("Death Loca_tion"),
                _("Place"),
                _("Filter by death place."),
                16,
            ),
            (
                "fs_id",
                _("FamilySearch _ID"),
                _("ID or profile URL"),
                _("Exact FamilySearch ID for direct lookup."),
                18,
            ),
        ]

    def _apply_default_terms(self) -> None:
        """Check the default search terms and disable unchecked entries."""
        for key, check in self.term_checks.items():
            check.set_active(SEARCH_TERM_DEFAULTS.get(key, False))
            self._sync_term_entry(key)

    def _sync_term_entry(self, key: str) -> None:
        """Enable a search entry only while its term is checked."""
        self.term_entries[key].set_sensitive(self.term_checks[key].get_active())

    def _term_value(self, key: str) -> str:
        """Return a checked search term's text."""
        if not self.term_checks[key].get_active():
            return ""
        return str(self.term_entries[key].get_text()).strip()

    def _update_target_label(self) -> None:
        """
        Update the target person header label.
        """
        db = self.dbstate.db if self.dbstate else None
        if self.target_handle and db:
            try:
                person = db.get_person_from_handle(self.target_handle)
                if person:
                    name = person.get_primary_name().get_name()
                    gid = person.get_gramps_id()
                    self.target_label.set_markup(
                        _("Merge FamilySearch data into: <b>%(name)s</b> (%(id)s)")
                        % {"name": GLib.markup_escape_text(name), "id": gid}
                    )
                    return
            except Exception as err:
                LOG.warning(
                    "Could not resolve target person %s: %s",
                    self.target_handle,
                    err,
                )

        self.target_label.set_markup(
            _("Merge FamilySearch data into: <i>None (will add as a new person)</i>")
        )

    def _prefill_entries(self, default_query: str = "") -> None:
        """
        Fill in search fields from the active target person or default query.
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
            self.given_name_entry.set_text(defaults["first_name"])
            self.middle_name_entry.set_text(defaults["middle_name"])
            self.surname_entry.set_text(defaults["last_name"])
            self.term_entries["gender"].set_text(defaults["gender"])
            self.birth_year_entry.set_text(defaults["birth_year"])
            self.term_entries["birth_place"].set_text(defaults["birth_place"])
            self.term_entries["death_year"].set_text(defaults["death_year"])
            self.term_entries["death_place"].set_text(defaults["death_place"])
            self.fs_id_entry.set_text(defaults["fs_id"])
        elif default_query:
            query = default_query.strip()
            extracted_id = extract_familysearch_id(query)
            if extracted_id:
                self.fs_id_entry.set_text(extracted_id)
            else:
                self.given_name_entry.set_text(query)

    def cb_term_toggled(self, _check: Gtk.CheckButton, key: str) -> None:
        """Enable or disable a search entry when its check button is toggled."""
        self._sync_term_entry(key)

    def cb_reset_terms(self, _widget: Any = None) -> None:
        """Restore the initial search values and default term selections."""
        for entry in self.term_entries.values():
            entry.set_text("")
        self._prefill_entries(default_query=self.default_query)
        self._apply_default_terms()
        self.store.clear()
        self.merge_button.set_sensitive(False)
        self.status_label.set_text(
            _(
                "Check the terms to search on and click Search, or look up "
                "directly by FamilySearch ID."
            )
        )

    def cb_entry_activate(self, _widget: Gtk.Entry) -> None:
        """
        Trigger search on Enter.
        """
        self.cb_search()

    def _show_authentication_error(self, message: str | None = None) -> None:
        """Show the FamilySearch authentication failure dialog."""
        error_message = message or _(
            "Failed authentication with FamilySearch. In the Family Trees "
            "menu, choose FamilySearch Sign in..., then search again."
        )
        self.status_label.set_text(error_message)
        ErrorDialog(
            _("FamilySearch Authentication Failed"),
            error_message,
            parent=self,
        )

    def cb_search(self, _widget: Any = None) -> None:
        """
        Execute search against FamilySearch.
        """
        fs_id = extract_familysearch_id(self._term_value("fs_id"))
        first_name = self._term_value("first_name")
        middle_name = self._term_value("middle_name")
        given = " ".join(name for name in (first_name, middle_name) if name)
        surname = self._term_value("last_name")
        gender = self._term_value("gender")
        birth = self._term_value("birth_year")
        birth_place = self._term_value("birth_place")
        death = self._term_value("death_year")
        death_place = self._term_value("death_place")

        if not (
            fs_id
            or given
            or surname
            or gender
            or birth
            or birth_place
            or death
            or death_place
        ):
            self.status_label.set_text(
                _(
                    "Please check and fill in a name, date, place, gender, "
                    "or FamilySearch ID."
                )
            )
            return

        if not self.client.is_authenticated():
            self._show_authentication_error()
            return

        self.status_label.set_text(_("Searching FamilySearch..."))
        self.search_button.set_sensitive(False)
        self.store.clear()
        self.merge_button.set_sensitive(False)

        def _pump():
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

        _pump()

        results: list[dict[str, Any]] = []
        try:
            if (
                given
                or surname
                or birth
                or gender
                or birth_place
                or death
                or death_place
            ):
                results.extend(
                    self.client.search_person(
                        first_name=given,
                        last_name=surname,
                        birth_date=birth,
                        death_date=death,
                        gender=gender,
                        birth_place=birth_place,
                        death_place=death_place,
                        limit=25,
                    )
                )
            if fs_id:
                results.extend(self.client.search_person(query=fs_id))
        except FamilySearchAuthenticationError as err:
            self._show_authentication_error(str(err))
            self.search_button.set_sensitive(True)
            return
        except Exception as err:
            self.status_label.set_text(
                _("Search failed: %(error)s") % {"error": str(err)}
            )
            self.search_button.set_sensitive(True)
            return

        seen: set[str] = set()
        for res in results:
            fid = res.get("fsid")
            if not fid or fid in seen:
                continue
            seen.add(fid)
            self.store.append(
                [
                    fid,
                    res.get("name") or "",
                    res.get("gender") or "",
                    res.get("birth_date") or "",
                    res.get("birth_place") or "",
                    res.get("death_date") or "",
                    res.get("death_place") or "",
                ]
            )

        count = len(seen)
        if count > 0:
            self.status_label.set_text(
                _(
                    "Found %(count)d matching profiles. Select a profile and "
                    "click Compare / Merge."
                )
                % {"count": count}
            )
            selection = self.tree_view.get_selection()
            selection.select_path(0)
        else:
            self.status_label.set_text(_("No FamilySearch people found."))

        self.search_button.set_sensitive(True)

    def cb_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        """Enable Compare / Merge only when a result is selected."""
        _model, tree_iter = selection.get_selected()
        self.merge_button.set_sensitive(tree_iter is not None)

    def cb_response(self, _dialog: Any, response: int) -> None:
        """Run Compare / Merge without closing the search dialog."""
        if response == RESPONSE_MERGE:
            self.stop_emission_by_name("response")
            self.cb_merge()

    def cb_row_activated(
        self, _tree: Gtk.TreeView, _path: Gtk.TreePath, _col: Gtk.TreeViewColumn
    ) -> None:
        """
        Double-clicking a row triggers Compare/Merge.
        """
        if self.merge_button.get_sensitive():
            self.cb_merge()

    def cb_merge(self, _widget: Any = None) -> None:
        """
        Load the selected FamilySearch person and open the merge dialog.
        """
        selection = self.tree_view.get_selection()
        model, tree_iter = selection.get_selected()
        if not tree_iter:
            self.status_label.set_text(
                _("Search for and select a FamilySearch person first.")
            )
            return

        fs_id = model.get_value(tree_iter, 0)
        if not fs_id:
            return

        merged, message = merge_familysearch_person(
            self.dbstate,
            fs_id,
            self.target_handle,
            parent=self,
            client=self.client,
            status=self._show_status,
        )
        if merged and self.target_handle:
            self._prefill_entries()
        if message:
            self.status_label.set_text(message)

    def _show_status(self, text: str) -> None:
        """
        Show a progress message.
        """
        self.status_label.set_text(text)
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)


# ------------------------------------------------------------
#
# run_gwizard_familysearch_flow
#
# ------------------------------------------------------------
def run_gwizard_familysearch_flow(
    uistate: Any, dbstate: Any, parent: Any = None
) -> bool:
    """
    Launch the GWizard FamilySearch search and merge flow.

    :param uistate: UI state manager.
    :param dbstate: Database state manager.
    :param parent: Parent window.
    :returns: True when completed.
    :rtype: bool
    """
    active_handle = uistate.get_active("Person") if uistate else None
    # Get the active session to ensure auth state is preserved
    session = get_session(dbstate=dbstate, uistate=uistate)
    dialog = FamilySearchSearchDialog(
        uistate=uistate,
        dbstate=dbstate,
        target_handle=active_handle,
        parent=parent,
        client=FamilySearchInterface(session=session),
    )
    try:
        dialog.show_all()
        dialog.run()
    finally:
        dialog.destroy()
    return True
