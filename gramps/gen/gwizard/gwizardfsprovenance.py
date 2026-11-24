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
Provenance handling for the GWizard FamilySearch merge.

Design rules:
* ONE shared repository ("FamilySearch") and ONE shared source ("FamilySearch Family Tree").
* ONE citation per (source, profile ID). Its PAGE is the bare FamilySearch ID,
  and its date is the retrieval date.
* The profile URL is stored as an Internet link on the person.
* The FamilySearch ID is stored as the canonical '_FSFTID' person attribute.
* Every function is idempotent: running the merge twice changes nothing
  the second time.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
from dataclasses import dataclass, field
import logging
import re
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.lib import (
    Attribute,
    Citation,
    Repository,
    RepositoryType,
    RepoRef,
    Source,
    SourceMediaType,
    Url,
    UrlType,
)
from gramps.gen.lib.date import Today

LOG = logging.getLogger(__name__)

REPO_NAME = "FamilySearch"
SOURCE_TITLE = "FamilySearch Family Tree"
SOURCE_AUTHOR = "The Church of Jesus Christ of Latter-day Saints"
SITE_URL = "https://www.familysearch.org"
ID_ATTRIBUTE = "_FSFTID"
URL_DESCRIPTION = "FamilySearch profile"

_FS_ID_RE = re.compile(r"\b([A-Za-z0-9]{4}-[A-Za-z0-9]{3,4})\b")
_URL_ID_RE = re.compile(
    r"familysearch\.org/(?:tree/person/(?:details/)?|platform/tree/persons/)([A-Za-z0-9]{4}-[A-Za-z0-9]{3,4})",
    re.IGNORECASE,
)


# ------------------------------------------------------------
#
# IDs and URLs
#
# ------------------------------------------------------------
def normalize_fs_id(value: str | None) -> str:
    """
    Return a bare FamilySearch person ID from an ID, a profile URL, or text.

    :param value: String to extract ID from.
    :returns: Extracted uppercase FamilySearch ID.
    :raises ValueError: If value does not contain a valid FamilySearch ID.
    """
    text = (value or "").strip()
    match = _URL_ID_RE.search(text)
    if match:
        return match.group(1).upper()
    match = _FS_ID_RE.search(text)
    if match:
        return match.group(1).upper()
    raise ValueError(f"Not a FamilySearch person ID: {value!r}")


def profile_url(fs_id: str) -> str:
    """
    Return the canonical profile URL for a FamilySearch person ID.

    :param fs_id: FamilySearch person ID.
    :returns: Web URL string.
    """
    return f"{SITE_URL}/tree/person/details/{normalize_fs_id(fs_id)}"


def _url_key(path: str) -> str:
    """
    Compare URLs ignoring scheme, 'www.', case of host, and trailing slash.
    """
    key = re.sub(r"^https?://", "", (path or "").strip(), flags=re.I)
    key = re.sub(r"^www\.", "", key, flags=re.I)
    return key.rstrip("/").lower()


# ------------------------------------------------------------
#
# Result record
#
# ------------------------------------------------------------
@dataclass
class ProvenanceResult:
    """
    Tracks provenance objects created or updated during merge.
    """

    repository: Repository | None = None
    source: Source | None = None
    citation: Citation | None = None
    created: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        """
        Return True if anything was created or updated.
        """
        return bool(self.created)


# ------------------------------------------------------------
#
# Shared repository and source
#
# ------------------------------------------------------------
def find_or_create_repository(
    db: Any, trans: Any, result: ProvenanceResult | None = None
) -> Repository:
    """
    Return the single FamilySearch repository, creating it if needed.
    """
    for repo in db.iter_repositories():
        if repo.get_name() == REPO_NAME:
            return repo
    repo = Repository()
    repo.set_name(REPO_NAME)
    repo.set_type(RepositoryType.WEBSITE)
    url = Url()
    url.set_path(SITE_URL)
    url.set_type(UrlType.WEB_HOME)
    url.set_description(REPO_NAME)
    repo.add_url(url)
    db.add_repository(repo, trans)
    if result is not None:
        result.created.append("repository")
    return repo


def find_or_create_source(
    db: Any, trans: Any, repo: Repository, result: ProvenanceResult | None = None
) -> Source:
    """
    Return the single shared FamilySearch source, creating it if needed.
    """
    for source in db.iter_sources():
        if source.get_title() == SOURCE_TITLE and any(
            ref.get_reference_handle() == repo.handle
            for ref in source.get_reporef_list()
        ):
            return source
    source = Source()
    source.set_title(SOURCE_TITLE)
    source.set_author(SOURCE_AUTHOR)
    source.set_publication_info(SITE_URL)
    reporef = RepoRef()
    reporef.set_reference_handle(repo.handle)
    reporef.set_media_type(SourceMediaType.ELECTRONIC)
    source.add_repo_reference(reporef)
    db.add_source(source, trans)
    if result is not None:
        result.created.append("source")
    return source


# ------------------------------------------------------------
#
# Citations
#
# ------------------------------------------------------------
def find_or_create_citation(
    db: Any,
    trans: Any,
    source: Source,
    fs_id: str,
    result: ProvenanceResult | None = None,
) -> Citation:
    """
    Return the citation for this FamilySearch person ID, creating it if needed.
    """
    for citation in db.iter_citations():
        if (
            citation.get_reference_handle() == source.handle
            and citation.get_page() == fs_id
        ):
            today = Today()
            if citation.get_date_object().sortval < today.sortval:
                citation.set_date_object(today)
                db.commit_citation(citation, trans)
                if result is not None:
                    result.created.append("citation date refreshed")
            return citation
    citation = Citation()
    citation.set_reference_handle(source.handle)
    citation.set_page(fs_id)
    citation.set_date_object(Today())
    db.add_citation(citation, trans)
    if result is not None:
        result.created.append("citation")
    return citation


def cite(obj: Any, citation: Citation) -> bool:
    """
    Attach citation to an object (Person, Event, etc.) if not already present.
    """
    if citation.handle in obj.get_citation_list():
        return False
    obj.add_citation(citation.handle)
    return True


# ------------------------------------------------------------
#
# Person-level data: ID attribute and profile link
#
# ------------------------------------------------------------
def _ensure_id_attribute(person: Any, fs_id: str, result: ProvenanceResult) -> bool:
    """
    Add the FamilySearch ID attribute unless present; report a mismatch.
    """
    for attr in person.get_attribute_list():
        if str(attr.get_type()) in (ID_ATTRIBUTE, "FamilySearch ID"):
            if attr.get_value().strip().upper() != fs_id:
                result.conflicts.append(
                    f"Person already has FamilySearch ID {attr.get_value()!r}, "
                    f"new ID is {fs_id!r}; left unchanged"
                )
            return False
    attr = Attribute()
    attr.set_type(ID_ATTRIBUTE)
    attr.set_value(fs_id)
    person.add_attribute(attr)
    result.created.append("attribute")
    return True


def _ensure_profile_link(person: Any, fs_id: str, result: ProvenanceResult) -> bool:
    """
    Add the profile URL as an Internet link unless already present.
    """
    wanted = _url_key(profile_url(fs_id))
    for url in person.get_url_list():
        if _url_key(url.get_path()) == wanted:
            return False
    url = Url()
    url.set_path(profile_url(fs_id))
    url.set_type(UrlType.WEB_HOME)
    url.set_description(URL_DESCRIPTION)
    person.add_url(url)
    result.created.append("link")
    return True


def ensure_provenance(db: Any, trans: Any, person: Any, fs_id: str) -> ProvenanceResult:
    """
    Attach FamilySearch identity and provenance to person, idempotently.
    """
    norm_id = normalize_fs_id(fs_id)
    result = ProvenanceResult()
    result.repository = find_or_create_repository(db, trans, result)
    result.source = find_or_create_source(db, trans, result.repository, result)
    result.citation = find_or_create_citation(db, trans, result.source, norm_id, result)

    _ensure_id_attribute(person, norm_id, result)
    _ensure_profile_link(person, norm_id, result)
    if cite(person, result.citation):
        result.created.append("person citation")
    if any(item in ("attribute", "link", "person citation") for item in result.created):
        db.commit_person(person, trans)
    return result
