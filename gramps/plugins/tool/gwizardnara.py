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

"""Tools/Family Tree Processing/GWizard NARA Merge."""

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
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.plug import tool

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# GWizardNaraMergeToolOptions
#
# ------------------------------------------------------------
class GWizardNaraMergeToolOptions(tool.ToolOptions):
    """Defines options and provides handling interface."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        """Initialize the options."""
        tool.ToolOptions.__init__(self, name, person_id)
        self.options_dict: dict[str, Any] = {}
        self.options_help: dict[str, Any] = {}


# ------------------------------------------------------------
#
# GWizardNaraMergeTool
#
# ------------------------------------------------------------
class GWizardNaraMergeTool(tool.Tool):
    """
    Launch the GWizard NARA Merge flow.

    Searches the National Archives (NARA) Catalog API v2, loads records
    into an in-memory database, and opens the side-by-side comparison
    window to merge selected records into the open Family Tree.
    """

    def __init__(
        self,
        dbstate: Any,
        user: Any,
        options_class: Any,
        name: str,
        callback: Any = None,
    ) -> None:
        """Initialize the tool and run the shared NARA merge flow."""
        uistate = user.uistate
        tool.Tool.__init__(self, dbstate, options_class, name)

        import os as _os
        import sys as _sys

        _addon_dir = _os.path.dirname(_os.path.abspath(__file__))
        if _addon_dir not in _sys.path:
            _sys.path.insert(0, _addon_dir)
        try:
            from gwizardnaralauncher import run_gwizard_nara_flow
        except ImportError:
            from gramps.gui.gwizard.gwizardnaralauncher import (
                run_gwizard_nara_flow,
            )

        run_gwizard_nara_flow(uistate, dbstate, parent=uistate.window)
