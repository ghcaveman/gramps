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

"""Grizard GEDCOM import launcher gramplet."""

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
from gramps.gen.lib import Person
from gramps.gen.plug import Gramplet
from gramps.gen.plug.menu import NumberOption

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 0.5
_MAX_CANDIDATES = 50
_THRESHOLD_LABEL = "Match threshold"


# ------------------------------------------------------------
#
# Helper functions (GTK-free, unit testable)
#
# ------------------------------------------------------------
def format_candidate_label(candidate: dict[str, Any]) -> str:
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


def build_status_text(
    gedcom_path: str | None,
    source_count: int,
    candidate_count: int,
    active_name: str | None = None,
) -> str:
    """
    Build the one-line status summary shown in the gramplet.
    """
    if not gedcom_path:
        return str(_("Select a GEDCOM file and click Load."))
    base = str(
        _("Loaded %(count)d people from %(path)s.")
        % {"count": source_count, "path": os.path.basename(gedcom_path)}
    )
    if active_name:
        return (
            base
            + " "
            + str(
                _("%(cand)d candidates for %(name)s.")
                % {"cand": candidate_count, "name": active_name}
            )
        )
    return (
        base
        + " "
        + str(_("%(cand)d candidates (no active person).") % {"cand": candidate_count})
    )


def clamp_threshold(value: Any) -> float:
    """
    Clamp a threshold option value into the 0.0-4.0 range.
    """
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD
    return max(0.0, min(4.0, threshold))


# ------------------------------------------------------------
#
# GrizardGramplet
#
# ------------------------------------------------------------
class GrizardGramplet(Gramplet):
    """
    Launcher gramplet for the GedGrizard compare/merge workflow.
    """

    def init(self) -> None:
        """Construct the GUI and restore the persisted GEDCOM path."""
        self.grizard = None
        self.source_people: list[Person] = []
        self.candidates: list[dict[str, Any]] = []
        self.gui.WIDGET = self.build_gui()
        self.gui.get_container_widget().remove(self.gui.textview)
        self.gui.get_container_widget().add(self.gui.WIDGET)
        self.gui.WIDGET.show()
        self.set_tooltip(_("Load a GEDCOM file, review matches, open Compare."))
        if len(self.gui.data) >= 1 and self.gui.data[0]:
            self.file_entry.set_text(str(self.gui.data[0]))

    def build_gui(self) -> Gtk.Box:
        """Build the GUI interface."""
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        top.set_border_width(6)
        file_row = Gtk.Box(spacing=6)
        self.file_entry = Gtk.Entry()
        self.file_entry.set_placeholder_text(_("Path to .ged file"))
        self.file_entry.set_hexpand(True)
        browse = Gtk.Button(label=_("Browse..."))
        browse.connect("clicked", self.cb_browse_clicked)
        file_row.pack_start(self.file_entry, True, True, 0)
        file_row.pack_start(browse, False, False, 0)
        top.pack_start(file_row, False, False, 0)
        load = Gtk.Button(label=_("Load GEDCOM"))
        load.connect("clicked", self.cb_load_clicked)
        top.pack_start(load, False, False, 0)
        self.status_label = Gtk.Label(halign=Gtk.Align.START)
        self.status_label.set_line_wrap(True)
        self.status_label.set_selectable(True)
        top.pack_start(self.status_label, False, False, 0)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(120)
        self.store = Gtk.ListStore(str, str, str)
        tree = Gtk.TreeView(model=self.store)
        for index, title in enumerate((_("Candidate"), _("Score"), _("Target"))):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            tree.append_column(column)
        self.tree = tree
        scrolled.add(tree)
        top.pack_start(scrolled, True, True, 0)
        self.compare_button = Gtk.Button(label=_("Open Compare..."))
        self.compare_button.set_sensitive(False)
        self.compare_button.connect("clicked", self.cb_compare_clicked)
        top.pack_start(self.compare_button, False, False, 0)
        self.refresh_button = Gtk.Button(label=_("Refresh Matches"))
        self.refresh_button.connect("clicked", self.cb_refresh_clicked)
        top.pack_start(self.refresh_button, False, False, 0)
        return top

    def build_options(self) -> None:
        """Build the threshold option."""
        threshold = NumberOption(
            _(_THRESHOLD_LABEL), _DEFAULT_THRESHOLD, 0.0, 4.0, 0.05
        )
        threshold.set_help(_("Minimum match score to list a candidate."))
        self.add_option(threshold)

    def on_save(self) -> None:
        """Persist the GEDCOM path in the gramplet data."""
        path = self.file_entry.get_text().strip() if hasattr(self, "file_entry") else ""
        self.gui.data[:] = [path]

    def active_changed(self, handle: str | None) -> None:
        """Refresh matches when the active person changes."""
        self.refresh_matches()

    def db_changed(self) -> None:
        """Clear cached source state when the database changes."""
        self.grizard = None
        self.source_people = []
        self.candidates = []
        self.connect_signal("Person", self._active_changed)
        self.update()

    def main(self) -> Any:
        """Refresh the status line and candidate list."""
        yield True
        if not self.dbstate.is_open():
            self.status_label.set_text(_("No Family Tree loaded."))
            self.set_has_data(False)
            yield False
            return
        if self.grizard is None:
            path = self.file_entry.get_text().strip()
            if path:
                self._load_gedcom(path)
            else:
                self.status_label.set_text(_("Select a GEDCOM file and click Load."))
                self.set_has_data(False)
                yield False
                return
        self.refresh_matches()
        yield False

    def update_has_data(self) -> None:
        """Update the has-data indicator when hidden."""
        self.set_has_data(self.grizard is not None and bool(self.source_people))

    def cb_browse_clicked(self, _button: Gtk.Button) -> None:
        """Open a file chooser for GEDCOM files."""
        dialog = Gtk.FileChooserDialog(
            title=_("Select GEDCOM file"),
            transient_for=self.gui.uistate.window,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            _("_Cancel"), Gtk.ResponseType.CANCEL, _("_Open"), Gtk.ResponseType.OK
        )
        ged_filter = Gtk.FileFilter()
        ged_filter.set_name(_("GEDCOM Files (*.ged)"))
        ged_filter.add_pattern("*.ged")
        dialog.add_filter(ged_filter)
        if dialog.run() == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            if filename:
                self.file_entry.set_text(filename)
        dialog.destroy()

    def cb_load_clicked(self, _button: Gtk.Button) -> None:
        """Load the GEDCOM file from the entry path."""
        self._load_gedcom(self.file_entry.get_text().strip())
        self.refresh_matches()

    def cb_refresh_clicked(self, _button: Gtk.Button) -> None:
        """Re-run matching for the active person."""
        self.refresh_matches()

    def cb_compare_clicked(self, _button: Gtk.Button) -> None:
        """Open the side-by-side compare window for the loaded GEDCOM."""
        from gramps.gui.grizard.grizardcompare import GrizardCompareWindow

        if self.grizard is None:
            return
        window = GrizardCompareWindow(
            self.uistate,
            self.dbstate,
            self.grizard,
            parent=self.gui.uistate.window,
        )
        window.show()

    def _load_gedcom(self, path: str) -> None:
        """Run the GedGrizard connect and load steps."""
        from gramps.gen.grizard.gedcom import GedGrizard

        if not path or not os.path.isfile(path):
            self.status_label.set_text(_("Invalid GEDCOM path: %s") % path)
            self.set_has_data(False)
            return
        try:
            grizard = GedGrizard(self.dbstate.db)
            if not grizard.run_step("connect", gedcom_path=path):
                raise ValueError(_("Could not read the GEDCOM file."))
            self.source_people = grizard.run_step("load")
            self.grizard = grizard
            self.on_save()
        except Exception as error:
            LOG.error("Grizard gramplet failed to load GEDCOM: %s", error)
            self.grizard = None
            self.source_people = []
            self.status_label.set_text(_("Load failed: %s") % error)
            self.set_has_data(False)

    def refresh_matches(self) -> None:
        """Match the active (or first source) person against the tree."""
        if self.grizard is None or not self.source_people:
            return
        threshold = self._get_threshold()
        active_handle = self.get_active("Person")
        source_person = self._resolve_source_person(active_handle)
        if source_person is None:
            return
        try:
            self.candidates = self.grizard.run_step(
                "match",
                source_person_handle=source_person.handle,
                threshold=threshold,
            )[:_MAX_CANDIDATES]
        except Exception as error:
            LOG.error("Grizard gramplet match failed: %s", error)
            self.candidates = []
        self._fill_candidate_list(source_person)

    def _get_threshold(self) -> float:
        """Return the configured match threshold."""
        try:
            option = self.get_option(_("Match threshold"))
        except Exception:
            return _DEFAULT_THRESHOLD
        try:
            return clamp_threshold(option.get_value())
        except Exception:
            return _DEFAULT_THRESHOLD

    def _resolve_source_person(self, active_handle: str | None) -> Person | None:
        """Pick the source person to match: best match for active or first."""
        if not self.source_people:
            return None
        if active_handle and self.grizard is not None:
            try:
                active = self.dbstate.db.get_person_from_handle(active_handle)
            except Exception:
                active = None
            if active is not None:
                from gramps.gen.grizard.grizard import CandidateMatcher

                matcher = CandidateMatcher(self.dbstate.db)
                best: Person | None = None
                best_score = -1.0
                for person in self.source_people:
                    try:
                        score = matcher.score_match(person, active)
                    except Exception:
                        continue
                    if score > best_score:
                        best_score = score
                        best = person
                if best is not None:
                    return best
        return self.source_people[0]

    def _selected_source_handle(self) -> str | None:
        """Return the handle of the source person currently matched."""
        active_handle = self.get_active("Person")
        person = self._resolve_source_person(active_handle)
        return person.handle if person is not None else None

    def _fill_candidate_list(self, source_person: Person) -> None:
        """Populate the list store and status label."""
        self.store.clear()
        for candidate in self.candidates:
            self.store.append(
                [
                    format_candidate_label(candidate),
                    str(candidate.get("score", "")),
                    str(candidate.get("handle", "")),
                ]
            )
        has_candidates = bool(self.candidates)
        self.compare_button.set_sensitive(self.grizard is not None and has_candidates)
        try:
            active_name: str | None = source_person.get_primary_name().get_name()
        except Exception:
            active_name = None
        path = self.file_entry.get_text().strip() or None
        self.status_label.set_text(
            build_status_text(
                path, len(self.source_people), len(self.candidates), active_name
            )
        )
        self.set_has_data(has_candidates)
