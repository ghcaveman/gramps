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
Tests for comparing and merging the families of people who are already
paired with a person in the tree.

The incoming Dad Doe and Mom Roe have a family with their daughter Ann, a
marriage in 1899 and a divorce in 1910. Each test starts from a tree that
has some of this already.
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
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.lib import EventType, FamilyRelType
from gramps.gen.user import User

HEADER = "0 HEAD\n1 CHAR UTF-8\n"
TRLR = "0 TRLR\n"
ZED = "0 @I9@ INDI\n1 NAME Zed /Zoe/\n1 SEX M\n"
DAD = "0 @I1@ INDI\n1 NAME Dad /Doe/\n1 SEX M\n{fams}"
MOM = "0 @I2@ INDI\n1 NAME Mom /Roe/\n1 SEX F\n{fams}"
ANN = "0 @I3@ INDI\n1 NAME Ann /Doe/\n1 SEX F\n1 BIRT\n2 DATE 1 JAN 1900\n{famc}"
MARRIAGE = "1 MARR\n2 DATE 1899\n2 PLAC Reno, NV\n"
DIVORCE = "1 DIV\n2 DATE 1910\n"

SOURCE_GED = (
    HEADER
    + DAD.format(fams="1 FAMS @F1@\n")
    + MOM.format(fams="1 FAMS @F1@\n")
    + ANN.format(famc="1 FAMC @F1@\n")
    + "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 CHIL @I3@\n"
    + MARRIAGE
    + DIVORCE
    + TRLR
)


def tree(*parts: str) -> str:
    return HEADER + "".join(parts) + TRLR


def linked(events: str = "", children: str = "1 CHIL @I3@\n") -> str:
    """Dad, Mom and Ann with a family in the tree."""
    return tree(
        DAD.format(fams="1 FAMS @F1@\n"),
        MOM.format(fams="1 FAMS @F1@\n"),
        ANN.format(famc="1 FAMC @F1@\n" if children else ""),
        "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n" + children + events,
    )


class GWizardFamilyCompareTest(unittest.TestCase):
    """Families of paired people are compared and merged."""

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

    def _entries(self) -> list[dict[str, Any]]:
        return self.gwizard.family_compare(
            self._first(self.gwizard.context["source_db"], "Dad").handle,
            self._first(self.db, "Dad").handle,
        )

    def _rows(self) -> list[Any]:
        rows = self.gwizard.run_step(
            "compare",
            source_person_handle=self._first(
                self.gwizard.context["source_db"], "Dad"
            ).handle,
            target_person_handle=self._first(self.db, "Dad").handle,
        )
        return [row for row in rows if row.field_type == "family"]

    def _merge_family(self, link_all: bool = False) -> None:
        (entry,) = self._entries()
        key = "link_families" if link_all else "family:" + entry["sf_handle"]
        self.assertTrue(
            self.gwizard.run_step(
                "apply",
                source_person_handle=self._first(
                    self.gwizard.context["source_db"], "Dad"
                ).handle,
                target_person_handle=self._first(self.db, "Dad").handle,
                resolutions={key: "source"},
            )
        )

    def _tree_family(self) -> Any:
        (family,) = list(self.db.iter_families())
        return family

    def _event_types(self, family: Any) -> list[str]:
        return sorted(
            str(self.db.get_event_from_handle(ref.ref).get_type())
            for ref in family.get_event_ref_list()
        )

    # ------------------------------------------------------------------
    # what differs
    # ------------------------------------------------------------------
    def test_missing_events_and_relationship_are_differences(self) -> None:
        """A tree family without the marriage and divorce is flagged."""
        self._open(linked())

        (entry,) = self._entries()

        self.assertEqual(sorted(entry["differences"]), ["events", "relationship"])
        self.assertEqual(len(entry["event_handles"]), 2)
        self.assertIn("1899", entry["source_text"])
        self.assertIn("Marriage", entry["source_text"])
        (row,) = self._rows()
        self.assertEqual(row.status, "differ")

    def test_matching_family_has_no_differences(self) -> None:
        """A family with the same events and members is not listed."""
        self._open(linked(events=MARRIAGE + DIVORCE))

        (entry,) = self._entries()

        self.assertEqual(entry["differences"], [])
        self.assertEqual(self._rows(), [])

    def test_family_missing_from_the_tree_is_listed(self) -> None:
        """Dad and Mom are in the tree but not linked: the family is missing."""
        self._open(
            tree(
                DAD.format(fams=""),
                MOM.format(fams=""),
                ANN.format(famc=""),
                ZED,
            )
        )

        (entry,) = self._entries()

        self.assertIsNone(entry["tf_handle"])
        self.assertTrue(entry["actionable"])
        self.assertEqual(entry["differences"], ["family"])
        (row,) = self._rows()
        self.assertEqual(row.status, "source_only")

    def test_family_with_partner_not_in_tree_is_not_actionable(self) -> None:
        """With only Dad in the tree there is nothing to merge yet."""
        self._open(tree(DAD.format(fams=""), ZED))

        (entry,) = self._entries()

        self.assertFalse(entry["actionable"])
        self.assertEqual(entry["differences"], [])
        self.assertEqual(self._rows(), [])

    def test_child_missing_from_the_family_is_a_member_difference(self) -> None:
        """Ann is in the tree but not in the family."""
        self._open(linked(events=MARRIAGE + DIVORCE, children=""))

        (entry,) = self._entries()

        self.assertEqual(entry["differences"], ["members"])

    def test_events_already_in_the_tree_are_not_offered_again(self) -> None:
        """Only the divorce is missing when the marriage is already there."""
        self._open(linked(events=MARRIAGE))

        (entry,) = self._entries()

        self.assertEqual(len(entry["event_handles"]), 1)

    # ------------------------------------------------------------------
    # merging
    # ------------------------------------------------------------------
    def test_merge_copies_events_once_and_sets_relationship(self) -> None:
        """Merging twice leaves one marriage, one divorce and the type."""
        self._open(linked())

        self._merge_family()
        self._merge_family()

        family = self._tree_family()
        self.assertEqual(self._event_types(family), ["Divorce", "Marriage"])
        self.assertEqual(family.get_relationship(), FamilyRelType.MARRIED)
        self.assertEqual(self._entries()[0]["differences"], [])
        self.assertEqual(self._rows(), [])

    def test_merge_creates_the_missing_family(self) -> None:
        """A family the tree lacks is created with all three people."""
        self._open(
            tree(
                DAD.format(fams=""),
                MOM.format(fams=""),
                ANN.format(famc=""),
                ZED,
            )
        )

        self._merge_family()

        family = self._tree_family()
        dad = self._first(self.db, "Dad")
        mom = self._first(self.db, "Mom")
        ann = self._first(self.db, "Ann")
        self.assertEqual(family.get_father_handle(), dad.handle)
        self.assertEqual(family.get_mother_handle(), mom.handle)
        self.assertEqual([r.ref for r in family.get_child_ref_list()], [ann.handle])
        self.assertEqual(dad.get_family_handle_list(), [family.handle])
        self.assertEqual(ann.get_parent_family_handle_list(), [family.handle])
        self.assertEqual(self._event_types(family), ["Divorce", "Marriage"])

    def test_merge_adds_the_missing_child(self) -> None:
        """Merging a family whose child is not in it adds the child."""
        self._open(linked(events=MARRIAGE + DIVORCE, children=""))

        self._merge_family()

        family = self._tree_family()
        ann = self._first(self.db, "Ann")
        self.assertEqual([r.ref for r in family.get_child_ref_list()], [ann.handle])
        self.assertEqual(ann.get_parent_family_handle_list(), [family.handle])

    def test_relationship_changes_only_when_the_family_is_chosen(self) -> None:
        """Linking everything keeps a known type; choosing the family replaces it."""
        self._open(linked())
        family = self._tree_family()
        family.set_relationship(FamilyRelType.UNMARRIED)
        with DbTxn("set type", self.db) as trans:
            self.db.commit_family(family, trans)

        self._merge_family(link_all=True)
        self.assertEqual(
            self._tree_family().get_relationship(), FamilyRelType.UNMARRIED
        )

        self._merge_family()
        self.assertEqual(self._tree_family().get_relationship(), FamilyRelType.MARRIED)

    def test_family_that_cannot_be_merged_yet_changes_nothing(self) -> None:
        """Choosing a family with Mom missing from the tree does nothing."""
        self._open(tree(DAD.format(fams=""), ZED))

        self._merge_family()

        self.assertEqual(self.db.get_number_of_families(), 0)
        self.assertEqual(self.db.get_number_of_events(), 0)


if __name__ == "__main__":
    unittest.main()
