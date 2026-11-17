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
Tests for how GWizard copies referenced objects into the family tree.

The incoming file here is a copy of the tree itself, so every note,
citation and place shares its handle with the tree's own object. That is
what a Gramps XML file exported from the same tree looks like. Each test
then changes the incoming copy and checks that the change is kept rather
than being replaced by the tree's object that happens to share the handle.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import copy
import os
import tempfile
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import import_as_dict, make_database
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.lib import Media, MediaRef, Place, PlaceRef, PlaceType
from gramps.gen.user import User

TREE_GED = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Kid /Doe/
1 SEX M
1 BIRT
2 DATE 1 JAN 1900
1 NOTE original note
1 SOUR @S1@
2 PAGE p. 1
0 @I2@ INDI
1 NAME Dad /Doe/
1 SEX M
0 @S1@ SOUR
1 TITL Book
0 TRLR
"""

_KINDS = (
    ("iter_people", "add_person"),
    ("iter_families", "add_family"),
    ("iter_events", "add_event"),
    ("iter_places", "add_place"),
    ("iter_sources", "add_source"),
    ("iter_citations", "add_citation"),
    ("iter_repositories", "add_repository"),
    ("iter_media", "add_media"),
    ("iter_notes", "add_note"),
    ("iter_tags", "add_tag"),
)


def clone_database(db: Any) -> Any:
    """Return an in-memory copy of ``db`` that keeps every handle."""
    clone = make_database("sqlite")
    clone.load(":memory:")
    with DbTxn("clone", clone) as trans:
        for iterate, add in _KINDS:
            for obj in getattr(db, iterate)():
                getattr(clone, add)(copy.deepcopy(obj), trans)
    return clone


class GWizardHandleMapTest(unittest.TestCase):
    """Shared handles do not make different content the same object."""

    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        )
        handle.write(TREE_GED)
        handle.close()
        self._path = handle.name
        db = import_as_dict(self._path, User())
        assert db is not None
        self.db = db
        self.source_db = clone_database(self.db)
        self.gwizard = GedGWizard(self.db)
        self.gwizard.context["source_db"] = self.source_db

    def tearDown(self) -> None:
        self.source_db.close()
        self.db.close()
        os.remove(self._path)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _named(self, db: Any, first: str) -> Any:
        for person in db.iter_people():
            if person.get_primary_name().first_name == first:
                return person
        raise AssertionError("no person named %s" % first)

    def _add_as_new(self, first: str) -> Any:
        """Add the incoming ``first`` as a new person; return that person."""
        before = set(self.db.iter_person_handles())
        self.assertTrue(
            self.gwizard.run_step(
                "apply",
                source_person_handle=self._named(self.source_db, first).handle,
                target_person_handle=None,
                resolutions={},
            )
        )
        (new_handle,) = set(self.db.iter_person_handles()) - before
        return self.db.get_person_from_handle(new_handle)

    def _commit_source(self, add_method: str, *objects: Any) -> None:
        with DbTxn("edit incoming copy", self.source_db) as trans:
            for obj in objects:
                getattr(self.source_db, add_method)(obj, trans)

    def _note_texts(self, db: Any, handles: Any) -> list[str]:
        return sorted(db.get_note_from_handle(h).get() for h in handles)

    def _pages(self, db: Any, handles: Any) -> list[str]:
        return sorted(db.get_citation_from_handle(h).get_page() for h in handles)

    # ------------------------------------------------------------------
    # notes
    # ------------------------------------------------------------------
    def test_changed_note_is_copied_not_replaced(self) -> None:
        """Different text under the same handle is kept as its own note."""
        kid = self._named(self.source_db, "Kid")
        note = self.source_db.get_note_from_handle(kid.get_note_list()[0])
        note.set("incoming note")
        self._commit_source("commit_note", note)

        new_person = self._add_as_new("Kid")

        self.assertEqual(
            self._note_texts(self.db, new_person.get_note_list()), ["incoming note"]
        )
        self.assertEqual(
            self._note_texts(self.db, self.db.iter_note_handles()),
            ["incoming note", "original note"],
        )

    def test_unchanged_note_is_reused(self) -> None:
        """The very same note is not copied a second time."""
        existing = set(self.db.iter_note_handles())

        new_person = self._add_as_new("Kid")

        self.assertEqual(set(self.db.iter_note_handles()), existing)
        self.assertEqual(set(new_person.get_note_list()), existing)

    # ------------------------------------------------------------------
    # citations
    # ------------------------------------------------------------------
    def test_changed_citation_is_copied_and_source_reused(self) -> None:
        """A changed page gives a new citation; the same source is reused."""
        kid = self._named(self.source_db, "Kid")
        citation = self.source_db.get_citation_from_handle(kid.get_citation_list()[0])
        citation.set_page("p. 99")
        self._commit_source("commit_citation", citation)
        sources_before = self.db.get_number_of_sources()

        new_person = self._add_as_new("Kid")

        self.assertEqual(
            self._pages(self.db, new_person.get_citation_list()), ["p. 99"]
        )
        self.assertEqual(
            self._pages(self.db, self.db.iter_citation_handles()), ["p. 1", "p. 99"]
        )
        self.assertEqual(self.db.get_number_of_sources(), sources_before)

    def test_shared_object_is_copied_once_across_merges(self) -> None:
        """Two people citing the same changed citation share one copy."""
        kid = self._named(self.source_db, "Kid")
        dad = self._named(self.source_db, "Dad")
        citation = self.source_db.get_citation_from_handle(kid.get_citation_list()[0])
        citation.set_page("p. 99")
        dad.add_citation(citation.handle)
        self._commit_source("commit_citation", citation)
        self._commit_source("commit_person", dad)

        new_kid = self._add_as_new("Kid")
        new_dad = self._add_as_new("Dad")

        self.assertEqual(new_kid.get_citation_list(), new_dad.get_citation_list())
        self.assertEqual(
            self._pages(self.db, self.db.iter_citation_handles()), ["p. 1", "p. 99"]
        )

    def test_shared_media_is_copied_once_across_merges(self) -> None:
        """Two people referencing the same media object share one copy."""
        media = Media()
        media.set_path("sample_photo.jpg")
        media.set_description("Family Portrait")
        media.set_mime_type("image/jpeg")
        self._commit_source("add_media", media)

        kid = self._named(self.source_db, "Kid")
        dad = self._named(self.source_db, "Dad")

        mref_kid = MediaRef()
        mref_kid.ref = media.handle
        kid.add_media_reference(mref_kid)

        mref_dad = MediaRef()
        mref_dad.ref = media.handle
        dad.add_media_reference(mref_dad)

        self._commit_source("commit_person", kid)
        self._commit_source("commit_person", dad)

        media_before = self.db.get_number_of_media()

        new_kid = self._add_as_new("Kid")
        new_dad = self._add_as_new("Dad")

        # Both people reference the same newly copied media handle in target DB
        kid_mrefs = new_kid.get_media_list()
        dad_mrefs = new_dad.get_media_list()
        self.assertEqual(len(kid_mrefs), 1)
        self.assertEqual(len(dad_mrefs), 1)
        self.assertEqual(kid_mrefs[0].ref, dad_mrefs[0].ref)

        # Only one media was added to target DB
        self.assertEqual(self.db.get_number_of_media(), media_before + 1)
        target_media = self.db.get_media_from_handle(kid_mrefs[0].ref)
        self.assertIsNotNone(target_media)
        self.assertEqual(target_media.get_description(), "Family Portrait")

    def test_stale_map_entry_is_ignored(self) -> None:
        """A mapped handle that no longer exists (rolled back) is not reused."""
        kid = self._named(self.source_db, "Kid")
        source_note = kid.get_note_list()[0]
        note = self.source_db.get_note_from_handle(source_note)
        note.set("incoming note")
        self._commit_source("commit_note", note)
        self.gwizard.context["handle_map"] = {"note": {source_note: "no-such-handle"}}

        new_person = self._add_as_new("Kid")

        self.assertEqual(
            self._note_texts(self.db, new_person.get_note_list()), ["incoming note"]
        )

    # ------------------------------------------------------------------
    # places
    # ------------------------------------------------------------------
    def _add_places(self) -> tuple[Place, Place]:
        """Give the incoming Kid a birthplace Reno, enclosed by Washoe."""
        county = Place()
        county.get_name().set_value("Washoe")
        county.set_type(PlaceType.COUNTY)
        town = Place()
        town.get_name().set_value("Reno")
        town.set_type(PlaceType.CITY)
        with DbTxn("incoming places", self.source_db) as trans:
            # A new place only gets its handle when it is added.
            self.source_db.add_place(county, trans)
            ref = PlaceRef()
            ref.ref = county.handle
            town.add_placeref(ref)
            self.source_db.add_place(town, trans)
        kid = self._named(self.source_db, "Kid")
        birth = self.source_db.get_event_from_handle(kid.get_birth_ref().ref)
        birth.set_place_handle(town.handle)
        self._commit_source("commit_event", birth)
        return county, town

    def test_place_hierarchy_is_copied_without_dangling_refs(self) -> None:
        """An enclosing place is copied too, and the link points at the copy."""
        self._add_places()

        new_person = self._add_as_new("Kid")

        birth = self.db.get_event_from_handle(new_person.get_birth_ref().ref)
        town = self.db.get_place_from_handle(birth.get_place_handle())
        self.assertEqual(town.get_name().get_value(), "Reno")
        (ref,) = town.get_placeref_list()
        self.assertTrue(self.db.has_place_handle(ref.ref))
        self.assertEqual(
            self.db.get_place_from_handle(ref.ref).get_name().get_value(), "Washoe"
        )

    def test_untitled_place_is_not_merged_into_another_untitled_place(self) -> None:
        """Places with an empty title are told apart by their names."""
        elsewhere = Place()
        elsewhere.get_name().set_value("Elsewhere")
        with DbTxn("existing place", self.db) as trans:
            self.db.add_place(elsewhere, trans)
        self._add_places()

        new_person = self._add_as_new("Kid")

        birth = self.db.get_event_from_handle(new_person.get_birth_ref().ref)
        self.assertNotEqual(birth.get_place_handle(), elsewhere.handle)
        names = sorted(place.get_name().get_value() for place in self.db.iter_places())
        self.assertEqual(names, ["Elsewhere", "Reno", "Washoe"])


if __name__ == "__main__":
    unittest.main()
