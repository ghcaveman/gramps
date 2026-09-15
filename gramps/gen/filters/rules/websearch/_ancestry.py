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
Ancestry.com web search filter.
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
# AncestrySearch
#
# -------------------------------------------------------------------------
class AncestrySearch(WebSearchFilter):
    """
    Search Ancestry.com for people matching criteria.
    """

    labels: list[str] = []
    name: str = _("Search Ancestry")
    category: str = _("Web Search filters")
    description: str = _("Search Ancestry.com for records matching this person")

    WEBSITE_NAME: str = "Ancestry"
    WEBSITE_URL: str = "https://www.ancestry.com"

    def get_search_url(self, params: dict[str, Any]) -> str:
        """
        Build Ancestry search URL.
        """
        first_name = params.get("first_name", "").replace(" ", "+")
        surname = params.get("surname", "").replace(" ", "+")
        birth_year = params.get("birth_date", "")

        base_url = self.WEBSITE_URL
        url = f"{base_url}/search/collections/deeds"
        url += f"?_ga=1&ssrk=&gss=&gi=&kaa=&cat=&indiv="
        url += f"&pid=&ps=&pc=&pup=&pt=&ptt=&pg=&pcert="
        url += f"&psln={surname}&psfn={first_name}"

        if birth_year:
            try:
                year = birth_year.split()[-1] if " " in birth_year else birth_year[:4]
                url += f"&pby={year}"
            except (ValueError, IndexError):
                pass

        return url

    def _execute_search(self, params: dict[str, Any], url: str) -> list[dict[str, Any]]:
        """
        Execute Ancestry search.
        """
        return []
