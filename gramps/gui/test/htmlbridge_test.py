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

"""Tests for the HTML bridge's URL and content routing."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import unittest
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gui.htmlbridge import HtmlBridge


# ------------------------------------------------------------
#
# HtmlBridgeTest
#
# ------------------------------------------------------------
class HtmlBridgeTest(unittest.TestCase):
    """Test queued content, URL fetching, view delivery, and receivers."""

    def setUp(self):
        """Reset bridge state and retain it for other tests."""
        self.original_pending = HtmlBridge.pending_html
        self.original_view = HtmlBridge.active_view
        self.original_callback = HtmlBridge.html_callback
        HtmlBridge.pending_html = None
        HtmlBridge.active_view = None
        HtmlBridge.html_callback = None

    def tearDown(self):
        """Restore bridge state after each test."""
        HtmlBridge.pending_html = self.original_pending
        HtmlBridge.active_view = self.original_view
        HtmlBridge.html_callback = self.original_callback

    def test_route_url_fetches_and_displays_content(self):
        """A registered view receives fetched HTML and its source URL."""
        url = "https://example.test/page"
        html_content = "<p>page</p>"
        view = MagicMock()
        HtmlBridge.register_view(view)

        with patch.object(HtmlBridge, "_fetch_url", return_value=html_content):
            handled = HtmlBridge.route_url(url)

        self.assertTrue(handled)
        view.set_search_url.assert_called_once_with(url)
        view.set_text.assert_called_once_with(html_content)

    def test_route_url_returns_false_when_fetch_fails(self):
        """A fetch failure lets the caller fall back to its own URL handling."""
        view = MagicMock()
        HtmlBridge.register_view(view)

        with patch.object(HtmlBridge, "_fetch_url", return_value=None):
            handled = HtmlBridge.route_url("https://example.test/page")

        self.assertFalse(handled)
        view.set_text.assert_not_called()

    def test_route_url_queues_until_view_registers(self):
        """A URL is queued and fetched when a view registers and flushes it."""
        url = "https://example.test/page"
        self.assertTrue(HtmlBridge.route_url(url))
        self.assertEqual(HtmlBridge.pending_html, (url, None))

        view = MagicMock()
        HtmlBridge.register_view(view)
        with patch.object(HtmlBridge, "_fetch_url", return_value="<p>page</p>"):
            HtmlBridge.flush_pending(view)

        view.set_search_url.assert_called_once_with(url)
        view.set_text.assert_called_once_with("<p>page</p>")
        self.assertIsNone(HtmlBridge.pending_html)

    def test_flush_pending_delivers_already_fetched_html(self):
        """Queued HTML is delivered without making another network request."""
        url = "https://example.test/page"
        html_content = "<p>already fetched</p>"
        view = MagicMock()
        HtmlBridge.register_view(view)
        HtmlBridge.pending_html = (url, html_content)

        with patch.object(HtmlBridge, "_fetch_url") as fetch_url:
            HtmlBridge.flush_pending(view)

        fetch_url.assert_not_called()
        view.set_search_url.assert_called_once_with(url)
        view.set_text.assert_called_once_with(html_content)
        self.assertIsNone(HtmlBridge.pending_html)

    def test_flush_pending_ignores_different_view(self):
        """A stale view cannot consume content queued for the active view."""
        active_view = MagicMock()
        other_view = MagicMock()
        pending = ("https://example.test/page", "<p>page</p>")
        HtmlBridge.register_view(active_view)
        HtmlBridge.pending_html = pending

        HtmlBridge.flush_pending(other_view)

        self.assertEqual(HtmlBridge.pending_html, pending)
        active_view.set_text.assert_not_called()
        other_view.set_text.assert_not_called()

    def test_html_callback_receives_content_until_unregistered(self):
        """A registered receiver gets routed HTML until it unregisters."""
        callback = MagicMock()
        HtmlBridge.register_html_callback(callback)
        first = ("https://example.test/first", "<p>first</p>")
        second = ("https://example.test/second", "<p>second</p>")

        HtmlBridge.route_html(*first)
        HtmlBridge.unregister_html_callback(callback)
        HtmlBridge.route_html(*second)

        callback.assert_called_once_with(*first)


if __name__ == "__main__":
    unittest.main()
