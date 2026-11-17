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
Tests for linking family relationships when a person is added as new.

The incoming file holds Dad Doe, who has two marriages: to Mom Roe, with
children Ann (1900), Cal (1902) and Bob (1905, adopted), and to Vera Poe.
Each test starts with some of these people already in the tree.
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
from gramps.gen.gwizard.gwizardgedcom import (
    GedGWizard,
    format_link_preview,
    format_link_summary,
)
from gramps.gen.lib import ChildRefType, EventType
from gramps.gen.user import User

SOURCE_GED = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Dad /Doe/
1 SEX M
1 FAMS @F1@
1 FAMS @F2@
0 @I2@ INDI
1 NAME Mom /Roe/
1 SEX F
1 FAMS @F1@
0 @I3@ INDI
1 NAME Ann /Doe/
1 SEX F
1 BIRT
2 DATE 1 JAN 1900
1 FAMC @F1@
0 @I4@ INDI
1 NAME Bob /Doe/
1 SEX M
1 BIRT
2 DATE 1 JAN 1905
1 FAMC @F1@
2 PEDI adopted
0 @I5@ INDI
1 NAME Cal /Doe/
1 SEX M
1 BIRT
2 DATE 1 JAN 1902
1 FAMC @F1@
0 @I6@ INDI
1 NAME Vera /Poe/
1 SEX F
1 FAMS @F2@
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
1 CHIL @I5@
1 CHIL @I4@
1 MARR
2 DATE 1899
2 PLAC Reno, NV
0 @F2@ FAM
1 HUSB @I1@
1 WIFE @I6@
0 TRLR
"""

HEADER = "0 HEAD\n1 CHAR UTF-8\n"
# A person who is in no incoming family, so the tree is never empty.
ZED = "0 @I9@ INDI\n1 NAME Zed /Zoe/\n1 SEX M\n"
DAD = "0 @I1@ INDI\n1 NAME Dad /Doe/\n1 SEX M\n{fams}"
MOM = "0 @I2@ INDI\n1 NAME Mom /Roe/\n1 SEX F\n{fams}"
ANN = "0 @I3@ INDI\n1 NAME Ann /Doe/\n1 SEX F\n1 BIRT\n2 DATE 1 JAN 1900\n{famc}"
BOB = "0 @I4@ INDI\n1 NAME Bob /Doe/\n1 SEX M\n1 BIRT\n2 DATE 1 JAN 1905\n{famc}"
VERA = "0 @I6@ INDI\n1 NAME Vera /Poe/\n1 SEX F\n{fams}"
TRLR = "0 TRLR\n"


def tree(*parts: str) -> str:
    """Build a GEDCOM text from person/family records."""
    return HEADER + "".join(parts) + TRLR


class GWizardLinkFamiliesTest(unittest.TestCase):
    """Adding a person as new links their families into the tree."""

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

    def _open(self, target_ged: str) -> None:
        self.db = import_as_dict(self._write(target_ged), User())
        self.gwizard = GedGWizard(self.db)
        self.assertTrue(
            self.gwizard.run_step("connect", gedcom_path=self._write(SOURCE_GED))
        )
        self.gwizard.run_step("load")

    def _first(self, db: Any, first: str) -> Any:
        for person in db.iter_people():
            if person.get_primary_name().first_name == first:
                return person
        raise AssertionError("no person named %s" % first)

    def _add(self, first: str, link: bool = True) -> Any:
        """Add the incoming ``first`` as a new person; return that person."""
        before = set(self.db.iter_person_handles())
        self.assertTrue(
            self.gwizard.run_step(
                "apply",
                source_person_handle=self._first(
                    self.gwizard.context["source_db"], first
                ).handle,
                target_person_handle=None,
                resolutions={},
                link_families=link,
            )
        )
        (handle,) = set(self.db.iter_person_handles()) - before
        return self.db.get_person_from_handle(handle)

    def _families_of(self, first: str) -> list[Any]:
        person = self._first(self.db, first)
        return [
            self.db.get_family_from_handle(h) for h in person.get_family_handle_list()
        ]

    def _children(self, family: Any) -> list[str]:
        return [
            self.db.get_person_from_handle(ref.ref).get_primary_name().first_name
            for ref in family.get_child_ref_list()
        ]

    def _statuses(self) -> list[str]:
        return [entry["status"] for entry in self.gwizard.context["link_summary"]]

    # ------------------------------------------------------------------
    # joining an existing family
    # ------------------------------------------------------------------
    def _existing_family_tree(self) -> str:
        """Dad, Mom, Ann and Bob, already a family."""
        return tree(
            DAD.format(fams="1 FAMS @F1@\n"),
            MOM.format(fams="1 FAMS @F1@\n"),
            ANN.format(famc="1 FAMC @F1@\n"),
            BOB.format(famc="1 FAMC @F1@\n"),
            "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 CHIL @I3@\n1 CHIL @I4@\n",
        )

    def test_new_child_is_placed_by_birth_date(self) -> None:
        """Cal (1902) goes between Ann (1900) and Bob (1905)."""
        self._open(self._existing_family_tree())

        self._add("Cal")

        (family,) = self._families_of("Dad")
        self.assertEqual(self._children(family), ["Ann", "Cal", "Bob"])
        cal = self._first(self.db, "Cal")
        self.assertEqual(cal.get_parent_family_handle_list(), [family.handle])
        self.assertEqual(self.db.get_number_of_families(), 1)

    def test_child_relationship_type_is_kept(self) -> None:
        """Bob was adopted in the incoming file and stays adopted."""
        self._open(
            tree(
                DAD.format(fams="1 FAMS @F1@\n"),
                MOM.format(fams="1 FAMS @F1@\n"),
                ANN.format(famc="1 FAMC @F1@\n"),
                "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 CHIL @I3@\n",
            )
        )

        self._add("Bob")

        (family,) = self._families_of("Dad")
        bob = self._first(self.db, "Bob")
        (ref,) = [r for r in family.get_child_ref_list() if r.ref == bob.handle]
        self.assertEqual(ref.get_father_relation(), ChildRefType.ADOPTED)
        self.assertEqual(ref.get_mother_relation(), ChildRefType.ADOPTED)

    # ------------------------------------------------------------------
    # nothing to link yet, and the flag
    # ------------------------------------------------------------------
    def test_no_relatives_in_tree_creates_no_family(self) -> None:
        """A person whose relatives are all missing arrives on their own."""
        self._open(tree(ZED))

        person = self._add("Ann")

        self.assertEqual(person.get_parent_family_handle_list(), [])
        self.assertEqual(self.db.get_number_of_families(), 0)
        self.assertEqual(self._statuses(), ["waiting"])

    def test_linking_can_be_turned_off(self) -> None:
        """With link_families=False the person arrives with no families."""
        self._open(self._existing_family_tree())

        person = self._add("Cal", link=False)

        self.assertEqual(person.get_parent_family_handle_list(), [])
        (family,) = self._families_of("Dad")
        self.assertEqual(self._children(family), ["Ann", "Bob"])

    # ------------------------------------------------------------------
    # order independence
    # ------------------------------------------------------------------
    def _assert_one_complete_family(self) -> None:
        self.assertEqual(self.db.get_number_of_families(), 1)
        (family,) = self._families_of("Dad")
        self.assertEqual(
            self.db.get_person_from_handle(family.get_mother_handle())
            .get_primary_name()
            .first_name,
            "Mom",
        )
        self.assertEqual(self._children(family), ["Ann"])
        for first in ("Dad", "Mom"):
            self.assertEqual(
                self._first(self.db, first).get_family_handle_list(), [family.handle]
            )
        self.assertEqual(
            self._first(self.db, "Ann").get_parent_family_handle_list(),
            [family.handle],
        )

    def test_parents_first_then_child(self) -> None:
        """Dad, Mom, then Ann: one family with all three."""
        self._open(tree(ZED))
        self._add("Dad")
        self._add("Mom")
        self._add("Ann")
        # The second marriage has no other member in the tree yet.
        self._assert_one_complete_family()

    def test_child_first_then_parents(self) -> None:
        """Ann, Mom, then Dad: the same family, filled in as they arrive."""
        self._open(tree(ZED))
        self._add("Ann")
        self._add("Mom")
        self._add("Dad")
        self._assert_one_complete_family()

    # ------------------------------------------------------------------
    # family events, and running again
    # ------------------------------------------------------------------
    def test_marriage_event_is_copied_once(self) -> None:
        """The family's marriage comes across, and running again adds nothing."""
        # Dad and Mom are in the tree, unlinked; adding Ann builds the family.
        self._open(tree(DAD.format(fams=""), MOM.format(fams=""), ZED))
        ann = self._add("Ann")

        (family,) = [
            self.db.get_family_from_handle(h)
            for h in ann.get_parent_family_handle_list()
        ]
        marriages = [
            r
            for r in family.get_event_ref_list()
            if self.db.get_event_from_handle(r.ref).get_type() == EventType.MARRIAGE
        ]
        self.assertEqual(len(marriages), 1)

        # Link again for Ann's own record: nothing is duplicated.
        for _ in range(2):
            self.assertTrue(
                self.gwizard.run_step(
                    "apply",
                    source_person_handle=self._first(
                        self.gwizard.context["source_db"], "Ann"
                    ).handle,
                    target_person_handle=ann.handle,
                    resolutions={"link_families": "source"},
                )
            )
        family = self.db.get_family_from_handle(family.handle)
        self.assertEqual(len(family.get_event_ref_list()), 1)
        self.assertEqual(self._children(family), ["Ann"])
        self.assertEqual(self.db.get_number_of_families(), 1)

    def test_several_marriages_keep_their_order(self) -> None:
        """Dad's families follow the incoming order: Mom first, then Vera."""
        self._open(tree(MOM.format(fams=""), VERA.format(fams=""), ZED))

        dad = self._add("Dad")

        mothers = [
            self.db.get_person_from_handle(f.get_mother_handle())
            .get_primary_name()
            .first_name
            for f in (
                self.db.get_family_from_handle(h) for h in dad.get_family_handle_list()
            )
        ]
        self.assertEqual(mothers, ["Mom", "Vera"])

    # ------------------------------------------------------------------
    # conflicts
    # ------------------------------------------------------------------
    def test_child_with_other_parents_is_reported_not_moved(self) -> None:
        """Ann already has other parents in the tree, so she is left alone."""
        other = tree(
            MOM.format(fams=""),
            "0 @I7@ INDI\n1 NAME Pat /Poe/\n1 SEX M\n1 FAMS @F7@\n",
            "0 @I8@ INDI\n1 NAME Sam /Poe/\n1 SEX F\n1 FAMS @F7@\n",
            ANN.format(famc="1 FAMC @F7@\n"),
            "0 @F7@ FAM\n1 HUSB @I7@\n1 WIFE @I8@\n1 CHIL @I3@\n",
        )
        self._open(other)
        ann_before = self._first(self.db, "Ann").get_parent_family_handle_list()

        self._add("Dad")

        ann = self._first(self.db, "Ann")
        self.assertEqual(ann.get_parent_family_handle_list(), ann_before)
        (family,) = self._families_of("Dad")
        self.assertNotIn("Ann", self._children(family))
        self.assertIn("conflict", self._statuses())

    # ------------------------------------------------------------------
    # preview and wording
    # ------------------------------------------------------------------
    def test_preview_says_who_is_in_the_tree(self) -> None:
        """The preview tells which relatives are already there."""
        self._open(tree(MOM.format(fams=""), ZED))
        source_dad = self._first(self.gwizard.context["source_db"], "Dad")

        entries = self.gwizard.link_preview(source_dad.handle)

        self.assertEqual([e["will_link"] for e in entries], [True, False])
        first = {m["name"]: m["in_tree"] for m in entries[0]["members"]}
        self.assertTrue(first["Doe, Dad"])
        self.assertTrue(first["Roe, Mom"])
        self.assertFalse(first["Doe, Ann"])
        text = format_link_preview(entries)
        self.assertIn("Roe, Mom", text)
        self.assertIn("not in your tree yet", text)

    def test_summary_text_lists_conflicts(self) -> None:
        """Only the entries asked for are written out."""
        summary = [
            {"status": "linked", "family": "A and B", "detail": "A"},
            {
                "status": "conflict",
                "family": "C and D",
                "detail": "C has other parents",
            },
        ]
        text = format_link_summary(summary)
        self.assertIn("C and D", text)
        self.assertIn("C has other parents", text)
        self.assertNotIn("A and B", text)


if __name__ == "__main__":
    unittest.main()
