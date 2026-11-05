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
import os
import re
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.config import config
from gramps.gen.datehandler import parser as dateparser
from gramps.gen.lib import (
    Person,
    Name,
    Surname,
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
)
from gramps.gen.const import GRAMPS_LOCALE as glocale

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .gwizardgedcom import GedGWizard

LOG = logging.getLogger(__name__)
_ = glocale.translation.gettext


# ------------------------------------------------------------
#
# NaraCatalogInterface
#
# ------------------------------------------------------------
class NaraCatalogInterface:
    """
    Interface client for the National Archives and Records Administration
    (NARA) Catalog API v2.
    """

    DEFAULT_BASE_URL = "https://catalog.archives.gov/api/v2"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        verify_ssl: bool | str | None = None,
    ) -> None:
        """
        Initialize the NARA Catalog interface.

        :param api_key: NARA API key (optional for public endpoints, required
            by NARA for higher rate quotas).
        :param base_url: Base URL for NARA Catalog API v2.
        :param verify_ssl: SSL certificate verification flag or path to CA bundle.
        """
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Gramps-GWizard-NARA/1.0",
        }
        if self.api_key:
            self.headers["x-api-key"] = self.api_key

        if verify_ssl is not None:
            self.verify_ssl = verify_ssl
        else:
            # Check environment or known system CA bundle
            ca_env = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get(
                "SSL_CERT_FILE"
            )
            if ca_env and os.path.isfile(ca_env):
                self.verify_ssl: bool | str = ca_env
            else:
                user_combined = os.path.expanduser(r"~\certs\COMBINED_PEM.pem")
                if os.path.isfile(user_combined):
                    self.verify_ssl = user_combined
                else:
                    self.verify_ssl = True

    def search_records(
        self,
        query: str,
        rows: int = 10,
        material_type: str | None = None,
        available_online: bool | None = None,
        timeout: int = 30,
    ) -> dict[str, Any] | None:
        """
        Search the NARA Catalog for archival records.

        :param query: Search query or string (e.g. person name, subject).
        :param rows: Number of records to return per request (default: 10).
        :param material_type: Filter by material type (e.g. 'textual records').
        :param available_online: Restrict to digitized online records.
        :param timeout: Request timeout in seconds.
        :returns: JSON response dictionary or None on failure.
        """
        import requests

        endpoint = f"{self.base_url}/records/search"
        params: dict[str, Any] = {
            "q": query,
            "limit": max(1, min(rows, 100)),
        }
        if material_type:
            params["typeOfMaterials"] = material_type
        if available_online is not None:
            params["availableOnline"] = str(available_online).lower()

        try:
            response = requests.get(
                endpoint,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as err:
                    LOG.error("Failed to parse NARA API response as JSON: %s", err)
                    return None
            else:
                LOG.warning(
                    "NARA API error %d: %s", response.status_code, response.text[:200]
                )
                return None
        except requests.exceptions.RequestException as err:
            LOG.error("NARA API request failed: %s", err)
            return None

    @staticmethod
    def extract_hits(response_data: dict[str, Any] | None) -> list[dict[str, Any]]:
        """
        Extract the list of record hits from a NARA search response.

        :param response_data: Parsed response dictionary from the NARA API.
        :returns: List of hit dictionaries.
        """
        if not response_data or not isinstance(response_data, dict):
            return []
        body = response_data.get("body")
        if isinstance(body, dict):
            hits_obj = body.get("hits")
            if isinstance(hits_obj, dict):
                hits = hits_obj.get("hits")
                if isinstance(hits, list):
                    return hits
        hits = response_data.get("hits")
        if isinstance(hits, list):
            return hits
        return []

    @staticmethod
    def parse_record(hit: dict[str, Any]) -> dict[str, Any]:
        """
        Extract structured fields from a single hit record.

        :param hit: Raw hit dictionary from NARA API.
        :returns: Normalized dictionary containing metadata fields.
        """
        source = hit.get("_source", {}) if isinstance(hit, dict) else {}
        record = source.get("record", {}) if isinstance(source, dict) else {}

        naid = str(source.get("naId") or hit.get("_id") or "")
        title = str(record.get("title") or _("National Archives Record"))

        creators: list[str] = []
        authors = record.get("authors", {})
        if isinstance(authors, dict):
            creator_list = authors.get("creator", [])
            if isinstance(creator_list, list):
                for item in creator_list:
                    if isinstance(item, dict) and "heading" in item:
                        creators.append(str(item["heading"]))

        digital_objects: list[dict[str, str]] = []
        raw_digital = record.get("digitalObjects", [])
        if isinstance(raw_digital, list):
            for obj in raw_digital:
                if isinstance(obj, dict):
                    url = obj.get("objectUrl") or obj.get("url") or ""
                    mime = obj.get("mimeType") or obj.get("objectType") or "image/jpeg"
                    if url:
                        digital_objects.append({"url": str(url), "mime": str(mime)})
        elif isinstance(raw_digital, dict):
            url = raw_digital.get("objectUrl") or raw_digital.get("url") or ""
            mime = (
                raw_digital.get("mimeType")
                or raw_digital.get("objectType")
                or "image/jpeg"
            )
            if url:
                digital_objects.append({"url": str(url), "mime": str(mime)})

        scope_note = str(record.get("scopeAndContentNote") or "")
        material_type = str(record.get("typeOfMaterials") or "")

        date_str = ""
        dates_raw = record.get("dates") or record.get("productionDateArray")
        if isinstance(dates_raw, list) and dates_raw:
            first_date = dates_raw[0]
            if isinstance(first_date, dict):
                date_str = str(
                    first_date.get("date")
                    or first_date.get("startDate")
                    or first_date.get("year")
                    or ""
                )
            elif isinstance(first_date, str):
                date_str = first_date
        elif isinstance(dates_raw, dict):
            date_str = str(
                dates_raw.get("date")
                or dates_raw.get("startDate")
                or dates_raw.get("year")
                or ""
            )
        elif isinstance(dates_raw, str):
            date_str = dates_raw

        return {
            "naid": naid,
            "title": title,
            "creators": creators,
            "digital_objects": digital_objects,
            "scope_note": scope_note,
            "material_type": material_type,
            "date_str": date_str,
            "web_url": f"https://catalog.archives.gov/id/{naid}" if naid else "",
        }


# ------------------------------------------------------------
#
# NaraGWizard
#
# ------------------------------------------------------------
class NaraGWizard(GedGWizard):
    """
    GWizard implementation for querying and merging National Archives (NARA)
    records into an active Gramps database.
    """

    def __init__(self, db: DbWriteBase) -> None:
        """
        Initialize the NaraGWizard.

        :param db: The target Gramps database instance.
        """
        super().__init__(db)

    def _connect(self, **kwargs: Any) -> bool:
        """
        Configure connection details for the NARA query.

        :param query: Search query or string (required).
        :param api_key: NARA API key (optional).
        :param limit: Maximum records to retrieve (default: 10).
        :param material_type: Filter by material type.
        :param client: Optional pre-configured NaraCatalogInterface instance.
        :param hits: Optional pre-fetched hits list for offline/testing use.
        :returns: True if query parameter is provided.
        :rtype: bool
        """
        query = kwargs.get("query", "").strip()
        hits = kwargs.get("hits")
        if not query and hits is None:
            LOG.error("A search query or hits list is required for NARA merge.")
            return False

        self.context["query"] = query
        self.context["api_key"] = kwargs.get("api_key", "").strip()
        self.context["limit"] = kwargs.get("limit", 10)
        self.context["material_type"] = kwargs.get("material_type")
        self.context["client"] = kwargs.get("client")
        self.context["hits"] = hits
        return True

    @staticmethod
    def _parse_person_name(
        raw_name: str,
    ) -> tuple[str, str, str, str]:
        """
        Parse a person name string and optional birth/death years.

        :param raw_name: Name string (e.g. "Lincoln, Abraham, 1809-1865").
        :returns: Tuple of (given_name, surname, birth_year, death_year).
        """
        text = raw_name.strip()
        birth_year = ""
        death_year = ""

        # Extract birth-death years if present (e.g., "1809-1865" or "1809-")
        year_match = re.search(r"\b(\d{4})\s*-\s*(\d{4})?\b", text)
        if year_match:
            birth_year = year_match.group(1) or ""
            death_year = year_match.group(2) or ""
            text = text[: year_match.start()].strip(" ,;-")

        if "," in text:
            parts = [p.strip() for p in text.split(",", 1)]
            surname = parts[0]
            given_name = parts[1] if len(parts) > 1 else ""
        else:
            tokens = text.split()
            if len(tokens) >= 2:
                given_name = " ".join(tokens[:-1])
                surname = tokens[-1]
            elif len(tokens) == 1:
                given_name = tokens[0]
                surname = ""
            else:
                given_name = text
                surname = ""

        return given_name, surname, birth_year, death_year

    def _load(self, **kwargs: Any) -> list[Person]:
        """
        Load records from the NARA Catalog API into an in-memory database.

        :returns: A list of Person objects loaded from NARA records.
        :rtype: list[Person]
        """
        query = self.context.get("query", "")
        hits = self.context.get("hits")
        client = self.context.get("client")

        if hits is None:
            if client is None:
                api_key = self.context.get("api_key", "")
                client = NaraCatalogInterface(api_key=api_key)
            limit = int(self.context.get("limit", 10))
            material_type = self.context.get("material_type")
            response = client.search_records(
                query=query, rows=limit, material_type=material_type
            )
            hits = client.extract_hits(response)

        source_db = make_database("sqlite")
        source_db.load(":memory:")
        source_db.set_prefixes(
            config.get("preferences.iprefix"),
            config.get("preferences.oprefix"),
            config.get("preferences.fprefix"),
            config.get("preferences.sprefix"),
            config.get("preferences.cprefix"),
            config.get("preferences.pprefix"),
            config.get("preferences.eprefix"),
            config.get("preferences.rprefix"),
            config.get("preferences.nprefix"),
            config.get("preferences.tprefix"),
            config.get("preferences.mprefix"),
        )

        with DbTxn(_("Load NARA Records"), source_db) as trans:
            # 1. Create Repository
            repo = Repository()
            repo.set_name(_("National Archives and Records Administration (NARA)"))
            repo.set_type(RepositoryType(RepositoryType.ARCHIVE))
            repo_handle = source_db.add_repository(repo, trans)

            # 2. Create Source
            source = Source()
            source_title = (
                _("National Archives Catalog - %s") % query
                if query
                else _("National Archives Catalog")
            )
            source.set_title(source_title)
            source.set_author(_("National Archives and Records Administration"))
            source.set_publication_info("https://catalog.archives.gov")
            repo_ref = RepoRef()
            repo_ref.ref = repo_handle
            source.add_repo_reference(repo_ref)
            source_handle = source_db.add_source(source, trans)

            # 3. Process each hit record
            for hit in hits:
                parsed = NaraCatalogInterface.parse_record(hit)
                naid = parsed["naid"]
                title = parsed["title"]
                creators = parsed["creators"]
                scope_note = parsed["scope_note"]
                date_str = parsed["date_str"]
                web_url = parsed["web_url"]
                digital_objects = parsed["digital_objects"]

                # Create Citation
                citation = Citation()
                citation.set_reference_handle(source_handle)
                citation.set_page(f"NAID: {naid}" if naid else title)

                # Citation note with web link and scope summary
                cit_note_lines = []
                if web_url:
                    cit_note_lines.append(f"URL: {web_url}")
                if scope_note:
                    cit_note_lines.append(scope_note)
                if cit_note_lines:
                    cit_note = Note()
                    cit_note.set("\n\n".join(cit_note_lines))
                    cit_note_handle = source_db.add_note(cit_note, trans)
                    citation.add_note(cit_note_handle)

                # Media objects for digital assets
                for item in digital_objects:
                    media = Media()
                    media.set_path(item["url"])
                    media.set_description(f"{title} (NAID {naid})")
                    media.set_mime_type(item["mime"])
                    media_handle = source_db.add_media(media, trans)
                    mref = MediaRef()
                    mref.ref = media_handle
                    citation.add_media_reference(mref)

                cit_handle = source_db.add_citation(citation, trans)
                creators_to_process = creators if creators else [query or title]

                for raw_name in creators_to_process:
                    given, surname, birth_yr, death_yr = self._parse_person_name(
                        raw_name
                    )

                    person = Person()
                    name_obj = Name()
                    name_obj.set_first_name(given)
                    if surname:
                        surn_obj = Surname()
                        surn_obj.set_surname(surname)
                        name_obj.add_surname(surn_obj)
                    person.set_primary_name(name_obj)

                    # Link citation to person
                    person.add_citation(cit_handle)

                    # Add person note if scope note exists
                    if scope_note:
                        p_note = Note()
                        p_note.set(f"{title}\n\n{scope_note}")
                        p_note_handle = source_db.add_note(p_note, trans)
                        person.add_note(p_note_handle)

                    # Add birth / death events if parsed
                    if birth_yr:
                        b_evt = Event()
                        b_evt.set_type(EventType(EventType.BIRTH))
                        b_evt.set_date_object(dateparser.parse(birth_yr))
                        b_evt.add_citation(cit_handle)
                        b_handle = source_db.add_event(b_evt, trans)
                        b_ref = EventRef()
                        b_ref.ref = b_handle
                        person.add_event_ref(b_ref)

                    if death_yr:
                        d_evt = Event()
                        d_evt.set_type(EventType(EventType.DEATH))
                        d_evt.set_date_object(dateparser.parse(death_yr))
                        d_evt.add_citation(cit_handle)
                        d_handle = source_db.add_event(d_evt, trans)
                        d_ref = EventRef()
                        d_ref.ref = d_handle
                        person.add_event_ref(d_ref)

                    # General record date event if date_str present and not already birth/death
                    if date_str and not birth_yr:
                        rec_evt = Event()
                        rec_evt.set_type(EventType(EventType.CUSTOM))
                        rec_evt.set_description(title)
                        rec_evt.set_date_object(dateparser.parse(date_str))
                        rec_evt.add_citation(cit_handle)
                        rec_handle = source_db.add_event(rec_evt, trans)
                        rec_ref = EventRef()
                        rec_ref.ref = rec_handle
                        person.add_event_ref(rec_ref)

                    source_db.add_person(person, trans)

        self.context["source_db"] = source_db
        display_name = f"NARA: {query}" if query else _("NARA Catalog")
        self.context["source_title"] = display_name
        self.context["gedcom_path"] = display_name

        people: list[Person] = []
        for handle in source_db.iter_person_handles():
            p = source_db.get_person_from_handle(handle)
            if p:
                people.append(p)

        return people
