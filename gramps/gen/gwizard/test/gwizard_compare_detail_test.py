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

"""
Tests for the detail panels of the GWizard compare window: the same people
are listed in the same order on both sides, whatever order each tree stores
them in, and differing lines are compared with their closest counterpart.

Nothing here builds a widget, so no display is needed.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import re
import sys
import tempfile
import types
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except (ImportError, ValueError):
    import html
    import types
    from unittest.mock import MagicMock

    class _DummyBase:
        pass

    class _DummyClass:
        FILL = 0
        START = 0
        END = 0
        CENTER = 0

        def __init__(self, *args, **kwargs):
            self._name = ""

        def __call__(self, *args, **kwargs):
            return self

        def __getattr__(self, name):
            if name == "get_default":
                return lambda: None
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
from gramps.gen.db.utils import import_as_dict
from gramps.gen.user import User
from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow

HEADER = "0 HEAD\n1 CHAR UTF-8\n"


def person(xref: str, name: str, sex: str, links: str = "", birth: str = "") -> str:
    born = "1 BIRT\n2 DATE %s\n" % birth if birth else ""
    return "0 @%s@ INDI\n1 NAME %s\n1 SEX %s\n%s%s" % (xref, name, sex, born, links)


def family(xref: str, husb: str, wife: str, children: list[str]) -> str:
    text = "0 @%s@ FAM\n" % xref
    if husb:
        text += "1 HUSB @%s@\n" % husb
    if wife:
        text += "1 WIFE @%s@\n" % wife
    return text + "".join("1 CHIL @%s@\n" % child for child in children)


def tree(wives: list[str], children: list[str]) -> str:
    """Dad Doe with the given wives and children, stored in the given order."""
    parts = [HEADER]
    parts.append(
        person("D", "Dad /Doe/", "M", "".join("1 FAMS @F%s@\n" % w for w in wives))
    )
    names = {"1": "Wanda /Roe/", "2": "Wilma /Poe/"}
    for xref in wives:
        parts.append(person("W" + xref, names[xref], "F", "1 FAMS @F%s@\n" % xref))
    kids = {"A": ("Anna /Doe/", "F", "1900"), "B": ("Bert /Doe/", "M", "1902")}
    for xref in children:
        name, sex, year = kids[xref]
        parts.append(person(xref, name, sex, "1 FAMC @F1@\n", year))
    for xref in wives:
        parts.append(
            family("F" + xref, "D", "W" + xref, children if xref == "1" else [])
        )
    parts.append("0 TRLR\n")
    return "".join(parts)


class DetailPanelOrderTest(unittest.TestCase):
    """Relatives are listed in one canonical order."""

    def setUp(self) -> None:
        self._paths: list[str] = []
        self.dbs: list[Any] = []

    def tearDown(self) -> None:
        for db in self.dbs:
            db.close()
        for path in self._paths:
            if os.path.exists(path):
                os.remove(path)

    def _db(self, text: str) -> Any:
        with tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write(text)
        self._paths.append(handle.name)
        db = import_as_dict(handle.name, User())
        self.dbs.append(db)
        return db

    def _dad(self, db: Any) -> Any:
        return [
            p for p in db.iter_people() if p.get_primary_name().first_name == "Dad"
        ][0]

    def _window(self) -> Any:
        return GWizardCompareWindow.__new__(GWizardCompareWindow)

    def test_children_are_listed_in_the_same_order(self) -> None:
        """The tree stores Bert before Anna; the lines come out the same."""
        window = self._window()
        left = self._db(tree(["1"], ["A", "B"]))
        right = self._db(tree(["1"], ["B", "A"]))
        self.assertEqual(
            window._children_lines(self._dad(left), left),
            window._children_lines(self._dad(right), right),
        )
        self.assertEqual(
            [
                line.split(" (")[0]
                for line in window._children_lines(self._dad(left), left)
            ],
            ["Doe, Anna", "Doe, Bert"],
        )

    def test_spouses_are_listed_in_the_same_order(self) -> None:
        """The Spouse line does not depend on the order of the families."""
        window = self._window()
        left = self._db(tree(["1", "2"], ["A"]))
        right = self._db(tree(["2", "1"], ["A"]))
        self.assertEqual(
            window._family_lines(self._dad(left), left),
            window._family_lines(self._dad(right), right),
        )
        (line,) = window._family_lines(self._dad(left), left)
        self.assertTrue(line.startswith("Spouse: Poe, Wilma"))
        self.assertIn("Roe, Wanda", line)

    def test_a_child_in_two_families_is_listed_once(self) -> None:
        """A child both of Dad's families share appears on one line."""
        window = self._window()
        text = tree(["1", "2"], ["A"]).replace(
            "0 @F2@ FAM\n1 HUSB @D@\n1 WIFE @W2@\n",
            "0 @F2@ FAM\n1 HUSB @D@\n1 WIFE @W2@\n1 CHIL @A@\n",
        )
        db = self._db(text)
        self.assertEqual(len(window._children_lines(self._dad(db), db)), 1)

    def test_different_people_are_still_different(self) -> None:
        """Ordering never hides a child that only one tree has."""
        window = self._window()
        left = self._db(tree(["1"], ["A", "B"]))
        right = self._db(tree(["1"], ["B"]))
        self.assertNotEqual(
            window._children_lines(self._dad(left), left),
            window._children_lines(self._dad(right), right),
        )


class SectionMarkupTest(unittest.TestCase):
    """Differing lines are compared with their closest counterpart."""

    def _markup(self, lines: list[str], other: list[str]) -> str:
        return GWizardCompareWindow._build_section_markup(lines, other, ())

    def test_same_lines_in_another_order_are_not_marked(self) -> None:
        """No italics or bold when the other side has the same lines."""
        markup = self._markup(
            ["Anna (b. 1900)", "Bert (b. 1902)"], ["Bert (b. 1902)", "Anna (b. 1900)"]
        )
        self.assertNotIn("<", markup)

    def test_changed_line_is_compared_with_its_namesake(self) -> None:
        """Bert's changed year is bold; Anna's line, listed first, is untouched."""
        markup = self._markup(
            ["Anna (b. 1900)", "Bert (b. 1901)"],
            ["Bert (b. 1902)", "Anna (b. 1900)"],
        )
        first, second = markup.split("\n")
        self.assertNotIn("<", first)
        self.assertEqual(re.findall(r"<b>([^<]*)</b>", second), ["1901"])

    def test_a_line_with_no_counterpart_is_italic(self) -> None:
        """A line nothing resembles is italic as a whole, with no bold words."""
        self.assertEqual(
            self._markup(["Zed Quux"], ["Anna (b. 1900)"]), "<i>Zed Quux</i>"
        )

    def test_each_counterpart_is_used_once(self) -> None:
        """A second changed line is not compared with a line already used."""
        markup = self._markup(
            ["Anna (b. 1901)", "Anna (b. 1902)"], ["Anna (b. 1900)", "Quux Zed"]
        )
        first, second = markup.split("\n")
        self.assertEqual(re.findall(r"<b>([^<]*)</b>", first), ["1901"])
        self.assertEqual(second, "<i>Anna (b. 1902)</i>")


if __name__ == "__main__":
    unittest.main()
