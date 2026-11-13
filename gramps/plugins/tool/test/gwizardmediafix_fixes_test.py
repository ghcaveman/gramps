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

"""Regression tests for the GWizard Media Fix review fixes (batches 1 and 2).

1. Accept hints in Fix media references never suggests deleting a record that
   has notes, attributes, tags, citations or a date.
2. Find missing media never repoints two different records at one file found
   by name (they would then be merged as duplicates).
6. Consolidate media location lists only records that are not consolidated.
7. find_duplicate_media_groups survives media_path_full() raising.
8. Windows drive paths are recognised and compared on Linux and macOS.

Batch 2:

3. A shared file is moved once with all its records; a file shared with a
   locked record stays put without blocking anything else; the Accept-all
   preview and the real run agree.
4. Changing the base media path keeps other relative records pointing at
   their files.
9. A file attached to a shared (household) census event is named after the
   person in its description, or deterministically when none is named.
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
# GTK fakes: importing the main test module installs them before any GWizard
# module (and so any Gtk base class) is imported.
#
# -------------------------------------------------------------------------
from gramps.plugins.tool import gwizardmediafix_test as _gtk_fakes  # noqa: F401

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.errors import HandleError
from gramps.gen.lib import (
    Attribute,
    AttributeType,
    Citation,
    Date,
    Event,
    EventRef,
    EventType,
    Media,
    MediaRef,
    Name,
    Person,
    Source,
    Surname,
)
from gramps.plugins.tool import gwizard_common as gc
from gramps.plugins.tool import gwizardmediafix as mf
from gramps.plugins.tool.gw_fixmediareferencesdialog import (
    FixMediaReferencesDialog,
    find_duplicate_media_groups,
)

_DLG = "gramps.plugins.tool.gw_fixmediareferencesdialog.OkDialog"
_MF_DLG = "gramps.plugins.tool.gwizardmediafix.OkDialog"


class _DbState:
    """Minimal stand-in for Gramps' DbState."""

    def __init__(self, db: object) -> None:
        self.db = db


# ------------------------------------------------------------
#
# _DbTestCase
#
# ------------------------------------------------------------
class _DbTestCase(unittest.TestCase):
    """In-memory database plus a temporary media folder."""

    def setUp(self) -> None:
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = _DbState(self.db)
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "MediaBase")
        os.makedirs(self.base)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_media(self, path: str, desc: str = "", attr: bool = False) -> str:
        """Add a media record and return its handle."""
        with DbTxn("add media", self.db) as trans:
            media = Media()
            media.set_path(path)
            media.set_description(desc)
            if attr:
                attribute = Attribute()
                attribute.set_type(AttributeType.CUSTOM)
                attribute.set_value("keep me")
                media.add_attribute(attribute)
            return self.db.add_media(media, trans)

    def touch(self, *parts: str) -> str:
        """Create a small file under the temp folder and return its path."""
        path = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(path)
        return path


# ------------------------------------------------------------
#
# Fix 1: Accept hints never deletes a record with data
#
# ------------------------------------------------------------
class AcceptHintsDeletionTest(_DbTestCase):
    """Fix media references: Accept hints suggests delete only for bare records."""

    def test_non_bare_unreferenced_record_survives_accept_hints(self) -> None:
        """A record with an attribute is kept after Accept hints + Apply."""
        h_data = self.add_media("orphan_with_data.jpg", "Has data", attr=True)
        h_bare = self.add_media("orphan_bare.jpg", "Bare")

        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        suggested = {
            t["group"]["keeper"]["handle"]: t["suggested_action"]
            for t in dlg.row_targets
        }
        self.assertEqual(suggested[h_data], 1)  # Keep
        self.assertEqual(suggested[h_bare], 0)  # Delete

        with patch(_DLG):
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())

        self.assertIsNotNone(self.db.get_media_from_handle(h_data))
        with self.assertRaises(HandleError):
            self.db.get_media_from_handle(h_bare)

    def test_default_selection_is_keep(self) -> None:
        """Without Accept hints, Apply deletes nothing (default stays Keep)."""
        h_bare = self.add_media("orphan_bare.jpg", "Bare")
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        with patch(_DLG):
            dlg.cb_apply(MagicMock())
        self.assertIsNotNone(self.db.get_media_from_handle(h_bare))

    def test_is_bare_media(self) -> None:
        """is_bare_media is False once a record carries an attribute."""
        bare = self.db.get_media_from_handle(self.add_media("a.jpg"))
        rich = self.db.get_media_from_handle(self.add_media("b.jpg", attr=True))
        self.assertTrue(gc.is_bare_media(bare))
        self.assertFalse(gc.is_bare_media(rich))
        self.assertFalse(mf.GWizardMediaFix._is_bare_media(rich))


# ------------------------------------------------------------
#
# Fix 2: a file found by name is never given to two different records
#
# ------------------------------------------------------------
class AmbiguousFindTest(_DbTestCase):
    """Find missing media holds back matches shared by different records."""

    def setUp(self) -> None:
        super().setUp()
        self.db.set_mediapath(self.base)
        with open(os.path.join(self.base, "scan1.jpg"), "w", encoding="utf-8") as f:
            f.write("one file")
        self.h_smith = self.add_media("C:/Smith/scan1.jpg", "Smith scan")
        self.h_jones = self.add_media("D:/Jones/scan1.jpg", "Jones scan")

    def test_ambiguous_matches_helper(self) -> None:
        """Different origins are ambiguous; identical origins are not."""
        self.assertEqual(
            mf.ambiguous_matches(
                [("a", "C:/x/p.jpg", "p.jpg"), ("b", "D:/y/p.jpg", "p.jpg")]
            ),
            {"a", "b"},
        )
        self.assertEqual(
            mf.ambiguous_matches(
                [("a", "old/p.jpg", "p.jpg"), ("b", "old/p.jpg", "p.jpg")]
            ),
            set(),
        )
        self.assertEqual(
            mf.ambiguous_matches(
                [("a", r"C:\X\p.jpg", "p.jpg"), ("b", "c:/x/P.JPG", "p.jpg")]
            ),
            set(),
        )

    def test_auto_find_does_not_repoint_ambiguous_records(self) -> None:
        """_auto_find_missing leaves both records alone and reports them."""
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        resolved, unresolved, _denied = tool._auto_find_missing(self.db)
        self.assertEqual(resolved, 0)
        self.assertEqual(len(unresolved), 2)
        self.assertEqual(
            self.db.get_media_from_handle(self.h_smith).get_path(),
            "C:/Smith/scan1.jpg",
        )
        self.assertEqual(
            self.db.get_media_from_handle(self.h_jones).get_path(),
            "D:/Jones/scan1.jpg",
        )
        # ...so nothing became a duplicate for the merge step to swallow.
        dups = [
            g for g in find_duplicate_media_groups(self.db) if g["type"] == "duplicate"
        ]
        self.assertEqual(dups, [])

    def test_plan_lists_ambiguous_not_find(self) -> None:
        """The Accept-all preview shows the hold-back instead of a repoint."""
        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertEqual(plan["find"], [])
        self.assertEqual(len(plan["ambiguous"]), 2)
        self.assertIn("NOT repointed", mf.format_plan(plan))

    def test_find_missing_dialog_gives_no_hint(self) -> None:
        """The Find missing dialog offers no suggestion for either record."""
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        self.assertEqual(len(dlg.rows), 2)
        for row in dlg.rows:
            self.assertEqual(row["suggested_path"], "")
            self.assertIn("also matches", row["hint_text"])

    def test_unique_match_still_repointed(self) -> None:
        """A single record matching a file is still found automatically."""
        h_other = self.add_media("E:/Old/unique.jpg", "Unique")
        with open(os.path.join(self.base, "unique.jpg"), "w", encoding="utf-8") as f:
            f.write("u")
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        resolved, _unresolved, _denied = tool._auto_find_missing(self.db)
        self.assertEqual(resolved, 1)
        self.assertEqual(
            self.db.get_media_from_handle(h_other).get_path(), "unique.jpg"
        )


# ------------------------------------------------------------
#
# Fix 6: Consolidate lists only unconsolidated records
#
# ------------------------------------------------------------
class ConsolidateListingTest(_DbTestCase):
    """Records already stored relative under their standard name are not listed."""

    def test_already_consolidated_record_not_listed(self) -> None:
        """Relative + standard name is skipped; others are still listed."""
        self.db.set_mediapath(self.base)
        h_done = self.add_media("placeholder.jpg", "Done")
        done = self.db.get_media_from_handle(h_done)
        std = "%s-Done.jpg" % done.get_gramps_id()
        with DbTxn("set path", self.db) as trans:
            done.set_path(std)
            self.db.commit_media(done, trans)

        h_rel = self.add_media("sub/raw name.jpg", "Raw")
        h_abs = self.add_media(os.path.join(self.tmp, "elsewhere.jpg"), "Abs")

        dlg = mf.ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        listed = {r["handle"] for r in dlg.rows}
        self.assertNotIn(h_done, listed)
        self.assertIn(h_rel, listed)
        self.assertIn(h_abs, listed)

    def test_nothing_to_do_when_all_consolidated(self) -> None:
        """With only consolidated records the dialog has no rows."""
        self.db.set_mediapath(self.base)
        h_done = self.add_media("placeholder.jpg", "Done")
        done = self.db.get_media_from_handle(h_done)
        with DbTxn("set path", self.db) as trans:
            done.set_path("%s-Done.jpg" % done.get_gramps_id())
            self.db.commit_media(done, trans)
        dlg = mf.ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        self.assertEqual(dlg.rows, [])


# ------------------------------------------------------------
#
# Fix 7: duplicate scan survives media_path_full raising
#
# ------------------------------------------------------------
class DuplicateScanRobustnessTest(_DbTestCase):
    """find_duplicate_media_groups no longer raises UnboundLocalError."""

    def test_media_path_full_raising(self) -> None:
        """Records still group by their stored path when resolution fails."""
        self.add_media("shared/a.jpg", "One")
        self.add_media("shared/a.jpg", "Two")
        with patch(
            "gramps.plugins.tool.gwizard_common.media_path_full",
            side_effect=ValueError("bad media path"),
        ):
            groups = find_duplicate_media_groups(self.db)
        dups = [g for g in groups if g["type"] == "duplicate"]
        self.assertEqual(len(dups), 1)
        self.assertEqual(len(dups[0]["records"]), 2)

    def test_report_and_dialog_agree_on_windows_paths(self) -> None:
        """ "C:\\X\\a.jpg" and "c:/x/a.jpg" are one file for report and dialog."""
        self.add_media(r"C:\X\a.jpg", "One")
        self.add_media("c:/x/a.jpg", "Two")
        dialog_dups = [
            g for g in find_duplicate_media_groups(self.db) if g["type"] == "duplicate"
        ]
        self.assertEqual(len(dialog_dups), 1)
        self.assertEqual(len(mf.find_duplicate_media_references(self.db)), 1)


# ------------------------------------------------------------
#
# Fix 8: Windows paths on every platform
#
# ------------------------------------------------------------
class WindowsPathTest(unittest.TestCase):
    """Path helpers treat Windows-style paths the same on every OS."""

    def test_is_absolute_path_drive(self) -> None:
        """Drive paths with either separator are absolute everywhere."""
        self.assertTrue(gc.is_absolute_path(r"C:\photos\photo.jpg"))
        self.assertTrue(gc.is_absolute_path("c:/photos/photo.jpg"))
        self.assertFalse(gc.is_absolute_path("C:photo.jpg"))  # drive-relative
        self.assertFalse(gc.is_absolute_path("photos/photo.jpg"))

    def test_is_windows_style_path(self) -> None:
        """Drive and UNC paths are Windows-style; POSIX paths are not."""
        self.assertTrue(gc.is_windows_style_path(r"C:\x.jpg"))
        self.assertTrue(gc.is_windows_style_path(r"\\server\share\x.jpg"))
        self.assertFalse(gc.is_windows_style_path("/home/x.jpg"))
        self.assertFalse(gc.is_windows_style_path("rel/x.jpg"))

    def test_path_key_windows(self) -> None:
        """Separators and case are normalised for Windows-style paths."""
        self.assertEqual(
            gc.path_key(r"C:\Photos\Family\Pic.JPG"),
            gc.path_key(' "c:/photos/family/pic.jpg" '),
        )

    @unittest.skipIf(os.name == "nt", "POSIX case-sensitivity check")
    @unittest.skipIf(
        __import__("sys").platform == "darwin", "macOS folds case by default"
    )
    def test_path_key_posix_case_preserved(self) -> None:
        """On Linux, distinct-case POSIX paths stay distinct files."""
        self.assertNotEqual(gc.path_key("/a/Pic.jpg"), gc.path_key("/a/pic.jpg"))

    def test_full_media_path_keeps_drive_path(self) -> None:
        """A drive path is never joined onto the media base path."""
        db = MagicMock()
        self.assertEqual(gc.full_media_path(db, r"C:\x\y.jpg"), r"C:\x\y.jpg")
        self.assertEqual(gc.full_media_path(db, "  "), "")


# ------------------------------------------------------------
#
# Fix 9: shared census events name the described person
#
# ------------------------------------------------------------
class SharedCensusNamingTest(_DbTestCase):
    """The resolver picks the described person from a household event."""

    HOUSEHOLD = [
        ("I0003", "Fuller", "Harry Jay"),
        ("I0001", "Fuller", "Anna"),
        ("I0002", "Fuller", "Lilly"),
    ]

    def build(
        self, desc: str, via_citation: bool = True, reverse: bool = False
    ) -> Media:
        """Create a 1910 census shared by a household; attach a media record."""
        people = list(reversed(self.HOUSEHOLD)) if reverse else list(self.HOUSEHOLD)
        with DbTxn("household", self.db) as trans:
            media = Media()
            media.set_path("scan.jpg")
            media.set_description(desc)
            m_h = self.db.add_media(media, trans)
            mref = MediaRef()
            mref.set_reference_handle(m_h)

            event = Event()
            event.set_type(EventType.CENSUS)
            date = Date()
            date.set_year(1910)
            event.set_date_object(date)
            if via_citation:
                src = Source()
                src.set_title("FamilySearch")
                s_h = self.db.add_source(src, trans)
                cit = Citation()
                cit.set_reference_handle(s_h)
                cit.add_media_reference(mref)
                c_h = self.db.add_citation(cit, trans)
                event.add_citation(c_h)
            else:
                event.add_media_reference(mref)
            e_h = self.db.add_event(event, trans)

            for gid, sur, giv in people:
                person = Person()
                person.set_gramps_id(gid)
                name = Name()
                surname = Surname()
                surname.set_surname(sur)
                name.add_surname(surname)
                name.set_first_name(giv)
                person.set_primary_name(name)
                eref = EventRef()
                eref.set_reference_handle(e_h)
                person.add_event_ref(eref)
                self.db.add_person(person, trans)
        return self.db.get_media_from_handle(m_h)

    def test_citation_chain_picks_described_person(self) -> None:
        """Citation -> shared Event -> the person named in the description."""
        ctx = mf.resolve_media_reference_context(
            self.db, self.build("Fuller, Lilly - 1910Census")
        )
        self.assertEqual((ctx["ref_id"], ctx["given"]), ("I0002", "Lilly"))

    def test_spelling_variant_still_matches(self) -> None:
        """A close misspelling ('Fuler') still picks Lilly, not the first person."""
        ctx = mf.resolve_media_reference_context(
            self.db, self.build("Fuler, Lilly - 1910Census")
        )
        self.assertEqual(ctx["ref_id"], "I0002")

    def test_event_chain_picks_described_person(self) -> None:
        """Media on the shared event itself also uses the description."""
        ctx = mf.resolve_media_reference_context(
            self.db,
            self.build("Fuller, Anna - 1910Census", via_citation=False),
        )
        # Anna is neither the first participant added nor the last
        self.assertEqual((ctx["ref_id"], ctx["given"]), ("I0001", "Anna"))

    def test_undescribed_is_lowest_gramps_id_in_any_order(self) -> None:
        """No name in the description: lowest Gramps ID, whatever the order."""
        first = mf.resolve_media_reference_context(self.db, self.build("census scan"))
        self.db.close()
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        second = mf.resolve_media_reference_context(
            self.db, self.build("census scan", reverse=True)
        )
        self.assertEqual(first["ref_id"], "I0001")
        self.assertEqual(second["ref_id"], "I0001")


# ------------------------------------------------------------
#
# Fix 3: shared files move as a group; locked shares are held
#
# ------------------------------------------------------------
class SharedFileConsolidationTest(_DbTestCase):
    """Consolidation moves a shared file once and repoints all its records."""

    def setUp(self) -> None:
        super().setUp()
        self.db.set_mediapath(self.base)
        self.tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        self.tool.dbstate = self.dbstate

    def test_auto_moves_shared_file_once(self) -> None:
        """Both records end on the same new path; the file moved once."""
        shared = self.touch("old", "shared.jpg")
        h1 = self.add_media(shared, "Shared")
        h2 = self.add_media(shared, "Shared")
        count, problems = self.tool._auto_consolidate_location(self.db)
        self.assertEqual((count, problems), (1, []))
        p1 = self.db.get_media_from_handle(h1).get_path()
        p2 = self.db.get_media_from_handle(h2).get_path()
        self.assertEqual(p1, p2)
        self.assertFalse(os.path.isabs(p1))
        self.assertTrue(os.path.exists(os.path.join(self.base, p1)))
        self.assertFalse(os.path.exists(shared))

    def test_locked_share_is_held_and_does_not_block_others(self) -> None:
        """A file shared with a locked record stays; other files still move."""
        shared = self.touch("old", "shared.jpg")
        h_locked = self.add_media(shared, "Locked copy")
        h_free = self.add_media(shared, "Free copy")
        gc.lock_media(self.db, self.db.get_media_from_handle(h_locked), commit=True)
        single = self.touch("old", "single.jpg")
        h_single = self.add_media(single, "Single", attr=True)  # kept by step 2

        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertEqual(len(plan["moves"]), 1)
        self.assertEqual(len(plan["held"]), 1)
        self.assertIn("Files left in place", mf.format_plan(plan))

        count, problems = self.tool._auto_consolidate_location(self.db)
        self.assertEqual(count, len(plan["moves"]))  # preview == run
        self.assertTrue(any("locked" in p[2] for p in problems))
        self.assertTrue(os.path.exists(shared))
        self.assertEqual(self.db.get_media_from_handle(h_free).get_path(), shared)
        self.assertFalse(
            os.path.isabs(self.db.get_media_from_handle(h_single).get_path())
        )
        self.assertNotEqual(self.db.get_media_from_handle(h_locked).get_path(), "")

    def test_dialog_apply_moves_shared_file_once(self) -> None:
        """The grouped dialog row repoints every record that shared the file."""
        shared = self.touch("old", "shared.jpg")
        h1 = self.add_media(shared, "Shared")
        h2 = self.add_media(shared, "Shared")
        dlg = mf.ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        self.assertEqual(len(dlg.rows), 1)
        with patch(_MF_DLG):
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())
        p1 = self.db.get_media_from_handle(h1).get_path()
        self.assertEqual(p1, self.db.get_media_from_handle(h2).get_path())
        self.assertTrue(os.path.exists(os.path.join(self.base, p1)))


# ------------------------------------------------------------
#
# Fix 4: base path changes keep other records valid
#
# ------------------------------------------------------------
class BasePathChangeTest(_DbTestCase):
    """Changing the base media path never silently breaks other records."""

    def setUp(self) -> None:
        super().setUp()
        self.db.set_mediapath(self.base)
        with open(os.path.join(self.base, "a.jpg"), "w", encoding="utf-8") as f:
            f.write("a")
        self.h_ok = self.add_media("a.jpg", "Present")
        self.h_missing = self.add_media("lost/b.jpg", "Missing")
        self.new_base = os.path.join(self.tmp, "NewBase")
        os.makedirs(self.new_base)

    def change_base(self, dlg: object, new_base: str) -> None:
        """Type a new base path into a dialog and press Apply."""
        dlg.path_entry.set_text(new_base)
        dlg.cb_set_mediapath()
        with patch(_MF_DLG) as ok_dialog:
            dlg.cb_apply(MagicMock())
        self.last_message = ok_dialog.call_args[0][1]

    def test_find_missing_keeps_present_record(self) -> None:
        """Outside the new base: the present record becomes absolute."""
        self.change_base(mf.FindMissingMediaDialog(dbstate=self.dbstate), self.new_base)
        self.assertEqual(self.db.get_mediapath(), self.new_base)
        path = self.db.get_media_from_handle(self.h_ok).get_path()
        self.assertTrue(os.path.isabs(path))
        self.assertTrue(os.path.samefile(path, os.path.join(self.base, "a.jpg")))
        # a record that was missing anyway is left to resolve against the new base
        self.assertEqual(
            self.db.get_media_from_handle(self.h_missing).get_path(), "lost/b.jpg"
        )
        self.assertIn("still point at their files", self.last_message)

    def test_new_base_containing_old_keeps_relative_path(self) -> None:
        """New base is a parent of the old: the path stays relative."""
        self.change_base(mf.FindMissingMediaDialog(dbstate=self.dbstate), self.tmp)
        path = self.db.get_media_from_handle(self.h_ok).get_path()
        self.assertEqual(path.replace("\\", "/"), "MediaBase/a.jpg")

    def test_consolidate_keeps_unlisted_record(self) -> None:
        """Consolidate: a record not in the batch still finds its file."""
        dlg = mf.ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        self.change_base(dlg, self.new_base)
        path = self.db.get_media_from_handle(self.h_ok).get_path()
        resolved = gc.full_media_path(self.db, path)
        self.assertTrue(os.path.samefile(resolved, os.path.join(self.base, "a.jpg")))

    def test_locked_record_reported_not_changed(self) -> None:
        """A locked record is not rewritten, and the user is told."""
        gc.lock_media(self.db, self.db.get_media_from_handle(self.h_ok), commit=True)
        self.change_base(mf.FindMissingMediaDialog(dbstate=self.dbstate), self.new_base)
        self.assertEqual(self.db.get_media_from_handle(self.h_ok).get_path(), "a.jpg")
        self.assertIn("Locked record(s) not updated", self.last_message)

    def test_unchanged_base_touches_nothing(self) -> None:
        """No base change: other records are not rewritten."""
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        with patch(_MF_DLG):
            dlg.cb_apply(MagicMock())
        self.assertEqual(self.db.get_media_from_handle(self.h_ok).get_path(), "a.jpg")


if __name__ == "__main__":
    unittest.main()
