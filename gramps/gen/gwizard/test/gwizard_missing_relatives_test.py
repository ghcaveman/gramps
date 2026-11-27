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
Tests for adding the relatives a tree lacks as new people.

The incoming file holds Thomas Baker (born 1753), his parents Joseph Baker
and Ruth Hale, his wife Mary Cole and their son William Baker. The tree
holds Thomas, and sometimes Mary. With ``add_missing_relatives`` a merge
adds the parents, spouses and children the tree has nobody for and links
them; without it, it leaves them out as before.
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
from gramps.gen.lib import EventType
from gramps.gen.user import User

HEADER = "0 HEAD\n1 CHAR UTF-8\n"
TRLR = "0 TRLR\n"


def source_ged(father_birth: str = "1728") -> str:
    """The incoming family of Thomas Baker."""
    return (
        HEADER
        + "0 @I1@ INDI\n1 NAME Thomas /Baker/\n1 SEX M\n"
        + "1 BIRT\n2 DATE 10 MAR 1753\n1 FAMC @F1@\n1 FAMS @F2@\n"
        + "0 @I2@ INDI\n1 NAME Joseph /Baker/\n1 SEX M\n"
        + "1 BIRT\n2 DATE %s\n1 FAMS @F1@\n" % father_birth
        + "0 @I3@ INDI\n1 NAME Ruth /Hale/\n1 SEX F\n"
        + "1 BIRT\n2 DATE 1730\n1 FAMS @F1@\n"
        + "0 @I4@ INDI\n1 NAME Mary /Cole/\n1 SEX F\n"
        + "1 BIRT\n2 DATE 1755\n1 FAMS @F2@\n"
        + "0 @I5@ INDI\n1 NAME William /Baker/\n1 SEX M\n"
        + "1 BIRT\n2 DATE 1780\n1 FAMC @F2@\n"
        + "0 @F1@ FAM\n1 HUSB @I2@\n1 WIFE @I3@\n1 CHIL @I1@\n"
        + "1 MARR\n2 DATE 1750\n"
        + "0 @F2@ FAM\n1 HUSB @I1@\n1 WIFE @I4@\n1 CHIL @I5@\n"
        + "1 MARR\n2 DATE 1777\n"
        + TRLR
    )


THOMAS = "0 @I1@ INDI\n1 NAME Thomas /Baker/\n1 SEX M\n1 BIRT\n2 DATE 10 MAR 1753\n"
MARY = "0 @I4@ INDI\n1 NAME Mary /Cole/\n1 SEX F\n1 BIRT\n2 DATE 1755\n"


class MissingRelativesTest(unittest.TestCase):
    """Adding the relatives the tree has nobody for."""

    def setUp(self) -> None:
        self._paths: list[str] = []
        self.db: Any = None
        self._wizards: list[GedGWizard] = []

    def tearDown(self) -> None:
        for gwizard in self._wizards:
            source_db = gwizard.context.get("source_db")
            if source_db is not None:
                source_db.close()
        if self.db is not None:
            self.db.close()
        for path in self._paths:
            if os.path.exists(path):
                os.remove(path)

    def _write(self, text: str) -> str:
        with tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write(text)
        self._paths.append(handle.name)
        return handle.name

    def _people(self, db: Any, first: str, surname: str) -> list[Any]:
        return [
            person
            for person in db.iter_people()
            if person.get_primary_name().first_name == first
            and person.get_primary_name().get_surname() == surname
        ]

    def _one(self, db: Any, first: str, surname: str) -> Any:
        found = self._people(db, first, surname)
        self.assertEqual(len(found), 1, "%s %s" % (first, surname))
        return found[0]

    def _open_tree(self, tree_records: str) -> None:
        self.db = import_as_dict(self._write(HEADER + tree_records + TRLR), User())

    def _wizard(self, father_birth: str = "1728") -> GedGWizard:
        gwizard = GedGWizard(self.db)
        self._wizards.append(gwizard)
        self.assertTrue(
            gwizard.run_step(
                "connect", gedcom_path=self._write(source_ged(father_birth))
            )
        )
        gwizard.run_step("load")
        return gwizard

    def _merge(
        self,
        resolutions: dict[str, str] | None = None,
        add: bool = True,
        father_birth: str = "1728",
    ) -> GedGWizard:
        """Merge the incoming Thomas into the tree's Thomas."""
        gwizard = self._wizard(father_birth)
        source_db = gwizard.context["source_db"]
        self.assertTrue(
            gwizard.run_step(
                "apply",
                source_person_handle=self._one(source_db, "Thomas", "Baker").handle,
                target_person_handle=self._one(self.db, "Thomas", "Baker").handle,
                resolutions=(
                    {"link_families": "source"} if resolutions is None else resolutions
                ),
                add_missing_relatives=add,
            )
        )
        return gwizard

    def _source_handle(self, gwizard: GedGWizard, first: str, surname: str) -> str:
        return self._one(gwizard.context["source_db"], first, surname).handle

    def _parents(self, person: Any) -> tuple[Any, Any, Any]:
        """Return (family, father, mother) of a person's only parent family."""
        families = person.get_parent_family_handle_list()
        self.assertEqual(len(families), 1)
        family = self.db.get_family_from_handle(families[0])
        return (
            family,
            self.db.get_person_from_handle(family.get_father_handle()),
            self.db.get_person_from_handle(family.get_mother_handle()),
        )

    def _marriage_years(self, family: Any) -> list[int]:
        years = []
        for ref in family.get_event_ref_list():
            event = self.db.get_event_from_handle(ref.ref)
            if event.get_type() == EventType.MARRIAGE:
                years.append(event.get_date_object().get_year())
        return years

    def _added(self, gwizard: GedGWizard) -> list[str]:
        return [
            entry["detail"]
            for entry in gwizard.context["link_summary"]
            if entry["status"] == "added"
        ]

    # ------------------------------------------------------------------
    # Whole-family linking
    # ------------------------------------------------------------------
    def test_missing_parents_wife_and_son_are_added_and_linked(self) -> None:
        """Joseph, Ruth and William are added; Mary, already there, is linked."""
        self._open_tree(THOMAS + MARY)
        gwizard = self._merge()
        self.assertEqual(self.db.get_number_of_people(), 5)
        thomas = self._one(self.db, "Thomas", "Baker")
        family, father, mother = self._parents(thomas)
        self.assertEqual(father.get_primary_name().first_name, "Joseph")
        self.assertEqual(mother.get_primary_name().first_name, "Ruth")
        self.assertEqual(self._marriage_years(family), [1750])
        self.assertIn(family.handle, father.get_family_handle_list())
        self.assertIn(family.handle, mother.get_family_handle_list())

        own = [
            self.db.get_family_from_handle(h) for h in thomas.get_family_handle_list()
        ]
        self.assertEqual(len(own), 1)
        mary = self._one(self.db, "Mary", "Cole")
        self.assertEqual(own[0].get_mother_handle(), mary.handle)
        william = self._one(self.db, "William", "Baker")
        self.assertEqual([r.ref for r in own[0].get_child_ref_list()], [william.handle])
        self.assertEqual(self._marriage_years(own[0]), [1777])
        self.assertEqual(
            sorted(self._added(gwizard)),
            [
                "Baker, Joseph added as a new person",
                "Baker, William added as a new person",
                "Hale, Ruth added as a new person",
            ],
        )

    def test_without_the_option_nobody_is_added(self) -> None:
        """Off, the merge only links the people the tree already has."""
        self._open_tree(THOMAS + MARY)
        gwizard = self._merge(add=False)
        self.assertEqual(self.db.get_number_of_people(), 2)
        self.assertEqual(self._added(gwizard), [])
        thomas = self._one(self.db, "Thomas", "Baker")
        self.assertEqual(thomas.get_parent_family_handle_list(), [])

    def test_merging_again_adds_nobody_twice(self) -> None:
        """A second merge finds the relatives the first one added."""
        self._open_tree(THOMAS)
        self._merge()
        self.assertEqual(self.db.get_number_of_people(), 5)
        families = self.db.get_number_of_families()
        gwizard = self._merge()
        self.assertEqual(self.db.get_number_of_people(), 5)
        self.assertEqual(self.db.get_number_of_families(), families)
        self.assertEqual(self._added(gwizard), [])

    # ------------------------------------------------------------------
    # Relatives chosen one by one in the merge dialog
    # ------------------------------------------------------------------
    def test_chosen_parents_are_added_into_one_family(self) -> None:
        """The Father and Mother rows add both parents to one family."""
        self._open_tree(THOMAS)
        gwizard = self._wizard()
        father = self._source_handle(gwizard, "Joseph", "Baker")
        mother = self._source_handle(gwizard, "Ruth", "Hale")
        self.assertTrue(
            gwizard.run_step(
                "apply",
                source_person_handle=self._source_handle(gwizard, "Thomas", "Baker"),
                target_person_handle=self._one(self.db, "Thomas", "Baker").handle,
                resolutions={
                    "father:" + father: "source",
                    "mother:" + mother: "source",
                },
                add_missing_relatives=True,
            )
        )
        self.assertEqual(self.db.get_number_of_people(), 3)
        self.assertEqual(self.db.get_number_of_families(), 1)
        family, joseph, ruth = self._parents(self._one(self.db, "Thomas", "Baker"))
        self.assertEqual(joseph.get_primary_name().first_name, "Joseph")
        self.assertEqual(ruth.get_primary_name().first_name, "Ruth")
        self.assertEqual(self._marriage_years(family), [1750])

    def test_chosen_wife_and_son_are_added(self) -> None:
        """The Spouse and Children rows add Mary and William to one family."""
        self._open_tree(THOMAS)
        gwizard = self._wizard()
        mary = self._source_handle(gwizard, "Mary", "Cole")
        william = self._source_handle(gwizard, "William", "Baker")
        self.assertTrue(
            gwizard.run_step(
                "apply",
                source_person_handle=self._source_handle(gwizard, "Thomas", "Baker"),
                target_person_handle=self._one(self.db, "Thomas", "Baker").handle,
                resolutions={"spouse:" + mary: "source", "child:" + william: "source"},
                add_missing_relatives=True,
            )
        )
        thomas = self._one(self.db, "Thomas", "Baker")
        own = [
            self.db.get_family_from_handle(h) for h in thomas.get_family_handle_list()
        ]
        self.assertEqual(len(own), 1)
        self.assertEqual(
            own[0].get_mother_handle(), self._one(self.db, "Mary", "Cole").handle
        )
        self.assertEqual(
            [r.ref for r in own[0].get_child_ref_list()],
            [self._one(self.db, "William", "Baker").handle],
        )
        self.assertEqual(self._marriage_years(own[0]), [1777])

    def test_unchosen_relatives_are_not_added(self) -> None:
        """Only the rows the user chose bring relatives in."""
        self._open_tree(THOMAS)
        gwizard = self._wizard()
        father = self._source_handle(gwizard, "Joseph", "Baker")
        gwizard.run_step(
            "apply",
            source_person_handle=self._source_handle(gwizard, "Thomas", "Baker"),
            target_person_handle=self._one(self.db, "Thomas", "Baker").handle,
            resolutions={"father:" + father: "source"},
            add_missing_relatives=True,
        )
        self.assertEqual(self._people(self.db, "Ruth", "Hale"), [])
        self.assertEqual(self._people(self.db, "Mary", "Cole"), [])
        self.assertEqual(len(self._people(self.db, "Joseph", "Baker")), 1)

    # ------------------------------------------------------------------
    # Relatives that are not added
    # ------------------------------------------------------------------
    def test_a_birth_year_refusal_is_not_added(self) -> None:
        """A Joseph Baker in the tree born far from 1728 may still be him."""
        self._open_tree(
            THOMAS + "0 @I9@ INDI\n1 NAME Joseph /Baker/\n1 SEX M\n"
            "1 BIRT\n2 DATE 1700\n"
        )
        gwizard = self._merge()
        self.assertEqual(len(self._people(self.db, "Joseph", "Baker")), 1)
        details = [
            entry["detail"]
            for entry in gwizard.context["link_summary"]
            if entry["status"] == "conflict"
        ]
        self.assertTrue(any("1700" in text for text in details), details)

    def test_a_parent_born_too_late_is_not_added(self) -> None:
        """A father born three years before his son is not added."""
        self._open_tree(THOMAS)
        gwizard = self._merge(father_birth="1750")
        self.assertEqual(self._people(self.db, "Joseph", "Baker"), [])
        details = [
            entry["detail"]
            for entry in gwizard.context["link_summary"]
            if entry["status"] == "conflict"
        ]
        self.assertTrue(any("was not added" in text for text in details), details)
        # The mother still is.
        self.assertEqual(len(self._people(self.db, "Ruth", "Hale")), 1)

    # ------------------------------------------------------------------
    # Adding the incoming person as new
    # ------------------------------------------------------------------
    def test_add_as_new_brings_the_relatives(self) -> None:
        """Adding Thomas as new, with the option, adds his whole family."""
        self._open_tree(MARY)
        gwizard = self._wizard()
        self.assertTrue(
            gwizard.run_step(
                "apply",
                source_person_handle=self._source_handle(gwizard, "Thomas", "Baker"),
                target_person_handle=None,
                resolutions={},
                link_families=True,
                add_missing_relatives=True,
            )
        )
        self.assertEqual(self.db.get_number_of_people(), 5)
        thomas = self._one(self.db, "Thomas", "Baker")
        _family, joseph, _ruth = self._parents(thomas)
        self.assertEqual(joseph.get_primary_name().first_name, "Joseph")
        own = self.db.get_family_from_handle(thomas.get_family_handle_list()[0])
        self.assertEqual(
            own.get_mother_handle(), self._one(self.db, "Mary", "Cole").handle
        )


if __name__ == "__main__":
    unittest.main()
