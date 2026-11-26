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
Match column of the WikiTree search window and the GWizard Record Scan.

The scoring itself (weights, name similarity, year fading) is shared with
the other GWizard record sources and lives in gwizard_base.py; this module
turns a WikiTree profile into a RecordCandidate. Any of the profile's
surnames (at birth, current or other) may match any of the target's (birth
or married). A profile whose dates are private shows only a decade
("1840s"); a year inside that decade counts as a full match.
"""

# ------------------------------------------------------------
#
# Python modules
#
# ------------------------------------------------------------
from __future__ import annotations
import re
from typing import Any

# ------------------------------------------------------------
#
# Gramps modules
#
# ------------------------------------------------------------
from gramps.gen.gwizard.gwizard_base import (
    RecordCandidate,
    RecordQuery,
    RecordScore,
    jaro_winkler,
    name_similarity,
    record_match_text,
    score_record,
    sounds_alike,
)

# The names this module has always offered, now shared in gwizard_base.
Candidate = RecordCandidate
MatchQuery = RecordQuery
MatchResult = RecordScore

__all__ = [
    "Candidate",
    "MatchQuery",
    "MatchResult",
    "candidate_from_profile",
    "parent_names",
    "jaro_winkler",
    "match_text",
    "name_similarity",
    "score_profile",
    "sounds_alike",
]


# ------------------------------------------------------------
#
# Profiles
#
# ------------------------------------------------------------
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


def _parent_id(value: Any) -> str:
    """Return a parent Id as text, or '' when unknown, private or none."""
    text = str(value or "").strip()
    return text if text.lstrip("-").isdigit() and int(text) > 0 else ""


def parent_profiles(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the parent profiles in a profile's "Parents" field."""
    parents = profile.get("Parents")
    if isinstance(parents, dict):
        parents = list(parents.values())
    if not isinstance(parents, list):
        return []
    return [parent for parent in parents if isinstance(parent, dict)]


def parent_names(profile: dict[str, Any]) -> tuple[str, str]:
    """
    Return the (father, mother) given names of a profile, from its
    "Parents" field (profiles keyed by Id). A parent is told apart by the
    profile's Father and Mother Ids, or else by the parent's gender.
    """
    father_id = _parent_id(profile.get("Father"))
    mother_id = _parent_id(profile.get("Mother"))
    father = mother = ""
    for parent in parent_profiles(profile):
        given = str(
            parent.get("FirstName")
            or parent.get("RealName")
            or parent.get("ColloquialName")
            or ""
        ).strip()
        if not given:
            continue
        pid = _parent_id(parent.get("Id"))
        gender = str(parent.get("Gender") or "").casefold()
        if (pid and pid == father_id) or (not pid and gender == "male"):
            father = father or given
        elif (pid and pid == mother_id) or (not pid and gender == "female"):
            mother = mother or given
        elif gender == "male":
            father = father or given
        elif gender == "female":
            mother = mother or given
    return father, mother


def missing_parent_ids(profile: dict[str, Any]) -> list[str]:
    """Return the Father/Mother Ids whose names the profile does not include."""
    have = {_parent_id(parent.get("Id")) for parent in parent_profiles(profile)}
    wanted = [_parent_id(profile.get(key)) for key in ("Father", "Mother")]
    return [pid for pid in wanted if pid and pid not in have]


def candidate_from_profile(profile: dict[str, Any]) -> RecordCandidate:
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
    middle = str(
        profile.get("MiddleName") or profile.get("MiddleInitial") or ""
    ).strip()
    real_or_colloquial = str(
        profile.get("ColloquialName") or profile.get("RealName") or ""
    ).strip()

    if not given:
        given = real_or_colloquial
    elif (
        real_or_colloquial
        and real_or_colloquial.casefold() != given.casefold()
        and not middle
    ):
        # Lets record_given_similarity's swapped-name check match preferred names
        # (e.g., FirstName="Giacento", ColloquialName="Jean" or FirstName="Mary", ColloquialName="Mamie")
        middle = real_or_colloquial

    if " " in given and not middle:
        given, middle = given.split(" ", 1)

    gender = str(profile.get("Gender") or "").strip().casefold()
    lnab = str(
        profile.get("LastNameAtBirth") or profile.get("LastNameBirth") or ""
    ).strip()
    lnc = str(profile.get("LastNameCurrent") or "").strip()

    candidate = RecordCandidate(
        given=given,
        middle=middle,
        surnames=surnames,
        birth_years=_years(profile.get("BirthDate"), profile.get("BirthDateDecade")),
        death_years=_years(profile.get("DeathDate"), profile.get("DeathDateDecade")),
        gender=gender,
        # Enable maiden-in-middle fallback when a female profile lacks a distinct LNAB
        maiden_from_middle=(gender == "female" and bool(middle) and lnab == lnc),
    )
    # Parents' names for the g/m/s/b+f+m and +f|m levels (GWizard File Merge
    # versions without them have no father_given / mother_given).
    if hasattr(candidate, "father_given"):
        candidate.father_given, candidate.mother_given = parent_names(profile)
    return candidate


# ------------------------------------------------------------
#
# Scoring
#
# ------------------------------------------------------------
def score_profile(query: RecordQuery, profile: dict[str, Any]) -> RecordScore:
    """
    Return how well a WikiTree profile matches the target, from 0 to 100.
    Only the parts both sides have count towards the score.
    """
    return score_record(query, candidate_from_profile(profile))


def match_text(result: RecordScore) -> str:
    """Return the Match column text, such as "92%" or "92% (name only)"."""
    return record_match_text(result)
