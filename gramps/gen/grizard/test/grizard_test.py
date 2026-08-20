#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Devin
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
Unit tests for the Grizard import framework and GEDCOM implementation.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import shutil
import tempfile
import unittest

# Set up test resources environment variables before importing any Gramps module
ROOT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
)
resource_path = os.environ.get("GRAMPS_RESOURCES")
if not resource_path or not os.path.exists(
    os.path.join(resource_path, "gramps", "authors.xml")
):
    resource_path = tempfile.mkdtemp(prefix="gramps-resources-")
    os.makedirs(os.path.join(resource_path, "gramps", "images"), exist_ok=True)
    os.makedirs(os.path.join(resource_path, "doc", "gramps"), exist_ok=True)
    os.makedirs(os.path.join(resource_path, "locale"), exist_ok=True)

    shutil.copyfile(
        os.path.join(ROOT_DIR, "data", "authors.xml"),
        os.path.join(resource_path, "gramps", "authors.xml"),
    )
    shutil.copyfile(
        os.path.join(ROOT_DIR, "images", "gramps.png"),
        os.path.join(resource_path, "gramps", "images", "gramps.png"),
    )
    shutil.copyfile(
        os.path.join(ROOT_DIR, "COPYING"),
        os.path.join(resource_path, "doc", "gramps", "COPYING"),
    )

os.environ["GRAMPS_RESOURCES"] = resource_path
os.environ["HOME"] = os.environ.get("HOME") or tempfile.mkdtemp(prefix="gramps-home-")

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import (
    Person,
    Event,
    Place,
    Surname,
    Name,
    Date,
    EventRef,
    EventType,
)
from gramps.gen.types import PersonHandle

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from ..grizard import GrizardCompareRow, CandidateMatcher
from ..gedcom import GedGrizard


# ------------------------------------------------------------
#
# GrizardTest
#
# ------------------------------------------------------------
class GrizardTest(unittest.TestCase):
    """
    Test cases for Grizard core framework, CandidateMatcher, and GedGrizard.
    """

    def setUp(self) -> None:
        """
        Set up the in-memory databases and test entities.
        """
        self.db = make_database("sqlite")
        self.db.load(":memory:")

        # Create basic target person in self.db
        with DbTxn("Add target person", self.db) as trans:
            self.target_person = Person()
            self.target_person.set_gender(Person.MALE)
            name = Name()
            name.first_name = "John"
            s1 = Surname()
            s1.set_surname("Doe")
            name.add_surname(s1)
            self.target_person.set_primary_name(name)
            self.db.add_person(self.target_person, trans)

            # Add Birth Event
            self.birth_event = Event()
            self.birth_event.set_type(EventType.BIRTH)
            d = Date()
            d.set_yr_mon_day(1980, 6, 15)
            self.birth_event.set_date_object(d)

            # Add Birth Place
            self.birth_place = Place()
            self.birth_place.set_title("Springfield")
            self.db.add_place(self.birth_place, trans)
            self.birth_event.set_place_handle(self.birth_place.handle)

            self.db.add_event(self.birth_event, trans)

            eref = EventRef()
            eref.ref = self.birth_event.handle
            self.target_person.set_birth_ref(eref)
            self.db.commit_person(self.target_person, trans)

    def tearDown(self) -> None:
        """
        Close the target database connection.
        """
        self.db.close()

    def test_candidate_matcher(self) -> None:
        """
        Verify that CandidateMatcher successfully matches similar records
        and flags gender mismatches.
        """
        matcher = CandidateMatcher(self.db)

        # Create matching person in memory
        source_person = Person()
        source_person.set_gender(Person.MALE)
        name = Name()
        name.first_name = "John"
        s1 = Surname()
        s1.set_surname("Doe")
        name.add_surname(s1)
        source_person.set_primary_name(name)

        # Exact gender & name match
        score = matcher.score_match(source_person, self.target_person)
        self.assertGreater(score, 1.0)

        # Gender mismatch
        source_person.set_gender(Person.FEMALE)
        score = matcher.score_match(source_person, self.target_person)
        self.assertEqual(score, -1.0)

    def test_ged_grizard_flow(self) -> None:
        """
        Test the end-to-end GedGrizard workflow sequence (connect, load, match, compare, apply).
        """
        # Create a simple valid minimal GEDCOM file
        gedcom_data = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME John /Doe/
2 GIVN John
2 SURN Doe
1 SEX M
1 BIRT
2 DATE 15 JUN 1980
2 PLAC Springfield
0 TRLR
"""
        with tempfile.NamedTemporaryFile(suffix=".ged", mode="w", delete=False) as f:
            f.write(gedcom_data)
            temp_path = f.name

        try:
            grizard = GedGrizard(self.db)

            # 1. Connect
            self.assertTrue(grizard.run_step("connect", gedcom_path=temp_path))

            # 2. Load
            people = grizard.run_step("load")
            self.assertEqual(len(people), 1)
            source_person = people[0]
            self.assertEqual(source_person.get_primary_name().first_name, "John")

            # 3. Match
            matches = grizard.run_step(
                "match", source_person_handle=source_person.handle
            )
            self.assertEqual(len(matches), 1)
            match = matches[0]
            self.assertEqual(match["handle"], self.target_person.handle)
            self.assertGreater(match["score"], 1.0)

            # 4. Compare
            comparison = grizard.run_step(
                "compare",
                source_person_handle=source_person.handle,
                target_person_handle=self.target_person.handle,
            )
            self.assertGreater(len(comparison), 0)

            given_name_row = [r for r in comparison if r.field_type == "given_name"][0]
            self.assertEqual(given_name_row.status, "match")
            self.assertEqual(given_name_row.source_val, "John")
            self.assertEqual(given_name_row.target_val, "John")

            # 5. Apply (Merge Overwrite given name with target, add birth)
            resolutions = {
                "given_name": "source",
                "surname": "target",
                "gender": "target",
                "birth_event": "source",
            }
            success = grizard.run_step(
                "apply",
                source_person_handle=source_person.handle,
                target_person_handle=self.target_person.handle,
                resolutions=resolutions,
            )
            self.assertTrue(success)

            # Verify target person has successfully updated primary details
            updated_person = self.db.get_person_from_handle(self.target_person.handle)
            self.assertEqual(updated_person.get_primary_name().first_name, "John")

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
