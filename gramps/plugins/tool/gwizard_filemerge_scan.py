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

"""Tools/Family Tree Processing/GWizard Multi-Archive Record Scan."""

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
            from gwizard_mediafix_basepath import (  # type: ignore[import-not-found]
                ensure_base_media_path_for,
            )
        except ImportError:
            LOG.info("GWizard Media Fix not found; the base media path is not checked")
            return
    ensure_base_media_path_for(uistate, dbstate, tool_name)


# ------------------------------------------------------------
#
# GWizardRecordScanOptions
#
# ------------------------------------------------------------
class GWizardRecordScanOptions(tool.ToolOptions):
    """Defines options and provides handling interface."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        """Initialize the options."""
        tool.ToolOptions.__init__(self, name, person_id)
        self.options_dict = {}
        self.options_help = {}


# ------------------------------------------------------------
#
# GWizardRecordScan
#
# ------------------------------------------------------------
class GWizardRecordScan(tool.Tool):
    """
    Open the GWizard Multi-Archive Record Scan window: every person in the Family Tree,
    scored against the record sources (WikiTree, NARA, ...) installed
    addons provide.
    """

    def __init__(
        self,
        dbstate: Any,
        user: Any,
        options_class: Any,
        name: str,
        callback: Any = None,
    ) -> None:
        """Initialize the tool and open the window."""
        uistate = user.uistate
        tool.Tool.__init__(self, dbstate, options_class, name)
        # As a standalone addon this module ships in each record-source addon
        # (WikiTree, NARA, ...), and the record-scan modules it opens ship in
        # the sibling GWizardFileMerge addon. Gramps removes addon
        # directories from sys.path after import, so put both back.
        addon_dir = os.path.dirname(os.path.abspath(__file__))
        for path in (
            os.path.join(os.path.dirname(addon_dir), "GWizardFileMerge"),
            addon_dir,
        ):
            if os.path.isdir(path) and path not in sys.path:
                sys.path.insert(0, path)
        if uistate is None:
            LOG.error("GWizard Multi-Archive Record Scan needs the Gramps GUI")
            return
        from gramps.gui.dialog import ErrorDialog

        if not dbstate.is_open():
            ErrorDialog(
                _("GWizard Multi-Archive Record Scan"),
                _("Open a Family Tree before running this tool."),
                parent=uistate.window,
            )
            return
        _ask_for_base_media_path(uistate, dbstate, _("Multi-Archive Record Scan"))
        from gramps.gui.gwizard.gwizard_filemerge_recordscandialog import (
            run_gwizard_record_scan,
        )

        run_gwizard_record_scan(uistate, dbstate, parent=uistate.window)
