#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Devin
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
GTK3 Assistant implementation for Grizard imports.
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
# GTK/Gnome modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk
from gi.repository import Gdk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.lib import Person
from gramps.gen.grizard.gedcom import GedGrizard
from gramps.gen.grizard.grizard import GrizardCompareRow
from gramps.gen.display.name import displayer as name_displayer
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.managedwindow import ManagedWindow
from gramps.gui.dialog import ErrorDialog, InfoDialog

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)

_ = glocale.translation.gettext


# ------------------------------------------------------------
#
# GrizardAssistant
#
# ------------------------------------------------------------
class GrizardAssistant(ManagedWindow, Gtk.Assistant):
    """
    A step-by-step wizard to import, match, compare, and merge GEDCOM data.
    """

    def __init__(
        self, uistate: Any, dbstate: Any, parent: Gtk.Window | None = None
    ) -> None:
        """
        Initialize the Grizard import assistant.

        :param uistate: Active Gramps UI state manager.
        :param dbstate: Active Gramps DB state manager.
        :param parent: Parent window.
        """
        Gtk.Assistant.__init__(self)
        ManagedWindow.__init__(self, uistate, [], self.__class__)

        self.dbstate = dbstate
        self.grizard = GedGrizard(self.dbstate.db)
        self.resolutions: dict[str, str] = {}

        self.set_title(_("Grizard Import Wizard"))
        self.set_default_size(700, 500)
        if parent:
            self.set_transient_for(parent)

        # Setup pages
        self._setup_connect_page()
        self._setup_load_page()
        self._setup_match_page()
        self._setup_compare_page()
        self._setup_confirm_page()

        # Connect callbacks
        self.connect("prepare", self.cb_prepare)
        self.connect("apply", self.cb_apply)
        self.connect("cancel", self.cb_cancel)
        self.connect("close", self.cb_close)

    def _setup_connect_page(self) -> None:
        """
        Create Step 1 page: Select GEDCOM file.
        """
        self.connect_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        self.connect_box.set_border_width(20)

        label = Gtk.Label(
            label=_("Please select a GEDCOM file to begin the import process:")
        )
        label.set_xalign(0.0)
        self.connect_box.pack_start(label, False, False, 0)

        # File chooser
        self.file_chooser = Gtk.FileChooserButton(
            title=_("Select GEDCOM File"), action=Gtk.FileChooserAction.OPEN
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("GEDCOM Files (*.ged)"))
        file_filter.add_pattern("*.ged")
        self.file_chooser.add_filter(file_filter)
        self.file_chooser.connect("file-set", self.cb_file_changed)

        self.connect_box.pack_start(self.file_chooser, False, False, 0)

        self.append_page(self.connect_box)
        self.set_page_title(self.connect_box, _("Select Import File"))
        self.set_page_type(self.connect_box, Gtk.AssistantPageType.INTRO)
        self.set_page_complete(self.connect_box, False)

    def _setup_load_page(self) -> None:
        """
        Create Step 2 page: Select primary source person.
        """
        self.load_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.load_box.set_border_width(15)

        self.load_label = Gtk.Label(
            label=_("Please select the person you wish to migrate from the list below:")
        )
        self.load_label.set_xalign(0.0)
        self.load_box.pack_start(self.load_label, False, False, 0)

        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # ListStore representing: handle, name, gender, birth date
        self.source_people_store = Gtk.ListStore(str, str, str, str)
        self.source_people_tree = Gtk.TreeView(model=self.source_people_store)

        # Columns
        col_name = Gtk.TreeViewColumn(_("Name"), Gtk.CellRendererText(), text=1)
        col_gender = Gtk.TreeViewColumn(_("Gender"), Gtk.CellRendererText(), text=2)
        col_birth = Gtk.TreeViewColumn(_("Birth"), Gtk.CellRendererText(), text=3)

        self.source_people_tree.append_column(col_name)
        self.source_people_tree.append_column(col_gender)
        self.source_people_tree.append_column(col_birth)

        self.source_people_tree.get_selection().connect(
            "changed", self.cb_person_selected
        )

        scrolled.add(self.source_people_tree)
        self.load_box.pack_start(scrolled, True, True, 0)

        self.append_page(self.load_box)
        self.set_page_title(self.load_box, _("Choose Source Person"))
        self.set_page_type(self.load_box, Gtk.AssistantPageType.CONTENT)
        self.set_page_complete(self.load_box, False)

    def _setup_match_page(self) -> None:
        """
        Create Step 3 page: Select matching database candidate.
        """
        self.match_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.match_box.set_border_width(15)

        label = Gtk.Label(
            label=_(
                "Select a potential duplicate from the target database to merge, or choose to add as a new person:"
            )
        )
        label.set_xalign(0.0)
        self.match_box.pack_start(label, False, False, 0)

        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # ListStore representing: handle, display text, birth year, match score
        self.candidates_store = Gtk.ListStore(str, str, str, str)
        self.candidates_tree = Gtk.TreeView(model=self.candidates_store)

        # Columns
        col_display = Gtk.TreeViewColumn(
            _("Person / Resolution"), Gtk.CellRendererText(), text=1
        )
        col_birth = Gtk.TreeViewColumn(_("Birth Year"), Gtk.CellRendererText(), text=2)
        col_score = Gtk.TreeViewColumn(_("Match Score"), Gtk.CellRendererText(), text=3)

        self.candidates_tree.append_column(col_display)
        self.candidates_tree.append_column(col_birth)
        self.candidates_tree.append_column(col_score)

        self.candidates_tree.get_selection().connect(
            "changed", self.cb_candidate_selected
        )

        scrolled.add(self.candidates_tree)
        self.match_box.pack_start(scrolled, True, True, 0)

        self.append_page(self.match_box)
        self.set_page_title(self.match_box, _("Match Target Candidate"))
        self.set_page_type(self.match_box, Gtk.AssistantPageType.CONTENT)
        self.set_page_complete(self.match_box, True)

    def _setup_compare_page(self) -> None:
        """
        Create Step 4 page: Compare side-by-side selective grid.
        """
        self.compare_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.compare_box.set_border_width(15)

        label = Gtk.Label(
            label=_("Configure individual fields comparison actions below:")
        )
        label.set_xalign(0.0)
        self.compare_box.pack_start(label, False, False, 0)

        # Grid / Scrolled Window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # ListStore representing: field_type, field label, resolution chosen, source val, target val
        self.compare_store = Gtk.ListStore(str, str, str, str, str)
        self.compare_tree = Gtk.TreeView(model=self.compare_store)

        col_field = Gtk.TreeViewColumn(_("Field"), Gtk.CellRendererText(), text=1)
        col_res = Gtk.TreeViewColumn(_("Action"), Gtk.CellRendererText(), text=2)
        col_s_val = Gtk.TreeViewColumn(
            _("Source Value"), Gtk.CellRendererText(), text=3
        )
        col_t_val = Gtk.TreeViewColumn(
            _("Target Value"), Gtk.CellRendererText(), text=4
        )

        self.compare_tree.append_column(col_field)
        self.compare_tree.append_column(col_res)
        self.compare_tree.append_column(col_s_val)
        self.compare_tree.append_column(col_t_val)

        self.compare_tree.get_selection().connect(
            "changed", self.cb_compare_row_selected
        )

        scrolled.add(self.compare_tree)
        self.compare_box.pack_start(scrolled, True, True, 0)

        # Detail master-control frame below comparison list
        self.detail_frame = Gtk.Frame(label=_("Resolution Details"))
        self.detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.detail_box.set_border_width(10)

        self.radio_source = Gtk.RadioButton.new_with_label(
            None, _("Overwrite with Source value")
        )
        self.radio_target = Gtk.RadioButton.new_with_label_from_widget(
            self.radio_source, _("Keep Target value")
        )

        self.radio_source.connect("toggled", self.cb_resolution_toggled, "source")
        self.radio_target.connect("toggled", self.cb_resolution_toggled, "target")

        self.detail_box.pack_start(self.radio_source, False, False, 0)
        self.detail_box.pack_start(self.radio_target, False, False, 0)
        self.detail_frame.add(self.detail_box)

        self.compare_box.pack_start(self.detail_frame, False, False, 0)

        self.append_page(self.compare_box)
        self.set_page_title(self.compare_box, _("Compare Differences"))
        self.set_page_type(self.compare_box, Gtk.AssistantPageType.CONTENT)
        self.set_page_complete(self.compare_box, True)

    def _setup_confirm_page(self) -> None:
        """
        Create Step 5 page: Apply Changes.
        """
        self.confirm_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        self.confirm_box.set_border_width(20)

        label = Gtk.Label(
            label=_(
                "Wizard complete! Click Apply to commit changes and update your database."
            )
        )
        label.set_xalign(0.5)
        self.confirm_box.pack_start(label, True, True, 0)

        self.append_page(self.confirm_box)
        self.set_page_title(self.confirm_box, _("Apply Changes"))
        self.set_page_type(self.confirm_box, Gtk.AssistantPageType.CONFIRM)
        self.set_page_complete(self.confirm_box, True)

    def cb_file_changed(self, button: Gtk.FileChooserButton) -> None:
        """
        Handle Step 1 FileChooser choice validation.
        """
        path = button.get_filename()
        if path and os.path.isfile(path):
            success = self.grizard.run_step("connect", gedcom_path=path)
            self.set_page_complete(self.connect_box, success)

    def cb_person_selected(self, selection: Gtk.TreeSelection) -> None:
        """
        Handle Step 2 source person selection.
        """
        model, tree_iter = selection.get_selected()
        if tree_iter:
            handle = model.get_value(tree_iter, 0)
            self.context_source_handle = handle
            self.set_page_complete(self.load_box, True)

    def cb_candidate_selected(self, selection: Gtk.TreeSelection) -> None:
        """
        Handle Step 3 target candidate selection.
        """
        model, tree_iter = selection.get_selected()
        if tree_iter:
            handle = model.get_value(tree_iter, 0)
            # If "None" handle (add as new), clear compared candidate
            if handle == "None":
                self.context_target_handle = None
            else:
                self.context_target_handle = handle

    def cb_compare_row_selected(self, selection: Gtk.TreeSelection) -> None:
        """
        Handle comparison TreeView row click. Updates radio values.
        """
        model, tree_iter = selection.get_selected()
        if tree_iter:
            f_type = model.get_value(tree_iter, 0)
            res = self.resolutions.get(f_type, "target")

            # Block signal propagation during internal UI state syncs
            self.radio_source.disconnect_by_func(self.cb_resolution_toggled)
            self.radio_target.disconnect_by_func(self.cb_resolution_toggled)

            if res == "source":
                self.radio_source.set_active(True)
            else:
                self.radio_target.set_active(True)

            self.radio_source.connect("toggled", self.cb_resolution_toggled, "source")
            self.radio_target.connect("toggled", self.cb_resolution_toggled, "target")

    def cb_resolution_toggled(
        self, button: Gtk.RadioButton, resolution_val: str
    ) -> None:
        """
        Handle radio button toggling. Updates compare resolution values.
        """
        if button.get_active():
            selection = self.compare_tree.get_selection()
            model, tree_iter = selection.get_selected()
            if tree_iter:
                f_type = model.get_value(tree_iter, 0)
                self.resolutions[f_type] = resolution_val

                # Update comparative liststore UI column value
                display_val = (
                    _("Overwrite with Source")
                    if resolution_val == "source"
                    else _("Keep Target")
                )
                model.set_value(tree_iter, 2, display_val)

    def cb_prepare(self, assistant: Gtk.Assistant, page: Gtk.Widget) -> None:
        """
        Handle page transitioning. Connects step hooks dynamically on prepare.
        """
        if page == self.load_box:
            # Step 2: load people from parsed database proxy
            self.source_people_store.clear()
            try:
                people = self.grizard.run_step("load")
                self.load_label.set_text(
                    _(
                        "Loaded {num} people from GEDCOM. Please choose the person you wish to migrate:"
                    ).format(num=len(people))
                )
                for person in people:
                    name_str = name_displayer.display(person)
                    gender_str = (
                        _("Male") if person.get_gender() == Person.MALE else _("Female")
                    )
                    birth_ref = person.get_birth_ref()
                    birth_dt = ""
                    if birth_ref:
                        birth_evt = self.grizard.context[
                            "source_db"
                        ].get_event_from_handle(birth_ref.ref)
                        if birth_evt:
                            birth_dt = glocale.date_displayer.display(
                                birth_evt.get_date_object()
                            )

                    self.source_people_store.append(
                        [person.handle, name_str, gender_str, birth_dt]
                    )
            except Exception as e:
                LOG.error("Failed to load source database: %s", e)
                ErrorDialog(_("Load Failed"), str(e), parent=self)

        elif page == self.match_box:
            # Step 3: find potential target duplicate candidates in DB
            self.candidates_store.clear()
            # Default top option is to create a new person
            self.candidates_store.append(
                ["None", _("Add as entirely new person"), "", "N/A"]
            )
            try:
                candidates = self.grizard.run_step(
                    "match", source_person_handle=self.context_source_handle
                )
                for item in candidates:
                    h = item["handle"]
                    n = item["name"]
                    score = f"{item['score']:.2f}"
                    birth = item["birth_year"]
                    self.candidates_store.append([h, n, birth, score])
            except Exception as e:
                LOG.error("Failed to run matching process: %s", e)

            # Auto-select the top row ("Add as new")
            self.candidates_tree.set_cursor(Gtk.TreePath.new_first())

        elif page == self.compare_box:
            # Step 4: generate side-by-side comparisons
            self.compare_store.clear()
            self.resolutions.clear()

            if self.context_target_handle is None:
                # Add as entirely new -> skip comparison page dynamically
                self.next_page()
                return

            try:
                rows = self.grizard.run_step(
                    "compare",
                    source_person_handle=self.context_source_handle,
                    target_person_handle=self.context_target_handle,
                )
                for r in rows:
                    # Initialize default resolution choice
                    self.resolutions[r.field_type] = "target"
                    display_res = _("Keep Target")
                    self.compare_store.append(
                        [r.field_type, r.field, display_res, r.source_val, r.target_val]
                    )
            except Exception as e:
                LOG.error("Failed to run side-by-side comparison: %s", e)

            # Auto-select first comparison row
            self.compare_tree.set_cursor(Gtk.TreePath.new_first())

    def cb_apply(self, assistant: Gtk.Assistant) -> None:
        """
        Commit resolutions and merge/add operations securely under transaction on apply.
        """
        try:
            success = self.grizard.run_step(
                "apply",
                source_person_handle=self.context_source_handle,
                target_person_handle=getattr(self, "context_target_handle", None),
                resolutions=self.resolutions,
            )
            if success:
                InfoDialog(
                    _("Merge Complete"),
                    _(
                        "Genealogy records successfully processed and committed to your family tree!"
                    ),
                    parent=self,
                )
            else:
                ErrorDialog(
                    _("Apply Failed"),
                    _("Could not apply transactions securely."),
                    parent=self,
                )
        except Exception as e:
            LOG.error("Failed to apply resolutions: %s", e)
            ErrorDialog(_("Apply Failed"), str(e), parent=self)

    def cb_cancel(self, assistant: Gtk.Assistant) -> None:
        """
        Handle wizard cancel.
        """
        self.close()

    def cb_close(self, assistant: Gtk.Assistant) -> None:
        """
        Handle wizard close.
        """
        self.destroy()
