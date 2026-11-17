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
Provenance handling for the GWizard WikiTree merge.

Design rules (each fixes a problem seen in the first test export):

* ONE shared repository ("WikiTree") and ONE shared source ("WikiTree"),
  never a source per profile.
* ONE citation per (source, profile ID).  Its PAGE is the bare profile ID,
  and its date is the retrieval date, so a stale profile can be recognised.
* The profile URL is stored once, as an Internet link on the person.
  No URL note, no URL in the source title.
* The WikiTree ID is stored once, as a person attribute.
* Every function is idempotent: running the merge twice changes nothing
  the second time, and a conflicting existing ID is reported, never
  silently overwritten.
* Facts taken from WikiTree (birth, death, names...) are cited at the fact
  level with :func:`cite`, not only on the person.

The caller owns the transaction: pass an open ``DbTxn`` as ``trans``.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.lib import (
    Attribute,
    AttributeType,
    Citation,
    Date,
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

REPO_NAME = "WikiTree (Free Family Tree)"
SOURCE_TITLE = "WikiTree"
SOURCE_AUTHOR = "WikiTree Community"
SITE_URL = "https://www.wikitree.com"
ID_ATTRIBUTE = "WikiTree ID"
URL_DESCRIPTION = "WikiTree profile"

# WikiTree IDs look like "White-94900": a last-name part, a hyphen, digits.
# Names may contain apostrophes, hyphens or non-ASCII letters, so match
# any non-space, non-slash text before the final "-digits".
_ID_RE = re.compile(r"^[^\s/?#]+-\d+$")
_URL_ID_RE = re.compile(r"wikitree\.com/wiki/([^\s/?#]+)", re.IGNORECASE)
_LEGACY_TITLE_RE = re.compile(r"^WikiTree\s+-\s+(\S+)\s*$")


# ------------------------------------------------------------
#
# IDs and URLs
#
# ------------------------------------------------------------
def normalize_profile_id(value: str) -> str:
    """
    Return a bare WikiTree ID from an ID, a profile URL, or "WikiTree: ID".

    Raises ValueError for anything that does not look like a profile ID,
    so a bad value is rejected before it is written to the tree.
    """
    text = (value or "").strip()
    if text.lower().startswith("wikitree:"):
        text = text.split(":", 1)[1].strip()
    match = _URL_ID_RE.search(text)
    if match:
        text = match.group(1)
    if not _ID_RE.match(text):
        raise ValueError(f"Not a WikiTree profile ID: {value!r}")
    return text


def profile_url(profile_id: str) -> str:
    """Return the canonical profile URL for a profile ID."""
    return f"{SITE_URL}/wiki/{normalize_profile_id(profile_id)}"


def _url_key(path: str) -> str:
    """Compare URLs ignoring scheme, "www.", case of host, trailing slash."""
    key = re.sub(r"^https?://", "", (path or "").strip(), flags=re.I)
    key = re.sub(r"^www\.", "", key, flags=re.I)
    return key.rstrip("/").lower()


# ------------------------------------------------------------
#
# Dates
#
# ------------------------------------------------------------
_STATUS_TO_MODIFIER = {
    "guess": Date.MOD_ABOUT,
    "before": Date.MOD_BEFORE,
    "after": Date.MOD_AFTER,
}


def wikitree_date_to_gramps(value: str | None, status: str | None = None) -> Date:
    """
    Convert a WikiTree date ("YYYY-MM-DD", zeros for unknown parts) to a Date.

    ``status`` is WikiTree's per-date certainty ("guess", "before", "after",
    "certain" or empty).  Unknown parts stay unknown instead of becoming
    January 1st.  An empty or all-zero date returns an empty Date.
    Verify the exact field names against a real API response.
    """
    date = Date()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", (value or "").strip())
    if not match:
        return date
    year, month, day = (int(part) for part in match.groups())
    if year == 0:
        return date
    if month == 0:
        day = 0
    modifier = _STATUS_TO_MODIFIER.get((status or "").strip().lower(), Date.MOD_NONE)
    date.set(
        quality=Date.QUAL_NONE,
        modifier=modifier,
        calendar=Date.CAL_GREGORIAN,
        value=(day, month, year, False),
    )
    return date


# ------------------------------------------------------------
#
# Result record
#
# ------------------------------------------------------------
@dataclass
class ProvenanceResult:
    """What ensure_provenance did, for the merge summary dialog."""

    repository: Repository | None = None
    source: Source | None = None
    citation: Citation | None = None
    created: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        """True if anything was created or updated."""
        return bool(self.created)


# ------------------------------------------------------------
#
# Shared repository and source
#
# ------------------------------------------------------------
def find_or_create_repository(
    db: Any, trans: Any, result: ProvenanceResult | None = None
) -> Repository:
    """Return the single WikiTree repository, creating it if needed."""
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
    """Return the single shared WikiTree source, creating it if needed."""
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
    profile_id: str,
    result: ProvenanceResult | None = None,
) -> Citation:
    """
    Return the citation for this profile, creating it if needed.

    An existing citation is reused; its date is refreshed to today because
    the profile has just been read again.
    """
    for citation in db.iter_citations():
        if (
            citation.get_reference_handle() == source.handle
            and citation.get_page() == profile_id
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
    citation.set_page(profile_id)
    citation.set_date_object(Today())
    db.add_citation(citation, trans)
    if result is not None:
        result.created.append("citation")
    return citation


def cite(obj: Any, citation: Citation) -> bool:
    """
    Attach ``citation`` to a person, event, name, attribute, etc.

    Returns True if it was added, False if already present.  The caller
    commits ``obj`` afterwards (db.commit_event, db.commit_person...).
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
def _ensure_id_attribute(
    person: Any, profile_id: str, result: ProvenanceResult
) -> bool:
    """Add the WikiTree ID attribute unless present; report a mismatch."""
    for attr in person.get_attribute_list():
        if str(attr.get_type()) == ID_ATTRIBUTE:
            if attr.get_value().strip() != profile_id:
                result.conflicts.append(
                    f"Person already has WikiTree ID {attr.get_value()!r}, "
                    f"profile is {profile_id!r}; left unchanged"
                )
            return False
    attr = Attribute()
    attr.set_type(AttributeType((AttributeType.CUSTOM, ID_ATTRIBUTE)))
    attr.set_value(profile_id)
    person.add_attribute(attr)
    result.created.append("attribute")
    return True


def _ensure_profile_link(
    person: Any, profile_id: str, result: ProvenanceResult
) -> bool:
    """Add the profile URL as an Internet link unless already present."""
    wanted = _url_key(profile_url(profile_id))
    for url in person.get_url_list():
        if _url_key(url.get_path()) == wanted:
            return False
    url = Url()
    url.set_path(profile_url(profile_id))
    url.set_type(UrlType.WEB_HOME)
    url.set_description(URL_DESCRIPTION)
    person.add_url(url)
    result.created.append("link")
    return True


def ensure_provenance(
    db: Any, trans: Any, person: Any, profile_id: str
) -> ProvenanceResult:
    """
    Attach WikiTree identity and provenance to ``person``, idempotently.

    Creates or reuses the shared repository and source and the per-profile
    citation, adds the ID attribute and profile link, cites the person, and
    commits the person only if something changed.  Raises ValueError for a
    malformed profile ID before touching the database.
    """
    profile_id = normalize_profile_id(profile_id)
    result = ProvenanceResult()
    result.repository = find_or_create_repository(db, trans, result)
    result.source = find_or_create_source(db, trans, result.repository, result)
    result.citation = find_or_create_citation(
        db, trans, result.source, profile_id, result
    )

    _ensure_id_attribute(person, profile_id, result)
    _ensure_profile_link(person, profile_id, result)
    if cite(person, result.citation):
        result.created.append("person citation")
    if any(item in ("attribute", "link", "person citation") for item in result.created):
        db.commit_person(person, trans)
    return result


# ------------------------------------------------------------
#
# Migration of the first-version output
#
# ------------------------------------------------------------
def migrate_legacy_sources(db: Any, trans: Any) -> int:
    """
    Fold per-profile sources ("WikiTree - White-94900") into the shared one.

    Citations are repointed at the shared source, their PAGE is reduced to
    the bare ID ("WikiTree: White-94900" -> "White-94900"), and the emptied
    legacy source is removed.  A legacy source is removed only when no
    object other than its own citations still refers to it.  Returns the
    number of legacy sources folded in.
    """
    result = ProvenanceResult()
    repo = find_or_create_repository(db, trans, result)
    shared = find_or_create_source(db, trans, repo, result)
    folded = 0
    for source in list(db.iter_sources()):
        match = _LEGACY_TITLE_RE.match(source.get_title())
        if source.handle == shared.handle or not match:
            continue
        for citation in list(db.iter_citations()):
            if citation.get_reference_handle() != source.handle:
                continue
            page = citation.get_page().strip()
            if page.lower().startswith("wikitree:"):
                page = page.split(":", 1)[1].strip()
            citation.set_page(page or match.group(1))
            citation.set_reference_handle(shared.handle)
            db.commit_citation(citation, trans)
        still_used = any(True for _ in db.find_backlink_handles(source.handle))
        if not still_used:
            db.remove_source(source.handle, trans)
        folded += 1
    return folded
