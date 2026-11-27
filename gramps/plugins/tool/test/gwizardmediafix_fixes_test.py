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

"""Regression tests for the GWizard Media Fix review fixes (batches 1-4).

1. Accept hints in Fix media references never suggests deleting a record that
   has notes, attributes, tags, citations or a date.
2. Find missing media never repoints two different records at one file found
   by name (they would then be merged as duplicates).
6. Consolidate media location lists only records that are not consolidated.
7. find_duplicate_media_groups survives media_path_full() raising.
8. Windows drive paths are recognised and compared on Linux and macOS.

Batch 2:

3. A shared file is moved once with all its records; the Accept-all
   preview and the real run agree.
4. Changing the base media path keeps other relative records pointing at
   their files.
9. A file attached to a shared (household) census event is named after the
   person in its description, or deterministically when none is named.

Batch 3:

- 12: failed actions are reported, not "nothing selected"; a relative path is
  never validated against the working directory.
- 13: paths and titles are escaped before going into markup.
- 14: removing import notes reports what was actually removed.

Batch 4:

- 5: every file operation is logged; "Undo last file moves" moves files back
  and repoints records, safely and one run at a time.
- 10: the base media path is resolved exactly as Gramps resolves it.
- Performance: the duplicate scan only walks permissions for unreadable files.
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
from typing import Any
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# GTK test doubles: installed before any GWizard module is imported, so the
# dialog classes subclass the fakes.
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
    Note,
    Person,
    Repository,
    Source,
    Surname,
)
from gramps.gen.types import MediaHandle
from gramps.plugins.tool import gwizard_mediafix_common as gc
from gramps.plugins.tool import gwizardmediafix as mf
from gramps.plugins.tool import gwizard_mediafix_basepath as bp
from gramps.plugins.tool.gw_fixmediareferencesdialog import (
    FixMediaReferencesDialog,
    find_duplicate_media_groups,
)

_DLG = "gramps.plugins.tool.gw_fixmediareferencesdialog.OkDialog"
_MF_DLG = "gramps.plugins.tool.gwizardmediafix.OkDialog"


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
                [
                    (MediaHandle("a"), "C:/x/p.jpg", "p.jpg"),
                    (MediaHandle("b"), "D:/y/p.jpg", "p.jpg"),
                ]
            ),
            {"a", "b"},
        )
        self.assertEqual(
            mf.ambiguous_matches(
                [
                    (MediaHandle("a"), "old/p.jpg", "p.jpg"),
                    (MediaHandle("b"), "old/p.jpg", "p.jpg"),
                ]
            ),
            set(),
        )
        self.assertEqual(
            mf.ambiguous_matches(
                [
                    (MediaHandle("a"), r"C:\X\p.jpg", "p.jpg"),
                    (MediaHandle("b"), "c:/x/P.JPG", "p.jpg"),
                ]
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
            "gramps.plugins.tool.gwizard_mediafix_common.media_path_full",
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
        ("I0003", "Barton", "Walter James"),
        ("I0001", "Barton", "Anna"),
        ("I0002", "Barton", "Clara"),
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
            self.db, self.build("Barton, Clara - 1910Census")
        )
        self.assertEqual((ctx["ref_id"], ctx["given"]), ("I0002", "Clara"))

    def test_spelling_variant_still_matches(self) -> None:
        """A close misspelling ('Barten') still picks Clara, not the first person."""
        ctx = mf.resolve_media_reference_context(
            self.db, self.build("Barten, Clara - 1910Census")
        )
        self.assertEqual(ctx["ref_id"], "I0002")

    def test_event_chain_picks_described_person(self) -> None:
        """Media on the shared event itself also uses the description."""
        ctx = mf.resolve_media_reference_context(
            self.db,
            self.build("Barton, Anna - 1910Census", via_citation=False),
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
# Fix 3: shared files move as a group
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

    def test_preview_matches_run_for_shared_and_single_files(self) -> None:
        """The preview plans one move per file, and the run makes exactly those."""
        shared = self.touch("old", "shared.jpg")
        h_a = self.add_media(shared, "Shared copy A")
        h_b = self.add_media(shared, "Shared copy B")
        single = self.touch("old", "single.jpg")
        h_single = self.add_media(single, "Single", attr=True)  # kept by step 2

        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertNotIn("held", plan)
        # step 2 merges the shared records first, so each file moves once
        self.assertEqual(len(plan["moves"]), 2)
        self.assertNotIn("Files left in place", mf.format_plan(plan))

        count, problems = self.tool._auto_consolidate_location(self.db)
        self.assertEqual((count, problems), (2, []))  # preview == run
        self.assertFalse(os.path.exists(shared))
        path_a = self.db.get_media_from_handle(h_a).get_path()
        self.assertEqual(path_a, self.db.get_media_from_handle(h_b).get_path())
        self.assertFalse(os.path.isabs(path_a))
        self.assertFalse(
            os.path.isabs(self.db.get_media_from_handle(h_single).get_path())
        )

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
# Fix media references: misspelled names in descriptions
#
# ------------------------------------------------------------
class NameMismatchFixTest(_DbTestCase):
    """Step 3 corrects a description that misspells the linked person."""

    def add_person(
        self, surname: str, given: str, media_handle: str, alt: str = ""
    ) -> str:
        """Add a person linked to a media record and return its handle."""

        def make_name(sur_text: str) -> Name:
            name = Name()
            name.set_first_name(given)
            sur = Surname()
            sur.set_surname(sur_text)
            name.add_surname(sur)
            return name

        with DbTxn("add person", self.db) as trans:
            person = Person()
            person.set_primary_name(make_name(surname))
            if alt:
                person.add_alternate_name(make_name(alt))
            ref = MediaRef()
            ref.set_reference_handle(media_handle)
            person.add_media_reference(ref)
            return self.db.add_person(person, trans)

    def name_targets(self, dlg: Any) -> list[dict[str, Any]]:
        """The dialog's name-mismatch rows."""
        return [t for t in dlg.row_targets if t["group"]["type"] == "name_mismatch"]

    def test_spelling_variant_is_corrected(self) -> None:
        """Smyth -> Smith, keeping the rest of the description."""
        h = self.add_media("anna.jpg", "Smyth, Anna - 1900Census")
        self.add_person("Smith", "Anna", h)

        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        targets = self.name_targets(dlg)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["group"]["new_desc"], "Smith, Anna - 1900Census")
        self.assertEqual(targets[0]["suggested_action"], 0)

        with patch(_DLG):
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())

        media = self.db.get_media_from_handle(h)
        self.assertEqual(media.get_description(), "Smith, Anna - 1900Census")
        self.assertEqual(mf.find_name_mismatches(self.db), [])

    def test_keep_leaves_description(self) -> None:
        """'Keep description' changes nothing."""
        h = self.add_media("anna.jpg", "Smyth, Anna - 1900Census")
        self.add_person("Smith", "Anna", h)
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        self.name_targets(dlg)[0]["action_combo"].set_active(1)
        with patch(_DLG):
            dlg.cb_apply(MagicMock())
        self.assertEqual(
            self.db.get_media_from_handle(h).get_description(),
            "Smyth, Anna - 1900Census",
        )

    def test_alternate_name_is_not_a_mismatch(self) -> None:
        """An alternate name with the description's spelling counts as a match."""
        h = self.add_media("anna.jpg", "Smyth, Anna - 1900Census")
        self.add_person("Smith", "Anna", h, alt="Smyth")
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        self.assertEqual(self.name_targets(dlg), [])
        self.assertEqual(mf.find_name_mismatches(self.db), [])

    def test_different_person_is_not_offered(self) -> None:
        """A description naming someone else stays in the report only."""
        h = self.add_media("jones.jpg", "Jones, John - 1900Census")
        self.add_person("Smith", "Anna", h)
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        self.assertEqual(self.name_targets(dlg), [])
        self.assertEqual(len(mf.find_name_mismatches(self.db)), 1)

    def test_replace_name_keeps_separator(self) -> None:
        """Only the name changes, not the separator or the rest."""
        self.assertEqual(
            mf.replace_name_in_text("Smyth, Anna_1900Census", "Smith", "Anna"),
            "Smith, Anna_1900Census",
        )
        self.assertEqual(mf.replace_name_in_text("scan", "Smith", "Anna"), "scan")


# ------------------------------------------------------------
#
# Fix media references: leftover import notes (was 'Clean import notes')
#
# ------------------------------------------------------------
class _NotedMediaTestCase(_DbTestCase):
    """Shared helper for tests that need media records with import notes."""

    def add_noted_media(
        self, path: str, readable: bool, referenced: bool = True
    ) -> tuple[str, str]:
        """A media record with an import note; returns (media, note) handles."""
        if readable:
            self.touch("MediaBase", path)
        self.db.set_mediapath(self.base)
        with DbTxn("noted media", self.db) as trans:
            note = Note()
            note.set(gc.IMPORT_NOTE_PREFIX + " (multi-media object)")
            n_h = self.db.add_note(note, trans)
            media = Media()
            media.set_path(path)
            media.set_description(path)
            media.add_note(n_h)
            m_h = self.db.add_media(media, trans)
            if referenced:  # otherwise it is also an unreferenced row
                person = Person()
                ref = MediaRef()
                ref.set_reference_handle(m_h)
                person.add_media_reference(ref)
                self.db.add_person(person, trans)
        return m_h, n_h


class ImportNoteRowsTest(_NotedMediaTestCase):
    """Step 3 lists and deletes out-of-date import notes."""

    def note_targets(self, dlg: Any) -> list[dict[str, Any]]:
        """The dialog's import-note rows."""
        return [t for t in dlg.row_targets if t["group"]["type"] == "import_notes"]

    def test_readable_file_notes_deleted(self) -> None:
        """A readable file's import note is offered and deleted on Apply."""
        m_h, n_h = self.add_noted_media("found.jpg", readable=True)
        self.add_noted_media("lost.jpg", readable=False)
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        targets = self.note_targets(dlg)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["group"]["keeper"]["handle"], m_h)
        with patch(_DLG) as ok_dialog:
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())
        self.assertEqual(self.db.get_media_from_handle(m_h).get_note_list(), [])
        with self.assertRaises(HandleError):
            self.db.get_note_from_handle(n_h)
        self.assertIn("Removed 1 leftover import notes", ok_dialog.call_args[0][1])

    def test_record_deleted_in_same_apply(self) -> None:
        """An unreferenced record deleted earlier in Apply is no error."""
        m_h, n_h = self.add_noted_media("found.jpg", readable=True, referenced=False)
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        types = sorted(t["group"]["type"] for t in dlg.row_targets)
        self.assertEqual(types, ["import_notes", "unreferenced"])
        with patch(_DLG) as ok_dialog:
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())
        message = ok_dialog.call_args[0][1]
        self.assertNotIn("not found", message)
        self.assertIn("Deleted 1 unreferenced", message)
        with self.assertRaises(HandleError):
            self.db.get_media_from_handle(m_h)
        with self.assertRaises(HandleError):
            self.db.get_note_from_handle(n_h)

    def test_record_merged_in_same_apply(self) -> None:
        """A record merged away earlier in Apply: its note leaves the keeper."""
        m_a, n_a = self.add_noted_media("shared.jpg", readable=True)
        m_b, n_b = self.add_noted_media("shared.jpg", readable=True)
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        with patch(_DLG) as ok_dialog:
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())
        self.assertNotIn("not found", ok_dialog.call_args[0][1])
        survivors = []
        for handle in (m_a, m_b):
            try:
                survivors.append(self.db.get_media_from_handle(handle))
            except HandleError:
                pass
        self.assertEqual(len(survivors), 1)
        self.assertEqual(survivors[0].get_note_list(), [])
        for note in (n_a, n_b):
            with self.assertRaises(HandleError):
                self.db.get_note_from_handle(note)

    def test_keep_notes(self) -> None:
        """'Keep notes' leaves the note."""
        m_h, n_h = self.add_noted_media("found.jpg", readable=True)
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        self.note_targets(dlg)[0]["action_combo"].set_active(1)
        with patch(_DLG):
            dlg.cb_apply(MagicMock())
        self.assertEqual(self.db.get_media_from_handle(m_h).get_note_list(), [n_h])


class AcceptAllMatchesStepThreeTest(_NotedMediaTestCase):
    """'Accept all hints' does what Fix media references does."""

    def link(self, media_handle: str, surname: str, given: str) -> None:
        """Link a named person to a media record."""
        with DbTxn("person", self.db) as trans:
            person = Person()
            name = Name()
            name.set_first_name(given)
            sur = Surname()
            sur.set_surname(surname)
            name.add_surname(sur)
            person.set_primary_name(name)
            ref = MediaRef()
            ref.set_reference_handle(media_handle)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)

    def run_accept_all(self, choose: bool = False, folder: str = "") -> str:
        """Run Accept all hints, confirming the preview; return the summary.

        :param choose: The answer to the no-base-path prompt.
        :param folder: The folder picked in its chooser ("" = Cancel).
        """
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        tool.window = MagicMock()
        question = MagicMock()
        question.return_value.run.return_value = choose
        chooser = MagicMock()
        chooser.run.return_value = (
            mf.Gtk.ResponseType.OK if folder else mf.Gtk.ResponseType.CANCEL
        )
        chooser.get_filename.return_value = folder or None
        with (
            patch.object(mf, "confirm_plan", return_value=True) as confirm,
            patch.object(mf, "AcceptAllHintsReportDialog") as report,
            patch.object(bp, "QuestionDialog2", question),
            patch.object(bp.Gtk, "FileChooserDialog", return_value=chooser),
            patch.object(mf, "OkDialog"),
            patch.object(bp, "OkDialog"),
        ):
            tool.cb_auto_all()
        self.asked = question.called
        self.preview = confirm.call_args[0][1]
        return report.call_args[1]["report_text"]

    def test_names_and_notes_fixed(self) -> None:
        """Misspelled names are corrected and leftover import notes deleted."""
        self.touch("MediaBase", "anna.jpg")
        self.db.set_mediapath(self.base)
        h_name = self.add_media("anna.jpg", "Smyth, Anna - 1900Census")
        self.link(h_name, "Smith", "Anna")
        m_h, n_h = self.add_noted_media("found.jpg", readable=True)
        m_a, n_a = self.add_noted_media("shared.jpg", readable=True)
        m_b, n_b = self.add_noted_media("shared.jpg", readable=True)

        summary = self.run_accept_all()

        self.assertIn("use the linked person's name (1)", self.preview)
        self.assertIn("delete leftover import notes (2 records)", self.preview)
        self.assertIn("names corrected: 1; leftover import notes deleted: 3", summary)
        self.assertEqual(
            self.db.get_media_from_handle(h_name).get_description(),
            "Smith, Anna - 1900Census",
        )
        for note in (n_h, n_a, n_b):
            with self.assertRaises(HandleError):
                self.db.get_note_from_handle(note)
        self.assertNotIn("OPTIONAL CLEANUP", summary)

    def test_uses_each_steps_own_code(self) -> None:
        """Every fix goes through the function its step's dialog uses."""
        self.db.set_mediapath(self.base)
        # Find missing media: lost here, found in the base folder by name
        self.touch("MediaBase", "scans", "lost.jpg")
        h_lost = self.add_media("Old/lost.jpg", "Lost")
        self.link(h_lost, "Jones", "Mary")
        # Fix media references: a duplicate pair and an empty orphan
        shared = self.touch("Elsewhere", "shared.jpg")
        h_a = self.add_media(shared, "Shared")
        self.link(h_a, "Jones", "Paul")
        self.add_media(shared, "Shared")
        self.add_media("orphan.jpg", "Orphan")
        # Fix media references: a misspelled name
        self.touch("MediaBase", "anna.jpg")
        h_name = self.add_media("anna.jpg", "Smyth, Anna - 1900Census")
        self.link(h_name, "Smith", "Anna")

        shared_fixes = (
            "repoint_media",
            "merge_into_keeper",
            "delete_unreferenced",
            "apply_name_fix",
            "relocate_media_records",
        )
        spies = {
            name: patch.object(mf, name, wraps=getattr(mf, name))
            for name in shared_fixes
        }
        mocks = {name: spy.start() for name, spy in spies.items()}
        try:
            self.run_accept_all()
        finally:
            for spy in spies.values():
                spy.stop()
        for name, mock in mocks.items():
            self.assertTrue(mock.called, "%s was not used" % name)

    def test_skipped_consolidation_is_not_fully_resolved(self) -> None:
        """Without a base path the summary asks for one instead of 'resolved'."""
        self.db.set_mediapath(None)
        shared = self.touch("Elsewhere", "shared.jpg")
        h_a = self.add_media(shared, "Shared")
        self.link(h_a, "Jones", "Paul")
        self.add_media(shared, "Shared")
        summary = self.run_accept_all()
        self.assertIn("Consolidate media location was skipped", summary)
        self.assertIn("CHANGES REQUIRING HUMAN INTERVENTION", summary)
        self.assertNotIn("fully resolved", summary)

    def far_record(self) -> str:
        """A referenced record whose file is outside the media folder."""
        handle = self.add_media(self.touch("Elsewhere", "far.jpg"), "Far")
        self.link(handle, "Jones", "Mary")
        return handle

    def test_prompt_sets_base_path_and_consolidates(self) -> None:
        """No base path: choosing a folder saves it and consolidation runs."""
        self.db.set_mediapath(None)
        handle = self.far_record()
        summary = self.run_accept_all(choose=True, folder=self.base)
        self.assertTrue(self.asked)
        self.assertEqual(self.db.get_mediapath(), self.base)
        path = self.db.get_media_from_handle(handle).get_path()
        self.assertFalse(os.path.isabs(path))
        self.assertTrue(os.path.exists(os.path.join(self.base, path)))
        self.assertNotIn("Consolidate media location was skipped", summary)

    def test_prompt_declined_skips_consolidation(self) -> None:
        """Continuing without a base path runs the rest and skips consolidation."""
        self.db.set_mediapath(None)
        handle = self.far_record()
        summary = self.run_accept_all(choose=False)
        self.assertTrue(self.asked)
        self.assertFalse((self.db.get_mediapath() or "").strip())
        self.assertTrue(os.path.isabs(self.db.get_media_from_handle(handle).get_path()))
        self.assertIn("Consolidate media location was skipped", summary)

    def test_chooser_cancelled_skips_consolidation(self) -> None:
        """Cancelling the folder chooser is the same as continuing without."""
        self.db.set_mediapath(None)
        self.far_record()
        summary = self.run_accept_all(choose=True, folder="")
        self.assertFalse((self.db.get_mediapath() or "").strip())
        self.assertIn("Consolidate media location was skipped", summary)

    def test_no_prompt_when_base_path_set(self) -> None:
        """With a base path already set nothing is asked."""
        self.db.set_mediapath(self.base)
        self.far_record()
        self.run_accept_all()
        self.assertFalse(self.asked)

    def test_unreadable_file_notes_kept(self) -> None:
        """A file that still cannot be found keeps its import note."""
        self.db.set_mediapath(self.base)
        m_h, n_h = self.add_noted_media("lost.jpg", readable=False)
        plan = mf.build_accept_all_plan(self.db, self.base, True)
        self.assertEqual(plan["notes"], [])
        self.assertIsNotNone(self.db.get_note_from_handle(n_h))


# ------------------------------------------------------------
#
# Consolidate reuses an identical file already at the standard name
#
# ------------------------------------------------------------
class IdenticalDestinationTest(_DbTestCase):
    """No _2, _3 ... copies when the same file is already in the media folder."""

    def setUp(self) -> None:
        super().setUp()
        gc._CHECKSUM_CACHE.clear()
        self.db.set_mediapath(self.base)
        self.src = os.path.join(self.tmp, "images", "scan.jpg")
        os.makedirs(os.path.dirname(self.src))
        with open(self.src, "w", encoding="utf-8") as handle:
            handle.write("census scan")
        self.handle = self.add_media(self.src, "Scan")
        with DbTxn("person", self.db) as trans:
            person = Person()
            ref = MediaRef()
            ref.set_reference_handle(self.handle)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)
        dlg = mf.ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        self.standard = os.path.basename(dlg.rows[0]["suggested_path"])

    def put_in_base(self, text: str) -> str:
        """Put a file with the standard name in the media folder."""
        path = os.path.join(self.base, self.standard)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def consolidate(self) -> str:
        """Accept the hints and apply; return the result message."""
        dlg = mf.ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        with patch(_MF_DLG) as ok_dialog:
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())
        return ok_dialog.call_args[0][1]

    def path(self) -> str:
        """The record's stored path."""
        return self.db.get_media_from_handle(self.handle).get_path()

    def test_identical_file_reused(self) -> None:
        """The record uses the file already there; the original stays put."""
        self.put_in_base("census scan")
        message = self.consolidate()
        self.assertEqual(self.path(), self.standard)
        self.assertTrue(os.path.exists(self.src))
        self.assertFalse(any("_2" in n for n in os.listdir(self.base)))
        self.assertIn("already in the media folder with the same content", message)

    def test_different_file_renamed_and_reported(self) -> None:
        """A different file with the standard name: _2, and it is reported."""
        self.put_in_base("some other scan")
        message = self.consolidate()
        self.assertTrue(self.path().endswith("_2.jpg"))
        self.assertFalse(os.path.exists(self.src))  # moved as usual
        self.assertIn("Renamed because a different file", message)

    def test_undo_after_reuse(self) -> None:
        """Undo points the record back at the original, which was left in place."""
        dest = self.put_in_base("census scan")
        self.consolidate()
        log = os.path.join(self.base, gc.MOVE_LOG_NAME)
        gc.undo_logged_run(self.db, log)
        self.assertEqual(os.path.normcase(self.path()), os.path.normcase(self.src))
        self.assertTrue(os.path.exists(self.src))
        self.assertTrue(os.path.exists(dest))

    def run_accept_all(self) -> str:
        """Run Accept all hints; return the summary."""
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        tool.window = MagicMock()
        with (
            patch.object(mf, "confirm_plan", return_value=True) as confirm,
            patch.object(mf, "AcceptAllHintsReportDialog") as report,
        ):
            tool.cb_auto_all()
        self.preview = confirm.call_args[0][1]
        return report.call_args[1]["report_text"]

    def test_accept_all_reuses_identical_file(self) -> None:
        """Accept all hints: no _2 copy, and still fully resolved."""
        self.put_in_base("census scan")
        summary = self.run_accept_all()
        self.assertIn("(already there with the same content)", self.preview)
        self.assertEqual(self.path(), self.standard)
        self.assertIn("already there with the same content", summary)
        self.assertIn("0 files moved or renamed", summary)
        self.assertIn("fully resolved", summary)

    def test_accept_all_reports_real_clash(self) -> None:
        """Accept all hints: a clash with a different file needs attention."""
        self.put_in_base("some other scan")
        summary = self.run_accept_all()
        self.assertIn("(renamed: name taken by another file)", self.preview)
        self.assertTrue(self.path().endswith("_2.jpg"))
        self.assertIn("Renamed because a different file", summary)
        self.assertNotIn("fully resolved", summary)


# ------------------------------------------------------------
#
# Checksums stored automatically (was 'Store checksums')
#
# ------------------------------------------------------------
class AutoChecksumTest(_DbTestCase):
    """Each step's Apply fills in missing checksums, and only missing ones."""

    def setUp(self) -> None:
        super().setUp()
        gc._CHECKSUM_CACHE.clear()
        self.db.set_mediapath(self.base)
        self.touch("MediaBase", "plain.jpg")
        self.h_plain = self.add_media("plain.jpg", "No checksum yet")
        self.touch("MediaBase", "kept.jpg")
        self.h_kept = self.add_media("kept.jpg", "Old checksum")
        media = self.db.get_media_from_handle(self.h_kept)
        media.set_checksum("0" * 32)  # no longer matches: must be kept
        with DbTxn("set", self.db) as trans:
            self.db.commit_media(media, trans)
            # Referenced, so Step 3 does not offer to delete them.
            person = Person()
            for handle in (self.h_plain, self.h_kept):
                ref = MediaRef()
                ref.set_reference_handle(handle)
                person.add_media_reference(ref)
            self.db.add_person(person, trans)

    def checksum(self, handle: str) -> str:
        """A record's stored checksum."""
        return self.db.get_media_from_handle(handle).get_checksum()

    def assert_filled(self, message: str) -> None:
        """The plain record got one, the changed one kept its old checksum."""
        self.assertTrue(self.checksum(self.h_plain))
        self.assertEqual(self.checksum(self.h_kept), "0" * 32)
        self.assertIn("that had none", message)

    def test_fix_references_apply(self) -> None:
        """Step 3."""
        self.add_media("orphan.jpg", "Bare orphan")
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        with patch(_DLG) as ok_dialog:
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())
        self.assert_filled(ok_dialog.call_args[0][1])

    def test_consolidate_apply(self) -> None:
        """Step 4."""
        outside = self.touch("elsewhere", "far.jpg")
        h_far = self.add_media(outside, "Far away")
        dlg = mf.ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        # Move only the far record, so the others get their checksum from the
        # automatic pass, not from being moved.
        for row, target in zip(dlg.rows, dlg.row_targets):
            if h_far in (
                target["entry"].get("handles") or [target["entry"].get("handle")]
            ):
                target["path_entry"].set_text(row["suggested_path"])
        with patch(_MF_DLG) as ok_dialog:
            dlg.cb_apply(MagicMock())
        self.assert_filled(ok_dialog.call_args[0][1])

    def test_find_missing_apply(self) -> None:
        """Step 2."""
        found = self.touch("MediaBase", "scans", "lost.jpg")
        h_lost = self.add_media("old/lost.jpg", "Lost")
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        target = next(t for t in dlg.row_targets if t["entry"].get("handle") == h_lost)
        target["path_entry"].set_text(found)
        with patch(_MF_DLG) as ok_dialog:
            dlg.cb_apply(MagicMock())
        self.assert_filled(ok_dialog.call_args[0][1])

    def test_nothing_to_apply_changes_nothing(self) -> None:
        """No checksums are written when Apply had nothing to do."""
        dlg = mf.ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        with patch(_MF_DLG):
            dlg.cb_apply(MagicMock())
        self.assertFalse(self.checksum(self.h_plain))


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

    def change_base(self, dlg: Any, new_base: str) -> None:
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
        self.assertIn("still points at its file", self.last_message)

    def test_new_base_containing_old_keeps_relative_path(self) -> None:
        """New base is a parent of the old: the path stays relative."""
        self.change_base(mf.FindMissingMediaDialog(dbstate=self.dbstate), self.tmp)
        path = self.db.get_media_from_handle(self.h_ok).get_path()
        self.assertEqual(path.replace("\\", "/"), "MediaBase/a.jpg")

    def test_find_missing_folder_pick_saves_and_keeps_records(self) -> None:
        """Picking a folder saves the base path at once and keeps records valid."""
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        chooser = MagicMock()
        chooser.run.return_value = mf.Gtk.ResponseType.OK
        chooser.get_filename.return_value = self.new_base
        with patch.object(mf.Gtk, "FileChooserDialog", return_value=chooser):
            with patch(_MF_DLG) as ok_dialog:
                dlg.cb_select_mediapath()
        self.assertEqual(self.db.get_mediapath(), self.new_base)
        path = self.db.get_media_from_handle(self.h_ok).get_path()
        self.assertTrue(os.path.samefile(path, os.path.join(self.base, "a.jpg")))
        self.assertIn("still points at its file", ok_dialog.call_args[0][1])
        # Apply afterwards does not count the base change a second time.
        with patch(_MF_DLG):
            dlg.cb_apply(MagicMock())
        self.assertEqual(self.db.get_mediapath(), self.new_base)

    def test_unchanged_base_touches_nothing(self) -> None:
        """No base change: other records are not rewritten."""
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        with patch(_MF_DLG):
            dlg.cb_apply(MagicMock())
        self.assertEqual(self.db.get_media_from_handle(self.h_ok).get_path(), "a.jpg")


# ------------------------------------------------------------
#
# Batch 3: generic tags shared with Citation Fix
#
# ------------------------------------------------------------
class GenericTagTest(_DbTestCase):
    """The tag helpers work on every tagged object type."""

    def add(self, obj: object) -> object:
        """Add *obj* with the matching add_<type> method and return it."""
        with DbTxn("add", self.db) as trans:
            getattr(self.db, "add_%s" % type(obj).__name__.lower())(obj, trans)
        return obj

    def test_checking_a_tag_creates_no_tags(self) -> None:
        """has_tag on a tree without GWizard tags leaves it untouched."""
        cit = self.add(Citation())
        self.assertFalse(gc.has_tag(self.db, cit, gc.TAG_MEDIA_FIXED))
        self.assertFalse(gc.has_tag(self.db, None, gc.TAG_MEDIA_FIXED))
        self.assertEqual(self.db.get_number_of_tags(), 0)

    def test_fixed_tag_on_non_media_objects(self) -> None:
        """Citation, Source, Repository and Note can carry the fixed tag."""
        for obj in (Citation(), Source(), Repository(), Note()):
            with self.subTest(kind=type(obj).__name__):
                self.add(obj)
                self.assertTrue(gc.add_fixed_tag(self.db, obj, commit=True))
                self.assertFalse(gc.add_fixed_tag(self.db, obj, commit=True))
                getter = getattr(
                    self.db, "get_%s_from_handle" % type(obj).__name__.lower()
                )
                stored = getter(obj.get_handle())
                self.assertTrue(gc.has_tag(self.db, stored, gc.TAG_MEDIA_FIXED))

    def test_custom_fixed_tag_for_another_tool(self) -> None:
        """add_fixed_tag accepts a tool-specific tag name."""
        cit = self.add(Citation())
        self.assertTrue(
            gc.add_fixed_tag(
                self.db, cit, "GWizard: CitationFixed", "#123456", commit=True
            )
        )
        self.assertTrue(gc.has_tag(self.db, cit, "GWizard: CitationFixed"))
        self.assertFalse(gc.has_tag(self.db, cit, gc.TAG_MEDIA_FIXED))

    def test_ensure_tag_commits_once(self) -> None:
        """Creating a tag commits it once (add_tag already commits)."""
        with patch.object(
            self.db, "commit_tag", wraps=self.db.commit_tag
        ) as commit_tag:
            self.assertIsNotNone(gc.ensure_tag(self.db, "GWizard: Test"))
        self.assertEqual(commit_tag.call_count, 1)

    def test_commit_object_rejects_unknown_type(self) -> None:
        """commit_object raises TypeError for an object it cannot commit."""
        with DbTxn("x", self.db) as trans:
            with self.assertRaises(TypeError):
                gc.commit_object(self.db, object(), trans)


# ------------------------------------------------------------
#
# Batch 3: small correctness fixes
#
# ------------------------------------------------------------
class SmallFixesTest(_DbTestCase):
    """Fixes 12, 13 and 14."""

    def test_failed_actions_are_reported(self) -> None:
        """12: a failed merge is reported, not "nothing selected"."""
        self.add_media("shared/a.jpg", "One")
        self.add_media("shared/a.jpg", "Two")
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        with (
            patch(
                "gramps.plugins.tool.gw_fixmediareferencesdialog.MergeMediaQuery",
                side_effect=RuntimeError("merge refused"),
            ),
            patch(_DLG) as ok_dialog,
        ):
            dlg.cb_apply(MagicMock())
        title, body = ok_dialog.call_args[0][:2]
        self.assertEqual(title, "Nothing was changed")
        self.assertIn("merge refused", body)

    def test_relative_path_not_checked_against_cwd(self) -> None:
        """12: a relative path that exists only in the working directory is refused."""
        self.db.set_mediapath(self.base)
        h_missing = self.add_media("lost/photo.jpg", "Missing")
        cwd_dir = os.path.join(self.tmp, "cwd")
        os.makedirs(cwd_dir)
        with open(os.path.join(cwd_dir, "only_here.jpg"), "w", encoding="utf-8") as f:
            f.write("x")
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        entry = MagicMock()
        entry.get_text.return_value = "only_here.jpg"
        dlg.row_targets = [{"entry": dlg.rows[0], "path_entry": entry}]
        old_cwd = os.getcwd()
        os.chdir(cwd_dir)
        try:
            with patch(_MF_DLG):
                dlg.cb_apply(MagicMock())
        finally:
            os.chdir(old_cwd)
        self.assertEqual(
            self.db.get_media_from_handle(h_missing).get_path(), "lost/photo.jpg"
        )

    def test_markup_is_escaped(self) -> None:
        """13: '&' and '<' in a base path or header do not break markup."""
        self.assertEqual(
            gc.escape_markup("Smith & Jones <1>"), "Smith &amp; Jones &lt;1&gt;"
        )
        self.assertEqual(gc.HeaderLabel("A & B").markup, "<b>A &amp; B</b>")
        base = os.path.join(self.tmp, "Smith & Jones")
        os.makedirs(base)
        self.db.set_mediapath(base)
        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        self.assertIn("Smith &amp; Jones", dlg.base_path_label.markup)
        self.assertNotIn("Smith & Jones", dlg.base_path_label.markup)

    def test_import_note_count_includes_shared_note(self) -> None:
        """14: a note detached from media but still used elsewhere is counted."""
        with DbTxn("notes", self.db) as trans:
            note = Note()
            note.set("Records not imported into OBJE (multi-media object)")
            n_h = self.db.add_note(note, trans)
            media = Media()
            media.set_path("x.jpg")
            media.add_note(n_h)
            m_h = self.db.add_media(media, trans)
            person = Person()
            person.add_note(n_h)
            self.db.add_person(person, trans)
        items = [(m_h, media.get_gramps_id(), n_h, note.get_gramps_id())]
        self.assertEqual(mf.remove_import_notes(self.db, items), 1)
        self.assertEqual(self.db.get_media_from_handle(m_h).get_note_list(), [])
        self.assertIsNotNone(self.db.get_note_from_handle(n_h))  # still used


# ------------------------------------------------------------
#
# Batch 4, fix 10: base path resolved as Gramps does
#
# ------------------------------------------------------------
class BasePathResolutionTest(_DbTestCase):
    """The tool's base folder is the folder Gramps opens relative paths from."""

    def test_settings_match_gramps(self) -> None:
        """'~', '{VAR}', relative and absolute settings agree with media_path()."""
        from gramps.gen.utils.file import media_path

        for setting in ("~/Media", "{GRAMPSHOME}/Media", "rel", self.base):
            with self.subTest(setting=setting):
                self.db.set_mediapath(setting)
                self.assertEqual(
                    gc.path_key(mf.get_media_base_path(self.db)),
                    gc.path_key(media_path(self.db)),
                )

    def test_dialog_entry_uses_same_rules(self) -> None:
        """Typing a base path in a dialog resolves like the saved setting."""
        from gramps.gen.const import USER_PICTURES

        dlg = mf.FindMissingMediaDialog(dbstate=self.dbstate)
        dlg.path_entry.set_text("")
        dlg.cb_set_mediapath()
        self.assertEqual(dlg.base_dir, os.path.normpath(os.path.abspath(USER_PICTURES)))
        dlg.path_entry.set_text(self.base)
        dlg.cb_set_mediapath()
        self.assertEqual(dlg.base_dir, os.path.normpath(os.path.abspath(self.base)))


# ------------------------------------------------------------
#
# Batch 4, fix 5: file-move log and undo
#
# ------------------------------------------------------------
class MoveLogUndoTest(_DbTestCase):
    """Logged runs can be reversed: files back, records repointed."""

    def setUp(self) -> None:
        super().setUp()
        self.db.set_mediapath(self.base)
        self.log = os.path.join(self.base, gc.MOVE_LOG_NAME)

    def consolidate(self, *paths: str) -> list[str]:
        """Add one record per path and run automatic consolidation."""
        handles = [self.add_media(p, "Photo %d" % i) for i, p in enumerate(paths)]
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        count, _problems = tool._auto_consolidate_location(self.db)
        self.assertEqual(count, len(paths))
        self.assertIn(gc.MOVE_LOG_NAME, tool.last_move_log_note)
        return handles

    def test_undo_moves_files_back_and_repoints(self) -> None:
        """One run is reversed completely, then there is nothing left to undo."""
        src = self.touch("old", "a.jpg")
        (handle,) = self.consolidate(src)
        moved = self.db.get_media_from_handle(handle).get_path()
        self.assertFalse(os.path.exists(src))

        files, records, problems = gc.undo_logged_run(self.db, self.log)
        self.assertEqual((files, records, problems), (1, 1, []))
        self.assertTrue(os.path.exists(src))
        self.assertFalse(os.path.exists(os.path.join(self.base, moved)))
        self.assertEqual(self.db.get_media_from_handle(handle).get_path(), src)
        self.assertEqual(gc.undo_logged_run(self.db, self.log), (0, 0, []))

    def test_undo_goes_back_one_run_at_a_time(self) -> None:
        """Two runs: the first undo reverses the second run only."""
        (h1,) = self.consolidate(self.touch("old", "one.jpg"))
        (h2,) = self.consolidate(self.touch("old", "two.jpg"))
        gc.undo_logged_run(self.db, self.log)
        self.assertTrue(os.path.isabs(self.db.get_media_from_handle(h2).get_path()))
        self.assertFalse(os.path.isabs(self.db.get_media_from_handle(h1).get_path()))
        gc.undo_logged_run(self.db, self.log)
        self.assertTrue(os.path.isabs(self.db.get_media_from_handle(h1).get_path()))

    def test_undo_after_edit_undo_still_moves_file(self) -> None:
        """If Edit > Undo already restored the path, the file is still moved back."""
        src = self.touch("old", "a.jpg")
        (handle,) = self.consolidate(src)
        media = self.db.get_media_from_handle(handle)
        with DbTxn("simulate Edit > Undo", self.db) as trans:
            media.set_path(src)
            self.db.commit_media(media, trans)
        files, records, problems = gc.undo_logged_run(self.db, self.log)
        self.assertEqual((files, records, problems), (1, 0, []))
        self.assertTrue(os.path.exists(src))

    def test_changed_records_are_left_alone(self) -> None:
        """A record repointed since the run is reported, not touched."""
        src_b = self.touch("old", "b.jpg")
        h_changed, h_other = self.consolidate(self.touch("old", "a.jpg"), src_b)
        changed = self.db.get_media_from_handle(h_changed)
        with DbTxn("user edit", self.db) as trans:
            changed.set_path("somewhere/else.jpg")
            self.db.commit_media(changed, trans)
        _files, records, problems = gc.undo_logged_run(self.db, self.log)
        self.assertEqual(records, 1)
        self.assertEqual(len(problems), 1)
        self.assertEqual(
            self.db.get_media_from_handle(h_changed).get_path(), "somewhere/else.jpg"
        )
        self.assertEqual(self.db.get_media_from_handle(h_other).get_path(), src_b)
        self.assertTrue(os.path.exists(src_b))

    def test_never_overwrites_old_location(self) -> None:
        """If something now occupies the old location, the file stays put."""
        src = self.touch("old", "a.jpg")
        (handle,) = self.consolidate(src)
        with open(src, "w", encoding="utf-8") as f:
            f.write("a different file")
        _files, _records, problems = gc.undo_logged_run(self.db, self.log)
        self.assertTrue(problems)
        with open(src, encoding="utf-8") as f:
            self.assertEqual(f.read(), "a different file")
        moved = self.db.get_media_from_handle(handle).get_path()
        self.assertTrue(os.path.exists(gc.full_media_path(self.db, moved)))

    def test_copy_is_kept_on_undo(self) -> None:
        """Undoing a copy repoints the record but never deletes the copy."""
        src = self.touch("old", "c.jpg")
        handle = self.add_media(src, "Copy me")
        dlg = mf.ConsolidateMediaLocationDialog(dbstate=self.dbstate)
        dlg.radio_copy.set_active(True)
        with patch(_MF_DLG) as ok_dialog:
            dlg.cb_accept_hints(MagicMock())
            dlg.cb_apply(MagicMock())
        self.assertIn("Undo last file moves", ok_dialog.call_args[0][1])
        copy_path = gc.full_media_path(
            self.db, self.db.get_media_from_handle(handle).get_path()
        )
        gc.undo_logged_run(self.db, self.log)
        self.assertEqual(self.db.get_media_from_handle(handle).get_path(), src)
        self.assertTrue(os.path.exists(copy_path))
        self.assertTrue(os.path.exists(src))

    def test_unwritable_log_is_reported(self) -> None:
        """If the log cannot be written the user is warned."""
        os.makedirs(self.log)  # a folder where the log file should be
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        self.add_media(self.touch("old", "a.jpg"), "A")
        tool._auto_consolidate_location(self.db)
        self.assertIn("could not be written", tool.last_move_log_note)

    def test_split_copies_are_logged(self) -> None:
        """Fix media references 'Create separate file copies' is logged."""
        shared = self.touch("old", "shared.jpg")
        self.add_media(shared, "One")
        h2 = self.add_media(shared, "Two")
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        combo = MagicMock()
        combo.get_active.return_value = 1
        dlg.row_targets = [{"group": dlg.groups[0], "action_combo": combo}]
        with patch(_DLG):
            dlg.cb_apply(MagicMock())
        run = gc.last_logged_run(gc.read_move_log(self.log))
        self.assertEqual([r["action"] for r in run], ["copy"])
        gc.undo_logged_run(self.db, self.log)
        self.assertEqual(self.db.get_media_from_handle(h2).get_path(), shared)

    def test_main_window_undo_button(self) -> None:
        """The main window button confirms, undoes and reports."""
        src = self.touch("old", "a.jpg")
        self.consolidate(src)
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        tool.window = MagicMock()
        question = MagicMock()
        question.return_value.run.return_value = True
        with (
            patch("gramps.plugins.tool.gwizardmediafix.QuestionDialog2", question),
            patch(_MF_DLG) as ok_dialog,
        ):
            tool.cb_button(MagicMock(), "undo_moves")
        question.assert_called_once()
        self.assertIn("Files moved back: 1", ok_dialog.call_args[0][1])
        self.assertTrue(os.path.exists(src))


# ------------------------------------------------------------
#
# Batch 4: performance
#
# ------------------------------------------------------------
class DuplicateScanPerformanceTest(_DbTestCase):
    """The permission walk runs only for files that cannot be read."""

    def test_permission_walk_only_for_missing_files(self) -> None:
        """Existing files are not walked; missing ones are."""
        present = self.touch("old", "here.jpg")
        self.add_media(present, "Present")
        self.add_media(os.path.join(self.tmp, "gone.jpg"), "Missing")
        with patch(
            "gramps.plugins.tool.gwizardmediafix.check_path_permission",
            return_value=(False, None),
        ) as walk:
            find_duplicate_media_groups(self.db)
        walked = [c.args[0] for c in walk.call_args_list]
        self.assertNotIn(present, walked)
        self.assertIn(os.path.join(self.tmp, "gone.jpg"), walked)


# Test discovery imports every test module before running any, so take the
# fakes off Gtk again now that the GWizard modules are imported; other Gramps
# tests need the real widgets.  setUpModule puts them back for this module.
# ------------------------------------------------------------
#
# Accept all hints: the main window stays open, the preview is clear
#
# ------------------------------------------------------------
class AcceptAllWindowTest(_DbTestCase):
    """Accept all hints neither closes the tool nor shows unexplained steps."""

    def tool(self) -> mf.GWizardMediaFix:
        """Return the tool without building its window."""
        tool = mf.GWizardMediaFix.__new__(mf.GWizardMediaFix)
        tool.dbstate = self.dbstate
        return tool

    def test_accept_all_response_keeps_tool_open(self) -> None:
        """The response GTK emits for 'Accept all hints' does not close the tool."""
        tool = self.tool()
        with patch.object(mf.GWizardMediaFix, "close") as close:
            tool.cb_close(MagicMock(), Gtk.ResponseType.NONE)
        close.assert_not_called()

    def test_close_and_window_x_close_tool(self) -> None:
        """Close, the window's X and Escape still close the tool."""
        for response in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
            tool = self.tool()
            with patch.object(mf.GWizardMediaFix, "close") as close:
                tool.cb_close(MagicMock(), response)
            close.assert_called_once_with()

    def test_no_base_path_explained_without_step_numbers(self) -> None:
        """Without a base path the preview says why and how to fix it."""
        self.add_media(self.touch("Elsewhere", "a.jpg"))
        plan = mf.build_accept_all_plan(self.db, self.base, False)
        text = mf.format_plan(plan)
        self.assertIn("Consolidate media location: SKIPPED.", text)
        self.assertIn("No base media path is set", text)
        self.assertIn("Edit > Preferences > Family Tree > Base media path", text)
        self.assertNotRegex(text, r"(?m)^\d\. ")  # no bare step numbers
        self.assertNotIn("Notes:", text)  # nothing will be moved

    def test_moves_keep_the_undo_note(self) -> None:
        """When files will move, the preview still explains how to undo it."""
        self.db.set_mediapath(self.base)
        handle = self.add_media(self.touch("Elsewhere", "a.jpg"))
        with DbTxn("add person", self.db) as trans:
            person = Person()
            ref = MediaRef()
            ref.set_reference_handle(handle)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)
        plan = mf.build_accept_all_plan(self.db, self.base, True)
        text = mf.format_plan(plan)
        self.assertIn("Consolidate media location: move/rename files into", text)
        self.assertIn("Undo last file moves", text)

    def test_run_without_base_path_reports_no_fake_row(self) -> None:
        """The run does not list a fake 'unconsolidated path' row."""
        self.add_media(self.touch("Elsewhere", "a.jpg"))
        moved, unconsolidated = self.tool()._auto_consolidate_location(self.db)
        self.assertEqual((moved, unconsolidated), (0, []))


fakes.uninstall()


if __name__ == "__main__":
    unittest.main()
