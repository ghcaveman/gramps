#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  The Gramps Project
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
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <https://www.gnu.org/licenses/>.
#

"""
Grizard Results gramplet: search external genealogy websites for the
active person and display the filtered results as a table.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

import threading
from html import escape as html_escape
from typing import Any

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
from gramps.gen.plug import Gramplet
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext

from gramps.gen.filters.rules.websearch import (
    BillionGravesSearch,
    FindAGraveSearch,
    WebSearchFilter,
)


def build_result_markup(website_name: str, results: list[dict[str, Any]]) -> str:
    """
    Build Pango markup listing the search results.

    :param website_name: Name of the website the results came from.
    :param results: Result dictionaries (name, birth, death, url).
    :returns: Pango markup string, or a "no results" message.
    """
    if not results:
        return _("<i>No matching records found.</i>")
    parts = [
        _("<b>%d matching record(s) — %s</b>") % (len(results), website_name),
        "",
    ]
    for result in results:
        name = html_escape(str(result.get("name", "Unknown")))
        birth = str(result.get("birth") or "")
        death = str(result.get("death") or "")
        url = html_escape(str(result.get("url", "")), quote=True)
        years = ""
        if birth or death:
            years = " (%s–%s)" % (birth or "?", death or "?")
        if url:
            parts.append(f'<a href="{url}">{name}</a>{years}')
        else:
            parts.append(f"{name}{years}")
    return "\n".join(parts)


# -------------------------------------------------------------------------
#
# GrizardResultsGramplet
#
# -------------------------------------------------------------------------
class GrizardResultsGramplet(Gramplet):
    """
    Gramplet that searches external websites for the active person.

    Shows the person's name and vital dates, a Search button per
    supported website, the filtered search results as clickable links,
    and a button to view the fetched page in the HTML view.
    """

    # Website filter classes offered as search buttons
    SEARCH_FILTERS: list[type[WebSearchFilter]] = [
        FindAGraveSearch,
        BillionGravesSearch,
    ]

    def init(self):
        """Build the gramplet GUI."""
        self.gui.WIDGET = self.build_gui()
        self.gui.get_container_widget().remove(self.gui.textview)
        self.gui.get_container_widget().add(self.gui.WIDGET)

        self._searching = False
        self._last_page_html = ""
        self._last_url = ""

    def build_gui(self) -> Gtk.Widget:
        """
        Build the gramplet widgets.

        :returns: The top widget.
        """
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self.person_label = Gtk.Label(halign=Gtk.Align.START)
        self.person_label.set_selectable(True)
        self.person_label.set_use_markup(True)
        self.person_label.set_line_wrap(True)
        vbox.pack_start(self.person_label, False, False, 2)

        self.button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for filter_class in self.SEARCH_FILTERS:
            button = Gtk.Button(label=_("Search %s") % filter_class.WEBSITE_NAME)
            button.connect("clicked", self.cb_search_clicked, filter_class)
            self.button_box.pack_start(button, False, False, 0)
        vbox.pack_start(self.button_box, False, False, 2)

        self.status_label = Gtk.Label(halign=Gtk.Align.START)
        self.status_label.set_use_markup(True)
        vbox.pack_start(self.status_label, False, False, 2)

        self.results_label = Gtk.Label(halign=Gtk.Align.START, valign=Gtk.Align.START)
        self.results_label.set_selectable(True)
        self.results_label.set_use_markup(True)
        self.results_label.set_line_wrap(True)
        self.results_label.set_xalign(0.0)
        self.results_label.set_yalign(0.0)

        results_scroll = Gtk.ScrolledWindow()
        results_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        results_scroll.add(self.results_label)
        vbox.pack_start(results_scroll, True, True, 2)

        self.view_button = Gtk.Button(label=_("View page in HTML view"))
        self.view_button.connect("clicked", self.cb_view_in_html)
        self.view_button.set_sensitive(False)
        vbox.pack_start(self.view_button, False, False, 2)

        vbox.show_all()
        return vbox

    # -------------------------------------------------------------------------
    #
    # Person display
    #
    # -------------------------------------------------------------------------

    def db_changed(self):
        """React to database changes."""
        self.connect(self.dbstate.db, "person-update", self.update)

    def active_changed(self, handle):
        """React to active person changes."""
        self.update()

    def update(self):
        """Refresh the person summary shown at the top of the gramplet."""
        person, db = self._get_active_person()
        if person is None or db is None:
            self.person_label.set_markup(_("<i>No active person.</i>"))
            return

        from gramps.gen.display.name import displayer as name_displayer
        from gramps.gen.display.place import displayer as place_displayer
        from gramps.gen.datehandler import get_date
        from gramps.gen.lib import EventType

        name = name_displayer.display(person)
        birth_date = birth_place = death_date = ""
        for event_ref in person.get_event_ref_list():
            if not event_ref:
                continue
            try:
                event = db.get_event_from_handle(event_ref.ref)
            except Exception:
                continue
            if event is None:
                continue
            if int(event.type) == EventType.BIRTH and not birth_date:
                birth_date = get_date(event) or ""
                if event.get_place_handle():
                    place = db.get_place_from_handle(event.get_place_handle())
                    if place is not None:
                        birth_place = place_displayer.display(db, place)
            elif int(event.type) == EventType.DEATH and not death_date:
                death_date = get_date(event) or ""

        from html import escape

        parts = [f"<b>{escape(name)}</b>"]
        if birth_date or birth_place:
            parts.append(
                _("Born: %s")
                % escape(" ".join(p for p in (birth_date, birth_place) if p))
            )
        if death_date:
            parts.append(_("Died: %s") % escape(death_date))
        self.person_label.set_markup("\n".join(parts))

    def _get_active_person(self) -> tuple[Any, Any]:
        """
        Return the active person and database, or ``(None, None)``.
        """
        try:
            handle = self.get_active("Person")
            if handle:
                db = self.dbstate.db
                return db.get_person_from_handle(handle), db
        except Exception:
            pass
        return None, None

    # -------------------------------------------------------------------------
    #
    # Searching
    #
    # -------------------------------------------------------------------------

    def cb_search_clicked(self, widget: Gtk.Button, filter_class) -> None:
        """
        Callback for a website search button click.

        Runs the search in a background thread so the UI stays
        responsive.

        :param widget: The clicked button.
        :param filter_class: The WebSearchFilter subclass to run.
        """
        if self._searching:
            return
        person, db = self._get_active_person()
        if person is None or db is None:
            self.status_label.set_markup(_("<i>No active person.</i>"))
            return

        self._searching = True
        self._set_buttons_sensitive(False)
        self.status_label.set_markup(
            _("<i>Searching %s…</i>") % filter_class.WEBSITE_NAME
        )
        self.results_label.set_markup("")
        self.view_button.set_sensitive(False)

        thread = threading.Thread(
            target=self._run_search, args=(filter_class(), person, db), daemon=True
        )
        thread.start()

    def _set_buttons_sensitive(self, sensitive: bool) -> None:
        """
        Enable or disable the search buttons.
        """
        for child in self.button_box.get_children():
            child.set_sensitive(sensitive)

    def _run_search(self, web_filter, person, db) -> None:
        """
        Perform the search (runs in a background thread).

        :param web_filter: The filter instance to search with.
        :param person: The person to search for.
        :param db: The database.
        """
        try:
            params = web_filter.extract_search_params(person, db)
            url = web_filter.get_search_url(params)
            page_html = web_filter._fetch_page(url)
            results = web_filter.parse_results(page_html or "", url)
            GLib.idle_add(
                self._show_results, web_filter.WEBSITE_NAME, url, page_html, results
            )
        except Exception as err:
            GLib.idle_add(self._show_error, str(err))

    def _show_results(self, website_name, url, page_html, results) -> bool:
        """
        Display search results in the gramplet (runs on the GUI thread).
        """
        self._searching = False
        self._set_buttons_sensitive(True)
        self.status_label.set_markup(_("<i>Done — %s</i>") % website_name)
        self.results_label.set_markup(build_result_markup(website_name, results))
        self._last_page_html = page_html or ""
        self._last_url = url or ""
        self.view_button.set_sensitive(bool(self._last_page_html))
        return False  # remove idle callback

    def _show_error(self, message: str) -> bool:
        """
        Display a search error (runs on the GUI thread).
        """
        self._searching = False
        self._set_buttons_sensitive(True)
        from html import escape

        self.status_label.set_markup(
            _('<span foreground="red"><b>Search failed:</b> %s</span>')
            % escape(message)
        )
        return False  # remove idle callback

    # -------------------------------------------------------------------------
    #
    # HTML view passthrough
    #
    # -------------------------------------------------------------------------

    def cb_view_in_html(self, widget: Gtk.Button) -> None:
        """
        Callback to show the last fetched page in the HTML view.
        """
        if not self._last_page_html:
            return
        try:
            from gramps.gui.htmlbridge import HtmlBridge

            HtmlBridge.route_html(self._last_url, self._last_page_html)
        except Exception as err:
            self.status_label.set_markup(
                _('<span foreground="red"><b>Cannot open HTML view:</b> %s</span>')
                % str(err)
            )
