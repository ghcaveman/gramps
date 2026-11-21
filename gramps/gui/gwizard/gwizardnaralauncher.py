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
from gramps.gen.gwizard.gwizardnaramerge import (
    AttachResult,
    NaraCatalogInterface,
    NaraGWizard,
    NaraRecordAttacher,
)

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

        # Row 1: Maximum number of records
        adv_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        limit_label = Gtk.Label(label=_("Max Records:"))
        adv_box.pack_start(limit_label, False, False, 0)

        limit_adj = Gtk.Adjustment(value=25, lower=1, upper=100, step_increment=5)
        self.limit_spin = Gtk.SpinButton(adjustment=limit_adj, climb_rate=1, digits=0)
        adv_box.pack_start(self.limit_spin, False, False, 0)

        # Image options for Attach to Person
        adv_box.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 6
        )
        self.download_check = Gtk.CheckButton(
            label=_("Download _images"), use_underline=True
        )
        self.download_check.set_active(True)
        self.download_check.set_tooltip_text(
            _(
                "When attaching a record, download its images into the NARA "
                "folder under your media base path. Unchecked, the images are "
                "linked by their web address instead."
            )
        )
        adv_box.pack_start(self.download_check, False, False, 0)
        images_label = Gtk.Label(label=_("up to"))
        adv_box.pack_start(images_label, False, False, 0)
        images_adj = Gtk.Adjustment(value=0, lower=0, upper=999, step_increment=1)
        self.max_images_spin = Gtk.SpinButton(
            adjustment=images_adj, climb_rate=1, digits=0
        )
        self.max_images_spin.set_tooltip_text(
            _("Most images to add from one record; 0 adds all of them.")
        )
        adv_box.pack_start(self.max_images_spin, False, False, 0)
        adv_box.pack_start(Gtk.Label(label=_("(0 = all)")), False, False, 0)

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
        # 2: Person creator(s), or a dash (str)
        # 3: Creator(s), own or the nearest ancestor's (str)
        # 4: Date (str)
        # 5: Material Type (str)
        # 6: Digital Media (str)
        # 7: Raw match data / hit (object)
        # 8: Can merge as a person (bool)
        self.results_store = Gtk.ListStore(
            str, str, str, str, str, str, str, object, bool
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
        self._prefill_entries(default_query=default_query)

        self.show_all()

    def _build_tree_columns(self) -> None:
        """
        Create and append column headers for the search results treeview.
        """
        cols = [
            (_("NAID"), 0, False),
            (_("Title"), 1, True),
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
        query = self.query_entry.get_text().strip()
        limit = int(self.limit_spin.get_value())
        selected_mat = self.material_combo.get_active_id() or None
        online_only = self.online_check.get_active()

        if not query:
            self.status_label.set_text(
                _("Please enter a name, keyword, or NAID to search.")
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

        mergeable_count = 0
        for hit in hits:
            parsed = NaraCatalogInterface.parse_record(hit)
            people = parsed["person_creators"]
            mergeable_count += 1 if people else 0
            num_digital = len(parsed["digital_objects"])
            digital_str = _("Yes (%d)") % num_digital if num_digital > 0 else _("No")

            self.results_store.append(
                [
                    parsed["naid"],
                    parsed["title"],
                    "; ".join(people) if people else "-",
                    self._with_level(
                        "; ".join(parsed["creators"]), parsed["creators_from"]
                    ),
                    self._with_level(parsed["date_str"], parsed["date_from"]),
                    parsed["material_type"] or "-",
                    digital_str,
                    hit,
                    bool(people),
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
            "• <b>Search Query:</b> Search by person name, historical subject, military unit, "
            "pension application, or National Archives Identifier (NAID).\n"
            "• <b>Material Type:</b> Narrow records to textual files, photographs, maps, etc.\n"
            "• <b>Online Only:</b> Restrict results to records with digitized online assets (images/documents).\n"
            "• Set the <b>NARA_API_KEY</b> environment variable before launching Gramps to authenticate with the catalog.\n\n"
            "<b>Attach to Person:</b>\n"
            "Select a record and click <b>Attach to Person</b> to add it to the target "
            "person: NARA as the repository, the record's series as the source, and the "
            "record as a citation with a note holding its catalog link. With "
            "<b>Download images</b> checked, its images are saved under the NARA folder "
            "of your media base path (one folder per NAID) and linked to the citation; "
            "otherwise they are linked by web address. Attaching the same record again "
            "adds nothing new.\n\n"
            "<b>Merging:</b>\n"
            "Most NARA records are created by agencies, so the Person column shows a dash "
            "and Merge is unavailable. For a record that names a person as its creator, "
            "click <b>Merge...</b> (or double-click the row) to open the side-by-side "
            "merge dialog."
        )
        dialog.format_secondary_markup(help_text)
        dialog.run()
        dialog.destroy()

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

    @staticmethod
    def _attach_summary(result: AttachResult) -> str:
        """Return the status message for a finished attach."""
        if result.citation_created:
            text = _("The NARA record was attached as a new citation.")
        elif result.person_linked:
            text = _("The NARA record's existing citation was attached.")
        else:
            text = _("The NARA record was already attached to this person.")
        parts = [text]
        if result.downloaded or result.already_downloaded:
            parts.append(
                _("Images downloaded: %(new)d (already there: %(old)d).")
                % {"new": result.downloaded, "old": result.already_downloaded}
            )
        if result.media_added:
            parts.append(_("Media added: %d.") % result.media_added)
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

    def cb_attach(self, _widget: Any = None) -> None:
        """
        Attach the selected NARA record to the target person as a source and
        citation, downloading its images when asked.
        """
        model, tree_iter = self.tree_view.get_selection().get_selected()
        target = self.target_handle
        if tree_iter is None or not target or not self._has_target():
            return
        hit = model.get_value(tree_iter, 7)
        if not hit:
            return
        parsed = NaraCatalogInterface.parse_record(hit)
        download = bool(self.download_check.get_active())
        max_images = int(self.max_images_spin.get_value())

        from gramps.gui.utils import ProgressMeter

        meter = None
        total = len(parsed["digital_objects"])
        if max_images > 0:
            total = min(total, max_images)
        if download and total:
            meter = ProgressMeter(_("Attach NARA Record"), can_cancel=True, parent=self)
            meter.set_pass(_("Downloading %d images from NARA...") % total, total)

        def progress(_done: int, _total: int) -> bool:
            if meter is None:
                return True
            meter.step()
            return not meter.get_cancelled()

        try:
            result = NaraRecordAttacher(self.dbstate.db).attach(
                target,
                parsed,
                download=download,
                max_images=max_images,
                progress=progress,
            )
        except Exception as err:
            LOG.warning("Failed to attach NARA record %s: %s", parsed["naid"], err)
            self.status_label.set_text(
                _("Could not attach the NARA record: %s") % str(err)
            )
            return
        finally:
            if meter is not None:
                meter.close()
        self.status_label.set_text(self._attach_summary(result))

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
        query = self.query_entry.get_text().strip()
        limit = int(self.limit_spin.get_value())
        selected_mat = self.material_combo.get_active_id() or None
        online_only = self.online_check.get_active()

        params: dict[str, Any] = {
            "query": query,
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
