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
Unit tests for the WikiTree API interface and GWizard WikiTree merge backend.
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
from unittest.mock import Mock, patch
from typing import Any

_RESOURCE_FILES = (
    ("data", "authors.xml"),
    ("images", "gramps.png"),
    ("COPYING",),
)


def _find_source_root() -> str | None:
    """Return a Gramps source checkout root holding the resources, or None."""
    candidates = [
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
        )
    ]
    try:
        import importlib.util

        spec = importlib.util.find_spec("gramps")
        for location in (spec.submodule_search_locations or []) if spec else []:
            candidates.append(os.path.dirname(os.path.abspath(location)))
    except (ImportError, ValueError):
        pass
    for candidate in candidates:
        if all(os.path.isfile(os.path.join(candidate, *f)) for f in _RESOURCE_FILES):
            return candidate
    return None


resource_path = os.environ.get("GRAMPS_RESOURCES")
if not resource_path or not os.path.exists(
    os.path.join(resource_path, "gramps", "authors.xml")
):
    ROOT_DIR = _find_source_root()
    if ROOT_DIR is not None:
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
    Name,
    Surname,
    Url,
    UrlType,
    Attribute,
    AttributeType,
    ChildRefType,
    Date,
)

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from ..gwizard_base import get_wikitree_id, extract_wikitree_id, is_wikitree_id
from ..gwizardwikitree import WikiTreeInterface, WikiTreeGWizard


# ------------------------------------------------------------
#
# TestWikiTreeInterface
#
# ------------------------------------------------------------
class TestWikiTreeInterface(unittest.TestCase):
    """Test suite for WikiTreeInterface API client."""

    def test_init_defaults(self) -> None:
        """Verify headers, base url, and default app_id."""
        client = WikiTreeInterface()
        self.assertEqual(client.base_url, "https://api.wikitree.com/api.php")
        self.assertEqual(client.app_id, "Gramps_GWizard_1.0")
        self.assertIn("Gramps_GWizard_1.0", client.headers["User-Agent"])

    @patch("requests.get")
    def test_get_person_success(self, mock_get: Mock) -> None:
        """Verify getPerson API query and response extraction."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "status": 0,
                "person": {
                    "Id": 388,
                    "Name": "Franklin-1",
                    "FirstName": "Benjamin",
                    "LastNameCurrent": "Franklin",
                },
            }
        ]
        mock_get.return_value = mock_resp

        client = WikiTreeInterface(app_id="TestApp")
        person = client.get_person("Franklin-1")

        self.assertIsNotNone(person)
        self.assertEqual(person["FirstName"], "Benjamin")
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["action"], "getPerson")
        self.assertEqual(kwargs["params"]["key"], "Franklin-1")
        self.assertEqual(kwargs["params"]["appId"], "TestApp")

    @patch("requests.get")
    def test_get_people_success(self, mock_get: Mock) -> None:
        """Verify getPeople API call with ancestors parameter."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "status": "",
                "people": {
                    "388": {"Id": 388, "Name": "Franklin-1"},
                    "389": {"Id": 389, "Name": "Franklin-2"},
                },
            }
        ]
        mock_get.return_value = mock_resp

        client = WikiTreeInterface()
        people = client.get_people(["Franklin-1"], ancestors=2)
        self.assertEqual(len(people), 2)
        self.assertIn("388", people)

    @patch("requests.get")
    def test_search_person_success(self, mock_get: Mock) -> None:
        """Verify searchPerson API parameter construction."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "status": 0,
                "matches": [{"Id": 101, "Name": "Franklin-101", "FirstName": "Ben"}],
            }
        ]
        mock_get.return_value = mock_resp

        client = WikiTreeInterface()
        matches = client.search_person(
            first_name="Ben",
            last_name="Franklin",
            birth_date="1706",
            death_date="1790",
            limit=50,
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["Name"], "Franklin-101")
        _, kwargs = mock_get.call_args
        sent_params = kwargs.get("params", {})
        self.assertEqual(sent_params.get("FirstName"), "Ben")
        self.assertEqual(sent_params.get("LastName"), "Franklin")
        self.assertEqual(sent_params.get("BirthDate"), "1706")
        self.assertEqual(sent_params.get("DeathDate"), "1790")
        self.assertEqual(sent_params.get("limit"), 50)

    @patch("requests.get")
    def test_get_bio_success(self, mock_get: Mock) -> None:
        """Verify getBio returns raw biography markdown text."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"bio": "== Biography ==\nTest biography text."}]
        mock_get.return_value = mock_resp

        client = WikiTreeInterface()
        bio = client.get_bio("Franklin-1")
        self.assertIn("Test biography text", bio)

    @patch("requests.get")
    def test_error_handling(self, mock_get: Mock) -> None:
        """Verify graceful error recovery when requests fail."""
        import requests

        mock_get.side_effect = requests.exceptions.RequestException("Network down")
        client = WikiTreeInterface()
        self.assertIsNone(client.get_person("Franklin-1"))
        self.assertEqual(client.get_people("Franklin-1"), {})
        self.assertEqual(client.search_person(last_name="Franklin"), [])
        self.assertEqual(client.get_bio("Franklin-1"), "")


# ------------------------------------------------------------
#
# TestWikiTreeGWizard
#
# ------------------------------------------------------------
class TestWikiTreeGWizard(unittest.TestCase):
    """Test suite for WikiTreeGWizard import and merge backend."""

    def setUp(self) -> None:
        """Set up an in-memory test database."""
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        """Close the test database."""
        self.db.close()

    def test_is_wikitree_id(self) -> None:
        """Verify identification of WikiTree ID format."""
        self.assertTrue(WikiTreeGWizard.is_wikitree_id("Franklin-1"))
        self.assertTrue(WikiTreeGWizard.is_wikitree_id("Ashley-1966"))
        self.assertFalse(WikiTreeGWizard.is_wikitree_id("Benjamin Franklin"))
        self.assertFalse(WikiTreeGWizard.is_wikitree_id("Franklin"))

    def test_clean_date_str(self) -> None:
        """Verify cleaning of incomplete WikiTree dates."""
        self.assertEqual(WikiTreeGWizard._clean_date_str("1706-01-17"), "1706-01-17")
        self.assertEqual(WikiTreeGWizard._clean_date_str("1706-00-00"), "1706")
        self.assertEqual(WikiTreeGWizard._clean_date_str("1706-05-00"), "1706-05")
        self.assertEqual(WikiTreeGWizard._clean_date_str("0000-00-00"), "")

    def test_parse_query_names(self) -> None:
        """Verify splitting query strings into first and last name."""
        fn, ln = WikiTreeGWizard._parse_query_names("Benjamin Franklin")
        self.assertEqual(fn, "Benjamin")
        self.assertEqual(ln, "Franklin")

        fn, ln = WikiTreeGWizard._parse_query_names("Franklin, Benjamin")
        self.assertEqual(fn, "Benjamin")
        self.assertEqual(ln, "Franklin")

        fn, ln = WikiTreeGWizard._parse_query_names("Lincoln")
        self.assertEqual(fn, "")
        self.assertEqual(ln, "Lincoln")

    def test_connect_validation(self) -> None:
        """Verify connect step checks required query or people_data arguments."""
        gw = WikiTreeGWizard(self.db)
        self.assertFalse(gw.run_step("connect"))
        self.assertTrue(gw.run_step("connect", query="Franklin-1"))
        self.assertEqual(gw.context["query"], "Franklin-1")

    def test_load_and_data_creation(self) -> None:
        """Verify WikiTree profile data is populated into source_db."""
        gw = WikiTreeGWizard(self.db)
        mock_person = {
            "Id": 388,
            "Name": "Franklin-1",
            "FirstName": "Benjamin",
            "MiddleName": "",
            "LastNameBirth": "Franklin",
            "LastNameCurrent": "Franklin",
            "BirthDate": "1706-01-17",
            "DeathDate": "1790-04-17",
            "BirthLocation": "Boston, Massachusetts",
            "DeathLocation": "Philadelphia, Pennsylvania",
            "Gender": "Male",
            "Bio": "Benjamin Franklin was an American polymath.",
            "PhotoData": {"path": "/photo.php/thumb/photo.jpg"},
        }

        gw.run_step("connect", query="Franklin-1", people_data=[mock_person])
        people = gw.run_step("load")
        self.assertEqual(len(people), 1)

        person = people[0]
        self.assertEqual(person.get_primary_name().get_name(), "Franklin, Benjamin")
        self.assertEqual(person.get_gender(), Person.MALE)

        # Verify WikiTree ID attribute and Web Home URL
        attrs = person.get_attribute_list()
        self.assertTrue(any(a.get_value() == "Franklin-1" for a in attrs))
        urls = person.get_url_list()
        self.assertTrue(any("Franklin-1" in u.get_path() for u in urls))
        self.assertEqual(get_wikitree_id(person), "Franklin-1")

        source_db = gw.context.get("source_db")
        self.assertIsNotNone(source_db)

        # Verify Source and Repository
        sources = list(source_db.iter_source_handles())
        self.assertEqual(len(sources), 1)
        src = source_db.get_source_from_handle(sources[0])
        self.assertIn("WikiTree", src.get_title())

        # Verify Citation and Media
        citations = list(source_db.iter_citation_handles())
        self.assertEqual(len(citations), 1)
        cit = source_db.get_citation_from_handle(citations[0])
        self.assertIn("Franklin-1", cit.get_page())
        self.assertEqual(len(cit.get_media_list()), 1)

        # Verify Events (Birth and Death with place handles)
        self.assertEqual(len(person.get_event_ref_list()), 2)
        b_ref = person.get_birth_ref()
        self.assertIsNotNone(b_ref)
        b_evt = source_db.get_event_from_handle(b_ref.ref)
        self.assertTrue(b_evt.get_place_handle())

        # Verify Biography Note
        notes = person.get_note_list()
        self.assertEqual(len(notes), 1)
        note = source_db.get_note_from_handle(notes[0])
        self.assertIn("American polymath", note.get())

    def test_family_relationship_linking(self) -> None:
        """Verify spouse information creates linked Family records."""
        gw = WikiTreeGWizard(self.db)
        husband = {
            "Id": 388,
            "Name": "Franklin-1",
            "FirstName": "Benjamin",
            "LastNameBirth": "Franklin",
            "LastNameCurrent": "Franklin",
            "Gender": "Male",
            "Spouses": [
                {
                    "Id": "394",
                    "Name": "Read-1",
                    "MarriageDate": "1730-09-01",
                    "MarriageLocation": "Philadelphia, Pennsylvania",
                }
            ],
        }
        wife = {
            "Id": 394,
            "Name": "Read-1",
            "FirstName": "Deborah",
            "LastNameBirth": "Read",
            "LastNameCurrent": "Franklin",
            "Gender": "Female",
            "Spouses": [],
        }

        gw.run_step("connect", query="Franklin-1", people_data=[husband, wife])
        people = gw.run_step("load")
        self.assertEqual(len(people), 2)

        source_db = gw.context.get("source_db")
        families = list(source_db.iter_family_handles())
        self.assertEqual(len(families), 1)

        fam = source_db.get_family_from_handle(families[0])
        self.assertTrue(fam.get_father_handle())
        self.assertTrue(fam.get_mother_handle())
        self.assertEqual(len(fam.get_event_ref_list()), 1)

    def test_match_compare_and_apply(self) -> None:
        """Verify match, compare, and apply steps against target DB."""
        target_p = Person()
        t_name = Name()
        t_name.set_first_name("Benjamin")
        t_surn = Surname()
        t_surn.set_surname("Franklin")
        t_name.add_surname(t_surn)
        target_p.set_primary_name(t_name)

        with DbTxn("Add target person", self.db) as trans:
            t_handle = self.db.add_person(target_p, trans)

        gw = WikiTreeGWizard(self.db)
        mock_person = {
            "Id": 388,
            "Name": "Franklin-1",
            "FirstName": "Benjamin",
            "LastNameBirth": "Franklin",
            "LastNameCurrent": "Franklin",
            "BirthDate": "1706-01-17",
            "DeathDate": "1790-04-17",
            "Gender": "Male",
        }

        gw.run_step("connect", query="Franklin-1", people_data=[mock_person])
        people = gw.run_step("load")
        s_handle = people[0].get_handle()

        # Step 3: Match
        matches = gw.run_step("match", source_person_handle=s_handle)
        self.assertTrue(len(matches) >= 1)
        self.assertEqual(matches[0]["handle"], t_handle)

        # Step 4: Compare
        rows = gw.run_step(
            "compare", source_person_handle=s_handle, target_person_handle=t_handle
        )
        self.assertTrue(len(rows) > 0)
        fields = [r.field for r in rows]
        self.assertIn("Given Name", fields)
        self.assertIn("Surname", fields)
        self.assertIn("Birth", fields)

        # Step 5: Apply
        success = gw.run_step(
            "apply",
            source_person_handle=s_handle,
            target_person_handle=t_handle,
            resolutions={
                "birth_event": "source",
                "death_event": "source",
                "person_sources": "source",
                "gender": "source",
            },
        )
        self.assertTrue(success)

        updated_p = self.db.get_person_from_handle(t_handle)
        self.assertEqual(updated_p.get_gender(), Person.MALE)
        self.assertIsNotNone(updated_p.get_birth_ref())
        self.assertIsNotNone(updated_p.get_death_ref())
        self.assertTrue(len(updated_p.get_citation_list()) >= 1)
        self.assertEqual(get_wikitree_id(updated_p), "Franklin-1")
        self.assertTrue(
            any("Franklin-1" in u.get_path() for u in updated_p.get_url_list())
        )

    def test_extract_and_get_wikitree_id(self) -> None:
        """Verify extract_wikitree_id and get_wikitree_id across various formats."""
        # Direct IDs
        self.assertEqual(extract_wikitree_id("Franklin-1"), "Franklin-1")
        self.assertEqual(extract_wikitree_id("Ashley-1966"), "Ashley-1966")
        self.assertEqual(extract_wikitree_id("Van_der_Linde-123"), "Van_der_Linde-123")
        self.assertEqual(extract_wikitree_id("Saint-Jean-42"), "Saint-Jean-42")

        # URLs
        self.assertEqual(
            extract_wikitree_id("https://www.wikitree.com/wiki/Washington-11"),
            "Washington-11",
        )
        self.assertEqual(
            extract_wikitree_id("http://wikitree.com/wiki/Washington-11"),
            "Washington-11",
        )
        self.assertEqual(
            extract_wikitree_id(
                "https://www.WikiTree.com/wiki/Washington-11#Biography"
            ),
            "Washington-11",
        )
        self.assertEqual(
            extract_wikitree_id(
                "https://www.wikitree.com/index.php?title=Washington-11"
            ),
            "Washington-11",
        )

        # Labels
        self.assertEqual(
            extract_wikitree_id("WikiTree: Washington-11"), "Washington-11"
        )
        self.assertEqual(
            extract_wikitree_id("WikiTree ID: Washington-11"), "Washington-11"
        )

        # Non-matching strings
        self.assertEqual(extract_wikitree_id(""), "")
        self.assertEqual(extract_wikitree_id(None), "")
        self.assertEqual(extract_wikitree_id("Benjamin Franklin"), "")
        self.assertEqual(extract_wikitree_id("https://example.com/test"), "")

        # get_wikitree_id from Person attribute
        p_attr = Person()
        attr = Attribute()
        attr.set_type(AttributeType("WikiTree ID"))
        attr.set_value("Lincoln-1")
        p_attr.add_attribute(attr)
        self.assertEqual(get_wikitree_id(p_attr), "Lincoln-1")

        # get_wikitree_id from Person Internet URL
        p_url = Person()
        url = Url()
        url.set_path("https://www.wikitree.com/wiki/Lincoln-2")
        url.set_type(UrlType(UrlType.WEB_HOME))
        p_url.add_url(url)
        self.assertEqual(get_wikitree_id(p_url), "Lincoln-2")

        # get_wikitree_id on empty or None person
        self.assertEqual(get_wikitree_id(Person()), "")
        self.assertEqual(get_wikitree_id(None), "")

    def test_apply_new_person_stores_wikitree_id_and_url(self) -> None:
        """Verify applying as a new person (target=None) preserves attribute and URL."""
        gw = WikiTreeGWizard(self.db)
        mock_person = {
            "Id": 100,
            "Name": "Adams-2",
            "FirstName": "John",
            "LastNameBirth": "Adams",
            "BirthDate": "1735-10-30",
            "Gender": "Male",
        }
        gw.run_step("connect", query="Adams-2", people_data=[mock_person])
        people = gw.run_step("load")
        s_handle = people[0].get_handle()

        success = gw.run_step(
            "apply",
            source_person_handle=s_handle,
            target_person_handle=None,
            resolutions={},
        )
        self.assertTrue(success)

        # Retrieve person added to target DB
        added_people = [
            self.db.get_person_from_handle(h) for h in self.db.iter_person_handles()
        ]
        self.assertEqual(len(added_people), 1)
        added_p = added_people[0]
        self.assertEqual(get_wikitree_id(added_p), "Adams-2")
        self.assertTrue(any("Adams-2" in u.get_path() for u in added_p.get_url_list()))
        self.assertTrue(
            any(a.get_value() == "Adams-2" for a in added_p.get_attribute_list())
        )

    def test_apply_explicit_wtid_resolution(self) -> None:
        """Verify applying wtid resolution stores both attribute and Internet URL."""
        target_p = Person()
        pname = Name()
        pname.set_first_name("George")
        surn = Surname()
        surn.set_surname("Washington")
        pname.add_surname(surn)
        target_p.set_primary_name(pname)

        with DbTxn("Add target", self.db) as trans:
            t_handle = self.db.add_person(target_p, trans)

        gw = WikiTreeGWizard(self.db)
        mock_person = {
            "Id": 1,
            "Name": "Washington-11",
            "FirstName": "George",
            "LastNameBirth": "Washington",
            "BirthDate": "1732-02-22",
            "Gender": "Male",
        }
        gw.run_step("connect", query="Washington-11", people_data=[mock_person])
        people = gw.run_step("load")
        s_handle = people[0].get_handle()

        success = gw.run_step(
            "apply",
            source_person_handle=s_handle,
            target_person_handle=t_handle,
            resolutions={"wtid": "source"},
        )
        self.assertTrue(success)

        updated = self.db.get_person_from_handle(t_handle)
        self.assertEqual(get_wikitree_id(updated), "Washington-11")
        # Ensure Attribute was created
        self.assertTrue(
            any(a.get_value() == "Washington-11" for a in updated.get_attribute_list())
        )
        # Ensure Internet Web Home URL was created
        self.assertTrue(
            any("Washington-11" in u.get_path() for u in updated.get_url_list())
        )

    def test_load_parent_child_relationships_and_confidence(self) -> None:
        """Verify father, mother, and child links with DNA confidence note."""
        gw = WikiTreeGWizard(self.db)
        mock_child = {
            "Id": 388,
            "Name": "Franklin-1",
            "FirstName": "Benjamin",
            "LastNameBirth": "Franklin",
            "Gender": "Male",
            "Father": 389,
            "Mother": 390,
            "DataStatus": {
                "Father": "20",  # DNA confirmed
                "Mother": "10",  # Confirmed with sources
            },
        }
        mock_father = {
            "Id": 389,
            "Name": "Franklin-2",
            "FirstName": "Josiah",
            "LastNameBirth": "Franklin",
            "Gender": "Male",
            "Spouses": [{"Id": 390, "Name": "Folger-1", "MarriageDate": "1689-11-25"}],
        }
        mock_mother = {
            "Id": 390,
            "Name": "Folger-1",
            "FirstName": "Abiah",
            "LastNameBirth": "Folger",
            "Gender": "Female",
        }

        gw.run_step(
            "connect",
            query="Franklin-1",
            people_data=[mock_child, mock_father, mock_mother],
        )
        people = gw.run_step("load")
        self.assertEqual(len(people), 3)

        source_db = gw.context.get("source_db")
        self.assertIsNotNone(source_db)
        self.assertEqual(source_db.get_number_of_families(), 1)

        fam_handle = list(source_db.iter_family_handles())[0]
        fam = source_db.get_family_from_handle(fam_handle)

        child_p = [p for p in people if get_wikitree_id(p) == "Franklin-1"][0]
        father_p = [p for p in people if get_wikitree_id(p) == "Franklin-2"][0]
        mother_p = [p for p in people if get_wikitree_id(p) == "Folger-1"][0]

        # Verify family parent handles
        self.assertEqual(fam.get_father_handle(), father_p.get_handle())
        self.assertEqual(fam.get_mother_handle(), mother_p.get_handle())

        # Verify child ref in family
        child_refs = fam.get_child_ref_list()
        self.assertEqual(len(child_refs), 1)
        cref = child_refs[0]
        self.assertEqual(cref.ref, child_p.get_handle())
        self.assertEqual(cref.get_father_relation(), ChildRefType.BIRTH)
        self.assertEqual(cref.get_mother_relation(), ChildRefType.BIRTH)

        # Verify DNA / source confirmation notes attached to ChildRef
        note_handles = cref.get_note_list()
        self.assertTrue(len(note_handles) >= 1)
        notes_text = " ".join(
            source_db.get_note_from_handle(nh).get() for nh in note_handles
        )
        self.assertIn("DNA", notes_text)
        self.assertIn("sources", notes_text)

        # Verify person parent/family references
        self.assertIn(fam.handle, child_p.get_parent_family_handle_list())
        self.assertIn(fam.handle, father_p.get_family_handle_list())
        self.assertIn(fam.handle, mother_p.get_family_handle_list())

    def test_load_adopted_and_stepchild_relations(self) -> None:
        """Verify non-biological and stepchild relationship status mapping."""
        gw = WikiTreeGWizard(self.db)
        mock_child = {
            "Id": 100,
            "Name": "Adopted-1",
            "FirstName": "Alex",
            "LastNameBirth": "Smith",
            "Gender": "Male",
            "Father": 101,
            "Mother": 102,
            "DataStatus": {
                "Father": "adopted",
                "Mother": "stepchild",
            },
        }
        mock_father = {
            "Id": 101,
            "Name": "Father-1",
            "FirstName": "John",
            "LastNameBirth": "Smith",
            "Gender": "Male",
        }
        mock_mother = {
            "Id": 102,
            "Name": "Mother-1",
            "FirstName": "Mary",
            "LastNameBirth": "Jones",
            "Gender": "Female",
        }

        gw.run_step(
            "connect",
            query="Adopted-1",
            people_data=[mock_child, mock_father, mock_mother],
        )
        gw.run_step("load")

        source_db = gw.context.get("source_db")
        fam_handle = list(source_db.iter_family_handles())[0]
        fam = source_db.get_family_from_handle(fam_handle)

        cref = fam.get_child_ref_list()[0]
        self.assertEqual(cref.get_father_relation(), ChildRefType.ADOPTED)
        self.assertEqual(cref.get_mother_relation(), ChildRefType.STEPCHILD)

    def test_load_nested_parents_and_children_dicts(self) -> None:
        """Verify automatic extraction of nested Parents and Children structures."""
        gw = WikiTreeGWizard(self.db)
        mock_child = {
            "Id": 10,
            "Name": "Child-1",
            "FirstName": "Junior",
            "LastNameBirth": "Doe",
            "Gender": "Male",
            "Parents": {
                "20": {
                    "Id": 20,
                    "Name": "Parent-1",
                    "FirstName": "Senior",
                    "LastNameBirth": "Doe",
                    "Gender": "Male",
                },
                "30": {
                    "Id": 30,
                    "Name": "Parent-2",
                    "FirstName": "Mother",
                    "LastNameBirth": "Smith",
                    "Gender": "Female",
                },
            },
            "Children": {
                "40": {
                    "Id": 40,
                    "Name": "Grandchild-1",
                    "FirstName": "Third",
                    "LastNameBirth": "Doe",
                    "Gender": "Female",
                }
            },
        }

        # Provide only the single mock_child profile - parents & children are nested
        gw.run_step("connect", query="Child-1", people_data=[mock_child])
        people = gw.run_step("load")
        self.assertEqual(len(people), 4)

        source_db = gw.context.get("source_db")
        self.assertEqual(source_db.get_number_of_people(), 4)
        # There should be two families: one for Senior+Mother with Junior as child,
        # and one for Junior with Grandchild-1 as child
        self.assertEqual(source_db.get_number_of_families(), 2)

    def test_wikitree_date_to_gramps(self) -> None:
        """Verify wikitree_date_to_gramps parses modifiers, qualities, and decades."""
        # Exact date with "certain"
        d1 = WikiTreeGWizard.wikitree_date_to_gramps("1706-01-17", "certain")
        self.assertEqual(d1.get_year(), 1706)
        self.assertEqual(d1.get_month(), 1)
        self.assertEqual(d1.get_day(), 17)
        self.assertEqual(d1.get_modifier(), Date.MOD_NONE)
        self.assertEqual(d1.get_quality(), Date.QUAL_NONE)

        # Incomplete year-only with "guess"
        d2 = WikiTreeGWizard.wikitree_date_to_gramps("1706-00-00", "guess")
        self.assertEqual(d2.get_year(), 1706)
        self.assertEqual(d2.get_month(), 0)
        self.assertEqual(d2.get_day(), 0)
        self.assertEqual(d2.get_modifier(), Date.MOD_ABOUT)
        self.assertEqual(d2.get_quality(), Date.QUAL_ESTIMATED)

        # Date with "before"
        d3 = WikiTreeGWizard.wikitree_date_to_gramps("1750-05-00", "before")
        self.assertEqual(d3.get_year(), 1750)
        self.assertEqual(d3.get_month(), 5)
        self.assertEqual(d3.get_day(), 0)
        self.assertEqual(d3.get_modifier(), Date.MOD_BEFORE)

        # Date with "after"
        d4 = WikiTreeGWizard.wikitree_date_to_gramps("1790-04-17", "after")
        self.assertEqual(d4.get_year(), 1790)
        self.assertEqual(d4.get_modifier(), Date.MOD_AFTER)

        # Empty date with decade fallback
        d5 = WikiTreeGWizard.wikitree_date_to_gramps("", None, "1700s")
        self.assertEqual(d5.get_modifier(), Date.MOD_RANGE)
        self.assertEqual(d5.get_quality(), Date.QUAL_ESTIMATED)
        self.assertEqual(d5.get_year(), 1700)
        self.assertEqual(d5.get_start_date(), (0, 0, 1700, False))
        self.assertEqual(d5.get_stop_date(), (0, 0, 1709, False))

        # 0000-00-00 without decade is empty
        d6 = WikiTreeGWizard.wikitree_date_to_gramps("0000-00-00")
        self.assertTrue(d6.is_empty())

    def test_load_date_certainty_and_modifiers(self) -> None:
        """Verify load step populates date modifiers on events from WikiTree status."""
        gw = WikiTreeGWizard(self.db)
        mock_person = {
            "Id": 1,
            "Name": "Franklin-1",
            "FirstName": "Benjamin",
            "LastNameBirth": "Franklin",
            "Gender": "Male",
            "BirthDate": "1706-00-00",
            "BirthDateStatus": "guess",
            "DeathDate": "1790-04-17",
            "DeathDateStatus": "after",
            "Spouses": [
                {
                    "Id": 2,
                    "Name": "Read-1",
                    "MarriageDate": "1730-09-01",
                    "MarriageDateStatus": "before",
                }
            ],
        }
        mock_spouse = {
            "Id": 2,
            "Name": "Read-1",
            "FirstName": "Deborah",
            "LastNameBirth": "Read",
            "Gender": "Female",
        }

        gw.run_step(
            "connect",
            query="Franklin-1",
            people_data=[mock_person, mock_spouse],
        )
        gw.run_step("load")

        source_db = gw.context.get("source_db")
        p = [
            source_db.get_person_from_handle(h)
            for h in source_db.iter_person_handles()
            if get_wikitree_id(source_db.get_person_from_handle(h)) == "Franklin-1"
        ][0]

        # Verify Birth Event has MOD_ABOUT and QUAL_ESTIMATED
        b_ref = p.get_birth_ref()
        self.assertIsNotNone(b_ref)
        b_evt = source_db.get_event_from_handle(b_ref.ref)
        b_date = b_evt.get_date_object()
        self.assertEqual(b_date.get_year(), 1706)
        self.assertEqual(b_date.get_modifier(), Date.MOD_ABOUT)
        self.assertEqual(b_date.get_quality(), Date.QUAL_ESTIMATED)

        # Verify Death Event has MOD_AFTER
        d_ref = p.get_death_ref()
        self.assertIsNotNone(d_ref)
        d_evt = source_db.get_event_from_handle(d_ref.ref)
        d_date = d_evt.get_date_object()
        self.assertEqual(d_date.get_year(), 1790)
        self.assertEqual(d_date.get_modifier(), Date.MOD_AFTER)

        # Verify Marriage Event has MOD_BEFORE
        fam_h = list(source_db.iter_family_handles())[0]
        fam = source_db.get_family_from_handle(fam_h)
        m_ref = fam.get_event_ref_list()[0]
        m_evt = source_db.get_event_from_handle(m_ref.ref)
        m_date = m_evt.get_date_object()
        self.assertEqual(m_date.get_year(), 1730)
        self.assertEqual(m_date.get_modifier(), Date.MOD_BEFORE)


if __name__ == "__main__":
    unittest.main()
