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
# WikiTreeSearchDialog
#
# ------------------------------------------------------------
class WikiTreeSearchDialog(Gtk.Dialog):
    """
    Search dialog prompting the user for WikiTree IDs or person search queries.
    """

    def __init__(
        self,
        parent: Any = None,
        default_query: str = "",
        default_ancestors: int = 0,
        default_app_id: str = "Gramps_GWizard_1.0",
    ) -> None:
        """
        Initialize the WikiTree search dialog.

        :param parent: Parent GTK window for transient placement.
        :param default_query: Pre-filled search query or WikiTree ID.
        :param default_ancestors: Default ancestor generations count.
        :param default_app_id: App ID passed to WikiTree API.
        """
        super().__init__(
            title=str(_("GWizard WikiTree Search")),
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(520, 230)
        self.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        self.add_button(_("_Search"), Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        content = self.get_content_area()
        content.set_spacing(12)
        content.set_border_width(12)

        header_label = Gtk.Label()
        header_label.set_markup(_("<b>Search and Merge from WikiTree</b>"))
        header_label.set_xalign(0.0)
        content.pack_start(header_label, False, False, 0)

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(12)
        content.pack_start(grid, True, True, 0)

        # 1. Query / WikiTree ID
        query_label = Gtk.Label(label=_("WikiTree ID or Name:"))
        query_label.set_xalign(0.0)
        grid.attach(query_label, 0, 0, 1, 1)

        self.query_entry = Gtk.Entry()
        self.query_entry.set_hexpand(True)
        self.query_entry.set_text(default_query)
        self.query_entry.set_placeholder_text(_("e.g. Franklin-1 or Benjamin Franklin"))
        self.query_entry.set_tooltip_text(
            _("Enter a specific WikiTree ID (e.g. 'Franklin-1') or a full person name.")
        )
        self.query_entry.connect("activate", self.cb_entry_activate)
        grid.attach(self.query_entry, 1, 0, 1, 1)

        # 2. Ancestor generations
        ancestor_label = Gtk.Label(label=_("Ancestor Generations:"))
        ancestor_label.set_xalign(0.0)
        grid.attach(ancestor_label, 0, 1, 1, 1)

        ancestor_adj = Gtk.Adjustment(
            value=default_ancestors, lower=0, upper=10, step_increment=1
        )
        self.ancestor_spin = Gtk.SpinButton(
            adjustment=ancestor_adj, climb_rate=1, digits=0
        )
        self.ancestor_spin.set_tooltip_text(
            _(
                "Generations of ancestors to fetch when querying by WikiTree ID "
                "(0 for person only, max 10)."
            )
        )
        grid.attach(self.ancestor_spin, 1, 1, 1, 1)

        # 3. App ID
        app_label = Gtk.Label(label=_("Application ID:"))
        app_label.set_xalign(0.0)
        grid.attach(app_label, 0, 2, 1, 1)

        self.app_entry = Gtk.Entry()
        self.app_entry.set_hexpand(True)
        self.app_entry.set_text(default_app_id)
        self.app_entry.set_tooltip_text(
            _(
                "Application identifier included in API requests to prevent "
                "aggressive rate limiting by WikiTree."
            )
        )
        grid.attach(self.app_entry, 1, 2, 1, 1)

        self.show_all()

    def cb_entry_activate(self, _widget: Gtk.Entry) -> None:
        """
        Trigger dialog submission when pressing Enter in the query entry.
        """
        self.response(Gtk.ResponseType.OK)

    def get_query_parameters(self) -> dict[str, Any]:
        """
        Retrieve user-entered parameters from the dialog fields.

        :returns: Parameter dictionary for WikiTreeGWizard.
        :rtype: dict[str, Any]
        """
        query = self.query_entry.get_text().strip()
        ancestors = int(self.ancestor_spin.get_value())
        app_id = self.app_entry.get_text().strip() or "Gramps_GWizard_1.0"

        return {
            "query": query,
            "ancestors": ancestors,
            "app_id": app_id,
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
    params = dialog.get_query_parameters() if response == Gtk.ResponseType.OK else None
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
    try:
        from gwizardwikitree import WikiTreeGWizard
    except ImportError:
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
    prompt for search terms, query WikiTree, load into memory, open compare window.

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
                # Look for existing WikiTree ID attribute first
                for attr in active_person.get_attribute_list():
                    attr_type = str(attr.get_type()).lower()
                    if "wikitree" in attr_type or attr_type == "_wtid":
                        default_query = attr.get_value()
                        break
                if not default_query:
                    default_query = active_person.get_primary_name().get_name()
    except Exception:  # pylint: disable=broad-except
        default_query = ""

    params = ask_wikitree_parameters(parent, default_query=default_query)
    if not params or not params.get("query"):
        return False

    meter = ProgressMeter(
        str(_("Loading WikiTree Profiles")),
        str(_("Querying the WikiTree API...")),
        parent=parent,
    )
    meter.set_pass(
        str(_("Querying the WikiTree API...")),
        mode=ProgressMeter.MODE_ACTIVITY,
    )
    meter.step()

    try:
        gwizard = load_wikitree_gwizard(dbstate.db, params)
    except (ValueError, RuntimeError) as error:
        meter.close()
        ErrorDialog(_("Search Failed"), str(error), parent=parent)
        return False

    source_db = gwizard.context.get("source_db")
    person_count = source_db.get_number_of_people() if source_db else 0
    if person_count == 0:
        meter.close()
        OkDialog(
            _("No Profiles Found"),
            _("No matching profiles found on WikiTree for '%s'.") % params.get("query"),
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
