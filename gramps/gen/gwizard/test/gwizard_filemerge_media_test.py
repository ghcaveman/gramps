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
Tests for how incoming media files are found, recorded and reused.

Each test gets three folders: the incoming file's folder, the family
tree's base media path, and a folder elsewhere. The pictures are small
files written by the test, so no test data is needed.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import hashlib
import os
import shutil
import tempfile
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import import_as_dict
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.gwizard.gwizard_filemerge_media import (
    base_path_configured,
    find_file,
    is_url,
    media_handles_of,
    media_note,
    target_path,
)
from gramps.gen.lib import (
    Citation,
    Event,
    EventRef,
    EventType,
    Media,
    MediaRef,
    Note,
    Source,
    Tag,
)
from gramps.gen.user import User

HEADER = "0 HEAD\n1 CHAR UTF-8\n"

PERSON_GED = HEADER + """0 @I1@ INDI
1 NAME Kid /Doe/
1 SEX M
0 TRLR
"""


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class GWizardMediaTest(unittest.TestCase):
    """Incoming media keeps pointing at the right file in the family tree."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="gwizard_media_")
        self.incoming = os.path.join(self.root, "incoming")
        self.base = os.path.join(self.root, "base")
        self.elsewhere = os.path.join(self.root, "elsewhere")
        for folder in (self.incoming, self.base, self.elsewhere):
            os.makedirs(folder)
        self.db: Any = None
        self.gwizard: GedGWizard

    def tearDown(self) -> None:
        gwizard = getattr(self, "gwizard", None)
        if gwizard is not None:
            source_db = gwizard.context.get("source_db")
            if source_db is not None:
                source_db.close()
        if self.db is not None:
            self.db.close()
        shutil.rmtree(self.root, ignore_errors=True)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _file(self, folder: str, name: str, data: bytes = b"picture") -> str:
        path = os.path.join(folder, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def _open(self, base_path: bool = True) -> None:
        tree_ged = self._file(self.elsewhere, "tree.ged", PERSON_GED.encode())
        self.db = import_as_dict(tree_ged, User())
        if base_path:
            self.db.set_mediapath(self.base)
        incoming_ged = self._file(self.incoming, "incoming.ged", PERSON_GED.encode())
        self.gwizard = GedGWizard(self.db)
        self.assertTrue(self.gwizard.run_step("connect", gedcom_path=incoming_ged))
        self.gwizard.run_step("load")

    @property
    def source_db(self) -> Any:
        return self.gwizard.context["source_db"]

    def _kid(self, db: Any) -> Any:
        (person,) = list(db.iter_people())
        return person

    def _media(self, db: Any, path: str, checksum: str = "") -> Media:
        media = Media()
        media.set_path(path)
        media.set_description("Portrait")
        media.set_mime_type("image/png")
        if checksum:
            media.set_checksum(checksum)
        with DbTxn("media", db) as trans:
            db.add_media(media, trans)
        return media

    def _give_kid(self, db: Any, media: Media) -> None:
        kid = self._kid(db)
        mref = MediaRef()
        mref.set_reference_handle(media.handle)
        kid.add_media_reference(mref)
        with DbTxn("ref", db) as trans:
            db.commit_person(kid, trans)

    def _add_as_new(self) -> Any:
        """Add the incoming Kid as a new person; return the new person."""
        before = {p.handle for p in self.db.iter_people()}
        self.gwizard.run_step(
            "apply",
            source_person_handle=self._kid(self.source_db).handle,
            target_person_handle=None,
            resolutions={},
        )
        (new,) = [p for p in self.db.iter_people() if p.handle not in before]
        return new

    def _merge_media(self, index: int = 0) -> Any:
        """Merge the incoming Kid's picture ``index`` into the tree's Kid."""
        self.gwizard.run_step(
            "apply",
            source_person_handle=self._kid(self.source_db).handle,
            target_person_handle=self._kid(self.db).handle,
            resolutions={"media:%d" % index: "source"},
        )
        return self._kid(self.db)

    def _media_rows(self) -> list[Any]:
        rows = self.gwizard.run_step(
            "compare",
            source_person_handle=self._kid(self.source_db).handle,
            target_person_handle=self._kid(self.db).handle,
        )
        return [r for r in rows if r.field_type == "media"]

    def _paths_of(self, person: Any) -> list[str]:
        return [
            self.db.get_media_from_handle(ref.ref).get_path()
            for ref in person.get_media_list()
        ]

    # ------------------------------------------------------------------
    # Bug 1: a relative path keeps meaning the same file
    # ------------------------------------------------------------------
    def test_relative_path_next_to_incoming_file_is_recorded_in_full(self) -> None:
        """A picture beside the incoming file is recorded with its full path."""
        self._open()
        picture = self._file(self.incoming, "photos/kid.png")
        self._give_kid(self.source_db, self._media(self.source_db, "photos/kid.png"))

        new = self._add_as_new()

        self.assertEqual(self._paths_of(new), [os.path.normpath(picture)])

    def test_file_under_the_base_path_is_recorded_relative_to_it(self) -> None:
        """A picture under the tree's base media path is recorded relative to it."""
        self._open()
        picture = self._file(self.base, "scans/kid.png")
        self._give_kid(self.source_db, self._media(self.source_db, picture))

        new = self._add_as_new()

        self.assertEqual(self._paths_of(new), [os.path.join("scans", "kid.png")])

    def test_incoming_media_path_of_gramps_xml_is_used(self) -> None:
        """Paths relative to the incoming file's own media path are found."""
        self._open()
        xml_media = os.path.join(self.root, "xml_media")
        picture = self._file(xml_media, "kid.png")
        self.source_db.set_mediapath(xml_media)
        self._give_kid(self.source_db, self._media(self.source_db, "kid.png"))

        new = self._add_as_new()

        self.assertEqual(self._paths_of(new), [os.path.normpath(picture)])

    def test_file_exported_from_the_tree_keeps_its_relative_path(self) -> None:
        """A relative path that only the tree's base path resolves is kept."""
        self._open()
        self._file(self.base, "scans/kid.png")
        self._give_kid(self.source_db, self._media(self.source_db, "scans/kid.png"))

        new = self._add_as_new()

        self.assertEqual(self._paths_of(new), [os.path.join("scans", "kid.png")])

    def test_missing_file_keeps_its_path_as_written(self) -> None:
        """A picture that cannot be found is still copied, path unchanged."""
        self._open()
        self._give_kid(self.source_db, self._media(self.source_db, "gone/kid.png"))

        new = self._add_as_new()

        self.assertEqual(self._paths_of(new), ["gone/kid.png"])

    def test_gedcom_file_reference_is_found_beside_the_file(self) -> None:
        """An OBJE FILE in the GEDCOM itself ends up pointing at the file."""
        picture = self._file(self.incoming, "photos/kid.png", b"from gedcom")
        incoming_ged = HEADER + """0 @I1@ INDI
1 NAME Kid /Doe/
1 SEX M
1 OBJE @M1@
0 @M1@ OBJE
1 FILE photos/kid.png
2 FORM png
2 TITL Portrait
0 TRLR
"""
        tree_ged = self._file(self.elsewhere, "tree.ged", PERSON_GED.encode())
        self.db = import_as_dict(tree_ged, User())
        self.db.set_mediapath(self.base)
        path = self._file(self.incoming, "incoming.ged", incoming_ged.encode())
        self.gwizard = GedGWizard(self.db)
        self.gwizard.run_step("connect", gedcom_path=path)
        self.gwizard.run_step("load")

        new = self._add_as_new()

        (path,) = self._paths_of(new)
        self.assertEqual(path, os.path.normpath(picture))
        media = self.db.get_media_from_handle(new.get_media_list()[0].ref)
        self.assertEqual(media.get_checksum(), md5(b"from gedcom"))

    # ------------------------------------------------------------------
    # Bug 2: media references never point at missing media
    # ------------------------------------------------------------------
    def test_event_reference_to_missing_media_is_dropped(self) -> None:
        """An event's reference to media the incoming file lacks is left out."""
        self._open()
        kid = self._kid(self.source_db)
        event = Event()
        event.set_type(EventType.BIRTH)
        mref = MediaRef()
        mref.set_reference_handle("no-such-media")
        event.add_media_reference(mref)
        with DbTxn("event", self.source_db) as trans:
            self.source_db.add_event(event, trans)
            eref = EventRef()
            eref.ref = event.handle
            kid.add_event_ref(eref)
            kid.set_birth_ref(eref)
            self.source_db.commit_person(kid, trans)

        new = self._add_as_new()

        t_event = self.db.get_event_from_handle(new.get_event_ref_list()[0].ref)
        self.assertEqual(t_event.get_media_list(), [])

    def test_event_media_reference_citation_is_copied(self) -> None:
        """The citation on an event's media reference comes across too."""
        self._open()
        self._file(self.incoming, "kid.png")
        media = self._media(self.source_db, "kid.png")
        kid = self._kid(self.source_db)
        source = Source()
        source.set_title("Photo album")
        citation = Citation()
        citation.set_page("p. 9")
        event = Event()
        event.set_type(EventType.BIRTH)
        with DbTxn("event", self.source_db) as trans:
            self.source_db.add_source(source, trans)
            citation.set_reference_handle(source.handle)
            self.source_db.add_citation(citation, trans)
            mref = MediaRef()
            mref.set_reference_handle(media.handle)
            mref.add_citation(citation.handle)
            event.add_media_reference(mref)
            self.source_db.add_event(event, trans)
            eref = EventRef()
            eref.ref = event.handle
            kid.add_event_ref(eref)
            kid.set_birth_ref(eref)
            self.source_db.commit_person(kid, trans)

        new = self._add_as_new()

        t_event = self.db.get_event_from_handle(new.get_event_ref_list()[0].ref)
        (t_mref,) = t_event.get_media_list()
        (t_citation_handle,) = t_mref.get_citation_list()
        t_citation = self.db.get_citation_from_handle(t_citation_handle)
        self.assertEqual(t_citation.get_page(), "p. 9")

    def test_person_media_reference_citation_survives_add_as_new(self) -> None:
        """The person's own media reference keeps its citation."""
        self._open()
        self._file(self.incoming, "kid.png")
        media = self._media(self.source_db, "kid.png")
        source = Source()
        source.set_title("Photo album")
        citation = Citation()
        citation.set_page("p. 4")
        kid = self._kid(self.source_db)
        with DbTxn("cite", self.source_db) as trans:
            self.source_db.add_source(source, trans)
            citation.set_reference_handle(source.handle)
            self.source_db.add_citation(citation, trans)
            mref = MediaRef()
            mref.set_reference_handle(media.handle)
            mref.add_citation(citation.handle)
            kid.add_media_reference(mref)
            self.source_db.commit_person(kid, trans)

        new = self._add_as_new()

        (t_mref,) = new.get_media_list()
        (t_citation_handle,) = t_mref.get_citation_list()
        self.assertEqual(
            self.db.get_citation_from_handle(t_citation_handle).get_page(), "p. 4"
        )

    def test_media_and_citation_citing_each_other_do_not_loop(self) -> None:
        """A citation whose media reference cites it again is copied once."""
        self._open()
        self._file(self.incoming, "kid.png")
        media = self._media(self.source_db, "kid.png")
        source = Source()
        source.set_title("Album")
        citation = Citation()
        kid = self._kid(self.source_db)
        with DbTxn("loop", self.source_db) as trans:
            self.source_db.add_source(source, trans)
            citation.set_reference_handle(source.handle)
            self.source_db.add_citation(citation, trans)
            mref = MediaRef()
            mref.set_reference_handle(media.handle)
            mref.add_citation(citation.handle)
            citation.add_media_reference(mref)
            self.source_db.commit_citation(citation, trans)
            kid.add_citation(citation.handle)
            self.source_db.commit_person(kid, trans)

        new = self._add_as_new()

        (t_citation_handle,) = new.get_citation_list()
        t_citation = self.db.get_citation_from_handle(t_citation_handle)
        (t_mref,) = t_citation.get_media_list()
        self.assertTrue(self.db.has_media_handle(t_mref.ref))

    # ------------------------------------------------------------------
    # Bug 3: copied objects carry no tags from the incoming file
    # ------------------------------------------------------------------
    def test_copied_objects_have_no_incoming_tags(self) -> None:
        """Tags of the incoming file (e.g. the import tag) are not carried."""
        self._open()
        self._file(self.incoming, "kid.png")
        tag = Tag()
        tag.set_name("Imported")
        note = Note()
        note.set("A note")
        with DbTxn("tag", self.source_db) as trans:
            self.source_db.add_tag(tag, trans)
            note.add_tag(tag.handle)
            self.source_db.add_note(note, trans)
        media = self._media(self.source_db, "kid.png")
        media.add_tag(tag.handle)
        media.add_note(note.handle)
        with DbTxn("tag", self.source_db) as trans:
            self.source_db.commit_media(media, trans)
        self._give_kid(self.source_db, media)

        self._add_as_new()

        for iterate in ("iter_media", "iter_notes", "iter_events", "iter_people"):
            for obj in getattr(self.db, iterate)():
                for handle in obj.get_tag_list():
                    self.assertTrue(
                        self.db.has_tag_handle(handle),
                        "%s %s has a missing tag" % (iterate, obj.handle),
                    )

    # ------------------------------------------------------------------
    # Bug 4: a picture the tree already has is reused
    # ------------------------------------------------------------------
    def test_same_file_under_another_handle_is_reused(self) -> None:
        """The tree's media for the same file is used; nothing is added."""
        self._open()
        picture = self._file(self.base, "kid.png")
        existing = self._media(self.db, "kid.png")
        self._give_kid(self.source_db, self._media(self.source_db, picture))
        before = self.db.get_number_of_media()

        new = self._add_as_new()

        self.assertEqual(self.db.get_number_of_media(), before)
        self.assertEqual(new.get_media_list()[0].ref, existing.handle)

    def test_copy_with_recorded_checksum_is_reused(self) -> None:
        """A copy of the tree's picture elsewhere is the same picture."""
        self._open()
        self._file(self.base, "kid.png", b"same bytes")
        existing = self._media(self.db, "kid.png", checksum=md5(b"same bytes"))
        copy_path = self._file(self.elsewhere, "copy_of_kid.png", b"same bytes")
        self._give_kid(self.source_db, self._media(self.source_db, copy_path))

        new = self._add_as_new()

        self.assertEqual(new.get_media_list()[0].ref, existing.handle)

    def test_copy_without_recorded_checksum_is_reused(self) -> None:
        """The tree's files are hashed when needed (e.g. GEDCOM-imported trees)."""
        self._open()
        self._file(self.base, "kid.png", b"same bytes")
        self._file(self.base, "other.png", b"other bytes")
        self._media(self.db, "other.png")
        existing = self._media(self.db, "kid.png")
        copy_path = self._file(self.elsewhere, "copy_of_kid.png", b"same bytes")
        self._give_kid(self.source_db, self._media(self.source_db, copy_path))

        new = self._add_as_new()

        self.assertEqual(new.get_media_list()[0].ref, existing.handle)

    def test_different_files_are_not_merged(self) -> None:
        """A different picture is added even under the same file name."""
        self._open()
        self._file(self.base, "kid.png", b"tree picture")
        self._media(self.db, "kid.png")
        picture = self._file(self.incoming, "kid.png", b"incoming picture")
        self._give_kid(self.source_db, self._media(self.source_db, picture))
        before = self.db.get_number_of_media()

        self._add_as_new()

        self.assertEqual(self.db.get_number_of_media(), before + 1)

    def test_two_incoming_media_for_one_file_become_one(self) -> None:
        """Two incoming media objects for one file are copied once."""
        self._open()
        picture = self._file(self.incoming, "kid.png")
        self._give_kid(self.source_db, self._media(self.source_db, picture))
        self._give_kid(self.source_db, self._media(self.source_db, "kid.png"))
        before = self.db.get_number_of_media()

        new = self._add_as_new()

        self.assertEqual(self.db.get_number_of_media(), before + 1)
        refs = {ref.ref for ref in new.get_media_list()}
        self.assertEqual(len(refs), 1)

    def test_missing_file_with_the_same_recorded_path_is_reused(self) -> None:
        """With no file to compare, the same recorded path is the same media."""
        self._open()
        existing = self._media(self.db, "gone/kid.png")
        self._give_kid(self.source_db, self._media(self.source_db, "gone/kid.png"))

        new = self._add_as_new()

        self.assertEqual(new.get_media_list()[0].ref, existing.handle)

    # ------------------------------------------------------------------
    # Improvement 1: base media path detection
    # ------------------------------------------------------------------
    def test_without_a_base_path_files_are_recorded_in_full(self) -> None:
        """No base media path: even a relative-looking file is recorded in full."""
        self._open(base_path=False)
        self.assertFalse(base_path_configured(self.db))
        picture = self._file(self.incoming, "kid.png")
        self._give_kid(self.source_db, self._media(self.source_db, "kid.png"))

        new = self._add_as_new()

        self.assertEqual(self._paths_of(new), [os.path.normpath(picture)])

    def test_base_path_detection(self) -> None:
        self._open()
        self.assertTrue(base_path_configured(self.db))
        self.db.set_mediapath("")
        self.assertFalse(base_path_configured(self.db))

    def test_target_path_outside_the_base_is_full(self) -> None:
        self._open()
        inside = self._file(self.base, "a/b.png")
        outside = self._file(self.elsewhere, "b.png")
        self.assertEqual(target_path(inside, self.db), os.path.join("a", "b.png"))
        self.assertEqual(target_path(outside, self.db), outside)

    # ------------------------------------------------------------------
    # Improvement 3: missing files are reported
    # ------------------------------------------------------------------
    def test_rows_flag_missing_files_only(self) -> None:
        """Only a picture whose file is missing is marked in the compare rows."""
        self._open()
        self._file(self.incoming, "found.png", b"found")
        self._give_kid(self.source_db, self._media(self.source_db, "found.png"))
        self._give_kid(self.source_db, self._media(self.source_db, "gone.png"))

        values = sorted(r.source_val for r in self._media_rows())

        self.assertEqual(
            values,
            ["found.png (Portrait)", "gone.png (Portrait) [file not found]"],
        )

    def test_web_address_is_not_flagged(self) -> None:
        self._open()
        url = "https://example.com/kid.png"
        self.assertTrue(is_url(url))
        self.assertFalse(is_url("C:\\pics\\kid.png"))
        self._give_kid(self.source_db, self._media(self.source_db, url))
        (row,) = self._media_rows()
        self.assertNotIn("not found", row.source_val)

    def test_media_note(self) -> None:
        """The note counts missing files and warns about a missing base path."""
        self._open(base_path=False)
        self._file(self.incoming, "found.png")
        found = self._media(self.source_db, "found.png")
        gone = self._media(self.source_db, "gone.png")

        note = media_note([found.handle, gone.handle], self.source_db, self.db)

        self.assertIn("1 of 2 media files could not be found", note)
        self.assertIn("no base media path", note)
        self.db.set_mediapath(self.base)
        self.assertEqual(media_note([found.handle], self.source_db, self.db), "")

    def test_media_handles_of_person_and_events(self) -> None:
        self._open()
        own = self._media(self.source_db, "own.png")
        on_event = self._media(self.source_db, "event.png")
        self._give_kid(self.source_db, own)
        kid = self._kid(self.source_db)
        event = Event()
        mref = MediaRef()
        mref.set_reference_handle(on_event.handle)
        event.add_media_reference(mref)
        with DbTxn("event", self.source_db) as trans:
            self.source_db.add_event(event, trans)
            eref = EventRef()
            eref.ref = event.handle
            kid.add_event_ref(eref)
            self.source_db.commit_person(kid, trans)

        handles = media_handles_of(self._kid(self.source_db), self.source_db)

        self.assertEqual(handles, [own.handle, on_event.handle])

    # ------------------------------------------------------------------
    # Improvement 4: checksums are filled in
    # ------------------------------------------------------------------
    def test_checksum_is_filled_in_when_missing(self) -> None:
        self._open()
        self._file(self.incoming, "kid.png", b"kid bytes")
        self._give_kid(self.source_db, self._media(self.source_db, "kid.png"))

        new = self._add_as_new()

        media = self.db.get_media_from_handle(new.get_media_list()[0].ref)
        self.assertEqual(media.get_checksum(), md5(b"kid bytes"))

    # ------------------------------------------------------------------
    # Improvement 6: the same picture is recognised when comparing
    # ------------------------------------------------------------------
    def test_full_and_relative_path_to_one_file_match(self) -> None:
        """An incoming full path and the tree's relative path are one picture."""
        self._open()
        picture = self._file(self.base, "kid.png")
        self._give_kid(self.db, self._media(self.db, "kid.png"))
        self._give_kid(self.source_db, self._media(self.source_db, picture))

        self.assertEqual(self._media_rows(), [])

    def test_same_content_under_another_name_matches(self) -> None:
        """Same checksum, different file name: one picture, nothing to merge."""
        self._open()
        self._file(self.base, "kid.png", b"kid bytes")
        self._give_kid(self.db, self._media(self.db, "kid.png"))
        self._file(self.incoming, "IMG_0001.png", b"kid bytes")
        self._give_kid(self.source_db, self._media(self.source_db, "IMG_0001.png"))

        self.assertEqual(self._media_rows(), [])
        kid = self._merge_media()
        self.assertEqual(len(kid.get_media_list()), 1)

    def test_merging_a_new_picture_adds_it_once(self) -> None:
        self._open()
        picture = self._file(self.incoming, "kid.png")
        self._give_kid(self.source_db, self._media(self.source_db, "kid.png"))
        (row,) = self._media_rows()
        self.assertEqual(row.status, "source_only")

        self._merge_media()
        kid = self._merge_media()

        self.assertEqual(self._paths_of(kid), [os.path.normpath(picture)])

    def test_find_file_reads_paths_from_the_right_place(self) -> None:
        self._open()
        in_incoming = self._file(self.incoming, "x.png")
        in_base = self._file(self.base, "y.png")
        self.assertEqual(find_file(self.source_db, "x.png"), in_incoming)
        self.assertIsNone(find_file(self.db, "x.png"))
        self.assertEqual(find_file(self.db, "y.png"), in_base)
        self.assertEqual(find_file(self.source_db, "y.png", self.db), in_base)
        self.assertEqual(find_file(self.source_db, "photos\\x.png"), in_incoming)


if __name__ == "__main__":
    unittest.main()
