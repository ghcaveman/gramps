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

"""Base class and interfaces for the GWizard import framework.

This module was previously named ``gwizard.py``.  It has been renamed to
``gwizard_base.py`` to better reflect that it provides the core abstract
implementation used by concrete GWizard importers (e.g. the GEDCOM
implementation in ``gwizardgedcom.py``).
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import abc
from dataclasses import dataclass, field
import difflib
import functools
import logging
import re
import unicodedata
from typing import Any, NamedTuple

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.errors import HandleError
from gramps.gen.types import PersonHandle
from gramps.gen.lib import Person, Event, Name
from gramps.gen.soundex import soundex
from gramps.gen.const import GRAMPS_LOCALE as glocale

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)

_ = glocale.translation.gettext


# ------------------------------------------------------------
#
# GWizardCompareRow
#
# ------------------------------------------------------------
class GWizardCompareRow(NamedTuple):
    """Represent a single side‑by‑side comparative difference.

    ``status`` is one of ``"match"``, ``"differ"``, ``"source_only"`` or
    ``"target_only"``.  ``field`` holds the human‑readable name of the compared
    attribute.  ``source_val`` and ``target_val`` contain the values from the
    incoming source and the existing Gramps database respectively.
    ``source_date``/``target_date`` and ``field_type`` are optional metadata.
    ``extra_data`` can carry any additional payload required by the UI.
    """

    status: str
    field: str
    source_val: str
    target_val: str
    source_date: str = ""
    target_date: str = ""
    field_type: str = ""
    extra_data: Any = None


# ------------------------------------------------------------
#
# GWizardBase
#
# ------------------------------------------------------------
class GWizardBase(abc.ABC):
    """Abstract base class representing the step‑by‑step wizard workflow.

    The workflow sequence is: ``connect → load → match → compare → apply``.
    Concrete subclasses implement the private ``_connect`` … ``_apply`` hooks.
    """

    def __init__(self, db: DbWriteBase) -> None:
        self.db = db
        self.context: dict[str, Any] = {}
        self.current_step: str = ""

    def get_steps(self) -> list[str]:
        return ["connect", "load", "match", "compare", "apply"]

    def get_step_title(self, step: str) -> str:
        titles = {
            "connect": _("Configure Connection"),
            "load": _("Load Data"),
            "match": _("Find Matching Persons"),
            "compare": _("Compare Differences"),
            "apply": _("Apply Changes"),
        }
        return titles.get(step, step)

    def get_step_description(self, step: str) -> str:
        descriptions = {
            "connect": _("Configure file path or authenticate with online service."),
            "load": _("Load/parse the external genealogy data into memory."),
            "match": _("Search for potential matches in your database."),
            "compare": _("Compare fields side‑by‑side between the source and target."),
            "apply": _("Merge selected changes or add new records to the database."),
        }
        return descriptions.get(step, step)

    def run_step(self, step: str, **kwargs: Any) -> Any:
        self.current_step = step
        LOG.debug("Running GWizard step: %s with args: %s", step, kwargs)
        if step == "connect":
            return self._connect(**kwargs)
        if step == "load":
            return self._load(**kwargs)
        if step == "match":
            return self._match(**kwargs)
        if step == "compare":
            return self._compare(**kwargs)
        if step == "apply":
            return self._apply(**kwargs)
        raise ValueError(f"Unknown step: {step}")

    @abc.abstractmethod
    def _connect(self, **kwargs: Any) -> bool: ...

    @abc.abstractmethod
    def _load(self, **kwargs: Any) -> Any: ...

    @abc.abstractmethod
    def _match(self, **kwargs: Any) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    def _compare(self, **kwargs: Any) -> list[GWizardCompareRow]: ...

    @abc.abstractmethod
    def _apply(self, **kwargs: Any) -> bool: ...


# ------------------------------------------------------------
# Safe handle lookups (unchanged from original implementation)
# ------------------------------------------------------------
def safe_get(db: Any, handle: str | None, getter_name: str, what: str) -> Any | None:
    if not handle:
        return None
    try:
        return getattr(db, getter_name)(handle)
    except HandleError:
        LOG.debug("Stale %s handle ignored: %s", what, handle)
        return None


def safe_get_person(db: Any, handle: str | None) -> Person | None:
    return safe_get(db, handle, "get_person_from_handle", "person")


def safe_get_family(db: Any, handle: str | None) -> Any | None:
    return safe_get(db, handle, "get_family_from_handle", "family")


def safe_get_event(db: Any, handle: str | None) -> Event | None:
    return safe_get(db, handle, "get_event_from_handle", "event")


def safe_get_place(db: Any, handle: str | None) -> Any | None:
    return safe_get(db, handle, "get_place_from_handle", "place")


def safe_get_source(db: Any, handle: str | None) -> Any | None:
    return safe_get(db, handle, "get_source_from_handle", "source")


def safe_get_repository(db: Any, handle: str | None) -> Any | None:
    return safe_get(db, handle, "get_repository_from_handle", "repository")


def is_empty_event(event: Any, db: Any = None) -> bool:
    """
    Return True when an event has nothing to show: no date, no place and
    no description.

    The compare window and merge dialog leave such events out of their
    Events & Other Records lists. Empty events (a bare "Birth" with no
    details, say) carry no information to compare, and when both sides
    have one they could not be ordered or paired meaningfully.

    :param event: The event to test, or None.
    :param db: The event's database. When given, a place whose name and
        title are both blank counts as no place.
    :returns: True if the event is missing or has no displayable data.
    """
    if event is None:
        return True
    try:
        date = event.get_date_object()
        if date is not None and date.is_empty() is not True:
            return False
        place_handle = event.get_place_handle()
        if place_handle:
            place = safe_get_place(db, place_handle) if db is not None else None
            if place is None:
                return False
            name = place.get_name().get_value()
            title = place.get_title()
            if not isinstance(name, str) or name.strip():
                return False
            if not isinstance(title, str) or title.strip():
                return False
        description = event.get_description()
        if not isinstance(description, str) or description.strip():
            return False
    except Exception:
        # When in doubt, show the event.
        return False
    return True


def date_specificity_score(date_obj: Any) -> float:
    """
    Return a numeric score representing the precision and specificity of a Date.

    Scores range from 0.0 (empty) to 4.0 (exact day, month, year):
    - 0.0: Empty, none, or invalid
    - 0.5: Text-only date without numeric components
    - 1.0: Broad modifier (before/after/about/range) with year only
    - 2.0: Exact year only (e.g. '1877')
    - 2.5: Broad modifier with month and year
    - 3.0: Exact month and year (e.g. 'JAN 1877')
    - 3.5: Broad modifier with full day, month, year
    - 4.0: Exact day, month, year (e.g. '25 JAN 1877')
    """
    if date_obj is None:
        return 0.0
    if hasattr(date_obj, "is_empty") and date_obj.is_empty():
        return 0.0

    try:
        year = int(date_obj.get_year()) if hasattr(date_obj, "get_year") else 0
        month = int(date_obj.get_month()) if hasattr(date_obj, "get_month") else 0
        day = int(date_obj.get_day()) if hasattr(date_obj, "get_day") else 0
        modifier = (
            int(date_obj.get_modifier()) if hasattr(date_obj, "get_modifier") else 0
        )
        quality = int(date_obj.get_quality()) if hasattr(date_obj, "get_quality") else 0
    except Exception:
        return 0.0

    if year <= 0:
        text = str(getattr(date_obj, "get_text", lambda: "")() or "").strip()
        return 0.5 if text else 0.0

    if day > 0 and month > 0:
        base = 4.0
    elif month > 0:
        base = 3.0
    else:
        base = 2.0

    if modifier != 0:
        base -= 0.5
    if quality != 0:
        base -= 0.2

    return max(0.0, base)


def compare_date_specificity(date_a: Any, date_b: Any) -> int:
    """
    Compare the specificity of two date objects.

    :returns: 1 if date_a is more specific than date_b,
             -1 if date_b is more specific than date_a,
              0 if both have equivalent specificity.
    :rtype: int
    """
    score_a = date_specificity_score(date_a)
    score_b = date_specificity_score(date_b)
    if score_a > score_b:
        return 1
    if score_a < score_b:
        return -1
    return 0


def place_specificity_score(place: Any, db: Any = None) -> float:
    """
    Return a numeric score representing the level of detail of a place.

    Evaluates the number of enclosing geographic levels (e.g. comma-separated
    tokens), coordinates, and hierarchy depth.
    """
    if place is None:
        return 0.0

    title = ""
    has_coords = False
    hierarchy_depth = 0

    if isinstance(place, str):
        title = place.strip()
    else:
        try:
            name_obj = place.get_name() if hasattr(place, "get_name") else None
            title = (
                str(name_obj.get_value() or "")
                if name_obj
                else str(place.get_title() or "")
            ).strip()
            lat = str(getattr(place, "get_latitude", lambda: "")() or "").strip()
            lon = str(getattr(place, "get_longitude", lambda: "")() or "").strip()
            has_coords = bool(lat and lon)
            placerefs: list[Any] = getattr(place, "get_placeref_list", lambda: [])()
            hierarchy_depth = len(placerefs)
        except Exception:
            title = str(place).strip()

    if not title and not has_coords and hierarchy_depth == 0:
        return 0.0

    tokens = [t.strip() for t in title.split(",") if t.strip()]
    score = float(len(tokens))
    if has_coords:
        score += 1.0
    score += float(hierarchy_depth) * 0.5
    return score


def compare_place_specificity(
    place_a: Any, place_b: Any, db_a: Any = None, db_b: Any = None
) -> int:
    """
    Compare the specificity of two places.

    :returns: 1 if place_a is more specific than place_b,
             -1 if place_b is more specific than place_a,
              0 if both have equivalent specificity.
    :rtype: int
    """
    score_a = place_specificity_score(place_a, db_a)
    score_b = place_specificity_score(place_b, db_b)
    if score_a > score_b:
        return 1
    if score_a < score_b:
        return -1
    return 0


def vital_event_ref(db: Any, person: Person | None, kind: str) -> Any | None:
    """
    Return the reference to the person's birth or death event.

    The person's own birth/death reference is used when it has data;
    otherwise the first Birth/Death event in the person's list that has
    data. Only when every candidate is empty (no date, place or
    description) is the empty one returned, the person's own reference
    first. ``kind`` is 'birth' or 'death'.
    """
    if person is None or db is None:
        return None
    try:
        ref = person.get_birth_ref() if kind == "birth" else person.get_death_ref()
    except Exception:
        ref = None
    if ref is not None and not is_empty_event(
        safe_get_event(db, getattr(ref, "ref", None)), db
    ):
        return ref
    first_empty = ref
    try:
        refs = person.get_event_ref_list() or []
    except Exception:
        return first_empty
    want_birth = kind == "birth"
    for cand in refs:
        try:
            event = safe_get_event(db, getattr(cand, "ref", None))
        except Exception:
            continue
        if event is None:
            continue
        try:
            etype = event.get_type()
        except Exception:
            continue
        try:
            is_match = etype.is_birth() if want_birth else etype.is_death()
        except Exception:
            continue
        if not is_match:
            continue
        if not is_empty_event(event, db):
            return cand
        if first_empty is None:
            first_empty = cand
    return first_empty


# ------------------------------------------------------------
# Source matching helpers (unchanged)
# ------------------------------------------------------------
SOURCE_MATCHED = "matched"
SOURCE_AMBIGUOUS = "ambiguous"
SOURCE_NEW = "new"

_MARKUP_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")


def normalize_source_text(text: str | None) -> str:
    text = unicodedata.normalize("NFKC", _MARKUP_TAG_RE.sub("", text or ""))
    return " ".join(text.split()).casefold()


def source_signature(source: Any) -> tuple[str, str, str] | None:
    title = normalize_source_text(source.get_title())
    if not title:
        return None
    return (
        title,
        normalize_source_text(source.get_author()),
        normalize_source_text(source.get_publication_info()),
    )


class SourceMatcher:
    def __init__(self, db: Any) -> None:
        self.db = db
        self._index: dict[tuple[str, str, str], list[str]] | None = None

    def _ensure_index(self) -> dict[tuple[str, str, str], list[str]]:
        if self._index is None:
            index: dict[tuple[str, str, str], list[str]] = {}
            for source in self.db.iter_sources():
                signature = source_signature(source)
                if signature is not None:
                    index.setdefault(signature, []).append(source.handle)
            self._index = index
        return self._index

    def find(self, source: Any) -> tuple[str | None, str]:
        signature = source_signature(source)
        if signature is None:
            return None, SOURCE_NEW
        handles = self._ensure_index().get(signature, [])
        if len(handles) == 1:
            return handles[0], SOURCE_MATCHED
        if len(handles) > 1:
            return None, SOURCE_AMBIGUOUS
        return None, SOURCE_NEW

    def add(self, source: Any) -> None:
        signature = source_signature(source)
        if signature is None:
            return
        handles = self._ensure_index().setdefault(signature, [])
        if source.handle not in handles:
            handles.append(source.handle)


def source_match_report(source_db: Any, target_db: Any) -> list[dict[str, str]]:
    matcher = SourceMatcher(target_db)
    rows = []
    for source in source_db.iter_sources():
        handle, status = matcher.find(source)
        rows.append(
            {
                "title": source.get_title() or "",
                "author": source.get_author() or "",
                "status": status,
                "target_handle": handle or "",
            }
        )
    rows.sort(key=lambda r: (r["status"], r["title"].casefold()))
    return rows


# ------------------------------------------------------------
# Given‑name matching helpers (unchanged)
# ------------------------------------------------------------
_QUOTED_NICK_RE = re.compile(r'"[^"]*"|\([^)]*\)|\'[^\']*\'')


def _strip_embedded_nickname(given: str) -> str:
    return _QUOTED_NICK_RE.sub(" ", given)


def _given_tokens(given: str) -> list[str]:
    cleaned = _strip_embedded_nickname(given)
    cleaned = cleaned.replace("-", " ")
    return [tok.lower() for tok in cleaned.split() if tok]


def score_given_names(source_given: str, target_given: str) -> float:
    s_raw = (source_given or "").strip()
    t_raw = (target_given or "").strip()
    if not s_raw or not t_raw:
        return 0.0
    if s_raw.lower() == t_raw.lower():
        return 1.0
    s_tokens = _given_tokens(s_raw)
    t_tokens = _given_tokens(t_raw)
    if not s_tokens or not t_tokens:
        return 0.0
    if s_tokens == t_tokens:
        return 1.0
    if sorted(s_tokens) == sorted(t_tokens):
        return 0.9
    if set(s_tokens) & set(t_tokens):
        return 0.5
    ratio = difflib.SequenceMatcher(
        None, " ".join(s_tokens), " ".join(t_tokens)
    ).ratio()
    if ratio >= 0.8:
        return 0.6
    if s_tokens[0][0] == t_tokens[0][0]:
        return 0.25
    return 0.0


# Given names repeat constantly across a tree, so scoring the same pair of
# names again and again is wasted work. The score depends only on the two texts.
_cached_given_score = functools.lru_cache(maxsize=1 << 16)(score_given_names)


# ------------------------------------------------------------
# Name part helpers (unchanged)
# ------------------------------------------------------------
def surname_text(name: Name) -> str:
    return " ".join(
        [surn.get_surname() for surn in name.get_surname_list() if surn.get_surname()]
    )


def surname_prefix_text(name: Name) -> str:
    return " ".join(
        [surn.get_prefix() for surn in name.get_surname_list() if surn.get_prefix()]
    )


# ------------------------------------------------------------
# CandidateMatcher (unchanged)
# ------------------------------------------------------------
class PersonProfile(NamedTuple):
    """
    What matching needs to know about a person, read from the database once.

    Scoring many candidates against each other from profiles avoids reading
    both people and their birth events again for every pair.
    """

    gender: int
    given: str  # first name, stripped
    surnames: str  # all surnames as one lower-case text
    soundex: str | None  # soundex of ``surnames``; None when it fails
    first_surname: str  # first surname, lower case
    first_name: str  # first name, stripped, lower case
    birth: tuple[int, int, int] | None  # (year, month, day) of the birth


class CandidateMatcher:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db

    def get_surnames(self, name: Name) -> str:
        return surname_text(name)

    def get_prefixes(self, name: Name) -> str:
        return surname_prefix_text(name)

    def profile(self, person: Person, db: Any | None = None) -> PersonProfile:
        """Return the PersonProfile of ``person`` (read from ``db``)."""
        lookup_db = db if db is not None else self.db
        name = person.get_primary_name()
        surnames = self.get_surnames(name).strip().lower()
        try:
            sx: str | None = soundex(surnames) if surnames else None
        except Exception:  # pylint: disable=broad-except
            sx = None
        first_surname = ""
        if name.surname_list:
            first_surname = (name.surname_list[0].surname or "").lower()
        birth = None
        try:
            birth_ref = vital_event_ref(lookup_db, person, "birth")
            if birth_ref:
                event = safe_get_event(lookup_db, birth_ref.ref)
                if event is not None:
                    date = event.get_date_object()
                    birth = (date.get_year(), date.get_month(), date.get_day())
        except Exception:  # pylint: disable=broad-except
            birth = None
        return PersonProfile(
            gender=person.get_gender(),
            given=name.first_name.strip(),
            surnames=surnames,
            soundex=sx,
            first_surname=first_surname,
            first_name=(name.first_name or "").strip().lower(),
            birth=birth,
        )

    @staticmethod
    def score_profiles(source: PersonProfile, target: PersonProfile) -> float:
        """Score how likely two people are the same person (see score_match)."""
        # Gender must match, or be unknown/other in either
        if source.gender in (Person.MALE, Person.FEMALE) and target.gender in (
            Person.MALE,
            Person.FEMALE,
        ):
            if source.gender != target.gender:
                return -1.0
        score = 0.0
        given_score = 0.0
        if source.given and target.given:
            given_score = _cached_given_score(source.given, target.given)
            score += given_score
        if source.surnames and target.surnames:
            surname_score = 0.0
            if source.surnames == target.surnames:
                surname_score = 1.0
            elif source.soundex is not None and source.soundex == target.soundex:
                surname_score = 0.75
            if given_score == 0.0 and source.given and target.given:
                surname_score = min(surname_score, 0.25)
            score += surname_score
        if source.birth and target.birth:
            s_year, s_mon, s_day = source.birth
            t_year, t_mon, t_day = target.birth
            if s_year > 0 and t_year > 0:
                diff = abs(s_year - t_year)
                if diff != 0:
                    if diff <= 2:
                        score += 0.5
                    elif diff <= 5:
                        score += 0.25
                elif s_mon <= 0 or t_mon <= 0:
                    score += 0.75
                elif s_mon != t_mon:
                    score += 0.5
                elif s_day <= 0 or t_day <= 0:
                    score += 0.85
                elif s_day != t_day:
                    score += 0.75
                else:
                    score += 1.0
        return score

    def score_match(
        self, source: Person, target: Person, source_db: Any | None = None
    ) -> float:
        source_lookup_db = source_db if source_db is not None else self.db
        return self.score_profiles(
            self.profile(source, source_lookup_db), self.profile(target, self.db)
        )

    def find_matches(
        self, source: Person, threshold: float = 1.0, source_db: Any | None = None
    ) -> list[tuple[PersonHandle, float]]:
        results: list[tuple[PersonHandle, float]] = []
        for handle in self.db.iter_person_handles():
            try:
                target = safe_get_person(self.db, handle)
                if target is None:
                    continue
                score = self.score_match(source, target, source_db=source_db)
                if score >= threshold:
                    results.append((PersonHandle(handle), score))
            except Exception:
                continue
        results.sort(key=lambda item: item[1], reverse=True)
        return results


# ------------------------------------------------------------
#
# Record matching
#
# ------------------------------------------------------------
# Scoring of a person found on an outside record source (a WikiTree
# profile, a person named by a NARA record, ...) against a person in the
# Family Tree. WikiTree and NARA turn their own data into a RecordCandidate
# and score it here, so both rank results the same way, and so does the
# GWizard Multi-Archive Record Scan.
#
# The score follows a weighted scheme: surname 35, given and middle names 30,
# birth year 25 (fading to nothing at 5 years apart) and death year 10
# (fading at 3 years), counting only the parts both sides have. Names are
# compared with Jaro-Winkler similarity plus a sound-alike bonus from Gramps'
# Soundex, all in plain Python so the addons need no extra packages. A known
# gender that differs halves the score.

# Match levels for the Multi-Archive Record Scan: which parts must be on both sides and
# count towards the score. Death years are left out of every level.
TIER_GMSB = "g/m/s/b"  # given, middle, surname and birth year
TIER_GSB = "g/s/b"  # given, surname and birth year
TIER_GS = "g/s"  # given and surname
RECORD_TIERS = (TIER_GMSB, TIER_GSB, TIER_GS)


def jaro_winkler(first: str, second: str, prefix_scale: float = 0.1) -> float:
    """
    Return the Jaro-Winkler similarity of two strings, from 0.0 (nothing in
    common) to 1.0 (equal). Comparison is case-insensitive.
    """
    first, second = first.casefold(), second.casefold()
    if first == second:
        return 1.0 if first else 0.0
    if not first or not second:
        return 0.0
    window = max(len(first), len(second)) // 2 - 1
    window = max(window, 0)
    first_matched = [False] * len(first)
    second_matched = [False] * len(second)
    matches = 0
    for i, char in enumerate(first):
        low, high = max(0, i - window), min(len(second), i + window + 1)
        for j in range(low, high):
            if not second_matched[j] and second[j] == char:
                first_matched[i] = second_matched[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    first_chars = [c for c, m in zip(first, first_matched) if m]
    second_chars = [c for c, m in zip(second, second_matched) if m]
    transpositions = sum(a != b for a, b in zip(first_chars, second_chars)) / 2
    jaro = (
        matches / len(first)
        + matches / len(second)
        + (matches - transpositions) / matches
    ) / 3
    prefix = 0
    for a, b in zip(first[:4], second[:4]):
        if a != b:
            break
        prefix += 1
    return jaro + prefix * prefix_scale * (1 - jaro)


def sounds_alike(first: str, second: str) -> bool:
    """Return True when two names have the same (non-empty) Soundex code."""
    try:
        code = soundex(first)
        return bool(code) and code != "Z000" and code == soundex(second)
    except Exception:
        return False


def name_similarity(first: str, second: str) -> float:
    """Jaro-Winkler similarity with a 0.15 bonus for sound-alike names."""
    if not first or not second:
        return 0.0
    bonus = 0.15 if sounds_alike(first, second) else 0.0
    return min(1.0, jaro_winkler(first, second) + bonus)


# ------------------------------------------------------------
#
# RecordQuery
#
# ------------------------------------------------------------
@dataclass
class RecordQuery:
    """The Family Tree person's details used for matching."""

    given: str = ""
    middle: str = ""
    surnames: list[str] = field(default_factory=list)
    birth_year: int | None = None
    death_year: int | None = None
    gender: str = ""  # "male", "female" or "" (any case)

    def has_name(self) -> bool:
        """Return True when there is a name to match against."""
        return bool(self.given or self.surnames)


# ------------------------------------------------------------
#
# RecordCandidate
#
# ------------------------------------------------------------
@dataclass
class RecordCandidate:
    """
    A person found on an outside record source, in the form scoring uses.

    Years are (first, last) ranges, so a date known only to the decade
    ("1840s") is (1840, 1849) and a full date is (year, year). With
    ``maiden_from_middle`` set, the last middle name is also tried as a
    surname (at 0.95), for records that write a married woman as
    "Mary Kreizer Smith".
    """

    given: str = ""
    middle: str = ""
    surnames: list[str] = field(default_factory=list)
    birth_years: tuple[int, int] | None = None
    death_years: tuple[int, int] | None = None
    gender: str = ""
    maiden_from_middle: bool = False


# ------------------------------------------------------------
#
# RecordScore
#
# ------------------------------------------------------------
@dataclass
class RecordScore:
    """How well a candidate fits the Family Tree person."""

    score: float
    compared_years: bool


def year_range(year: int | None) -> tuple[int, int] | None:
    """Return the (first, last) range of a single known year, else None."""
    return (year, year) if year else None


def years_apart(year: int, years: tuple[int, int]) -> int:
    """Return how far a year is outside a (first, last) range; 0 inside it."""
    first, last = years
    if year < first:
        return first - year
    if year > last:
        return year - last
    return 0


def _first_word(text: str) -> str:
    """Return the first word of a name, case-folded."""
    return text.split()[0].casefold() if text.split() else ""


def record_given_similarity(
    query: RecordQuery, candidate: RecordCandidate, use_middle: bool = True
) -> float:
    """
    Given/middle name similarity, allowing initials and swapped names.

    With ``use_middle`` off, differing middle names neither help nor hurt.
    """
    q_given, c_given = query.given.casefold(), candidate.given.casefold()
    if len(q_given) == 1 or len(c_given) == 1:
        direct = 0.85 if q_given[:1] == c_given[:1] else 0.0
    else:
        direct = name_similarity(q_given, c_given)
    c_mid = _first_word(candidate.middle)
    swapped = name_similarity(q_given, c_mid) * 0.85 if c_mid else 0.0
    best = max(direct, swapped)
    q_mid = _first_word(query.middle) if use_middle else ""
    factor = 1.0
    if q_mid and c_mid:
        if q_mid[0] == c_mid[0]:
            if len(q_mid) == 1 or len(c_mid) == 1:
                factor = 1.05
            else:
                factor = 0.9 + 0.15 * jaro_winkler(q_mid, c_mid)
        else:
            factor = 0.85
    return min(1.0, best * factor)


def record_surname_similarity(query: RecordQuery, candidate: RecordCandidate) -> float:
    """
    Best similarity of any of the person's surnames (birth or married) to
    any of the candidate's, or to its maiden name (see RecordCandidate).
    """
    best = 0.0
    words = candidate.middle.split()
    maiden = words[-1] if candidate.maiden_from_middle and words else ""
    for wanted in query.surnames:
        for surname in candidate.surnames:
            best = max(best, name_similarity(wanted, surname))
        if maiden and len(maiden) > 1:
            best = max(best, name_similarity(wanted, maiden) * 0.95)
    return best


def _tier_parts(tier: str | None) -> tuple[bool, bool, bool, bool]:
    """Return (middle, birth required, use birth, use death) for a tier."""
    if tier is None:
        return False, False, True, True
    if tier == TIER_GS:
        return False, False, False, False
    if tier == TIER_GSB:
        return False, True, True, False
    if tier == TIER_GMSB:
        return True, True, True, False
    raise ValueError(f"unknown match tier: {tier}")


def score_record(query: RecordQuery, candidate: RecordCandidate) -> RecordScore:
    """
    Return how well a candidate matches the person, from 0 to 100. Every
    part both sides have counts (names, birth and death years).
    """
    result = _score_record(query, candidate, None)
    return result if result is not None else RecordScore(0.0, False)


def score_record_tier(
    query: RecordQuery, candidate: RecordCandidate, tier: str
) -> RecordScore | None:
    """
    Return how well a candidate matches the person at one match level
    (TIER_GS, TIER_GSB or TIER_GMSB), from 0 to 100.

    Only the tier's parts count, and each must be on both sides: None is
    returned when one is missing, as the tier cannot be judged.
    """
    return _score_record(query, candidate, tier)


def _score_record(
    query: RecordQuery, candidate: RecordCandidate, tier: str | None
) -> RecordScore | None:
    """Score a candidate in full (``tier`` None) or at one tier."""
    need_middle, need_birth, use_birth, use_death = _tier_parts(tier)
    if tier is not None:
        if not (query.given and candidate.given):
            return None
        if not (query.surnames and candidate.surnames):
            return None
        if need_birth and not (query.birth_year and candidate.birth_years):
            return None
        if need_middle and not (query.middle and candidate.middle):
            return None
    score = 0.0
    possible = 0.0
    if query.surnames and candidate.surnames:
        possible += 35.0
        score += 35.0 * record_surname_similarity(query, candidate)
    if query.given and candidate.given:
        possible += 30.0
        use_middle = tier is None or need_middle
        score += 30.0 * record_given_similarity(query, candidate, use_middle)
    compared_years = False
    if use_birth and query.birth_year and candidate.birth_years:
        compared_years = True
        possible += 25.0
        diff = years_apart(query.birth_year, candidate.birth_years)
        if diff <= 5:
            score += 25.0 * (1.0 - diff * 0.18)
    if use_death and query.death_year and candidate.death_years:
        compared_years = True
        possible += 10.0
        diff = years_apart(query.death_year, candidate.death_years)
        if diff <= 3:
            score += 10.0 * (1.0 - diff * 0.25)
    if not possible:
        return RecordScore(0.0, False)
    result = score / possible * 100.0
    wanted = query.gender.casefold()
    found = candidate.gender.casefold()
    if wanted in ("male", "female") and found in ("male", "female"):
        if wanted != found:
            result /= 2
    return RecordScore(round(result, 1), compared_years)


def record_match_text(result: RecordScore) -> str:
    """Return Match column text, such as "92%" or "92% (name only)"."""
    text = f"{result.score:.0f}%"
    return text if result.compared_years else f"{text} (name only)"
