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


def _ask_for_base_media_path(uistate: Any, dbstate: Any, tool_name: str) -> None:
    """
    Before the tool opens: offer to set the family tree's base media path
    when none is set (GWizard Media Fix's question). The tool opens whatever
    the answer; without GWizard Media Fix nothing is asked.
    """
    # As an addon, Media Fix's modules are in the sibling MediaFix folder,
    # which Gramps removes from sys.path after loading it.
    media_fix_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "MediaFix"
    )
    if os.path.isdir(media_fix_dir) and media_fix_dir not in sys.path:
        sys.path.insert(0, media_fix_dir)
    # pylint: disable=import-outside-toplevel
    try:
        from gramps.plugins.tool.gwizard_mediafix_basepath import (
            ensure_base_media_path_for,
        )
    except ImportError:
        try:
            from gwizard_mediafix_basepath import (  # type: ignore[import-not-found, no-redef]
                ensure_base_media_path_for,
            )
        except ImportError:
            LOG.info("GWizard Media Fix not found; the base media path is not checked")
            return
    ensure_base_media_path_for(uistate, dbstate, tool_name)


# ------------------------------------------------------------
#
# GWizardNaraMergeOptions
#
# ------------------------------------------------------------
class GWizardNaraMergeOptions(tool.ToolOptions):
    """Defines options and provides handling interface."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        """Initialize the options."""
        tool.ToolOptions.__init__(self, name, person_id)
        self.options_dict: dict[str, Any] = {}
        self.options_help: dict[str, Any] = {}


# ------------------------------------------------------------
#
# GWizardNaraMerge
#
# ------------------------------------------------------------
class GWizardNaraMerge(tool.Tool):
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
            # Found on sys.path only when installed as an addon.
            from gwizardnaralauncher import (  # type: ignore[import-not-found]
                run_gwizard_nara_flow,
            )
        except ImportError:
            from gramps.gui.gwizard.gwizardnaralauncher import (
                run_gwizard_nara_flow,
            )

        _ask_for_base_media_path(uistate, dbstate, _("GWizard NARA Merge"))
        run_gwizard_nara_flow(uistate, dbstate, parent=uistate.window)
