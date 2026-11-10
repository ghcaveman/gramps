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
import mimetypes
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
    ChildRefType,
    Url,
    UrlType,
    Date,
    NameType,
)
from gramps.gen.lib.date import Today
from gramps.gen.const import GRAMPS_LOCALE as glocale

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .gwizard_base import is_wikitree_id, extract_wikitree_id, get_wikitree_id
from .gwizardgedcom import GedGWizard

LOG = logging.getLogger(__name__)
_ = glocale.translation.gettext

_DEFAULT_FIELDS = (
    "Id,Name,FirstName,MiddleName,MiddleInitial,LastNameBirth,LastNameCurrent,LastNameOther,"
    "RealName,ColloquialName,Prefix,Suffix,Nicknames,Gender,BirthDate,DeathDate,BirthDateDecade,"
    "DeathDateDecade,BirthLocation,DeathLocation,BirthDateStatus,DeathDateStatus,"
    "IsLiving,Privacy,Photo,PhotoData,Father,Mother,Parents,Children,Spouses,DataStatus,"
    "Templates,Categories,Bio"
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
                self.verify_ssl = ca_env
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
        birth_date: str = "",
        death_date: str = "",
        limit: int = 25,
        timeout: int = 30,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Fuzzy search for persons across names and dates.

        :param first_name: First/given name.
        :param last_name: Last/surname.
        :param birth_date: Birth year or full date.
        :param death_date: Death year or full date.
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
        if birth_date:
            params["BirthDate"] = birth_date
        if death_date:
            params["DeathDate"] = death_date

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
        return is_wikitree_id(value)

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
        extracted_query = extract_wikitree_id(query)
        if extracted_query:
            query = extracted_query
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
    def wikitree_date_to_gramps(
        value: str | None,
        status: str | None = None,
        decade: str | None = None,
    ) -> Date:
        """
        Convert WikiTree date, status/certainty flag, and decade to a Date.

        :param value: Date string (e.g. '1706-01-17', '1706-00-00', or '1706').
        :param status: Certainty status ('certain', 'guess', 'before', 'after').
        :param decade: Fallback decade string (e.g. '1700s').
        :returns: Gramps Date object with appropriate modifier and quality.
        """
        date = Date()
        val = (value or "").strip()
        st = (status or "").strip().lower()

        modifier = Date.MOD_NONE
        quality = Date.QUAL_NONE
        if st in ("guess", "estimated", "about", "abt"):
            modifier = Date.MOD_ABOUT
            quality = Date.QUAL_ESTIMATED
        elif st in ("before", "bef"):
            modifier = Date.MOD_BEFORE
        elif st in ("after", "aft"):
            modifier = Date.MOD_AFTER

        # Check full ISO YYYY-MM-DD
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", val)
        if m:
            year, month, day = (int(p) for p in m.groups())
            if year > 0:
                if month == 0:
                    day = 0
                date.set(
                    quality=quality,
                    modifier=modifier,
                    calendar=Date.CAL_GREGORIAN,
                    value=(day, month, year, False),
                )
                return date

        # Check YYYY-MM
        m = re.match(r"^(\d{4})-(\d{2})$", val)
        if m:
            year, month = (int(p) for p in m.groups())
            if year > 0:
                date.set(
                    quality=quality,
                    modifier=modifier,
                    calendar=Date.CAL_GREGORIAN,
                    value=(0, month, year, False),
                )
                return date

        # Check year only
        m = re.match(r"^(\d{4})$", val)
        if m:
            year = int(m.group(1))
            if year > 0:
                date.set(
                    quality=quality,
                    modifier=modifier,
                    calendar=Date.CAL_GREGORIAN,
                    value=(0, 0, year, False),
                )
                return date

        # Try parsing with dateparser if non-empty and not all zero
        if val and val != "0000-00-00":
            clean = WikiTreeGWizard._clean_date_str(val)
            if clean:
                parsed = dateparser.parse(clean)
                if not parsed.is_empty():
                    if (
                        modifier != Date.MOD_NONE
                        and parsed.get_modifier() == Date.MOD_NONE
                    ):
                        parsed.set_modifier(modifier)
                    if (
                        quality != Date.QUAL_NONE
                        and parsed.get_quality() == Date.QUAL_NONE
                    ):
                        parsed.set_quality(quality)
                    return parsed

        # Fallback to decade if value was empty or 0000-00-00
        dec_val = (decade or "").strip()
        m_dec = re.match(r"^(\d{3}0)s$", dec_val, re.IGNORECASE)
        if m_dec:
            start_yr = int(m_dec.group(1))
            stop_yr = start_yr + 9
            date.set(
                quality=Date.QUAL_ESTIMATED,
                modifier=Date.MOD_RANGE,
                calendar=Date.CAL_GREGORIAN,
                value=(0, 0, start_yr, False, 0, 0, stop_yr, False),
            )
            return date

        return date

    @staticmethod
    def clean_source_text(raw_text: str) -> str:
        """
        Strip wikitext markup and normalize external source citation text.

        :param raw_text: Raw reference or source line from WikiTree.
        :returns: Cleaned human-readable citation text.
        """
        text = (raw_text or "").strip()
        # Convert [http://url Description] -> Description
        text = re.sub(r"\[(?:https?://[^\s\]]+)\s+([^\]]+)\]", r"\1", text)
        # Convert [http://url] -> http://url
        text = re.sub(r"\[(https?://[^\s\]]+)\]", r"\1", text)
        # Convert [[Target|Label]] -> Label, [[Target]] -> Target
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
        # Clean common templates like {{FindAGrave|123}}
        text = re.sub(
            r"\{\{FindAGrave\|(?:[^|]*\|)?(\d+)\}\}",
            r"Find A Grave memorial \1",
            text,
            flags=re.I,
        )
        text = re.sub(r"\{\{[^\}]+\}\}", "", text)
        # Clean HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Clean bold and italics
        text = re.sub(r"'''+|''", "", text)
        # Normalize whitespace
        return " ".join(text.split()).strip()

    @staticmethod
    def extract_source_title(cleaned_text: str) -> str:
        """
        Extract a concise, descriptive title for a Source record from citation text.

        :param cleaned_text: Cleaned citation text string.
        :returns: Abbreviated or full title string.
        """
        cleaned = (cleaned_text or "").strip()
        if not cleaned:
            return _("WikiTree Cited Source")
        if len(cleaned) <= 90:
            return cleaned.rstrip(".,;")
        # Look for sentence boundary after at least 30 characters
        m = re.search(r"^(.{30,90}?[.?!])\s+", cleaned)
        if m:
            return m.group(1).rstrip(".,;")
        # Truncate at word boundary
        cut = cleaned[:87]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut.rstrip(".,;:-") + "..."

    @staticmethod
    def parse_bio_sources(bio_text: str) -> list[dict[str, str]]:
        """
        Extract inline <ref> citations and bibliography sources from a biography.

        :param bio_text: Raw WikiTree biography markup.
        :returns: List of dicts with keys 'name', 'text', and 'context'.
        """
        bio = (bio_text or "").strip()
        if not bio:
            return []

        sources: list[dict[str, str]] = []
        seen_texts: set[str] = set()

        # 1. Match full <ref> tags
        ref_pattern = re.compile(
            r"<ref(?:\s+name\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s/>]+)))?\s*>(.*?)</ref>",
            re.DOTALL | re.IGNORECASE,
        )
        for m in ref_pattern.finditer(bio):
            name = m.group(1) or m.group(2) or m.group(3) or ""
            content = m.group(4).strip()
            if content:
                norm = " ".join(content.split()).lower()
                if norm not in seen_texts:
                    seen_texts.add(norm)
                    # Extract surrounding context (100 chars before, 50 chars after)
                    start_pos = max(0, m.start() - 100)
                    end_pos = min(len(bio), m.end() + 50)
                    context_snippet = bio[start_pos:end_pos]
                    sources.append(
                        {
                            "name": name,
                            "text": content,
                            "context": context_snippet,
                        }
                    )

        # 2. Match sources section
        sec_match = re.search(
            r"==+\s*(?:Sources|References|Bibliography).*?==+(.*)",
            bio,
            re.DOTALL | re.IGNORECASE,
        )
        if sec_match:
            sec_text = sec_match.group(1)
            for line in sec_text.splitlines():
                line = line.strip()
                if line.startswith(("*", "#")):
                    item = line.lstrip("*# ").strip()
                    if item and not item.lower().startswith(
                        ("<references", "{{reflist", "see also:")
                    ):
                        norm = " ".join(item.split()).lower()
                        if norm not in seen_texts:
                            seen_texts.add(norm)
                            sources.append(
                                {
                                    "name": "",
                                    "text": item,
                                    "context": "sources_section",
                                }
                            )

        return sources

    @staticmethod
    def clean_bio_text(bio_text: str) -> str:
        """
        Clean wikitext markup and remove inline references to produce narrative text.

        :param bio_text: Raw WikiTree biography markup.
        :returns: Cleaned narrative text suitable for a Gramps Note.
        """
        bio = (bio_text or "").strip()
        if not bio:
            return ""

        # Remove everything starting at the Sources section
        bio = re.split(
            r"==+\s*(?:Sources|References|Bibliography).*?==+",
            bio,
            flags=re.IGNORECASE,
        )[0]

        # Remove inline <ref> tags and self-closing tags
        bio = re.sub(
            r"<ref(?:\s+[^>]*)?>.*?</ref>",
            "",
            bio,
            flags=re.DOTALL | re.IGNORECASE,
        )
        bio = re.sub(r"<ref(?:\s+[^>]*)?/>", "", bio, flags=re.IGNORECASE)

        # Remove categories [[Category:...]]
        bio = re.sub(r"\[\[Category:[^\]]+\]\]", "", bio, flags=re.IGNORECASE)

        # Remove templates {{...}}
        bio = re.sub(r"\{\{[^\}]+\}\}", "", bio)

        # Convert wiki links [[Target|Label]] -> Label, [[Target]] -> Target
        bio = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", bio)

        # Convert external links [http://url label] -> label
        bio = re.sub(r"\[(?:https?://[^\s\]]+)\s+([^\]]+)\]", r"\1", bio)
        bio = re.sub(r"\[(https?://[^\s\]]+)\]", r"\1", bio)

        # Clean bold and italics
        bio = re.sub(r"'''+|''", "", bio)

        # Convert section headers like == Biography == or === Birth === to headings
        bio = re.sub(r"==+\s*([^=]+?)\s*==+", r"\1:", bio)

        # Collapse excess empty lines
        lines = [line.strip() for line in bio.splitlines()]
        cleaned_lines: list[str] = []
        prev_empty = False
        for line in lines:
            if not line:
                if not prev_empty and cleaned_lines:
                    cleaned_lines.append("")
                    prev_empty = True
            else:
                cleaned_lines.append(line)
                prev_empty = False

        return "\n".join(cleaned_lines).strip()

    @staticmethod
    def parse_bio_templates(bio_text: str) -> list[dict[str, Any]]:
        """
        Parse WikiTree templates/stickers {{Name|param1|param2=val}} from bio text.

        :param bio_text: Raw biography wikitext markup.
        :returns: List of dicts with 'name' and 'params'.
        """
        templates: list[dict[str, Any]] = []
        if not bio_text:
            return templates
        for m in re.finditer(r"\{\{([A-Za-z0-9 _-]+)(?:\|([^}]+))?\}\}", bio_text):
            tname = m.group(1).strip()
            raw_params = m.group(2) or ""
            params: dict[str, str] = {}
            idx = 1
            for part in raw_params.split("|"):
                part = part.strip()
                if not part:
                    continue
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k.strip()] = v.strip()
                else:
                    params[str(idx)] = part
                    params[part] = ""
                    idx += 1
            templates.append({"name": tname, "params": params})
        return templates

    def process_templates(
        self,
        person: Person,
        templates: list[dict[str, Any]],
        source_db: DbWriteBase,
        trans: DbTxn,
    ) -> None:
        """
        Process WikiTree templates/stickers into Gramps Attributes, URLs, and Events.

        :param person: Target Person object being populated.
        :param templates: List of template dictionaries.
        :param source_db: In-memory source database.
        :param trans: Active database transaction.
        """
        existing_attrs = {
            (str(a.get_type()), str(a.get_value())) for a in person.get_attribute_list()
        }
        existing_urls = {u.get_path() for u in person.get_url_list()}

        for item in templates:
            if not isinstance(item, dict):
                continue
            tname = str(item.get("name") or "").strip()
            params = item.get("params") or {}
            if isinstance(params, list):
                params = {str(i + 1): v for i, v in enumerate(params)}
            elif not isinstance(params, dict):
                params = {}

            tname_lower = tname.lower()

            # 1. Find A Grave
            if "findagrave" in tname_lower or "find a grave" in tname_lower:
                mem_id = ""
                for k in ("id", "memorial", "memorial_id", "1"):
                    if k in params and str(params[k]).strip().isdigit():
                        mem_id = str(params[k]).strip()
                        break
                if not mem_id:
                    for k, v in params.items():
                        if str(k).strip().isdigit():
                            mem_id = str(k).strip()
                            break
                        if str(v).strip().isdigit():
                            mem_id = str(v).strip()
                            break

                if mem_id:
                    attr_val = mem_id
                    if ("Find A Grave ID", attr_val) not in existing_attrs:
                        attr = Attribute()
                        attr.set_type(AttributeType(_("Find A Grave ID")))
                        attr.set_value(attr_val)
                        person.add_attribute(attr)
                        existing_attrs.add(("Find A Grave ID", attr_val))

                    memorial_url = f"https://www.findagrave.com/memorial/{mem_id}"
                    if memorial_url not in existing_urls:
                        fg_url = Url()
                        fg_url.set_path(memorial_url)
                        fg_url.set_type(UrlType(UrlType.WEB_SEARCH))
                        fg_url.set_description(_("Find A Grave Memorial"))
                        person.add_url(fg_url)
                        existing_urls.add(memorial_url)

            # 2. Occupation
            elif tname_lower == "occupation":
                occ_raw = (
                    params.get("text")
                    or params.get("occupation")
                    or params.get("1")
                    or ""
                )
                occ_cleaned = self.clean_source_text(str(occ_raw))
                if occ_cleaned:
                    occ_evt = Event()
                    occ_evt.set_type(EventType(EventType.OCCUPATION))
                    occ_evt.set_description(occ_cleaned)
                    occ_h = source_db.add_event(occ_evt, trans)
                    occ_ref = EventRef()
                    occ_ref.ref = occ_h
                    person.add_event_ref(occ_ref)

                    if (
                        len(occ_cleaned) <= 60
                        and (str(AttributeType.OCCUPATION), occ_cleaned)
                        not in existing_attrs
                    ):
                        attr = Attribute()
                        attr.set_type(AttributeType(AttributeType.OCCUPATION))
                        attr.set_value(occ_cleaned)
                        person.add_attribute(attr)
                        existing_attrs.add((str(AttributeType.OCCUPATION), occ_cleaned))

            # 3. Succession / Public Office
            elif "succession" in tname_lower:
                for i in range(1, 10):
                    pos = params.get(f"position{i}") or params.get(f"office{i}")
                    yrs = params.get(f"years{i}") or params.get(f"dates{i}")
                    if pos:
                        pos_cleaned = self.clean_source_text(str(pos))
                        succ_evt = Event()
                        succ_evt.set_type(EventType(EventType.ELECTED))
                        succ_evt.set_description(pos_cleaned)
                        if yrs:
                            succ_evt.set_date_object(
                                self.wikitree_date_to_gramps(str(yrs))
                            )
                        succ_h = source_db.add_event(succ_evt, trans)
                        succ_ref = EventRef()
                        succ_ref.ref = succ_h
                        person.add_event_ref(succ_ref)

                        val_str = f"{pos_cleaned} ({yrs})" if yrs else pos_cleaned
                        if ("Public Office", val_str) not in existing_attrs:
                            attr = Attribute()
                            attr.set_type(AttributeType(_("Public Office")))
                            attr.set_value(val_str)
                            person.add_attribute(attr)
                            existing_attrs.add(("Public Office", val_str))

            # 4. Society Ancestor
            elif any(
                term in tname_lower
                for term in ("society ancestor", "dar sticker", "sar sticker")
            ):
                soc = params.get("society") or (
                    "DAR" if "dar" in tname_lower else "SAR"
                )
                anc = params.get("ancestor") or params.get("1") or ""
                val = f"{soc}: {anc}".strip(": ")
                if ("Society Ancestor", val) not in existing_attrs:
                    attr = Attribute()
                    attr.set_type(AttributeType(_("Society Ancestor")))
                    attr.set_value(val)
                    person.add_attribute(attr)
                    existing_attrs.add(("Society Ancestor", val))

            # 5. Military / Revolutionary / Civil War
            elif any(
                term in tname_lower
                for term in (
                    "1776 sticker",
                    "military",
                    "civil war",
                    "war of 1812",
                    "veteran",
                    "war sticker",
                )
            ):
                unit = (
                    params.get("unit")
                    or params.get("regiment")
                    or params.get("branch")
                    or ""
                )
                rank = params.get("rank") or ""
                parts = [tname]
                if rank:
                    parts.append(str(rank))
                if unit:
                    parts.append(str(unit))
                desc = (
                    ": ".join(parts[:1] + [" ".join(parts[1:])])
                    if len(parts) > 1
                    else parts[0]
                )
                mil_evt = Event()
                mil_evt.set_type(EventType(EventType.MILITARY_SERV))
                mil_evt.set_description(desc)
                mil_h = source_db.add_event(mil_evt, trans)
                mil_ref = EventRef()
                mil_ref.ref = mil_h
                person.add_event_ref(mil_ref)

            # 6. Notability
            elif tname_lower == "notability":
                notab_text = params.get("text") or params.get("1") or ""
                if notab_text:
                    cleaned_notab = self.clean_source_text(str(notab_text))[:250]
                    if ("Notability", cleaned_notab) not in existing_attrs:
                        attr = Attribute()
                        attr.set_type(AttributeType(_("Notability")))
                        attr.set_value(cleaned_notab)
                        person.add_attribute(attr)
                        existing_attrs.add(("Notability", cleaned_notab))

            # 7. Other project or ancestor stickers
            elif (
                tname.endswith("Sticker")
                or tname.endswith("Project")
                or any(
                    x in tname_lower
                    for x in ("mayflower", "huguenot", "puritan", "pioneer")
                )
            ):
                if tname_lower not in ("citation needed", "reflist", "references"):
                    if ("Project / Sticker", tname) not in existing_attrs:
                        attr = Attribute()
                        attr.set_type(AttributeType(_("Project / Sticker")))
                        attr.set_value(tname)
                        person.add_attribute(attr)
                        existing_attrs.add(("Project / Sticker", tname))

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

        # Expand raw_people with relatives if present in Parents or Spouses/Children
        existing_ids = {str(p.get("Id")) for p in raw_people if p.get("Id") is not None}
        existing_names = {str(p.get("Name")) for p in raw_people if p.get("Name")}

        for p in list(raw_people):
            parents_dict = p.get("Parents")
            if isinstance(parents_dict, dict):
                for par_id, par_data in parents_dict.items():
                    if isinstance(par_data, dict):
                        p_id = str(par_data.get("Id") or par_id)
                        p_name = str(par_data.get("Name") or "")
                        if p_id not in existing_ids and p_name not in existing_names:
                            raw_people.append(par_data)
                            if p_id:
                                existing_ids.add(p_id)
                            if p_name:
                                existing_names.add(p_name)

            children_val = p.get("Children")
            children_dict = children_val if isinstance(children_val, dict) else {}
            if isinstance(children_val, list):
                children_dict = {
                    str(i): ch
                    for i, ch in enumerate(children_val)
                    if isinstance(ch, dict)
                }
            for ch_id, ch_data in children_dict.items():
                if isinstance(ch_data, dict):
                    c_id = str(ch_data.get("Id") or ch_id)
                    c_name = str(ch_data.get("Name") or "")
                    if (c_id not in existing_ids or not c_id) and (
                        c_name not in existing_names or not c_name
                    ):
                        raw_people.append(ch_data)
                        if c_id:
                            existing_ids.add(c_id)
                        if c_name:
                            existing_names.add(c_name)

        if self.context.get("include_relatives") and client:
            missing_keys: list[str] = []
            for p in list(raw_people):
                spouses = p.get("Spouses")
                if isinstance(spouses, list):
                    for sp in spouses:
                        if isinstance(sp, dict):
                            sp_id = str(sp.get("Id") or sp.get("Name") or "")
                            if (
                                sp_id
                                and sp_id not in existing_ids
                                and sp_id not in existing_names
                                and sp_id not in missing_keys
                            ):
                                missing_keys.append(sp_id)
                children = p.get("Children")
                if isinstance(children, dict):
                    for ch_id, ch_data in children.items():
                        ch_key = str(
                            (ch_data.get("Name") if isinstance(ch_data, dict) else "")
                            or ch_id
                        )
                        if (
                            ch_key
                            and ch_key not in existing_ids
                            and ch_key not in existing_names
                            and ch_key not in missing_keys
                        ):
                            missing_keys.append(ch_key)
                elif isinstance(children, list):
                    for ch in children:
                        if isinstance(ch, dict):
                            ch_key = str(ch.get("Name") or ch.get("Id") or "")
                            if (
                                ch_key
                                and ch_key not in existing_ids
                                and ch_key not in existing_names
                                and ch_key not in missing_keys
                            ):
                                missing_keys.append(ch_key)

            if missing_keys:
                rel_people = client.get_people(missing_keys)
                for rk, rdata in rel_people.items():
                    rid = str(rdata.get("Id") or rk)
                    rname = str(rdata.get("Name") or "")
                    if rid not in existing_ids and rname not in existing_names:
                        raw_people.append(rdata)
                        if rid:
                            existing_ids.add(rid)
                        if rname:
                            existing_names.add(rname)

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
        source_cache: dict[str, str] = {}
        media_cache: dict[str, str] = {}
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
                middle_initial = str(pdata.get("MiddleInitial") or "")
                last_name_birth = str(
                    pdata.get("LastNameBirth") or pdata.get("LastNameAtBirth") or ""
                )
                last_name_current = str(pdata.get("LastNameCurrent") or "")
                last_name_other = str(pdata.get("LastNameOther") or "")
                prefix = str(pdata.get("Prefix") or "")
                suffix = str(pdata.get("Suffix") or "")
                nicknames = str(pdata.get("Nicknames") or "")
                real_name = str(
                    pdata.get("RealName") or pdata.get("ColloquialName") or ""
                ).strip()

                given = first_name
                if middle_name and middle_name not in given:
                    given = f"{given} {middle_name}".strip()
                elif middle_initial and middle_initial not in given:
                    given = f"{given} {middle_initial}.".strip()

                if not given and real_name:
                    given = real_name

                surname_val = last_name_birth or last_name_current

                person = Person()
                name_obj = Name()
                name_obj.set_first_name(given)
                if last_name_birth:
                    name_obj.set_type(NameType(NameType.BIRTH))
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

                # Set call name if RealName/ColloquialName provided
                if real_name:
                    if real_name != given and real_name != first_name:
                        name_obj.set_call_name(real_name)
                    if not nicknames and real_name != given and real_name != first_name:
                        name_obj.set_nick_name(real_name)

                person.set_primary_name(name_obj)

                # Alternate name if current surname differs from birth surname
                if (
                    last_name_current
                    and last_name_birth
                    and last_name_current != last_name_birth
                ):
                    alt_name = Name()
                    alt_name.set_type(NameType(NameType.MARRIED))
                    alt_name.set_first_name(given)
                    alt_surn = Surname()
                    alt_surn.set_surname(last_name_current)
                    alt_name.add_surname(alt_surn)
                    if prefix:
                        alt_name.set_title(prefix)
                    if suffix:
                        alt_name.set_suffix(suffix)
                    person.add_alternate_name(alt_name)

                # Alternate names for LastNameOther (e.g. prior married names, aliases)
                if last_name_other:
                    other_surnames = [
                        s.strip()
                        for s in re.split(r"[,;/]+", last_name_other)
                        if s.strip()
                    ]
                    for oth_surn in other_surnames:
                        if (
                            oth_surn
                            and oth_surn != last_name_birth
                            and oth_surn != last_name_current
                        ):
                            alt_other = Name()
                            alt_other.set_type(NameType(NameType.AKA))
                            alt_other.set_first_name(given)
                            alt_surn_oth = Surname()
                            alt_surn_oth.set_surname(oth_surn)
                            alt_other.add_surname(alt_surn_oth)
                            if prefix:
                                alt_other.set_title(prefix)
                            if suffix:
                                alt_other.set_suffix(suffix)
                            person.add_alternate_name(alt_other)

                # If RealName differs significantly from given name, also add an AKA alternate name
                if real_name and real_name != given and real_name != first_name:
                    alt_real = Name()
                    alt_real.set_type(NameType(NameType.AKA))
                    alt_real.set_first_name(real_name)
                    if surname_val:
                        alt_s = Surname()
                        alt_s.set_surname(surname_val)
                        alt_real.add_surname(alt_s)
                    if prefix:
                        alt_real.set_title(prefix)
                    if suffix:
                        alt_real.set_suffix(suffix)
                    person.add_alternate_name(alt_real)

                # Gender
                gender_str = str(pdata.get("Gender") or "").strip().lower()
                if gender_str == "male":
                    person.set_gender(Person.MALE)
                elif gender_str == "female":
                    person.set_gender(Person.FEMALE)
                else:
                    person.set_gender(Person.UNKNOWN)

                # Privacy & Living Status
                privacy_val = pdata.get("Privacy")
                is_private = pdata.get("Privacy_IsPrivate")
                if is_private is True or (
                    isinstance(privacy_val, (int, str))
                    and str(privacy_val).isdigit()
                    and int(privacy_val) < 50
                ):
                    person.set_privacy(True)

                is_living_raw = (
                    pdata.get("IsLiving")
                    if pdata.get("IsLiving") is not None
                    else pdata.get("is_living")
                )
                is_living: bool | None = None
                if is_living_raw is not None:
                    try:
                        is_living = int(is_living_raw) == 1
                    except (ValueError, TypeError):
                        is_living = bool(is_living_raw)

                if is_living is True:
                    liv_attr = Attribute()
                    liv_attr.set_type(AttributeType(_("Living Status")))
                    liv_attr.set_value(_("Living"))
                    person.add_attribute(liv_attr)

                # WikiTree ID custom attribute and Internet Web Home URL
                if wt_key:
                    wt_attr = Attribute()
                    wt_attr.set_type(AttributeType("WikiTree ID"))
                    wt_attr.set_value(wt_key)
                    person.add_attribute(wt_attr)

                    wt_url = Url()
                    wt_url.set_path(f"https://www.wikitree.com/wiki/{wt_key}")
                    wt_url.set_type(UrlType(UrlType.WEB_HOME))
                    wt_url.set_description(_("WikiTree Profile"))
                    person.add_url(wt_url)

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

                # Primary Photo / Media
                photo_file = str(pdata.get("Photo") or "").strip()
                photo_data = pdata.get("PhotoData")
                primary_media_url = ""
                primary_media_desc = ""
                orig_w = ""
                orig_h = ""

                if isinstance(photo_data, dict):
                    photo_path = str(
                        photo_data.get("path") or photo_data.get("url") or ""
                    ).strip()
                    if photo_path:
                        primary_media_url = (
                            f"https://www.wikitree.com{photo_path}"
                            if photo_path.startswith("/")
                            else photo_path
                        )
                    orig_w = str(
                        photo_data.get("orig_width") or photo_data.get("width") or ""
                    )
                    orig_h = str(
                        photo_data.get("orig_height") or photo_data.get("height") or ""
                    )
                    file_name = str(photo_data.get("file") or photo_file or "")
                    if file_name:
                        primary_media_desc = (
                            f"{given} {surname_val} ({file_name})".strip()
                        )

                if not primary_media_url and photo_file:
                    ext = (
                        photo_file.rsplit(".", 1)[-1].lower()
                        if "." in photo_file
                        else "jpg"
                    )
                    primary_media_url = (
                        f"https://www.wikitree.com/photo/{ext}/{photo_file}"
                    )
                    primary_media_desc = f"{given} {surname_val} ({photo_file})".strip()

                if not primary_media_desc:
                    primary_media_desc = (
                        f"WikiTree photo for {given} {surname_val}".strip()
                    )

                if primary_media_url:
                    primary_media_h = media_cache.get(primary_media_url)
                    if not primary_media_h:
                        media = Media()
                        media.set_path(primary_media_url)
                        media.set_description(primary_media_desc)
                        mime = mimetypes.guess_type(primary_media_url)[0]
                        media.set_mime_type(mime or "image/jpeg")

                        if orig_w and orig_h:
                            dim_attr = Attribute()
                            dim_attr.set_type(AttributeType(_("Dimensions")))
                            dim_attr.set_value(f"{orig_w}x{orig_h}")
                            media.add_attribute(dim_attr)

                        primary_media_h = source_db.add_media(media, trans)
                        media_cache[primary_media_url] = primary_media_h

                    # Attach directly to Person (primary photo / avatar)
                    p_mref = MediaRef()
                    p_mref.ref = primary_media_h
                    person.add_media_reference(p_mref)

                    # Also attach to Citation
                    c_mref = MediaRef()
                    c_mref.ref = primary_media_h
                    citation.add_media_reference(c_mref)

                citation.set_date_object(Today())
                cit_handle = source_db.add_citation(citation, trans)
                person.add_citation(cit_handle)

                # Birth Event
                birth_status = str(
                    pdata.get("BirthDateStatus")
                    or (pdata.get("DataStatus") or {}).get("BirthDate")
                    or ""
                )
                birth_decade = str(pdata.get("BirthDateDecade") or "")
                b_date_obj = self.wikitree_date_to_gramps(
                    pdata.get("BirthDate"), birth_status, birth_decade
                )
                birth_loc = str(pdata.get("BirthLocation") or "").strip()
                if not b_date_obj.is_empty() or birth_loc:
                    b_evt = Event()
                    b_evt.set_type(EventType(EventType.BIRTH))
                    if not b_date_obj.is_empty():
                        b_evt.set_date_object(b_date_obj)
                    if birth_loc:
                        p_h = get_or_create_place(birth_loc, trans)
                        b_evt.set_place_handle(p_h)
                    b_evt.add_citation(cit_handle)
                    b_h = source_db.add_event(b_evt, trans)
                    b_ref = EventRef()
                    b_ref.ref = b_h
                    person.set_birth_ref(b_ref)

                # Death Event
                death_status = str(
                    pdata.get("DeathDateStatus")
                    or (pdata.get("DataStatus") or {}).get("DeathDate")
                    or ""
                )
                death_decade = str(pdata.get("DeathDateDecade") or "")
                d_date_obj = self.wikitree_date_to_gramps(
                    pdata.get("DeathDate"), death_status, death_decade
                )
                death_loc = str(pdata.get("DeathLocation") or "").strip()
                if not d_date_obj.is_empty() or death_loc:
                    d_evt = Event()
                    d_evt.set_type(EventType(EventType.DEATH))
                    if not d_date_obj.is_empty():
                        d_evt.set_date_object(d_date_obj)
                    if death_loc:
                        p_h = get_or_create_place(death_loc, trans)
                        d_evt.set_place_handle(p_h)
                    d_evt.add_citation(cit_handle)
                    d_h = source_db.add_event(d_evt, trans)
                    d_ref = EventRef()
                    d_ref.ref = d_h
                    person.set_death_ref(d_ref)
                elif is_living is False and d_date_obj.is_empty() and not death_loc:
                    d_evt = Event()
                    d_evt.set_type(EventType(EventType.DEATH))
                    d_evt.add_citation(cit_handle)
                    d_h = source_db.add_event(d_evt, trans)
                    d_ref = EventRef()
                    d_ref.ref = d_h
                    person.set_death_ref(d_ref)

                # Burial Event (from Categories or Bio Cemetery)
                cemetery_name = ""
                categories_val = pdata.get("Categories") or []
                if isinstance(categories_val, list):
                    for cat in categories_val:
                        cat_clean = str(cat).replace("_", " ").strip()
                        if any(
                            kw in cat_clean.lower()
                            for kw in (
                                "cemetery",
                                "burial ground",
                                "burying ground",
                                "memorial park",
                                "churchyard",
                            )
                        ):
                            cemetery_name = cat_clean
                            break

                raw_bio = str(pdata.get("Bio") or pdata.get("bio") or "").strip()
                if not cemetery_name and raw_bio:
                    cat_m = re.search(
                        r"\[\[Category:\s*([^\]]*(?:cemetery|burial ground|burying ground|memorial park|churchyard)[^\]]*)\]\]",
                        raw_bio,
                        re.IGNORECASE,
                    )
                    if cat_m:
                        cemetery_name = cat_m.group(1).replace("_", " ").strip()

                if cemetery_name:
                    bur_evt = Event()
                    bur_evt.set_type(EventType(EventType.BURIAL))
                    cem_p_h = get_or_create_place(cemetery_name, trans)
                    bur_evt.set_place_handle(cem_p_h)
                    bur_evt.add_citation(cit_handle)
                    bur_h = source_db.add_event(bur_evt, trans)
                    bur_ref = EventRef()
                    bur_ref.ref = bur_h
                    person.add_event_ref(bur_ref)

                # Biography & Sources from Bio Text
                if raw_bio:
                    # 1. Extract and create structured external Sources & Citations
                    bio_sources = self.parse_bio_sources(raw_bio)
                    for src_info in bio_sources:
                        s_raw = src_info.get("text") or ""
                        if not s_raw:
                            continue
                        s_cleaned = self.clean_source_text(s_raw)
                        if not s_cleaned:
                            continue
                        s_title = self.extract_source_title(s_cleaned)

                        cache_key = s_title.lower()
                        s_h = source_cache.get(cache_key)
                        if not s_h:
                            new_src = Source()
                            new_src.set_title(s_title)
                            url_m = re.search(r"https?://[^\s()<>\"']+", s_raw)
                            if url_m:
                                new_src.set_publication_info(url_m.group(0))
                            r_ref = RepoRef()
                            r_ref.ref = repo_handle
                            new_src.add_repo_reference(r_ref)
                            s_h = source_db.add_source(new_src, trans)
                            source_cache[cache_key] = s_h

                        cit_obj = Citation()
                        cit_obj.set_reference_handle(s_h)
                        cit_obj.set_date_object(Today())

                        m_page = re.search(
                            r"(?:pp?\.\s*|pages?\s*|image\s*)(\d+(?:[-–]\d+)?)",
                            s_cleaned,
                            re.I,
                        )
                        if m_page:
                            cit_obj.set_page(m_page.group(0))

                        c_note = Note()
                        c_note.set_type(NoteType(NoteType.CITATION))
                        c_note.set(s_cleaned)
                        c_note_h = source_db.add_note(c_note, trans)
                        cit_obj.add_note(c_note_h)

                        ext_cit_h = source_db.add_citation(cit_obj, trans)
                        person.add_citation(ext_cit_h)

                        ctx = (src_info.get("context") or "").lower()
                        if b_ref and any(
                            kw in ctx
                            for kw in (
                                "born",
                                "birth",
                                "baptism",
                                "christen",
                                "baptized",
                            )
                        ):
                            b_ev = source_db.get_event_from_handle(b_ref.ref)
                            if b_ev and ext_cit_h not in b_ev.get_citation_list():
                                b_ev.add_citation(ext_cit_h)
                                source_db.commit_event(b_ev, trans)

                        if d_ref and any(
                            kw in ctx
                            for kw in (
                                "died",
                                "death",
                                "burial",
                                "buried",
                                "cemetery",
                                "grave",
                                "killed",
                                "probate",
                                "will",
                            )
                        ):
                            d_ev = source_db.get_event_from_handle(d_ref.ref)
                            if d_ev and ext_cit_h not in d_ev.get_citation_list():
                                d_ev.add_citation(ext_cit_h)
                                source_db.commit_event(d_ev, trans)

                    # 2. Clean narrative biography text for Person Note
                    clean_bio = self.clean_bio_text(raw_bio)
                    if clean_bio:
                        note = Note()
                        note.set_type(NoteType(NoteType.GENERAL))
                        note.set(clean_bio)
                        note_h = source_db.add_note(note, trans)
                        person.add_note(note_h)

                # 3. Process structured templates and stickers
                templates_data = pdata.get("Templates")
                if not templates_data and raw_bio:
                    templates_data = self.parse_bio_templates(raw_bio)
                if templates_data and isinstance(templates_data, list):
                    self.process_templates(person, templates_data, source_db, trans)

                # 4. Extract gallery images from bio text: [[Image:filename|caption]]
                if raw_bio:
                    for img_m in re.finditer(
                        r"\[\[(?:Image|File):([^\s|\]]+)(?:\|([^\]]+))?\]\]",
                        raw_bio,
                        re.IGNORECASE,
                    ):
                        img_file = img_m.group(1).strip()
                        raw_caption = img_m.group(2) or ""
                        clean_parts = [
                            p.strip()
                            for p in raw_caption.split("|")
                            if not re.match(
                                r"^\d+px$|^thumb$|^right$|^left$|^center$|^none$",
                                p.strip(),
                                re.IGNORECASE,
                            )
                        ]
                        img_desc = (
                            " - ".join(clean_parts)
                            if clean_parts
                            else f"{img_file} ({given} {surname_val})"
                        )
                        ext = (
                            img_file.rsplit(".", 1)[-1].lower()
                            if "." in img_file
                            else "jpg"
                        )
                        img_url = f"https://www.wikitree.com/photo/{ext}/{img_file}"

                        if img_url == primary_media_url:
                            continue

                        g_media_h = media_cache.get(img_url)
                        if not g_media_h:
                            g_media = Media()
                            g_media.set_path(img_url)
                            g_media.set_description(img_desc)
                            mime = mimetypes.guess_type(img_url)[0]
                            g_media.set_mime_type(mime or "image/jpeg")
                            g_media_h = source_db.add_media(g_media, trans)
                            media_cache[img_url] = g_media_h

                        if not any(r.ref == g_media_h for r in person.get_media_list()):
                            g_mref = MediaRef()
                            g_mref.ref = g_media_h
                            person.add_media_reference(g_mref)

                p_handle = source_db.add_person(person, trans)
                if wt_key:
                    person_handle_map[wt_key] = p_handle
                if num_id:
                    person_handle_map[num_id] = p_handle

            # 4. Link family relationships (parents, children, spouses)
            def get_or_create_family(
                father_h: str | None, mother_h: str | None
            ) -> Family:
                """Find an existing Family for father/mother or create a new one."""
                for existing_fam_h in source_db.iter_family_handles():
                    fam = source_db.get_family_from_handle(existing_fam_h)
                    if not fam:
                        continue
                    cur_f = fam.get_father_handle()
                    cur_m = fam.get_mother_handle()
                    if father_h and mother_h:
                        if (cur_f == father_h and cur_m == mother_h) or (
                            cur_f == mother_h and cur_m == father_h
                        ):
                            return fam
                    elif father_h and not mother_h:
                        if cur_f == father_h and not cur_m:
                            return fam
                    elif mother_h and not father_h:
                        if cur_m == mother_h and not cur_f:
                            return fam

                fam = Family()
                if father_h:
                    fam.set_father_handle(father_h)
                if mother_h:
                    fam.set_mother_handle(mother_h)
                fam_h = source_db.add_family(fam, trans)
                fam.handle = fam_h

                if father_h:
                    f_person = source_db.get_person_from_handle(father_h)
                    if f_person and fam_h not in f_person.get_family_handle_list():
                        f_person.add_family_handle(fam_h)
                        source_db.commit_person(f_person, trans)

                if mother_h:
                    m_person = source_db.get_person_from_handle(mother_h)
                    if m_person and fam_h not in m_person.get_family_handle_list():
                        m_person.add_family_handle(fam_h)
                        source_db.commit_person(m_person, trans)

                return fam

            def status_to_relation(status_val: str) -> ChildRefType:
                """Convert WikiTree relationship status to ChildRefType."""
                st = (status_val or "").strip().lower()
                if st in ("non-biological", "adopted"):
                    return ChildRefType(ChildRefType.ADOPTED)
                if st in ("foster",):
                    return ChildRefType(ChildRefType.FOSTER)
                if st in ("stepchild", "step"):
                    return ChildRefType(ChildRefType.STEPCHILD)
                return ChildRefType(ChildRefType.BIRTH)

            # 4a. Link spouses
            for pdata in raw_people:
                wt_key = str(pdata.get("Name") or "")
                num_id = str(pdata.get("Id") or "")
                p_handle = person_handle_map.get(wt_key) or person_handle_map.get(
                    num_id
                )
                if not p_handle:
                    continue

                spouses = pdata.get("Spouses")
                if isinstance(spouses, list):
                    for spouse_item in spouses:
                        if not isinstance(spouse_item, dict):
                            continue
                        s_key = str(spouse_item.get("Name") or "")
                        s_id = str(spouse_item.get("Id") or "")
                        s_handle = person_handle_map.get(
                            s_key
                        ) or person_handle_map.get(s_id)
                        if not s_handle or s_handle == p_handle:
                            continue

                        cur_p = source_db.get_person_from_handle(p_handle)
                        is_father = cur_p.get_gender() == Person.MALE
                        f_h = p_handle if is_father else s_handle
                        m_h = s_handle if is_father else p_handle

                        fam = get_or_create_family(f_h, m_h)

                        if not fam.get_event_ref_list():
                            m_status = str(
                                spouse_item.get("MarriageDateStatus")
                                or (spouse_item.get("DataStatus") or {}).get(
                                    "MarriageDate"
                                )
                                or (spouse_item.get("data_status") or {}).get(
                                    "marriage_date"
                                )
                                or ""
                            )
                            m_date_obj = self.wikitree_date_to_gramps(
                                spouse_item.get("MarriageDate")
                                or spouse_item.get("marriage_date"),
                                m_status,
                            )
                            m_loc = str(
                                spouse_item.get("MarriageLocation")
                                or spouse_item.get("marriage_location")
                                or ""
                            ).strip()
                            if not m_date_obj.is_empty() or m_loc:
                                m_evt = Event()
                                m_evt.set_type(EventType(EventType.MARRIAGE))
                                if not m_date_obj.is_empty():
                                    m_evt.set_date_object(m_date_obj)
                                if m_loc:
                                    m_evt.set_place_handle(
                                        get_or_create_place(m_loc, trans)
                                    )
                                m_handle = source_db.add_event(m_evt, trans)
                                m_ref = EventRef()
                                m_ref.ref = m_handle
                                fam.add_event_ref(m_ref)
                                source_db.commit_family(fam, trans)

                        # Check for MarriageEndDate (Divorce)
                        m_end_raw = self._clean_date_str(
                            str(
                                spouse_item.get("MarriageEndDate")
                                or spouse_item.get("marriage_end_date")
                                or ""
                            )
                        )
                        if m_end_raw:
                            m_end_status = str(
                                spouse_item.get("MarriageEndDateStatus")
                                or (spouse_item.get("DataStatus") or {}).get(
                                    "MarriageEndDate"
                                )
                                or (spouse_item.get("data_status") or {}).get(
                                    "marriage_end_date"
                                )
                                or ""
                            )
                            div_date_obj = self.wikitree_date_to_gramps(
                                m_end_raw, m_end_status
                            )
                            has_div = any(
                                source_db.get_event_from_handle(r.ref).get_type()
                                == EventType.DIVORCE
                                for r in fam.get_event_ref_list()
                                if source_db.get_event_from_handle(r.ref)
                            )
                            if not has_div:
                                div_evt = Event()
                                div_evt.set_type(EventType(EventType.DIVORCE))
                                if not div_date_obj.is_empty():
                                    div_evt.set_date_object(div_date_obj)
                                div_h = source_db.add_event(div_evt, trans)
                                div_ref = EventRef()
                                div_ref.ref = div_h
                                fam.add_event_ref(div_ref)
                                source_db.commit_family(fam, trans)

            # 4b. Link parents and children via ChildRef
            for pdata in raw_people:
                wt_key = str(pdata.get("Name") or "")
                num_id = str(pdata.get("Id") or "")
                child_h = person_handle_map.get(wt_key) or person_handle_map.get(num_id)
                if not child_h:
                    continue

                child_p = source_db.get_person_from_handle(child_h)
                if not child_p:
                    continue

                f_h: str | None = None
                m_h: str | None = None

                fat_val = pdata.get("Father")
                mot_val = pdata.get("Mother")
                if fat_val:
                    f_h = person_handle_map.get(str(fat_val))
                if mot_val:
                    m_h = person_handle_map.get(str(mot_val))

                parents_val = pdata.get("Parents")
                if isinstance(parents_val, dict):
                    for par_id, par_data in parents_val.items():
                        if isinstance(par_data, dict):
                            pk = str(
                                par_data.get("Name") or par_data.get("Id") or par_id
                            )
                            ph = person_handle_map.get(pk) or person_handle_map.get(
                                str(par_id)
                            )
                            if ph:
                                g = str(par_data.get("Gender") or "").lower()
                                if g == "male" and not f_h:
                                    f_h = ph
                                elif g == "female" and not m_h:
                                    m_h = ph

                if f_h or m_h:
                    fam = get_or_create_family(f_h, m_h)
                    if not any(cr.ref == child_h for cr in fam.get_child_ref_list()):
                        data_status = pdata.get("DataStatus") or {}
                        f_status = str(data_status.get("Father") or "").strip()
                        m_status = str(data_status.get("Mother") or "").strip()

                        child_ref = ChildRef()
                        child_ref.ref = child_h
                        child_ref.set_father_relation(status_to_relation(f_status))
                        child_ref.set_mother_relation(status_to_relation(m_status))

                        notes_to_add: list[str] = []
                        if f_status == "20" and m_status == "20":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Paternal and maternal relationships are confirmed with DNA."
                                )
                            )
                        elif f_status == "20":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Paternal relationship is confirmed with DNA."
                                )
                            )
                        elif m_status == "20":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Maternal relationship is confirmed with DNA."
                                )
                            )

                        if f_status == "10" and m_status == "10":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Paternal and maternal relationships are confirmed with sources."
                                )
                            )
                        elif f_status == "10":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Paternal relationship is confirmed with sources."
                                )
                            )
                        elif m_status == "10":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Maternal relationship is confirmed with sources."
                                )
                            )

                        for note_text in notes_to_add:
                            note = Note()
                            note.set_type(NoteType(NoteType.GENERAL))
                            note.set(note_text)
                            note_h = source_db.add_note(note, trans)
                            child_ref.add_note(note_h)

                        fam.add_child_ref(child_ref)
                        source_db.commit_family(fam, trans)

                        if fam.handle not in child_p.get_parent_family_handle_list():
                            child_p.add_parent_family_handle(fam.handle)
                            source_db.commit_person(child_p, trans)

            # 4c. Link children from parent's Children list
            for pdata in raw_people:
                wt_key = str(pdata.get("Name") or "")
                num_id = str(pdata.get("Id") or "")
                parent_h = person_handle_map.get(wt_key) or person_handle_map.get(
                    num_id
                )
                if not parent_h:
                    continue

                parent_p = source_db.get_person_from_handle(parent_h)
                if not parent_p:
                    continue

                children = pdata.get("Children")
                children_list = []
                if isinstance(children, dict):
                    children_list = list(children.values())
                elif isinstance(children, list):
                    children_list = children

                is_fat = parent_p.get_gender() == Person.MALE
                for ch_data in children_list:
                    if not isinstance(ch_data, dict):
                        continue
                    c_key = str(ch_data.get("Name") or "")
                    c_id = str(ch_data.get("Id") or "")
                    c_h = person_handle_map.get(c_key) or person_handle_map.get(c_id)
                    if not c_h or c_h == parent_h:
                        continue

                    c_p = source_db.get_person_from_handle(c_h)
                    if not c_p:
                        continue

                    already_linked = False
                    for pf_h in c_p.get_parent_family_handle_list():
                        pfam = source_db.get_family_from_handle(pf_h)
                        if pfam and (
                            (is_fat and pfam.get_father_handle() == parent_h)
                            or (not is_fat and pfam.get_mother_handle() == parent_h)
                        ):
                            already_linked = True
                            break

                    if not already_linked:
                        p_f_h = parent_h if is_fat else None
                        p_m_h = None if is_fat else parent_h
                        fam = get_or_create_family(p_f_h, p_m_h)
                        if not any(cr.ref == c_h for cr in fam.get_child_ref_list()):
                            cr = ChildRef()
                            cr.ref = c_h
                            cr.set_father_relation(ChildRefType(ChildRefType.BIRTH))
                            cr.set_mother_relation(ChildRefType(ChildRefType.BIRTH))
                            fam.add_child_ref(cr)
                            source_db.commit_family(fam, trans)
                        if fam.handle not in c_p.get_parent_family_handle_list():
                            c_p.add_parent_family_handle(fam.handle)
                            source_db.commit_person(c_p, trans)

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

    def _apply(self, **kwargs: Any) -> bool:
        """
        Apply resolutions for WikiTree merge, ensuring WikiTree ID is stored
        on the target person unless explicitly rejected.

        :param kwargs: Arguments passed to GedGWizard._apply.
        :returns: True if apply was successful.
        :rtype: bool
        """
        resolutions = kwargs.get("resolutions")
        target_person_handle = kwargs.get("target_person_handle")
        if target_person_handle and resolutions is not None:
            if "wtid" not in resolutions:
                resolutions["wtid"] = "source"
        return super()._apply(**kwargs)
