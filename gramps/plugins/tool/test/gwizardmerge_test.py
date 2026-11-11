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

"""Unittests for the GWizard merge tool launcher."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import unittest

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except (ImportError, ValueError):
    import html
    import sys
    import types
    from unittest.mock import MagicMock

    class _DummyBase:
        pass

    class _DummyClass:
        def __init__(self, *args, **kwargs):
            self._name = ""

        def __call__(self, *args, **kwargs):
            return self

        def __getattr__(self, name):
            return self

        def __int__(self):
            return 0

        def __mro_entries__(self, bases):
            return (type(f"_DummyBase_{id(self)}", (), {}),)

        def set_name(self, name):
            self._name = name

        def get_name(self):
            return self._name

        def add_pattern(self, pattern):
            pass

    class _GtkModule(types.ModuleType):
        def __getattr__(self, name):
            return _DummyClass()

    _gtk = _GtkModule("gi.repository.Gtk")
    _glib = MagicMock()
    _glib.MAJOR_VERSION = 2
    _glib.MINOR_VERSION = 80
    _glib.MICRO_VERSION = 0
    _glib.markup_escape_text = html.escape

    _repo = types.ModuleType("gi.repository")
    _repo.Gtk = _gtk
    _repo.GLib = _glib
    _repo.Gio = MagicMock()
    _repo.Gdk = _DummyClass()
    _repo.Pango = MagicMock()
    _repo.PangoCairo = MagicMock()
    _repo.GObject = _DummyClass()
    _repo.GdkPixbuf = MagicMock()

    _gi = types.ModuleType("gi")
    _gi.repository = _repo
    _gi.require_version = lambda *args: None

    sys.modules["gi"] = _gi
    sys.modules["gi.repository"] = _repo
    sys.modules["gi.repository.Gtk"] = _gtk
    sys.modules["gi.repository.GLib"] = _glib
    sys.modules["gi.repository.Gio"] = _repo.Gio
    sys.modules["gi.repository.Gdk"] = _repo.Gdk
    sys.modules["gi.repository.Pango"] = _repo.Pango
    sys.modules["gi.repository.PangoCairo"] = _repo.PangoCairo
    sys.modules["gi.repository.GObject"] = _repo.GObject
    sys.modules["gi.repository.GdkPixbuf"] = _repo.GdkPixbuf

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gui.gwizard.gwizardlauncher import _case_insensitive_pattern


# ------------------------------------------------------------------
#
# GWizardMergeToolHelperTest
#
# ------------------------------------------------------------------
class GWizardMergeToolHelperTest(unittest.TestCase):
    """Test the GTK-free helpers used by the GWizard merge flow."""

    def test_case_insensitive_pattern(self) -> None:
        """Extension patterns match upper and lower case."""
        self.assertEqual(_case_insensitive_pattern("ged"), "*.[gG][eE][dD]")
        self.assertEqual(
            _case_insensitive_pattern("gramps"), "*.[gG][rR][aA][mM][pP][sS]"
        )

    def test_build_source_file_filters_fallback(self) -> None:
        """Filters always include genealogy types and an All files entry."""
        from gramps.gui.gwizard.gwizardlauncher import build_source_file_filters

        filters = build_source_file_filters()
        names = [f.get_name() for f in filters]
        self.assertTrue(any("All files" in name for name in names))
        self.assertTrue(len(filters) >= 2)


if __name__ == "__main__":
    unittest.main()
