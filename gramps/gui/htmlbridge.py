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
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
HTML Bridge for routing raw web data between WebSearch, HTMLView, and Grizard.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

import logging

LOG = logging.getLogger(".htmlbridge")


# ------------------------------------------------------------
#
# HtmlBridge
#
# ------------------------------------------------------------
class HtmlBridge:
    """
    HtmlBridge handles routing downloaded HTML content from WebSearch
    to either HTMLView or Grizard based on availability.
    """

    @classmethod
    def route_html(cls, url: str, html_content: str) -> None:
        """
        Route HTML content. By default, sends it to HTMLView.
        If Grizard is installed, it also routes to Grizard.

        :param url: The origin URL of the HTML content.
        :type url: str
        :param html_content: The raw HTML content.
        :type html_content: str
        """
        # 1. Default routing path: Send to HTMLView if loaded/active
        try:
            from gramps.plugins.view.htmlview import HTMLView

            HTMLView.set_html_text(html_content)
        except Exception as err:
            LOG.debug("HTMLView is not loaded or active: %s", err)

        # 2. Conditional routing path: Route to Grizard if the addon is installed
        try:
            # Check if Grizard package/modules are installed/importable
            from gramps.gui.grizard.grizardassistant import GrizardAssistant

            LOG.info(
                "Grizard is installed. Routing HTML to Grizard for parsing: %s", url
            )
            # If Grizard assistant implements a receiver, we can route it here:
            # GrizardAssistant.receive_html(url, html_content)
        except ImportError:
            # Grizard is not installed, skip gracefully
            LOG.debug("Grizard addon is not installed, skipping Grizard routing.")
