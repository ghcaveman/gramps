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
Tests for leaving empty items out of the compare window and merge dialog:
empty birth/death events are passed over when choosing a person's birth or
death, and blank alternate names, attributes, addresses, web links and
notes are not compared.
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
from gramps.gen.gwizard.gwizard_base import is_empty_event, vital_event_ref
from gramps.gen.gwizard.gwizardgedcom import extra_items
from gramps.gen.lib import (
    Address,
    Attribute,
    AttributeType,
    Event,
    EventType,
    Name,
    Place,
    PlaceName,
    Url,
)
from gramps.gen.user import User

# Ann's first Birth is empty, her second is dated; her only Death is empty.
# Bob has a single, dated birth.
GED = (
    "0 HEAD\n1 CHAR UTF-8\n"
    "0 @I1@ INDI\n1 NAME Ann /Doe/\n1 SEX F\n"
    "1 BIRT\n"
    "1 BIRT\n2 DATE 1 JAN 1900\n2 PLAC Reno, NV\n"
    "1 DEAT\n"
    "0 @I2@ INDI\n1 NAME Bob /Doe/\n1 SEX M\n"
    "1 BIRT\n2 DATE 1901\n"
    "0 TRLR\n"
)


class GWizardEmptyItemsTest(unittest.TestCase):
    """Empty events and blank person items are left out."""

    def setUp(self) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write(GED)
        self._path = handle.name
        self.db: Any = import_as_dict(self._path, User())

    def tearDown(self) -> None:
        self.db.close()
        os.remove(self._path)

    def _person(self, first: str) -> Any:
        for person in self.db.iter_people():
            if person.get_primary_name().first_name == first:
                return person
        raise AssertionError("no person named %s" % first)

    def _event(self, ref: Any) -> Any:
        return self.db.get_event_from_handle(ref.ref)

    # ------------------------------------------------------------------
    # birth and death
    # ------------------------------------------------------------------
    def test_empty_primary_birth_gives_way_to_a_dated_one(self) -> None:
        """The Birth row shows the dated birth, not an empty one."""
        ann = self._person("Ann")
        # Make sure the person's own birth reference is the empty event.
        for ref in ann.get_event_ref_list():
            if is_empty_event(self._event(ref), self.db):
                if self._event(ref).get_type() == EventType.BIRTH:
                    ann.set_birth_ref(ref)
                    break
        self.assertTrue(is_empty_event(self._event(ann.get_birth_ref()), self.db))

        birth = self._event(vital_event_ref(self.db, ann, "birth"))

        self.assertEqual(birth.get_date_object().get_year(), 1900)

    def test_only_empty_death_is_still_returned(self) -> None:
        """With nothing better, the empty event is what there is."""
        ann = self._person("Ann")

        ref = vital_event_ref(self.db, ann, "death")

        self.assertIsNotNone(ref)
        self.assertTrue(is_empty_event(self._event(ref), self.db))

    def test_dated_birth_is_unchanged(self) -> None:
        """A person whose birth has data keeps it."""
        bob = self._person("Bob")

        self.assertEqual(vital_event_ref(self.db, bob, "birth"), bob.get_birth_ref())

    def test_place_with_blank_name_counts_as_no_place(self) -> None:
        """An event whose only data is a nameless place is empty."""
        place = Place()
        place.set_name(PlaceName(value="  "))
        event = Event()
        event.set_type(EventType.BURIAL)
        with DbTxn("blank place", self.db) as trans:
            self.db.add_place(place, trans)
            event.set_place_handle(place.handle)
            self.db.add_event(event, trans)

        self.assertTrue(is_empty_event(event, self.db))
        # Without the database the place cannot be checked, so it counts.
        self.assertFalse(is_empty_event(event))

    # ------------------------------------------------------------------
    # other details
    # ------------------------------------------------------------------
    def test_blank_items_are_not_compared(self) -> None:
        """Blank alternate names, attributes, addresses and links are dropped."""
        bob = self._person("Bob")
        blank_attribute = Attribute()
        blank_attribute.set_type(AttributeType.NICKNAME)
        blank_attribute.set_value("  ")
        bob.add_attribute(blank_attribute)
        real_attribute = Attribute()
        real_attribute.set_type(AttributeType.DESCRIPTION)
        real_attribute.set_value("Tall")
        bob.add_attribute(real_attribute)
        bob.add_address(Address())
        blank_url = Url()
        blank_url.set_path(" ")
        bob.add_url(blank_url)
        bob.add_alternate_name(Name())
        real_name = Name()
        real_name.set_first_name("Robert")
        bob.add_alternate_name(real_name)
        real_url = Url()
        real_url.set_path("https://example.org/bob")
        bob.add_url(real_url)

        attributes = [a.get_value() for _i, a in extra_items("attribute", bob, self.db)]
        self.assertEqual(attributes, ["Tall"])
        self.assertEqual(extra_items("address", bob, self.db), [])
        self.assertEqual(
            [u.get_path() for _i, u in extra_items("url", bob, self.db)],
            ["https://example.org/bob"],
        )
        names = extra_items("altname", bob, self.db)
        self.assertEqual([n.get_first_name() for _i, n in names], ["Robert"])
        # Indexes still point into the person's own lists.
        self.assertEqual(names[0][0], 1)


if __name__ == "__main__":
    unittest.main()
