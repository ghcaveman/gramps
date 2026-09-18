#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Brian Caudill
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

"""Tools/Family Tree Processing/Grizard Data Merge."""

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
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.const import URL_MANUAL_PAGE
from gramps.gen.errors import WindowActiveError
from gramps.gen.lib import Person
from gramps.gui.dialog import OkDialog
from gramps.gui.display import display_help
from gramps.gui.managedwindow import ManagedWindow
from gramps.gui.plug import tool

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 0.5
_MAX_CANDIDATES = 50
WIKI_HELP_PAGE = "%s_-_Tools" % URL_MANUAL_PAGE
WIKI_HELP_SEC = _("Grizard_Data_Merge", "manual")


# ------------------------------------------------------------
#
# GrizardMergeToolOptions
#
# ------------------------------------------------------------
class GrizardMergeToolOptions(tool.ToolOptions):
    """Defines options and provides handling interface."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        """Initialize the options."""
        tool.ToolOptions.__init__(self, name, person_id)
        self.options_dict = {
            "gedcom_path": "",
            "threshold": _DEFAULT_THRESHOLD,
        }
        self.options_help = {
            "gedcom_path": ("=path", "GEDCOM file to compare against"),
            "threshold": ("=num", "Match threshold", "Floating point number"),
        }


# ------------------------------------------------------------
#
# Helper functions (GTK-free, unit testable)
#
# ------------------------------------------------------------
def build_candidate_label(candidate: dict[str, Any]) -> str:
    """
    Format a match candidate dict for display.
    """
    name = str(candidate.get("name", "?"))
    birth_year = str(candidate.get("birth_year", ""))
    score = candidate.get("score", 0.0)
    try:
        score_text = f"{float(score):.2f}"
    except (TypeError, ValueError):
        score_text = "?"
    if birth_year:
        return f"{name} (b. {birth_year}) [{score_text}]"
    return f"{name} [{score_text}]"


def clamp_threshold(value: Any) -> float:
    """
    Clamp a threshold value into the 0.0-1.0 range.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD
    if number != number:  # NaN
        return _DEFAULT_THRESHOLD
    return max(0.0, min(1.0, number))


def resolve_compare_pair(
    candidates: list[dict[str, Any]],
    source_handle: str | None,
    selected_target: str | None,
) -> tuple[str | None, str | None]:
    """
    Resolve the (source, target) handle pair for the compare window.
    """
    if not source_handle:
        return (None, None)
    if selected_target:
        return (source_handle, selected_target)
    if candidates:
        return (source_handle, str(candidates[0].get("handle", "")) or None)
    return (source_handle, None)


# ------------------------------------------------------------
#
# GrizardMergeTool
#
# ------------------------------------------------------------
class GrizardMergeTool(tool.Tool, ManagedWindow):
    """On-top dialog tool that finds Grizard merge candidates."""

    def __init__(
        self,
        dbstate: Any,
        user: Any,
        options_class: Any,
        name: str,
        callback: Any = None,
    ) -> None:
        """Initialize the tool dialog."""
        uistate = user.uistate
        tool.Tool.__init__(self, dbstate, options_class, name)
        try:
            ManagedWindow.__init__(self, uistate, [], self.__class__)
        except WindowActiveError:
            return
        self.dbstate = dbstate
        self.uistate = uistate
        self.grizard: Any = None
        self.source_people: list[Person] = []
        self.candidates: list[dict[str, Any]] = []

        window = Gtk.Dialog(title=_("Grizard Data Merge"))
        window.set_default_size(560, 420)
        window.set_modal(False)
        window.set_transient_for(uistate.window)
        self.set_window(window, None, _("Grizard Data Merge"))
        self.setup_configs("interface.grizardmergetool", 560, 420)
        content = window.get_content_area()
        content.set_spacing(6)
        content.set_border_width(12)

        file_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.file_entry = Gtk.Entry()
        self.file_entry.set_hexpand(True)
        self.file_entry.set_placeholder_text(_("Select a GEDCOM file..."))
        saved_path = str(self.options.options_dict.get("gedcom_path", "") or "")
        if saved_path:
            self.file_entry.set_text(saved_path)
        browse_button = Gtk.Button(label=_("Browse..."))
        browse_button.connect("clicked", self.cb_browse_clicked)
        file_row.pack_start(Gtk.Label(label=_("GEDCOM:")), False, False, 0)
        file_row.pack_start(self.file_entry, True, True, 0)
        file_row.pack_start(browse_button, False, False, 0)
        content.pack_start(file_row, False, False, 0)

        option_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.threshold_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        self.threshold_spin.set_digits(2)
        saved_threshold = clamp_threshold(
            self.options.options_dict.get("threshold", _DEFAULT_THRESHOLD)
        )
        self.threshold_spin.set_value(saved_threshold)
        self.load_button = Gtk.Button(label=_("Load"))
        self.load_button.connect("clicked", self.cb_load_clicked)
        self.refresh_button = Gtk.Button(label=_("Refresh Matches"))
        self.refresh_button.connect("clicked", self.cb_refresh_clicked)
        self.thr_label = Gtk.Label(label=_("Match threshold:"))
        option_row.pack_start(self.thr_label, False, False, 0)
        option_row.pack_start(self.threshold_spin, False, False, 0)
        option_row.pack_start(self.load_button, False, False, 0)
        option_row.pack_start(self.refresh_button, False, False, 0)
        content.pack_start(option_row, False, False, 0)

        self.src_label = Gtk.Label(label=_("Source person:"))
        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.source_combo = Gtk.ComboBoxText()
        self.source_combo.set_hexpand(True)
        self.source_combo.connect("changed", self.cb_source_changed)
        source_row.pack_start(self.src_label, False, False, 0)
        source_row.pack_start(self.source_combo, True, True, 0)
        content.pack_start(source_row, False, False, 0)

        self.status_label = Gtk.Label(label=_("Select a GEDCOM file and click Load."))
        self.status_label.set_halign(Gtk.Align.START)
        content.pack_start(self.status_label, False, False, 0)

        self.store = Gtk.ListStore(str, str, str)
        self.tree = Gtk.TreeView(model=self.store)
        for index, title in enumerate((_("Candidate"), _("Score"), _("Handle"))):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            self.tree.append_column(column)
        self.tree.get_selection().connect("changed", self.cb_candidate_selected)
        self.tree.connect("row-activated", self.cb_candidate_activated)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add(self.tree)
        content.pack_start(scrolled, True, True, 0)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.compare_button = Gtk.Button(label=_("Open Compare..."))
        self.compare_button.set_sensitive(False)
        self.compare_button.connect("clicked", self.cb_compare_clicked)
        help_button = Gtk.Button(label=_("Help"))
        help_button.connect("clicked", self.cb_help_clicked)
        close_button = Gtk.Button(label=_("Close"))
        close_button.connect("clicked", self.cb_close_clicked)
        action_row.pack_start(self.compare_button, False, False, 0)
        action_row.pack_end(close_button, False, False, 0)
        action_row.pack_end(help_button, False, False, 0)
        content.pack_start(action_row, False, False, 0)

        try:
            active_handle = uistate.get_active("Person")
        except Exception:  # pylint: disable=broad-except
            active_handle = None
        self._active_handle: str | None = active_handle

        window.connect("delete-event", self.cb_close_clicked)
        self.show()
        saved = self.file_entry.get_text().strip()
        if saved and os.path.isfile(saved):
            self.cb_load_clicked(None)

    def build_menu_names(self, obj: Any) -> tuple[str, str]:
        """Return the menu names for the managed window."""
        return (_("Tool settings"), _("Grizard Data Merge"))

    def cb_help_clicked(self, obj: Any) -> None:
        """Display the relevant portion of the Gramps manual."""
        display_help(WIKI_HELP_PAGE, WIKI_HELP_SEC)

    def cb_close_clicked(self, obj: Any, event: Any = None) -> None:
        """Close the tool dialog."""
        self.close()
        return

    def cb_browse_clicked(self, obj: Any) -> None:
        """Open a file chooser to pick the GEDCOM file."""
        dialog = Gtk.FileChooserDialog(
            title=_("Select GEDCOM file"),
            parent=self.window,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            _("Cancel"),
            Gtk.ResponseType.CANCEL,
            _("Open"),
            Gtk.ResponseType.OK,
        )
        gedcom_filter = Gtk.FileFilter()
        gedcom_filter.set_name(_("GEDCOM files"))
        gedcom_filter.add_pattern("*.ged")
        dialog.add_filter(gedcom_filter)
        any_filter = Gtk.FileFilter()
        any_filter.set_name(_("All files"))
        any_filter.add_pattern("*")
        dialog.add_filter(any_filter)
        if dialog.run() == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            if filename:
                self.file_entry.set_text(filename)
        dialog.destroy()

    def cb_load_clicked(self, obj: Any) -> None:
        """Load the GEDCOM file into a Grizard session."""
        from gramps.gen.grizard.gedcom import GedGrizard

        path = self.file_entry.get_text().strip()
        if not path:
            OkDialog(_("No file selected"), _("Please select a GEDCOM file first."))
            return
        if not os.path.isfile(path):
            OkDialog(_("File not found"), _("The selected GEDCOM file is missing."))
            return
        try:
            self.grizard = GedGrizard(self.dbstate.db)
            self.grizard.run_step("connect", gedcom_path=path)
            people = self.grizard.run_step("load")
        except Exception as error:  # pylint: disable=broad-except
            LOG.error("Grizard tool failed to load GEDCOM: %s", error)
            OkDialog(_("Load failed"), str(error))
            self.grizard = None
            self.source_people = []
            self.candidates = []
            self._fill_source_combo()
            self._fill_candidate_list()
            return
        self.source_people = list(people or [])
        self.candidates = []
        self.options.options_dict["gedcom_path"] = path
        self.options.handler.save_options()
        self._fill_source_combo()
        self.cb_refresh_clicked(None)

    def cb_refresh_clicked(self, obj: Any) -> None:
        """Refresh match candidates for the selected source person."""
        if self.grizard is None:
            return
        threshold = clamp_threshold(self.threshold_spin.get_value())
        self.options.options_dict["threshold"] = threshold
        self.options.handler.save_options()
        source_person = self._resolve_source_person()
        if source_person is None:
            return
        try:
            self.candidates = self.grizard.run_step(
                "match",
                source_person_handle=source_person.handle,
                threshold=threshold,
            )[:_MAX_CANDIDATES]
        except Exception as error:  # pylint: disable=broad-except
            LOG.error("Grizard tool match failed: %s", error)
            self.candidates = []
        self._fill_candidate_list()

    def cb_source_changed(self, obj: Any) -> None:
        """Re-run matching when a different source person is picked."""
        if self.grizard is None or not self.source_people:
            return
        self.cb_refresh_clicked(None)

    def cb_candidate_selected(self, selection: Any) -> None:
        """Enable the compare button when candidates exist."""
        self.compare_button.set_sensitive(
            self.grizard is not None and bool(self.candidates)
        )

    def cb_candidate_activated(self, treeview: Any, path: Any, column: Any) -> None:
        """Open the compare window on double-click/Enter."""
        self.cb_compare_clicked(treeview)

    def cb_compare_clicked(self, obj: Any) -> None:
        """Open the compare window positioned on the selected pair."""
        if self.grizard is None:
            return
        from gramps.gui.grizard.grizardcompare import GrizardCompareWindow

        source_handle = self._selected_source_handle()
        target_handle = self._selected_candidate_handle()
        source, target = resolve_compare_pair(
            self.candidates, source_handle, target_handle
        )
        try:
            window = GrizardCompareWindow(self.uistate, self.dbstate, self.grizard)
            if source is not None:
                window.select_pair(source, target)
            window.show()
        except Exception as error:  # pylint: disable=broad-except
            LOG.error("Grizard tool failed to open compare window: %s", error)
            OkDialog(_("Could not open compare window"), str(error))

    def _resolve_source_person(self) -> Person | None:
        """Return the source person selected in the combo."""
        if not self.source_people:
            return None
        index = self.source_combo.get_active()
        if index is not None and 0 <= index < len(self.source_people):
            return self.source_people[index]
        return self.source_people[0]

    def _selected_source_handle(self) -> str | None:
        """Return the handle of the selected source person."""
        person = self._resolve_source_person()
        return person.handle if person is not None else None

    def _selected_candidate_handle(self) -> str | None:
        """Return the target handle of the selected candidate row."""
        try:
            _model, treeiter = self.tree.get_selection().get_selected()
        except Exception:  # pylint: disable=broad-except
            return None
        if treeiter is None:
            return None
        try:
            handle = self.store[treeiter][2]
        except Exception:  # pylint: disable=broad-except
            return None
        return str(handle) if handle else None

    def _fill_source_combo(self) -> None:
        """Populate the source person combo box."""
        self.source_combo.remove_all()
        for person in self.source_people:
            try:
                label = person.get_primary_name().get_name()
            except Exception:  # pylint: disable=broad-except
                label = _("Unknown")
            self.source_combo.append_text(f"{label} [{person.gramps_id}]")
        if self.source_people:
            best = self._best_for_active()
            self.source_combo.set_active(best if best is not None else 0)
        self._fill_status()

    def _best_for_active(self) -> int | None:
        """Return the combo index of the best source match for active."""
        if not self._active_handle or self.grizard is None:
            return None
        try:
            active = self.dbstate.db.get_person_from_handle(self._active_handle)
        except Exception:  # pylint: disable=broad-except
            return None
        if active is None:
            return None
        from gramps.gen.grizard.grizard import CandidateMatcher

        matcher = CandidateMatcher(self.dbstate.db)
        source_db = self.grizard.context.get("source_db")
        best_index: int | None = None
        best_score = -1.0
        for index, person in enumerate(self.source_people):
            try:
                score = matcher.score_match(person, active, source_db=source_db)
            except Exception:  # pylint: disable=broad-except
                continue
            if score > best_score:
                best_score = score
                best_index = index
        return best_index

    def _fill_candidate_list(self) -> None:
        """Populate the candidate list store and status label."""
        self.store.clear()
        for candidate in self.candidates:
            self.store.append(
                [
                    build_candidate_label(candidate),
                    str(candidate.get("score", "")),
                    str(candidate.get("handle", "")),
                ]
            )
        self.compare_button.set_sensitive(
            self.grizard is not None and bool(self.candidates)
        )
        self._fill_status()

    def _fill_status(self) -> None:
        """Update the one-line status summary."""
        path = self.file_entry.get_text().strip()
        if not path:
            self.status_label.set_text(_("Select a GEDCOM file and click Load."))
            return
        self.status_label.set_text(
            _("Loaded %(count)d people from %(path)s. %(cand)d candidates shown.")
            % {
                "count": len(self.source_people),
                "path": os.path.basename(path),
                "cand": len(self.candidates),
            }
        )
