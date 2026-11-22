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
import json
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
from gramps.gen.utils.file import media_path

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from ..gwizardnaramerge import (
    IMAGE_IN_TREE,
    IMAGE_LINKED,
    IMAGE_NEW,
    NAID_ATTRIBUTE,
    NARA_REPOSITORY_NAME,
    OBJECT_ID_ATTRIBUTE,
    NaraCatalogInterface,
    NaraGWizard,
    NaraRecordAttacher,
)

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _load_sample(name: str) -> dict[str, Any]:
    """
    Load a NARA Catalog API v2 response saved in the test data folder.

    nara_record_naturalization.json (NAID 90361620) and
    nara_search_pension.json ("john smith pension") are real responses,
    trimmed to two hits and two digital objects each, with the archives'
    contact details removed.
    """
    with open(os.path.join(_DATA_DIR, name), encoding="utf-8") as sample:
        return json.load(sample)


# ------------------------------------------------------------
#
# TestNaraCatalogInterface
#
# ------------------------------------------------------------
class TestNaraCatalogInterface(unittest.TestCase):
    """Test suite for NaraCatalogInterface API client."""

    def test_init_defaults_and_api_key(self) -> None:
        """Verify headers and base url configuration."""
        with patch.dict(os.environ, {}, clear=True):
            client_no_key = NaraCatalogInterface()
        self.assertEqual(client_no_key.base_url, "https://catalog.archives.gov/api/v2")
        self.assertNotIn("x-api-key", client_no_key.headers)

        client_with_key = NaraCatalogInterface(api_key="secret123")
        self.assertEqual(client_with_key.headers.get("x-api-key"), "secret123")

        with patch.dict(os.environ, {"NARA_API_KEY": "environment_key"}):
            client_from_environment = NaraCatalogInterface()
        self.assertEqual(
            client_from_environment.headers.get("x-api-key"), "environment_key"
        )

    @patch("requests.get")
    def test_validate_api_key(self, mock_get: Mock) -> None:
        """Check valid and rejected keys through the catalog search endpoint."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"body": {"hits": {"hits": []}}}
        mock_get.return_value = response

        client = NaraCatalogInterface(api_key="secret123")
        self.assertIsNone(client.validate_api_key())
        kwargs = mock_get.call_args.kwargs
        self.assertEqual(kwargs["params"], {"q": "constitution", "limit": 1})
        self.assertEqual(kwargs["headers"]["x-api-key"], "secret123")

        response.json.return_value = {"statusCode": 403}
        self.assertIn("rejected", client.validate_api_key() or "")

        response.json.return_value = {"statusCode": 200}
        response.status_code = 403
        self.assertIn("rejected", client.validate_api_key() or "")

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
    def test_search_records_record_years(self, mock_get: Mock) -> None:
        """Verify record years are sent as startDate/endDate only when set."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"body": {"hits": {"hits": []}}}
        mock_get.return_value = mock_response
        client = NaraCatalogInterface(api_key="key99")

        client.search_records(query="Smith", start_year="1840", end_year="1935")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["startDate"], "1840")
        self.assertEqual(params["endDate"], "1935")

        client.search_records(query="Smith")
        params = mock_get.call_args.kwargs["params"]
        self.assertNotIn("startDate", params)
        self.assertNotIn("endDate", params)

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
                    "creators": [
                        {
                            "heading": "Lincoln, Abraham, 1809-1865",
                            "authorityType": "person",
                        }
                    ],
                    "scopeAndContentNote": "Contains pension files.",
                    "generalRecordsTypes": ["Textual Records"],
                    "inclusiveStartDate": {"year": 1861, "logicalDate": "1861-01-01"},
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
        self.assertEqual(parsed["person_creators"], ["Lincoln, Abraham, 1809-1865"])
        self.assertEqual(parsed["scope_note"], "Contains pension files.")
        self.assertEqual(parsed["material_type"], "Textual Records")
        self.assertEqual(parsed["date_str"], "1861")
        self.assertEqual(parsed["web_url"], "https://catalog.archives.gov/id/999")
        self.assertEqual(len(parsed["digital_objects"]), 1)
        self.assertEqual(
            parsed["digital_objects"][0]["url"],
            "https://catalog.archives.gov/image.jpg",
        )

    def test_is_person_creator_headings(self) -> None:
        """Verify personal-name headings are told apart from agency headings."""
        people = [
            "Lincoln, Abraham, 1809-1865",
            "Washington, George",
            "Smith, John, Jr., 1900-",
            "Smith, J. R.",
            "O'Brien, Mary-Kate",
            "House, Edward M. (Edward Mandell), 1858-1938",
            "Church, Frederic Edwin, b. 1826",
            "John Adams",
        ]
        agencies = [
            "Department of Veterans Affairs",
            "Department of Veterans Affairs. 1989-",
            "United States. War Department.",
            "United States. Army. Corps of Engineers. Missouri River Division, 1937-",
            "Bureau of Pensions, 1833-1930",
            "Office of the Secretary, War",
            "Veterans Administration",
            "Library of Congress",
            "U.S. Army",
            "Peace Corps",
            "Jefferson",
            "",
        ]
        for heading in people:
            self.assertTrue(
                NaraCatalogInterface.is_person_creator({}, heading), heading
            )
        for heading in agencies:
            self.assertFalse(
                NaraCatalogInterface.is_person_creator({}, heading), heading
            )

    def test_is_person_creator_type_field_wins(self) -> None:
        """Verify a person/organization type on the creator overrides the heading."""
        self.assertFalse(
            NaraCatalogInterface.is_person_creator(
                {"authorityType": "organization"}, "Smith, John"
            )
        )
        self.assertTrue(
            NaraCatalogInterface.is_person_creator(
                {"authorityType": "Person"}, "Peace Corps"
            )
        )
        self.assertTrue(
            NaraCatalogInterface.is_person_creator("Smith, John", "Smith, John")
        )

    def test_parse_record_separates_person_creators(self) -> None:
        """Verify agency creators stay in 'creators' but not 'person_creators'."""
        hit = {
            "_source": {
                "naId": "777",
                "record": {
                    "title": "Pension File of John Smith",
                    "creators": [
                        {
                            "heading": "Department of Veterans Affairs. 1989-",
                            "authorityType": "organization",
                        },
                        {
                            "heading": "Smith, John, 1840-1910",
                            "authorityType": "person",
                        },
                    ],
                },
            }
        }
        parsed = NaraCatalogInterface.parse_record(hit)
        self.assertEqual(
            parsed["creators"],
            ["Department of Veterans Affairs. 1989-", "Smith, John, 1840-1910"],
        )
        self.assertEqual(parsed["person_creators"], ["Smith, John, 1840-1910"])

    def test_parse_real_naturalization_record(self) -> None:
        """Verify parsing of a real file unit whose creators are on its series."""
        hits = NaraCatalogInterface.extract_hits(
            _load_sample("nara_record_naturalization.json")
        )
        self.assertEqual(len(hits), 1)

        parsed = NaraCatalogInterface.parse_record(hits[0])
        self.assertEqual(parsed["naid"], "90361620")
        self.assertEqual(parsed["title"], "MacDonald, Lyman Angus - 1942")
        self.assertEqual(parsed["level"], "fileUnit")
        self.assertEqual(
            parsed["creators"], ["California. Superior Court (San Diego County)"]
        )
        self.assertEqual(parsed["creators_from"], "series")
        self.assertEqual(parsed["person_creators"], [])
        self.assertEqual(parsed["date_str"], "1929-1956")
        self.assertEqual(parsed["date_from"], "series")
        self.assertEqual(parsed["material_type"], "Textual Records")
        self.assertEqual(len(parsed["digital_objects"]), 2)
        self.assertEqual(parsed["digital_objects"][0]["mime_type"], "image/jpeg")
        self.assertTrue(
            parsed["digital_objects"][0]["url"].endswith("/images/2480.jpg")
        )
        self.assertEqual(
            parsed["digital_objects"][0]["description"], "Image provided by Fold3."
        )

    def test_parse_real_pension_search(self) -> None:
        """Verify real pension file units take the nearest ancestor's creators."""
        hits = NaraCatalogInterface.extract_hits(
            _load_sample("nara_search_pension.json")
        )
        self.assertEqual(len(hits), 2)
        for hit in hits:
            parsed = NaraCatalogInterface.parse_record(hit)
            self.assertIn("Approved Pension Application File for", parsed["title"])
            self.assertEqual(parsed["person_creators"], [])
            self.assertEqual(
                parsed["creators"],
                [
                    "Veterans Administration. (7/21/1930 - 3/15/1989)",
                    "Department of the Interior. Bureau of Pensions. 1849-1930",
                ],
            )
            self.assertEqual(parsed["creators_from"], "series")
            self.assertEqual(parsed["date_str"], "1861-1934")
            self.assertEqual(parsed["material_type"], "Textual Records")
            self.assertEqual(len(parsed["digital_objects"]), 2)

    def test_parse_record_own_dates_win(self) -> None:
        """Verify a record's own dates are used before its ancestors'."""
        hit = {
            "_source": {
                "record": {
                    "naId": 5,
                    "coverageStartDate": {"year": 1918, "logicalDate": "1918-01-01"},
                    "ancestors": [
                        {
                            "distance": 1,
                            "levelOfDescription": "series",
                            "inclusiveStartDate": {"year": 1900},
                            "inclusiveEndDate": {"year": 1950},
                        }
                    ],
                }
            }
        }
        parsed = NaraCatalogInterface.parse_record(hit)
        self.assertEqual(parsed["naid"], "5")
        self.assertEqual(parsed["date_str"], "1918")
        self.assertEqual(parsed["date_from"], "")


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
                        "creators": [
                            {
                                "heading": "Lincoln, Abraham, 1809-1865",
                                "authorityType": "person",
                            }
                        ],
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
        assert source_db is not None

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

    def test_load_skips_agency_creators(self) -> None:
        """Verify only the person creator of a mixed record becomes a person."""
        gw = NaraGWizard(self.db)
        hits = [
            {
                "_source": {
                    "naId": "888",
                    "record": {
                        "title": "Pension File of John Smith",
                        "creators": [
                            {
                                "heading": "Department of Veterans Affairs",
                                "authorityType": "organization",
                            },
                            {
                                "heading": "Smith, John, 1840-1910",
                                "authorityType": "person",
                            },
                        ],
                    },
                }
            }
        ]
        gw.run_step("connect", query="John Smith", hits=hits)
        people = gw.run_step("load")

        self.assertEqual(len(people), 1)
        self.assertEqual(people[0].get_primary_name().get_name(), "Smith, John")
        source_db = gw.context["source_db"]
        self.assertEqual(source_db.get_number_of_people(), 1)
        source = source_db.get_source_from_handle(
            next(iter(source_db.iter_source_handles()))
        )
        self.assertIn("Department of Veterans Affairs", source.get_author())

    def test_load_agency_only_record_raises(self) -> None:
        """Verify a record created only by agencies makes no fake people."""
        gw = NaraGWizard(self.db)
        hits = [
            {
                "_source": {
                    "naId": "889",
                    "record": {
                        "title": "Civil War Pension Index",
                        "creators": [
                            {
                                "heading": "United States. Bureau of Pensions.",
                                "authorityType": "organization",
                            },
                            {
                                "heading": "Veterans Administration",
                                "authorityType": "organization",
                            },
                        ],
                    },
                }
            }
        ]
        gw.run_step("connect", query="pension", hits=hits)
        with self.assertRaises(RuntimeError) as ctx:
            gw.run_step("load")
        self.assertIn("names no person", str(ctx.exception))

    def test_load_real_record_without_person_raises(self) -> None:
        """Verify the real naturalization record makes no person."""
        gw = NaraGWizard(self.db)
        hits = NaraCatalogInterface.extract_hits(
            _load_sample("nara_record_naturalization.json")
        )
        gw.run_step("connect", query="90361620", hits=hits)
        with self.assertRaises(RuntimeError) as ctx:
            gw.run_step("load")
        self.assertIn("names no person", str(ctx.exception))

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
                        "creators": [
                            {
                                "heading": "Lincoln, Abraham, 1809-1865",
                                "authorityType": "person",
                            }
                        ],
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


# ------------------------------------------------------------
#
# TestNaraRecordAttacher
#
# ------------------------------------------------------------
class _FakeReply:
    """A requests-style reply with fixed content."""

    def __init__(self, status_code: int = 200, content: bytes = b"jpegdata") -> None:
        self.status_code = status_code
        self.content = content

    def iter_content(self, chunk_size: int = 65536):
        """Yield the content in one chunk."""
        yield self.content


class TestNaraRecordAttacher(unittest.TestCase):
    """Test attaching real NARA records to an existing person."""

    def setUp(self) -> None:
        """Set up a family tree with one person and a temporary media folder."""
        self.media_dir = tempfile.mkdtemp(prefix="nara-media-")
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.db.set_mediapath(self.media_dir)
        person = Person()
        name = Name()
        name.set_first_name("Lyman Angus")
        surname = Surname()
        surname.set_surname("MacDonald")
        name.add_surname(surname)
        person.set_primary_name(name)
        with DbTxn("Add person", self.db) as trans:
            self.person_handle = self.db.add_person(person, trans)
        hits = NaraCatalogInterface.extract_hits(
            _load_sample("nara_record_naturalization.json")
        )
        self.parsed = NaraCatalogInterface.parse_record(hits[0])
        self.session = Mock()
        self.session.get.return_value = _FakeReply()

    def tearDown(self) -> None:
        """Close the tree and remove the media folder."""
        self.db.close()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def test_parse_record_series(self) -> None:
        """Verify the series title and NAID are taken from the ancestors."""
        self.assertEqual(self.parsed["series_title"], "Index to Naturalization Records")
        self.assertEqual(self.parsed["series_naid"], "7551473")

    def test_attach_with_downloads(self) -> None:
        """Verify repository, source, citation and downloaded media are created."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        result = attacher.attach(self.person_handle, self.parsed)

        self.assertTrue(result.repository_created)
        self.assertTrue(result.source_created)
        self.assertTrue(result.citation_created)
        self.assertTrue(result.person_linked)
        self.assertEqual(result.downloaded, 2)
        self.assertEqual(result.media_added, 2)
        self.assertEqual(result.failed, [])

        repositories = list(self.db.iter_repositories())
        self.assertEqual([r.get_name() for r in repositories], [NARA_REPOSITORY_NAME])
        sources = list(self.db.iter_sources())
        self.assertEqual(sources[0].get_title(), "Index to Naturalization Records")
        self.assertEqual(
            sources[0].get_reporef_list()[0].get_call_number(), "NAID 7551473"
        )

        citation = self.db.get_citation_from_handle(result.citation_handle)
        self.assertEqual(
            citation.get_page(), "MacDonald, Lyman Angus - 1942 (NAID 90361620)"
        )
        note = self.db.get_note_from_handle(citation.get_note_list()[0])
        self.assertIn("https://catalog.archives.gov/id/90361620", note.get())

        person = self.db.get_person_from_handle(self.person_handle)
        self.assertIn(result.citation_handle, person.get_citation_list())

        media = [
            self.db.get_media_from_handle(r.ref) for r in citation.get_media_list()
        ]
        paths = sorted(m.get_path() for m in media)
        self.assertEqual(
            paths,
            [
                os.path.join("NARA", "90361620", "2480.jpg"),
                os.path.join("NARA", "90361620", "2481.jpg"),
            ],
        )
        for item in media:
            self.assertEqual(item.get_mime_type(), "image/jpeg")
            self.assertTrue(item.get_checksum())
            self.assertTrue(
                os.path.isfile(os.path.join(media_path(self.db), item.get_path()))
            )

    def test_attach_twice_reuses_everything(self) -> None:
        """Verify attaching the same record again adds nothing new."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        first = attacher.attach(self.person_handle, self.parsed)
        second = attacher.attach(self.person_handle, self.parsed)

        self.assertEqual(second.citation_handle, first.citation_handle)
        self.assertFalse(second.repository_created)
        self.assertFalse(second.source_created)
        self.assertFalse(second.citation_created)
        self.assertFalse(second.person_linked)
        self.assertEqual(second.media_added, 0)
        self.assertEqual(second.media_linked, 0)
        self.assertEqual(second.downloaded, 0)
        self.assertEqual(second.already_downloaded, 0)
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(self.db.get_number_of_media(), 2)
        self.assertEqual(self.db.get_number_of_citations(), 1)

    def test_attach_without_download_links_urls(self) -> None:
        """Verify images are linked by URL when not downloaded."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        result = attacher.attach(self.person_handle, self.parsed, download=False)

        self.session.get.assert_not_called()
        self.assertEqual(result.media_added, 2)
        paths = [m.get_path() for m in self.db.iter_media()]
        self.assertTrue(all(p.startswith("https://") for p in paths), paths)

    def test_failed_download_falls_back_to_url(self) -> None:
        """Verify a failed download leaves the image linked by its URL."""
        self.session.get.return_value = _FakeReply(status_code=403)
        attacher = NaraRecordAttacher(self.db, session=self.session)
        result = attacher.attach(self.person_handle, self.parsed, max_images=1)

        self.assertEqual(result.downloaded, 0)
        self.assertEqual(len(result.failed), 1)
        paths = [m.get_path() for m in self.db.iter_media()]
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].startswith("https://"))
        folder = attacher.download_folder("90361620")
        self.assertFalse(
            os.path.exists(os.path.join(folder, "2480.jpg.part")), "partial left"
        )

    def test_cancel_keeps_downloaded_images(self) -> None:
        """Verify cancelling after the first image keeps only that image."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        result = attacher.attach(
            self.person_handle, self.parsed, progress=lambda done, total: False
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(result.downloaded, 1)
        self.assertEqual(self.db.get_number_of_media(), 1)
        self.assertEqual(self.session.get.call_count, 1)

    def test_existing_nara_repository_is_reused(self) -> None:
        """Verify a repository named like Citation Fix's NARA entry is reused."""
        from gramps.gen.lib import Repository

        repository = Repository()
        repository.set_name(NARA_REPOSITORY_NAME)
        with DbTxn("Add repository", self.db) as trans:
            self.db.add_repository(repository, trans)

        attacher = NaraRecordAttacher(self.db, session=self.session)
        result = attacher.attach(self.person_handle, self.parsed, download=False)

        self.assertFalse(result.repository_created)
        self.assertEqual(self.db.get_number_of_repositories(), 1)

    def test_parse_record_image_details(self) -> None:
        """Verify each image's object ID, file name and size are parsed."""
        first = self.parsed["digital_objects"][0]
        self.assertEqual(first["filename"], "2480.jpg")
        self.assertTrue(first["object_id"])
        self.assertGreater(first["size"], 0)

    def test_review_before_attaching(self) -> None:
        """Verify a record not yet in the tree shows every image as new."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        review = attacher.review(self.person_handle, self.parsed)

        self.assertEqual(review.citation_handle, "")
        self.assertFalse(review.citation_on_person)
        self.assertEqual([i.status for i in review.images], [IMAGE_NEW, IMAGE_NEW])
        self.assertEqual(len(review.new_images), 2)
        self.assertEqual(review.person_citations, [])
        self.session.get.assert_not_called()

    def test_review_after_attaching_part(self) -> None:
        """Verify attached images show as linked and the rest as new."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        attacher.attach(self.person_handle, self.parsed, selected=[1])
        review = attacher.review(self.person_handle, self.parsed)

        self.assertTrue(review.citation_handle)
        self.assertTrue(review.citation_on_person)
        self.assertEqual([i.status for i in review.images], [IMAGE_NEW, IMAGE_LINKED])
        self.assertEqual(len(review.person_citations), 1)
        existing = review.person_citations[0]
        self.assertTrue(existing.is_this_record)
        self.assertEqual(existing.naid, "90361620")
        self.assertEqual(existing.source_title, "Index to Naturalization Records")
        self.assertEqual(existing.media_count, 1)

    def test_attach_selected_images_only(self) -> None:
        """Verify only the chosen images are downloaded and added."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        result = attacher.attach(self.person_handle, self.parsed, selected=[1])

        self.assertEqual(result.downloaded, 1)
        self.assertEqual(result.media_added, 1)
        self.assertEqual(self.session.get.call_count, 1)
        self.assertTrue(self.session.get.call_args[0][0].endswith("2481.jpg"))
        media = list(self.db.iter_media())
        self.assertEqual(len(media), 1)
        attributes = {
            str(a.get_type()): a.get_value() for a in media[0].get_attribute_list()
        }
        self.assertEqual(
            attributes[OBJECT_ID_ATTRIBUTE],
            self.parsed["digital_objects"][1]["object_id"],
        )
        citation = self.db.get_citation_from_handle(result.citation_handle)
        naids = [
            a.get_value()
            for a in citation.get_attribute_list()
            if str(a.get_type()) == NAID_ATTRIBUTE
        ]
        self.assertEqual(naids, ["90361620"])

    def test_renamed_media_still_recognised(self) -> None:
        """Verify an image moved and renamed (as Media Fix does) is still found."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        attacher.attach(self.person_handle, self.parsed, selected=[0])
        media = next(iter(self.db.iter_media()))
        media.set_path("I0001_MacDonald_Lyman-Naturalization-1942.jpg")
        with DbTxn("Rename", self.db) as trans:
            self.db.commit_media(media, trans)

        review = attacher.review(self.person_handle, self.parsed)
        self.assertEqual(review.images[0].status, IMAGE_LINKED)
        self.assertEqual(
            review.images[0].media_path,
            "I0001_MacDonald_Lyman-Naturalization-1942.jpg",
        )

    def test_media_in_tree_but_not_on_citation(self) -> None:
        """Verify an image in the tree under another citation is linked, not added."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        attacher.attach(self.person_handle, self.parsed, selected=[0])
        citation = self.db.get_citation_from_handle(
            attacher.review(self.person_handle, self.parsed).citation_handle
        )
        citation.set_media_list([])
        with DbTxn("Unlink", self.db) as trans:
            self.db.commit_citation(citation, trans)

        review = attacher.review(self.person_handle, self.parsed)
        self.assertEqual(review.images[0].status, IMAGE_IN_TREE)
        result = attacher.attach(self.person_handle, self.parsed, selected=[0])
        self.assertEqual(result.media_added, 0)
        self.assertEqual(result.media_linked, 1)
        self.assertEqual(self.db.get_number_of_media(), 1)

    def test_citation_found_by_naid_after_page_edit(self) -> None:
        """Verify the record's citation is found by its NAID attribute."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        first = attacher.attach(self.person_handle, self.parsed, download=False)
        citation = self.db.get_citation_from_handle(first.citation_handle)
        citation.set_page("Naturalization index card, Lyman Angus MacDonald")
        with DbTxn("Edit page", self.db) as trans:
            self.db.commit_citation(citation, trans)

        second = attacher.attach(self.person_handle, self.parsed, download=False)
        self.assertEqual(second.citation_handle, first.citation_handle)
        self.assertFalse(second.citation_created)

    def test_download_one_for_preview(self) -> None:
        """Verify a preview download is reused by a later attach."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        review = attacher.review(self.person_handle, self.parsed)
        path = attacher.download_one(self.parsed, review.images[0])
        self.assertTrue(os.path.isfile(path))

        result = attacher.attach(self.person_handle, self.parsed, selected=[0])
        self.assertEqual(result.already_downloaded, 1)
        self.assertEqual(result.downloaded, 0)
        self.assertEqual(self.session.get.call_count, 1)

    def test_attach_with_page_descriptions_and_text(self) -> None:
        """Verify page descriptions and Transcript notes on new media."""
        from gramps.gen.lib import NoteType

        attacher = NaraRecordAttacher(self.db, session=self.session)
        attacher.attach(
            self.person_handle,
            self.parsed,
            download=False,
            descriptions={0: "MacDonald, Lyman Angus - 1942, page 1: Cover or jacket"},
            page_texts={0: "Box 123 Cert. 456", 1: "   "},
        )
        media = sorted(self.db.iter_media(), key=lambda m: m.get_path())
        self.assertEqual(
            media[0].get_description(),
            "MacDonald, Lyman Angus - 1942, page 1: Cover or jacket",
        )
        self.assertEqual(
            media[1].get_description(), "MacDonald, Lyman Angus - 1942, image 2 of 2"
        )
        notes = [self.db.get_note_from_handle(h) for h in media[0].get_note_list()]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].get_type(), NoteType.TRANSCRIPT)
        self.assertIn("Box 123 Cert. 456", notes[0].get())
        self.assertIn("machine-read", notes[0].get())
        self.assertEqual(media[1].get_note_list(), [])


class TestNaraMergeWindowFlow(unittest.TestCase):
    """
    Test attaching a record through the GWizard merge window: an incoming
    copy of the person, the window's own apply step, then finish_merge.
    """

    # The same tree, record and download stub as TestNaraRecordAttacher.
    # Borrowing its setUp hides the attributes from mypy, so name them here.
    media_dir: str
    db: DbWriteBase
    person_handle: str
    parsed: dict[str, Any]
    session: Mock

    setUp = TestNaraRecordAttacher.setUp
    tearDown = TestNaraRecordAttacher.tearDown

    def _merge(self, resolutions: dict[str, str]) -> bool:
        """Load the record as an incoming person and apply the resolutions."""
        gwizard = NaraGWizard(self.db)
        handle = gwizard.load_for_person(self.person_handle, self.parsed)
        try:
            return gwizard.run_step(
                "apply",
                source_person_handle=handle,
                target_person_handle=self.person_handle,
                resolutions=resolutions,
            )
        finally:
            gwizard.context["source_db"].close()

    def test_incoming_person(self) -> None:
        """Verify the incoming copy has the name, the citation and the images."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        source_db, handle = attacher.build_incoming(
            self.person_handle, self.parsed, descriptions={0: "Page one"}
        )
        try:
            incoming = source_db.get_person_from_handle(handle)
            self.assertEqual(
                incoming.get_primary_name().get_first_name(), "Lyman Angus"
            )
            self.assertEqual(len(incoming.get_citation_list()), 1)
            citation = source_db.get_citation_from_handle(
                incoming.get_citation_list()[0]
            )
            self.assertEqual(
                [str(a.get_type()) for a in citation.get_attribute_list()],
                [NAID_ATTRIBUTE],
            )
            self.assertEqual(citation.get_media_list(), [])
            media = [
                source_db.get_media_from_handle(r.ref)
                for r in incoming.get_media_list()
            ]
            self.assertEqual(len(media), 2)
            self.assertTrue(media[0].get_path().startswith("https://"))
            self.assertEqual(media[0].get_description(), "Page one")
            self.assertEqual(
                str(media[0].get_attribute_list()[0].get_type()), OBJECT_ID_ATTRIBUTE
            )
            # Nothing is written to the family tree.
            self.assertEqual(self.db.get_number_of_citations(), 0)
            self.assertEqual(self.db.get_number_of_media(), 0)
        finally:
            source_db.close()

    def test_merge_copies_chosen_image_then_downloads_it(self) -> None:
        """Verify the chosen image is copied, downloaded and cited."""
        self.assertTrue(self._merge({"person_sources": "source", "media:0": "source"}))
        person = self.db.get_person_from_handle(self.person_handle)
        self.assertEqual(len(person.get_citation_list()), 1)
        self.assertEqual(len(person.get_media_list()), 1)
        self.assertEqual(self.db.get_number_of_media(), 1)

        attacher = NaraRecordAttacher(self.db, session=self.session)
        images, online = attacher.merged_images(self.person_handle, self.parsed)
        self.assertEqual(len(images), 1)
        self.assertEqual(len(online), 1)

        result = attacher.finish_merge(self.person_handle, self.parsed, download=True)
        self.assertEqual(result.downloaded, 1)
        self.assertEqual(result.media_linked, 1)
        media = self.db.get_media_from_handle(person.get_media_list()[0].ref)
        self.assertEqual(media.get_path(), os.path.join("NARA", "90361620", "2480.jpg"))
        self.assertTrue(media.get_checksum())
        citation = self.db.get_citation_from_handle(person.get_citation_list()[0])
        self.assertEqual([r.ref for r in citation.get_media_list()], [media.handle])
        self.assertEqual(attacher.merged_images(self.person_handle, self.parsed)[1], [])

    def test_finish_without_download_keeps_web_address(self) -> None:
        """Verify an image not downloaded keeps its web address but is cited."""
        self._merge({"person_sources": "source", "media:0": "source"})
        attacher = NaraRecordAttacher(self.db, session=self.session)
        result = attacher.finish_merge(self.person_handle, self.parsed)
        self.assertEqual(result.downloaded, 0)
        self.assertEqual(result.media_linked, 1)
        self.session.get.assert_not_called()
        media = next(self.db.iter_media())
        self.assertTrue(media.get_path().startswith("https://"))

    def test_second_merge_reuses_citation_and_image(self) -> None:
        """Verify merging the record again adds no duplicates."""
        self._merge({"person_sources": "source", "media:0": "source"})
        NaraRecordAttacher(self.db, session=self.session).finish_merge(
            self.person_handle, self.parsed, download=True
        )
        self._merge(
            {"person_sources": "source", "media:0": "source", "media:1": "source"}
        )
        self.assertEqual(self.db.get_number_of_repositories(), 1)
        self.assertEqual(self.db.get_number_of_sources(), 1)
        self.assertEqual(self.db.get_number_of_citations(), 1)
        self.assertEqual(self.db.get_number_of_media(), 2)
        person = self.db.get_person_from_handle(self.person_handle)
        self.assertEqual(len(person.get_citation_list()), 1)
        self.assertEqual(len(person.get_media_list()), 2)


class TestNaraRecordText(unittest.TestCase):
    """Test fetching a record's machine-read page text."""

    @patch("requests.get")
    def test_fetch_record_text(self, mock_get: Mock) -> None:
        """Verify one call returns every page's text by object ID."""
        reply = Mock()
        reply.status_code = 200
        reply.json.return_value = _load_sample("nara_record_pension_text.json")
        mock_get.return_value = reply
        client = NaraCatalogInterface(api_key="key99")

        texts = client.fetch_record_text("115768360")
        assert texts is not None

        self.assertEqual(mock_get.call_count, 1)
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params, {"naId": "115768360", "includeExtractedText": "true"})
        self.assertEqual(len(texts), 12)
        self.assertIn("Box 31981", texts["115768361"])
        self.assertIn("CLAIM FOR WIDOW'S PENSION", texts["115768362"])

    @patch("requests.get")
    def test_fetch_record_text_failure(self, mock_get: Mock) -> None:
        """Verify a failed call returns None."""
        reply = Mock()
        reply.status_code = 403
        mock_get.return_value = reply
        self.assertIsNone(NaraCatalogInterface().fetch_record_text("1"))

        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError("down")
        self.assertIsNone(NaraCatalogInterface().fetch_record_text("1"))

    def test_texts_from_hits_without_text(self) -> None:
        """Verify images without extracted text map to ''."""
        hits = [
            {
                "_source": {
                    "record": {
                        "digitalObjects": [{"objectId": "9"}, {"objectUrl": "x"}]
                    }
                }
            }
        ]
        self.assertEqual(NaraCatalogInterface.texts_from_hits(hits), {"9": ""})
