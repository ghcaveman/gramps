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
Unit tests for FamilySearch GWizard engine and provenance.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import MagicMock

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
    shutil.copyfile(
        os.path.join(ROOT_DIR, "images", "gramps.png"),
        os.path.join(resource_path, "gramps", "images", "gramps.png"),
    )
    shutil.copyfile(
        os.path.join(ROOT_DIR, "COPYING"),
        os.path.join(resource_path, "doc", "gramps", "COPYING"),
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
from gramps.gen.fs import utils as fs_utilities
from gramps.gen.fs.fs_import import deserializer as deserialize
from gramps.gen.fs.tree import Tree
from gramps.gen.gwizard.gwizardfamilysearch import (
    FamilySearchGWizard,
    FamilySearchInterface,
    extract_familysearch_id,
    get_familysearch_id,
    is_familysearch_id,
)
from gramps.gen.gwizard.gwizardfsprovenance import (
    ensure_provenance,
    normalize_fs_id,
    profile_url,
)
from gramps.gen.lib import Attribute, Name, Person


# ------------------------------------------------------------
#
# TestFamilySearchUtilities
#
# ------------------------------------------------------------
class TestFamilySearchUtilities(unittest.TestCase):
    """
    Tests for identifier extraction, validation, and URLs.
    """

    def test_is_familysearch_id(self):
        self.assertTrue(is_familysearch_id("GSVF-SGV"))
        self.assertTrue(is_familysearch_id("KWCR-123"))
        self.assertTrue(is_familysearch_id("kwcr-1234"))
        self.assertFalse(is_familysearch_id(""))
        self.assertFalse(is_familysearch_id(None))
        self.assertFalse(is_familysearch_id("John Doe"))
        self.assertFalse(is_familysearch_id("12345"))

    def test_extract_familysearch_id(self):
        self.assertEqual(extract_familysearch_id("GSVF-SGV"), "GSVF-SGV")
        self.assertEqual(extract_familysearch_id("id: kwcr-1234"), "KWCR-1234")
        url = "https://www.familysearch.org/tree/person/details/L123-ABC"
        self.assertEqual(extract_familysearch_id(url), "L123-ABC")
        platform_url = "https://api.familysearch.org/platform/tree/persons/M987-654"
        self.assertEqual(extract_familysearch_id(platform_url), "M987-654")
        self.assertEqual(extract_familysearch_id("no id here"), "")

    def test_get_familysearch_id_from_person(self):
        p = Person()
        self.assertEqual(get_familysearch_id(p), "")

        attr = Attribute()
        attr.set_type("_FSFTID")
        attr.set_value("GSVF-SGV")
        p.add_attribute(attr)
        self.assertEqual(get_familysearch_id(p), "GSVF-SGV")

    def test_normalize_fs_id_and_url(self):
        self.assertEqual(normalize_fs_id("gsvf-sgv"), "GSVF-SGV")
        self.assertEqual(
            profile_url("gsvf-sgv"),
            "https://www.familysearch.org/tree/person/details/GSVF-SGV",
        )
        with self.assertRaises(ValueError):
            normalize_fs_id("invalid-format")


# ------------------------------------------------------------
#
# TestFamilySearchProvenance
#
# ------------------------------------------------------------
class TestFamilySearchProvenance(unittest.TestCase):
    """
    Tests for FamilySearch repository, source, and citation provenance.
    """

    def setUp(self):
        self.db = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self):
        self.db.close()

    def test_ensure_provenance_creates_and_links(self):
        p = Person()
        name = Name()
        name.set_first_name("Thomas")
        name.get_primary_surname().set_surname("Lincoln")
        p.set_primary_name(name)

        with DbTxn("Add Person", self.db) as trans:
            self.db.add_person(p, trans)
            res = ensure_provenance(self.db, trans, p, "KWCR-987")

        self.assertTrue(res.changed)
        self.assertEqual(get_familysearch_id(p), "KWCR-987")
        self.assertEqual(len(p.get_url_list()), 1)
        self.assertEqual(
            p.get_url_list()[0].get_path(),
            "https://www.familysearch.org/tree/person/details/KWCR-987",
        )
        self.assertEqual(len(p.get_citation_list()), 1)

        # Idempotence: running again should not duplicate anything
        with DbTxn("Ensure again", self.db) as trans:
            res2 = ensure_provenance(self.db, trans, p, "KWCR-987")

        self.assertFalse(res2.changed)
        self.assertEqual(len(p.get_citation_list()), 1)
        self.assertEqual(len(p.get_url_list()), 1)


# ------------------------------------------------------------
#
# TestFamilySearchGWizardFlow
#
# ------------------------------------------------------------
class TestFamilySearchGWizardFlow(unittest.TestCase):
    """
    Tests for FamilySearchGWizard connect, load, match, and apply.
    """

    def setUp(self):
        self.db = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self):
        self.db.close()

    def _create_mock_tree(self, fsid="GSVF-SGV", name_str="Abraham Lincoln"):
        tree = Tree()
        fs_p = deserialize.Person()
        fs_p.id = fsid

        name = deserialize.Name()
        name_form = deserialize.NameForm()
        parts = name_str.split(" ", 1)
        p1 = deserialize.NamePart()
        p1.type = "http://gedcomx.org/Given"
        p1.value = parts[0]
        p2 = deserialize.NamePart()
        p2.type = "http://gedcomx.org/Surname"
        p2.value = parts[1] if len(parts) > 1 else ""
        name_form.parts = [p1, p2]
        name.nameForms = [name_form]
        name.preferred = True
        fs_p.names = [name]

        gender = deserialize.Gender()
        gender.type = "http://gedcomx.org/Male"
        fs_p.gender = gender

        # Add birth fact
        fact = deserialize.Fact()
        fact.type = "http://gedcomx.org/Birth"
        date_obj = deserialize.Date()
        date_obj.original = "12 February 1809"
        formal = types.SimpleNamespace()
        formal.start_date = types.SimpleNamespace(year=1809, month=2, day=12)
        formal.end_date = None
        formal.approximate = False
        formal.is_range = False
        date_obj.formal = formal
        fact.date = date_obj
        place_obj = deserialize.PlaceReference()
        place_obj.original = "Hodgenville, Kentucky"
        fact.place = place_obj
        fs_p.facts = [fact]

        deserialize.Person.index[fsid] = fs_p
        tree._persons[fsid] = fs_p
        return tree

    def test_connect_validation(self):
        wizard = FamilySearchGWizard(self.db)
        self.assertFalse(wizard._connect(query=""))
        self.assertTrue(wizard._connect(query="GSVF-SGV"))
        self.assertEqual(wizard.context["fsid"], "GSVF-SGV")

    def test_load_and_match_flow(self):
        fsid = "GSVF-SGV"
        mock_tree = self._create_mock_tree(fsid, "Abraham Lincoln")

        # Create target person in self.db
        target_p = Person()
        t_name = Name()
        t_name.set_first_name("Abraham")
        t_name.get_primary_surname().set_surname("Lincoln")
        target_p.set_primary_name(t_name)
        with DbTxn("Add target", self.db) as trans:
            self.db.add_person(target_p, trans)

        wizard = FamilySearchGWizard(self.db)
        self.assertTrue(wizard._connect(query=fsid, tree_data=mock_tree))

        loaded = wizard._load()
        self.assertEqual(len(loaded), 1)
        staged_person = loaded[0]
        self.assertEqual(get_familysearch_id(staged_person), fsid)

        # Match against self.db
        matches = wizard._match(source_person_handle=staged_person.handle)
        self.assertTrue(len(matches) > 0)
        top_match = matches[0]
        self.assertEqual(top_match["handle"], target_p.handle)

    def test_compare_and_apply_merge(self):
        fsid = "GSVF-SGV"
        mock_tree = self._create_mock_tree(fsid, "Abraham Lincoln")

        # Create target person in self.db with no birth event and no FSID
        target_p = Person()
        t_name = Name()
        t_name.set_first_name("Abraham")
        t_name.get_primary_surname().set_surname("Lincoln")
        target_p.set_primary_name(t_name)
        with DbTxn("Add target", self.db) as trans:
            self.db.add_person(target_p, trans)

        wizard = FamilySearchGWizard(self.db)
        wizard._connect(query=fsid, tree_data=mock_tree)
        wizard._load()

        staged_handle = wizard.source_db.get_person_handles()[0]

        # Apply merge resolutions
        resolutions = {
            "birth_event": "source",
            "fsid": "source",
        }
        success = wizard._apply(
            source_person_handle=staged_handle,
            target_person_handle=target_p.handle,
            resolutions=resolutions,
        )
        self.assertTrue(success)

        # Refresh target person and verify birth event and FSID
        updated_p = self.db.get_person_from_handle(target_p.handle)
        self.assertEqual(get_familysearch_id(updated_p), fsid)
        self.assertIsNotNone(updated_p.get_birth_ref())

        birth_evt = self.db.get_event_from_handle(
            updated_p.get_birth_ref().get_reference_handle()
        )
        self.assertEqual(birth_evt.get_date_object().get_year(), 1809)

    def test_apply_add_new_person(self):
        fsid = "GSVF-SGV"
        mock_tree = self._create_mock_tree(fsid, "Abraham Lincoln")

        wizard = FamilySearchGWizard(self.db)
        wizard._connect(query=fsid, tree_data=mock_tree)
        wizard._load()

        staged_handle = wizard.source_db.get_person_handles()[0]

        # Add as new person (target_person_handle=None)
        success = wizard._apply(
            source_person_handle=staged_handle,
            target_person_handle=None,
            resolutions={},
        )
        self.assertTrue(success)

        # Check self.db has one person with FSID and citation
        handles = self.db.get_person_handles()
        self.assertEqual(len(handles), 1)
        new_p = self.db.get_person_from_handle(handles[0])
        self.assertEqual(get_familysearch_id(new_p), fsid)
        self.assertEqual(len(new_p.get_citation_list()), 1)

    def test_interface_search_person(self):
        mock_session = MagicMock()
        mock_session.get_url.return_value = {
            "entries": [
                {
                    "content": {
                        "gedcomx": {
                            "persons": [
                                {
                                    "id": "GSVF-SGV",
                                    "display": {
                                        "name": "Abraham Lincoln",
                                        "lifespan": "1809-1865",
                                    },
                                }
                            ]
                        }
                    }
                }
            ]
        }
        client = FamilySearchInterface(session=mock_session)
        results = client.search_person(query="Abraham Lincoln")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["fsid"], "GSVF-SGV")
        self.assertEqual(results[0]["name"], "Abraham Lincoln")
        self.assertEqual(results[0]["life"], "1809-1865")

    def test_interface_is_authenticated(self):
        mock_session = MagicMock()
        mock_session.access_token = "valid_token"
        mock_session.connected = True
        mock_session.logged = True
        client = FamilySearchInterface(session=mock_session)
        self.assertTrue(client.is_authenticated())

        mock_session.access_token = None
        mock_session.connected = False
        mock_session.logged = False
        self.assertFalse(client.is_authenticated())


if __name__ == "__main__":
    unittest.main()
