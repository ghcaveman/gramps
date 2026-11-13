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
Tests for the Father, Mother, Spouse and Children rows of the GWizard merge
dialog: a relative the tree person already has is paired with the incoming
one whatever the order of the two lists, and gets no arrow.
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
from types import SimpleNamespace
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
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.user import User
from gramps.gui.gwizard import gwizardmergedialog
from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog, pair_relatives

HEADER = "0 HEAD\n1 CHAR UTF-8\n"


def person(xref: str, name: str, sex: str, links: str) -> str:
    return "0 @%s@ INDI\n1 NAME %s\n1 SEX %s\n%s" % (xref, name, sex, links)


def family(xref: str, husb: str, wife: str, children: list[str]) -> str:
    text = "0 @%s@ FAM\n" % xref
    if husb:
        text += "1 HUSB @%s@\n" % husb
    if wife:
        text += "1 WIFE @%s@\n" % wife
    return text + "".join("1 CHIL @%s@\n" % child for child in children)


# Dad Doe with two children and two wives, listed in one order. The incoming
# file knows when Wanda and Anna were born, so their rows differ in text even
# though the tree has the very same people.
SOURCE_GED = (
    HEADER
    + person("D", "Dad /Doe/", "M", "1 FAMS @F1@\n1 FAMS @F2@\n")
    + person("W1", "Wanda /Roe/", "F", "1 FAMS @F1@\n1 BIRT\n2 DATE 1850\n")
    + person("W2", "Wilma /Poe/", "F", "1 FAMS @F2@\n")
    + person("A", "Anna /Doe/", "F", "1 FAMC @F1@\n1 BIRT\n2 DATE 1900\n")
    + person("B", "Bert /Doe/", "M", "1 FAMC @F1@\n")
    + family("F1", "D", "W1", ["A", "B"])
    + family("F2", "D", "W2", [])
    + "0 TRLR\n"
)

# ... and in the reverse order in the tree, which also has a third child.
TARGET_GED = (
    HEADER
    + person("D", "Dad /Doe/", "M", "1 FAMS @F2@\n1 FAMS @F1@\n")
    + person("W1", "Wanda /Roe/", "F", "1 FAMS @F1@\n")
    + person("W2", "Wilma /Poe/", "F", "1 FAMS @F2@\n")
    + person("B", "Bert /Doe/", "M", "1 FAMC @F1@\n")
    + person("A", "Anna /Doe/", "F", "1 FAMC @F1@\n")
    + person("C", "Cora /Doe/", "F", "1 FAMC @F1@\n")
    + family("F2", "D", "W2", [])
    + family("F1", "D", "W1", ["B", "A", "C"])
    + "0 TRLR\n"
)


def rel(handle: str) -> Any:
    return SimpleNamespace(handle=handle)


# ------------------------------------------------------------
#
# pair_relatives
#
# ------------------------------------------------------------
class PairRelativesTest(unittest.TestCase):
    """The pure pairing of two lists of relatives."""

    def _names(self, pairs: list[tuple[Any, Any]]) -> list[tuple[Any, Any]]:
        return [(s.handle if s else None, t.handle if t else None) for s, t in pairs]

    def test_pairs_come_first_whatever_the_order(self) -> None:
        """The same people in another order are still paired."""
        resolve = {"s1": "t1", "s2": "t2"}.get
        pairs = pair_relatives([rel("s1"), rel("s2")], [rel("t2"), rel("t1")], resolve)
        self.assertEqual(self._names(pairs), [("s1", "t1"), ("s2", "t2")])

    def test_unpaired_sides_follow_the_pairs(self) -> None:
        """Then incoming-only relatives, then tree-only ones."""
        resolve = {"s2": "t2"}.get
        pairs = pair_relatives([rel("s1"), rel("s2")], [rel("t9"), rel("t2")], resolve)
        self.assertEqual(self._names(pairs), [("s2", "t2"), ("s1", None), (None, "t9")])

    def test_nothing_in_the_tree_means_no_lookup(self) -> None:
        """A person with no relatives of this role needs no matching."""
        calls = []
        pairs = pair_relatives([rel("s1")], [], lambda handle: calls.append(handle))
        self.assertEqual(self._names(pairs), [("s1", None)])
        self.assertEqual(calls, [])

    def test_a_tree_relative_is_paired_only_once(self) -> None:
        """Two incoming people standing for one tree person: first one wins."""
        pairs = pair_relatives(
            [rel("s1"), rel("s2")], [rel("t1")], {"s1": "t1", "s2": "t1"}.get
        )
        self.assertEqual(self._names(pairs), [("s1", "t1"), ("s2", None)])

    def test_unmatched_relative_does_not_pair_with_none(self) -> None:
        """An incoming person with no counterpart pairs with nobody."""
        pairs = pair_relatives([rel("s1")], [rel("t1")], lambda handle: None)
        self.assertEqual(self._names(pairs), [("s1", None), (None, "t1")])


# ------------------------------------------------------------
#
# The dialog rows
#
# ------------------------------------------------------------
class DialogRelativeRowsTest(unittest.TestCase):
    """Father/Mother/Spouse/Children rows of a Dad that differs only in order."""

    def setUp(self) -> None:
        self._paths: list[str] = []
        self.db = import_as_dict(self._write(TARGET_GED), User())
        self.gwizard = GedGWizard(self.db)
        self.assertTrue(
            self.gwizard.run_step("connect", gedcom_path=self._write(SOURCE_GED))
        )
        self.gwizard.run_step("load")
        self.source_db = self.gwizard.context["source_db"]

    def tearDown(self) -> None:
        self.source_db.close()
        self.db.close()
        for path in self._paths:
            if os.path.exists(path):
                os.remove(path)

    def _write(self, text: str) -> str:
        with tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write(text)
        self._paths.append(handle.name)
        return handle.name

    def _find(self, db: Any, first: str) -> Any:
        for found in db.iter_people():
            if found.get_primary_name().first_name == first:
                return found
        raise AssertionError(first)

    def _rows(self, add_new: bool = False) -> tuple[list[str], list[tuple[str, bool]]]:
        """Return the arrow keys and the (text, differs) of each value cell."""
        dialog = GWizardMergeDialog.__new__(GWizardMergeDialog)
        dialog.gwizard = self.gwizard
        dialog.source_db = self.source_db
        dialog.target_db = self.db
        source = self._find(self.source_db, "Dad")
        target = self._find(self.db, "Dad")
        dialog.source_handle = source.handle
        dialog.target_handle = None if add_new else target.handle
        dialog.source_person = source
        dialog.target_person = None if add_new else target
        dialog._resolutions = {}
        dialog._mergeable_count = 0
        dialog._matched_sources = set()
        dialog._grid = MagicMock()
        dialog._value_column_size_group = MagicMock()
        dialog._row_index = 0
        keys: list[str] = []
        dialog._make_arrow = lambda key, label: keys.append(key) or MagicMock()
        cells: list[tuple[str, bool]] = []

        def record(markup: str, differs: bool, xalign: float) -> Any:
            cells.append((markup, differs))
            return MagicMock()

        with patch.object(gwizardmergedialog, "create_diff_cell", record):
            dialog._populate_fields()
        return keys, cells

    def _handles(self, db: Any, *names: str) -> list[str]:
        return [self._find(db, name).handle for name in names]

    def test_same_children_in_another_order_get_no_arrows(self) -> None:
        """Anna and Bert are in the tree already; only Cora is tree-only.

        Anna's birth makes her two cells differ, but she is not offered.
        """
        keys, _cells = self._rows()
        self.assertEqual([key for key in keys if key.startswith("child:")], [])

    def test_children_are_listed_pair_by_pair(self) -> None:
        """Each incoming child sits on one row with its counterpart."""
        _keys, cells = self._rows()
        texts = [re.sub(r"<[^>]+>", "", text) for text, _differs in cells]
        anna = [i for i, t in enumerate(texts) if "Doe, Anna" in t]
        bert = [i for i, t in enumerate(texts) if "Doe, Bert" in t]
        # Each name is shown on the incoming and the tree side of one row.
        self.assertEqual(len(anna), 2)
        self.assertEqual(len(bert), 2)
        self.assertEqual(anna[1] - anna[0], 1)
        self.assertEqual(bert[1] - bert[0], 1)
        self.assertEqual(anna[0] % 2, 0)

    def test_same_spouses_in_another_order_get_no_arrows(self) -> None:
        """The wives are listed in the other order in the tree."""
        keys, _cells = self._rows()
        self.assertEqual([key for key in keys if key.startswith("spouse:")], [])

    def test_a_child_the_tree_lacks_still_gets_an_arrow(self) -> None:
        """Remove Anna from the tree: she is offered, Bert is not."""
        family_handle = self._find(self.db, "Dad").get_family_handle_list()
        from gramps.gen.db import DbTxn

        anna = self._find(self.db, "Anna")
        with DbTxn("remove", self.db) as trans:
            for handle in family_handle:
                fam = self.db.get_family_from_handle(handle)
                fam.set_child_ref_list(
                    [r for r in fam.get_child_ref_list() if r.ref != anna.handle]
                )
                self.db.commit_family(fam, trans)
            anna.set_parent_family_handle_list([])
            self.db.commit_person(anna, trans)
        keys, _cells = self._rows()
        source_anna = self._find(self.source_db, "Anna").handle
        source_bert = self._find(self.source_db, "Bert").handle
        self.assertIn("child:" + source_anna, keys)
        self.assertNotIn("child:" + source_bert, keys)

    def test_a_pair_the_window_rejected_is_offered_again(self) -> None:
        """ "Not a Match" in the window makes the incoming child a new one."""
        source_anna = self._find(self.source_db, "Anna").handle
        self.gwizard.context["pair_map"] = {source_anna: None}
        keys, _cells = self._rows()
        self.assertIn("child:" + source_anna, keys)

    def test_pair_map_decides_which_person_a_relative_is(self) -> None:
        """The window's pairing, not the name, decides who is already linked."""
        source_anna = self._find(self.source_db, "Anna").handle
        cora = self._find(self.db, "Cora").handle
        self.gwizard.context["pair_map"] = {source_anna: cora}
        keys, _cells = self._rows()
        # Anna is paired with Cora (a child of Dad's), so she gets no arrow.
        self.assertNotIn("child:" + source_anna, keys)

    def test_adding_as_new_lists_every_relative_with_an_arrow(self) -> None:
        """With no tree person every incoming relative is offered."""
        keys, _cells = self._rows(add_new=True)
        children = [key for key in keys if key.startswith("child:")]
        self.assertEqual(len(children), 2)


if __name__ == "__main__":
    unittest.main()
