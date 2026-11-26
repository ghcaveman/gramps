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
Unit tests for date and place specificity comparisons and smart non-destructive merging.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
import shutil
import tempfile
import unittest

# -------------------------------------------------------------------------
#
# Test environment setup
#
# -------------------------------------------------------------------------
ROOT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)


def _ensure_test_resources():
    resource_path = os.environ.get("GRAMPS_RESOURCES")
    if resource_path and os.path.exists(
        os.path.join(resource_path, "gramps", "authors.xml")
    ):
        return resource_path

    build_share = os.path.join(ROOT_DIR, "build", "share")
    if os.path.exists(os.path.join(build_share, "gramps", "authors.xml")):
        return build_share

    resource_path = tempfile.mkdtemp(prefix="gramps-resources-")
    os.makedirs(os.path.join(resource_path, "gramps", "images"), exist_ok=True)
    os.makedirs(os.path.join(resource_path, "doc", "gramps"), exist_ok=True)
    os.makedirs(os.path.join(resource_path, "locale"), exist_ok=True)

    shutil.copyfile(
        os.path.join(ROOT_DIR, "data", "authors.xml"),
        os.path.join(resource_path, "gramps", "authors.xml"),
    )
    return resource_path


os.environ["GRAMPS_RESOURCES"] = _ensure_test_resources()
os.environ["HOME"] = os.environ.get("HOME") or tempfile.mkdtemp(prefix="gramps-home-")

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.gwizard.gwizard_base import (
    compare_date_specificity,
    compare_place_specificity,
    date_specificity_score,
    place_specificity_score,
)
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.lib import (
    Citation,
    Date,
    Event,
    EventRef,
    EventRoleType,
    EventType,
    Name,
    Person,
    Place,
    PlaceName,
    Source,
)


# ------------------------------------------------------------
#
# TestDateAndPlaceSpecificity
#
# ------------------------------------------------------------
class TestDateAndPlaceSpecificity(unittest.TestCase):
    """Test date and place specificity scoring and comparison."""

    def test_date_specificity_scoring(self):
        d_empty = Date()
        self.assertEqual(date_specificity_score(d_empty), 0.0)

        # Year only
        d_year = Date()
        d_year.set(value=(0, 0, 1877, 0))
        self.assertEqual(date_specificity_score(d_year), 2.0)

        # Month and Year
        d_month_year = Date()
        d_month_year.set(value=(0, 1, 1877, 0))
        self.assertEqual(date_specificity_score(d_month_year), 3.0)

        # Full day, month, year
        d_full = Date()
        d_full.set(value=(25, 1, 1877, 0))
        self.assertEqual(date_specificity_score(d_full), 4.0)

        # Imprecise date (about 1877)
        d_abt = Date()
        d_abt.set(value=(0, 0, 1877, 0), modifier=Date.MOD_ABOUT)
        self.assertEqual(date_specificity_score(d_abt), 1.5)

    def test_compare_date_specificity(self):
        d_full = Date()
        d_full.set(value=(25, 1, 1877, 0))

        d_year = Date()
        d_year.set(value=(0, 0, 1877, 0))

        d_empty = Date()

        # Full vs Year-only
        self.assertEqual(compare_date_specificity(d_full, d_year), 1)
        self.assertEqual(compare_date_specificity(d_year, d_full), -1)

        # Year-only vs Empty
        self.assertEqual(compare_date_specificity(d_year, d_empty), 1)
        self.assertEqual(compare_date_specificity(d_empty, d_year), -1)

        # Equal
        self.assertEqual(compare_date_specificity(d_year, d_year), 0)

    def test_place_specificity_scoring_and_comparison(self):
        p_empty = ""
        p_country = "Italy"
        p_detailed = "Belsito, Cosenza, Calabria, Italy"

        self.assertEqual(place_specificity_score(p_empty), 0.0)
        self.assertEqual(place_specificity_score(p_country), 1.0)
        self.assertEqual(place_specificity_score(p_detailed), 4.0)

        self.assertEqual(compare_place_specificity(p_detailed, p_country), 1)
        self.assertEqual(compare_place_specificity(p_country, p_detailed), -1)
        self.assertEqual(compare_place_specificity(p_country, p_country), 0)


# ------------------------------------------------------------
#
# TestSmartEventMerging
#
# ------------------------------------------------------------
class TestSmartEventMerging(unittest.TestCase):
    """Test non-destructive merging and alternate event creation in GedGWizard._apply."""

    def setUp(self):
        self.target_db = make_database("sqlite")
        self.target_db.load(":memory:")
        self.source_db = make_database("sqlite")
        self.source_db.load(":memory:")

    def tearDown(self):
        self.target_db.close()
        self.source_db.close()

    def test_smart_merge_preserves_more_specific_target_date(self):
        """Target with 25 JAN 1877 must not be overwritten by incoming 1877."""
        with DbTxn("Setup target", self.target_db) as trans:
            t_person = Person()
            t_name = Name()
            t_name.set_first_name("John")
            t_name.get_primary_surname().set_surname("Smith")
            t_person.set_primary_name(t_name)

            t_evt = Event()
            t_evt.set_type(EventType.BIRTH)
            d_full = Date()
            d_full.set(value=(25, 1, 1877, 0))
            t_evt.set_date_object(d_full)
            t_evt_h = self.target_db.add_event(t_evt, trans)

            b_ref = EventRef()
            b_ref.ref = t_evt_h
            b_ref.role = EventRoleType.PRIMARY
            t_person.set_birth_ref(b_ref)
            t_h = self.target_db.add_person(t_person, trans)

        with DbTxn("Setup source", self.source_db) as trans:
            s_person = Person()
            s_name = Name()
            s_name.set_first_name("John")
            s_name.get_primary_surname().set_surname("Smith")
            s_person.set_primary_name(s_name)

            s_evt = Event()
            s_evt.set_type(EventType.BIRTH)
            d_year = Date()
            d_year.set(value=(0, 0, 1877, 0))  # Less specific: year only
            s_evt.set_date_object(d_year)

            # Add source citation to verify citation preservation
            src = Source()
            src.set_title("1877 Birth Registry")
            src_h = self.source_db.add_source(src, trans)
            cit = Citation()
            cit.set_reference_handle(src_h)
            cit_h = self.source_db.add_citation(cit, trans)
            s_evt.add_citation(cit_h)

            s_evt_h = self.source_db.add_event(s_evt, trans)

            sb_ref = EventRef()
            sb_ref.ref = s_evt_h
            sb_ref.role = EventRoleType.PRIMARY
            s_person.set_birth_ref(sb_ref)
            s_h = self.source_db.add_person(s_person, trans)

        wizard = GedGWizard(self.target_db)
        wizard.context["source_db"] = self.source_db

        # Apply resolutions with birth_event = source
        applied = wizard._apply(
            source_person_handle=s_h,
            target_person_handle=t_h,
            resolutions={"birth_event": "source"},
        )
        self.assertTrue(applied)

        updated_p = self.target_db.get_person_from_handle(t_h)
        birth_evt = self.target_db.get_event_from_handle(updated_p.get_birth_ref().ref)

        # Date must remain 25 JAN 1877 (not downgraded to 1877)
        self.assertEqual(birth_evt.get_date_object().get_day(), 25)
        self.assertEqual(birth_evt.get_date_object().get_month(), 1)
        self.assertEqual(birth_evt.get_date_object().get_year(), 1877)

        # Citation from source must be copied to target event!
        self.assertEqual(len(birth_evt.get_citation_list()), 1)

    def test_smart_merge_upgrades_less_specific_target_date(self):
        """Target with 1877 is upgraded when incoming has 25 JAN 1877."""
        with DbTxn("Setup target", self.target_db) as trans:
            t_person = Person()
            t_name = Name()
            t_name.set_first_name("John")
            t_name.get_primary_surname().set_surname("Smith")
            t_person.set_primary_name(t_name)

            t_evt = Event()
            t_evt.set_type(EventType.BIRTH)
            d_year = Date()
            d_year.set(value=(0, 0, 1877, 0))  # Target has year only
            t_evt.set_date_object(d_year)
            t_evt_h = self.target_db.add_event(t_evt, trans)

            b_ref = EventRef()
            b_ref.ref = t_evt_h
            b_ref.role = EventRoleType.PRIMARY
            t_person.set_birth_ref(b_ref)
            t_h = self.target_db.add_person(t_person, trans)

        with DbTxn("Setup source", self.source_db) as trans:
            s_person = Person()
            s_name = Name()
            s_name.set_first_name("John")
            s_name.get_primary_surname().set_surname("Smith")
            s_person.set_primary_name(s_name)

            s_evt = Event()
            s_evt.set_type(EventType.BIRTH)
            d_full = Date()
            d_full.set(value=(25, 1, 1877, 0))  # Source has full date
            s_evt.set_date_object(d_full)
            s_evt_h = self.source_db.add_event(s_evt, trans)

            sb_ref = EventRef()
            sb_ref.ref = s_evt_h
            sb_ref.role = EventRoleType.PRIMARY
            s_person.set_birth_ref(sb_ref)
            s_h = self.source_db.add_person(s_person, trans)

        wizard = GedGWizard(self.target_db)
        wizard.context["source_db"] = self.source_db

        applied = wizard._apply(
            source_person_handle=s_h,
            target_person_handle=t_h,
            resolutions={"birth_event": "source"},
        )
        self.assertTrue(applied)

        updated_p = self.target_db.get_person_from_handle(t_h)
        birth_evt = self.target_db.get_event_from_handle(updated_p.get_birth_ref().ref)

        # Date must be upgraded to 25 JAN 1877
        self.assertEqual(birth_evt.get_date_object().get_day(), 25)
        self.assertEqual(birth_evt.get_date_object().get_month(), 1)
        self.assertEqual(birth_evt.get_date_object().get_year(), 1877)

    def test_alternate_event_resolution(self):
        """Resolution 'alternate' preserves target primary event and adds source as secondary."""
        with DbTxn("Setup target", self.target_db) as trans:
            t_person = Person()
            t_name = Name()
            t_name.set_first_name("Mary")
            t_name.get_primary_surname().set_surname("Jones")
            t_person.set_primary_name(t_name)

            t_evt = Event()
            t_evt.set_type(EventType.BIRTH)
            d1 = Date()
            d1.set(value=(10, 5, 1880, 0))
            t_evt.set_date_object(d1)
            t_evt_h = self.target_db.add_event(t_evt, trans)

            b_ref = EventRef()
            b_ref.ref = t_evt_h
            b_ref.role = EventRoleType.PRIMARY
            t_person.set_birth_ref(b_ref)
            t_h = self.target_db.add_person(t_person, trans)

        with DbTxn("Setup source", self.source_db) as trans:
            s_person = Person()
            s_name = Name()
            s_name.set_first_name("Mary")
            s_name.get_primary_surname().set_surname("Jones")
            s_person.set_primary_name(s_name)

            s_evt = Event()
            s_evt.set_type(EventType.BIRTH)
            d2 = Date()
            d2.set(value=(12, 5, 1882, 0))  # Conflicting birth date from census
            s_evt.set_date_object(d2)
            s_evt_h = self.source_db.add_event(s_evt, trans)

            sb_ref = EventRef()
            sb_ref.ref = s_evt_h
            sb_ref.role = EventRoleType.PRIMARY
            s_person.set_birth_ref(sb_ref)
            s_h = self.source_db.add_person(s_person, trans)

        wizard = GedGWizard(self.target_db)
        wizard.context["source_db"] = self.source_db

        applied = wizard._apply(
            source_person_handle=s_h,
            target_person_handle=t_h,
            resolutions={"birth_event": "alternate"},
        )
        self.assertTrue(applied)

        updated_p = self.target_db.get_person_from_handle(t_h)

        # Primary birth event remains 10 May 1880
        primary_birth = self.target_db.get_event_from_handle(
            updated_p.get_birth_ref().ref
        )
        self.assertEqual(primary_birth.get_date_object().get_year(), 1880)

        # In Gramps, get_event_ref_list() contains both primary and alternate events
        event_refs = updated_p.get_event_ref_list()
        self.assertEqual(len(event_refs), 2)  # Primary birth + Alternate birth

        # Find the alternate event ref
        primary_h = updated_p.get_birth_ref().ref
        alt_refs = [r for r in event_refs if r.ref != primary_h]
        self.assertEqual(len(alt_refs), 1)
        alt_birth = self.target_db.get_event_from_handle(alt_refs[0].ref)
        self.assertEqual(alt_birth.get_date_object().get_year(), 1882)

    def test_given_name_truncation_protection(self):
        """Target 'John Fitzgerald' is not truncated to 'John' by incoming data."""
        with DbTxn("Setup target", self.target_db) as trans:
            t_person = Person()
            t_name = Name()
            t_name.set_first_name("John Fitzgerald")
            t_name.get_primary_surname().set_surname("Kennedy")
            t_person.set_primary_name(t_name)
            t_h = self.target_db.add_person(t_person, trans)

        with DbTxn("Setup source", self.source_db) as trans:
            s_person = Person()
            s_name = Name()
            s_name.set_first_name("John")
            s_name.get_primary_surname().set_surname("Kennedy")
            s_person.set_primary_name(s_name)
            s_h = self.source_db.add_person(s_person, trans)

        wizard = GedGWizard(self.target_db)
        wizard.context["source_db"] = self.source_db

        applied = wizard._apply(
            source_person_handle=s_h,
            target_person_handle=t_h,
            resolutions={"given_name": "source"},
        )
        self.assertTrue(applied)

        updated_p = self.target_db.get_person_from_handle(t_h)
        # Middle name preserved!
        self.assertEqual(updated_p.get_primary_name().first_name, "John Fitzgerald")


if __name__ == "__main__":
    unittest.main()
