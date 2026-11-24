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

"""Tools/Family Tree Processing/GWizard FamilySearch Merge."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import importlib
import logging
import os
import sys
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.plug import tool

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# GWizardFamilySearchMergeOptions
#
# ------------------------------------------------------------
class GWizardFamilySearchMergeOptions(tool.ToolOptions):
    """Defines options and provides handling interface."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        """Initialize the options."""
        tool.ToolOptions.__init__(self, name, person_id)
        self.options_dict: dict[str, Any] = {}
        self.options_help: dict[str, Any] = {}


# ------------------------------------------------------------
#
# GWizardFamilySearchMerge
#
# ------------------------------------------------------------
class GWizardFamilySearchMerge(tool.Tool):
    """
    Launch the GWizard FamilySearch Merge flow.

    Queries FamilySearch Tree records, loads profiles into an in-memory
    database, and opens the side-by-side comparison window. Provenance
    (shared source, dated citation, FSID, profile link) is added through
    gwizardfsprovenance.ensure_provenance.
    """

    def __init__(
        self,
        dbstate: Any,
        user: Any,
        options_class: Any,
        name: str,
        callback: Any = None,
    ) -> None:
        """Initialize the tool and run the FamilySearch merge flow."""
        uistate = getattr(user, "uistate", None)
        tool.Tool.__init__(self, dbstate, options_class, name)

        addon_dir = os.path.dirname(os.path.abspath(__file__))
        if addon_dir not in sys.path:
            sys.path.insert(0, addon_dir)

        try:
            launcher_module = importlib.import_module("gwizardfslauncher")
        except ModuleNotFoundError as err:
            if err.name != "gwizardfslauncher":
                raise
            launcher_module = importlib.import_module(
                "gramps.gui.gwizard.gwizardfslauncher"
            )

        run_gwizard_familysearch_flow = getattr(
            launcher_module, "run_gwizard_familysearch_flow"
        )
        run_gwizard_familysearch_flow(
            uistate, dbstate, parent=getattr(uistate, "window", None)
        )
