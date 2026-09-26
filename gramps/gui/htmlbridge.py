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
        return True

    @classmethod
    def _fetch_url(cls, url: str) -> str | None:
        """
        Fetch the content of the given URL with browser-like headers.

        :param url: The URL to fetch.
        :type url: str
        :returns: The decoded content, or None on failure.
        :rtype: str | None
        """
        # Prefer ``curl_cffi`` for fetching because it offers better TLS handling
        # and respects system proxy settings. If it is not available we gracefully
        # fall back to the standard library ``urllib`` implementation that was
        # previously used.
        # Detect ``curl_cffi`` without triggering an ImportError that can be
        # masked by unusual ``sys.path`` configurations (e.g., when the package
        # lives in a non‑standard location). ``importlib.util.find_spec`` works
        # reliably across platforms.
        import importlib.util

        # Detect ``curl_cffi`` without triggering import errors caused by missing
        # native DLLs. ``importlib.util.find_spec`` tells us whether the module is
        # importable; we then attempt the import inside a guarded block.
        import importlib.util
        spec = importlib.util.find_spec("curl_cffi")
        if spec is not None:
            try:
                from curl_cffi import requests as curl_requests  # type: ignore
            except Exception:  # pragma: no cover – DLL load failure etc.
                LOG.debug("curl_cffi found but could not be imported; falling back to urllib")
                curl_requests = None
        else:  # pragma: no cover – exercised when curl_cffi missing
            curl_requests = None

        # Common header preparation – identical for both back‑ends.
        import urllib.parse

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
            # ``urllib.parse.quote`` is safe for both back‑ends.
            url = urllib.parse.quote(url, safe=";/?:@&=+$,~*!'()#%[]")
        except Exception:
            # If URL parsing fails we simply continue with the original string.
            pass

        if curl_requests is not None:
            # ``curl_cffi`` raises ``CurlError`` on failure; we treat any exception
            # uniformly and log a warning.
            try:
                resp = curl_requests.get(url, headers=headers, timeout=10)
                content = resp.content.decode("utf-8", errors="ignore")
                # Detect sites that require JavaScript (common placeholder).
                if "Javascript is required for this site" in content:
                    LOG.info("Page requires JavaScript – attempting Playwright fallback")
                    # Try Playwright if available.
                    try:
                        from playwright.sync_api import sync_playwright  # type: ignore
                        with sync_playwright() as p:
                            browser = p.chromium.launch(headless=True)
                            page = browser.new_page()
                            page.goto(url, timeout=10000)
                            # Wait for network idle to allow JS execution.
                            page.wait_for_load_state("networkidle", timeout=10000)
                            js_content = page.content()
                            browser.close()
                            return js_content
                    except Exception as pw_err:
                        LOG.warning("Playwright fallback failed: %s", pw_err)
                return content
            except Exception as err:  # pragma: no cover – exercised on network error
                LOG.warning("Failed to fetch URL with curl_cffi for HTMLView: %s", err)
                return None
        else:
            # Fallback to urllib implementation (unchanged semantics).
            import urllib.request

            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.read().decode("utf-8", errors="ignore")
            except Exception as err:
                LOG.warning("Failed to fetch URL for HTMLView: %s", err)
                return None
