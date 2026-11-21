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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Score how closely a WikiTree profile matches the target person, for the
Match column of the WikiTree search window.

The score follows a weighted scheme: surname 35, given and middle names 30,
birth year 25 (fading to nothing at 5 years apart) and death year 10
(fading at 3 years), counting only the parts both sides have. Names are
compared with Jaro-Winkler similarity plus a sound-alike bonus from Gramps'
Soundex, all in plain Python so the addon needs no extra packages. Any of
the profile's surnames (at birth, current or other) may match any of the
target's (birth or married). A profile whose dates are private shows only
a decade ("1840s"); a year inside that decade counts as a full match. A
known gender that differs halves the score.

This is a copy of the NARA addon's scoring, kept separate so the two
addons do not share code.
"""

# ------------------------------------------------------------
#
# Python modules
#
# ------------------------------------------------------------
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------
#
# Gramps modules
#
# ------------------------------------------------------------
from gramps.gen.soundex import soundex


# ------------------------------------------------------------
#
# Name similarity
#
# ------------------------------------------------------------
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
# Profiles
#
# ------------------------------------------------------------
@dataclass
class Candidate:
    """The parts of a WikiTree profile used for matching."""

    given: str = ""
    middle: str = ""
    surnames: list[str] = field(default_factory=list)
    birth_years: tuple[int, int] | None = None
    death_years: tuple[int, int] | None = None
    gender: str = ""


_YEAR = re.compile(r"^(\d{4})")
_DECADE = re.compile(r"^(\d{3})0s$")


def _years(date: Any, decade: Any) -> tuple[int, int] | None:
    """
    Return the (first, last) years a WikiTree date allows: one year for a
    date such as "1706-01-17", ten for a decade such as "1700s", None when
    unknown ("0000-00-00" or blank).
    """
    match = _YEAR.match(str(date or "").strip())
    if match and int(match.group(1)) > 0:
        year = int(match.group(1))
        return year, year
    match = _DECADE.match(str(decade or "").strip())
    if match and int(match.group(1)) > 0:
        start = int(match.group(1)) * 10
        return start, start + 9
    return None


def candidate_from_profile(profile: dict[str, Any]) -> Candidate:
    """Return the matching parts of a WikiTree profile (search result)."""
    surnames: list[str] = []
    for key in ("LastNameAtBirth", "LastNameBirth", "LastNameCurrent"):
        value = str(profile.get(key) or "").strip()
        if value and value not in surnames:
            surnames.append(value)
    for value in str(profile.get("LastNameOther") or "").split(","):
        value = value.strip()
        if value and value not in surnames:
            surnames.append(value)
    given = str(profile.get("FirstName") or "").strip()
    middle = str(profile.get("MiddleName") or "").strip()
    if not given:
        # Some results carry only RealName (the preferred first name).
        given = str(profile.get("RealName") or "").strip()
    if " " in given and not middle:
        given, middle = given.split(" ", 1)
    return Candidate(
        given=given,
        middle=middle,
        surnames=surnames,
        birth_years=_years(profile.get("BirthDate"), profile.get("BirthDateDecade")),
        death_years=_years(profile.get("DeathDate"), profile.get("DeathDateDecade")),
        gender=str(profile.get("Gender") or "").strip().casefold(),
    )


# ------------------------------------------------------------
#
# Scoring
#
# ------------------------------------------------------------
@dataclass
class MatchQuery:
    """The target person's details used for matching."""

    given: str = ""
    middle: str = ""
    surnames: list[str] = field(default_factory=list)
    birth_year: int | None = None
    death_year: int | None = None
    gender: str = ""

    def has_name(self) -> bool:
        """Return True when there is a name to match against."""
        return bool(self.given or self.surnames)


@dataclass
class MatchResult:
    """How well a profile fits the target person."""

    score: float
    compared_years: bool


def _given_similarity(query: MatchQuery, candidate: Candidate) -> float:
    """Given/middle name similarity, allowing initials and swapped names."""
    q_given, c_given = query.given.casefold(), candidate.given.casefold()
    if len(q_given) == 1 or len(c_given) == 1:
        direct = 0.85 if q_given[:1] == c_given[:1] else 0.0
    else:
        direct = name_similarity(q_given, c_given)
    c_mid = candidate.middle.split()[0].casefold() if candidate.middle else ""
    swapped = name_similarity(q_given, c_mid) * 0.85 if c_mid else 0.0
    best = max(direct, swapped)
    q_mid = query.middle.split()[0].casefold() if query.middle else ""
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


def _surname_similarity(query: MatchQuery, candidate: Candidate) -> float:
    """Best similarity of any target surname to any profile surname."""
    return max(
        (
            name_similarity(wanted, surname)
            for wanted in query.surnames
            for surname in candidate.surnames
        ),
        default=0.0,
    )


def _years_apart(year: int, years: tuple[int, int]) -> int:
    """Return how far a year is outside a (first, last) range; 0 inside it."""
    first, last = years
    if year < first:
        return first - year
    if year > last:
        return year - last
    return 0


def score_profile(query: MatchQuery, profile: dict[str, Any]) -> MatchResult:
    """
    Return how well a WikiTree profile matches the target, from 0 to 100.
    Only the parts both sides have count towards the score.
    """
    candidate = candidate_from_profile(profile)
    score = 0.0
    possible = 0.0
    if query.surnames and candidate.surnames:
        possible += 35.0
        score += 35.0 * _surname_similarity(query, candidate)
    if query.given and candidate.given:
        possible += 30.0
        score += 30.0 * _given_similarity(query, candidate)
    compared_years = False
    if query.birth_year and candidate.birth_years:
        compared_years = True
        possible += 25.0
        diff = _years_apart(query.birth_year, candidate.birth_years)
        if diff <= 5:
            score += 25.0 * (1.0 - diff * 0.18)
    if query.death_year and candidate.death_years:
        compared_years = True
        possible += 10.0
        diff = _years_apart(query.death_year, candidate.death_years)
        if diff <= 3:
            score += 10.0 * (1.0 - diff * 0.25)
    if not possible:
        return MatchResult(0.0, False)
    result = score / possible * 100.0
    wanted = query.gender.casefold()
    if wanted in ("male", "female") and candidate.gender in ("male", "female"):
        if wanted != candidate.gender:
            result /= 2
    return MatchResult(round(result, 1), compared_years)


def match_text(result: MatchResult) -> str:
    """Return the Match column text, such as "92%" or "92% (name only)"."""
    text = f"{result.score:.0f}%"
    return text if result.compared_years else f"{text} (name only)"
