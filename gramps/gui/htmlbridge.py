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
import os
import urllib.parse
import urllib.request

LOG = logging.getLogger(".htmlbridge")

# Environment variable that enables the HTMLView plugin and the routing
# of WebSearch URL data to the HTMLView.
HTML_VIEW_ENV_FLAG = "GRAMPS_HTML"


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

    # The live HTMLView page, registered by the view when it is created.
    # Kept here (not as a class attribute of HTMLView) because Gramps'
    # plugin loader can create a distinct class object for the plugin
    # module, which would break class-attribute based discovery.
    active_view: HTMLViewProtocol | None = None

    # Content fetched before the view was opened, delivered on registration.
    pending_html: tuple[str, str] | None = None

    @classmethod
    def register_view(cls, view) -> None:
        """
        Register the live HTMLView page so routed content can reach it.

        :param view: The HTMLView instance being created.
        """
        cls.active_view = view

    @classmethod
    def unregister_view(cls, view) -> None:
        """
        Unregister the HTMLView page when it is destroyed.

        :param view: The HTMLView instance being destroyed.
        """
        if cls.active_view is view:
            cls.active_view = None

    @classmethod
    def flush_pending(cls, view) -> None:
        """
        Deliver any content that was routed before the view was ready.

        :param view: The HTMLView instance that is now ready to display.
        """
        if cls.pending_html is not None and cls.active_view is view:
            url, html_content = cls.pending_html
            cls.pending_html = None
            if html_content is None or getattr(view, "web_view", None) is not None:
                # Load the live URL in the embedded browser so JavaScript
                # pages render correctly.
                view.load_url(url)
                LOG.info("Delivered pending URL %s to HTMLView", url)
            else:
                view.set_text(html_content)
                LOG.info(
                    "Delivered %d chars of pending HTML from %s",
                    len(html_content),
                    url,
                )

    @classmethod
    def is_html_view_enabled(cls) -> bool:
        """
        Return True when the HTMLView feature is enabled via the
        GRAMPS_HTML environment variable.
        """
        return bool(os.environ.get(HTML_VIEW_ENV_FLAG))

    # Headers used when fetching pages on behalf of the HTMLView, sized to
    # look like a normal desktop browser so sites do not reject the request.
    FETCH_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    @classmethod
    def route_url(cls, url: str) -> bool:
        """
        Route the given URL to the HTMLView. When the view page exists,
        the URL is loaded directly in its embedded WebKit2 browser (full
        JavaScript support), so no fetching is done here. Only when the
        view is not available, or WebKit2 is missing, is the content
        fetched and routed as plain HTML text.

        :param url: The URL to display.
        :type url: str
        :returns: True if the URL was handled, False if the caller should
            fall back to its own handling (e.g. open the system browser).
        :rtype: bool
        """
        view = cls.active_view
        if view is not None and hasattr(view, "load_url"):
            if getattr(view, "web_view", None) is not None:
                view.load_url(url)
                LOG.info("Routed URL %s to embedded browser in HTMLView", url)
                return True
            # View exists but WebKit2 is not available; fetch the page and
            # display it as plain HTML text instead.
            LOG.info(
                "WebKit2 browser not available for HTMLView; fetching %s as text",
                url,
            )
        if view is not None:
            # No WebKit2: fetch the content and show it as text, unless
            # it is a JS-challenge page the caller should open externally.
            html_content = cls.fetch(url)
            if html_content is None:
                return False
            if cls.is_challenge_page(html_content):
                LOG.info(
                    "URL %s returned a JavaScript challenge page; falling "
                    "back to the system browser",
                    url,
                )
                return False
            cls.route_html(url, html_content)
            return True
        # Queue the URL itself so the view can load it when opened.
        cls.pending_html = (url, None)
        LOG.info("URL %s queued until the HTML view page is opened.", url)
        return True

    @classmethod
    def fetch(cls, url: str) -> str | None:
        """
        Fetch the content of the given URL with browser-like headers.

        :param url: The URL to fetch.
        :type url: str
        :returns: The decoded content, or None on failure.
        :rtype: str | None
        """
        headers = dict(cls.FETCH_HEADERS)
        try:
            # Include the site root as Referer; some sites require it.
            parsed = urllib.parse.urlsplit(url)
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
            # Encode spaces and other control characters that some sites
            # leave unencoded in search URLs.
            url = urllib.parse.quote(url, safe=";/?:@&=+$,~*!'()#%[]")
        except Exception:
            pass
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception as err:
            LOG.warning("Failed to fetch URL for HTMLView: %s", err)
            return None

    # Markers commonly found in bot-challenge or JavaScript-only gate
    # pages. Content matching these cannot be meaningfully rendered as
    # static text, so the caller should fall back to the system browser.
    CHALLENGE_MARKERS = (
        "enable javascript",
        "javascript is required",
        "javascript required",
        "click here if you are not redirected",
        "cf-browser-verification",
        "cf_chl_opt",
        "just a moment...",
        "checking your browser",
        "verify you are a human",
        "attention required",
    )

    @classmethod
    def is_challenge_page(cls, html_content: str) -> bool:
        """
        Return True when the fetched content looks like a bot-challenge
        or JavaScript-only gate page rather than real content.

        :param html_content: The fetched HTML content.
        :type html_content: str
        :rtype: bool
        """
        # Only judge small pages: real content pages are large, challenge
        # pages are tiny shells. Case-insensitive marker match.
        if len(html_content) > 200000:
            return False
        lower = html_content.lower()
        return any(marker in lower for marker in cls.CHALLENGE_MARKERS)

    @classmethod
    def route_html(cls, url: str, html_content: str) -> None:
        """
        Route HTML content to the HTMLView when the view is available.
        If Grizard is installed, it also routes to Grizard.

        :param url: The origin URL of the HTML content.
        :type url: str
        :param html_content: The raw HTML content.
        :type html_content: str
        """
        # 1. Default routing path: Send to the registered HTMLView page.
        view = cls.active_view
        if view is not None:
            view.set_text(html_content)
            LOG.info(
                "Routed %d chars of HTML from %s to HTMLView",
                len(html_content),
                url,
            )
        else:
            # The view page has not been opened yet; stash the content so
            # it is shown as soon as the view registers itself.
            cls.pending_html = (url, html_content)
            LOG.info(
                "HTML content from %s (%d chars) queued until the HTML view "
                "page is opened.",
                url,
                len(html_content),
            )

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
