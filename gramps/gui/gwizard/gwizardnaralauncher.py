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
from gramps.gen.gwizard.gwizard import surname_text
from gramps.gen.gwizard.gwizardnara import NaraGWizard, NaraCatalogInterface

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


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
    :returns: Dictionary with keys 'first_name', 'last_name', 'query',
        'birth_year', 'death_year'.
    """
    defaults = {
        "first_name": "",
        "last_name": "",
        "query": "",
        "birth_year": "",
        "death_year": "",
    }
    if not person:
        return defaults

    pname = person.get_primary_name()
    if pname:
        fn = str(pname.get_first_name() or "").strip()
        ln = str(surname_text(pname) or "").strip()
        defaults["first_name"] = fn
        defaults["last_name"] = ln
        defaults["query"] = f"{fn} {ln}".strip() or pname.get_name().strip()

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

    return defaults


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
        default_api_key: str = "",
        client: Any = None,
    ) -> None:
        """
        Initialize the NARA search and merge dialog.

        :param uistate: Gramps UI state manager.
        :param dbstate: Gramps database state manager.
        :param target_handle: Handle of the target Gramps Person to merge into.
        :param parent: Parent GTK window for transient placement.
        :param default_query: Optional pre-filled search query.
        :param default_api_key: Optional pre-filled API key.
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

        env_key = (
            os.environ.get("NARA_API_KEY") or os.environ.get("CATALOG_API_KEY") or ""
        )
        self.api_key = default_api_key.strip() or env_key.strip()
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
            label=_("_Change Target..."), use_underline=True
        )
        self.btn_change_target.set_tooltip_text(
            _("Select a different person in your Family Tree as the merge target.")
        )
        self.btn_change_target.connect("clicked", self.cb_change_target)
        header_box.pack_start(self.btn_change_target, False, False, 0)

        self.btn_new_target = Gtk.Button(label=_("_Add as New"), use_underline=True)
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

        # Row 0: Search Query
        q_label = Gtk.Label(label=_("Search Query:"))
        q_label.set_xalign(0.0)
        search_grid.attach(q_label, 0, 0, 1, 1)

        self.query_entry = Gtk.Entry()
        self.query_entry.set_hexpand(True)
        self.query_entry.set_placeholder_text(
            _("e.g. Abraham Lincoln, Civil War Pension, or NAID")
        )
        self.query_entry.set_tooltip_text(
            _("Search query (person name, keywords, subject, or NAID).")
        )
        self.query_entry.connect("activate", self.cb_entry_activate)
        search_grid.attach(self.query_entry, 0, 1, 1, 1)

        # Row 0: Material Type
        mat_label = Gtk.Label(label=_("Material Type:"))
        mat_label.set_xalign(0.0)
        search_grid.attach(mat_label, 1, 0, 1, 1)

        self.material_combo = Gtk.ComboBoxText()
        for code, label in self.MATERIAL_TYPES:
            self.material_combo.append(code, label)
        self.material_combo.set_active(0)
        search_grid.attach(self.material_combo, 1, 1, 1, 1)

        # Row 0: Online only
        self.online_check = Gtk.CheckButton(label=_("Online only"))
        self.online_check.set_tooltip_text(
            _("Restrict results to records with digitized online assets.")
        )
        self.online_check.set_active(False)
        search_grid.attach(self.online_check, 2, 1, 1, 1)

        # Row 0: Search Button
        search_grid.attach(Gtk.Label(label=""), 3, 0, 1, 1)
        self.btn_search = Gtk.Button(label=_("_Search"), use_underline=True)
        self.btn_search.get_style_context().add_class("suggested-action")
        self.btn_search.set_tooltip_text(
            _("Search the National Archives Catalog using the parameters above.")
        )
        self.btn_search.connect("clicked", self.cb_search)
        search_grid.attach(self.btn_search, 3, 1, 1, 1)

        # Row 0: Help Button
        search_grid.attach(Gtk.Label(label=""), 4, 0, 1, 1)
        self.btn_help = Gtk.Button(label=_("_Help"), use_underline=True)
        self.btn_help.set_tooltip_text(
            _("Learn how National Archives search and filters work.")
        )
        self.btn_help.connect("clicked", self.cb_help)
        search_grid.attach(self.btn_help, 4, 1, 1, 1)

        # Row 1: Max records & Optional API Key in sub-box
        adv_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        limit_label = Gtk.Label(label=_("Max Records:"))
        adv_box.pack_start(limit_label, False, False, 0)

        limit_adj = Gtk.Adjustment(value=25, lower=1, upper=100, step_increment=5)
        self.limit_spin = Gtk.SpinButton(adjustment=limit_adj, climb_rate=1, digits=0)
        adv_box.pack_start(self.limit_spin, False, False, 0)

        key_label = Gtk.Label(label=_("API Key (optional):"))
        adv_box.pack_start(key_label, False, False, 0)

        self.key_entry = Gtk.Entry()
        self.key_entry.set_hexpand(True)
        self.key_entry.set_text(self.api_key)
        self.key_entry.set_placeholder_text(_("Optional (tracks monthly quota)"))
        self.key_entry.set_tooltip_text(
            _(
                "NARA API key obtained from Catalog_API@nara.gov. "
                "Optional for standard usage, but increases rate limits."
            )
        )
        self.key_entry.connect("activate", self.cb_entry_activate)
        adv_box.pack_start(self.key_entry, True, True, 0)

        search_grid.attach(adv_box, 0, 2, 5, 1)

        content.pack_start(search_grid, False, False, 0)

        # -----------------------------------------------------------------
        # 3. Status Message
        # -----------------------------------------------------------------
        self.status_label = Gtk.Label()
        self.status_label.set_xalign(0.0)
        self.status_label.set_line_wrap(True)
        self.status_label.set_text(
            _("Enter search query above and click Search, or look up by NAID.")
        )
        content.pack_start(self.status_label, False, False, 0)

        # -----------------------------------------------------------------
        # 4. Results Table
        # -----------------------------------------------------------------
        # Model columns:
        # 0: NAID (str)
        # 1: Title (str)
        # 2: Creator / Person (str)
        # 3: Date (str)
        # 4: Material Type (str)
        # 5: Digital Media (str)
        # 6: Raw match data / hit (object)
        self.results_store = Gtk.ListStore(str, str, str, str, str, str, object)
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
        self.btn_merge.get_style_context().add_class("suggested-action")
        self.btn_merge.set_tooltip_text(
            _("Open the field-by-field merge dialog for the selected NARA record.")
        )
        self.btn_merge.set_sensitive(False)
        self.btn_merge.connect("clicked", self.cb_merge)
        action_area = self.get_action_area()
        action_area.pack_end(self.btn_merge, False, False, 0)

        # Pre-populate search entries from target person or default query
        self._prefill_entries(default_query=default_query)

        self.show_all()

    def _build_tree_columns(self) -> None:
        """
        Create and append column headers for the search results treeview.
        """
        cols = [
            (_("NAID"), 0, False),
            (_("Title"), 1, True),
            (_("Creator / Person"), 2, True),
            (_("Date"), 3, False),
            (_("Material Type"), 4, False),
            (_("Digital Media"), 5, False),
        ]
        for title, col_id, is_expand in cols:
            renderer = Gtk.CellRendererText()
            if is_expand:
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(title, renderer, text=col_id)
            col.set_sort_column_id(col_id)
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
            if defaults["query"]:
                self.query_entry.set_text(defaults["query"])
        elif default_query:
            self.query_entry.set_text(default_query.strip())

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
        except Exception as err:
            LOG.error("Failed to select target person: %s", err)

    def cb_set_target_none(self, _widget: Any = None) -> None:
        """
        Set target person to None so selected profile will be added as new.
        """
        self.target_handle = None
        self._update_target_label()

    def cb_entry_activate(self, _widget: Gtk.Entry) -> None:
        """
        Trigger search when pressing Enter in any search entry box.
        """
        self.cb_search()

    def cb_search(self, _widget: Any = None) -> None:
        """
        Execute search against NARA Catalog API and populate the results table.
        """
        query = self.query_entry.get_text().strip()
        api_key = self.key_entry.get_text().strip()
        limit = int(self.limit_spin.get_value())
        selected_mat = self.material_combo.get_active_id() or None
        online_only = self.online_check.get_active()

        if not query:
            self.status_label.set_text(
                _("Please enter a name, keyword, or NAID to search.")
            )
            return

        if api_key != self.api_key:
            self.api_key = api_key
            self.client.api_key = api_key
            if hasattr(self.client, "headers") and isinstance(
                self.client.headers, dict
            ):
                if api_key:
                    self.client.headers["x-api-key"] = api_key
                else:
                    self.client.headers.pop("x-api-key", None)

        self.status_label.set_text(_("Searching National Archives Catalog..."))
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        try:
            response = self.client.search_records(
                query=query,
                rows=limit,
                material_type=selected_mat,
                available_online=True if online_only else None,
            )
            hits = self.client.extract_hits(response)
        except Exception as err:
            LOG.error("NARA search failed: %s", err)
            self.status_label.set_text(_("NARA search failed: %s") % str(err))
            return

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

        for hit in hits:
            parsed = NaraCatalogInterface.parse_record(hit)
            naid = parsed["naid"]
            title = parsed["title"]
            creators = ", ".join(parsed["creators"]) if parsed["creators"] else "-"
            date_str = parsed["date_str"] or "-"
            mat_type = parsed["material_type"] or "-"
            num_digital = len(parsed["digital_objects"])
            digital_str = _("Yes (%d)") % num_digital if num_digital > 0 else _("No")

            self.results_store.append(
                [
                    naid,
                    title,
                    creators,
                    date_str,
                    mat_type,
                    digital_str,
                    hit,
                ]
            )

        self.status_label.set_text(
            _(
                "Found %d matching records in the National Archives Catalog. "
                "Select a record and click Merge."
            )
            % len(hits)
        )

        first_iter = self.results_store.get_iter_first()
        if first_iter:
            self.tree_view.get_selection().select_iter(first_iter)
            self.btn_merge.set_sensitive(True)

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
            "• <b>Search Query:</b> Search by person name, historical subject, military unit, "
            "pension application, or National Archives Identifier (NAID).\n"
            "• <b>Material Type:</b> Narrow records to textual files, photographs, maps, etc.\n"
            "• <b>Online Only:</b> Restrict results to records with digitized online assets (images/documents).\n"
            "• <b>API Key:</b> Free API key from Catalog_API@nara.gov for higher rate limits (optional).\n\n"
            "<b>Merging:</b>\n"
            "Select a record from the search results table and click <b>Merge...</b> "
            "(or double-click the row). This opens the side-by-side merge dialog "
            "where you can review extracted person details, citations, notes, and digital media "
            "to merge into your Family Tree."
        )
        dialog.format_secondary_markup(help_text)
        dialog.run()
        dialog.destroy()

    def cb_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        """
        Enable or disable the Merge button based on table row selection.
        """
        model, tree_iter = selection.get_selected()
        self.btn_merge.set_sensitive(tree_iter is not None)

    def cb_row_activated(self, _tree: Any, _path: Any, _col: Any) -> None:
        """
        Handle double-clicking a row to trigger merge directly.
        """
        if self.btn_merge.get_sensitive():
            self.cb_merge()

    def cb_merge(self, _widget: Any = None) -> None:
        """
        Load the selected NARA record and launch the GWizardMergeDialog.
        """
        selection = self.tree_view.get_selection()
        model, tree_iter = selection.get_selected()
        if not tree_iter:
            return

        naid = model.get_value(tree_iter, 0)
        hit = model.get_value(tree_iter, 6)
        if not hit:
            return

        self.status_label.set_text(
            _("Loading details for NAID '%s' from NARA...") % naid
        )
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        from gramps.gen.gwizard.gwizardnara import NaraGWizard

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
            LOG.error("Failed to load records from NARA for NAID %s: %s", naid, err)
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
        query = self.query_entry.get_text().strip()
        api_key = self.key_entry.get_text().strip()
        limit = int(self.limit_spin.get_value())
        selected_mat = self.material_combo.get_active_id() or None
        online_only = self.online_check.get_active()

        params: dict[str, Any] = {
            "query": query,
            "api_key": api_key,
            "limit": limit,
        }
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
    from gramps.gen.gwizard.gwizardnara import NaraGWizard

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
    )
    try:
        dialog.run()
    finally:
        dialog.destroy()

    return True
