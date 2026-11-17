#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Gramps project
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
Tests for two problems found in a run on gwizard_data_base.ged:

- Gramps IDs were compared as text, so M17 sorted before M7. Merging the
  duplicate pair kept the "(copy)" record M17, and consolidation named the
  shared file after M17's person instead of M7's.
- An unreferenced record whose only note was the GEDCOM import's
  "Records not imported into OBJE" note counted as having user data, so it
  was never deleted.
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
from unittest.mock import MagicMock, patch

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
from gramps.gen.lib import Media, MediaRef, Name, Note, Person, Surname
from gramps.plugins.tool import gwizard_common as gc
from gramps.plugins.tool import gwizardmediafix as mf
from gramps.plugins.tool.gw_fixmediareferencesdialog import (
    FixMediaReferencesDialog,
    find_duplicate_media_groups,
)

_DLG = "gramps.plugins.tool.gw_fixmediareferencesdialog.OkDialog"
TEMPLATE = "{ref_id}_{surname}_{given}-{doc_type}-{year}.{ext}"
IMPORT_TEXT = (
    "Records not imported into OBJE (multi-media object) Gramps ID M8:\n\n"
    "Could not import unknown_woman_1900.jpg    Line   347: 1 FILE ...\n"
)


def setUpModule() -> None:
    """Install the GTK fakes for this module's tests."""
    fakes.install()


def tearDownModule() -> None:
    """Restore the real GTK classes for other test modules."""
    fakes.uninstall()


class _DbState:
    """Minimal stand-in for Gramps' DbState."""

    def __init__(self, db: object) -> None:
        self.db = db


class _DbTestCase(unittest.TestCase):
    """In-memory database plus a temporary media folder."""

    def setUp(self) -> None:
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = _DbState(self.db)
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "MediaBase")
        os.makedirs(self.base)
        self.db.set_mediapath(self.base)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_media(self, gid: str, path: str, desc: str, note: str = "") -> str:
        """Add a media record with a fixed Gramps ID; return its handle."""
        with DbTxn("add media", self.db) as trans:
            media = Media()
            media.set_gramps_id(gid)
            media.set_path(path)
            media.set_description(desc)
            if note:
                obj = Note()
                obj.set(note)
                media.add_note(self.db.add_note(obj, trans))
            return self.db.add_media(media, trans)

    def add_person(self, gid: str, surname: str, given: str, media_handle: str) -> str:
        """Add a person with one media reference; return its handle."""
        with DbTxn("add person", self.db) as trans:
            person = Person()
            person.set_gramps_id(gid)
            name = Name()
            name.set_first_name(given)
            sur = Surname()
            sur.set_surname(surname)
            name.add_surname(sur)
            person.set_primary_name(name)
            ref = MediaRef()
            ref.set_reference_handle(media_handle)
            person.add_media_reference(ref)
            return self.db.add_person(person, trans)

    def add_reunion_pair(self) -> tuple[str, str]:
        """The M7/M17 pair from gwizard_data_base.ged, sharing one file."""
        shared = os.path.join(self.tmp, "old", "family_reunion_1950.jpg")
        os.makedirs(os.path.dirname(shared), exist_ok=True)
        with open(shared, "wb") as handle:
            handle.write(b"reunion")
        h7 = self.add_media("M7", shared, "Turner family reunion, 1950")
        h17 = self.add_media("M17", shared, "Turner family reunion, 1950 (copy)")
        self.add_person("I00012", "Turner", "William", h7)
        self.add_person("I00013", "Harris", "Elizabeth", h17)
        return h7, h17


# ------------------------------------------------------------
#
# Gramps IDs sort by number
#
# ------------------------------------------------------------
class GrampsIdSortTest(_DbTestCase):
    """M7 comes before M17 wherever records are ranked."""

    def test_gramps_id_key_orders_by_number(self) -> None:
        """M7 < M17 < M100; zero-padded and odd IDs still sort."""
        ids = ["M17", "M100", "M7", "I00012", "I00009", "odd"]
        self.assertEqual(
            sorted(ids, key=gc.gramps_id_key),
            ["I00009", "I00012", "M7", "M17", "M100", "odd"],
        )

    def test_duplicate_merge_keeps_lower_id(self) -> None:
        """The duplicate group's keeper is M7, not the '(copy)' record M17."""
        h7, _h17 = self.add_reunion_pair()
        groups = [
            g for g in find_duplicate_media_groups(self.db) if g["type"] == "duplicate"
        ]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["keeper"]["handle"], h7)

    def test_accept_all_plan_merges_into_m7(self) -> None:
        """Accept all plans M17 -> M7."""
        self.add_reunion_pair()
        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertEqual([(k, o) for k, o, _p in plan["merges"]], [("M7", ["M17"])])

    def test_shared_file_named_after_m7(self) -> None:
        """Consolidating the shared file names it after M7's person."""
        self.add_reunion_pair()
        moves = mf.plan_consolidation_moves(self.db, self.base, TEMPLATE)
        self.assertEqual(len(moves), 1)
        name = os.path.basename(moves[0]["dest_full"])
        self.assertTrue(name.startswith("I00012_Turner_William-"), name)


# ------------------------------------------------------------
#
# Import-debris notes don't make a record worth keeping
#
# ------------------------------------------------------------
class ImportNoteBareTest(_DbTestCase):
    """An unreferenced record with only the import's note is deleted."""

    def test_is_bare_ignores_import_note(self) -> None:
        """Only the import note: bare with a db, not bare without one."""
        media = self.db.get_media_from_handle(
            self.add_media("M8", "unknown_woman_1900.jpg", "Unknown", IMPORT_TEXT)
        )
        self.assertTrue(gc.is_bare_media(media, self.db))
        self.assertFalse(gc.is_bare_media(media))

    def test_is_bare_keeps_real_note(self) -> None:
        """A note the user wrote still keeps the record."""
        media = self.db.get_media_from_handle(
            self.add_media("M8", "unknown_woman_1900.jpg", "Unknown", "Aunt Rose?")
        )
        self.assertFalse(gc.is_bare_media(media, self.db))

    def test_accept_all_plan_deletes_import_note_only_record(self) -> None:
        """Accept all plans the delete instead of 'kept; review manually'."""
        self.add_media("M8", "unknown_woman_1900.jpg", "Unknown", IMPORT_TEXT)
        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertEqual([gid for gid, _p in plan["delete"]], ["M8"])
        self.assertEqual(plan["keep_unref"], [])

    def test_dialog_delete_removes_import_note_too(self) -> None:
        """Fix references deletes the record and its now-orphaned import note."""
        handle = self.add_media("M8", "unknown_woman_1900.jpg", "Unknown", IMPORT_TEXT)
        note_handle = self.db.get_media_from_handle(handle).get_note_list()[0]
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        actions = {
            t["group"]["keeper"]["handle"]: t["suggested_action"]
            for t in dlg.row_targets
        }
        self.assertEqual(actions[handle], 0)  # Delete
        with patch(_DLG):
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())
        self.assertFalse(self.db.has_media_handle(handle))
        self.assertFalse(self.db.has_note_handle(note_handle))


if __name__ == "__main__":
    unittest.main()
