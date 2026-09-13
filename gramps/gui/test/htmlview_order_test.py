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
Tests for ViewManager.get_available_views HTML ordering.
"""

# python3 -m unittest gramps.gui.test.htmlview_order_test -v

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import ast
import os
import types
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# Extract get_available_views from viewmanager.py via AST
#
# -------------------------------------------------------------------------
_VIEWMANAGER_PATH = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "viewmanager.py")
)


def _load_method_code(filepath: str, classname: str, methodname: str):
    """
    Parse a Python source file and return compiled code for one class method.
    """
    with open(filepath) as fh:
        source = fh.read()
    tree = ast.parse(source, filename=filepath)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == classname:
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == methodname
                ):
                    mod = ast.Module(body=[item], type_ignores=[])
                    ast.fix_missing_locations(mod)
                    return compile(mod, filepath, "exec")
    raise ValueError(f"{classname}.{methodname} not found in {filepath}")


# The method's global namespace
_START = 1
_END = 2
_METHOD_NS: dict = {
    "__builtins__": __builtins__,
    "defaultdict": defaultdict,
    "START": _START,
    "END": _END,
    "config": MagicMock(),
    "GuiPluginManager": MagicMock(),
    "ErrorDialog": MagicMock(),
    "URL_BUGHOME": "http://dummy",
}

exec(
    _load_method_code(_VIEWMANAGER_PATH, "ViewManager", "get_available_views"),
    _METHOD_NS,
)
_get_available_views = _METHOD_NS["get_available_views"]


# -------------------------------------------------------------------------
#
# HtmlViewOrderTest
#
# -------------------------------------------------------------------------
class HtmlViewOrderTest(unittest.TestCase):
    """
    Tests to ensure HTML view category is always ordered at the very end
    of available views.
    """

    def setUp(self):
        """
        Set up the mock configuration and plugin manager.
        """
        self.config_mock = _METHOD_NS["config"]
        self.pmgr_mock = _METHOD_NS["GuiPluginManager"]

        # Default configuration categories
        self.config_mock.get.return_value = [
            "Dashboard",
            "People",
            "Relationships",
            "Families",
        ]

    def test_html_is_last_when_present(self):
        """
        Test that if HTML view is present, it is positioned last.
        """
        # Create mock view plugin datas
        pdata_dash = MagicMock()
        pdata_dash.viewclass = "DashboardView"
        pdata_dash.category = ("Dashboard", "Dashboard")
        pdata_dash.order = _START

        pdata_people = MagicMock()
        pdata_people.viewclass = "PeopleView"
        pdata_people.category = ("People", "People")
        pdata_people.order = _START

        pdata_html = MagicMock()
        pdata_html.viewclass = "HTMLView"
        pdata_html.category = ("HTML", "HTML")
        pdata_html.order = _END

        # Set up GuiPluginManager mock returns
        pmgr_instance = self.pmgr_mock.get_instance.return_value
        pmgr_instance.get_reg_views.return_value = [
            pdata_html,
            pdata_dash,
            pdata_people,
        ]

        # Mock load_plugin and class extraction
        mock_mod = MagicMock()
        setattr(mock_mod, "DashboardView", MagicMock())
        setattr(mock_mod, "PeopleView", MagicMock())
        setattr(mock_mod, "HTMLView", MagicMock())
        pmgr_instance.load_plugin.return_value = mock_mod

        # Call get_available_views with simple mocked self
        vm = types.SimpleNamespace()
        result = _get_available_views(vm)

        # Result should be a list of lists of (pdata, viewclass)
        # We check the category names in order
        categories = [group[0][0].category[0] for group in result if group]

        self.assertEqual(categories[-1], "HTML")
        self.assertIn("Dashboard", categories)
        self.assertIn("People", categories)

    def test_no_crash_when_html_absent(self):
        """
        Test that if HTML view is not present, ordering succeeds normally.
        """
        pdata_dash = MagicMock()
        pdata_dash.viewclass = "DashboardView"
        pdata_dash.category = ("Dashboard", "Dashboard")
        pdata_dash.order = _START

        pmgr_instance = self.pmgr_mock.get_instance.return_value
        pmgr_instance.get_reg_views.return_value = [pdata_dash]

        mock_mod = MagicMock()
        setattr(mock_mod, "DashboardView", MagicMock())
        pmgr_instance.load_plugin.return_value = mock_mod

        vm = types.SimpleNamespace()
        result = _get_available_views(vm)

        categories = [group[0][0].category[0] for group in result if group]
        self.assertNotIn("HTML", categories)
        self.assertEqual(categories, ["Dashboard"])


# -------------------------------------------------------------------------
#
# Inline tests for HtmlBridge queue/flush/live-reload lifecycle.
# These run directly via python3 -m unittest gramps.gui.test.htmlview_order_test.
#
# -------------------------------------------------------------------------
class HtmlBridgeQueueTest(unittest.TestCase):
    """
    Tests that HtmlBridge's pending-queue does not crash when flushing
    a URL that was queued without fetched content (html_content is None).
    """

    # ---------- setUp / tearDown ----------

    def setUp(self):
        # Import the real HtmlBridge and snapshot/clean its class-level state
        # so each test starts from a clean slate.
        import sys
        from gramps.gui import htmlbridge as _hb_mod

        # Ensure the module is loaded under the gramps.gui package so the
        # relative import of htmlview.py still resolves in the same process.
        _hb_mod.__package__ = "gramps.gui"
        if "gramps.gui.htmlbridge" not in sys.modules:
            sys.modules["gramps.gui.htmlbridge"] = _hb_mod

        from gramps.gui.htmlbridge import HtmlBridge

        self._HtmlBridge = HtmlBridge
        self._orig_pending = HtmlBridge.pending_html
        self._orig_active = HtmlBridge.active_view
        self._orig_route_html = HtmlBridge.route_html
        self._orig_route_url = HtmlBridge.route_url
        HtmlBridge.pending_html = None
        HtmlBridge.active_view = None

    def tearDown(self):
        HtmlBridge = self._HtmlBridge
        HtmlBridge.pending_html = self._orig_pending
        HtmlBridge.active_view = self._orig_active
        HtmlBridge.route_html = self._orig_route_html
        HtmlBridge.route_url = self._orig_route_url

    # ---------- helpers ----------

    def _fake_route(self, html_mock, url_mock):
        """Install MagicMock route_html/route_url on the real HtmlBridge."""
        self._HtmlBridge.route_html = html_mock
        self._HtmlBridge.route_url = url_mock

    def _queue_url(self, url: str, html_content: str | None = None):
        """Simulate what route_url does when no view is registered."""
        self._HtmlBridge.pending_html = (url, html_content)

    # ---------- flush_pending ----------

    def test_flush_pending_with_html_content_calls_route_html(self):
        """
        When pending_html holds (url, html), flush_pending delivers it via route_html.
        """
        route_html = MagicMock()
        route_url = MagicMock()
        active_view = MagicMock()
        self._HtmlBridge.active_view = active_view
        self._fake_route(route_html, route_url)
        self._queue_url("http://example.test/queued", "<p>hello</p>")
        self._HtmlBridge.flush_pending(active_view)
        route_html.assert_called_once_with("http://example.test/queued", "<p>hello</p>")
        self.assertIsNone(self._HtmlBridge.pending_html)
        self.assertEqual(route_url.call_count, 0)

    def test_flush_pending_with_none_html_calls_route_url(self):
        """
        When pending_html holds (url, None), flush_pending re-fetches live
        via route_url instead of passing None to route_html (avoids the
        set_text(None) crash when the view opens).
        """
        route_html = MagicMock()
        route_url = MagicMock()
        active_view = MagicMock()
        self._HtmlBridge.active_view = active_view
        self._fake_route(route_html, route_url)
        self._queue_url("http://example.test/queued", None)
        self._HtmlBridge.flush_pending(active_view)
        route_url.assert_called_once_with("http://example.test/queued")
        self.assertIsNone(self._HtmlBridge.pending_html)
        self.assertEqual(route_html.call_count, 0)

    def test_flush_pending_ignores_when_view_mismatch(self):
        """
        flush_pending is a no-op when the live active_view is a different
        instance than the one being asked to flush (view was re-opened or
        a stale flush call arrives).
        """
        route_html = MagicMock()
        route_url = MagicMock()
        live = MagicMock()
        other = MagicMock()
        self._HtmlBridge.active_view = live
        self._fake_route(route_html, route_url)
        self._queue_url("http://example.test/queued", "<p>x</p>")
        self._HtmlBridge.flush_pending(other)
        self.assertEqual(
            self._HtmlBridge.pending_html, ("http://example.test/queued", "<p>x</p>")
        )
        self.assertEqual(route_html.call_count, 0)
        self.assertEqual(route_url.call_count, 0)

    def test_flush_pending_ignores_when_nothing_queued(self):
        """
        flush_pending is a no-op when pending_html is None.
        """
        route_html = MagicMock()
        route_url = MagicMock()
        view = MagicMock()
        self._HtmlBridge.active_view = view
        self._fake_route(route_html, route_url)
        self._HtmlBridge.flush_pending(view)
        self.assertIsNone(self._HtmlBridge.pending_html)
        self.assertEqual(route_html.call_count, 0)
        self.assertEqual(route_url.call_count, 0)
