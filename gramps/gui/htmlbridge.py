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
            if html_content is None:
                cls.route_url(url)
            else:
                cls.route_html(url, html_content)

    @classmethod
    def route_html(cls, url: str, html_content: str) -> None:
        """
        Route HTML content. By default, sends it to the registered HTMLView.
        If no view is registered, queues the content until the view opens.
        If Grizard is installed, it also routes to Grizard.

        :param url: The origin URL of the HTML content.
        :type url: str
        :param html_content: The raw HTML content.
        :type html_content: str
        """
        # 1. Default routing path: send to the registered HTMLView page.
        view = cls.active_view
        if view is not None:
            # Let the view show the origin website in its header.
            if hasattr(view, "set_search_url"):
                view.set_search_url(url)
            view.set_text(html_content)
            LOG.info(
                "Routed %d chars of HTML from %s to HTMLView",
                len(html_content),
                url,
            )
        else:
            # 2. No view registered yet: queue the content for delivery when
            #    the HTMLView page opens and registers itself.
            cls.pending_html = (url, html_content)
            LOG.info(
                "HTML content from %s (%d chars) queued until the HTML view "
                "page is opened.",
                url,
                len(html_content),
            )

        # 3. Conditional routing path: Route to Grizard if the addon is installed
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

    # -------------------------------------------------------------------------
    #
    # URL routing (no WebKit2 dependency — fetches content as HTML text)
    #
    # -------------------------------------------------------------------------

    @classmethod
    def route_url(cls, url: str) -> bool:
        """
        Route the given URL to the HTMLView without requiring WebKit2.
        The URL content is fetched server-side and shown as plain HTML
        text in the HTMLView. If the view is not available, content is
        queued until the view is opened.

        :param url: The URL to display.
        :type url: str
        :returns: True if the URL was handled, False if the caller should
            fall back to its own handling (e.g. open the system browser).
        :rtype: bool
        """
        view = cls.active_view
        if view is not None:
            html_content = cls._fetch_url(url)
            if html_content is None:
                return False
            cls.route_html(url, html_content)
            return True

        # No view registered: queue the URL for later loading when the
        # HTMLView page opens and registers itself.
        cls.pending_html = (url, None)
        LOG.info("URL %s queued until the HTML view page is opened.", url)
    @classmethod
    def _fetch_url(cls, url: str) -> str | None:
        """Fetch the content of *url*.

        The original implementation performed a plain ``urllib`` request with
        a browser‑like ``User‑Agent`` header.  That works for static pages but
        fails for sites that require JavaScript.  When Selenium is available we
        now use the same ``scrape_page_async`` helper that ``HTMLView`` uses –
        it runs a head‑less browser, executes JavaScript and returns the fully
        rendered HTML.

        If Selenium cannot be started we fall back to the original ``urllib``
        request so the function never raises an exception.
        """
        # -----------------------------------------------------------------
        # 1️⃣  Try Selenium first (if the flag is True and the scraper can be
        #     imported).  This mirrors the logic in ``HTMLView.set_text``.
        # -----------------------------------------------------------------
        try:
            from gramps.plugins.gramplet.scraper import scrape_page_direct  # type: ignore
            LOG.info("HtmlBridge: using Selenium to fetch %s", url)
            # Use a longer timeout to give JavaScript‑heavy pages more time to
            # finish loading.  A generic selector is not provided here because
            # the HTMLView does not know which element signals completion for a
            # given site.
            return scrape_page_direct(url, timeout=60)
        except Exception as exc:  # pragma: no cover – defensive fallback
            LOG.error("Selenium fetch failed for %s: %s", url, exc)
            # Fall back to the plain HTTP request below.
            pass

        # -----------------------------------------------------------------
        # 2️⃣  Plain HTTP fallback (original behaviour).
        # -----------------------------------------------------------------
        import urllib.parse
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
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except Exception as exc:  # pragma: no cover – defensive fallback
            LOG.error("Failed to fetch URL %s: %s", url, exc)
            return None
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception as err:
            LOG.warning("Failed to fetch URL for HTMLView: %s", err)
            return None
