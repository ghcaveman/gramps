"""Unittest for display.py"""

import os
import unittest
from unittest.mock import patch
from ..display import display_help, display_url
from gramps.gen.const import URL_WIKISTRING


# ------------------------------------------------------------
#
# Test_display_help
#
# ------------------------------------------------------------
class Test_display_help(unittest.TestCase):

    def test_page(self):
        with patch("gramps.gui.display.display_url") as mock:
            display_help("page")
            mock.assert_called_with(URL_WIKISTRING + "page")

    def test_page_section(self):
        with patch("gramps.gui.display.display_url") as mock:
            display_help("page", "section")
            mock.assert_called_with(URL_WIKISTRING + "page#section")

    def test_page_section2(self):
        with patch("gramps.gui.display.display_url") as mock:
            display_help("page#section")
            mock.assert_called_with(URL_WIKISTRING + "page#section")

    def test_http_page(self):
        with patch("gramps.gui.display.display_url") as mock:
            display_help("https://page")
            mock.assert_called_with("https://page")

    def test_http_page_section(self):
        with patch("gramps.gui.display.display_url") as mock:
            display_help("https://page", "section")
            mock.assert_called_with("https://page#section")

    def test_http_page_section2(self):
        with patch("gramps.gui.display.display_url") as mock:
            display_help("https://page#section")
            mock.assert_called_with("https://page#section")

    def test_page_fr(self):
        with patch("gramps.gui.display.EXTENSION", "/fr"):
            with patch("gramps.gui.display.display_url") as mock:
                display_help("page")
                mock.assert_called_with(URL_WIKISTRING + "page/fr")

    def test_page_section_fr(self):
        with patch("gramps.gui.display.EXTENSION", "/fr"):
            with patch("gramps.gui.display.display_url") as mock:
                display_help("page", "section")
                mock.assert_called_with(URL_WIKISTRING + "page/fr#section")

    def test_page_section2_fr(self):
        with patch("gramps.gui.display.EXTENSION", "/fr"):
            with patch("gramps.gui.display.display_url") as mock:
                display_help("page#section")
                mock.assert_called_with(URL_WIKISTRING + "page/fr#section")

    def test_http_page_fr(self):
        with patch("gramps.gui.display.EXTENSION", "/fr"):
            with patch("gramps.gui.display.display_url") as mock:
                display_help("https://page")
                mock.assert_called_with("https://page/fr")

    def test_http_page_section_fr(self):
        with patch("gramps.gui.display.EXTENSION", "/fr"):
            with patch("gramps.gui.display.display_url") as mock:
                display_help("https://page", "section")
                mock.assert_called_with("https://page/fr#section")

    def test_http_page_section2_fr(self):
        with patch("gramps.gui.display.EXTENSION", "/fr"):
            with patch("gramps.gui.display.display_url") as mock:
                display_help("https://page#section")
                mock.assert_called_with("https://page/fr#section")


# ------------------------------------------------------------
#
# Test_display_url
#
# ------------------------------------------------------------
class Test_display_url(unittest.TestCase):
    """Test URL routing to HTMLView or external browser."""

    @patch("webbrowser.open_new_tab")
    def test_default_external_browser(self, mock_open):
        """When GRAMPS_HTML is not set, URL opens in external browser."""
        with patch.dict(os.environ, {}, clear=True):
            display_url("https://example.com")
            mock_open.assert_called_once_with("https://example.com")

    @patch("webbrowser.open_new_tab")
    @patch("gramps.gui.htmlbridge.HtmlBridge.route_url", return_value=True)
    def test_internal_html_view_enabled_success(self, mock_route, mock_open):
        """When GRAMPS_HTML is set and route_url succeeds, internal view handles it."""
        with patch.dict(os.environ, {"GRAMPS_HTML": "1"}):
            display_url("https://example.com")
            mock_route.assert_called_once_with("https://example.com")
            mock_open.assert_not_called()

    @patch("webbrowser.open_new_tab")
    @patch("gramps.gui.htmlbridge.HtmlBridge.route_url", return_value=False)
    def test_internal_html_view_fallback_on_false(self, mock_route, mock_open):
        """When route_url returns False, falls back to external browser."""
        with patch.dict(os.environ, {"GRAMPS_HTML": "1"}):
            display_url("https://example.com")
            mock_route.assert_called_once_with("https://example.com")
            mock_open.assert_called_once_with("https://example.com")

    @patch("webbrowser.open_new_tab")
    @patch(
        "gramps.gui.htmlbridge.HtmlBridge.route_url",
        side_effect=RuntimeError("Bridge error"),
    )
    def test_internal_html_view_fallback_on_exception(self, mock_route, mock_open):
        """When route_url raises an exception, falls back to external browser."""
        with patch.dict(os.environ, {"GRAMPS_HTML": "1"}):
            display_url("https://example.com")
            mock_route.assert_called_once_with("https://example.com")
            mock_open.assert_called_once_with("https://example.com")

    @patch("webbrowser.open_new_tab")
    @patch("gramps.gui.htmlbridge.HtmlBridge.route_url")
    def test_non_http_link_opens_external_even_with_flag(self, mock_route, mock_open):
        """Non-http(s) links always open in external browser."""
        with patch.dict(os.environ, {"GRAMPS_HTML": "1"}):
            display_url("file:///path/to/doc")
            mock_route.assert_not_called()
            mock_open.assert_called_once_with("file:///path/to/doc")

    @patch("webbrowser.open_new_tab")
    @patch("gramps.gui.htmlbridge.HtmlBridge.route_url", return_value=True)
    def test_http_case_insensitive(self, mock_route, mock_open):
        """Scheme check is case-insensitive (e.g. HTTP://)."""
        with patch.dict(os.environ, {"GRAMPS_HTML": "1"}):
            display_url("HTTP://EXAMPLE.COM")
            mock_route.assert_called_once_with("HTTP://EXAMPLE.COM")
            mock_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
