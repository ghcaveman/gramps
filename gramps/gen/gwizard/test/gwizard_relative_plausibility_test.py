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
Tests that a merge links a relative only to a plausible person in the tree.

The incoming file holds Thomas Baker (born 1753) and his parents Joseph
Baker and Ruth Hale. A relative the compare window did not pair is found
by name; a first name alone, a surname that differs, or a birth year that
cannot fit must not make someone in the tree that relative.
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
from gramps.gen.gwizard.gwizard_base import (
    parent_age_problem,
    relative_match_plausible,
)
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.lib import Name, Person, Surname
from gramps.gen.user import User

HEADER = "0 HEAD\n1 CHAR UTF-8\n"
TRLR = "0 TRLR\n"


def source_ged(father_birth: str) -> str:
    """The incoming family; father_birth is a GEDCOM date or ''."""
    birth = "1 BIRT\n2 DATE %s\n" % father_birth if father_birth else ""
    return (
        HEADER
        + "0 @I1@ INDI\n1 NAME Thomas /Baker/\n1 SEX M\n"
        + "1 BIRT\n2 DATE 10 MAR 1753\n1 FAMC @F1@\n"
        + "0 @I2@ INDI\n1 NAME Joseph /Baker/\n1 SEX M\n"
        + birth
        + "1 FAMS @F1@\n"
        + "0 @I3@ INDI\n1 NAME Ruth /Hale/\n1 SEX F\n1 FAMS @F1@\n"
        + "0 @F1@ FAM\n1 HUSB @I2@\n1 WIFE @I3@\n1 CHIL @I1@\n"
        + TRLR
    )


THOMAS = "0 @I1@ INDI\n1 NAME Thomas /Baker/\n1 SEX M\n1 BIRT\n2 DATE 10 MAR 1753\n"


def person_ged(xref: str, given: str, surname: str, sex: str, year: str) -> str:
    """One tree person record."""
    birth = "1 BIRT\n2 DATE %s\n" % year if year else ""
    return "0 @%s@ INDI\n1 NAME %s /%s/\n1 SEX %s\n%s" % (
        xref,
        given,
        surname,
        sex,
        birth,
    )


class RelativePlausibilityMergeTest(unittest.TestCase):
    """Merging Thomas links his parents only to people who fit."""

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

    def _write(self, text: str) -> str:
        with tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write(text)
        self._paths.append(handle.name)
        return handle.name

    def _first(self, db: Any, first: str, surname: str = "") -> Any:
        for person in db.iter_people():
            name = person.get_primary_name()
            if name.first_name == first and (
                not surname or name.get_surname() == surname
            ):
                return person
        raise AssertionError("no person named %s %s" % (first, surname))

    def _merge_thomas(self, tree_records: str, father_birth: str) -> Any:
        """Merge the incoming Thomas into the tree's Thomas, linking families."""
        self.db = import_as_dict(self._write(HEADER + tree_records + TRLR), User())
        self.gwizard = GedGWizard(self.db)
        self.assertTrue(
            self.gwizard.run_step(
                "connect", gedcom_path=self._write(source_ged(father_birth))
            )
        )
        self.gwizard.run_step("load")
        source_db = self.gwizard.context["source_db"]
        target = self._first(self.db, "Thomas", "Baker")
        self.assertTrue(
            self.gwizard.run_step(
                "apply",
                source_person_handle=self._first(source_db, "Thomas").handle,
                target_person_handle=target.handle,
                resolutions={"link_families": "source"},
            )
        )
        return self.db.get_person_from_handle(target.handle)

    def _statuses(self) -> list[str]:
        assert self.gwizard is not None
        return [entry["status"] for entry in self.gwizard.context["link_summary"]]

    def test_first_name_alone_is_not_a_father(self) -> None:
        """Joseph Miller (1905) is not Thomas's father Joseph Baker."""
        thomas = self._merge_thomas(
            THOMAS
            + person_ged("I2", "Joseph", "Miller", "M", "1905")
            + person_ged("I3", "Ruth Ann", "Cole", "F", "1910"),
            father_birth="1728",
        )
        self.assertEqual(thomas.get_parent_family_handle_list(), [])
        self.assertEqual(self.db.get_number_of_families(), 0)
        miller = self._first(self.db, "Joseph", "Miller")
        self.assertEqual(miller.get_family_handle_list(), [])

    def test_first_name_alone_is_not_a_father_without_dates(self) -> None:
        """With no birth date on the incoming father, the surname still decides."""
        thomas = self._merge_thomas(
            THOMAS + person_ged("I2", "Joseph", "Miller", "M", "1905"),
            father_birth="",
        )
        self.assertEqual(thomas.get_parent_family_handle_list(), [])
        self.assertEqual(self.db.get_number_of_families(), 0)

    def test_birth_year_far_apart_is_not_the_same_person(self) -> None:
        """A Joseph Baker born in 1905 is not the Joseph Baker born in 1728."""
        thomas = self._merge_thomas(
            THOMAS + person_ged("I2", "Joseph", "Baker", "M", "1905"),
            father_birth="1728",
        )
        self.assertEqual(thomas.get_parent_family_handle_list(), [])
        self.assertEqual(self.db.get_number_of_families(), 0)

    def test_parent_born_after_child_is_a_conflict(self) -> None:
        """An undated incoming father that names a too-young tree person is refused."""
        thomas = self._merge_thomas(
            THOMAS
            + person_ged("I2", "Joseph", "Baker", "M", "1905")
            + person_ged("I3", "Ruth", "Hale", "F", ""),
            father_birth="",
        )
        self.assertIn("conflict", self._statuses())
        joseph = self._first(self.db, "Joseph", "Baker")
        self.assertEqual(joseph.get_family_handle_list(), [])
        # The mother still fits, so Thomas is linked to her alone.
        (family_handle,) = thomas.get_parent_family_handle_list()
        family = self.db.get_family_from_handle(family_handle)
        self.assertIsNone(family.get_father_handle())
        ruth = self._first(self.db, "Ruth", "Hale")
        self.assertEqual(family.get_mother_handle(), ruth.handle)

    def test_plausible_father_is_linked(self) -> None:
        """Joseph Baker born 1730 is linked as the father."""
        thomas = self._merge_thomas(
            THOMAS + person_ged("I2", "Joseph", "Baker", "M", "1730"),
            father_birth="1728",
        )
        (family_handle,) = thomas.get_parent_family_handle_list()
        family = self.db.get_family_from_handle(family_handle)
        joseph = self._first(self.db, "Joseph", "Baker")
        self.assertEqual(family.get_father_handle(), joseph.handle)


class RelativePlausibilityHelperTest(unittest.TestCase):
    """The helpers behind the merge checks."""

    @staticmethod
    def _person(given: str, *surnames: str) -> Person:
        person = Person()
        name = Name()
        name.set_first_name(given)
        name.set_surname_list([])
        for text in surnames[:1]:
            surname = Surname()
            surname.set_surname(text)
            name.add_surname(surname)
        person.set_primary_name(name)
        for text in surnames[1:]:
            alt = Name()
            alt.set_first_name(given)
            surname = Surname()
            surname.set_surname(text)
            alt.add_surname(surname)
            person.add_alternate_name(alt)
        return person

    def test_surname_must_agree(self) -> None:
        self.assertFalse(
            relative_match_plausible(
                self._person("Joseph", "Baker"),
                None,
                self._person("Joseph", "Miller"),
                None,
            )
        )

    def test_sound_alike_surname_agrees(self) -> None:
        self.assertTrue(
            relative_match_plausible(
                self._person("Joseph", "Baker"),
                None,
                self._person("Joseph", "Backer"),
                None,
            )
        )

    def test_alternate_surname_agrees(self) -> None:
        """A mother recorded under her married name still matches her birth name."""
        self.assertTrue(
            relative_match_plausible(
                self._person("Ruth", "Hale"),
                None,
                self._person("Ruth", "Baker", "Hale"),
                None,
            )
        )

    def test_parent_age_problem(self) -> None:
        self.assertEqual(parent_age_problem(1728, 1753), "")
        self.assertEqual(parent_age_problem(1905, 1753), "too_young")
        self.assertEqual(parent_age_problem(1745, 1753), "too_young")
        self.assertEqual(parent_age_problem(1660, 1753), "too_old")
        self.assertEqual(parent_age_problem(0, 1753), "")


if __name__ == "__main__":
    unittest.main()
