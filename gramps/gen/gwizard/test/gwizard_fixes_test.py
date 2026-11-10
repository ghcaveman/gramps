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
Regression tests for GWizard merge relationship and event handling.

Each test builds both trees from small inline GEDCOM text, so no fixture
files are needed.
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
from gramps.gen.db.utils import import_as_dict
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.lib import EventRoleType, EventType
from gramps.gen.user import User

# The incoming file: Kid Doe, whose parents are Dad Doe and Mom Roe.
SOURCE_GED = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Kid /Doe/
1 SEX M
1 BIRT
2 DATE 1 JAN 1900
1 RESI
2 DATE 1920
2 PLAC Reno, NV
1 FAMC @F1@
0 @I2@ INDI
1 NAME Dad /Doe/
1 SEX M
1 FAMS @F1@
0 @I3@ INDI
1 NAME Mom /Roe/
1 SEX F
1 FAMS @F1@
0 @F1@ FAM
1 HUSB @I2@
1 WIFE @I3@
1 CHIL @I1@
0 TRLR
"""

# The same three people with no relationships.
TARGET_NO_FAMILY = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Kid /Doe/
1 SEX M
0 @I2@ INDI
1 NAME Dad /Doe/
1 SEX M
0 @I3@ INDI
1 NAME Mom /Roe/
1 SEX F
0 TRLR
"""

# Dad and Mom already have a family; ``@I1@`` is optionally their child.
TARGET_WITH_FAMILY = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Kid /Doe/
1 SEX M
{famc}0 @I2@ INDI
1 NAME Dad /Doe/
1 SEX M
1 FAMS @F1@
0 @I3@ INDI
1 NAME Mom /Roe/
1 SEX F
1 FAMS @F1@
0 @F1@ FAM
1 HUSB @I2@
1 WIFE @I3@
{chil}0 TRLR
"""


class GWizardMergeFixesTest(unittest.TestCase):
    """Merge keeps both sides of a relationship consistent."""

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

    def _open(self, target_ged: str, source_ged: str = SOURCE_GED) -> None:
        """Import ``target_ged`` as the tree and load ``source_ged``."""
        self.db = import_as_dict(self._write(target_ged), User())
        self.gwizard = GedGWizard(self.db)
        self.assertTrue(
            self.gwizard.run_step("connect", gedcom_path=self._write(source_ged))
        )
        self.gwizard.run_step("load")

    def _person(self, db: Any, first: str) -> Any:
        for person in db.iter_people():
            if person.get_primary_name().first_name == first:
                return person
        raise AssertionError("no person named %s" % first)

    def _source(self, first: str) -> Any:
        return self._person(self.gwizard.context["source_db"], first)

    def _apply(self, target_first: str, resolutions: dict[str, str]) -> None:
        assert self.gwizard is not None
        result = self.gwizard.run_step(
            "apply",
            source_person_handle=self._source(target_first).handle,
            target_person_handle=self._person(self.db, target_first).handle,
            resolutions=resolutions,
        )
        self.assertTrue(result)

    # ------------------------------------------------------------------
    # parents
    # ------------------------------------------------------------------
    def test_parent_merge_links_both_sides(self) -> None:
        """Father and mother also list the new family (no one-way links)."""
        self._open(TARGET_NO_FAMILY)
        self._apply(
            "Kid",
            {
                "father:" + self._source("Dad").handle: "source",
                "mother:" + self._source("Mom").handle: "source",
            },
        )
        kid = self._person(self.db, "Kid")
        dad = self._person(self.db, "Dad")
        mom = self._person(self.db, "Mom")

        self.assertEqual(len(kid.get_parent_family_handle_list()), 1)
        family = self.db.get_family_from_handle(kid.get_parent_family_handle_list()[0])
        self.assertEqual(family.get_father_handle(), dad.handle)
        self.assertEqual(family.get_mother_handle(), mom.handle)
        self.assertIn(family.handle, dad.get_family_handle_list())
        self.assertIn(family.handle, mom.get_family_handle_list())
        self.assertEqual([c.ref for c in family.get_child_ref_list()], [kid.handle])

    # ------------------------------------------------------------------
    # children
    # ------------------------------------------------------------------
    def test_child_already_in_family_is_not_duplicated(self) -> None:
        """A child the family already has is skipped, not added again."""
        self._open(
            TARGET_WITH_FAMILY.format(famc="1 FAMC @F1@\n", chil="1 CHIL @I1@\n")
        )
        self._apply("Dad", {"child:" + self._source("Kid").handle: "source"})

        dad = self._person(self.db, "Dad")
        family = self.db.get_family_from_handle(dad.get_family_handle_list()[0])
        self.assertEqual(len(family.get_child_ref_list()), 1)
        kid = self._person(self.db, "Kid")
        self.assertEqual(kid.get_parent_family_handle_list(), [family.handle])

    def test_child_merge_twice_adds_one_child(self) -> None:
        """Pushing the same child again leaves a single child reference."""
        self._open(TARGET_WITH_FAMILY.format(famc="", chil=""))
        key = {"child:" + self._source("Kid").handle: "source"}
        self._apply("Dad", key)
        self._apply("Dad", key)

        dad = self._person(self.db, "Dad")
        kid = self._person(self.db, "Kid")
        family = self.db.get_family_from_handle(dad.get_family_handle_list()[0])
        self.assertEqual([c.ref for c in family.get_child_ref_list()], [kid.handle])
        self.assertEqual(kid.get_parent_family_handle_list(), [family.handle])

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    def test_other_event_keeps_source_role(self) -> None:
        """A copied event keeps the role it had, not a blank Custom role."""
        self._open(TARGET_NO_FAMILY)
        source_kid = self._source("Kid")
        source_db = self.gwizard.context["source_db"]
        resi = [
            ref.ref
            for ref in source_kid.get_event_ref_list()
            if source_db.get_event_from_handle(ref.ref).get_type()
            == EventType.RESIDENCE
        ]
        self.assertEqual(len(resi), 1)

        self._apply("Kid", {"event:" + resi[0]: "source"})

        kid = self._person(self.db, "Kid")
        refs = [
            ref
            for ref in kid.get_event_ref_list()
            if self.db.get_event_from_handle(ref.ref).get_type() == EventType.RESIDENCE
        ]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].get_role(), EventRoleType.PRIMARY)

    def test_birth_event_merge_is_primary(self) -> None:
        """A merged birth becomes the person's birth with the Primary role."""
        self._open(TARGET_NO_FAMILY)
        self._apply("Kid", {"birth_event": "source"})

        kid = self._person(self.db, "Kid")
        birth_ref = kid.get_birth_ref()
        self.assertIsNotNone(birth_ref)
        self.assertEqual(birth_ref.get_role(), EventRoleType.PRIMARY)
        self.assertEqual(
            self.db.get_event_from_handle(birth_ref.ref).get_date_object().get_year(),
            1900,
        )

    # ------------------------------------------------------------------
    # pairing shared by the compare window
    # ------------------------------------------------------------------
    def test_relative_uses_compare_window_pairing(self) -> None:
        """The pairing in the context decides which person a relative is."""
        # Two equally good "Dad Doe" candidates in the tree.
        target = TARGET_NO_FAMILY + ""
        target = target.replace(
            "0 TRLR\n", "0 @I4@ INDI\n1 NAME Dad /Doe/\n1 SEX M\n0 TRLR\n"
        )
        self._open(target)
        dads = [
            p
            for p in self.db.iter_people()
            if p.get_primary_name().first_name == "Dad"
        ]
        self.assertEqual(len(dads), 2)
        chosen = dads[1]
        self.gwizard.context["pair_map"] = {self._source("Dad").handle: chosen.handle}

        self._apply("Kid", {"father:" + self._source("Dad").handle: "source"})

        kid = self._person(self.db, "Kid")
        family = self.db.get_family_from_handle(kid.get_parent_family_handle_list()[0])
        self.assertEqual(family.get_father_handle(), chosen.handle)

    def test_rejected_pair_is_not_linked_by_fuzzy_match(self) -> None:
        """A person the window left unpaired is not linked as a relative."""
        self._open(TARGET_NO_FAMILY)
        self.gwizard.context["pair_map"] = {self._source("Dad").handle: None}

        self._apply("Kid", {"father:" + self._source("Dad").handle: "source"})

        kid = self._person(self.db, "Kid")
        for family_handle in kid.get_parent_family_handle_list():
            family = self.db.get_family_from_handle(family_handle)
            self.assertIsNone(family.get_father_handle())


if __name__ == "__main__":
    unittest.main()
