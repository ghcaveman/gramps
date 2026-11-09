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
from gramps.gen.gwizard.gwizard import (
    surname_text,
    get_wikitree_id,
    extract_wikitree_id,
)
from gramps.gen.gwizard.gwizardwikitree import WikiTreeGWizard, WikiTreeInterface

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# Helper functions
#
# ------------------------------------------------------------
def _extract_person_search_defaults(db: Any, person: Any) -> dict[str, str]:
    """
    Extract default search values (names, dates, WikiTree ID) from a Person.

    :param db: Active Gramps database.
    :param person: Gramps Person object.
    :returns: Dictionary with keys 'first_name', 'last_name', 'birth_year',
        'death_year', 'wt_id'.
    """
    defaults = {
        "first_name": "",
        "last_name": "",
        "birth_year": "",
        "death_year": "",
        "wt_id": "",
    }
    if not person:
        return defaults

    pname = person.get_primary_name()
    if pname:
        defaults["first_name"] = str(pname.get_first_name() or "").strip()
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

    return defaults


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
                "Import selected WikiTree profile as a new person rather than merging into an existing record."
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

        # First Name
        fn_label = Gtk.Label(label=_("First Name:"))
        fn_label.set_xalign(0.0)
        search_grid.attach(fn_label, 0, 0, 1, 1)

        self.first_name_entry = Gtk.Entry()
        self.first_name_entry.set_hexpand(True)
        self.first_name_entry.set_placeholder_text(_("e.g. Benjamin"))
        self.first_name_entry.set_tooltip_text(
            _("Given name (supports wildcards * and ?).")
        )
        self.first_name_entry.connect("activate", self.cb_entry_activate)
        search_grid.attach(self.first_name_entry, 0, 1, 1, 1)

        # Last Name
        ln_label = Gtk.Label(label=_("Last Name:"))
        ln_label.set_xalign(0.0)
        search_grid.attach(ln_label, 1, 0, 1, 1)

        self.last_name_entry = Gtk.Entry()
        self.last_name_entry.set_hexpand(True)
        self.last_name_entry.set_placeholder_text(_("e.g. Franklin"))
        self.last_name_entry.set_tooltip_text(
            _("Surname at birth or current surname (supports wildcards * and ?).")
        )
        self.last_name_entry.connect("activate", self.cb_entry_activate)
        search_grid.attach(self.last_name_entry, 1, 1, 1, 1)

        # Birth Year
        by_label = Gtk.Label(label=_("Birth Year:"))
        by_label.set_xalign(0.0)
        search_grid.attach(by_label, 2, 0, 1, 1)

        self.birth_year_entry = Gtk.Entry()
        self.birth_year_entry.set_width_chars(10)
        self.birth_year_entry.set_placeholder_text(_("e.g. 1706"))
        self.birth_year_entry.set_tooltip_text(
            _("Birth year (4 digits) or full date (YYYY-MM-DD).")
        )
        self.birth_year_entry.connect("activate", self.cb_entry_activate)
        search_grid.attach(self.birth_year_entry, 2, 1, 1, 1)

        # Death Year
        dy_label = Gtk.Label(label=_("Death Year:"))
        dy_label.set_xalign(0.0)
        search_grid.attach(dy_label, 3, 0, 1, 1)

        self.death_year_entry = Gtk.Entry()
        self.death_year_entry.set_width_chars(10)
        self.death_year_entry.set_placeholder_text(_("e.g. 1790"))
        self.death_year_entry.set_tooltip_text(
            _("Death year (4 digits) or full date (YYYY-MM-DD).")
        )
        self.death_year_entry.connect("activate", self.cb_entry_activate)
        search_grid.attach(self.death_year_entry, 3, 1, 1, 1)

        # WikiTree ID
        wt_label = Gtk.Label(label=_("WikiTree ID:"))
        wt_label.set_xalign(0.0)
        search_grid.attach(wt_label, 4, 0, 1, 1)

        self.wt_id_entry = Gtk.Entry()
        self.wt_id_entry.set_width_chars(16)
        self.wt_id_entry.set_placeholder_text(_("e.g. Franklin-1"))
        self.wt_id_entry.set_tooltip_text(
            _("Exact WikiTree ID for direct lookup (e.g. 'Franklin-1').")
        )
        self.wt_id_entry.connect("activate", self.cb_entry_activate)
        search_grid.attach(self.wt_id_entry, 4, 1, 1, 1)

        # Search Button
        search_grid.attach(Gtk.Label(label=""), 5, 0, 1, 1)
        self.btn_search = Gtk.Button(label=_("_Search"), use_underline=True)
        self.btn_search.get_style_context().add_class("suggested-action")
        self.btn_search.set_tooltip_text(
            _("Search WikiTree using the parameters entered above.")
        )
        self.btn_search.connect("clicked", self.cb_search)
        search_grid.attach(self.btn_search, 5, 1, 1, 1)

        # Help Button in Search Bar
        search_grid.attach(Gtk.Label(label=""), 6, 0, 1, 1)
        self.btn_help = Gtk.Button(label=_("_Help"), use_underline=True)
        self.btn_help.set_tooltip_text(
            _("Learn how WikiTree search and wildcards work.")
        )
        self.btn_help.connect("clicked", self.cb_help)
        search_grid.attach(self.btn_help, 6, 1, 1, 1)

        content.pack_start(search_grid, False, False, 0)

        # -----------------------------------------------------------------
        # 3. Status Message
        # -----------------------------------------------------------------
        self.status_label = Gtk.Label()
        self.status_label.set_xalign(0.0)
        self.status_label.set_line_wrap(True)
        self.status_label.set_text(
            _("Enter search terms above and click Search, or look up by WikiTree ID.")
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
        self.results_store = Gtk.ListStore(
            str, str, str, str, str, str, str, str, object
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
        self.btn_merge.get_style_context().add_class("suggested-action")
        self.btn_merge.set_tooltip_text(
            _("Open the field-by-field merge dialog for the selected WikiTree profile.")
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
            (_("WikiTree ID"), 0, False),
            (_("Name"), 1, True),
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
            self.first_name_entry.set_text(defaults["first_name"])
            self.last_name_entry.set_text(defaults["last_name"])
            self.birth_year_entry.set_text(defaults["birth_year"])
            self.death_year_entry.set_text(defaults["death_year"])
            self.wt_id_entry.set_text(defaults["wt_id"])
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
        Execute search against WikiTree and populate the results table.
        """
        first_name = self.first_name_entry.get_text().strip()
        last_name = self.last_name_entry.get_text().strip()
        birth_year = self.birth_year_entry.get_text().strip()
        death_year = self.death_year_entry.get_text().strip()
        wt_id = self.wt_id_entry.get_text().strip()
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

        if not (first_name or last_name or birth_year or death_year or wt_id):
            self.status_label.set_text(
                _("Please enter a name, year, or WikiTree ID to search.")
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

            # 2. Search by name and dates if provided
            if first_name or last_name or birth_year or death_year:
                search_matches = self.client.search_person(
                    first_name=first_name,
                    last_name=last_name,
                    birth_date=birth_year,
                    death_date=death_year,
                    limit=50,
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

    def cb_help(self, _widget: Any = None) -> None:
        """
        Display information explaining WikiTree search features and syntax.
        """
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=_("WikiTree Search Help"),
        )
        help_text = _(
            "<b>Search Criteria:</b>\n"
            "• <b>First Name & Last Name:</b> Search by given name and/or surname.\n"
            "• <b>Wildcards:</b> WikiTree supports wildcards (* and ?). "
            "For example, 'Frank*' matches Franklin, Frank, etc.\n"
            "• <b>Birth & Death Years:</b> Enter a 4-digit year (e.g. 1706) or "
            "full date (YYYY-MM-DD) to narrow results.\n"
            "• <b>WikiTree ID:</b> If you know the exact ID (e.g. Franklin-1), "
            "enter it directly for an exact profile lookup.\n\n"
            "<b>Merging:</b>\n"
            "Select a person from the search results table and click <b>Merge...</b> "
            "(or double-click the row). This opens the side-by-side merge dialog "
            "where you can compare fields and choose which details to merge into your Family Tree."
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
        Load the selected WikiTree profile and launch the GWizardMergeDialog.
        """
        selection = self.tree_view.get_selection()
        model, tree_iter = selection.get_selected()
        if not tree_iter:
            return

        wt_id = model.get_value(tree_iter, 0)
        if not wt_id:
            return

        self.status_label.set_text(
            _("Loading details for '%s' from WikiTree...") % wt_id
        )
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        from gramps.gen.gwizard.gwizardwikitree import WikiTreeGWizard

        db = self.dbstate.db if self.dbstate else None
        if not db:
            self.status_label.set_text(_("No open database available for merge."))
            return

        try:
            gwizard = WikiTreeGWizard(db)
            if not gwizard.run_step(
                "connect",
                query=wt_id,
                app_id=self.app_id,
                client=self.client,
            ):
                self.status_label.set_text(
                    _("Could not configure connection to WikiTree.")
                )
                return
            gwizard.run_step("load")
        except Exception as err:
            LOG.error("Failed to load records from WikiTree for %s: %s", wt_id, err)
            self.status_label.set_text(
                _("Failed to load records from WikiTree: %s") % str(err)
            )
            return

        source_db = gwizard.context.get("source_db")
        if not source_db or source_db.get_number_of_people() == 0:
            self.status_label.set_text(
                _("No profile data found on WikiTree for '%s'.") % wt_id
            )
            return

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
            self.status_label.set_text(
                _("Could not resolve source person for '%s'.") % wt_id
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
                    _("Successfully merged '%(wt_id)s' into '%(target)s'.")
                    % {"wt_id": wt_id, "target": target_name}
                )
            else:
                self.status_label.set_text(
                    _("Successfully imported '%s' as a new person.") % wt_id
                )

    def get_query_parameters(self) -> dict[str, Any]:
        """
        Retrieve user-entered parameters from the dialog fields.

        :returns: Parameter dictionary for WikiTreeGWizard.
        :rtype: dict[str, Any]
        """
        first_name = self.first_name_entry.get_text().strip()
        last_name = self.last_name_entry.get_text().strip()
        birth_year = self.birth_year_entry.get_text().strip()
        death_year = self.death_year_entry.get_text().strip()
        wt_id = self.wt_id_entry.get_text().strip()

        query = wt_id or f"{first_name} {last_name}".strip()

        return {
            "query": query,
            "first_name": first_name,
            "last_name": last_name,
            "birth_date": birth_year,
            "death_date": death_year,
            "wt_id": wt_id,
            "ancestors": self.ancestors,
            "app_id": self.app_id,
        }


# ------------------------------------------------------------
#
# Launcher functions
#
# ------------------------------------------------------------
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
