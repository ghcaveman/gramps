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
Tests for numbered file names ("..._2.jpg").

When two media files would get the same standard name, the second gets the
name numbered "_2" (Media Fix's consolidation does this, and so do the
record-source tools when they download a file). Such a name is standard
while the plain standard name belongs to a different file: the report does
not list it as non-standard and Accept all does not try to rename it.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import shutil
import tempfile
import unittest

# -------------------------------------------------------------------------
#
# GTK test doubles: installed before any GWizard module is imported.
#
# -------------------------------------------------------------------------
from gramps.plugins.tool.test import gwizard_gtk_fakes as fakes

Gtk = fakes.install()

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Media, MediaRef, Name, Person, Surname
from gramps.plugins.tool import gwizard_mediafix_common as gc
from gramps.plugins.tool import gwizardmediafix as mf

TEMPLATE = "{ref_id}_{surname}_{given}-{doc_type}-{year}.{ext}"
STANDARD = "I0001_Smith_John-Census-1920.jpg"
NUMBERED = "I0001_Smith_John-Census-1920_2.jpg"


def setUpModule() -> None:
    """Install the GTK fakes for this module's tests."""
    fakes.install()


def tearDownModule() -> None:
    """Restore the real GTK classes for other test modules."""
    fakes.uninstall()


class NumberedNameTest(unittest.TestCase):
    """Two census images of John Smith that both name as STANDARD."""

    def setUp(self) -> None:
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "MediaBase")
        os.makedirs(self.base)
        self.db.set_mediapath(self.base)
        self.person: Person | None = None

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _file(self, name: str, data: bytes) -> str:
        path = os.path.join(self.base, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def _media(self, gid: str, name: str) -> str:
        """Add a census image of John Smith stored as ``name``."""
        with DbTxn("add media", self.db) as trans:
            media = Media()
            media.set_gramps_id(gid)
            media.set_path(name)
            media.set_description("Smith, John - Census 1920")
            handle = self.db.add_media(media, trans)
            if self.person is None:
                self.person = Person()
                self.person.set_gramps_id("I0001")
                pname = Name()
                pname.set_first_name("John")
                surname = Surname()
                surname.set_surname("Smith")
                pname.add_surname(surname)
                self.person.set_primary_name(pname)
                self.db.add_person(self.person, trans)
            ref = MediaRef()
            ref.set_reference_handle(handle)
            self.person.add_media_reference(ref)
            self.db.commit_person(self.person, trans)
            return handle

    def _both(self) -> None:
        self._file(STANDARD, b"first page")
        self._file(NUMBERED, b"second page")
        self._media("O0001", STANDARD)
        self._media("O0002", NUMBERED)

    def _moves(self) -> list[tuple[str, str]]:
        return [
            (os.path.basename(m["src_full"]), os.path.basename(m["dest_full"]))
            for m in mf.plan_consolidation_moves(self.db, self.base, TEMPLATE)
        ]

    def test_numbered_name_kept_by_accept_all(self) -> None:
        """Nothing to move: both files already have their standard names."""
        self._both()
        self.assertEqual(self._moves(), [])

    def test_numbered_name_not_reported_as_non_standard(self) -> None:
        self._both()
        text = mf.generate_media_fix_report(self.db, check_content=False)
        self.assertNotIn(NUMBERED, text)

    def test_numbered_name_without_the_standard_file_is_renamed(self) -> None:
        """With the standard name free, the numbered file takes it."""
        self._file(NUMBERED, b"only page")
        self._media("O0002", NUMBERED)
        self.assertEqual(self._moves(), [(NUMBERED, STANDARD)])
        text = mf.generate_media_fix_report(self.db, check_content=False)
        self.assertIn(NUMBERED, text)

    def test_old_dash_numbered_name_gets_the_underscore_form(self) -> None:
        """A "-2" name (from earlier downloads) is renamed to "_2"."""
        dashed = "I0001_Smith_John-Census-1920-2.jpg"
        self._file(STANDARD, b"first page")
        self._file(dashed, b"second page")
        self._media("O0001", STANDARD)
        self._media("O0002", dashed)
        self.assertEqual(self._moves(), [(dashed, NUMBERED)])

    def test_keeps_numbered_name(self) -> None:
        standard = self._file(STANDARD, b"first page")
        numbered = self._file(NUMBERED, b"second page")
        self.assertTrue(gc.keeps_numbered_name(numbered, standard))
        # The standard name is not taken: the number has no reason to be.
        os.remove(standard)
        self.assertFalse(gc.keeps_numbered_name(numbered, standard))
        # Not a numbered form of that name.
        self.assertFalse(gc.keeps_numbered_name(standard, numbered))

    def test_unique_destination_numbers_with_underscore(self) -> None:
        standard = self._file(STANDARD, b"first page")
        self.assertEqual(
            os.path.basename(gc.unique_destination(standard, set())), NUMBERED
        )


if __name__ == "__main__":
    unittest.main()
