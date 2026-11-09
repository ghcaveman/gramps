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
Unit tests for the NARA Catalog API interface and GWizard NARA merge backend.
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
from gramps.gen.lib import Person, Name, Surname

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from ..gwizardnaramerge import NaraCatalogInterface, NaraGWizard


# ------------------------------------------------------------
#
# TestNaraCatalogInterface
#
# ------------------------------------------------------------
class TestNaraCatalogInterface(unittest.TestCase):
    """Test suite for NaraCatalogInterface API client."""

    def test_init_defaults_and_api_key(self) -> None:
        """Verify headers and base url configuration."""
        client_no_key = NaraCatalogInterface()
        self.assertEqual(client_no_key.base_url, "https://catalog.archives.gov/api/v2")
        self.assertNotIn("x-api-key", client_no_key.headers)

        client_with_key = NaraCatalogInterface(api_key="secret123")
        self.assertEqual(client_with_key.headers.get("x-api-key"), "secret123")

    @patch("requests.get")
    def test_search_records_success(self, mock_get: Mock) -> None:
        """Verify search query parameter construction and successful response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "statusCode": 200,
            "body": {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_id": "1001",
                            "_source": {
                                "naId": "1001",
                                "record": {"title": "Sample Document"},
                            },
                        }
                    ],
                }
            },
        }
        mock_get.return_value = mock_response

        client = NaraCatalogInterface(api_key="key99")
        result = client.search_records(
            query="Civil War",
            rows=5,
            material_type="textual records",
            available_online=True,
        )

        self.assertIsNotNone(result)
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "https://catalog.archives.gov/api/v2/records/search")
        self.assertEqual(kwargs["params"]["q"], "Civil War")
        self.assertEqual(kwargs["params"]["limit"], 5)
        self.assertEqual(kwargs["params"]["typeOfMaterials"], "textual records")
        self.assertEqual(kwargs["params"]["availableOnline"], "true")

    @patch("requests.get")
    def test_search_records_error_handling(self, mock_get: Mock) -> None:
        """Verify graceful failure on HTTP error status or network exception."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_get.return_value = mock_response

        client = NaraCatalogInterface()
        self.assertIsNone(client.search_records(query="test"))

        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError("Connection lost")
        self.assertIsNone(client.search_records(query="test"))

    def test_extract_hits(self) -> None:
        """Verify hit extraction from standard and flat responses."""
        nested = {"body": {"hits": {"hits": [{"_id": "1"}, {"_id": "2"}]}}}
        self.assertEqual(len(NaraCatalogInterface.extract_hits(nested)), 2)

        flat = {"hits": [{"_id": "3"}]}
        self.assertEqual(len(NaraCatalogInterface.extract_hits(flat)), 1)

        self.assertEqual(NaraCatalogInterface.extract_hits({}), [])
        self.assertEqual(NaraCatalogInterface.extract_hits(None), [])

    def test_parse_record(self) -> None:
        """Verify normalization of raw NARA hit data."""
        hit = {
            "_id": "999",
            "_source": {
                "naId": "999",
                "record": {
                    "title": "Lincoln, Abraham - Pension Application",
                    "authors": {
                        "creator": [{"heading": "Lincoln, Abraham, 1809-1865"}]
                    },
                    "scopeAndContentNote": "Contains pension files.",
                    "typeOfMaterials": "textual records",
                    "dates": [{"startDate": "1861"}],
                    "digitalObjects": [
                        {
                            "objectUrl": "https://catalog.archives.gov/image.jpg",
                            "mimeType": "image/jpeg",
                        }
                    ],
                },
            },
        }

        parsed = NaraCatalogInterface.parse_record(hit)
        self.assertEqual(parsed["naid"], "999")
        self.assertEqual(parsed["title"], "Lincoln, Abraham - Pension Application")
        self.assertEqual(parsed["creators"], ["Lincoln, Abraham, 1809-1865"])
        self.assertEqual(parsed["scope_note"], "Contains pension files.")
        self.assertEqual(parsed["material_type"], "textual records")
        self.assertEqual(parsed["date_str"], "1861")
        self.assertEqual(parsed["web_url"], "https://catalog.archives.gov/id/999")
        self.assertEqual(len(parsed["digital_objects"]), 1)
        self.assertEqual(
            parsed["digital_objects"][0]["url"],
            "https://catalog.archives.gov/image.jpg",
        )


# ------------------------------------------------------------
#
# TestNaraGWizard
#
# ------------------------------------------------------------
class TestNaraGWizard(unittest.TestCase):
    """Test suite for NaraGWizard import and merge backend."""

    def setUp(self) -> None:
        """Set up an in-memory test database."""
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        """Close the test database."""
        self.db.close()

    def test_parse_person_name(self) -> None:
        """Verify parsing of various author and creator heading formats."""
        given, surn, b_yr, d_yr = NaraGWizard._parse_person_name(
            "Lincoln, Abraham, 1809-1865"
        )
        self.assertEqual(given, "Abraham")
        self.assertEqual(surn, "Lincoln")
        self.assertEqual(b_yr, "1809")
        self.assertEqual(d_yr, "1865")

        given, surn, b_yr, d_yr = NaraGWizard._parse_person_name("Washington, George")
        self.assertEqual(given, "George")
        self.assertEqual(surn, "Washington")
        self.assertEqual(b_yr, "")
        self.assertEqual(d_yr, "")

        given, surn, b_yr, d_yr = NaraGWizard._parse_person_name("John Adams")
        self.assertEqual(given, "John")
        self.assertEqual(surn, "Adams")

        given, surn, b_yr, d_yr = NaraGWizard._parse_person_name("Jefferson")
        self.assertEqual(given, "Jefferson")
        self.assertEqual(surn, "")

    def test_connect_validation(self) -> None:
        """Verify connect step checks required query or hits arguments."""
        gw = NaraGWizard(self.db)
        self.assertFalse(gw.run_step("connect"))
        self.assertTrue(gw.run_step("connect", query="Lincoln"))
        self.assertEqual(gw.context["query"], "Lincoln")

    def test_load_and_data_creation(self) -> None:
        """Verify NARA records are populated into in-memory source_db."""
        gw = NaraGWizard(self.db)
        mock_hits = [
            {
                "_id": "54321",
                "_source": {
                    "naId": "54321",
                    "record": {
                        "title": "Abraham Lincoln Military Papers",
                        "scopeAndContentNote": "Official papers and orders.",
                        "authors": {
                            "creator": [{"heading": "Lincoln, Abraham, 1809-1865"}]
                        },
                        "digitalObjects": [
                            {
                                "objectUrl": "https://catalog.archives.gov/doc1.png",
                                "objectType": "image/png",
                            }
                        ],
                    },
                },
            }
        ]

        gw.run_step("connect", query="Abraham Lincoln", hits=mock_hits)
        people = gw.run_step("load")
        self.assertEqual(len(people), 1)

        person = people[0]
        self.assertEqual(person.get_primary_name().get_name(), "Lincoln, Abraham")

        source_db = gw.context.get("source_db")
        self.assertIsNotNone(source_db)

        # Check repository and source creation
        sources = list(source_db.iter_source_handles())
        self.assertEqual(len(sources), 1)
        source = source_db.get_source_from_handle(sources[0])
        self.assertIn("Abraham Lincoln", source.get_title())

        # Check citation creation
        citations = list(source_db.iter_citation_handles())
        self.assertEqual(len(citations), 1)
        cit = source_db.get_citation_from_handle(citations[0])
        self.assertIn("54321", cit.get_page())
        self.assertEqual(len(cit.get_media_list()), 1)

        # Check events (Birth and Death)
        self.assertEqual(len(person.get_event_ref_list()), 2)

    def test_compare_and_apply_merge(self) -> None:
        """Verify comparing and applying NARA merge to existing target person."""
        target_p = Person()
        t_name = Name()
        t_name.set_first_name("Abraham")
        t_surn = Surname()
        t_surn.set_surname("Lincoln")
        t_name.add_surname(t_surn)
        target_p.set_primary_name(t_name)

        with DbTxn("Add target person", self.db) as trans:
            t_handle = self.db.add_person(target_p, trans)

        gw = NaraGWizard(self.db)
        mock_hits = [
            {
                "_id": "111",
                "_source": {
                    "naId": "111",
                    "record": {
                        "title": "Lincoln, Abraham - Orders",
                        "authors": {
                            "creator": [{"heading": "Lincoln, Abraham, 1809-1865"}]
                        },
                    },
                },
            }
        ]
        gw.run_step("connect", query="Abraham Lincoln", hits=mock_hits)
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

        # Step 5: Apply merge
        success = gw.run_step(
            "apply",
            source_person_handle=s_handle,
            target_person_handle=t_handle,
            resolutions={
                "person_sources": "source",
                "birth_event": "source",
                "death_event": "source",
            },
        )
        self.assertTrue(success)

        updated_p = self.db.get_person_from_handle(t_handle)
        self.assertTrue(len(updated_p.get_citation_list()) >= 1)
        self.assertIsNotNone(updated_p.get_birth_ref())


if __name__ == "__main__":
    unittest.main()
