#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  GWizard Merge Dialog Tests
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
Unit tests for the GWizard merge dialog and add-new confirmation dialog.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import sys
import tempfile
import unittest

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.errors import HandleError
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.lib import Event, EventRef, EventType, Name, Person, Surname


def _has_gtk_display() -> bool:
    """
    Return True only if a real Gtk display is available.
    """
    if sys.platform not in ("win32", "darwin"):
        if not os.environ.get("DISPLAY") or os.environ.get("GDK_BACKEND") == "-":
            return False
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        return bool(Gtk.init_check([])[0])
    except Exception:
        return False


_HAS_GTK_DISPLAY = _has_gtk_display()


# ------------------------------------------------------------
#
# GWizardDialogTest
#
# ------------------------------------------------------------
class GWizardDialogTest(unittest.TestCase):
    """
    Test suite for GWizardMergeDialog and GWizardAddNewDialog.
    """

    def setUp(self) -> None:
        """
        Create a clean target database.
        """
        self.db = make_database("sqlite")
        self.db.load(":memory:")

        with DbTxn("Add target person", self.db) as trans:
            self.target_person = Person()
            self.target_person.set_gender(Person.MALE)
            name = Name()
            name.first_name = "John"
            s1 = Surname()
            s1.set_surname("Doe")
            name.add_surname(s1)
            self.target_person.set_primary_name(name)
            self.db.add_person(self.target_person, trans)

            self.birth_event = Event()
            self.birth_event.set_type(EventType.BIRTH)
            self.db.add_event(self.birth_event, trans)

            eref = EventRef()
            eref.ref = self.birth_event.handle
            self.target_person.set_birth_ref(eref)
            self.db.commit_person(self.target_person, trans)

    def tearDown(self) -> None:
        """
        Close the target database.
        """
        self.db.close()

    @unittest.skipUnless(
        _HAS_GTK_DISPLAY,
        "needs a real Gtk display; skipped in headless/no-display environments",
    )
    def test_format_diff_line(self) -> None:
        """
        Test the GWizardMergeDialog's static method for rendering
        Pango-highlighted differences between values.
        """
        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        # Exact match (should be plain)
        res = GWizardMergeDialog._format_diff_line(
            "Given Name", "John", "John", show_label=False, is_left=True
        )
        self.assertEqual(res, "John")

        # Differ (one word differs)
        res_diff = GWizardMergeDialog._format_diff_line(
            "Given Name", "John James", "John Paul", show_label=False, is_left=True
        )
        self.assertIn("James", res_diff)

        # Show label
        res_label = GWizardMergeDialog._format_diff_line(
            "Given Name", "John", "John", show_label=True, is_left=True
        )
        self.assertEqual(res_label, "Given Name: John")

    @unittest.skipUnless(
        _HAS_GTK_DISPLAY,
        "needs a real Gtk display; skipped in headless/no-display environments",
    )
    def test_dialog_find_dangling_references(self) -> None:
        """
        Verify that GWizardMergeDialog._find_dangling_references correctly
        detects and categorizes missing references prior to merge.
        """
        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        gedcom_data = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME John /Doe/
2 GIVN John
2 SURN Doe
1 SEX M
1 BIRT
2 DATE 15 JUN 1980
2 SOUR @S1@
3 PAGE 42
0 @S1@ SOUR
1 TITL Famous Book of Doe
1 NOTE @N1@
0 @N1@ NOTE This is a linked note for a source.
0 TRLR
"""
        with tempfile.NamedTemporaryFile(suffix=".ged", mode="w", delete=False) as f:
            f.write(gedcom_data)
            temp_path = f.name

        try:
            gwizard = GedGWizard(self.db)
            gwizard.run_step("connect", gedcom_path=temp_path)
            people = gwizard.run_step("load")
            source_person = people[0]

            class MockDbState:
                def __init__(self, db):
                    self.db = db

            dbstate = MockDbState(self.db)
            dialog = GWizardMergeDialog(
                dbstate=dbstate,
                gwizard=gwizard,
                source_handle=source_person.handle,
                target_handle=self.target_person.handle,
            )

            dialog._resolutions = {
                "birth_event": "source",
            }

            missing = dialog._find_dangling_references()
            self.assertTrue(len(missing["citation"]) > 0)
            self.assertTrue(len(missing["source"]) > 0)
            self.assertTrue(len(missing["note"]) > 0)

            dialog._resolutions = {}
            missing_empty = dialog._find_dangling_references()
            self.assertEqual(len(missing_empty["citation"]), 0)
            self.assertEqual(len(missing_empty["source"]), 0)
            self.assertEqual(len(missing_empty["note"]), 0)

            dialog.destroy()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @unittest.skipUnless(
        _HAS_GTK_DISPLAY,
        "needs a real Gtk display; skipped in headless/no-display environments",
    )
    def test_dialog_rejects_dangling_source_handle(self) -> None:
        """
        Opening the merge dialog with a handle that no longer resolves
        must raise HandleError instead of failing later with an AttributeError.
        """
        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        class MockDbState:
            def __init__(self, db):
                self.db = db

        gedcom_data = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Solo /Person/
2 GIVN Solo
2 SURN Person
0 TRLR
"""
        with tempfile.NamedTemporaryFile(suffix=".ged", mode="w", delete=False) as f:
            f.write(gedcom_data)
            temp_path = f.name

        try:
            gwizard = GedGWizard(self.db)
            gwizard.run_step("connect", gedcom_path=temp_path)

            with self.assertRaises(HandleError):
                GWizardMergeDialog(
                    dbstate=MockDbState(self.db),
                    gwizard=gwizard,
                    source_handle="0000006e0000006e",
                    target_handle=None,
                )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @unittest.skipUnless(
        _HAS_GTK_DISPLAY,
        "needs a real Gtk display; skipped in headless/no-display environments",
    )
    def test_dialog_opens_in_add_as_new_mode(self) -> None:
        """
        With no target handle the dialog must still build for unmatched people.
        """
        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        gedcom_data = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Solo /Person/
2 GIVN Solo
2 SURN Person
0 TRLR
"""
        with tempfile.NamedTemporaryFile(suffix=".ged", mode="w", delete=False) as f:
            f.write(gedcom_data)
            temp_path = f.name

        try:
            gwizard = GedGWizard(self.db)
            gwizard.run_step("connect", gedcom_path=temp_path)
            people = gwizard.run_step("load")
            source_person = people[0]

            class MockDbState:
                def __init__(self, db):
                    self.db = db

            dialog = GWizardMergeDialog(
                dbstate=MockDbState(self.db),
                gwizard=gwizard,
                source_handle=source_person.handle,
                target_handle=None,
            )
            self.assertTrue(dialog._row_index > 0)
            dialog.destroy()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
