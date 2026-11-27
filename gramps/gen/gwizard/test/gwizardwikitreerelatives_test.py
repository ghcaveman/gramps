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
Tests for WikiTree relatives: birth surnames (the API's LastNameAtBirth
field), spouses as the API returns them (an object keyed by Id), and a
merged person's wife linked to the wife already in the tree.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Date, Event, EventRef, EventType, Name, Person, Surname

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .. import gwizardwikitree
from ..gwizardwikitree import WikiTreeGWizard, relative_items


def _profiles(spouses: Any) -> list[dict[str, Any]]:
    """Thomas Baker, his wife Ann (born Smith) and their son William."""
    return [
        {
            "Id": 101,
            "Name": "Baker-101",
            "FirstName": "Thomas",
            "LastNameAtBirth": "Baker",
            "LastNameCurrent": "Baker",
            "Gender": "Male",
            "BirthDate": "1753-03-10",
            "Spouses": spouses,
        },
        {
            "Id": 102,
            "Name": "Smith-102",
            "FirstName": "Ann",
            "LastNameAtBirth": "Smith",
            "LastNameCurrent": "Baker",
            "Gender": "Female",
            "BirthDate": "1751-00-00",
        },
        {
            "Id": 103,
            "Name": "Baker-103",
            "FirstName": "William",
            "LastNameAtBirth": "Baker",
            "Gender": "Male",
            "BirthDate": "1791-08-02",
            "Father": 101,
            "Mother": 102,
        },
    ]


SPOUSES_BY_ID = {"102": {"Id": 102, "Name": "Smith-102", "MarriageDate": "1777-11-18"}}


class RelativeItemsTest(unittest.TestCase):
    """Parents, Children and Spouses in either shape."""

    def test_object_keyed_by_id(self) -> None:
        self.assertEqual(
            relative_items({"7": {"Name": "Doe-7"}}), [{"Name": "Doe-7", "Id": 7}]
        )

    def test_list_and_nothing(self) -> None:
        self.assertEqual(relative_items([{"Id": 7}, "x"]), [{"Id": 7}])
        self.assertEqual(relative_items(None), [])

    def test_requests_birth_surname_field(self) -> None:
        fields = gwizardwikitree._DEFAULT_FIELDS.split(",")
        self.assertIn("LastNameAtBirth", fields)
        self.assertNotIn("LastNameBirth", fields)


class _WikiTreeFixture(unittest.TestCase):
    """A tree with Thomas, Ann and William (no tests of its own)."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.handles = {}
        with DbTxn("setup", self.db) as trans:
            for given, surname, gender, year in (
                ("Thomas", "Baker", Person.MALE, 1753),
                ("Ann", "Smith", Person.FEMALE, 1751),
                ("William", "Baker", Person.MALE, 1791),
            ):
                birth = Event()
                birth.set_type(EventType(EventType.BIRTH))
                date = Date()
                date.set_yr_mon_day(year, 0, 0)
                birth.set_date_object(date)
                self.db.add_event(birth, trans)
                person = Person()
                name = Name()
                name.set_first_name(given)
                sur = Surname()
                sur.set_surname(surname)
                name.add_surname(sur)
                person.set_primary_name(name)
                person.set_gender(gender)
                ref = EventRef()
                ref.ref = birth.handle
                person.add_event_ref(ref)
                person.set_birth_ref(ref)
                self.db.add_person(person, trans)
                self.handles[given] = person.handle

    def tearDown(self) -> None:
        self.db.close()

    def _load(self, spouses: Any) -> tuple[WikiTreeGWizard, Any]:
        gw = WikiTreeGWizard(self.db)
        gw.run_step("connect", query="Baker-101", people_data=_profiles(spouses))
        gw.run_step("load")
        return gw, gw.context["source_db"]

    def _incoming(self, source_db: Any, given: str) -> Any:
        for person in source_db.iter_people():
            if person.get_primary_name().get_first_name() == given:
                return person
        raise AssertionError(given)


class WikiTreeWifeTest(_WikiTreeFixture):
    """The wife's birth surname, and linking her to the tree's wife."""

    def test_wife_has_her_birth_surname(self) -> None:
        _gw, source_db = self._load(SPOUSES_BY_ID)
        ann = self._incoming(source_db, "Ann")
        self.assertEqual(ann.get_primary_name().get_surname(), "Smith")
        married = [n.get_surname() for n in ann.get_alternate_names()]
        self.assertIn("Baker", married)

    def test_spouses_keyed_by_id_make_a_family(self) -> None:
        _gw, source_db = self._load(SPOUSES_BY_ID)
        thomas = self._incoming(source_db, "Thomas")
        (family_handle,) = thomas.get_family_handle_list()
        family = source_db.get_family_from_handle(family_handle)
        self.assertEqual(
            family.get_mother_handle(), self._incoming(source_db, "Ann").handle
        )

    def test_merge_links_the_trees_wife(self) -> None:
        gw, source_db = self._load(SPOUSES_BY_ID)
        self.assertTrue(
            gw.run_step(
                "apply",
                source_person_handle=self._incoming(source_db, "Thomas").handle,
                target_person_handle=self.handles["Thomas"],
                resolutions={"link_families": "source"},
            )
        )
        thomas = self.db.get_person_from_handle(self.handles["Thomas"])
        (family_handle,) = thomas.get_family_handle_list()
        family = self.db.get_family_from_handle(family_handle)
        self.assertEqual(family.get_mother_handle(), self.handles["Ann"])
        self.assertEqual(
            [ref.ref for ref in family.get_child_ref_list()], [self.handles["William"]]
        )


class WikiTreeAddedRelativesTest(_WikiTreeFixture):
    """Relatives the tree lacks, added as new people, with their photos."""

    def setUp(self) -> None:
        _WikiTreeFixture.setUp(self)
        # A tree with Thomas only.
        with DbTxn("trim", self.db) as trans:
            for given in ("Ann", "William"):
                self.db.remove_person(self.handles.pop(given), trans)

    def test_wife_and_son_are_added_and_their_photos_fetched(self) -> None:
        gw, source_db = self._load(SPOUSES_BY_ID)
        gw.context["download_media"] = True
        fetched: list[str] = []

        def fake_download(handle: str) -> dict[str, Any]:
            fetched.append(handle)
            return {"downloaded": 1, "failed": [], "no_base_path": 0}

        gw.download_person_media = fake_download  # type: ignore[method-assign]
        self.assertTrue(
            gw.run_step(
                "apply",
                source_person_handle=self._incoming(source_db, "Thomas").handle,
                target_person_handle=self.handles["Thomas"],
                resolutions={"link_families": "source"},
                add_missing_relatives=True,
            )
        )
        self.assertEqual(self.db.get_number_of_people(), 3)
        thomas = self.db.get_person_from_handle(self.handles["Thomas"])
        (family_handle,) = thomas.get_family_handle_list()
        family = self.db.get_family_from_handle(family_handle)
        ann = self.db.get_person_from_handle(family.get_mother_handle())
        self.assertEqual(ann.get_primary_name().get_surname(), "Smith")
        self.assertEqual(len(family.get_child_ref_list()), 1)
        added = gw.context["added_relatives"]
        self.assertEqual(len(added), 2)
        self.assertEqual(fetched, [self.handles["Thomas"]] + added)
        self.assertEqual(gw.context["media_download"]["downloaded"], 3)


if __name__ == "__main__":
    unittest.main()
