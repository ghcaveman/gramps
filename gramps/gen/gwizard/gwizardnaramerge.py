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
    EventType,
    Citation,
    Source,
    Repository,
    RepositoryType,
    RepoRef,
    Media,
    MediaRef,
    Note,
    NoteType,
    Url,
    UrlType,
)
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
            except TypeError, ValueError:
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
    ) -> dict[str, Any] | None:
        """Search the NARA catalog and return its decoded response."""
        params: dict[str, str | int] = {"q": query, "limit": rows}
        if material_type:
            params["typeOfMaterials"] = material_type
        if available_online:
            params["availableOnline"] = "true"

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
                parsed_media.append(
                    {
                        "url": str(url),
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


@dataclass
class AttachResult:
    """What attaching one NARA record to a person did."""

    citation_handle: str = ""
    repository_created: bool = False
    source_created: bool = False
    citation_created: bool = False
    person_linked: bool = False
    media_added: int = 0
    downloaded: int = 0
    already_downloaded: int = 0
    failed: list[str] = field(default_factory=list)
    cancelled: bool = False


class NaraRecordAttacher:
    """
    Attach a NARA catalog record to an existing person as a source and
    citation, with the record's images as media linked to the citation.

    - Repository: NARA, reused when one with the same name exists.
    - Source: the record's series (or the record itself when it has no
      series), reused when a NARA source with that title exists.
    - Citation: the record (title and NAID) with a note holding its catalog
      link and description, reused when attached before.
    - Media: one object per image, linked to the citation. Downloaded images
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

    def download_folder(self, naid: str) -> str:
        """Return the absolute folder a record's images are downloaded to."""
        return os.path.join(media_path(self.db), NARA_MEDIA_FOLDER, naid or "unknown")

    def attach(
        self,
        person_handle: str,
        parsed: dict[str, Any],
        download: bool = True,
        max_images: int = 0,
        progress: Callable[[int, int], bool] | None = None,
    ) -> AttachResult:
        """
        Attach a parsed NARA record (see NaraCatalogInterface.parse_record).

        :param person_handle: Handle of the person to attach the record to.
        :param parsed: The parsed record.
        :param download: Download the images (otherwise link them by URL).
        :param max_images: Most images to add; 0 means all.
        :param progress: Called as progress(done, total) after each image is
            downloaded; returning False cancels the remaining downloads. The
            images already downloaded are still added.
        :returns: What was done.
        """
        person = self.db.get_person_from_handle(person_handle)
        if person is None:
            raise RuntimeError(_("The target person could not be found."))

        result = AttachResult()
        objects = list(parsed.get("digital_objects") or [])
        if max_images > 0:
            objects = objects[:max_images]
        images = self._fetch_images(parsed, objects, download, progress, result)

        title = parsed.get("title") or parsed.get("naid") or _("NARA record")
        with DbTxn(
            _("Attach NARA record %s") % parsed.get("naid", ""), self.db
        ) as trans:
            repository = self._repository(trans, result)
            source = self._source(trans, parsed, repository, result)
            citation = self._citation(trans, parsed, source, title, result)
            result.citation_handle = citation.get_handle()

            existing = {
                str(media.get_path()): media.get_handle()
                for media in self.db.iter_media()
            }
            linked = {ref.ref for ref in citation.get_media_list()}
            for number, (path, mime_type) in enumerate(images, start=1):
                handle = existing.get(path)
                if handle is None:
                    media = Media()
                    media.set_path(path)
                    media.set_mime_type(mime_type)
                    media.set_description(
                        _("%(title)s, image %(number)d")
                        % {"title": title, "number": number}
                    )
                    if not path.startswith(("http://", "https://")):
                        full_path = os.path.join(media_path(self.db), path)
                        media.set_checksum(create_checksum(full_path))
                    handle = self.db.add_media(media, trans)
                    existing[path] = handle
                    result.media_added += 1
                if handle not in linked:
                    media_ref = MediaRef()
                    media_ref.set_reference_handle(handle)
                    citation.add_media_reference(media_ref)
                    linked.add(handle)
            self.db.commit_citation(citation, trans)

            if citation.get_handle() not in person.get_citation_list():
                person.add_citation(citation.get_handle())
                self.db.commit_person(person, trans)
                result.person_linked = True
        return result

    def _fetch_images(
        self,
        parsed: dict[str, Any],
        objects: list[dict[str, Any]],
        download: bool,
        progress: Callable[[int, int], bool] | None,
        result: AttachResult,
    ) -> list[tuple[str, str]]:
        """
        Download the images (when asked) and return (media path, MIME type)
        for each: a path relative to the media base path, or the web address.
        """
        images: list[tuple[str, str]] = []
        folder = self.download_folder(str(parsed.get("naid") or ""))
        base = media_path(self.db)
        for number, digital_object in enumerate(objects, start=1):
            url = str(digital_object.get("url") or "")
            mime_type = str(digital_object.get("mime_type") or "")
            if not url:
                continue
            if result.cancelled or not download:
                if not result.cancelled:
                    images.append((url, mime_type))
                continue

            name = os.path.basename(url.split("?", 1)[0]) or f"image_{number}"
            full_path = os.path.join(folder, name)
            if os.path.isfile(full_path) and os.path.getsize(full_path) > 0:
                result.already_downloaded += 1
                images.append((relative_path(full_path, base), mime_type))
            elif self._download(url, full_path):
                result.downloaded += 1
                images.append((relative_path(full_path, base), mime_type))
            else:
                result.failed.append(url)
                images.append((url, mime_type))

            if progress is not None and progress(number, len(objects)) is False:
                result.cancelled = True
        return images

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
        wanted = NARA_REPOSITORY_NAME.casefold()
        for repository in self.db.iter_repositories():
            if str(repository.get_name() or "").strip().casefold() == wanted:
                return repository
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
        for source in self.db.iter_sources():
            if str(source.get_title() or "").strip() != title.strip():
                continue
            if any(
                ref.get_reference_handle() == repo_handle
                for ref in source.get_reporef_list()
            ):
                return source

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
        page = _("%(title)s (NAID %(naid)s)") % {"title": title, "naid": naid}
        for class_name, handle in self.db.find_backlink_handles(
            source.get_handle(), ["Citation"]
        ):
            citation = self.db.get_citation_from_handle(handle)
            if citation and citation.get_page() == page:
                return citation

        citation = Citation()
        citation.set_reference_handle(source.get_handle())
        citation.set_page(page)
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
