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
Base class for WebSearch filters that query external genealogy websites.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

import html
import re
import urllib.parse
from typing import Any
from html.parser import HTMLParser

from ...rules._rule import Rule

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.lib import EventType

_ = glocale.translation.gettext

# -------------------------------------------------------------------------
#
# Logging
#
# -------------------------------------------------------------------------
import logging

LOG = logging.getLogger(".websearch")

# Anchor texts that are generic link labels, not person names.  When a
# result link uses one of these, the name is taken from nearby page text.
_GENERIC_LINK_TEXTS = {"view", "view memorial", "memorial", "record", "profile"}

# Year (or year range) extraction from free text, e.g. "1822 - 1898"
_YEAR_RANGE_RE = re.compile(r"(\d{3,4})\s*[-\u2013\u2014]\s*(\d{3,4})")
_YEAR_RE = re.compile(r"\d{3,4}")


# ------------------------------------------------------------
#
# _ResultLinkParser
#
# ------------------------------------------------------------
class _ResultLinkParser(HTMLParser):
    """
    Extract candidate result links from a website search result page.

    Records document-order events (text chunks and anchors); after
    feeding, result entries are built for every anchor whose href
    matches the site pattern, with the name taken from the anchor text
    or nearby text and years taken from the surrounding text window.
    """

    # Number of text chunks to consider before/after a matched anchor
    # when looking for a name and years.
    CONTEXT_CHUNKS = 5

    def __init__(self, href_pattern: re.Pattern[str]) -> None:
        """
        Initialise the parser.

        :param href_pattern: Compiled regex the href must match.
        """
        super().__init__()
        self.href_pattern = href_pattern
        # Document-order events: ("text", chunk) or
        # ("anchor", href, title, text)
        self.events: list[tuple[Any, ...]] = []
        self._anchor_href: str | None = None
        self._anchor_title: str = ""
        self._anchor_text: list[str] = []

    def _flush_text(self, data: str) -> None:
        """Append a non-empty text chunk to the event stream."""
        stripped = " ".join(data.split())
        if stripped:
            self.events.append(("text", stripped))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track anchors; block tags close any pending text chunk."""
        if tag == "a":
            self._anchor_href = None
            self._anchor_title = ""
            for name, value in attrs:
                if name == "href" and value:
                    self._anchor_href = value
                elif name == "title" and value:
                    self._anchor_title = value
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        """Record a completed anchor as an event."""
        if tag != "a" or self._anchor_href is None:
            return
        href = self._anchor_href
        self._anchor_href = None
        self._flush_text("".join(self._anchor_text))
        self.events.append(("anchor", href, " ".join(self._anchor_title.split())))

    def handle_data(self, data: str) -> None:
        """Accumulate text inside anchors or emit standalone chunks."""
        if self._anchor_href is not None:
            self._anchor_text.append(data)
        else:
            self._flush_text(data)

    def _name_from_chunks(self, chunks: list[str], text: str, title: str) -> str:
        """
        Choose the best person name from nearby text chunks.

        Prefers the anchor text unless it is a generic label; otherwise
        uses the nearest preceding chunk containing letters.
        """
        if text and text.lower() not in _GENERIC_LINK_TEXTS:
            return text
        if title:
            return title
        for chunk in reversed(chunks):
            if chunk.lower() in _GENERIC_LINK_TEXTS:
                continue
            if re.search(r"[A-Za-z]", chunk) and not _YEAR_RE.fullmatch(chunk):
                return chunk
        return text or "Unknown"

    def get_results(self) -> list[dict[str, Any]]:
        """
        Build result entries from the recorded events.

        :returns: List of result dictionaries (name, birth, death,
            details, url).
        """
        results: list[dict[str, Any]] = []
        for index, event in enumerate(self.events):
            if event[0] != "anchor":
                continue
            _, href, title = event
            if not self.href_pattern.search(href):
                continue

            anchor_event = self.events[index - 1]
            text = anchor_event[1] if anchor_event[0] == "text" else ""
            before = [
                self.events[j][1]
                for j in range(max(0, index - 1 - self.CONTEXT_CHUNKS), index - 1)
                if self.events[j][0] == "text"
            ]
            after = [
                self.events[j][1]
                for j in range(
                    index + 1,
                    min(len(self.events), index + 1 + self.CONTEXT_CHUNKS),
                )
                if self.events[j][0] == "text"
            ]

            name = self._name_from_chunks(before, text, title)

            # Years: prefer a range in the text following the link
            # (typical result layout), then a range before it, then any
            # two single years in document order.
            after_text = " ".join(after)
            before_text = " ".join(before + ([text] if text else []))
            birth = death = ""
            match = _YEAR_RANGE_RE.search(after_text) or _YEAR_RANGE_RE.search(
                before_text
            )
            if match:
                birth, death = match.group(1), match.group(2)
            else:
                years = _YEAR_RE.findall(after_text + " " + before_text)
                if len(years) >= 2:
                    birth, death = years[0], years[1]
                elif len(years) == 1:
                    birth = years[0]

            results.append(
                {
                    "name": name,
                    "birth": birth,
                    "death": death,
                    "details": title,
                    "url": href,
                }
            )
        return results


# -------------------------------------------------------------------------
#
# WebSearchFilter
#
# -------------------------------------------------------------------------
class WebSearchFilter(Rule):
    """
    Base class for filters that define web search parameters.

    These filters extract search criteria from people and can query
    external genealogy websites for matching records.

    Subclasses should override:
    - WEBSITE_NAME: The display name of the website
    - get_search_url(): Return the URL template for searching
    - extract_search_params(): Extract search params from a person
    """

    labels: list[str] = []
    name: str = _("Web Search Filter")
    category: str = _("Web Search filters")
    description: str = _(
        "Search external genealogy websites for people matching criteria"
    )
    allow_regex: bool = False

    # Website identification - override in subclasses
    WEBSITE_NAME: str = _("Web Search")
    WEBSITE_URL: str = ""

    # Regex (as a string) that hrefs of result records must match on the
    # site's search result pages.  None means the site has no parser.
    RESULT_HREF_PATTERN: str | None = None

    # URL template with {param} placeholders
    URL_TEMPLATE: str = "{base_url}/search?name={first_name}_{surname}"

    def __init__(self, arg: list[str] | None = None, **kwargs: Any) -> None:
        """
        Initialize the WebSearch filter.

        :param arg: List of filter arguments (typically empty for web search)
        :param kwargs: Additional keyword arguments
        """
        super().__init__(arg or [], **kwargs)
        self._last_search_params: dict[str, Any] = {}
        self._last_search_results: list[dict[str, Any]] = []

    def apply_to_one(self, db: Any, person: Any) -> bool:
        """
        For web search filters, this always returns True.
        Actual matching happens when performing the web search.

        :param db: Database instance (not used directly)
        :param person: Person to evaluate
        :returns: Always True (selection happens via web search)
        """
        return True

    def get_search_url(self, params: dict[str, Any]) -> str:
        """
        Build the search URL for the given parameters.

        :param params: Search parameters extracted from a person
        :returns: Complete URL for the web search
        """
        url = self.URL_TEMPLATE.format(**params)
        return url

    def extract_search_params(self, person: Any, db: Any) -> dict[str, Any]:
        """
        Extract search parameters from a person for web search.

        :param person: Person to extract parameters from
        :param db: Database instance
        :returns: Dictionary of search parameters
        """
        from gramps.gen.display.name import displayer as name_displayer

        name_str = name_displayer.display(person)

        # Extract birth info
        birth_date = ""
        birth_place = ""
        for event_ref in person.event_ref_list:
            if not event_ref:
                continue
            event = db.get_event_from_handle(event_ref.ref)
            if event and event.type.value == EventType.BIRTH:
                from gramps.gen.datehandler import get_date
                from gramps.gen.display.place import displayer as place_displayer

                birth_date = get_date(event) or ""
                if event.place:
                    place = db.get_place_from_handle(event.place)
                    if place:
                        birth_place = place_displayer.display(db, place)
                break

        # Extract death info
        death_date = ""
        for event_ref in person.event_ref_list:
            if not event_ref:
                continue
            event = db.get_event_from_handle(event_ref.ref)
            if event and event.type.value == EventType.DEATH:
                from gramps.gen.datehandler import get_date

                death_date = get_date(event) or ""
                break

        # Build parameter dict
        params: dict[str, Any] = {
            "first_name": "",
            "surname": "",
            "full_name": name_str,
            "birth_date": birth_date,
            "death_date": death_date,
            "birth_place": birth_place,
            "death_place": "",
        }

        # Use the person's primary name directly for reliable components
        primary_name = person.primary_name
        if primary_name is not None:
            params["first_name"] = primary_name.first_name or ""
            surnames = primary_name.surname_list or []
            if surnames:
                params["surname"] = surnames[0].surname or ""
        if not params["first_name"] and not params["surname"]:
            name_parts = name_str.split()
            if len(name_parts) >= 2:
                params["first_name"] = name_parts[0]
                params["surname"] = name_parts[-1]
            elif len(name_parts) == 1:
                params["first_name"] = name_parts[0]
                params["surname"] = name_parts[0]

        return params

    def perform_search(self, person: Any, db: Any) -> list[dict[str, Any]]:
        """
        Perform the web search for the given person.

        :param person: Person to search for
        :param db: Database instance
        :returns: List of result dictionaries
        """
        params = self.extract_search_params(person, db)
        url = self.get_search_url(params)
        self._last_search_params = params

        LOG.info(
            "WebSearch: %s - Searching for: %s",
            self.WEBSITE_NAME,
            params.get("full_name", "Unknown"),
        )

        results = self._execute_search(params, url)
        self._last_search_results = results
        return results

    def _execute_search(self, params: dict[str, Any], url: str) -> list[dict[str, Any]]:
        """
        Execute the actual HTTP request to the website.

        Override this method in subclasses to implement actual web search.

        :param params: Search parameters
        :param url: Complete search URL
        :returns: List of result dictionaries
        """
        LOG.debug("WebSearch: %s - No search implementation", self.WEBSITE_NAME)
        return []

    def get_results_html(self) -> str:
        """
        Generate HTML table of the last search results.

        :returns: HTML string for displaying results
        """
        results = self._last_search_results
        if not results:
            return "<p>No search results</p>"

        html_parts: list[str] = [
            '<table border="1" cellpadding="4" cellspacing="0" style="border-collapse: collapse; width: 100%;">'
        ]
        html_parts.append(
            "<thead><tr>"
            '<th style="background-color: #f0f0f0;">Name</th>'
            '<th style="background-color: #f0f0f0;">Birth</th>'
            '<th style="background-color: #f0f0f0;">Death</th>'
            '<th style="background-color: #f0f0f0;">Details</th>'
            '<th style="background-color: #f0f0f0;">Link</th>'
            "</tr></thead>"
        )
        html_parts.append("<tbody>")

        for result in results:
            name = html.escape(str(result.get("name", "Unknown")))
            birth = html.escape(str(result.get("birth", "-")))
            death = html.escape(str(result.get("death", "-")))
            details = html.escape(str(result.get("details", "")))
            result_url = html.escape(str(result.get("url", "")))
            website = html.escape(str(result.get("website", self.WEBSITE_NAME)))

            if result_url:
                link_html = (
                    f'<a href="{result_url}" style="color: #0066cc;">{website}</a>'
                )
            else:
                link_html = website

            html_parts.append(
                f"<tr>"
                f'<td style="padding: 6px;">{name}</td>'
                f'<td style="padding: 6px;">{birth}</td>'
                f'<td style="padding: 6px;">{death}</td>'
                f'<td style="padding: 6px;">{details}</td>'
                f'<td style="padding: 6px;">{link_html}</td>'
                f"</tr>"
            )

        html_parts.append("</tbody></table>")
        return "\n".join(html_parts)

    def get_person_search_header_html(self, person: Any, db: Any) -> str:
        """
        Generate HTML header showing person info and search target website.

        :param person: Person being searched for
        :param db: Database instance
        :returns: HTML string with person summary
        """
        from gramps.gen.display.name import displayer as name_displayer
        from gramps.gen.display.place import displayer as place_displayer
        from gramps.gen.datehandler import get_date

        name_str = name_displayer.display(person)

        # Get birth info
        birth_date = ""
        birth_place = ""
        for event_ref in person.event_ref_list:
            if not event_ref:
                continue
            event = db.get_event_from_handle(event_ref.ref)
            if event and event.type.value == EventType.BIRTH:
                birth_date = get_date(event) or ""
                if event.place:
                    place = db.get_place_from_handle(event.place)
                    if place:
                        birth_place = place_displayer.display(db, place)
                break

        # Get death info
        death_date = ""
        for event_ref in person.event_ref_list:
            if not event_ref:
                continue
            event = db.get_event_from_handle(event_ref.ref)
            if event and event.type.value == EventType.DEATH:
                death_date = get_date(event) or ""
                break

        website_display = self.WEBSITE_NAME

        html_parts: list[str] = [
            '<div style="'
            "margin-bottom: 20px; "
            "padding: 12px; "
            "border: 1px solid #ccc; "
            "background: #f8f9fa; "
            'border-radius: 4px;">',
            f'<h2 style="margin-top: 0; color: #333;">Searching for: {html.escape(name_str)}</h2>',
            '<table border="0" cellpadding="4" style="width: 100%;">',
            f'<tr><td style="width: 120px; vertical-align: top; color: #666;"><b>Website:</b></td>'
            f'<td style="color: #0066cc; font-weight: bold;">{html.escape(website_display)}</td></tr>',
        ]

        if birth_date or birth_place:
            html_parts.append(
                '<tr><td style="vertical-align: top; color: #666;"><b>Born:</b></td><td>'
            )
            if birth_date:
                html_parts.append(html.escape(birth_date))
            if birth_place:
                if birth_date:
                    html_parts.append(" - ")
                html_parts.append(html.escape(birth_place))
            html_parts.append("</td></tr>")

        if death_date:
            html_parts.append(
                f'<tr><td style="vertical-align: top; color: #666;"><b>Died:</b></td>'
                f"<td>{html.escape(death_date)}</td></tr>"
            )

        html_parts.append("</table></div>")
        return "\n".join(html_parts)

    def clear_results(self) -> None:
        """Clear stored search results."""
        self._last_search_params = {}
        self._last_search_results = []

    # -------------------------------------------------------------------------
    #
    # Result page filtering
    #
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_year(date_str: str) -> str:
        """
        Return the four-digit year from a date string, if any.

        :param date_str: Date string (e.g. "12 Mar 1874")
        :returns: The year, or "" if none found.
        """
        match = re.search(r"\d{4}", date_str or "")
        return match.group(0) if match else ""

    def _fetch_page(self, url: str) -> str | None:
        """
        Fetch the content of the given URL with browser-like headers.

        :param url: The URL to fetch.
        :returns: The decoded content, or None on failure.
        """
        import urllib.request

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
        }
        try:
            parsed = urllib.parse.urlsplit(url)
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
        except Exception:
            pass
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception as err:
            LOG.warning(
                "WebSearch: %s - failed to fetch %s: %s", self.WEBSITE_NAME, url, err
            )
            return None

    def parse_results(self, html_content: str, base_url: str) -> list[dict[str, Any]]:
        """
        Filter a fetched search result page into structured results.

        Extracts all links whose href matches the site's
        RESULT_HREF_PATTERN, resolving them against base_url.

        :param html_content: Raw HTML of the fetched page.
        :param base_url: URL the page was fetched from (for link resolution).
        :returns: List of result dictionaries (name, birth, death, details,
            url, website).
        """
        if not self.RESULT_HREF_PATTERN:
            return []
        try:
            pattern = re.compile(self.RESULT_HREF_PATTERN)
        except re.error as err:
            LOG.warning("WebSearch: invalid RESULT_HREF_PATTERN: %s", err)
            return []

        parser = _ResultLinkParser(pattern)
        try:
            parser.feed(html_content)
            parser.close()
        except Exception as err:
            LOG.warning(
                "WebSearch: %s - failed to parse result page: %s",
                self.WEBSITE_NAME,
                err,
            )

        results = []
        for result in parser.get_results():
            result["url"] = urllib.parse.urljoin(base_url, result["url"])
            result["website"] = self.WEBSITE_NAME
            results.append(result)

        LOG.info(
            "WebSearch: %s - filtered %d result(s) from page",
            self.WEBSITE_NAME,
            len(results),
        )
        return results
