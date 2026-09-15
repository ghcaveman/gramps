# -*- coding: utf-8 -*-
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
# with this program; if not, see <https://www.gnu.org/licenses/>.

"""
FamilySearch web search filter.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext

from ._websearchfilter import WebSearchFilter


# -------------------------------------------------------------------------
#
# FamilyServiceSearch
#
# -------------------------------------------------------------------------
class FamilyServiceSearch(WebSearchFilter):
    """
    Search FamilySearch for people matching criteria.

    This filter extracts person information and prepares it for
    searching on FamilySearch.org.
    """

    labels: list[str] = []  # No additional labels needed
    name: str = _("Search FamilySearch")
    category: str = _("Web Search filters")
    description: str = _("Search FamilySearch.org for records matching this person")

    WEBSITE_NAME: str = "FamilySearch"
    WEBSITE_URL: str = "https://www.familysearch.org"

    # FamilySearch uses a different URL structure
    URL_TEMPLATE: str = (
        "{base_url}/search/artist/KnownPerson" "?person={first_name}_{surname}"
    )

    def get_search_url(self, params: dict[str, Any]) -> str:
        """
        Build FamilySearch search URL.

        :param params: Search parameters
        :returns: FamilySearch URL
        """
        # FamilySearch URL uses encoded parameters
        first_name = params.get("first_name", "").replace(" ", "+")
        surname = params.get("surname", "").replace(" ", "+")

        base_url = self.WEBSITE_URL
        url = f"{base_url}/search/artist/KnownPerson?person={first_name}_{surname}"
        return url

    def _execute_search(self, params: dict[str, Any], url: str) -> list[dict[str, Any]]:
        """
        Execute FamilySearch search.

        In a full implementation, this would:
        1. Make HTTP request to FamilySearch API
        2. Parse JSON response
        3. Return list of matching persons

        For now, returns placeholder results.

        :param params: Search parameters
        :param url: Search URL
        :returns: List of result dictionaries
        """
        LOG.info(
            "FamilySearch: Would search URL: %s",
            url,
        )

        # Placeholder - in real implementation, make HTTP request
        # and parse FamilySearch API response
        return []
