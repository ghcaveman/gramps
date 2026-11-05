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
WikiTree implementation of the GWizard import and merge framework.
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
    NoteType,
    Place,
    PlaceName,
    Attribute,
    AttributeType,
    Family,
    ChildRef,
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

_DEFAULT_FIELDS = (
    "Id,Name,FirstName,MiddleName,LastNameBirth,LastNameCurrent,LastNameOther,"
    "RealName,Prefix,Suffix,Nicknames,Gender,BirthDate,DeathDate,BirthLocation,"
    "DeathLocation,BirthDateStatus,DeathDateStatus,Photo,PhotoData,Parents,Children,Spouses,Bio"
)


# ------------------------------------------------------------
#
# WikiTreeInterface
#
# ------------------------------------------------------------
class WikiTreeInterface:
    """
    Interface client for the WikiTree REST API.
    """

    DEFAULT_BASE_URL = "https://api.wikitree.com/api.php"
    DEFAULT_APP_ID = "Gramps_GWizard_1.0"

    def __init__(
        self,
        app_id: str = DEFAULT_APP_ID,
        base_url: str = DEFAULT_BASE_URL,
        verify_ssl: bool | str | None = None,
    ) -> None:
        """
        Initialize the WikiTree API client.

        :param app_id: Application identifier requested by WikiTree.
        :param base_url: Base URL for WikiTree API endpoint.
        :param verify_ssl: SSL certificate verification flag or CA bundle path.
        """
        self.app_id = app_id.strip() or self.DEFAULT_APP_ID
        self.base_url = base_url.rstrip("/")
        self.headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": f"Gramps-GWizard-WikiTree/{self.app_id}",
        }

        if verify_ssl is not None:
            self.verify_ssl = verify_ssl
        else:
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

    def get_person(
        self,
        key: str,
        fields: str = _DEFAULT_FIELDS,
        timeout: int = 30,
    ) -> dict[str, Any] | None:
        """
        Fetch profile details for a single WikiTree ID or key.

        :param key: WikiTree ID (e.g. 'Franklin-1' or integer ID).
        :param fields: Comma-separated list of profile fields to retrieve.
        :param timeout: HTTP request timeout in seconds.
        :returns: Dictionary of person fields, or None if not found or on error.
        """
        import requests

        params = {
            "action": "getPerson",
            "key": key,
            "fields": fields,
            "appId": self.app_id,
        }
        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    item = data[0]
                    if isinstance(item, dict) and item.get("status") == 0:
                        return item.get("person")
            else:
                LOG.warning("WikiTree API getPerson returned %d", response.status_code)
        except Exception as err:
            LOG.error("WikiTree getPerson failed: %s", err)
        return None

    def get_people(
        self,
        keys: str | list[str],
        ancestors: int = 0,
        descendants: int = 0,
        fields: str = _DEFAULT_FIELDS,
        timeout: int = 30,
    ) -> dict[str, dict[str, Any]]:
        """
        Query multiple IDs or ancestor/descendant trees simultaneously.

        :param keys: Single WikiTree key or list of keys.
        :param ancestors: Generations of ancestors to retrieve (0 to 10).
        :param descendants: Generations of descendants to retrieve (0 to 10).
        :param fields: Comma-separated list of fields.
        :param timeout: HTTP request timeout.
        :returns: Dictionary mapping person ID/key to profile dictionary.
        """
        import requests

        keys_str = ",".join(keys) if isinstance(keys, list) else str(keys)
        params: dict[str, Any] = {
            "action": "getPeople",
            "keys": keys_str,
            "fields": fields,
            "appId": self.app_id,
        }
        if ancestors > 0:
            params["ancestors"] = min(ancestors, 10)
        if descendants > 0:
            params["descendants"] = min(descendants, 10)

        results: dict[str, dict[str, Any]] = {}
        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    item = data[0]
                    if isinstance(item, dict) and "people" in item:
                        people_dict = item["people"]
                        if isinstance(people_dict, dict):
                            for pid, pdata in people_dict.items():
                                if isinstance(pdata, dict):
                                    results[str(pid)] = pdata
            else:
                LOG.warning("WikiTree getPeople returned %d", response.status_code)
        except Exception as err:
            LOG.error("WikiTree getPeople failed: %s", err)
        return results

    def search_person(
        self,
        first_name: str = "",
        last_name: str = "",
        limit: int = 10,
        timeout: int = 30,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Fuzzy search for persons across names and dates.

        :param first_name: First/given name.
        :param last_name: Last/surname.
        :param limit: Maximum records to return.
        :param timeout: HTTP request timeout.
        :returns: List of matching profile dictionaries.
        """
        import requests

        params: dict[str, Any] = {
            "action": "searchPerson",
            "limit": max(1, min(limit, 50)),
            "appId": self.app_id,
        }
        if first_name:
            params["FirstName"] = first_name
        if last_name:
            params["LastName"] = last_name

        for key, val in kwargs.items():
            if val is not None:
                params[key] = val

        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    item = data[0]
                    if isinstance(item, dict) and item.get("status") == 0:
                        matches = item.get("matches", [])
                        if isinstance(matches, list):
                            return matches
            else:
                LOG.warning("WikiTree searchPerson returned %d", response.status_code)
        except Exception as err:
            LOG.error("WikiTree searchPerson failed: %s", err)
        return []

    def get_bio(self, key: str, timeout: int = 30) -> str:
        """
        Retrieve biography markdown text for a person.

        :param key: WikiTree ID.
        :param timeout: HTTP request timeout.
        :returns: Biography text string.
        """
        import requests

        params = {
            "action": "getBio",
            "key": key,
            "appId": self.app_id,
        }
        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    item = data[0]
                    if isinstance(item, dict):
                        return str(item.get("bio") or "")
        except Exception as err:
            LOG.error("WikiTree getBio failed: %s", err)
        return ""


# ------------------------------------------------------------
#
# WikiTreeGWizard
#
# ------------------------------------------------------------
class WikiTreeGWizard(GedGWizard):
    """
    GWizard implementation for querying and merging WikiTree genealogical
    profiles into an active Gramps database.
    """

    WT_ID_REGEX = re.compile(r"^[A-Za-z]+-\d+$")

    def __init__(self, db: DbWriteBase) -> None:
        """
        Initialize the WikiTreeGWizard.

        :param db: The target Gramps database instance.
        """
        super().__init__(db)

    @classmethod
    def is_wikitree_id(cls, value: str) -> bool:
        """
        Check if a string matches the standard WikiTree ID pattern.

        :param value: String to test (e.g. 'Franklin-1').
        :returns: True if value matches '<Surname>-<Number>'.
        """
        return bool(cls.WT_ID_REGEX.match(value.strip()))

    def _connect(self, **kwargs: Any) -> bool:
        """
        Configure connection details for the WikiTree query.

        :param query: Search query or WikiTree ID (required).
        :param ancestors: Ancestor generations to crawl (0 to 10).
        :param include_relatives: Whether to fetch spouses and children.
        :param app_id: Custom WikiTree App ID.
        :param client: Optional pre-configured WikiTreeInterface instance.
        :param people_data: Optional pre-fetched list/dict of profile data for tests.
        :returns: True if query or people_data is configured.
        """
        query = kwargs.get("query", "").strip()
        people_data = kwargs.get("people_data")
        if not query and people_data is None:
            LOG.error("A search query or people data is required for WikiTree merge.")
            return False

        self.context["query"] = query
        self.context["ancestors"] = int(kwargs.get("ancestors", 0))
        self.context["include_relatives"] = bool(kwargs.get("include_relatives", False))
        self.context["app_id"] = kwargs.get("app_id", WikiTreeInterface.DEFAULT_APP_ID)
        self.context["client"] = kwargs.get("client")
        self.context["people_data"] = people_data
        return True

    @staticmethod
    def _clean_date_str(raw_date: str) -> str:
        """
        Normalize WikiTree dates by removing unknown month/day zeros.

        :param raw_date: Date string (e.g. '1706-00-00' or '0000-00-00').
        :returns: Normalized date string for Gramps date parser.
        """
        val = raw_date.strip()
        if not val or val == "0000-00-00":
            return ""
        if val.endswith("-00-00"):
            return val[:-6]
        if val.endswith("-00"):
            return val[:-3]
        return val

    @staticmethod
    def _parse_query_names(query: str) -> tuple[str, str]:
        """
        Split a human name query into first name and last name.

        :param query: Search query string.
        :returns: Tuple of (first_name, last_name).
        """
        text = query.strip()
        if "," in text:
            parts = [p.strip() for p in text.split(",", 1)]
            return parts[1], parts[0]
        tokens = text.split()
        if len(tokens) >= 2:
            return " ".join(tokens[:-1]), tokens[-1]
        elif len(tokens) == 1:
            return "", tokens[0]
        return "", ""

    def _load(self, **kwargs: Any) -> list[Person]:
        """
        Load records from WikiTree into an in-memory database.

        :returns: A list of Person objects loaded from WikiTree.
        :rtype: list[Person]
        """
        query = self.context.get("query", "")
        people_data = self.context.get("people_data")
        client = self.context.get("client")
        ancestors_depth = int(self.context.get("ancestors", 0))

        if client is None:
            app_id = self.context.get("app_id", WikiTreeInterface.DEFAULT_APP_ID)
            client = WikiTreeInterface(app_id=app_id)

        raw_people: list[dict[str, Any]] = []

        if people_data is not None:
            if isinstance(people_data, dict):
                raw_people = list(people_data.values())
            elif isinstance(people_data, list):
                raw_people = people_data
        else:
            if self.is_wikitree_id(query):
                # Direct lookup by WikiTree ID
                if ancestors_depth > 0:
                    people_map = client.get_people(query, ancestors=ancestors_depth)
                    raw_people = list(people_map.values())
                else:
                    person_dict = client.get_person(query)
                    if person_dict:
                        raw_people = [person_dict]
            else:
                # Name search
                fn, ln = self._parse_query_names(query)
                matches = client.search_person(first_name=fn, last_name=ln, limit=10)
                for match in matches:
                    wt_id = match.get("Name")
                    if wt_id and self.is_wikitree_id(str(wt_id)):
                        full_prof = client.get_person(str(wt_id))
                        if full_prof:
                            raw_people.append(full_prof)
                        else:
                            raw_people.append(match)
                    else:
                        raw_people.append(match)

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

        place_cache: dict[str, str] = {}
        person_handle_map: dict[str, str] = {}  # wt_id or str(Id) -> person_handle

        def get_or_create_place(title: str, trans: DbTxn) -> str:
            clean = title.strip()
            if not clean:
                return ""
            if clean in place_cache:
                return place_cache[clean]
            p = Place()
            pname = PlaceName()
            pname.set_value(clean)
            p.set_name(pname)
            p.set_title(clean)
            h = source_db.add_place(p, trans)
            place_cache[clean] = h
            return h

        with DbTxn(_("Load WikiTree Records"), source_db) as trans:
            # 1. Create Repository
            repo = Repository()
            repo.set_name(_("WikiTree (Free Family Tree)"))
            repo.set_type(RepositoryType(RepositoryType.WEBSITE))
            repo_handle = source_db.add_repository(repo, trans)

            # 2. Create Source
            source = Source()
            source_title = _("WikiTree - %s") % query if query else _("WikiTree")
            source.set_title(source_title)
            source.set_author(_("WikiTree Community"))
            source.set_publication_info("https://www.wikitree.com")
            repo_ref = RepoRef()
            repo_ref.ref = repo_handle
            source.add_repo_reference(repo_ref)
            source_handle = source_db.add_source(source, trans)

            # 3. Create Person records
            for pdata in raw_people:
                wt_key = str(pdata.get("Name") or "")
                num_id = str(pdata.get("Id") or "")
                first_name = str(pdata.get("FirstName") or "")
                middle_name = str(pdata.get("MiddleName") or "")
                last_name_birth = str(
                    pdata.get("LastNameBirth") or pdata.get("LastNameAtBirth") or ""
                )
                last_name_current = str(pdata.get("LastNameCurrent") or "")
                prefix = str(pdata.get("Prefix") or "")
                suffix = str(pdata.get("Suffix") or "")
                nicknames = str(pdata.get("Nicknames") or "")
                real_name = str(pdata.get("RealName") or "")

                given = first_name
                if middle_name and middle_name not in given:
                    given = f"{given} {middle_name}".strip()
                if not given and real_name:
                    given = real_name

                surname_val = last_name_birth or last_name_current

                person = Person()
                name_obj = Name()
                name_obj.set_first_name(given)
                if surname_val:
                    surn_obj = Surname()
                    surn_obj.set_surname(surname_val)
                    name_obj.add_surname(surn_obj)
                if prefix:
                    name_obj.set_title(prefix)
                if suffix:
                    name_obj.set_suffix(suffix)
                if nicknames:
                    name_obj.set_nick_name(nicknames)
                person.set_primary_name(name_obj)

                # Alternate name if current surname differs from birth surname
                if (
                    last_name_current
                    and last_name_birth
                    and last_name_current != last_name_birth
                ):
                    alt_name = Name()
                    alt_name.set_first_name(given)
                    alt_surn = Surname()
                    alt_surn.set_surname(last_name_current)
                    alt_name.add_surname(alt_surn)
                    person.add_alternate_name(alt_name)

                # Gender
                gender_str = str(pdata.get("Gender") or "").strip().lower()
                if gender_str == "male":
                    person.set_gender(Person.MALE)
                elif gender_str == "female":
                    person.set_gender(Person.FEMALE)
                else:
                    person.set_gender(Person.UNKNOWN)

                # WikiTree ID custom attribute
                if wt_key:
                    wt_attr = Attribute()
                    wt_attr.set_type(AttributeType("WikiTree ID"))
                    wt_attr.set_value(wt_key)
                    person.add_attribute(wt_attr)

                # Citation
                citation = Citation()
                citation.set_reference_handle(source_handle)
                citation.set_page(f"WikiTree: {wt_key}" if wt_key else f"ID: {num_id}")
                if wt_key:
                    cit_url = f"https://www.wikitree.com/wiki/{wt_key}"
                    cit_note = Note()
                    cit_note.set(f"URL: {cit_url}")
                    cit_note_handle = source_db.add_note(cit_note, trans)
                    citation.add_note(cit_note_handle)

                # Photo / Media
                photo_data = pdata.get("PhotoData")
                if isinstance(photo_data, dict):
                    photo_path = str(
                        photo_data.get("path") or photo_data.get("url") or ""
                    )
                    if photo_path:
                        media_url = (
                            f"https://www.wikitree.com{photo_path}"
                            if photo_path.startswith("/")
                            else photo_path
                        )
                        media = Media()
                        media.set_path(media_url)
                        media.set_description(
                            f"WikiTree photo for {given} {surname_val}".strip()
                        )
                        media.set_mime_type("image/jpeg")
                        media_h = source_db.add_media(media, trans)
                        mref = MediaRef()
                        mref.ref = media_h
                        citation.add_media_reference(mref)

                cit_handle = source_db.add_citation(citation, trans)
                person.add_citation(cit_handle)

                # Birth Event
                birth_date_raw = self._clean_date_str(str(pdata.get("BirthDate") or ""))
                birth_loc = str(pdata.get("BirthLocation") or "").strip()
                if birth_date_raw or birth_loc:
                    b_evt = Event()
                    b_evt.set_type(EventType(EventType.BIRTH))
                    if birth_date_raw:
                        b_evt.set_date_object(dateparser.parse(birth_date_raw))
                    if birth_loc:
                        p_h = get_or_create_place(birth_loc, trans)
                        b_evt.set_place_handle(p_h)
                    b_evt.add_citation(cit_handle)
                    b_h = source_db.add_event(b_evt, trans)
                    b_ref = EventRef()
                    b_ref.ref = b_h
                    person.set_birth_ref(b_ref)

                # Death Event
                death_date_raw = self._clean_date_str(str(pdata.get("DeathDate") or ""))
                death_loc = str(pdata.get("DeathLocation") or "").strip()
                if death_date_raw or death_loc:
                    d_evt = Event()
                    d_evt.set_type(EventType(EventType.DEATH))
                    if death_date_raw:
                        d_evt.set_date_object(dateparser.parse(death_date_raw))
                    if death_loc:
                        p_h = get_or_create_place(death_loc, trans)
                        d_evt.set_place_handle(p_h)
                    d_evt.add_citation(cit_handle)
                    d_h = source_db.add_event(d_evt, trans)
                    d_ref = EventRef()
                    d_ref.ref = d_h
                    person.set_death_ref(d_ref)

                # Biography / Note
                bio_text = str(pdata.get("Bio") or "").strip()
                if bio_text:
                    note = Note()
                    note.set_type(NoteType(NoteType.GENERAL))
                    note.set(bio_text)
                    note_h = source_db.add_note(note, trans)
                    person.add_note(note_h)

                p_handle = source_db.add_person(person, trans)
                if wt_key:
                    person_handle_map[wt_key] = p_handle
                if num_id:
                    person_handle_map[num_id] = p_handle

            # 4. Link family relationships (parents, children, spouses)
            for pdata in raw_people:
                wt_key = str(pdata.get("Name") or "")
                num_id = str(pdata.get("Id") or "")
                p_handle = person_handle_map.get(wt_key) or person_handle_map.get(
                    num_id
                )
                if not p_handle:
                    continue

                # Spouses
                spouses = pdata.get("Spouses")
                if isinstance(spouses, list):
                    for spouse_item in spouses:
                        if isinstance(spouse_item, dict):
                            s_key = str(spouse_item.get("Name") or "")
                            s_id = str(spouse_item.get("Id") or "")
                            s_handle = person_handle_map.get(
                                s_key
                            ) or person_handle_map.get(s_id)
                            if s_handle and s_handle != p_handle:
                                # Ensure only one Family record per couple
                                current_p = source_db.get_person_from_handle(p_handle)
                                s_person = source_db.get_person_from_handle(s_handle)
                                is_father = current_p.get_gender() == Person.MALE
                                f_h = p_handle if is_father else s_handle
                                m_h = s_handle if is_father else p_handle

                                # Check if family already exists
                                fam_found = False
                                for existing_fam_h in source_db.iter_family_handles():
                                    fam = source_db.get_family_from_handle(
                                        existing_fam_h
                                    )
                                    if (
                                        fam.get_father_handle() == f_h
                                        and fam.get_mother_handle() == m_h
                                    ) or (
                                        fam.get_father_handle() == m_h
                                        and fam.get_mother_handle() == f_h
                                    ):
                                        fam_found = True
                                        break
                                if not fam_found:
                                    fam = Family()
                                    fam.set_father_handle(f_h)
                                    fam.set_mother_handle(m_h)
                                    m_date_raw = self._clean_date_str(
                                        str(spouse_item.get("MarriageDate") or "")
                                    )
                                    m_loc = str(
                                        spouse_item.get("MarriageLocation") or ""
                                    ).strip()
                                    if m_date_raw or m_loc:
                                        m_evt = Event()
                                        m_evt.set_type(EventType(EventType.MARRIAGE))
                                        if m_date_raw:
                                            m_evt.set_date_object(
                                                dateparser.parse(m_date_raw)
                                            )
                                        if m_loc:
                                            m_evt.set_place_handle(
                                                get_or_create_place(m_loc, trans)
                                            )
                                        m_handle = source_db.add_event(m_evt, trans)
                                        m_ref = EventRef()
                                        m_ref.ref = m_handle
                                        fam.add_event_ref(m_ref)

                                    source_db.add_family(fam, trans)

        self.context["source_db"] = source_db
        display_name = f"WikiTree: {query}" if query else _("WikiTree")
        self.context["source_title"] = display_name
        self.context["gedcom_path"] = display_name

        people: list[Person] = []
        for handle in source_db.iter_person_handles():
            p = source_db.get_person_from_handle(handle)
            if p:
                people.append(p)

        return people
