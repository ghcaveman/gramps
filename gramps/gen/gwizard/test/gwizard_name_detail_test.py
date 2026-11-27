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
Tests that merging a name never loses detail: the tree's fuller given name
or surname is kept, and a name that is replaced is kept as an "Also Known
As" name.
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
from gramps.gen.gwizard.gwizard_base import name_covers
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.lib import NameType
from gramps.gen.user import User

HEADER = "0 HEAD\n1 CHAR UTF-8\n"
TRLR = "0 TRLR\n"


def person_ged(name: str) -> str:
    """One person record; name is GEDCOM style ("Thomas Edward /Baker/")."""
    return HEADER + "0 @I1@ INDI\n1 NAME %s\n1 SEX M\n" % name + TRLR


class NameCoversTest(unittest.TestCase):
    """name_covers: does one name already hold everything in another?"""

    def test_covers(self) -> None:
        self.assertTrue(name_covers("Thomas Edward", "Thomas"))
        self.assertTrue(name_covers("Thomas Edward", "Thomas E."))
        self.assertTrue(name_covers("Thomas Edward", "Thomas E"))
        self.assertTrue(name_covers("Thomas Edward", "thomas edward"))
        self.assertTrue(name_covers("Thomas Edward", ""))

    def test_does_not_cover(self) -> None:
        self.assertFalse(name_covers("Thomas Edward", "Tom"))
        self.assertFalse(name_covers("Thomas", "Thomas Edward"))
        self.assertFalse(name_covers("Thomas Edward", "Edward Thomas"))
        self.assertFalse(name_covers("", "Thomas"))


class NameMergeTest(unittest.TestCase):
    """Merging the incoming name into the tree's Thomas Edward Baker."""

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

    def _merge(self, incoming: str, resolutions: dict[str, str]) -> Any:
        """Merge the incoming person's name; return the tree's person."""
        self.db = import_as_dict(
            self._write(person_ged("Thomas Edward /Baker/")), User()
        )
        self.gwizard = GedGWizard(self.db)
        self.gwizard.run_step("connect", gedcom_path=self._write(person_ged(incoming)))
        self.gwizard.run_step("load")
        source_db = self.gwizard.context["source_db"]
        (s_handle,) = list(source_db.iter_person_handles())
        (t_handle,) = list(self.db.iter_person_handles())
        self.assertTrue(
            self.gwizard.run_step(
                "apply",
                source_person_handle=s_handle,
                target_person_handle=t_handle,
                resolutions=resolutions,
            )
        )
        return self.db.get_person_from_handle(t_handle)

    @staticmethod
    def _names(person: Any) -> list[tuple[str, str, int]]:
        return [
            (n.get_first_name(), n.get_surname(), int(n.get_type()))
            for n in person.get_alternate_names()
        ]

    def test_shorter_given_name_keeps_the_middle_name(self) -> None:
        person = self._merge("Thomas /Baker/", {"given_name": "source"})
        self.assertEqual(person.get_primary_name().get_first_name(), "Thomas Edward")
        self.assertEqual(self._names(person), [])

    def test_initial_keeps_the_middle_name(self) -> None:
        person = self._merge("Thomas E. /Baker/", {"given_name": "source"})
        self.assertEqual(person.get_primary_name().get_first_name(), "Thomas Edward")

    def test_fuller_given_name_is_taken(self) -> None:
        person = self._merge("Thomas Edward Lee /Baker/", {"given_name": "source"})
        self.assertEqual(
            person.get_primary_name().get_first_name(), "Thomas Edward Lee"
        )
        # The old name is part of the new one, so it is not kept again.
        self.assertEqual(self._names(person), [])

    def test_different_given_name_keeps_the_old_one(self) -> None:
        person = self._merge("Tom /Baker/", {"given_name": "source"})
        self.assertEqual(person.get_primary_name().get_first_name(), "Tom")
        self.assertEqual(
            self._names(person), [("Thomas Edward", "Baker", NameType.AKA)]
        )

    def test_different_surname_keeps_the_old_one(self) -> None:
        person = self._merge("Thomas Edward /Bakker/", {"surname": "source"})
        self.assertEqual(person.get_primary_name().get_surname(), "Bakker")
        self.assertEqual(
            self._names(person), [("Thomas Edward", "Baker", NameType.AKA)]
        )


if __name__ == "__main__":
    unittest.main()
