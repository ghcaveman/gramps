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


def vital_event_ref(db: Any, person: Person | None, kind: str) -> Any | None:
    if person is None or db is None:
        return None
    try:
        ref = person.get_birth_ref() if kind == "birth" else person.get_death_ref()
    except Exception:
        ref = None
    if ref is not None:
        return ref
    try:
        refs = person.get_event_ref_list() or []
    except Exception:
        return None
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
        if is_match:
            return cand
    return None


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
