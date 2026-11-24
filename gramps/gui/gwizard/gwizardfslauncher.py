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

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

RESPONSE_MERGE = 1


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
        "birth_year": "",
        "death_year": "",
        "fs_id": "",
        "birth_place": "",
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
        self.set_default_size(880, 560)
        self.set_resizable(True)

        self.uistate = uistate
        self.dbstate = dbstate
        self.target_handle = target_handle
        self.client = client or FamilySearchInterface()

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_border_width(12)

        # 1. Target Person Header
        self.target_label = Gtk.Label()
        self.target_label.set_xalign(0.0)
        self.target_label.set_hexpand(True)
        content.pack_start(self.target_label, False, False, 0)
        self._update_target_label()

        # 2. Search Criteria Grid
        search_grid = Gtk.Grid()
        search_grid.set_column_spacing(10)
        search_grid.set_row_spacing(6)

        # Row 0: FamilySearch ID
        lbl_fsid = Gtk.Label(label=_("FamilySearch ID:"))
        lbl_fsid.set_xalign(0.0)
        self.fs_id_entry = Gtk.Entry()
        self.fs_id_entry.set_placeholder_text(_("e.g. GSVF-SGV or profile URL"))
        self.fs_id_entry.set_hexpand(True)
        self.fs_id_entry.connect("activate", self.cb_entry_activate)
        search_grid.attach(lbl_fsid, 0, 0, 1, 1)
        search_grid.attach(self.fs_id_entry, 1, 0, 3, 1)

        # Row 1: Given Name & Surname
        lbl_given = Gtk.Label(label=_("Given Name:"))
        lbl_given.set_xalign(0.0)
        self.given_name_entry = Gtk.Entry()
        self.given_name_entry.set_hexpand(True)
        self.given_name_entry.connect("activate", self.cb_entry_activate)

        lbl_surname = Gtk.Label(label=_("Surname:"))
        lbl_surname.set_xalign(0.0)
        self.surname_entry = Gtk.Entry()
        self.surname_entry.set_hexpand(True)
        self.surname_entry.connect("activate", self.cb_entry_activate)

        search_grid.attach(lbl_given, 0, 1, 1, 1)
        search_grid.attach(self.given_name_entry, 1, 1, 1, 1)
        search_grid.attach(lbl_surname, 2, 1, 1, 1)
        search_grid.attach(self.surname_entry, 3, 1, 1, 1)

        # Row 2: Birth Year & Search Button
        lbl_birth = Gtk.Label(label=_("Birth Year:"))
        lbl_birth.set_xalign(0.0)
        self.birth_year_entry = Gtk.Entry()
        self.birth_year_entry.set_placeholder_text(_("YYYY"))
        self.birth_year_entry.connect("activate", self.cb_entry_activate)

        self.search_button = Gtk.Button(label=_("Search FamilySearch"))
        self.search_button.connect("clicked", self.cb_search)

        search_grid.attach(lbl_birth, 0, 2, 1, 1)
        search_grid.attach(self.birth_year_entry, 1, 2, 1, 1)
        search_grid.attach(self.search_button, 3, 2, 1, 1)

        content.pack_start(search_grid, False, False, 0)

        # Status label
        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0.0)
        content.pack_start(self.status_label, False, False, 0)

        # 3. Results Table
        # Store: [FSID, Name, Lifespan]
        self.store = Gtk.ListStore(str, str, str)
        self.tree_view = Gtk.TreeView(model=self.store)
        self.tree_view.set_headers_visible(True)
        self.tree_view.set_vexpand(True)
        self.tree_view.connect("row-activated", self.cb_row_activated)

        for col_idx, (col_title, width) in enumerate(
            [
                (_("FamilySearch ID"), 130),
                (_("Name"), 260),
                (_("Life Span"), 200),
            ]
        ):
            renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(col_title, renderer, text=col_idx)
            col.set_min_width(width)
            col.set_resizable(True)
            self.tree_view.append_column(col)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.tree_view)
        scroll.set_min_content_height(200)
        content.pack_start(scroll, True, True, 0)

        # 4. Action Buttons
        self.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        self.merge_button = self.add_button(_("Compare / Merge"), RESPONSE_MERGE)
        self.merge_button.get_style_context().add_class("suggested-action")
        self.merge_button.connect("clicked", self.cb_merge)

        self._prefill_entries(default_query=default_query)

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
            self.surname_entry.set_text(defaults["last_name"])
            self.birth_year_entry.set_text(defaults["birth_year"])
            self.fs_id_entry.set_text(defaults["fs_id"])
        elif default_query:
            query = default_query.strip()
            extracted_id = extract_familysearch_id(query)
            if extracted_id:
                self.fs_id_entry.set_text(extracted_id)
            else:
                self.given_name_entry.set_text(query)

    def cb_entry_activate(self, _widget: Gtk.Entry) -> None:
        """
        Trigger search on Enter.
        """
        self.cb_search()

    def cb_search(self, _widget: Any = None) -> None:
        """
        Execute search against FamilySearch.
        """
        fs_id = extract_familysearch_id(self.fs_id_entry.get_text())
        given = self.given_name_entry.get_text().strip()
        surname = self.surname_entry.get_text().strip()
        birth = self.birth_year_entry.get_text().strip()

        if not (fs_id or given or surname or birth):
            self.status_label.set_text(
                _("Please enter a FamilySearch ID or name/year to search.")
            )
            return

        self.status_label.set_text(_("Searching FamilySearch..."))
        self.search_button.set_sensitive(False)
        self.store.clear()

        def _pump():
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

        _pump()

        results: list[dict[str, Any]] = []
        try:
            if fs_id:
                results.append({"fsid": fs_id, "name": fs_id, "life": ""})
            results.extend(
                self.client.search_person(
                    first_name=given,
                    last_name=surname,
                    birth_date=birth,
                    limit=25,
                )
            )
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
            self.store.append([fid, res.get("name") or "", res.get("life") or ""])

        count = len(seen)
        if count > 0:
            self.status_label.set_text(
                _("Found %(count)d matching results.") % {"count": count}
            )
            selection = self.tree_view.get_selection()
            selection.select_path(0)
        else:
            self.status_label.set_text(_("No FamilySearch people found."))

        self.search_button.set_sensitive(True)

    def cb_row_activated(
        self, _tree: Gtk.TreeView, _path: Gtk.TreePath, _col: Gtk.TreeViewColumn
    ) -> None:
        """
        Double-clicking a row triggers Compare/Merge.
        """
        self.cb_merge()

    def cb_merge(self, _widget: Any = None) -> None:
        """
        Load the selected FamilySearch person and open the merge dialog.
        """
        selection = self.tree_view.get_selection()
        model, tree_iter = selection.get_selected()
        if not tree_iter:
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
    dialog = FamilySearchSearchDialog(
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
