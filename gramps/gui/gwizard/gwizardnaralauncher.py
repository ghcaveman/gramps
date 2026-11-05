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
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# NaraSearchDialog
#
# ------------------------------------------------------------
class NaraSearchDialog(Gtk.Dialog):
    """
    Search dialog prompting the user for National Archives Catalog search terms.
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
        parent: Any = None,
        default_query: str = "",
        default_api_key: str = "",
    ) -> None:
        """
        Initialize the NARA search dialog.

        :param parent: Parent window for transient positioning.
        :param default_query: Optional pre-filled search query.
        :param default_api_key: Optional pre-filled API key.
        """
        super().__init__(
            title=str(_("GWizard NARA Search")),
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(520, 260)
        self.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        self.add_button(_("_Search"), Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        content = self.get_content_area()
        content.set_spacing(12)
        content.set_border_width(12)

        header_label = Gtk.Label()
        header_label.set_markup(_("<b>Search the National Archives (NARA) Catalog</b>"))
        header_label.set_xalign(0.0)
        content.pack_start(header_label, False, False, 0)

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(12)
        content.pack_start(grid, True, True, 0)

        # 1. Search Query
        query_label = Gtk.Label(label=_("Search Query:"))
        query_label.set_xalign(0.0)
        grid.attach(query_label, 0, 0, 1, 1)

        self.query_entry = Gtk.Entry()
        self.query_entry.set_hexpand(True)
        self.query_entry.set_text(default_query)
        self.query_entry.set_placeholder_text(
            _("e.g. Abraham Lincoln, Civil War Pension")
        )
        self.query_entry.connect("activate", self.cb_entry_activate)
        grid.attach(self.query_entry, 1, 0, 1, 1)

        # 2. API Key
        key_label = Gtk.Label(label=_("API Key (optional):"))
        key_label.set_xalign(0.0)
        grid.attach(key_label, 0, 1, 1, 1)

        env_key = (
            os.environ.get("NARA_API_KEY") or os.environ.get("CATALOG_API_KEY") or ""
        )
        initial_key = default_api_key or env_key
        self.key_entry = Gtk.Entry()
        self.key_entry.set_hexpand(True)
        self.key_entry.set_text(initial_key)
        self.key_entry.set_placeholder_text(_("Optional (tracks monthly quota)"))
        self.key_entry.set_tooltip_text(
            _(
                "NARA API key obtained from Catalog_API@nara.gov. "
                "Optional for standard usage, but increases rate limits."
            )
        )
        grid.attach(self.key_entry, 1, 1, 1, 1)

        # 3. Maximum records
        limit_label = Gtk.Label(label=_("Maximum Records:"))
        limit_label.set_xalign(0.0)
        grid.attach(limit_label, 0, 2, 1, 1)

        limit_adj = Gtk.Adjustment(value=10, lower=1, upper=100, step_increment=5)
        self.limit_spin = Gtk.SpinButton(adjustment=limit_adj, climb_rate=1, digits=0)
        grid.attach(self.limit_spin, 1, 2, 1, 1)

        # 4. Material Type
        mat_label = Gtk.Label(label=_("Material Type:"))
        mat_label.set_xalign(0.0)
        grid.attach(mat_label, 0, 3, 1, 1)

        self.material_combo = Gtk.ComboBoxText()
        for code, label in self.MATERIAL_TYPES:
            self.material_combo.append(code, label)
        self.material_combo.set_active(0)
        grid.attach(self.material_combo, 1, 3, 1, 1)

        # 5. Online / Digitized only
        self.online_check = Gtk.CheckButton(
            label=_("Only records with online digital media")
        )
        self.online_check.set_active(False)
        grid.attach(self.online_check, 1, 4, 1, 1)

        self.show_all()

    def cb_entry_activate(self, _widget: Gtk.Entry) -> None:
        """
        Trigger dialog submission when pressing Enter in the query entry.
        """
        self.response(Gtk.ResponseType.OK)

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
    params = dialog.get_query_parameters() if response == Gtk.ResponseType.OK else None
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
    try:
        from gwizardnara import NaraGWizard
    except ImportError:
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
    prompt for search terms, query NARA, load into memory, open compare window.

    :param uistate: Active Gramps UI state manager.
    :param dbstate: Active Gramps database state manager.
    :param parent: Optional parent GTK window.
    :returns: True if the compare window was successfully launched.
    """
    from gramps.gui.dialog import ErrorDialog, OkDialog
    from gramps.gui.utils import ProgressMeter

    if parent is None:
        try:
            parent = uistate.window
        except Exception:  # pylint: disable=broad-except
            parent = None

    default_query = ""
    try:
        active_handle = uistate.get_active("Person")
        if active_handle and dbstate and dbstate.db:
            active_person = dbstate.db.get_person_from_handle(active_handle)
            if active_person:
                default_query = active_person.get_primary_name().get_name()
    except Exception:  # pylint: disable=broad-except
        default_query = ""

    params = ask_nara_parameters(parent, default_query=default_query)
    if not params or not params.get("query"):
        return False

    meter = ProgressMeter(
        str(_("Loading NARA Records")),
        str(_("Querying the National Archives Catalog...")),
        parent=parent,
    )
    meter.set_pass(
        str(_("Querying the National Archives Catalog...")),
        mode=ProgressMeter.MODE_ACTIVITY,
    )
    meter.step()

    try:
        gwizard = load_nara_gwizard(dbstate.db, params)
    except (ValueError, RuntimeError) as error:
        meter.close()
        ErrorDialog(_("Search Failed"), str(error), parent=parent)
        return False

    source_db = gwizard.context.get("source_db")
    person_count = source_db.get_number_of_people() if source_db else 0
    if person_count == 0:
        meter.close()
        OkDialog(
            _("No Records Found"),
            _("No matching records found in the National Archives Catalog for '%s'.")
            % params.get("query"),
            parent=parent,
        )
        return False

    meter.set_header(str(_("Building the comparison window...")))
    meter.step()
    try:
        try:
            from gwizardlauncher import open_compare_window
        except ImportError:
            from gramps.gui.gwizard.gwizardlauncher import open_compare_window

        open_compare_window(uistate, dbstate, gwizard, parent=parent)
    finally:
        meter.close()

    return True
