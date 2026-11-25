# -*- coding: utf-8 -*-
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
National Archives and Records Administration (NARA) implementation of the
GWizard import and merge framework.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import copy
import logging
import mimetypes
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

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
    Date,
    Event,
    EventRef,
    EventRoleType,
    EventType,
    Citation,
    Source,
    Repository,
    RepositoryType,
    RepoRef,
    Attribute,
    Media,
    MediaRef,
    Note,
    NoteType,
    SrcAttribute,
    Url,
    UrlType,
)
from gramps.gen.datehandler import parser as dateparser
from gramps.gen.utils.file import create_checksum, media_path, relative_path
from gramps.gen.const import GRAMPS_LOCALE as glocale

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .gwizardgedcom import GedGWizard

LOG = logging.getLogger(__name__)
_ = glocale.translation.gettext

# Creator fields that may say whether a NARA authority is a person or an
# organization. NARA's documentation does not name the field, so several
# likely names are checked; the heading test below is the fallback.
_CREATOR_TYPE_KEYS = (
    "authorityType",
    "creatorAuthorityType",
    "entityType",
    "recordType",
    "type",
)

# Words that mark a heading as an organization rather than a person. They
# are checked in the given-name part of a "Surname, Given" heading and in
# multi-word surnames only, so a person surnamed House or Church still
# counts as a person.
_ORGANIZATION_WORDS = frozenset("""
    administration agency army association authority battalion board branch
    bureau cavalry center centre church college command commission committee
    company congress corporation corps council county court department
    district division federal foundation government guard headquarters
    hospital house inc infantry institute institution international
    laboratory league legislature library ltd marine militia museum national
    navy office organization party program project regiment school section
    senate service society staff state states station union united unit
    university volunteers
    """.split())

# A trailing date part of a NARA personal-name heading, such as
# ", 1809-1865", ", 1900-" or ", b. 1850".
_HEADING_DATES = re.compile(
    r",?\s*(?:b\.|d\.|ca\.|fl\.|active|approximately|born|died)?\s*\d.*$",
    re.IGNORECASE,
)

# One word of a personal name: a capitalized word (allowing ' and -) or an
# initial such as "A." or "J.R.".
_NAME_WORD = re.compile(r"^(?:[A-Z][\w'’-]*\.?|(?:[A-Z]\.)+)$")


# ------------------------------------------------------------
#
# NaraCatalogInterface
#
# ------------------------------------------------------------
class NaraCatalogInterface:
    """Client for the National Archives Catalog API v2."""

    DEFAULT_BASE_URL = "https://catalog.archives.gov/api/v2"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        verify_ssl: bool | str | None = None,
    ) -> None:
        """Initialize the NARA Catalog interface.

        :param api_key: NARA API key; defaults to the NARA_API_KEY environment
            variable.
        :param base_url: Base URL for NARA Catalog API v2.
        :param verify_ssl: SSL certificate verification flag or path to CA bundle.
        """
        # An explicit key supports callers that supply credentials directly;
        # the NARA tool itself reads only NARA_API_KEY from the environment.
        self.api_key = api_key.strip() or os.environ.get("NARA_API_KEY", "").strip()
        self.base_url = base_url.rstrip("/")
        self.headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Gramps-GWizard-NARA/1.0",
        }
        if self.api_key:
            self.headers["x-api-key"] = self.api_key
        self.verify_ssl = verify_ssl

    def validate_api_key(self) -> str | None:
        """Check the key with a minimal catalog request; return an error if invalid."""
        if not self.api_key:
            return _(
                "Set the NARA_API_KEY environment variable before using this tool."
            )

        request_options: dict[str, Any] = {
            "params": {"q": "constitution", "limit": 1},
            "headers": self.headers,
            "timeout": 10,
        }
        if self.verify_ssl is not None:
            request_options["verify"] = self.verify_ssl

        try:
            response = requests.get(
                f"{self.base_url}/records/search", **request_options
            )
        except requests.exceptions.RequestException:
            LOG.warning("Could not contact NARA to validate the API key", exc_info=True)
            return _(
                "Could not contact NARA to validate the API key. "
                "Check your network connection and try again."
            )

        if response.status_code in (401, 403):
            return _("NARA rejected the API key. Verify the value of NARA_API_KEY.")
        if response.status_code != 200:
            LOG.error("NARA API key validation returned HTTP %s", response.status_code)
            return (
                _("NARA could not validate the API key (HTTP %s).")
                % response.status_code
            )
        try:
            response_data = response.json()
            if not isinstance(response_data, dict):
                raise ValueError("Expected a JSON object")
        except ValueError:
            LOG.exception("NARA returned an invalid response during API key validation")
            return _("NARA returned an invalid response while validating the API key.")

        api_status = response_data.get("statusCode")
        if api_status is not None:
            try:
                api_status = int(api_status)
            except (TypeError, ValueError):
                LOG.error("NARA returned an invalid API status during key validation")
                return _(
                    "NARA returned an invalid response while validating the API key."
                )
            if api_status in (401, 403):
                return _("NARA rejected the API key. Verify the value of NARA_API_KEY.")
            if api_status != 200:
                LOG.error("NARA API key validation returned API status %s", api_status)
                return _("NARA could not validate the API key (HTTP %s).") % api_status
        return None

    @staticmethod
    def is_person_creator(creator: Any, heading: str) -> bool:
        """
        Return True when a NARA creator is a person rather than an
        organization.

        A type field on the creator decides when NARA supplies one.
        Otherwise the heading must have the shape of a personal name:
        "Surname, Given[, dates]" (NARA's form for people) or two to four
        capitalized words, with no organization words in the given names.
        Agency headings such as "United States. Department of War." fail.
        """
        if isinstance(creator, dict):
            for key in _CREATOR_TYPE_KEYS:
                value = str(creator.get(key) or "").strip().lower()
                if "organi" in value:
                    return False
                if "person" in value:
                    return True

        value = _HEADING_DATES.sub("", heading.strip()).strip(" ,.")
        if not value or re.search(r"\.\s+[A-Z][a-z]", value.split(",")[0]):
            # Empty, or an agency hierarchy ("United States. Army") before
            # any comma.
            return False

        def name_words(text: str, allow_org_words: bool) -> bool:
            words = text.split()
            if not 1 <= len(words) <= 4:
                return False
            if not all(_NAME_WORD.match(word) for word in words):
                return False
            if allow_org_words:
                return True
            return not any(
                word.strip(".,").lower() in _ORGANIZATION_WORDS for word in words
            )

        if "," in value:
            surname, rest = value.split(",", 1)
            # Drop a fuller form in parentheses: "Edward M. (Edward Mandell)".
            given = re.sub(r"\([^)]*\)", " ", rest.split(",", 1)[0]).strip()
            single_surname = len(surname.split()) == 1
            return (
                bool(given)
                and len(surname.split()) <= 3
                and name_words(surname, allow_org_words=single_surname)
                and name_words(given, allow_org_words=False)
            )
        return len(value.split()) >= 2 and name_words(value, allow_org_words=False)

    def search_records(
        self,
        query: str,
        rows: int = 25,
        material_type: str | None = None,
        available_online: bool = False,
        start_year: str = "",
        end_year: str = "",
        level_of_description: str = "",
    ) -> dict[str, Any] | None:
        params: dict[str, str | int] = {"q": query, "limit": rows}
        if material_type:
            params["generalRecordsTypes"] = material_type
        if available_online:
            params["availableOnline"] = "true"
        if level_of_description:
            params["levelOfDescription"] = level_of_description
        if start_year or end_year:
            params["dateRange"] = f"{start_year or '*'} TO {end_year or '*'}"
        # ... rest of search_records unchanged ...

        request_options: dict[str, Any] = {
            "params": params,
            "headers": self.headers,
            "timeout": 30,
        }
        if self.verify_ssl is not None:
            request_options["verify"] = self.verify_ssl

        try:
            response = requests.get(
                f"{self.base_url}/records/search", **request_options
            )
        except requests.exceptions.RequestException:
            LOG.exception("NARA catalog search request failed")
            return None

        if response.status_code != 200:
            LOG.error(
                "NARA catalog search returned HTTP %s: %s",
                response.status_code,
                response.text,
            )
            return None
        try:
            return response.json()
        except ValueError:
            LOG.exception("NARA catalog returned invalid JSON")
            return None

    def fetch_record_text(self, naid: str) -> dict[str, str] | None:
        """
        Fetch the text NARA machine-read from each image of one record.

        This is one API call, however many images the record has.

        :param naid: The record's National Archives Identifier.
        :returns: Each image's text keyed by its object ID ('' for an image
            without text), or None when the call fails.
        """
        request_options: dict[str, Any] = {
            "params": {"naId": naid, "includeExtractedText": "true"},
            "headers": self.headers,
            "timeout": 60,
        }
        if self.verify_ssl is not None:
            request_options["verify"] = self.verify_ssl
        try:
            response = requests.get(
                f"{self.base_url}/records/search", **request_options
            )
        except requests.exceptions.RequestException:
            LOG.exception("NARA page text request failed for %s", naid)
            return None
        if response.status_code != 200:
            LOG.warning(
                "NARA page text for %s returned HTTP %s", naid, response.status_code
            )
            return None
        try:
            hits = self.extract_hits(response.json())
        except ValueError:
            LOG.warning("NARA page text for %s was not valid JSON", naid)
            return None
        return self.texts_from_hits(hits)

    @staticmethod
    def texts_from_hits(hits: list[dict[str, Any]]) -> dict[str, str]:
        """Return each image's extracted text by object ID from search hits."""
        texts: dict[str, str] = {}
        for hit in hits:
            source = hit.get("_source") if isinstance(hit, dict) else None
            record = (source or {}).get("record") or {}
            for digital_object in record.get("digitalObjects") or []:
                if isinstance(digital_object, dict) and digital_object.get("objectId"):
                    texts[str(digital_object["objectId"])] = str(
                        digital_object.get("extractedText") or ""
                    )
        return texts

    @staticmethod
    def extract_hits(response: Any) -> list[dict[str, Any]]:
        """Extract search hits from supported NARA response shapes."""
        if not isinstance(response, dict):
            return []
        body = response.get("body")
        if isinstance(body, dict):
            hits = body.get("hits")
            if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
                return hits["hits"]
        hits = response.get("hits")
        if isinstance(hits, list):
            return hits
        if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
            return hits["hits"]
        return []

    @staticmethod
    def _creators_of(entry: dict[str, Any]) -> tuple[list[str], list[str]]:
        """
        Return (all creator headings, person creator headings) of a record or
        ancestor entry from its 'creators' list.
        """
        creators: list[str] = []
        person_creators: list[str] = []
        creators_data = entry.get("creators") or []
        if isinstance(creators_data, dict):
            creators_data = [creators_data]
        for creator in creators_data if isinstance(creators_data, list) else []:
            if isinstance(creator, dict):
                heading = str(creator.get("heading") or "").strip()
            else:
                heading = str(creator or "").strip()
            if not heading:
                continue
            creators.append(heading)
            if NaraCatalogInterface.is_person_creator(creator, heading):
                person_creators.append(heading)
        return creators, person_creators

    @staticmethod
    def _date_range_of(entry: dict[str, Any]) -> str:
        """
        Return an entry's inclusive (or coverage) date range as "YYYY" or
        "YYYY-YYYY", or '' when it has none.
        """

        def year(value: Any) -> str:
            if isinstance(value, dict):
                value = value.get("year") or value.get("logicalDate") or ""
            match = re.match(r"\s*(\d{4})", str(value or ""))
            return match.group(1) if match else ""

        for start_key, end_key in (
            ("inclusiveStartDate", "inclusiveEndDate"),
            ("coverageStartDate", "coverageEndDate"),
        ):
            start, end = year(entry.get(start_key)), year(entry.get(end_key))
            if start or end:
                return (
                    f"{start}-{end}" if start and end and start != end else start or end
                )
        return ""

    @staticmethod
    def _mime_type_of(digital_object: dict[str, Any]) -> str:
        """
        Return a MIME type for a digital object. NARA gives a description
        such as "Image (JPG)" in objectType, so the file name decides.
        """
        object_type = str(digital_object.get("objectType") or "")
        if "/" in object_type:
            return object_type
        name = str(
            digital_object.get("objectFilename")
            or digital_object.get("objectUrl")
            or ""
        )
        guessed, _encoding = mimetypes.guess_type(name)
        return guessed or ""

    @staticmethod
    def parse_record(hit: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize a NARA search hit into fields used by the merge flow.

        Field names follow real NARA Catalog API v2 responses (see the
        nara_*.json samples in the test data folder):

        - 'creators' holds the record's own creator headings (people and
          agencies). File units and items usually have none; then the
          creators of the nearest ancestor (normally the series) are used and
          'creators_from' names that ancestor's level.
        - 'person_creators' holds only the record's own creators that name a
          person; ancestor creators are never treated as the record's person.
        - 'date_str' is the record's own date range, or the nearest
          ancestor's, with 'date_from' naming the ancestor's level.
        - 'series_title' and 'series_naid' name the series the record
          belongs to ('' when it has none).
        """
        record_source = hit.get("_source")
        if not isinstance(record_source, dict):
            record_source = hit
        record = record_source.get("record")
        if not isinstance(record, dict):
            record = record_source

        naid = str(record.get("naId") or hit.get("_id") or "")
        creators, person_creators = NaraCatalogInterface._creators_of(record)
        date_str = NaraCatalogInterface._date_range_of(record)
        creators_from = ""
        date_from = ""
        series_title = ""
        series_naid = ""

        ancestors = record.get("ancestors") or []
        ancestors = sorted(
            (a for a in ancestors if isinstance(a, dict)),
            key=lambda a: int(a.get("distance") or 0),
        )
        for ancestor in ancestors:
            level = str(ancestor.get("levelOfDescription") or "")
            if not creators:
                creators = NaraCatalogInterface._creators_of(ancestor)[0]
                creators_from = level if creators else ""
            if not date_str:
                date_str = NaraCatalogInterface._date_range_of(ancestor)
                date_from = level if date_str else ""
            if not series_title and level == "series":
                series_title = str(ancestor.get("title") or "")
                series_naid = str(ancestor.get("naId") or "")

        record_types = record.get("generalRecordsTypes") or []
        if isinstance(record_types, str):
            record_types = [record_types]

        parsed_media = []
        digital_objects = record.get("digitalObjects") or []
        if isinstance(digital_objects, dict):
            digital_objects = [digital_objects]
        for digital_object in (
            digital_objects if isinstance(digital_objects, list) else []
        ):
            if not isinstance(digital_object, dict):
                continue
            url = digital_object.get("objectUrl")
            if url:
                try:
                    size = int(digital_object.get("objectFileSize") or 0)
                except (TypeError, ValueError):
                    size = 0
                parsed_media.append(
                    {
                        "url": str(url),
                        "object_id": str(digital_object.get("objectId") or ""),
                        "filename": str(
                            digital_object.get("objectFilename")
                            or os.path.basename(str(url).split("?", 1)[0])
                        ),
                        "size": size,
                        "mime_type": NaraCatalogInterface._mime_type_of(digital_object),
                        "description": str(
                            digital_object.get("objectDescription")
                            or digital_object.get("objectDesignator")
                            or ""
                        ),
                    }
                )

        return {
            "naid": naid,
            "title": str(record.get("title") or ""),
            "level": str(record.get("levelOfDescription") or ""),
            "creators": creators,
            "creators_from": creators_from,
            "person_creators": person_creators,
            "scope_note": str(record.get("scopeAndContentNote") or ""),
            "material_type": ", ".join(str(t) for t in record_types if t),
            "date_str": date_str,
            "date_from": date_from,
            "series_title": series_title,
            "series_naid": series_naid,
            "web_url": f"https://catalog.archives.gov/id/{naid}" if naid else "",
            "digital_objects": parsed_media,
        }


# ------------------------------------------------------------
#
# NaraGWizard
#
# ------------------------------------------------------------
class NaraGWizard(GedGWizard):
    """Load NARA catalog records and reuse the GWizard merge workflow."""

    def _connect(self, **kwargs: Any) -> bool:
        """Save search parameters or selected result data for the load step."""
        query = str(kwargs.get("query") or "").strip()
        hits = kwargs.get("hits")
        if not query and not hits:
            LOG.error("NARA connection requires a search query or selected hits")
            return False

        api_key = str(kwargs.get("api_key") or "").strip()
        self.context["query"] = query
        self.context["hits"] = hits
        self.context["api_key"] = api_key
        self.context["rows"] = kwargs.get("limit", kwargs.get("rows", 25))
        self.context["material_type"] = kwargs.get("material_type")
        self.context["available_online"] = bool(kwargs.get("available_online", False))
        self.context["start_year"] = str(kwargs.get("start_year") or "")
        self.context["end_year"] = str(kwargs.get("end_year") or "")
        self.context["client"] = kwargs.get("client") or NaraCatalogInterface(
            api_key=api_key
        )
        return True

    def _load(self, **kwargs: Any) -> list[Person]:
        """Load selected NARA records into an in-memory Gramps database."""
        client = self.context.get("client")
        if client is None:
            raise RuntimeError("NARA connection has not been configured.")

        hits = self.context.get("hits")
        if hits is None:
            response = client.search_records(
                query=self.context["query"],
                rows=int(self.context.get("rows", 25)),
                material_type=self.context.get("material_type"),
                available_online=self.context.get("available_online", False),
                start_year=self.context.get("start_year", ""),
                end_year=self.context.get("end_year", ""),
            )
            if response is None:
                raise RuntimeError("NARA catalog search failed.")
            hits = NaraCatalogInterface.extract_hits(response)
        elif isinstance(hits, dict):
            hits = NaraCatalogInterface.extract_hits(hits)
        if not isinstance(hits, list):
            raise RuntimeError("NARA catalog returned an invalid result list.")

        source_db = make_database("sqlite")
        source_db.load(":memory:")
        people: list[Person] = []
        try:
            with DbTxn(_("Load NARA Catalog Records"), source_db) as trans:
                repository = Repository()
                repository.set_name("National Archives and Records Administration")
                repository.set_type(RepositoryType(RepositoryType.ARCHIVE))
                source_db.add_repository(repository, trans)

                for hit in hits:
                    if not isinstance(hit, dict):
                        continue
                    parsed = NaraCatalogInterface.parse_record(hit)
                    headings = parsed["person_creators"]
                    if not headings:
                        LOG.warning(
                            "NARA record %s has no person creator and was skipped",
                            parsed["naid"],
                        )
                        continue

                    source = Source()
                    source.set_title(parsed["title"] or parsed["naid"])
                    source.set_author("; ".join(parsed["creators"]))
                    publication = [
                        value
                        for value in (
                            parsed["material_type"],
                            parsed["date_str"],
                            parsed["scope_note"],
                            parsed["web_url"],
                        )
                        if value
                    ]
                    source.set_publication_info("\n".join(publication))
                    repo_ref = RepoRef()
                    repo_ref.set_reference_handle(repository.handle)
                    source.add_repo_reference(repo_ref)
                    source_db.add_source(source, trans)

                    citation = Citation()
                    citation.set_reference_handle(source.handle)
                    citation.set_page(parsed["naid"])
                    for media_data in parsed["digital_objects"]:
                        media = Media()
                        media.set_path(media_data["url"])
                        media.set_mime_type(media_data["mime_type"])
                        media.set_description(
                            media_data["description"] or parsed["title"]
                        )
                        source_db.add_media(media, trans)
                        media_ref = MediaRef()
                        media_ref.set_reference_handle(media.handle)
                        citation.add_media_reference(media_ref)
                    source_db.add_citation(citation, trans)

                    for heading in headings:
                        given, surname, birth_year, death_year = (
                            self._parse_person_name(heading)
                        )
                        if not given and not surname:
                            LOG.warning(
                                "Could not identify a person in NARA creator %r",
                                heading,
                            )
                            continue
                        person = Person()
                        name = Name()
                        name.set_first_name(given)
                        if surname:
                            surname_obj = Surname()
                            surname_obj.set_surname(surname)
                            name.add_surname(surname_obj)
                        person.set_primary_name(name)
                        person.add_citation(citation.handle)

                        for year, event_type in (
                            (birth_year, EventType.BIRTH),
                            (death_year, EventType.DEATH),
                        ):
                            if not year:
                                continue
                            event = Event()
                            event.set_type(EventType(event_type))
                            event_date = Date()
                            event_date.set_year(int(year))
                            event.set_date_object(event_date)
                            event.add_citation(citation.handle)
                            event_handle = source_db.add_event(event, trans)
                            event_ref = EventRef()
                            event_ref.ref = event_handle
                            if event_type == EventType.BIRTH:
                                person.set_birth_ref(event_ref)
                            else:
                                person.set_death_ref(event_ref)

                        source_db.add_person(person, trans)
                        people.append(person)
        except Exception:
            source_db.close()
            raise

        if not people:
            source_db.close()
            raise RuntimeError(
                _(
                    "The selected NARA record names no person as its creator "
                    "(its creators are agencies or organizations), so it cannot "
                    "be merged as a person."
                )
            )
        self.context["source_db"] = source_db
        self.context["source_title"] = _("NARA Catalog")
        self.context["nara_records"] = hits
        return people

    def load_for_person(
        self,
        person_handle: str,
        parsed: dict[str, Any],
        descriptions: dict[int, str] | None = None,
        page_texts: dict[int, str] | None = None,
    ) -> str:
        """
        Load one parsed record as an incoming copy of an existing person,
        for the GWizard merge window (see NaraRecordAttacher.build_incoming).

        :returns: The incoming person's handle.
        """
        attacher = NaraRecordAttacher(self.db)
        source_db, handle = attacher.build_incoming(
            person_handle, parsed, descriptions, page_texts
        )
        self.context["source_db"] = source_db
        self.context["source_title"] = _("NARA Catalog")
        self.context["nara_parsed"] = parsed
        return handle

    @staticmethod
    def _parse_person_name(heading: str) -> tuple[str, str, str, str]:
        """Parse a NARA creator heading into given, surname, birth and death."""
        value = heading.strip()
        years = re.search(r"(?<!\d)(\d{4})\s*[-–]\s*(\d{4})(?!\d)", value)
        birth_year, death_year = years.groups() if years else ("", "")
        if years:
            value = value[: years.start()].rstrip(" ,")

        parts = [part.strip() for part in value.split(",") if part.strip()]
        if len(parts) > 1:
            surname = parts[0]
            given = parts[1]
        else:
            words = value.split()
            if len(words) > 1:
                given = " ".join(words[:-1])
                surname = words[-1]
            else:
                given = value
                surname = ""
        return given, surname, birth_year, death_year


def format_size(size: int) -> str:
    """Return a file size for display, such as '870 KB' or '1.2 GB'."""
    if size <= 0:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit in ("B", "KB") or value >= 100:
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return ""


# ------------------------------------------------------------
#
# Attach a NARA record to a person
#
# ------------------------------------------------------------
# NARA's entry in Citation Fix's standard repository list
# (gw_goldstandardrepos.py in the gwizard_citationfix repo). Keep the name the
# same as there, so Citation Fix recognizes the repository this tool creates.
NARA_REPOSITORY_NAME = "National Archives and Records Administration (NARA)"
NARA_REPOSITORY_URL = "https://www.archives.gov"

# Folder under the media base path that downloaded images go in, one
# subfolder per record (by NAID). A stopgap until downloads are named with
# Media Fix's template.
NARA_MEDIA_FOLDER = "NARA"


# Attributes this tool puts on what it creates, so a record or image can be
# recognised later even after Citation Fix edits the citation's page or
# Media Fix renames and moves the file.
NAID_ATTRIBUTE = "NAID"
OBJECT_ID_ATTRIBUTE = "NARA Object ID"

# Image statuses reported by NaraRecordAttacher.review().
IMAGE_NEW = "new"
IMAGE_IN_TREE = "in_tree"
IMAGE_LINKED = "linked"


@dataclass
class ImageStatus:
    """One image of a NARA record, and whether the tree already has it."""

    index: int
    object_id: str
    filename: str
    size: int
    url: str
    mime_type: str
    status: str = IMAGE_NEW
    media_handle: str = ""
    media_path: str = ""


@dataclass
class ExistingCitation:
    """A NARA citation the person already has."""

    handle: str
    page: str
    source_title: str
    naid: str
    media_count: int
    is_this_record: bool = False


@dataclass
class RecordReview:
    """How a NARA record compares with what is already in the tree."""

    citation_handle: str = ""
    citation_on_person: bool = False
    images: list[ImageStatus] = field(default_factory=list)
    person_citations: list[ExistingCitation] = field(default_factory=list)

    @property
    def new_images(self) -> list[ImageStatus]:
        """The images the tree does not have yet."""
        return [image for image in self.images if image.status == IMAGE_NEW]


@dataclass
class AttachResult:
    """What attaching one NARA record to a person did."""

    citation_handle: str = ""
    repository_created: bool = False
    source_created: bool = False
    citation_created: bool = False
    person_linked: bool = False
    event_linked: bool = False
    event_created: bool = False
    event_type: str = ""
    media_added: int = 0
    media_linked: int = 0
    downloaded: int = 0
    already_downloaded: int = 0
    failed: list[str] = field(default_factory=list)
    cancelled: bool = False


class NaraRecordAttacher:
    """
    Compare a NARA catalog record with what an existing person already has,
    and attach it as a source and citation with the chosen images.

    - Repository: NARA, reused when one with the same name exists.
    - Source: the record's series (or the record itself when it has no
      series), reused when a NARA source with that title exists.
    - Citation: the record (title and NAID), with a "NAID" attribute and a
      note holding its catalog link and description; reused when the tree
      already has a citation for that NAID.
    - Media: one object per chosen image, with a "NARA Object ID" attribute,
      linked to the citation. Images the tree already has (same object ID,
      path or web address) are linked, not added again. Downloaded images
      are stored under <media base path>/NARA/<NAID>/; an image that is not
      downloaded, or fails to download, is linked by its web address.

    Images are downloaded before the family tree is changed, so a slow or
    cancelled download never leaves a half-written transaction.
    """

    def __init__(self, db: DbWriteBase, session: Any = None, timeout: int = 60):
        """
        :param db: The open family tree.
        :param session: Object with a requests-style get() for downloads;
            defaults to the requests module.
        :param timeout: Seconds to wait for each image.
        """
        self.db = db
        self.session = session if session is not None else requests
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Comparing
    # ------------------------------------------------------------------
    def download_folder(self, naid: str) -> str:
        """Return the absolute folder a record's images are downloaded to."""
        return os.path.join(media_path(self.db), NARA_MEDIA_FOLDER, naid or "unknown")

    def download_path(self, parsed: dict[str, Any], image: ImageStatus) -> str:
        """Return the absolute path an image is (or would be) downloaded to."""
        name = image.filename or f"image_{image.index + 1}"
        return os.path.join(self.download_folder(str(parsed.get("naid") or "")), name)

    def review(self, person_handle: str, parsed: dict[str, Any]) -> RecordReview:
        """
        Compare a parsed NARA record with the tree and the person.

        :returns: The record's existing citation (if any), each image's status
            (new, in the tree, or already linked to that citation), and the
            NARA citations the person already has.
        """
        person = self.db.get_person_from_handle(person_handle)
        review = RecordReview()
        citation = self._find_citation(parsed)
        linked: set[str] = set()
        if citation is not None:
            review.citation_handle = citation.get_handle()
            linked = {ref.ref for ref in citation.get_media_list()}
            if person is not None:
                review.citation_on_person = (
                    citation.get_handle() in person.get_citation_list()
                )

        index = self._media_index()
        base = media_path(self.db)
        for number, digital_object in enumerate(parsed.get("digital_objects") or []):
            image = ImageStatus(
                index=number,
                object_id=str(digital_object.get("object_id") or ""),
                filename=str(digital_object.get("filename") or ""),
                size=int(digital_object.get("size") or 0),
                url=str(digital_object.get("url") or ""),
                mime_type=str(digital_object.get("mime_type") or ""),
            )
            download = relative_path(self.download_path(parsed, image), base)
            handle = self._match_media(index, image, download)
            if handle:
                media = self.db.get_media_from_handle(handle)
                image.media_handle = handle
                image.media_path = str(media.get_path()) if media else ""
                image.status = IMAGE_LINKED if handle in linked else IMAGE_IN_TREE
            review.images.append(image)

        if person is not None:
            review.person_citations = self._person_nara_citations(
                person, review.citation_handle
            )
        return review

    def _media_index(self) -> dict[str, str]:
        """
        Return a lookup from 'id:<object id>' and 'path:<path or URL>' to the
        handle of the media object that has it.
        """
        index: dict[str, str] = {}
        for media in self.db.iter_media():
            index.setdefault(f"path:{media.get_path()}", media.get_handle())
            for attribute in media.get_attribute_list():
                if str(attribute.get_type()) == OBJECT_ID_ATTRIBUTE:
                    index.setdefault(f"id:{attribute.get_value()}", media.get_handle())
        return index

    @staticmethod
    def _match_media(index: dict[str, str], image: ImageStatus, download: str) -> str:
        """Return the handle of the tree's copy of an image, or ''."""
        keys = []
        if image.object_id:
            keys.append(f"id:{image.object_id}")
        keys.extend([f"path:{download}", f"path:{image.url}"])
        for key in keys:
            if key in index:
                return index[key]
        return ""

    def _find_citation(self, parsed: dict[str, Any]) -> Citation | None:
        """Return the tree's citation for this NAID, or None."""
        naid = str(parsed.get("naid") or "")
        if not naid:
            return None
        page = self._page(parsed)
        for citation in self.db.iter_citations():
            for attribute in citation.get_attribute_list():
                if (
                    str(attribute.get_type()) == NAID_ATTRIBUTE
                    and str(attribute.get_value()) == naid
                ):
                    return citation
            if citation.get_page() == page:
                return citation
        return None

    def _person_nara_citations(
        self, person: Person, this_handle: str
    ) -> list[ExistingCitation]:
        """Return the person's citations whose source is held by NARA."""
        nara_repos = {
            repository.get_handle()
            for repository in self.db.iter_repositories()
            if str(repository.get_name() or "").strip().casefold()
            == NARA_REPOSITORY_NAME.casefold()
        }
        found: list[ExistingCitation] = []
        for handle in person.get_citation_list():
            citation = self.db.get_citation_from_handle(handle)
            if citation is None:
                continue
            source = self.db.get_source_from_handle(citation.get_reference_handle())
            if source is None or not any(
                ref.ref in nara_repos for ref in source.get_reporef_list()
            ):
                continue
            naid = ""
            for attribute in citation.get_attribute_list():
                if str(attribute.get_type()) == NAID_ATTRIBUTE:
                    naid = str(attribute.get_value())
            found.append(
                ExistingCitation(
                    handle=handle,
                    page=str(citation.get_page() or ""),
                    source_title=str(source.get_title() or ""),
                    naid=naid,
                    media_count=len(citation.get_media_list()),
                    is_this_record=handle == this_handle,
                )
            )
        return found

    # ------------------------------------------------------------------
    # Attaching
    # ------------------------------------------------------------------
    def attach(
        self,
        person_handle: str,
        parsed: dict[str, Any],
        download: bool = True,
        max_images: int = 0,
        progress: Callable[[int, int], bool] | None = None,
        selected: list[int] | None = None,
        descriptions: dict[int, str] | None = None,
        page_texts: dict[int, str] | None = None,
    ) -> AttachResult:
        """
        Attach a parsed NARA record (see NaraCatalogInterface.parse_record).

        :param person_handle: Handle of the person to attach the record to.
        :param parsed: The parsed record.
        :param download: Download the new images (otherwise link them by URL).
        :param max_images: Most images to add; 0 means all. Ignored when
            'selected' is given.
        :param progress: Called as progress(done, total) after each image is
            downloaded; returning False cancels the remaining downloads. The
            images already downloaded are still added.
        :param selected: Indexes (into the record's images) of the images to
            add; None adds all of them, up to max_images.
        :param descriptions: Descriptions for new media by image index, such
            as "..., page 3: Claim brief"; others get "..., image N of M".
        :param page_texts: NARA's machine-read text by image index; each new
            media object gets it as a Transcript note.
        :returns: What was done.
        """
        person = self.db.get_person_from_handle(person_handle)
        if person is None:
            raise RuntimeError(_("The target person could not be found."))

        review = self.review(person_handle, parsed)
        if selected is not None:
            wanted = set(selected)
            images = [image for image in review.images if image.index in wanted]
        else:
            images = list(review.images)
            if max_images > 0:
                images = images[:max_images]

        result = AttachResult()
        paths = self._fetch_images(parsed, images, download, progress, result)

        title = parsed.get("title") or parsed.get("naid") or _("NARA record")
        with DbTxn(
            _("Attach NARA record %s") % parsed.get("naid", ""), self.db
        ) as trans:
            repository = self._repository(trans, result)
            source = self._source(trans, parsed, repository, result)
            citation = self._citation(trans, parsed, source, title, result)
            result.citation_handle = citation.get_handle()

            linked = {ref.ref for ref in citation.get_media_list()}
            for image in images:
                if image.index not in paths:
                    continue
                handle = image.media_handle
                if not handle:
                    handle = self._add_media(
                        trans,
                        image,
                        paths[image.index],
                        (descriptions or {}).get(image.index)
                        or _("%(title)s, image %(number)d of %(total)d")
                        % {
                            "title": title,
                            "number": image.index + 1,
                            "total": len(review.images),
                        },
                        (page_texts or {}).get(image.index, ""),
                        citation=citation,
                    )
                    result.media_added += 1
                if handle not in linked:
                    media_ref = MediaRef()
                    media_ref.set_reference_handle(handle)
                    citation.add_media_reference(media_ref)
                    linked.add(handle)
                    result.media_linked += 1
            self.db.commit_citation(citation, trans)

            if citation.get_handle() not in person.get_citation_list():
                person.add_citation(citation.get_handle())
                self.db.commit_person(person, trans)
                result.person_linked = True

            # Link or create the relevant event (Pension, Naturalization, Military, Death, Marriage)
            event_type = self._detect_record_event_type(parsed, descriptions)
            if event_type is not None:
                linked_evt = self._link_or_create_event(
                    person, event_type, citation, parsed, trans
                )
                if linked_evt is not None:
                    result.event_linked = True
                    result.event_type = str(event_type)
        return result

    # ------------------------------------------------------------------
    # Merging through the GWizard merge window
    # ------------------------------------------------------------------
    def build_incoming(
        self,
        person_handle: str,
        parsed: dict[str, Any],
        descriptions: dict[int, str] | None = None,
        page_texts: dict[int, str] | None = None,
    ) -> tuple[Any, str]:
        """
        Build an in-memory database holding an "incoming" copy of the person
        that carries this record, for the GWizard merge window.

        The copy has the person's own name and gender (so those rows match
        and offer nothing to copy), the record's citation as a person
        source, and every image of the record in its gallery. The window's
        arrows then copy the citation and the chosen images over.

        The tree's NARA repository, source, citation and images, when it
        already has them, are copied in with their own handles, so the merge
        reuses them instead of adding duplicates. New images are linked by
        their web address; finish_merge downloads them afterwards.

        :param person_handle: The tree person the record is attached to.
        :param parsed: The parsed record.
        :param descriptions: Descriptions for new images by index.
        :param page_texts: NARA's machine-read text by image index; each new
            image gets it as a Transcript note.
        :returns: The in-memory database and the incoming person's handle.
        """
        person = self.db.get_person_from_handle(person_handle)
        if person is None:
            raise RuntimeError(_("The target person could not be found."))
        review = self.review(person_handle, parsed)
        title = parsed.get("title") or parsed.get("naid") or _("NARA record")

        source_db = make_database("sqlite")
        source_db.load(":memory:")
        staging = NaraRecordAttacher(source_db, self.session, self.timeout)
        result = AttachResult()
        try:
            with DbTxn(
                _("NARA record %s") % parsed.get("naid", ""), source_db
            ) as trans:
                repository = self._find_repository()
                if repository is not None:
                    repository = self._bare_copy(repository)
                    source_db.add_repository(repository, trans)
                else:
                    repository = staging._repository(trans, result)

                source = self._find_source(parsed, repository.get_handle())
                if source is not None:
                    source = self._bare_copy(source)
                    source_db.add_source(source, trans)
                else:
                    source = staging._source(trans, parsed, repository, result)

                citation = (
                    self.db.get_citation_from_handle(review.citation_handle)
                    if review.citation_handle
                    else None
                )
                if citation is not None:
                    citation = self._bare_copy(citation)
                    citation.set_reference_handle(source.get_handle())
                    source_db.add_citation(citation, trans)
                else:
                    citation = staging._citation(trans, parsed, source, title, result)

                incoming = Person()
                name = copy.deepcopy(person.get_primary_name())
                name.set_citation_list([])
                name.set_note_list([])
                incoming.set_primary_name(name)
                incoming.set_gender(person.get_gender())
                incoming.add_citation(citation.get_handle())

                for image in review.images:
                    if image.media_handle:
                        media = self.db.get_media_from_handle(image.media_handle)
                        if media is None:
                            continue
                        media = self._bare_copy(media)
                        source_db.add_media(media, trans)
                        handle = media.get_handle()
                    else:
                        handle = staging._add_media(
                            trans,
                            image,
                            image.url,
                            (descriptions or {}).get(image.index)
                            or _("%(title)s, image %(number)d of %(total)d")
                            % {
                                "title": title,
                                "number": image.index + 1,
                                "total": len(review.images),
                            },
                            (page_texts or {}).get(image.index, ""),
                        )
                    media_ref = MediaRef()
                    media_ref.set_reference_handle(handle)
                    incoming.add_media_reference(media_ref)
                source_db.add_person(incoming, trans)
        except Exception:
            source_db.close()
            raise
        return source_db, incoming.get_handle()

    @staticmethod
    def _bare_copy(obj: Any) -> Any:
        """
        Return a copy of a tree object, with the same handle, for the
        incoming database: notes, citations, media and tags are left off,
        since the merge reuses the tree's object as it is.
        """
        duplicate = copy.deepcopy(obj)
        for setter in (
            "set_note_list",
            "set_citation_list",
            "set_media_list",
            "set_tag_list",
        ):
            if hasattr(duplicate, setter):
                getattr(duplicate, setter)([])
        return duplicate

    def merged_images(
        self, person_handle: str, parsed: dict[str, Any]
    ) -> tuple[list[ImageStatus], list[ImageStatus]]:
        """
        Return the record's images in the person's gallery, and those of
        them that are linked by web address only (not downloaded yet).
        """
        person = self.db.get_person_from_handle(person_handle)
        if person is None:
            return [], []
        gallery = {ref.ref for ref in person.get_media_list()}
        review = self.review(person_handle, parsed)
        images = [image for image in review.images if image.media_handle in gallery]
        online = [
            image
            for image in images
            if image.media_path.startswith(("http://", "https://"))
        ]
        return images, online

    def finish_merge(
        self,
        person_handle: str,
        parsed: dict[str, Any],
        download: bool = False,
        progress: Callable[[int, int], bool] | None = None,
    ) -> AttachResult:
        """
        Tidy up after the merge window copied a record over: link the
        record's images in the person's gallery to the record's citation,
        and (when asked) download the ones linked by web address and point
        them at the downloaded files.

        :param progress: Called as progress(done, total) after each
            download; returning False cancels the rest.
        """
        result = AttachResult()
        images, online = self.merged_images(person_handle, parsed)
        citation = self._find_citation(parsed)
        if citation is not None:
            result.citation_handle = citation.get_handle()

        base = media_path(self.db)
        new_paths: dict[str, str] = {}
        if download:
            for done, image in enumerate(online, start=1):
                if result.cancelled:
                    break
                full_path = self.download_path(parsed, image)
                if os.path.isfile(full_path) and os.path.getsize(full_path) > 0:
                    result.already_downloaded += 1
                elif self._download(image.url, full_path):
                    result.downloaded += 1
                else:
                    result.failed.append(image.url)
                    full_path = ""
                if full_path:
                    new_paths[image.media_handle] = full_path
                if progress is not None and progress(done, len(online)) is False:
                    result.cancelled = True

        linked = {ref.ref for ref in citation.get_media_list()} if citation else set()
        to_link = [image for image in images if image.media_handle not in linked]
        if not new_paths and not (citation is not None and to_link):
            return result
        with DbTxn(
            _("Finish NARA record %s") % parsed.get("naid", ""), self.db
        ) as trans:
            for handle, full_path in new_paths.items():
                media = self.db.get_media_from_handle(handle)
                if media is None:
                    continue
                media.set_path(relative_path(full_path, base))
                media.set_checksum(create_checksum(full_path))
                self.db.commit_media(media, trans)
            if citation is not None and to_link:
                for image in to_link:
                    media_ref = MediaRef()
                    media_ref.set_reference_handle(image.media_handle)
                    citation.add_media_reference(media_ref)
                    result.media_linked += 1
                self.db.commit_citation(citation, trans)
        return result

    def _add_media(
        self,
        trans: DbTxn,
        image: ImageStatus,
        path: str,
        description: str,
        page_text: str = "",
        citation: Citation | None = None,
    ) -> str:
        """
        Add a media object for an image and return its handle; a page text
        becomes a Transcript note on it and is cross-referenced on the citation.
        """
        media = Media()
        media.set_path(path)
        media.set_mime_type(image.mime_type)
        media.set_description(description)
        if page_text.strip():
            note = Note(
                _(
                    "Text machine-read by the National Archives Catalog; it may "
                    "contain errors.\n\n%s"
                )
                % page_text.strip()
            )
            note.set_type(NoteType(NoteType.TRANSCRIPT))
            self.db.add_note(note, trans)
            media.add_note(note.get_handle())
            if (
                citation is not None
                and note.get_handle() not in citation.get_note_list()
            ):
                citation.add_note(note.get_handle())
        if not path.startswith(("http://", "https://")):
            media.set_checksum(create_checksum(os.path.join(media_path(self.db), path)))
        if image.object_id:
            attribute = Attribute()
            attribute.set_type(OBJECT_ID_ATTRIBUTE)
            attribute.set_value(image.object_id)
            media.add_attribute(attribute)
        return self.db.add_media(media, trans)

    def _fetch_images(
        self,
        parsed: dict[str, Any],
        images: list[ImageStatus],
        download: bool,
        progress: Callable[[int, int], bool] | None,
        result: AttachResult,
    ) -> dict[int, str]:
        """
        Download the new images (when asked) and return each usable image's
        media path by index: a path relative to the media base path, or the
        web address. Images already in the tree keep their own path.
        """
        paths: dict[int, str] = {}
        base = media_path(self.db)
        to_download = [image for image in images if not image.media_handle]
        for image in images:
            if image.media_handle:
                paths[image.index] = image.media_path
            elif image.url and not download:
                paths[image.index] = image.url
        if not download:
            return paths

        for done, image in enumerate(to_download, start=1):
            if result.cancelled or not image.url:
                continue
            full_path = self.download_path(parsed, image)
            if os.path.isfile(full_path) and os.path.getsize(full_path) > 0:
                result.already_downloaded += 1
                paths[image.index] = relative_path(full_path, base)
            elif self._download(image.url, full_path):
                result.downloaded += 1
                paths[image.index] = relative_path(full_path, base)
            else:
                result.failed.append(image.url)
                paths[image.index] = image.url
            if progress is not None and progress(done, len(to_download)) is False:
                result.cancelled = True
        return paths

    def download_one(self, parsed: dict[str, Any], image: ImageStatus) -> str:
        """
        Download one image for previewing (reusing a copy already on disk)
        and return its absolute path, or '' when it cannot be downloaded.
        """
        full_path = self.download_path(parsed, image)
        if os.path.isfile(full_path) and os.path.getsize(full_path) > 0:
            return full_path
        return full_path if self._download(image.url, full_path) else ""

    def _download(self, url: str, full_path: str) -> bool:
        """Download url to full_path; return False (and log why) on failure."""
        partial = full_path + ".part"
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            reply = self.session.get(
                url,
                stream=True,
                timeout=self.timeout,
                headers={"User-Agent": "Gramps-GWizard-NARA/1.0"},
            )
            if reply.status_code != 200:
                LOG.warning("NARA image %s: HTTP %s", url, reply.status_code)
                return False
            with open(partial, "wb") as out:
                for chunk in reply.iter_content(chunk_size=65536):
                    if chunk:
                        out.write(chunk)
            if os.path.getsize(partial) == 0:
                LOG.warning("NARA image %s: empty file", url)
                os.remove(partial)
                return False
            os.replace(partial, full_path)
            return True
        except (OSError, requests.RequestException) as err:
            LOG.warning("NARA image %s could not be downloaded: %s", url, err)
            try:
                if os.path.exists(partial):
                    os.remove(partial)
            except OSError:
                pass
            return False

    def _repository(self, trans: DbTxn, result: AttachResult) -> Repository:
        """Return the NARA repository, creating it when there is none."""
        existing = self._find_repository()
        if existing is not None:
            return existing
        repository = Repository()
        repository.set_name(NARA_REPOSITORY_NAME)
        repository.set_type(RepositoryType(RepositoryType.ARCHIVE))
        url = Url()
        url.set_path(NARA_REPOSITORY_URL)
        url.set_type(UrlType(UrlType.WEB_HOME))
        repository.add_url(url)
        self.db.add_repository(repository, trans)
        result.repository_created = True
        return repository

    def _find_repository(self) -> Repository | None:
        """Return the tree's NARA repository, or None."""
        wanted = NARA_REPOSITORY_NAME.casefold()
        for repository in self.db.iter_repositories():
            if str(repository.get_name() or "").strip().casefold() == wanted:
                return repository
        return None

    def _find_source(self, parsed: dict[str, Any], repo_handle: str) -> Source | None:
        """Return the tree's source for the record's series, or None."""
        title = parsed.get("series_title") or parsed.get("title") or ""
        for source in self.db.iter_sources():
            if str(source.get_title() or "").strip() != title.strip():
                continue
            if any(
                ref.get_reference_handle() == repo_handle
                for ref in source.get_reporef_list()
            ):
                return source
        return None

    def _source(
        self,
        trans: DbTxn,
        parsed: dict[str, Any],
        repository: Repository,
        result: AttachResult,
    ) -> Source:
        """Return the source for the record's series, creating it if needed."""
        title = parsed.get("series_title") or parsed.get("title") or ""
        series_naid = parsed.get("series_naid") or ""
        repo_handle = repository.get_handle()
        existing = self._find_source(parsed, repo_handle)
        if existing is not None:
            return existing

        source = Source()
        source.set_title(title)
        source.set_author("; ".join(parsed.get("creators") or []))
        if series_naid:
            source.set_publication_info(
                _("National Archives Identifier %s") % series_naid
            )
        repo_ref = RepoRef()
        repo_ref.set_reference_handle(repo_handle)
        if series_naid:
            repo_ref.set_call_number(_("NAID %s") % series_naid)
        source.add_repo_reference(repo_ref)
        self.db.add_source(source, trans)
        result.source_created = True
        return source

    @staticmethod
    def _page(parsed: dict[str, Any]) -> str:
        """Return the citation page text for a record."""
        title = parsed.get("title") or parsed.get("naid") or _("NARA record")
        return _("%(title)s (NAID %(naid)s)") % {
            "title": title,
            "naid": str(parsed.get("naid") or ""),
        }

    def _citation(
        self,
        trans: DbTxn,
        parsed: dict[str, Any],
        source: Source,
        title: str,
        result: AttachResult,
    ) -> Citation:
        """Return the citation for this record, creating it if needed."""
        naid = str(parsed.get("naid") or "")
        existing = self._find_citation(parsed)
        if existing is not None:
            return existing

        citation = Citation()
        citation.set_reference_handle(source.get_handle())
        citation.set_page(self._page(parsed))
        if naid:
            attribute = SrcAttribute()
            attribute.set_type(NAID_ATTRIBUTE)
            attribute.set_value(naid)
            citation.add_attribute(attribute)

        date_str = str(parsed.get("date_str") or "").strip()
        if date_str:
            try:
                date_obj = dateparser.parse(date_str)
                if not date_obj.is_empty():
                    citation.set_date_object(date_obj)
            except Exception:
                pass

        lines = [
            value
            for value in (
                parsed.get("web_url"),
                parsed.get("date_str"),
                parsed.get("scope_note"),
            )
            if value
        ]
        if lines:
            note = Note("\n".join(lines))
            note.set_type(NoteType(NoteType.CITATION))
            self.db.add_note(note, trans)
            citation.add_note(note.get_handle())
        self.db.add_citation(citation, trans)
        result.citation_created = True
        return citation

    @staticmethod
    def _detect_record_event_type(
        parsed: dict[str, Any], descriptions: dict[int, str] | None = None
    ) -> EventType | None:
        """
        Determine if the NARA record documents a specific genealogical event.
        """
        title = str(parsed.get("title") or "").strip()
        series = str(parsed.get("series_title") or "").strip()
        scope = str(parsed.get("scope_note") or "").strip()
        combined = f"{title} {series} {scope}".lower()

        desc_text = " ".join((descriptions or {}).values()).lower()

        if re.search(
            r"naturaliz|citizenship|declaration\s+of\s+intent|petition\s+for",
            combined,
        ):
            return EventType(EventType.NATURALIZATION)
        if "death record" in desc_text or re.search(
            r"certificate\s+of\s+death|death\s+certificate", combined
        ):
            return EventType(EventType.DEATH)
        if "marriage record" in desc_text or re.search(
            r"marriage\s+certificate|marriage\s+record|proof\s+of\s+marriage",
            combined,
        ):
            return EventType(EventType.MARRIAGE)
        if (
            "claim brief" in desc_text
            or "pension claim form" in desc_text
            or re.search(r"\bpension\b|widow'?s\s+claim", combined)
        ):
            return EventType((EventType.CUSTOM, "Pension"))
        if "service report" in desc_text or re.search(
            r"military|service\s+record|confederate|union\s+army|civil\s+war|enlistment|mustered",
            combined,
        ):
            return EventType(EventType.MILITARY_SERV)
        if re.search(r"\bcensus\b|population\s+schedule", combined):
            return EventType(EventType.CENSUS)

        return None

    def _link_or_create_event(
        self,
        person: Person,
        event_type: EventType,
        citation: Citation,
        parsed: dict[str, Any],
        trans: DbTxn,
    ) -> Event | None:
        """
        Attach the citation to an existing matching event on the person,
        or create a new event for this record and link it to the person.
        """
        target_event: Event | None = None

        if int(event_type) == EventType.DEATH:
            death_ref = person.get_death_ref()
            if death_ref and death_ref.ref:
                target_event = self.db.get_event_from_handle(death_ref.ref)
        elif int(event_type) == EventType.MARRIAGE:
            for fam_handle in person.get_family_handle_list():
                fam = self.db.get_family_from_handle(fam_handle)
                if not fam:
                    continue
                for ref in fam.get_event_ref_list():
                    evt = self.db.get_event_from_handle(ref.ref)
                    if evt and int(evt.get_type()) == EventType.MARRIAGE:
                        target_event = evt
                        break
                if target_event:
                    break
        else:
            for ref in person.get_event_ref_list():
                evt = self.db.get_event_from_handle(ref.ref)
                if evt and int(evt.get_type()) == int(event_type):
                    target_event = evt
                    break

        if target_event is not None:
            if citation.get_handle() not in target_event.get_citation_list():
                target_event.add_citation(citation.get_handle())
                self.db.commit_event(target_event, trans)
            return target_event

        # No existing event found: create a new one
        new_event = Event()
        new_event.set_type(event_type)
        date_str = str(parsed.get("date_str") or "").strip()
        if date_str:
            try:
                date_obj = dateparser.parse(date_str)
                if not date_obj.is_empty():
                    new_event.set_date_object(date_obj)
            except Exception:
                pass

        title = str(parsed.get("title") or parsed.get("naid") or "")
        if title:
            new_event.set_description(title)

        new_event.add_citation(citation.get_handle())
        new_handle = self.db.add_event(new_event, trans)

        ref = EventRef()
        ref.ref = new_handle
        ref.role = EventRoleType.PRIMARY

        if int(event_type) == EventType.DEATH and not person.get_death_ref():
            person.set_death_ref(ref)
        else:
            person.add_event_ref(ref)

        self.db.commit_person(person, trans)
        return new_event
