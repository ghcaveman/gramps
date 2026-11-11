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
WebSearch filter rules for querying external genealogy websites.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

import urllib.parse

from ._websearchfilter import WebSearchFilter
from ._familyservice import FamilyServiceSearch
from ._ancestry import AncestrySearch
from ._findagrave import FindAGraveSearch
from ._billiongraves import BillionGravesSearch

__all__ = [
    "WebSearchFilter",
    "FamilyServiceSearch",
    "AncestrySearch",
    "FindAGraveSearch",
    "BillionGravesSearch",
    "WEBSEARCH_FILTER_CLASSES",
    "get_websearch_filter_for_url",
]

# All known web search filter classes, used for URL matching and search runs
WEBSEARCH_FILTER_CLASSES: list[type[WebSearchFilter]] = [
    FamilyServiceSearch,
    AncestrySearch,
    FindAGraveSearch,
    BillionGravesSearch,
]


def get_websearch_filter_for_url(url: str) -> WebSearchFilter | None:
    """
    Return the web search filter matching the given URL's website.

    :param url: The URL of the page being displayed.
    :returns: A matching WebSearchFilter instance, or None.
    """
    try:
        netloc = urllib.parse.urlsplit(url).netloc.lower()
    except Exception:
        return None
    if not netloc:
        return None
    # Normalise so that "site.com" and "www.site.com" both match
    host = netloc[4:] if netloc.startswith("www.") else netloc
    for filter_class in WEBSEARCH_FILTER_CLASSES:
        try:
            site_netloc = urllib.parse.urlsplit(filter_class.WEBSITE_URL).netloc.lower()
        except Exception:
            continue
        site_host = site_netloc[4:] if site_netloc.startswith("www.") else site_netloc
        if host == site_host or host.endswith("." + site_host):
            return filter_class()
    return None
