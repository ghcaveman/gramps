#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026       Kevin White <gocaveman@gmail.com>
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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""Engine for analyzing, auditing, and linking media to citations in Gramps.

Provides identity extraction for Media and Citations, discordance and compatibility
scoring heuristics to prevent attaching images to wrong sources/citations, and
scanner routines to promote, unpack, and link media.
"""

from __future__ import annotations

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
import re
import logging
from dataclasses import dataclass, field
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.lib import MediaRef
from gramps.plugins.tool.gwizard_common import is_locked

_ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext
LOG = logging.getLogger(__name__)

# -------------------------------------------------------------------------
#
# Classification dictionaries & conflict categories
#
# -------------------------------------------------------------------------
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "census": [
        "census",
        "population schedule",
        "enumeration",
        "census schedule",
        "federal census",
        "state census",
    ],
    "birth": [
        "birth",
        "born",
        "baptism",
        "christening",
        "natal",
        "birth certificate",
        "parish register",
    ],
    "death": [
        "death",
        "died",
        "decease",
        "obituary",
        "funeral",
        "burial",
        "interment",
        "cemetery",
        "grave",
        "tombstone",
        "headstone",
        "memorial",
        "death certificate",
    ],
    "marriage": [
        "marriage",
        "married",
        "wedding",
        "matrimony",
        "spousal",
        "divorce",
        "marriage license",
        "marriage certificate",
        "banns",
    ],
    "military": [
        "military",
        "draft",
        "enlistment",
        "service",
        "veteran",
        "regiment",
        "army",
        "navy",
        "pension",
        "wwi",
        "wwii",
        "civil war",
    ],
    "probate": [
        "probate",
        "will",
        "testament",
        "estate",
        "executor",
        "administration",
        "intestate",
    ],
    "land": [
        "deed",
        "land grant",
        "land patent",
        "homestead",
        "property conveyance",
        "indenture",
    ],
    "directory": [
        "directory",
        "city directory",
        "gazetteer",
        "telephone directory",
    ],
    "immigration": [
        "passenger",
        "manifest",
        "immigration",
        "naturalization",
        "border crossing",
        "ship arrival",
    ],
    "portrait": [
        "portrait",
        "photo",
        "photograph",
        "headshot",
        "picture",
        "snapshot",
    ],
}

# Incompatible category pairings for documentary evidence
INCOMPATIBLE_CATEGORIES: dict[str, set[str]] = {
    "census": {"marriage", "death", "military", "probate", "land", "immigration"},
    "marriage": {"census", "birth", "death", "probate", "land", "military"},
    "birth": {"marriage", "death", "census", "probate", "land", "military"},
    "death": {"marriage", "birth", "census", "land"},
    "probate": {"census", "marriage", "birth"},
    "military": {"census", "marriage", "birth"},
    "land": {"census", "marriage", "birth", "death"},
}


# -------------------------------------------------------------------------
#
# Data models
#
# -------------------------------------------------------------------------
@dataclass
class MediaIdentity:
    """Structured identity tokens extracted from a Media object."""

    handle: str = ""
    gramps_id: str = ""
    path: str = ""
    desc: str = ""
    filename: str = ""
    year: str = ""
    category: str = ""
    doc_type: str = ""
    surname: str = ""
    given: str = ""
    sheet_page: str = ""
    is_portrait: bool = False
    is_locked: bool = False
    raw_tokens: list[str] = field(default_factory=list)


@dataclass
class CitationIdentity:
    """Structured identity tokens extracted from a Citation and its Source."""

    handle: str = ""
    gramps_id: str = ""
    source_handle: str = ""
    source_title: str = ""
    source_author: str = ""
    source_pub: str = ""
    page: str = ""
    year: str = ""
    category: str = ""
    doc_type: str = ""
    surnames: list[str] = field(default_factory=list)
    givens: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    sheet_page: str = ""
    has_media: bool = False
    media_handles: list[str] = field(default_factory=list)
    raw_tokens: list[str] = field(default_factory=list)


@dataclass
class CompatibilityResult:
    """Evaluation result comparing a Media object and a Citation."""

    score: int = 0
    status: str = "ambiguous"  # safe | ambiguous | conflict
    is_match: bool = False
    reasons: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


# -------------------------------------------------------------------------
#
# Helper utilities
#
# -------------------------------------------------------------------------
def extract_year(text: str) -> str:
    """Extract a 4-digit calendar year (1500-2099) from text, if present."""
    if not text:
        return ""
    match = re.search(r"(?:^|[^\d])(1[5-9]\d{2}|20\d{2})(?:[^\d]|$)", text)
    return match.group(1) if match else ""


def extract_sheet_page(text: str) -> str:
    """Extract sheet, page, or certificate numbers from text."""
    if not text:
        return ""
    # Sheet 12A, Sheet_12A, Sheet 12, p. 45, page 123, cert 402, ed 16-100
    m = re.search(
        r"(?i)(?:^|[\W_])(?:sheet|page|p\.|cert|certificate|line)[\s_]*([0-9]+[a-z]?)(?:$|[\W_])",
        text,
    )
    if m:
        return m.group(1).upper()
    m_num = re.search(r"(?i)(?:^|[\W_])ed[\s_]*([0-9]+[\-_][0-9]+)(?:$|[\W_])", text)
    if m_num:
        return m_num.group(1)
    return ""


def detect_category(text: str) -> str:
    """Detect primary genealogical document category from keywords."""
    if not text:
        return ""
    lower = re.sub(r"[\W_]+", " ", text).lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        for kw in kws:
            if re.search(rf"\b{re.escape(kw)}\b", lower):
                return cat
    return ""


def clean_name_token(text: str) -> str:
    """Clean a surname or given name string for matching."""
    return re.sub(r"[^\w\-]", "", text or "").strip().lower()


# -------------------------------------------------------------------------
#
# Extractors
#
# -------------------------------------------------------------------------
def extract_media_identity(media: Any, db: Any = None) -> MediaIdentity:
    """Extract identity tokens from a Media primary object."""
    if media is None:
        return MediaIdentity()

    handle = str(media.get_handle() or "")
    gid = str(media.get_gramps_id() or "")
    raw_path = str(media.get_path() or "")
    desc = str(media.get_description() or "")

    basename = os.path.basename(raw_path)
    stem, _ext = os.path.splitext(basename)

    combined_text = f"{stem} {desc}"
    year = extract_year(combined_text)
    if not year and hasattr(media, "get_date_object"):
        date_obj = media.get_date_object()
        if date_obj and hasattr(date_obj, "get_year"):
            y = date_obj.get_year()
            if y:
                year = str(y)

    cat = detect_category(combined_text)
    sheet_page = extract_sheet_page(combined_text)

    # Detect portrait vs documentary evidence
    is_portrait = cat == "portrait" or bool(
        re.search(
            r"\b(?:portrait|headshot|profile photo|gravestone photo)\b",
            combined_text,
            re.IGNORECASE,
        )
    )

    # Extract name parts from filename or description (e.g., Smith_John_1940)
    surname = ""
    given = ""
    name_match = re.search(r"^([a-zA-Z\-']+)[_,\-\s]+([a-zA-Z\-']+)", stem)
    if name_match:
        part1 = name_match.group(1)
        part2 = name_match.group(2)
        if (
            detect_category(part1) == ""
            and detect_category(part2) == ""
            and not extract_year(part1)
        ):
            surname = clean_name_token(part1)
            given = clean_name_token(part2)

    locked = is_locked(db, media) if db else False

    tokens = [t.lower() for t in re.split(r"[\W_]+", f"{stem} {desc}") if len(t) >= 3]

    return MediaIdentity(
        handle=handle,
        gramps_id=gid,
        path=raw_path,
        desc=desc,
        filename=stem,
        year=year,
        category=cat,
        doc_type=cat or "document",
        surname=surname,
        given=given,
        sheet_page=sheet_page,
        is_portrait=is_portrait,
        is_locked=locked,
        raw_tokens=tokens,
    )


def extract_citation_identity(db: Any, citation: Any) -> CitationIdentity:
    """Extract identity tokens from a Citation object and its Source."""
    if citation is None:
        return CitationIdentity()

    handle = str(citation.get_handle() or "")
    gid = str(citation.get_gramps_id() or "")
    page = str(citation.get_page() or "").strip()

    src_handle = str(citation.get_reference_handle() or "")
    src_title = ""
    src_author = ""
    src_pub = ""
    if db and src_handle and hasattr(db, "get_source_from_handle"):
        src = db.get_source_from_handle(src_handle)
        if src:
            src_title = str(src.get_title() or "").strip()
            src_author = str(src.get_author() or "").strip()
            src_pub = str(src.get_publication_info() or "").strip()

    combined_text = f"{src_title} {page} {src_pub}"
    year = extract_year(combined_text)
    if not year and hasattr(citation, "get_date_object"):
        date_obj = citation.get_date_object()
        if date_obj and hasattr(date_obj, "get_year"):
            y = date_obj.get_year()
            if y:
                year = str(y)

    cat = detect_category(combined_text)
    sheet_page = extract_sheet_page(page)

    surnames: list[str] = []
    givens: list[str] = []
    event_types: list[str] = []

    # Inspect backlinks from citation to Person, Family, or Event
    if db and hasattr(db, "find_backlink_handles") and handle:
        try:
            for cname, b_handle in db.find_backlink_handles(handle):
                if cname == "Person":
                    person = (
                        db.get_person_from_handle(b_handle)
                        if hasattr(db, "get_person_from_handle")
                        else None
                    )
                    if person and person.get_primary_name():
                        pname = person.get_primary_name()
                        s = clean_name_token(pname.get_surname())
                        g = clean_name_token(pname.get_first_name())
                        if s and s not in surnames:
                            surnames.append(s)
                        if g and g not in givens:
                            givens.append(g)
                elif cname == "Family":
                    family = (
                        db.get_family_from_handle(b_handle)
                        if hasattr(db, "get_family_from_handle")
                        else None
                    )
                    if family and hasattr(family, "get_father_handle"):
                        f_h = family.get_father_handle()
                        father = (
                            db.get_person_from_handle(f_h)
                            if (f_h and hasattr(db, "get_person_from_handle"))
                            else None
                        )
                        if father and father.get_primary_name():
                            s = clean_name_token(
                                father.get_primary_name().get_surname()
                            )
                            if s and s not in surnames:
                                surnames.append(s)
                elif cname == "Event":
                    event = (
                        db.get_event_from_handle(b_handle)
                        if hasattr(db, "get_event_from_handle")
                        else None
                    )
                    if event:
                        e_type = str(event.get_type() or "")
                        if e_type and e_type not in event_types:
                            event_types.append(e_type)
                        if not year and hasattr(event, "get_date_object"):
                            ed = event.get_date_object()
                            if ed and hasattr(ed, "get_year") and ed.get_year():
                                year = str(ed.get_year())
        except Exception:
            pass

    # Existing media links on this citation
    media_handles: list[str] = []
    if hasattr(citation, "get_media_list"):
        for mref in citation.get_media_list() or []:
            ref = str(getattr(mref, "ref", "") or "")
            if ref and ref not in media_handles:
                media_handles.append(ref)

    tokens = [
        t.lower()
        for t in re.split(r"[\W_]+", f"{src_title} {page} {src_pub}")
        if len(t) >= 3
    ]

    return CitationIdentity(
        handle=handle,
        gramps_id=gid,
        source_handle=src_handle,
        source_title=src_title,
        source_author=src_author,
        source_pub=src_pub,
        page=page,
        year=year,
        category=cat,
        doc_type=cat or "document",
        surnames=surnames,
        givens=givens,
        event_types=event_types,
        sheet_page=sheet_page,
        has_media=len(media_handles) > 0,
        media_handles=media_handles,
        raw_tokens=tokens,
    )


# -------------------------------------------------------------------------
#
# Compatibility heuristic & scoring
#
# -------------------------------------------------------------------------
def compute_citation_media_compatibility(
    media: MediaIdentity, citation: CitationIdentity
) -> CompatibilityResult:
    """Compute compatibility score and list matches/conflicts between Media and Citation."""
    score = 0
    reasons: list[str] = []
    conflicts: list[str] = []

    # 1. Document Category Compatibility
    if media.category and citation.category:
        if media.category == citation.category:
            score += 35
            reasons.append(
                _("Category match: {category} (+35)").format(
                    category=media.category.title()
                )
            )
        elif citation.category in INCOMPATIBLE_CATEGORIES.get(media.category, set()):
            score -= 50
            conflicts.append(
                _(
                    "Severe category conflict: image is '{media_category}' but "
                    "citation is '{citation_category}'"
                ).format(
                    media_category=media.category.title(),
                    citation_category=citation.category.title(),
                )
            )
    elif media.is_portrait:
        # Portraits attached to documentary citations (like census or wills) are suspect
        if citation.category in {"census", "probate", "land"}:
            score -= 20
            conflicts.append(
                _(
                    "Type conflict: personal portrait matched with archival document "
                    "citation"
                )
            )

    # 2. Chronological Year Matching
    if media.year and citation.year:
        try:
            m_yr = int(media.year)
            c_yr = int(citation.year)
            diff = abs(m_yr - c_yr)
            if diff == 0:
                score += 30
                reasons.append(
                    _("Exact year match: {year} (+30)").format(year=media.year)
                )
            elif diff == 1:
                score += 20
                reasons.append(
                    _(
                        "Contemporary year match: {media_year} vs {citation_year} (+20)"
                    ).format(media_year=media.year, citation_year=citation.year)
                )
            elif diff > 1:
                # Severity scales with distance
                penalty = min(60, 20 + diff * 5)
                score -= penalty
                conflicts.append(
                    _(
                        "Year mismatch: image is {media_year} vs citation is "
                        "{citation_year} (diff {difference})"
                    ).format(
                        media_year=media.year,
                        citation_year=citation.year,
                        difference=diff,
                    )
                )
        except ValueError:
            pass

    # 3. Surname & Family Matching
    if media.surname and citation.surnames:
        if media.surname in citation.surnames:
            score += 25
            reasons.append(
                _("Surname match: {surname} (+25)").format(
                    surname=media.surname.title()
                )
            )
        else:
            # Surnames exist in both but none match
            score -= 25
            conflicts.append(
                _(
                    "Surname mismatch: image specifies '{media_surname}' but citation "
                    "references [{citation_surnames}]"
                ).format(
                    media_surname=media.surname.title(),
                    citation_surnames=", ".join(s.title() for s in citation.surnames),
                )
            )

    # 4. Given Name Matching
    if media.given and citation.givens:
        if media.given in citation.givens:
            score += 10
            reasons.append(
                _("Given name match: {given} (+10)").format(given=media.given.title())
            )

    # 5. Page / Sheet / Line Number Matching
    if media.sheet_page and citation.sheet_page:
        if media.sheet_page == citation.sheet_page:
            score += 25
            reasons.append(
                _("Sheet/Page match: {page} (+25)").format(page=media.sheet_page)
            )
        else:
            score -= 30
            conflicts.append(
                _(
                    "Sheet/Page mismatch: image mentions {media_page} vs citation "
                    "specifies {citation_page}"
                ).format(media_page=media.sheet_page, citation_page=citation.sheet_page)
            )

    # 6. Keyword overlap bonus
    if media.raw_tokens and citation.raw_tokens:
        overlap = set(media.raw_tokens).intersection(set(citation.raw_tokens))
        # Filter out trivial common words
        meaningful = {
            w
            for w in overlap
            if w
            not in {
                "the",
                "and",
                "for",
                "with",
                "from",
                "page",
                "image",
                "media",
                "record",
            }
        }
        if meaningful:
            pts = min(15, len(meaningful) * 5)
            score += pts
            reasons.append(
                _("Keyword overlap [{keywords}] (+{points})").format(
                    keywords=", ".join(meaningful), points=pts
                )
            )

    # Normalization & Status Assignment
    score = max(0, min(score, 100))

    if conflicts:
        status = "conflict"
        is_match = False
    elif score >= 70:
        status = "safe"
        is_match = True
    elif score >= 40:
        status = "ambiguous"
        is_match = True
    else:
        status = "ambiguous"
        is_match = False

    return CompatibilityResult(
        score=score,
        status=status,
        is_match=is_match,
        reasons=reasons,
        conflicts=conflicts,
    )


# -------------------------------------------------------------------------
#
# Scanner routines
#
# -------------------------------------------------------------------------
def find_promotable_gallery_media(db: Any) -> list[dict[str, Any]]:
    """Find document media in Person or Event galleries that match an attached Citation."""
    if not db:
        return []

    results: list[dict[str, Any]] = []

    # 1. Person galleries
    if hasattr(db, "iter_people"):
        for person in db.iter_people():
            p_media_refs = list(person.get_media_list() or [])
            p_cit_refs = list(person.get_citation_list() or [])
            if not p_media_refs or not p_cit_refs:
                continue

            person_name = ""
            if person.get_primary_name():
                person_name = (
                    f"{person.get_primary_name().get_surname()}, "
                    f"{person.get_primary_name().get_first_name()}"
                )

            for mref in p_media_refs:
                m_handle = str(getattr(mref, "ref", "") or "")
                media_obj = (
                    db.get_media_from_handle(m_handle)
                    if hasattr(db, "get_media_from_handle")
                    else None
                )
                if not media_obj:
                    continue

                m_id = extract_media_identity(media_obj, db)
                if m_id.is_portrait:
                    continue  # Keep genuine portraits in person gallery

                for cit_h in p_cit_refs:
                    cit_obj = (
                        db.get_citation_from_handle(cit_h)
                        if hasattr(db, "get_citation_from_handle")
                        else None
                    )
                    if not cit_obj:
                        continue
                    if m_handle in [str(r.ref) for r in cit_obj.get_media_list() or []]:
                        continue  # Already attached to citation

                    c_id = extract_citation_identity(db, cit_obj)
                    compat = compute_citation_media_compatibility(m_id, c_id)

                    if compat.is_match and compat.score >= 50:
                        results.append(
                            {
                                "action": "promote_from_person",
                                "media_handle": m_handle,
                                "citation_handle": cit_h,
                                "owner_handle": person.get_handle(),
                                "owner_type": "Person",
                                "owner_display": (
                                    f"Person: {person_name} [{person.get_gramps_id()}]"
                                ),
                                "media_identity": m_id,
                                "citation_identity": c_id,
                                "compatibility": compat,
                                "is_locked": m_id.is_locked,
                            }
                        )

    # 2. Event galleries
    if hasattr(db, "iter_events"):
        for event in db.iter_events():
            e_media_refs = list(event.get_media_list() or [])
            e_cit_refs = list(event.get_citation_list() or [])
            if not e_media_refs or not e_cit_refs:
                continue

            e_type = str(event.get_type() or "Event")

            for mref in e_media_refs:
                m_handle = str(getattr(mref, "ref", "") or "")
                media_obj = (
                    db.get_media_from_handle(m_handle)
                    if hasattr(db, "get_media_from_handle")
                    else None
                )
                if not media_obj:
                    continue

                m_id = extract_media_identity(media_obj, db)

                for cit_h in e_cit_refs:
                    cit_obj = (
                        db.get_citation_from_handle(cit_h)
                        if hasattr(db, "get_citation_from_handle")
                        else None
                    )
                    if not cit_obj:
                        continue
                    if m_handle in [str(r.ref) for r in cit_obj.get_media_list() or []]:
                        continue

                    c_id = extract_citation_identity(db, cit_obj)
                    compat = compute_citation_media_compatibility(m_id, c_id)

                    if compat.is_match and compat.score >= 50:
                        results.append(
                            {
                                "action": "promote_from_event",
                                "media_handle": m_handle,
                                "citation_handle": cit_h,
                                "owner_handle": event.get_handle(),
                                "owner_type": "Event",
                                "owner_display": (
                                    f"Event: {e_type} [{event.get_gramps_id()}]"
                                ),
                                "media_identity": m_id,
                                "citation_identity": c_id,
                                "compatibility": compat,
                                "is_locked": m_id.is_locked,
                            }
                        )

    return results


def find_unpackable_source_media(db: Any) -> list[dict[str, Any]]:
    """Find media attached at the Source level that should be unpacked to Citations."""
    if not db or not hasattr(db, "iter_sources"):
        return []

    # Map citations by source handle
    citations_by_source: dict[str, list[Any]] = {}
    if hasattr(db, "iter_citations"):
        for cit in db.iter_citations():
            s_h = str(cit.get_reference_handle() or "")
            if s_h:
                citations_by_source.setdefault(s_h, []).append(cit)

    results: list[dict[str, Any]] = []

    for src in db.iter_sources():
        src_h = str(src.get_handle() or "")
        src_media = list(src.get_media_list() or [])
        # Only unpack if source has media AND child citations
        if not src_media or src_h not in citations_by_source:
            continue

        cits = citations_by_source[src_h]
        for mref in src_media:
            m_handle = str(getattr(mref, "ref", "") or "")
            media_obj = (
                db.get_media_from_handle(m_handle)
                if hasattr(db, "get_media_from_handle")
                else None
            )
            if not media_obj:
                continue

            m_id = extract_media_identity(media_obj, db)

            best_match: tuple[Any, CompatibilityResult] | None = None
            for cit in cits:
                c_id = extract_citation_identity(db, cit)
                compat = compute_citation_media_compatibility(m_id, c_id)
                if compat.is_match and (
                    best_match is None or compat.score > best_match[1].score
                ):
                    best_match = (cit, compat)

            if best_match and best_match[1].score >= 60:
                best_cit, best_compat = best_match
                results.append(
                    {
                        "action": "unpack_from_source",
                        "media_handle": m_handle,
                        "citation_handle": best_cit.get_handle(),
                        "owner_handle": src_h,
                        "owner_type": "Source",
                        "owner_display": (
                            f"Source: {src.get_title()} [{src.get_gramps_id()}]"
                        ),
                        "media_identity": m_id,
                        "citation_identity": extract_citation_identity(db, best_cit),
                        "compatibility": best_compat,
                        "is_locked": m_id.is_locked,
                    }
                )

    return results


def find_orphan_media_matches(db: Any) -> list[dict[str, Any]]:
    """Match orphan or unlinked media files to media-less citations."""
    if not db or not hasattr(db, "iter_media") or not hasattr(db, "iter_citations"):
        return []

    # Find citations lacking media
    citations_without_media = []
    for cit in db.iter_citations():
        if not cit.get_media_list():
            citations_without_media.append(cit)

    if not citations_without_media:
        return []

    # Cache citation identities
    cit_ids = [
        (cit, extract_citation_identity(db, cit)) for cit in citations_without_media
    ]

    results: list[dict[str, Any]] = []

    for media in db.iter_media():
        m_handle = str(media.get_handle() or "")
        # Check if media is unreferenced or orphan (no backlinks to any object)
        backlinks = (
            list(db.find_backlink_handles(m_handle))
            if hasattr(db, "find_backlink_handles")
            else []
        )
        if backlinks:
            continue

        m_id = extract_media_identity(media, db)
        if m_id.is_portrait:
            continue

        for cit, c_id in cit_ids:
            compat = compute_citation_media_compatibility(m_id, c_id)
            if compat.is_match and compat.score >= 70 and not compat.conflicts:
                results.append(
                    {
                        "action": "link_orphan",
                        "media_handle": m_handle,
                        "citation_handle": cit.get_handle(),
                        "owner_handle": "",
                        "owner_type": "None",
                        "owner_display": _("Orphan / Unlinked Media"),
                        "media_identity": m_id,
                        "citation_identity": c_id,
                        "compatibility": compat,
                        "is_locked": m_id.is_locked,
                    }
                )

    return results


def audit_existing_citation_media_links(db: Any) -> list[dict[str, Any]]:
    """Audit citations currently referencing media to identify suspect attachments."""
    if not db or not hasattr(db, "iter_citations"):
        return []

    issues: list[dict[str, Any]] = []

    for cit in db.iter_citations():
        m_list = list(cit.get_media_list() or [])
        if not m_list:
            continue

        c_id = extract_citation_identity(db, cit)

        for mref in m_list:
            m_handle = str(getattr(mref, "ref", "") or "")
            media_obj = (
                db.get_media_from_handle(m_handle)
                if hasattr(db, "get_media_from_handle")
                else None
            )
            if not media_obj:
                continue

            m_id = extract_media_identity(media_obj, db)
            compat = compute_citation_media_compatibility(m_id, c_id)

            if compat.status == "conflict" or (compat.conflicts and compat.score < 40):
                issues.append(
                    {
                        "citation_handle": cit.get_handle(),
                        "media_handle": m_handle,
                        "citation_identity": c_id,
                        "media_identity": m_id,
                        "compatibility": compat,
                    }
                )

    return issues


# -------------------------------------------------------------------------
#
# Safe mutation routines
#
# -------------------------------------------------------------------------
def apply_link_media_to_citation(
    db: Any, trans: Any, citation_handle: str, media_handle: str
) -> bool:
    """Attach a Media object to a Citation via a MediaRef."""
    if not db or not citation_handle or not media_handle:
        return False

    cit = (
        db.get_citation_from_handle(citation_handle)
        if hasattr(db, "get_citation_from_handle")
        else None
    )
    if not cit:
        return False

    # Check if already present
    existing = [str(r.ref) for r in cit.get_media_list() or []]
    if media_handle in existing:
        return False

    mref = MediaRef()
    mref.set_reference_handle(media_handle)
    cit.add_media_reference(mref)

    if hasattr(db, "commit_citation"):
        db.commit_citation(cit, trans)
    return True


def apply_unlink_media_from_citation(
    db: Any, trans: Any, citation_handle: str, media_handle: str
) -> bool:
    """Detach a Media object from a Citation."""
    if not db or not citation_handle or not media_handle:
        return False

    cit = (
        db.get_citation_from_handle(citation_handle)
        if hasattr(db, "get_citation_from_handle")
        else None
    )
    if not cit:
        return False

    m_list = list(cit.get_media_list() or [])
    new_list = [r for r in m_list if str(getattr(r, "ref", "")) != media_handle]
    if len(new_list) == len(m_list):
        return False

    cit.set_media_list(new_list)
    if hasattr(db, "commit_citation"):
        db.commit_citation(cit, trans)
    return True


def apply_promote_media_to_citation(
    db: Any,
    trans: Any,
    citation_handle: str,
    media_handle: str,
    detach_from_owner: bool = False,
    owner_type: str = "",
    owner_handle: str = "",
) -> bool:
    """Link media to citation and optionally detach from Person or Event gallery.

    Only locked media (checked in Media Fix) reach this step, so the lock
    does not stop the detach; detaching changes the owner, not the media.
    """
    linked = apply_link_media_to_citation(db, trans, citation_handle, media_handle)
    if not linked:
        return False

    if detach_from_owner and owner_type and owner_handle:
        if owner_type == "Person" and hasattr(db, "get_person_from_handle"):
            person = db.get_person_from_handle(owner_handle)
            if person:
                m_list = list(person.get_media_list() or [])
                new_list = [
                    r for r in m_list if str(getattr(r, "ref", "")) != media_handle
                ]
                person.set_media_list(new_list)
                if hasattr(db, "commit_person"):
                    db.commit_person(person, trans)
        elif owner_type == "Event" and hasattr(db, "get_event_from_handle"):
            event = db.get_event_from_handle(owner_handle)
            if event:
                m_list = list(event.get_media_list() or [])
                new_list = [
                    r for r in m_list if str(getattr(r, "ref", "")) != media_handle
                ]
                event.set_media_list(new_list)
                if hasattr(db, "commit_event"):
                    db.commit_event(event, trans)

    return True


def apply_unpack_source_media(
    db: Any,
    trans: Any,
    source_handle: str,
    citation_handle: str,
    media_handle: str,
    detach_from_source: bool = False,
) -> bool:
    """Unpack media from a Source down to a Citation."""
    linked = apply_link_media_to_citation(db, trans, citation_handle, media_handle)
    if not linked:
        return False

    if detach_from_source and source_handle and hasattr(db, "get_source_from_handle"):
        source = db.get_source_from_handle(source_handle)
        if source:
            m_list = list(source.get_media_list() or [])
            new_list = [r for r in m_list if str(getattr(r, "ref", "")) != media_handle]
            source.set_media_list(new_list)
            if hasattr(db, "commit_source"):
                db.commit_source(source, trans)

    return True
