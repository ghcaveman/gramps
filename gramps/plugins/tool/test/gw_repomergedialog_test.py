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

"""Tests for RepoMergeDialog (Fix Repositories dialog)."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import sys
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

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

        def destroy(self) -> None:
            pass

        def run(self) -> int:
            return 0

    class _FakeLabel:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_markup(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_halign(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_hexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_line_wrap(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_line_wrap_mode(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_max_width_chars(self, *args: Any, **kwargs: Any) -> None:
            if args:
                self._max_width_chars = args[0]

        def get_max_width_chars(self) -> int:
            return getattr(self, "_max_width_chars", -1)

        def set_xalign(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_size_request(self, *args: Any, **kwargs: Any) -> None:
            if len(args) >= 2:
                self._size_request = (args[0], args[1])

        def get_size_request(self) -> tuple[int, int]:
            return getattr(self, "_size_request", (-1, -1))

        def get_style_context(self) -> MagicMock:
            return MagicMock()

    class _FakeGrid:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_column_spacing(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_row_spacing(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_column_homogeneous(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_hexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_vexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_style_context(self) -> MagicMock:
            return MagicMock()

        def attach(self, *args: Any, **kwargs: Any) -> None:
            pass

    class _FakeComboBox:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._model: list[Any] = []
            self._active = 0

        @classmethod
        def new_with_model(cls, model: Any) -> _FakeComboBox:
            cb = cls()
            cb._model = list(model)
            return cb

        def set_hexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_size_request(self, *args: Any, **kwargs: Any) -> None:
            pass

        def pack_start(self, *args: Any, **kwargs: Any) -> None:
            pass

        def add_attribute(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_active(self, val: int) -> None:
            self._active = val

        def get_active(self) -> int:
            return self._active

        def get_active_iter(self) -> Any:
            return self._active if 0 <= self._active < len(self._model) else None

        def get_model(self) -> Any:
            return self._model

        def connect(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_style_context(self) -> MagicMock:
            return MagicMock()

    class _FakeScrolledWindow:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_min_content_height(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_min_content_width(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_policy(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_hexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_vexpand(self, *args: Any, **kwargs: Any) -> None:
            pass

        def add(self, *args: Any, **kwargs: Any) -> None:
            pass

    gi_mock.repository.Gtk.Dialog = _FakeDialog
    gi_mock.repository.Gtk.Label = _FakeLabel
    gi_mock.repository.Gtk.Grid = _FakeGrid
    gi_mock.repository.Gtk.ComboBox = _FakeComboBox
    gi_mock.repository.Gtk.ScrolledWindow = _FakeScrolledWindow
    gi_mock.repository.Gtk.ListStore = lambda *types: []
    gi_mock.repository.Gtk.ResponseType.OK = 1
    gi_mock.repository.Gtk.ResponseType.CANCEL = 2
    gi_mock.repository.Gtk.ResponseType.CLOSE = 3
    gi_mock.repository.Gtk.ResponseType.NONE = 4
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Repository, Source, RepoRef
from gramps.plugins.tool.gw_repomergedialog import RepoMergeDialog

_ = glocale.translation.sgettext


class FakeDbState:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class RepoMergeDialogTest(unittest.TestCase):
    """Test suite for RepoMergeDialog (Fix Repositories)."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = FakeDbState(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_dialog_buttons_and_footer(self) -> None:
        """Verify buttons in action area next to close, and footer text at bottom."""
        with DbTxn("Create repo and source", self.db) as trans:
            r = Repository()
            r.set_name("ancestry")
            r_h = self.db.add_repository(r, trans)

            s = Source()
            s.set_title("1900 US Census")
            ref = RepoRef()
            ref.set_reference_handle(r_h)
            s.add_repo_reference(ref)
            self.db.add_source(s, trans)

        with (
            patch.object(RepoMergeDialog, "add_action_widget") as mock_action,
            patch.object(RepoMergeDialog, "add_button") as mock_add_button,
            patch("gramps.plugins.tool.gw_repomergedialog.Gtk.Label") as mock_label_cls,
        ):
            dlg = RepoMergeDialog("Fix Repositories", self.dbstate)

            # Both accept_button and apply_button added via add_action_widget
            self.assertTrue(hasattr(dlg, "accept_button"))
            self.assertTrue(hasattr(dlg, "apply_button"))
            self.assertEqual(mock_action.call_count, 2)

            # Close button added via add_button
            mock_add_button.assert_called_with(
                str(_("_Close")),
                sys.modules["gi.repository"].Gtk.ResponseType.CLOSE,
            )

            # Verify footer text includes "Create missing repositories and link orphan sources."
            labels_created = [
                call.kwargs.get("label", "") for call in mock_label_cls.call_args_list
            ]
            footer_found = any(
                "Create missing repositories and link orphan sources." in text
                for text in labels_created
            )
            self.assertTrue(footer_found)


if __name__ == "__main__":
    unittest.main()
