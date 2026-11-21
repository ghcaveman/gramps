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
    middle = str(profile.get("MiddleName") or "").strip()
    if not given:
        # Some results carry only RealName (the preferred first name).
        given = str(profile.get("RealName") or "").strip()
    if " " in given and not middle:
        given, middle = given.split(" ", 1)
    return RecordCandidate(
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
def score_profile(query: RecordQuery, profile: dict[str, Any]) -> RecordScore:
    """
    Return how well a WikiTree profile matches the target, from 0 to 100.
    Only the parts both sides have count towards the score.
    """
    return score_record(query, candidate_from_profile(profile))


def match_text(result: RecordScore) -> str:
    """Return the Match column text, such as "92%" or "92% (name only)"."""
    return record_match_text(result)
