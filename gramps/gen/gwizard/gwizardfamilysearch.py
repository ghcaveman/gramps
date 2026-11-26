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
FamilySearch implementation of the GWizard import and merge framework.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import re
import types
from typing import Any
from urllib.parse import urlencode, urlparse

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.config import config
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.fs import tree as fs_tree_mod
from gramps.gen.fs import utils as fs_utilities
from gramps.gen.fs.fs_import import deserializer as deserialize
from gramps.gen.fs.fs_import.importer import FSToGrampsImporter
from gramps.gen.fs.fs_import.places import add_place
from gramps.gen.fs.session import GLOBAL_SESSION, SESSION, Session
from gramps.gen.lib import Attribute, AttributeType, Person

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .gwizardfsprovenance import (
    ensure_provenance,
    normalize_fs_id,
    profile_url,
)
from .gwizardgedcom import GedGWizard

LOG = logging.getLogger(__name__)
_ = glocale.translation.gettext

_FS_ID_REGEX = re.compile(r"^[A-Za-z0-9]{4}-[A-Za-z0-9]{3,4}$")
_URL_ID_REGEX = re.compile(
    r"familysearch\.org/(?:tree/person/(?:details/)?|platform/tree/persons/)([A-Za-z0-9]{4}-[A-Za-z0-9]{3,4})",
    re.IGNORECASE,
)
_BARE_ID_REGEX = re.compile(r"\b([A-Za-z0-9]{4}-[A-Za-z0-9]{3,4})\b")


# ------------------------------------------------------------
#
# FamilySearchAuthenticationError
#
# ------------------------------------------------------------
class FamilySearchAuthenticationError(RuntimeError):
    """Raised when a FamilySearch request is not authorized."""


# ------------------------------------------------------------
#
# Search result formatting
#
# ------------------------------------------------------------
def _search_result(
    fsid: str, person_data: dict[str, Any], fallback_name: str = ""
) -> dict[str, str] | None:
    """Build a search result from FamilySearch display properties."""
    display = person_data.get("display") or {}
    name = str(display.get("name") or display.get("fullName") or fallback_name).strip()
    if not name:
        return None

    lifespan = str(display.get("lifespan") or display.get("lifeSpan") or "").strip()
    birth_date = str(display.get("birthDate") or "").strip()
    death_date = str(display.get("deathDate") or "").strip()
    if not lifespan:
        if birth_date and death_date:
            lifespan = f"{birth_date} - {death_date}"
        else:
            lifespan = birth_date or death_date

    return {
        "fsid": fsid,
        "name": name,
        "life": lifespan,
        "gender": str(display.get("gender") or "").strip(),
        "birth_date": birth_date,
        "birth_place": str(display.get("birthPlace") or "").strip(),
        "death_date": death_date,
        "death_place": str(display.get("deathPlace") or "").strip(),
    }


_YEAR_REGEX = re.compile(r"^\d{1,4}$")


def _search_date_value(value: str) -> str:
    """
    Return a search date as a GEDCOM X date (a bare year becomes '+1850').

    Values that are not a bare year are passed through unchanged.
    """
    clean_value = " ".join(value.split())
    if _YEAR_REGEX.match(clean_value):
        return "+" + clean_value.zfill(4)
    return clean_value


def _search_sex_value(value: str) -> str:
    """Return a search sex term value ('Male', 'Female' or 'Unknown')."""
    clean_value = value.strip().lower()
    if clean_value in ("m", "male"):
        return "Male"
    if clean_value in ("f", "female"):
        return "Female"
    if clean_value in ("u", "unknown"):
        return "Unknown"
    return value.strip()


def _search_params(
    query: str = "",
    first_name: str = "",
    last_name: str = "",
    birth_date: str = "",
    death_date: str = "",
    gender: str = "",
    birth_place: str = "",
    death_place: str = "",
) -> dict[str, str]:
    """
    Build the Tree Person Search query parameters (q.givenName, q.surname, ...).

    FamilySearch rejects the old single 'q=givenName:... surname:...' string
    with HTTP 400; each search term is now its own 'q.<term>' parameter.
    Free text with no explicit name is split into given names and a surname
    (its last word).
    """
    params: dict[str, str] = {}
    given = " ".join(first_name.split())
    surname = " ".join(last_name.split())
    words = query.split()
    if words and not (given or surname):
        surname = words[-1]
        given = " ".join(words[:-1])
    elif words:
        params["q.miscKeyword"] = " ".join(words)

    for field, value in (
        ("q.givenName", given),
        ("q.surname", surname),
        ("q.sex", _search_sex_value(gender)),
        ("q.birthLikeDate", _search_date_value(birth_date)),
        ("q.birthLikePlace", " ".join(birth_place.split())),
        ("q.deathLikeDate", _search_date_value(death_date)),
        ("q.deathLikePlace", " ".join(death_place.split())),
    ):
        if value:
            params[field] = value
    return params


def _response_error_detail(response: Any) -> str:
    """Return the first FamilySearch error message in a response, if any."""
    try:
        data = response.json()
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    for error in data.get("errors") or []:
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("label") or "").strip()
            if message:
                return message
    return ""


def _response_data(response: Any, operation: str) -> dict[str, Any]:
    """Return decoded FamilySearch response data or raise a useful error."""
    if isinstance(response, dict):
        return response

    status_code = getattr(response, "status_code", None)
    if status_code == 401:
        raise FamilySearchAuthenticationError(
            _(
                "Failed authentication with FamilySearch. In the Family Trees "
                "menu, choose FamilySearch Sign in..., then try again."
            )
        )
    if isinstance(status_code, int) and status_code >= 400:
        message = _("FamilySearch %(operation)s failed (HTTP %(status)s).") % {
            "operation": operation,
            "status": status_code,
        }
        detail = _response_error_detail(response)
        if detail:
            message += " " + detail
        LOG.warning(
            "FamilySearch %s failed (HTTP %s): %s",
            operation,
            status_code,
            str(getattr(response, "text", "") or "")[:500],
        )
        raise RuntimeError(message)

    json_method = getattr(response, "json", None)
    if not callable(json_method):
        raise RuntimeError(
            _("FamilySearch %(operation)s returned an invalid response.")
            % {"operation": operation}
        )
    try:
        data = json_method()
    except Exception as err:
        raise RuntimeError(
            _("FamilySearch %(operation)s returned invalid JSON.")
            % {"operation": operation}
        ) from err
    if not isinstance(data, dict):
        raise RuntimeError(
            _("FamilySearch %(operation)s returned an invalid response.")
            % {"operation": operation}
        )
    return data


# ------------------------------------------------------------
#
# FamilySearch ID utilities
#
# ------------------------------------------------------------
def is_familysearch_id(value: str | None) -> bool:
    """
    Check if a string matches the standard FamilySearch person ID pattern.

    :param value: String to test (e.g. 'GSVF-SGV' or 'KWCR-1234').
    :returns: True if value matches '<4 alphanumeric>-<3 to 4 alphanumeric>'.
    :rtype: bool
    """
    if not value:
        return False
    return bool(_FS_ID_REGEX.match(str(value).strip()))


def extract_familysearch_id(text: str | None) -> str:
    """
    Extract a normalized uppercase FamilySearch person ID from text or URL.

    :param text: Text, URL, or identifier string.
    :returns: Extracted FamilySearch ID or empty string if not found.
    :rtype: str
    """
    val = (text or "").strip()
    if not val:
        return ""

    match = _URL_ID_REGEX.search(val)
    if match:
        return match.group(1).upper()

    match = _BARE_ID_REGEX.search(val)
    if match:
        return match.group(1).upper()

    return ""


def get_familysearch_id(person: Any) -> str:
    """
    Return the FamilySearch person ID stored on a Gramps Person, if any.

    :param person: Person object to inspect.
    :returns: FamilySearch ID or empty string.
    :rtype: str
    """
    if person is None:
        return ""
    fsid = fs_utilities.get_fsftid(person)
    if fsid:
        return str(fsid).strip().upper()

    for attr in getattr(person, "get_attribute_list", lambda: [])():
        attr_type = str(attr.get_type() or "")
        if attr_type in ("_FSFTID", "FamilySearch ID"):
            val = str(attr.get_value() or "").strip()
            if val:
                return val.upper()
    return ""


# ------------------------------------------------------------
#
# FamilySearchInterface
#
# ------------------------------------------------------------
class FamilySearchInterface:
    """
    Interface for interacting with FamilySearch REST services and Tree API.
    """

    def __init__(self, session: Session | None = None) -> None:
        """
        Initialize the interface with an existing or active Session.

        :param session: Optional FamilySearch Session instance.
        """
        self._session = session

    @property
    def session(self) -> Session | None:
        """
        Return the FamilySearch session instance.
        """
        if self._session is not None:
            return self._session
        if GLOBAL_SESSION is not None:
            return GLOBAL_SESSION
        if SESSION is not None:
            return SESSION
        try:
            return Session.from_config()
        except Exception:
            return None

    def is_authenticated(self) -> bool:
        """
        Check if the session is currently authenticated.

        :returns: True if session has valid token or active connection.
        :rtype: bool
        """
        sess = self.session
        if sess is None:
            return False
        if bool(getattr(sess, "access_token", None)):
            return True
        if bool(getattr(sess, "connected", False)):
            return True
        logged_val = getattr(sess, "logged", False)
        if callable(logged_val):
            return bool(logged_val())
        return bool(logged_val)

    def search_person(
        self,
        query: str = "",
        first_name: str = "",
        last_name: str = "",
        birth_date: str = "",
        death_date: str = "",
        gender: str = "",
        birth_place: str = "",
        death_place: str = "",
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """
        Search FamilySearch Tree for matching individuals.

        :param query: Free-form search string or FSID.
        :param first_name: Given name constraint.
        :param last_name: Surname constraint.
        :param birth_date: Birth year or date constraint.
        :param death_date: Death year or date constraint.
        :param gender: Gender constraint.
        :param birth_place: Birth place constraint.
        :param death_place: Death place constraint.
        :param limit: Maximum results to retrieve.
        :returns: List of result dictionaries containing ID, name, lifespan,
            gender, and birth/death dates and places.
        :rtype: list[dict[str, Any]]
        """
        sess = self.session
        if sess is None:
            return []

        clean_query = (query or "").strip()
        fsid = extract_familysearch_id(clean_query)
        if fsid:
            endpoint = f"/platform/tree/persons/{fsid}"
            get_url = getattr(sess, "get_url", None)
            try:
                if callable(get_url):
                    response = get_url(endpoint)
                else:
                    get_json = getattr(sess, "get_jsonurl", None) or getattr(
                        sess, "get_json", None
                    )
                    response = get_json(endpoint) if callable(get_json) else None
                profile = _response_data(response, _("profile lookup"))
            except Exception as err:
                LOG.warning("FamilySearch profile lookup failed for %s: %s", fsid, err)
                raise
            gedcomx = profile.get("gedcomx") or profile.get("gedcomX") or {}
            persons = profile.get("persons") or gedcomx.get("persons")
            person_data = (
                persons[0]
                if isinstance(persons, list)
                and persons
                and isinstance(persons[0], dict)
                else profile
            )
            result = _search_result(fsid, person_data)
            return [result] if result else []

        params = _search_params(
            query=clean_query,
            first_name=first_name,
            last_name=last_name,
            birth_date=birth_date,
            death_date=death_date,
            gender=gender,
            birth_place=birth_place,
            death_place=death_place,
        )
        if not params:
            return []
        params["count"] = str(limit)

        headers = {"Accept": "application/x-gedcomx-atom+json"}

        data: dict[str, Any] | None = None
        get_url = getattr(sess, "get_url", None)
        if callable(get_url):
            try:
                resp = get_url(
                    "/platform/tree/search",
                    headers=headers,
                    params=params,
                )
                data = _response_data(resp, _("search"))
            except Exception as err:
                LOG.warning("FamilySearch search request failed: %s", err)
                raise
        else:
            get_json = getattr(sess, "get_jsonurl", None) or getattr(
                sess, "get_json", None
            )
            if callable(get_json):
                endpoint = "/platform/tree/search?" + urlencode(params)
                try:
                    data = _response_data(
                        get_json(endpoint, headers=headers), _("search")
                    )
                except Exception as err:
                    LOG.warning("FamilySearch search request failed: %s", err)
                    raise

        if data is None:
            raise RuntimeError(_("FamilySearch search is unavailable."))

        entries = data.get("entries")
        if entries is None:
            entries = (data.get("feed") or {}).get("entries")
        if not isinstance(entries, list):
            return []

        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content") or {}
            gedcomx = content.get("gedcomx") or content.get("gedcomX") or {}
            persons = gedcomx.get("persons") or entry.get("persons") or []
            p_data = persons[0] if (persons and isinstance(persons[0], dict)) else {}

            fid = extract_familysearch_id(
                str(p_data.get("id") or "")
            ) or extract_familysearch_id(str(entry.get("id") or ""))
            if not fid or fid in seen:
                continue
            seen.add(fid)

            result = _search_result(
                fid, p_data, str(entry.get("title") or "").strip() or fid
            )
            if result:
                results.append(result)

        return results

    def get_tree(
        self,
        fsid: str,
        ancestors: int = 0,
        descendants: int = 0,
        include_spouses: bool = False,
        include_notes: bool = True,
        include_sources: bool = True,
    ) -> fs_tree_mod.Tree:
        """
        Fetch a Tree structure starting at a root FamilySearch ID.

        :param fsid: Root person FamilySearch ID.
        :param ancestors: Generations of ancestors to fetch.
        :param descendants: Generations of descendants to fetch.
        :param include_spouses: Whether to fetch spouses of individuals.
        :param include_notes: Whether to fetch notes.
        :param include_sources: Whether to fetch citations and source descriptions.
        :returns: Populated Tree instance.
        :rtype: Tree
        """
        tree_obj = fs_tree_mod.Tree()
        sess = self.session
        if sess is not None:
            setattr(fs_tree_mod, "_fs_session", sess)

        clean_id = normalize_fs_id(fsid)
        tree_obj.add_persons([clean_id])

        if ancestors > 0:
            todo = {clean_id}
            done = set()
            for _ in range(ancestors):
                if not todo:
                    break
                done |= todo
                todo = tree_obj.add_parents(set(todo)) - done

        if descendants > 0:
            todo = {clean_id}
            done = set()
            for _ in range(descendants):
                if not todo:
                    break
                done |= todo
                todo = tree_obj.add_children(set(todo)) - done

        if include_spouses:
            all_ids = set(tree_obj._persons.keys())
            tree_obj.add_spouses(all_ids)

        return tree_obj


# ------------------------------------------------------------
#
# FamilySearchGWizard
#
# ------------------------------------------------------------
class FamilySearchGWizard(GedGWizard):
    """
    GWizard implementation for querying and merging FamilySearch genealogical
    profiles and relatives into an active Gramps database.
    """

    def __init__(self, db: DbWriteBase) -> None:
        """
        Initialize the FamilySearchGWizard.

        :param db: The target Gramps database instance.
        """
        super().__init__(db)

    @classmethod
    def is_familysearch_id(cls, value: str) -> bool:
        """
        Check if a string matches the standard FamilySearch ID pattern.

        :param value: String to test.
        :returns: True if valid FSID.
        """
        return is_familysearch_id(value)

    def match(self, source_person_handle: str) -> list[dict[str, Any]]:
        """
        Find potential matching persons in the target database.

        :param source_person_handle: Handle of the person in the source database.
        :returns: List of target candidates with match details.
        """
        return self._match(source_person_handle=source_person_handle)

    def _connect(self, **kwargs: Any) -> bool:
        """
        Configure connection details for the FamilySearch query.

        :param query: FamilySearch ID or URL.
        :param fsid: Explicit FamilySearch ID.
        :param ancestors: Ancestor generations to crawl (default 0).
        :param descendants: Descendant generations to crawl (default 0).
        :param include_spouses: Whether to fetch spouses.
        :param include_notes: Whether to fetch notes.
        :param include_sources: Whether to fetch sources.
        :param session: Optional Session instance.
        :param client: Optional FamilySearchInterface instance.
        :param tree_data: Optional pre-loaded Tree or mock data for testing.
        :returns: True if valid query, fsid, or tree_data is supplied.
        :rtype: bool
        """
        tree_data = kwargs.get("tree_data")
        query = str(kwargs.get("query") or kwargs.get("fsid") or "").strip()
        fsid = extract_familysearch_id(query)

        if not fsid and tree_data is None:
            LOG.error(
                "A FamilySearch ID or tree_data is required for FamilySearch merge."
            )
            return False

        client = kwargs.get("client")
        if client is None:
            session = kwargs.get("session")
            client = FamilySearchInterface(session=session)

        self.context["query"] = fsid or query
        self.context["fsid"] = fsid
        self.context["ancestors"] = int(kwargs.get("ancestors", 0))
        self.context["descendants"] = int(kwargs.get("descendants", 0))
        self.context["include_spouses"] = bool(kwargs.get("include_spouses", False))
        self.context["include_notes"] = bool(kwargs.get("include_notes", True))
        self.context["include_sources"] = bool(kwargs.get("include_sources", True))
        self.context["client"] = client
        self.context["tree_data"] = tree_data
        return True

    def _load(self, **kwargs: Any) -> list[Person]:
        """
        Load records from FamilySearch into an in-memory staging database.

        :returns: A list of Person objects loaded from FamilySearch.
        :rtype: list[Person]
        """
        fsid = self.context.get("fsid") or extract_familysearch_id(
            self.context.get("query", "")
        )
        tree_data = self.context.get("tree_data")
        client: FamilySearchInterface = (
            self.context.get("client") or FamilySearchInterface()
        )

        if tree_data is not None:
            tree_obj = tree_data
        else:
            ancestors = int(self.context.get("ancestors", 0))
            descendants = int(self.context.get("descendants", 0))
            include_spouses = bool(self.context.get("include_spouses", False))
            include_notes = bool(self.context.get("include_notes", True))
            include_sources = bool(self.context.get("include_sources", True))

            tree_obj = client.get_tree(
                fsid=fsid,
                ancestors=ancestors,
                descendants=descendants,
                include_spouses=include_spouses,
                include_notes=include_notes,
                include_sources=include_sources,
            )

        source_db = make_database("sqlite")
        source_db.load(":memory:")

        try:
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
        except (AttributeError, TypeError):
            LOG.debug("ID prefixes not set: this Gramps version differs")

        # Staging into source_db while keeping global active tree state isolated
        saved_index = dict(fs_utilities.FS_INDEX_PEOPLE)
        try:
            fs_utilities.FS_INDEX_PEOPLE.clear()

            importer = FSToGrampsImporter()
            importer.dbstate = types.SimpleNamespace(db=source_db)
            importer.noreimport = False
            importer.import_cpr = True
            importer.fs_TreeImp = tree_obj

            with DbTxn(_("FamilySearch GWizard Staging"), source_db) as txn:
                importer.txn = txn

                # 1. Places
                for fs_place in list(getattr(tree_obj, "places", []) or []):
                    add_place(source_db, txn, fs_place)

                # 2. Persons
                persons_to_import = list(getattr(tree_obj, "persons", []) or [])
                if not persons_to_import and hasattr(tree_obj, "_persons"):
                    persons_to_import = list(tree_obj._persons.values())

                for fs_person in persons_to_import:
                    importer.add_person(source_db, txn, fs_person)

                # 3. Couple relationships
                for fs_rel in list(getattr(tree_obj, "relationships", []) or []):
                    if getattr(fs_rel, "type", "") == "http://gedcomx.org/Couple":
                        importer.add_family(fs_rel)

                # 4. Parent-child relationships
                for fs_cpr in list(
                    getattr(tree_obj, "childAndParentsRelationships", []) or []
                ):
                    importer.add_child(fs_cpr)

                # 5. Connect single root parent link if needed
                if fsid:
                    importer._ensure_root_parent_link(fsid)

                # 6. Ensure provenance and link URL on all staged persons
                for handle in source_db.get_person_handles():
                    person = source_db.get_person_from_handle(handle)
                    p_fsid = get_familysearch_id(person)
                    if p_fsid:
                        ensure_provenance(source_db, txn, person, p_fsid)

        finally:
            fs_utilities.FS_INDEX_PEOPLE.clear()
            fs_utilities.FS_INDEX_PEOPLE.update(saved_index)

        self.context["source_db"] = source_db
        self.source_db = source_db
        self.context["source_title"] = fsid or _("FamilySearch")

        loaded_persons = [
            source_db.get_person_from_handle(h) for h in source_db.get_person_handles()
        ]
        return loaded_persons

    def _apply(self, **kwargs: Any) -> bool:
        """
        Apply resolutions for FamilySearch merge, ensuring FamilySearch ID
        and provenance are preserved on the target person.

        :param kwargs: Arguments passed to GedGWizard._apply.
        :returns: True if apply was successful.
        :rtype: bool
        """
        applied = super()._apply(**kwargs)

        target_person_handle = kwargs.get("target_person_handle")
        source_person_handle = kwargs.get("source_person_handle")

        if applied and target_person_handle and source_person_handle:
            source_db = self.context.get("source_db")
            if source_db:
                s_p = source_db.get_person_from_handle(source_person_handle)
                t_p = self.db.get_person_from_handle(target_person_handle)
                if s_p and t_p:
                    fs_id = get_familysearch_id(s_p)
                    if fs_id:
                        with DbTxn(
                            _("Update FamilySearch Provenance"), self.db
                        ) as trans:
                            ensure_provenance(self.db, trans, t_p, fs_id)

        return applied
