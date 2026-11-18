# -*- coding: utf-8 -*-
#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2013 Vassilii Khachaturov <vassilii@tarunz.org>
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
# with this program; if not, see <https://www.gnu.org/licenses/>.
#

"""Unittest for constfunc.py"""

import unittest
import sys
import types
from unittest.mock import Mock, patch
from .. import constfunc

from os import environ as env


class Test_has_display(unittest.TestCase):
    def setUp(self):
        self.has = constfunc.has_display()
        self.display_nonempty = ("DISPLAY" in env) and bool(env["DISPLAY"])

    @unittest.skipUnless(constfunc.lin(), "Written for Linux only...")
    def test_consistent_with_DISPLAY_env(self):
        self.assertEqual(
            self.has,
            self.display_nonempty,
            "has_display(): {}, $DISPLAY: {}".format(
                self.has, env["DISPLAY"] if ("DISPLAY" in env) else "(unset)"
            ),
        )


class Test_has_display_init_check(unittest.TestCase):
    """Test handling of Gtk.init_check's (success, argv) result."""

    def test_failed_gtk_init_is_not_a_display(self):
        gtk = Mock()
        gtk.init_check.return_value = (False, [])
        gdk = Mock()
        gdk.Display.get_default.return_value = object()
        repository = types.ModuleType("gi.repository")
        repository.Gtk = gtk
        repository.Gdk = gdk
        gi = types.ModuleType("gi")
        gi.require_version = Mock()
        gi.repository = repository

        with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
            self.assertFalse(constfunc.has_display())


if __name__ == "__main__":
    unittest.main()
