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
Score how closely a FamilySearch profile matches the target person, for the
Match column of the FamilySearch search window and the GWizard Record Scan.

The scoring itself (weights, name similarity, year fading) is shared with
the other GWizard record sources and lives in gwizard_base.py; this module
turns a FamilySearch search result into a RecordCandidate. The profile you
looked up by FamilySearch ID is a 100% match whatever its details say.
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
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizard_base import (
    RecordCandidate,
    RecordQuery,
    RecordScore,
    record_match_text,
    score_record,
    year_range,
)

_ = glocale.translation.sgettext

__all__ = [
    "ID_MATCH_SORT_SCORE",
    "candidate_from_result",
    "id_match_text",
    "match_text",
    "score_result",
]

# The sort value of the profile looked up by its FamilySearch ID: above any
# scored result (at most 100), so it stays first when sorted by Match.
ID_MATCH_SORT_SCORE = 101.0

_YEAR = re.compile(r"\b(\d{4})\b")


# ------------------------------------------------------------
#
# Results
#
# ------------------------------------------------------------
def _year(text: str) -> int | None:
    """Return the first four-digit year in a date or lifespan, else None."""
    match = _YEAR.search(text or "")
    return int(match.group(1)) if match else None


def _life_years(life: str) -> tuple[int | None, int | None]:
    """
    Return the (birth, death) years of a lifespan such as "1809-1865",
    "1809-" or "1900".
    """
    if not life:
        return None, None
    parts = life.split("-", 1)
    birth = _year(parts[0])
    death = _year(parts[1]) if len(parts) > 1 else None
    return birth, death


def candidate_from_result(res: dict[str, Any]) -> RecordCandidate:
    """
    Return the matching parts of a FamilySearch search result: the name
    (last word as the surname, the next as the given name, the rest as
    middle names), birth and death years and gender. The years come from
    the birth and death dates, or else the lifespan.
    """
    words = str(res.get("name") or "").split()
    given = middle = ""
    surnames: list[str] = []
    if len(words) == 1:
        given = words[0]
    elif words:
        surnames.append(words[-1])
        given = words[0]
        middle = " ".join(words[1:-1])

    life_birth, life_death = _life_years(str(res.get("life") or ""))
    birth = _year(str(res.get("birth_date") or "")) or life_birth
    death = _year(str(res.get("death_date") or "")) or life_death

    return RecordCandidate(
        given=given,
        middle=middle,
        surnames=surnames,
        birth_years=year_range(birth),
        death_years=year_range(death),
        gender=str(res.get("gender") or "").strip().casefold(),
    )


# ------------------------------------------------------------
#
# Scoring
#
# ------------------------------------------------------------
def score_result(query: RecordQuery, res: dict[str, Any]) -> RecordScore:
    """
    Return how well a FamilySearch result matches the target, from 0 to
    100. Only the parts both sides have count towards the score.
    """
    return score_record(query, candidate_from_result(res))


def match_text(result: RecordScore) -> str:
    """Return the Match column text, such as "92%" or "92% (name only)"."""
    return record_match_text(result)


def id_match_text() -> str:
    """Return the Match column text for the profile looked up by its ID."""
    return _("100% (FamilySearch ID)")
