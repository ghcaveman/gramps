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
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Grizard Web Importer interface for launching selective merges on scraped search results.
"""

from __future__ import annotations
import logging
from typing import Any
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.grizard.webscraped import WebScrapedGrizard
from .grizardcompare import GrizardCompareWindow

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# GrizardWebImporter
#
# ------------------------------------------------------------
class GrizardWebImporter:
    """
    Utility class to bridge external web scraping tools and the selective merge GUI.
    """

    @classmethod
    def import_results(
        cls,
        uistate: Any,
        dbstate: Any,
        scraped_results: list[dict[str, Any]],
        parent: Gtk.Window | None = None,
    ) -> GrizardCompareWindow | None:
        """
        Feed scraped web search results into the Grizard Compare Window for selective merging.

        :param uistate: Active Gramps UI state manager.
        :param dbstate: Active Gramps DB state manager.
        :param scraped_results: List of dictionaries of scraped records.
        :param parent: Parent window.
        :returns: The instantiated GrizardCompareWindow, or None if db is closed.
        """
        if not dbstate.is_open():
            LOG.error("Cannot import web results: Database is closed.")
            return None

        try:
            # 1. Instantiate the web scraped Grizard backend
            web_grizard = WebScrapedGrizard(dbstate.db)

            # 2. Connect the results
            if not web_grizard.run_step("connect", scraped_results=scraped_results):
                LOG.error("Failed to connect scraped results to Grizard.")
                return None

            # 3. Load results into in-memory database
            web_grizard.run_step("load")

            # 4. Open the comparison window
            compare_win = GrizardCompareWindow(
                uistate, dbstate, web_grizard, parent=parent
            )
            compare_win.show()
            return compare_win

        except Exception as e:
            LOG.exception("Failed to launch Grizard Web Importer: %s", e)
            return None
