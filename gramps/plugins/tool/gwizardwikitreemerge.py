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

"""Tools/Family Tree Processing/GWizard WikiTree Merge."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import importlib
import os
import sys
import logging
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.plug import tool

# When installed as a standalone addon, sibling modules live in the addon
# directory, which Gramps removes from sys.path after import.  Re-add it
# (once) so the shared helper and the launcher can be imported.
_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
if _ADDON_DIR not in sys.path:
    sys.path.insert(0, _ADDON_DIR)

if __package__:
    _addon_util = importlib.import_module(".gwizardaddonutil", __package__)
else:
    _addon_util = importlib.import_module("gwizardaddonutil")
run_flow = getattr(_addon_util, "run_flow")

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
            from gwizard_mediafix_basepath import (  # type: ignore[import-not-found]
                ensure_base_media_path_for,
            )
        except ImportError:
            LOG.info("GWizard Media Fix not found; the base media path is not checked")
            return
    ensure_base_media_path_for(uistate, dbstate, tool_name)


# ------------------------------------------------------------
#
# GWizardWikiTreeMergeOptions
#
# ------------------------------------------------------------
class GWizardWikiTreeMergeOptions(tool.ToolOptions):
    """Defines options and provides handling interface."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        """Initialize the options."""
        tool.ToolOptions.__init__(self, name, person_id)
        self.options_dict: dict[str, Any] = {}
        self.options_help: dict[str, Any] = {}


# ------------------------------------------------------------
#
# GWizardWikiTreeMerge
#
# ------------------------------------------------------------
class GWizardWikiTreeMerge(tool.Tool):
    """
    Launch the GWizard WikiTree Merge flow.

    Queries the WikiTree REST API, loads profiles into an in-memory
    database, and opens the side-by-side comparison window.  Provenance
    (shared source, dated citation, ID, link) is added through
    gwizardwikitreeprovenance.ensure_provenance.
    """

    def __init__(
        self,
        dbstate: Any,
        user: Any,
        options_class: Any,
        name: str,
        callback: Any = None,
    ) -> None:
        """Initialize the tool and run the shared flow."""
        tool.Tool.__init__(self, dbstate, options_class, name)
        _ask_for_base_media_path(
            getattr(user, "uistate", None), dbstate, _("GWizard WikiTree Merge")
        )
        run_flow(
            getattr(user, "uistate", None),
            dbstate,
            addon_module="gwizardwikitreelauncher",
            core_module="gramps.gui.gwizard.gwizardwikitreelauncher",
            func_name="run_gwizard_wikitree_flow",
            title=_("GWizard WikiTree Merge"),
        )
