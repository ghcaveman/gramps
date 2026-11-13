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
Tests for comparing and merging alternate names, attributes, addresses,
notes, web links, media and LDS ordinances of a person.

The incoming Kid Doe has an alternate name, three attributes (one of them
the FamilySearch ID), two notes and an address. The tree's Kid Doe has the
Social Security attribute and the first note already. Web links, media and
LDS ordinances are added by the tests that need them.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
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
from gramps.gen.db.utils import import_as_dict
from gramps.gen.gwizard.gwizardgedcom import (
    EXTRA_KINDS,
    GedGWizard,
    extra_items,
    extra_signature,
    pair_extra_items,
)
from gramps.gen.lib import (
    Address,
    Date,
    LdsOrd,
    Media,
    MediaRef,
    Note,
    NoteType,
    Place,
    Url,
    UrlType,
)
from gramps.gen.user import User

HEADER = "0 HEAD\n1 CHAR UTF-8\n"

SOURCE_GED = HEADER + """0 @I1@ INDI
1 NAME Kid /Doe/
1 NAME Kiddo /Doe/
2 TYPE aka
3 SOUR @S1@
4 PAGE p. 3
1 SEX M
1 DSCR tall and thin
1 SSN 123-45
1 _FSFTID ABCD-123
1 NOTE First note text
1 NOTE Second note text
0 @S1@ SOUR
1 TITL Book
0 TRLR
"""

# The tree already knows the Social Security number and the first note.
TARGET_GED = HEADER + """0 @I1@ INDI
1 NAME Kid /Doe/
1 SEX M
1 SSN 123-45
1 NOTE First note text
0 TRLR
"""


class GWizardExtraItemsTest(unittest.TestCase):
    """Alternate names, attributes, addresses and notes are compared."""

    def setUp(self) -> None:
        self._paths: list[str] = []
        self.db: Any = None
        self.gwizard: GedGWizard | None = None

    def tearDown(self) -> None:
        if self.gwizard is not None:
            source_db = self.gwizard.context.get("source_db")
            if source_db is not None:
                source_db.close()
        if self.db is not None:
            self.db.close()
        for path in self._paths:
            if os.path.exists(path):
                os.remove(path)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _write(self, text: str) -> str:
        with tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write(text)
        self._paths.append(handle.name)
        return handle.name

    def _open(self, target_ged: str = TARGET_GED, source_ged: str = SOURCE_GED) -> None:
        self.db = import_as_dict(self._write(target_ged), User())
        self.gwizard = GedGWizard(self.db)
        self.assertTrue(
            self.gwizard.run_step("connect", gedcom_path=self._write(source_ged))
        )
        self.gwizard.run_step("load")

    @property
    def source_db(self) -> Any:
        return self.gwizard.context["source_db"]

    def _kid(self, db: Any) -> Any:
        (person,) = [p for p in db.iter_people()]
        return person

    def _add_address(self, db: Any, person: Any, street: str) -> None:
        address = Address()
        address.set_street(street)
        address.set_city("Reno")
        person.add_address(address)
        with DbTxn("address", db) as trans:
            db.commit_person(person, trans)

    def _add_url(self, db: Any, person: Any, path: str) -> None:
        url = Url()
        url.set_path(path)
        url.set_type(UrlType.WEB_HOME)
        url.set_description("Home page")
        person.add_url(url)
        with DbTxn("url", db) as trans:
            db.commit_person(person, trans)

    def _add_media(
        self, db: Any, person: Any, path: str, description: str = ""
    ) -> None:
        media = Media()
        media.set_path(path)
        media.set_description(description)
        media.set_mime_type("image/png")
        mref = MediaRef()
        with DbTxn("media", db) as trans:
            db.add_media(media, trans)
            mref.set_reference_handle(media.handle)
            person.add_media_reference(mref)
            db.commit_person(person, trans)

    def _add_lds(self, db: Any, person: Any, temple: str = "SLAKE") -> LdsOrd:
        ordinance = LdsOrd()
        ordinance.set_type(LdsOrd.BAPTISM)
        ordinance.set_temple(temple)
        ordinance.set_status(LdsOrd.STATUS_COMPLETED)
        ordinance.set_date_object(Date(1930, 5, 6))
        person.add_lds_ord(ordinance)
        with DbTxn("lds", db) as trans:
            db.commit_person(person, trans)
        return ordinance

    def _rows(self) -> list[Any]:
        rows = self.gwizard.run_step(
            "compare",
            source_person_handle=self._kid(self.source_db).handle,
            target_person_handle=self._kid(self.db).handle,
        )
        return [row for row in rows if row.field_type in EXTRA_KINDS]

    def _merge(self, keys: list[str]) -> None:
        self.assertTrue(
            self.gwizard.run_step(
                "apply",
                source_person_handle=self._kid(self.source_db).handle,
                target_person_handle=self._kid(self.db).handle,
                resolutions={key: "source" for key in keys},
            )
        )

    # ------------------------------------------------------------------
    # what is compared
    # ------------------------------------------------------------------
    def test_unmatched_items_are_listed(self) -> None:
        """Each item the tree lacks shows up; matching items do not."""
        self._open()
        self._add_address(self.source_db, self._kid(self.source_db), "12 Main St")
        self._add_url(
            self.source_db, self._kid(self.source_db), "http://example.com/kid"
        )
        self._add_media(
            self.source_db, self._kid(self.source_db), "kid.png", "Portrait"
        )
        self._add_lds(self.source_db, self._kid(self.source_db))

        rows = {row.field_type: row for row in self._rows()}

        self.assertEqual(set(rows), set(EXTRA_KINDS))
        self.assertTrue(all(r.status == "source_only" for r in rows.values()))
        self.assertIn("Kiddo", rows["altname"].source_val)
        self.assertEqual(rows["attribute"].source_val, "Description: tall and thin")
        self.assertIn("12 Main St", rows["address"].source_val)
        self.assertIn("Second note text", rows["note"].source_val)
        self.assertIn("http://example.com/kid", rows["url"].source_val)
        self.assertEqual(rows["media"].source_val, "kid.png (Portrait)")
        self.assertIn("Baptism", rows["lds"].source_val)
        self.assertIn("SLAKE", rows["lds"].source_val)

    def test_matching_items_are_not_listed(self) -> None:
        """Same social security number and first note: no rows for them."""
        self._open()
        values = [row.source_val for row in self._rows()]
        self.assertFalse(any("123-45" in value for value in values))
        self.assertFalse(any("First note text" in value for value in values))

    def test_familysearch_id_is_not_an_attribute_row(self) -> None:
        """The FamilySearch ID has its own row in the dialog."""
        self._open()
        source_kid = self._kid(self.source_db)
        names = [
            str(a.get_type())
            for _i, a in extra_items("attribute", source_kid, self.source_db)
        ]
        self.assertNotIn("_FSFTID", names)
        self.assertEqual(sorted(names), ["Description", "Social Security Number"])

    def test_importer_notes_are_not_compared(self) -> None:
        """The note the GEDCOM importer writes about itself is left out."""
        self._open()
        kid = self._kid(self.db)
        note = Note("Records not imported into INDI")
        note.set_type("GEDCOM import")
        with DbTxn("import note", self.db) as trans:
            self.db.add_note(note, trans)
            kid.add_note(note.handle)
            self.db.commit_person(kid, trans)

        self.assertEqual(
            [n.get() for _i, n in extra_items("note", kid, self.db)],
            ["First note text"],
        )

    def test_items_only_in_the_tree_are_reported(self) -> None:
        """An item only the tree has is a target_only row."""
        self._open()
        kid = self._kid(self.db)
        self._add_address(self.db, kid, "9 Elm Rd")

        (row,) = [r for r in self._rows() if r.field_type == "address"]

        self.assertEqual(row.status, "target_only")
        self.assertIn("9 Elm Rd", row.target_val)

    def test_same_content_matches_whatever_the_spacing_and_case(self) -> None:
        """Notes that differ only in case or spacing are the same note."""
        first = Note("Hello   World")
        second = Note("hello world")
        first.set_type(NoteType.PERSON)
        second.set_type(NoteType.PERSON)
        self.assertEqual(
            extra_signature("note", first), extra_signature("note", second)
        )
        third = Note("hello there")
        third.set_type(NoteType.PERSON)
        self.assertNotEqual(
            extra_signature("note", first), extra_signature("note", third)
        )

    def test_pairing_puts_matches_first(self) -> None:
        """Pairs come first, then incoming-only, then tree-only items."""
        self._open()
        pairs = pair_extra_items(
            "note",
            self._kid(self.source_db),
            self.source_db,
            self._kid(self.db),
            self.db,
        )
        shape = [(s is not None, t is not None) for _a, s, _b, t in pairs]
        self.assertEqual(shape, [(True, True), (True, False)])

    # ------------------------------------------------------------------
    # merging
    # ------------------------------------------------------------------
    def _keys(self) -> list[str]:
        return [
            "%s:%d" % (row.field_type, row.extra_data["source_index"])
            for row in self._rows()
        ]

    def test_merge_copies_each_item_once(self) -> None:
        """All four kinds are added, and merging again adds nothing."""
        self._open()
        self._add_address(self.source_db, self._kid(self.source_db), "12 Main St")
        self._add_url(
            self.source_db, self._kid(self.source_db), "http://example.com/kid"
        )
        self._add_media(self.source_db, self._kid(self.source_db), "kid.png")
        self._add_lds(self.source_db, self._kid(self.source_db))
        keys = self._keys()
        self.assertEqual(len(keys), 7)

        self._merge(keys)
        self._merge(keys)

        kid = self._kid(self.db)
        self.assertEqual(
            [extra_signature("altname", n)[1] for n in kid.get_alternate_names()],
            ["kiddo"],
        )
        attributes = sorted(
            a.get_value() for _i, a in extra_items("attribute", kid, self.db)
        )
        self.assertEqual(attributes, ["123-45", "tall and thin"])
        self.assertEqual(
            [a.get_street() for a in kid.get_address_list()], ["12 Main St"]
        )
        self.assertEqual(
            sorted(n.get() for _i, n in extra_items("note", kid, self.db)),
            ["First note text", "Second note text"],
        )
        self.assertEqual(
            [u.get_path() for u in kid.get_url_list()], ["http://example.com/kid"]
        )
        self.assertEqual(
            [
                self.db.get_media_from_handle(m.ref).get_path()
                for m in kid.get_media_list()
            ],
            ["kid.png"],
        )
        self.assertEqual(
            [(o.type2str(), o.get_temple()) for o in kid.get_lds_ord_list()],
            [("Baptism", "SLAKE")],
        )
        self.assertEqual(self._rows(), [])

    def test_same_web_link_matches_despite_trailing_slash_and_case(self) -> None:
        """A link that differs only by a trailing slash or case is the same."""
        self._open()
        self._add_url(
            self.source_db, self._kid(self.source_db), "HTTP://Example.com/kid/"
        )
        self._add_url(self.db, self._kid(self.db), "http://example.com/kid")
        self.assertEqual([r for r in self._rows() if r.field_type == "url"], [])

    def test_different_web_link_is_listed(self) -> None:
        """A different link is listed as something to add."""
        self._open()
        self._add_url(
            self.source_db, self._kid(self.source_db), "http://example.com/other"
        )
        self._add_url(self.db, self._kid(self.db), "http://example.com/kid")
        rows = [r for r in self._rows() if r.field_type == "url"]
        self.assertEqual(
            sorted((r.status, r.source_val or r.target_val) for r in rows),
            [
                ("source_only", "Web Home: http://example.com/other (Home page)"),
                ("target_only", "Web Home: http://example.com/kid (Home page)"),
            ],
        )

    def test_copied_alternate_name_keeps_its_citation(self) -> None:
        """The alternate name's citation comes across, with its source."""
        self._open()
        (row,) = [r for r in self._rows() if r.field_type == "altname"]

        self._merge(["altname:%d" % row.extra_data["source_index"]])

        (alt,) = self._kid(self.db).get_alternate_names()
        (citation_handle,) = alt.get_citation_list()
        citation = self.db.get_citation_from_handle(citation_handle)
        self.assertEqual(citation.get_page(), "p. 3")
        source = self.db.get_source_from_handle(citation.get_reference_handle())
        self.assertEqual(source.get_title(), "Book")

    # ------------------------------------------------------------------
    # media
    # ------------------------------------------------------------------
    def test_same_media_file_matches_whatever_the_slashes_and_case(self) -> None:
        """The same picture under a differently written path is the same."""
        self._open()
        self._add_media(self.source_db, self._kid(self.source_db), "Pics\\Kid.PNG")
        self._add_media(self.db, self._kid(self.db), "pics/kid.png")
        self.assertEqual([r for r in self._rows() if r.field_type == "media"], [])

    def test_media_only_in_the_tree_is_reported(self) -> None:
        """A picture only the tree has is a target_only row."""
        self._open()
        self._add_media(self.db, self._kid(self.db), "elsewhere.png")
        (row,) = [r for r in self._rows() if r.field_type == "media"]
        self.assertEqual(row.status, "target_only")
        self.assertEqual(row.target_val, "elsewhere.png")

    def test_media_reference_keeps_its_details_and_media_is_reused(self) -> None:
        """The copied reference keeps its region and citations; no duplicate."""
        self._open()
        kid = self._kid(self.source_db)
        self._add_media(self.source_db, kid, "kid.png", "Portrait")
        kid = self._kid(self.source_db)
        kid.get_media_list()[0].set_rectangle((1, 2, 30, 40))
        with DbTxn("rect", self.source_db) as trans:
            self.source_db.commit_person(kid, trans)
        (row,) = [r for r in self._rows() if r.field_type == "media"]
        media_before = self.db.get_number_of_media()

        self._merge(["media:%d" % row.extra_data["source_index"]])
        self._merge(["media:%d" % row.extra_data["source_index"]])

        self.assertEqual(self.db.get_number_of_media(), media_before + 1)
        (mref,) = self._kid(self.db).get_media_list()
        self.assertEqual(mref.get_rectangle(), (1, 2, 30, 40))
        media = self.db.get_media_from_handle(mref.ref)
        self.assertEqual(media.get_description(), "Portrait")

    # ------------------------------------------------------------------
    # LDS ordinances
    # ------------------------------------------------------------------
    def test_ordinance_differing_in_temple_is_a_different_ordinance(self) -> None:
        """Same type and date at another temple is listed on both sides."""
        self._open()
        self._add_lds(self.source_db, self._kid(self.source_db), "SLAKE")
        self._add_lds(self.db, self._kid(self.db), "LOGAN")
        rows = [r for r in self._rows() if r.field_type == "lds"]
        self.assertEqual(sorted(r.status for r in rows), ["source_only", "target_only"])

    def test_same_ordinance_is_not_listed(self) -> None:
        """An ordinance the tree has, ignoring case, is not listed."""
        self._open()
        self._add_lds(self.source_db, self._kid(self.source_db), "SLAKE")
        self._add_lds(self.db, self._kid(self.db), "slake")
        self.assertEqual([r for r in self._rows() if r.field_type == "lds"], [])

    def test_copied_ordinance_gets_the_place_and_drops_the_family(self) -> None:
        """The temple place is created in the tree; no family link is kept."""
        self._open()
        kid = self._kid(self.source_db)
        self._add_lds(self.source_db, kid)
        place = Place()
        place.get_name().set_value("Salt Lake Temple")
        with DbTxn("place", self.source_db) as trans:
            self.source_db.add_place(place, trans)
            kid = self._kid(self.source_db)
            kid.get_lds_ord_list()[0].set_place_handle(place.handle)
            kid.get_lds_ord_list()[0].set_family_handle("stale-family")
            self.source_db.commit_person(kid, trans)
        (row,) = [r for r in self._rows() if r.field_type == "lds"]

        self._merge(["lds:%d" % row.extra_data["source_index"]])

        (copied,) = self._kid(self.db).get_lds_ord_list()
        self.assertIsNone(copied.get_family_handle())
        target_place = self.db.get_place_from_handle(copied.get_place_handle())
        self.assertEqual(target_place.get_name().get_value(), "Salt Lake Temple")

    def test_add_as_new_person_keeps_lds_ordinances(self) -> None:
        """Adding the incoming person as new brings the ordinances along."""
        self._open()
        self._add_lds(self.source_db, self._kid(self.source_db))
        self.assertTrue(
            self.gwizard.run_step(
                "apply",
                source_person_handle=self._kid(self.source_db).handle,
                target_person_handle=None,
                resolutions={},
            )
        )
        added = [p for p in self.db.iter_people() if p.get_lds_ord_list()]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].get_lds_ord_list()[0].get_temple(), "SLAKE")

    def test_merged_note_is_a_new_note_for_the_person(self) -> None:
        """A merged note is added next to the tree's own note."""
        self._open()
        (row,) = [r for r in self._rows() if r.field_type == "note"]
        notes_before = self.db.get_number_of_notes()

        self._merge(["note:%d" % row.extra_data["source_index"]])

        self.assertEqual(self.db.get_number_of_notes(), notes_before + 1)
        self.assertEqual(len(self._kid(self.db).get_note_list()), 2)


if __name__ == "__main__":
    unittest.main()
