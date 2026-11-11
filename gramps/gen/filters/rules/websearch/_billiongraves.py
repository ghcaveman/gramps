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
BillionGraves.com web search filter.
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
# BillionGravesSearch
#
# -------------------------------------------------------------------------
class BillionGravesSearch(WebSearchFilter):
    """
    Search BillionGraves.com for grave records matching criteria.
    """

    labels: list[str] = []
    name: str = _("Search BillionGraves")
    category: str = _("Web Search filters")
    description: str = _("Search BillionGraves.com for records matching this person")

    WEBSITE_NAME: str = "BillionGraves"
    WEBSITE_URL: str = "https://www.billiongraves.com"

    # BillionGraves record links on result pages
    RESULT_HREF_PATTERN: str = r"^/(search/result|gravestone)/"

    def get_search_url(self, params: dict[str, Any]) -> str:
        """
        Build BillionGraves search URL.

        :param params: Search parameters
        :returns: BillionGraves URL
        """
        first_name = params.get("first_name", "").replace(" ", "+")
        surname = params.get("surname", "").replace(" ", "+")
        birth_year = self._extract_year(params.get("birth_date", ""))
        death_year = self._extract_year(params.get("death_date", ""))

        url = (
            f"{self.WEBSITE_URL}/search/results"
            f"?given_names={first_name}&family_names={surname}"
        )
        if birth_year:
            url += f"&birth_year={birth_year}"
        if death_year:
            url += f"&death_year={death_year}"
        url += "&size=15"
        return url

    def _execute_search(self, params: dict[str, Any], url: str) -> list[dict[str, Any]]:
        """
        Execute BillionGraves search by fetching and filtering the page.

        :param params: Search parameters
        :param url: Search URL
        :returns: List of result dictionaries
        """
        page_html = self._fetch_page(url)
        if page_html is None:
            return []
        return self.parse_results(page_html, url)
