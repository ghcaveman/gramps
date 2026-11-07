#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Kevin White
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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""Tests for shared GWizard UI widgets and utilities."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import sys
import unittest
from typing import Any
from unittest.mock import MagicMock

# -------------------------------------------------------------------------
#
# GTK mock fallback when running without display or PyGObject
#
# -------------------------------------------------------------------------
if "gi" not in sys.modules:
    gi_mock = MagicMock()

    class _FakeDialog:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_content_area(self) -> MagicMock:
            return MagicMock()

        def add_button(self, *args: Any, **kwargs: Any) -> None:
            pass

        def add_action_widget(self, *args: Any, **kwargs: Any) -> None:
            pass

        def connect(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_default_size(self, *args: Any, **kwargs: Any) -> None:
            pass

        def show_all(self) -> None:
            pass

    class _FakeLabel:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.selectable = False
            self.can_focus = True
            self.line_wrap = False
            self.text = ""
            self.markup = ""
            self.max_width_chars: int | None = None
            self.size_request: tuple[int, int] | None = None
            self.xalign = 0.5
            self.halign: Any = None

        def set_text(self, val: str) -> None:
            self.text = val

        def set_markup(self, val: str) -> None:
            self.markup = val

        def set_selectable(self, val: bool) -> None:
            self.selectable = val

        def set_can_focus(self, val: bool) -> None:
            self.can_focus = val

        def set_line_wrap(self, val: bool) -> None:
            self.line_wrap = val

        def set_line_wrap_mode(self, val: Any) -> None:
            pass

        def set_halign(self, val: Any) -> None:
            self.halign = val

        def set_xalign(self, val: float) -> None:
            self.xalign = val

        def set_max_width_chars(self, val: int) -> None:
            self.max_width_chars = val

        def set_size_request(self, w: int, h: int) -> None:
            self.size_request = (w, h)

        def set_hexpand(self, val: bool) -> None:
            self.hexpand = val

        def set_vexpand(self, val: bool) -> None:
            self.vexpand = val

    class _FakeGrid:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.col_spacing = 0
            self.row_spacing = 0
            self.hexpand = False
            self.vexpand = False

        def set_column_spacing(self, val: int) -> None:
            self.col_spacing = val

        def set_row_spacing(self, val: int) -> None:
            self.row_spacing = val

        def set_hexpand(self, val: bool) -> None:
            self.hexpand = val

        def set_vexpand(self, val: bool) -> None:
            self.vexpand = val

        def attach(self, *args: Any, **kwargs: Any) -> None:
            pass

    gi_mock.repository.Gtk.Dialog = _FakeDialog
    gi_mock.repository.Gtk.Label = _FakeLabel
    gi_mock.repository.Gtk.Grid = _FakeGrid
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.plugins.tool.gwizard_common import (
    SelectableLabel,
    TableLabel,
    HeaderLabel,
    create_table_grid,
)


class GWizardCommonTest(unittest.TestCase):
    """Test suite for GWizard common UI widgets."""

    def test_selectable_label_defaults(self) -> None:
        """SelectableLabel initializes with selectable=True, left alignment, and wrapping."""
        lbl = SelectableLabel("Test copyable text")
        self.assertTrue(lbl.selectable)
        self.assertFalse(lbl.can_focus)
        self.assertTrue(lbl.line_wrap)
        self.assertEqual(lbl.text, "Test copyable text")

    def test_table_label(self) -> None:
        """TableLabel inherits from SelectableLabel and sets constraints."""
        tbl_lbl = TableLabel(
            "Cell text", width_chars=30, width_request=240, markup=False
        )
        self.assertIsInstance(tbl_lbl, SelectableLabel)
        self.assertTrue(tbl_lbl.selectable)
        self.assertEqual(tbl_lbl.text, "Cell text")
        self.assertEqual(tbl_lbl.max_width_chars, 30)
        self.assertEqual(tbl_lbl.size_request, (240, -1))

    def test_header_label(self) -> None:
        """HeaderLabel inherits from SelectableLabel and displays bold markup."""
        hdr = HeaderLabel("Column Title")
        self.assertIsInstance(hdr, SelectableLabel)
        self.assertTrue(hdr.selectable)
        self.assertEqual(hdr.markup, "<b>Column Title</b>")

    def test_create_table_grid(self) -> None:
        """create_table_grid sets spacing and expansion defaults."""
        grid = create_table_grid(col_spacing=8, row_spacing=4)
        self.assertEqual(grid.col_spacing, 8)
        self.assertEqual(grid.row_spacing, 4)
        self.assertTrue(grid.hexpand)
        self.assertTrue(grid.vexpand)


if __name__ == "__main__":
    unittest.main()
