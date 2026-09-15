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
# along with this program; if not, see <https://www.gnu.org/licenses/>.
#

"""
FindAGrave.com web search filter.
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
# FindAGraveSearch
#
# -------------------------------------------------------------------------
class FindAGraveSearch(WebSearchFilter):
    """
    Search FindAGrave.com for memorial records matching criteria.
    """

    labels: list[str] = []
    name: str = _("Search FindAGrave")
    category: str = _("Web Search filters")
    description: str = _("Search FindAGrave.com for records matching this person")

    WEBSITE_NAME: str = "FindAGrave"
    WEBSITE_URL: str = "https://www.findagrave.com"

    # Memorial record links on FindAGrave result pages
    RESULT_HREF_PATTERN: str = r"^/memorial/\d+"

    def get_search_url(self, params: dict[str, Any]) -> str:
        """
        Build FindAGrave search URL.

        :param params: Search parameters
        :returns: FindAGrave URL
        """
        first_name = params.get("first_name", "").replace(" ", "+")
        surname = params.get("surname", "").replace(" ", "+")
        birth_year = self._extract_year(params.get("birth_date", ""))
        death_year = self._extract_year(params.get("death_date", ""))

        url = (
            f"{self.WEBSITE_URL}/memorial/search"
            f"?firstname={first_name}&lastname={surname}"
        )
        if birth_year:
            url += f"&birthyear={birth_year}"
        if death_year:
            url += f"&deathyear={death_year}"
        return url

    def _execute_search(self, params: dict[str, Any], url: str) -> list[dict[str, Any]]:
        """
        Execute FindAGrave search by fetching and filtering the page.

        :param params: Search parameters
        :param url: Search URL
        :returns: List of result dictionaries
        """
        page_html = self._fetch_page(url)
        if page_html is None:
            return []
        return self.parse_results(page_html, url)
