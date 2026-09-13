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
Unit tests for HTMLToPangoParser in htmlview.py plus live-site rendering
quality tests for the pages linked by the WebSearch gramplet.

Test data modes controlled by environment variables:

    * Default (no flags): run against canned HTML fixture files under
      ``gramps/plugins/view/test/canned/``.  CI-safe, no network access.

    * ``LIVE_HTMLVIEW_TESTS=1``: fetch live HTML from the real websites listed
      in ``_SAMPLE_URLS``.  Intended for manual/local runs only; skipped on
      network failure.

    * ``REFRESH_CANNED=1``: download live HTML from the real URLs and
      write it into the ``canned/`` fixture directory, then run the tests
      against those freshly-downloaded fixtures (so the actual assertions
      still use offline data).  Use this to update the canned data so it
      can be committed and used in CI.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
import sys
import types
import unittest

# -------------------------------------------------------------------------
#
# Prevent Gtk / gramps.gui from initialising when htmlview.py is imported.
# HTMLToPangoParser is pure Python and needs no GTK.  We must, however,
# satisfy the ``from gramps.gui.views.pageview import PageView`` and
# ``from gramps.gui.htmlbridge import HtmlBridge`` imports inside htmlview.py
# with fake modules so the real (Gtk-dependent) import chain is never
# triggered.
#
# -------------------------------------------------------------------------
sys.modules["gi"] = types.ModuleType("gi")
sys.modules["gi.repository"] = types.ModuleType("gi.repository")

# gramps.gui.views.pageview — only PageView is used by htmlview.py


class _FakePageView:
    """Stand-in for gramps.gui.views.pageview.PageView."""


_fake_pageview = types.ModuleType("gramps.gui.views.pageview")
_fake_pageview.PageView = _FakePageView
sys.modules["gramps.gui.views.pageview"] = _fake_pageview

# gramps.gui.htmlbridge — only HtmlBridge is used by htmlview.py


class _FakeHtmlBridge:
    """Stand-in for gramps.gui.htmlbridge.HtmlBridge."""


_fake_htmlbridge = types.ModuleType("gramps.gui.htmlbridge")
_fake_htmlbridge.HtmlBridge = _FakeHtmlBridge
sys.modules["gramps.gui.htmlbridge"] = _fake_htmlbridge

# -------------------------------------------------------------------------
#
# Configuration — live vs. canned data
#
# -------------------------------------------------------------------------
TEST_DIR = os.path.abspath(os.path.dirname(__file__))
CANNED_DIR = os.path.join(TEST_DIR, "canned")


def _ensure_canned_dir():
    """Create the canned/ fixture directory if it does not exist."""
    os.makedirs(CANNED_DIR, exist_ok=True)


# Live URLs — the real sites that the WebSearch gramplet links to.
# Used when ``LIVE_HTMLVIEW_TESTS=1`` or ``REFRESH_CANNED=1``.
_SAMPLE_URLS = {
    "archive_js_required": (
        "https://www.archive.org/search.php?query=White+Milton",
        "Archive.org (JavaScript required)",
    ),
    "openlibrary_offline": (
        "https://openlibrary.org/search?q=White%2C+Milton",
        "OpenLibrary.org (offline)",
    ),
    "google_redirect": (
        "https://www.google.com/search?q=White+Milton",
        "Google.com (redirect interstitial)",
    ),
    "familysearch_unsupported": (
        "https://www.familysearch.org/en/tree/person/details/GHR5-28Q",
        "FamilySearch.org (unsupported browser)",
    ),
    "billiongraves_empty": (
        "https://billiongraves.com/search/"
        "results?given_names=Milton&family_names=White"
        "&birth_year=1822&death_year=1898&size=15",
        "BillionGraves.com (no matches)",
    ),
    "findagrave_result": (
        "https://www.findagrave.com/memorial/search"
        "?firstname=Milton&lastname=White"
        "&birthyear=1822&deathyear=1898",
        "FindAGrave.com (1 result)",
    ),
}

USE_LIVE = os.environ.get("LIVE_HTMLVIEW_TESTS") == "1"
USE_REFRESH = os.environ.get("REFRESH_CANNED") == "1"

# By default, use canned fixtures (CI-safe, no network).
# The refresh block below downloads live data *into* canned/ and then
# switches back to canned mode so the actual test run uses the fixtures.

# -------------------------------------------------------------------------
#
# Gramps modules (after the GTK stubs above)
#
# -------------------------------------------------------------------------
from gramps.plugins.view.htmlview import HTMLToPangoParser


# -------------------------------------------------------------------------
#
# Helpers — live-data fetching and canned-fixture refresh
#
# -------------------------------------------------------------------------
def _fetch_url(url: str) -> str:
    """Return the HTML served by *url*, decoded as UTF-8."""
    import logging
    import urllib.request

    LOG = logging.getLogger(__name__)
    req = urllib.request.Request(url, headers={"User-Agent": "Gramps-HTMLTest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    encoding = resp.headers.get_content_charset() or "utf-8"
    html_text = data.decode(encoding, errors="replace")
    LOG.info("Fetched %s (%d bytes)", url, len(html_text))
    return html_text


def _write_canned(key: str, html_text: str) -> None:
    """Write *html_text* into ``canned/<key>.html``."""
    out_path = os.path.join(CANNED_DIR, f"{key}.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_text)


def _read_canned(key: str) -> str:
    """Read the canned HTML fixture for *key* from ``canned/<key>.html``."""
    path = os.path.join(CANNED_DIR, f"{key}.html")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _load_sample(key: str) -> str:
    """Return the HTML to test for *key*.

    When ``LIVE_HTMLVIEW_TESTS=1`` is set, fetch live from the real URL.
    Otherwise read the canned fixture file (CI-safe, no network).
    """
    if USE_LIVE:
        return _fetch_url(_SAMPLE_URLS[key][0])
    return _read_canned(key)


# Refresh canned fixtures when requested (before any TestCase is loaded).
# This downloads live HTML and writes it into ``canned/<key>.html`` so that
# subsequent test runs (without the flag) use the updated offline data.
if USE_REFRESH:
    _ensure_canned_dir()
    for key, (url, _) in sorted(_SAMPLE_URLS.items()):
        try:
            html_text = _fetch_url(url)
            _write_canned(key, html_text)
            print(
                f"Canned {key!r} -> {CANNED_DIR}/{key}.html "
                f"({len(html_text)} bytes)"
            )
        except Exception as exc:
            print(f"WARNING: failed to refresh canned {key!r}: {exc}")
    # Switch back to canned mode so the actual tests use the fixtures.
    USE_LIVE = False


# ------------------------------------------------------------
#
# HTMLToPangoParserTest
#
# ------------------------------------------------------------
class HTMLToPangoParserTest(unittest.TestCase):
    """Tests for the HTMLToPangoParser, a lightweight HTML-to-Pango converter.

    These tests use hardcoded inline HTML; they never touch the network.
    """

    def _parse(self, html_text: str) -> str:
        """Feed *html_text* to a fresh parser and return the Pango markup."""
        parser = HTMLToPangoParser()
        parser.feed(html_text)
        return parser.get_pango_markup()

    # -- bold / strong --------------------------------------------------

    def test_bold(self):
        self.assertEqual(self._parse("<b>bold</b>"), "<b>bold</b>")

    def test_strong(self):
        self.assertEqual(self._parse("<strong>strong</strong>"), "<b>strong</b>")

    # -- italic / emphasis ---------------------------------------------

    def test_italic(self):
        self.assertEqual(self._parse("<i>italic</i>"), "<i>italic</i>")

    def test_em(self):
        self.assertEqual(self._parse("<em>em</em>"), "<i>em</i>")

    # -- underline / strikethrough -------------------------------------

    def test_underline(self):
        self.assertEqual(self._parse("<u>underline</u>"), "<u>underline</u>")

    def test_strikethrough(self):
        self.assertEqual(self._parse("<s>strike</s>"), "<s>strike</s>")

    # -- superscript / subscript ----------------------------------------

    def test_superscript(self):
        self.assertEqual(self._parse("<sup>sup</sup>"), "<sup>sup</sup>")

    def test_subscript(self):
        self.assertEqual(self._parse("<sub>sub</sub>"), "<sub>sub</sub>")

    # -- headings ------------------------------------------------------

    def test_h1(self):
        result = self._parse("<h1>Heading</h1>")
        self.assertIn("<big>", result)
        self.assertIn("</big>", result)
        self.assertIn("<b>", result)

    def test_h2(self):
        result = self._parse("<h2>Sub</h2>")
        self.assertIn("<big>", result)

    def test_h3(self):
        result = self._parse("<h3>Sub3</h3>")
        self.assertIn("<big>", result)

    def test_h4_no_big(self):
        result = self._parse("<h4>Small heading</h4>")
        self.assertNotIn("<big>", result)
        self.assertIn("<b>", result)

    # -- paragraphs ---------------------------------------------------

    def test_paragraph(self):
        result = self._parse("<p>Paragraph</p>")
        self.assertEqual(result, "Paragraph")

    def test_div(self):
        result = self._parse("<div>Block</div>")
        self.assertEqual(result, "Block")

    # -- line break ---------------------------------------------------

    def test_br(self):
        self.assertEqual(self._parse("line1<br>line2"), "line1\nline2")

    # -- nesting -----------------------------------------------------

    def test_nested_bold_italic(self):
        result = self._parse("<b><i>both</i></b>")
        self.assertIn("<b>", result)
        self.assertIn("<i>", result)

    def test_misnested_tags_auto_close(self):
        result = self._parse("<b><i>mismatch</b></i>")
        self.assertIn("</b>", result)

    # -- done() flushes open tags -------------------------------------

    def test_done_closes_open_tags(self):
        parser = HTMLToPangoParser()
        parser.feed("<b>open")
        self.assertEqual(parser.result, ["<b>", "open"])
        result = parser.get_pango_markup()
        self.assertIn("</b>", result)

    def test_done_no_open_tags(self):
        result = self._parse("plain text")
        self.assertNotIn("</", result)

    # -- script/style suppressed -------------------------------------

    def test_script_skipped(self):
        result = self._parse("before<script>js</script>after")
        self.assertNotIn("js", result)
        self.assertIn("before", result)
        self.assertIn("after", result)

    def test_style_skipped(self):
        result = self._parse("before<style>css</style>after")
        self.assertNotIn("css", result)

    def test_head_skipped(self):
        result = self._parse("before<head>head</head>after")
        self.assertNotIn("head", result)

    def test_title_skipped(self):
        result = self._parse("before<title>tit</title>after")
        self.assertNotIn("tit", result)

    # -- bare <a> without href ----------------------------------------

    def test_bare_a_no_href(self):
        result = self._parse("<a>link text</a>")
        self.assertNotIn("<a ", result)
        self.assertNotIn("</a>", result)
        self.assertIn("link text", result)

    def test_a_with_href(self):
        result = self._parse('<a href="http://example.com">link</a>')
        self.assertIn('href="http://example.com"', result)

    def test_a_with_empty_href(self):
        result = self._parse('<a href="">link</a>')
        self.assertNotIn("<a ", result)
        self.assertIn("link", result)

    # -- empty / whitespace -------------------------------------------

    def test_empty(self):
        self.assertEqual(self._parse(""), "")

    def test_whitespace_only(self):
        result = self._parse("   ")
        self.assertEqual(result.strip(), "")

    # -- multiple paragraphs ------------------------------------------

    def test_multiple_paragraphs(self):
        result = self._parse("<p>p1</p><p>p2</p>")
        self.assertNotIn("\n\n\n\n\n", result)


# ------------------------------------------------------------
#
# RealWebPageTest
#
# ------------------------------------------------------------
# Per-page assertions on the Pango output produced by real
# (or canned) HTML samples fetched from the WebSearch gramplet
# links.  ``must_contain`` needles must appear in the output;
# ``must_not_contain`` needles must not.
#
_REAL_PAGE_ASSERTIONS = {
    "archive_js_required": {
        "label": "Archive.org (JavaScript required)",
        "must_contain": [
            "JavaScript is required for this site.",
            "Consider enabling JavaScript or upgrading",
        ],
        "must_not_contain": [],
    },
    "openlibrary_offline": {
        "label": "OpenLibrary.org (offline)",
        "must_contain": [
            "It looks like you&#x27;re offline",
            "Please check your internet connection",
        ],
        "must_not_contain": [],
    },
    "google_redirect": {
        "label": "Google.com (redirect interstitial)",
        "must_contain": [
            "redirected within a few seconds",
            "click here",
            "send feedback",
        ],
        "must_not_contain": [],
    },
    "familysearch_unsupported": {
        "label": "FamilySearch.org (unsupported browser)",
        "must_contain": [
            "Your web browser is not fully supported.",
            "Please update to the latest version",
        ],
        "must_not_contain": [],
    },
    "billiongraves_empty": {
        "label": "BillionGraves.com (no matches)",
        "must_contain": [
            "Search Results",
            "No matches found",
        ],
        "must_not_contain": [],
    },
    "findagrave_result": {
        "label": "FindAGrave.com (1 result)",
        "must_contain": [
            "Search Results",
            "1 matching record found for Milton White",
            "Milton White",
        ],
        "must_not_contain": [],
    },
}


def _assert_real_page(self, key):
    """Parse the (live or canned) HTML for *key* and assert on known markers."""
    html_text = _load_sample(key)
    pango = self._parse(html_text)
    cfg = _REAL_PAGE_ASSERTIONS[key]
    for needle in cfg["must_contain"]:
        with self.subTest(page=key, check="contains:" + needle):
            self.assertIn(needle, pango)
    for needle in cfg["must_not_contain"]:
        with self.subTest(page=key, check="not:" + needle):
            self.assertNotIn(needle, pango)


class RealWebPageTest(unittest.TestCase):
    """Feed HTML from real websites (via WebSearch gramplet) through
    HTMLToPangoParser to assess rendering quality.

    Uses canned HTML fixtures by default; set ``LIVE_HTMLVIEW_TESTS=1``
    to fetch live from the Internet instead.
    """

    def _parse(self, html_text):
        parser = HTMLToPangoParser()
        parser.feed(html_text)
        return parser.get_pango_markup()

    def test_archive_js_required(self):
        """Archive.org returns a JS-required notice."""
        _assert_real_page(self, "archive_js_required")

    def test_openlibrary_offline(self):
        """OpenLibrary.org displays an offline message."""
        _assert_real_page(self, "openlibrary_offline")

    def test_google_redirect(self):
        """Google shows a redirect interstitial."""
        _assert_real_page(self, "google_redirect")

    def test_familysearch_unsupported(self):
        """FamilySearch warns that the browser is not fully supported."""
        _assert_real_page(self, "familysearch_unsupported")

    def test_billiongraves_empty(self):
        """BillionGraves reports no matching records."""
        _assert_real_page(self, "billiongraves_empty")

    def test_findagrave_result(self):
        """FindAGrave returns a matching record for Milton White."""
        _assert_real_page(self, "findagrave_result")

    def test_scripts_suppressed_in_real_pages(self):
        """JavaScript embedded in real-page HTML is not rendered."""
        html_with_script = (
            _load_sample("findagrave_result")
            + '<script>var analytics = "tracking";</script>'
        )
        pango = self._parse(html_with_script)
        self.assertNotIn("analytics", pango)
        self.assertNotIn("tracking", pango)

    def test_headings_rendered_for_real_pages(self):
        """Every real-page sample produces non-empty Pango output."""
        for key in _REAL_PAGE_ASSERTIONS:
            html_text = _load_sample(key)
            pango = self._parse(html_text)
            with self.subTest(page=key):
                self.assertTrue(len(pango) > 0)


if __name__ == "__main__":
    unittest.main()
