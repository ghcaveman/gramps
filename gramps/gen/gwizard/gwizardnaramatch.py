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
Find the people a NARA record names, and score how closely each matches the
target person.

NARA rarely lists a person as a record's creator; the person a record is
about is usually in its title ("Approved Pension Application File for Mary
Kreizer Smith, Widow of John A Smith, ...", "MacDonald, Lyman Angus - 1942")
or its description ("Birth Year: 1915", "Full Name: MacDonald, Angus").

The scoring itself (weights, name similarity, year fading) is shared with
the other GWizard record sources and lives in gwizard_base.py; this module
finds the people a record names and turns each into a RecordCandidate.
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
from gramps.gen.gwizard.gwizard_base import (
    RecordCandidate,
    RecordQuery,
    RecordScore,
    jaro_winkler,
    name_similarity,
    record_match_text,
    score_record,
    sounds_alike,
    year_range,
)

# The query type this module has always offered, now shared in gwizard_base.
MatchQuery = RecordQuery

__all__ = [
    "Candidate",
    "MatchQuery",
    "MatchResult",
    "best_match",
    "candidates_from_record",
    "jaro_winkler",
    "match_text",
    "name_similarity",
    "record_candidate",
    "score_candidate",
    "sounds_alike",
]


# ------------------------------------------------------------
#
# People named by a record
#
# ------------------------------------------------------------
@dataclass
class Candidate:
    """A person a NARA record names."""

    given: str = ""
    middle: str = ""
    surname: str = ""
    birth_year: int | None = None
    death_year: int | None = None
    role: str = ""
    source: str = ""

    def display(self) -> str:
        """Return the name as "Surname, Given Middle"."""
        given = " ".join(part for part in (self.given, self.middle) if part)
        if self.surname and given:
            return f"{self.surname}, {given}"
        return self.surname or given


# Words that end a name inside a title.
_NAME_STOP = re.compile(
    r",|;|\(| - | – |\bcompany\b|\bregiment\b|\bco\.|\bstate:|\byear:",
    re.IGNORECASE,
)
_YEARS = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# Surname prefixes written as a separate word ("Mac donald", "van Buren").
_PARTICLES = {"mac", "mc", "van", "von", "de", "del", "della", "di", "la", "le", "o"}
# Words that show a title part is not a person's given name, as in
# "Ohio, 8th Congressional District, Class No. 1" (a draft register).
_NOT_GIVEN_WORDS = {
    "class",
    "congressional",
    "county",
    "department",
    "district",
    "division",
    "no",
    "regiment",
    "vol",
    "volume",
}


def _clean_words(text: str) -> list[str]:
    """Split a name into words, dropping suffixes and stray punctuation."""
    words = [w.strip(".,'\"") for w in text.split()]
    return [
        w
        for w in words
        if any(c.isalpha() for c in w) and w.casefold().strip(".") not in _SUFFIXES
    ]


def _natural_name(text: str, role: str, source: str) -> Candidate | None:
    """Parse "Given [Middle...] Surname" (as in "Mary Kreizer Smith")."""
    words = _clean_words(text)
    words = [w for w in words if not w.startswith("[")]
    if not words:
        return None
    if len(words) > 2 and words[-2].casefold() in _PARTICLES:
        words[-2:] = [f"{words[-2]} {words[-1]}"]
    if len(words) == 1:
        return Candidate(surname=words[0], role=role, source=source)
    return Candidate(
        given=words[0],
        middle=" ".join(words[1:-1]),
        surname=words[-1],
        role=role,
        source=source,
    )


def _inverted_name(text: str, role: str, source: str) -> Candidate | None:
    """Parse "Surname, Given [Middle...]" (as in "MacDonald, Lyman Angus")."""
    if "," not in text:
        return None
    surname, rest = text.split(",", 1)
    surname = surname.strip()
    # Only the part before the next comma can be the given names.
    given_part = rest.split(",", 1)[0]
    if any(c.isdigit() for c in _YEARS.sub(" ", given_part)) or any(
        w.casefold() in _NOT_GIVEN_WORDS for w in _clean_words(given_part)
    ):
        return None
    rest = _YEARS.sub(" ", rest)
    given_words = [w for w in _clean_words(rest) if not w.startswith("[")]
    if not surname or not re.match(r"^[A-Za-z][A-Za-z'\- ]*$", surname):
        return None
    if len(surname.split()) > 3:
        return None
    return Candidate(
        given=given_words[0] if given_words else "",
        middle=" ".join(given_words[1:3]),
        surname=surname,
        role=role,
        source=source,
    )


def _upper_index_name(text: str, source: str) -> Candidate | None:
    """
    Parse index-card titles that start with the surname in capitals and no
    comma, such as "MacDONALD Angus Daniel".
    """
    words = text.split()
    if len(words) < 2 or "," in words[0]:
        return None
    capitals = sum(1 for c in words[0] if c.isupper())
    if capitals < 3 or not words[0].isalpha():
        return None
    rest = [w for w in words[1:] if w[:1].isupper() and w.strip(".").isalpha()]
    if not rest:
        return None
    return Candidate(
        given=rest[0], middle=" ".join(rest[1:3]), surname=words[0], source=source
    )


def _service_file_name(text: str, source: str) -> Candidate | None:
    """
    Parse military service-file titles that give the name surname first,
    without a comma, before " -- " and a service number, such as "Smith
    John William -- [Service Number] 0011712".
    """
    if " -- " not in text:
        return None
    head, tail = text.split(" -- ", 1)
    # Only service files: other titles with " -- " ("Muster Rolls -- [Box
    # 12]") start with capitalised words that are not a name.
    if "service number" not in tail.casefold():
        return None
    words = head.split()
    if not 2 <= len(words) <= 4:
        return None
    if not all(w.strip(".").isalpha() and w[:1].isupper() for w in words):
        return None
    return Candidate(
        given=words[1].strip("."),
        middle=" ".join(w.strip(".") for w in words[2:]),
        surname=words[0],
        source=source,
    )


def candidates_from_record(parsed: dict[str, Any]) -> list[Candidate]:
    """
    Return the people a parsed NARA record names: its person creators, the
    names in its title, and names in its description.
    """
    found: list[Candidate] = []
    title = str(parsed.get("title") or "").strip()
    # Drop a leading bracketed note, as in "[Connecticut] Hine, Lewis - ...".
    title = re.sub(r"^\[[^\]]*\]\s*", "", title)
    note = str(parsed.get("scope_note") or "")

    for heading in parsed.get("person_creators") or []:
        candidate = _inverted_name(heading, "creator", "creator")
        if candidate:
            years = [int(y) for y in _YEARS.findall(heading)]
            if years:
                candidate.birth_year = years[0]
                candidate.death_year = years[1] if len(years) > 1 else None
            found.append(candidate)

    # "... File for Mary Kreizer Smith, Widow of John A Smith, ..."
    match = re.search(r"\b(?:file|application|record)s? for (.+)", title, re.I)
    if match:
        name = _NAME_STOP.split(match.group(1))[0]
        candidate = _natural_name(name, "subject", "title")
        if candidate:
            found.append(candidate)
    for match in re.finditer(
        r"\b(widow|son|daughter|mother|father|child|children|wife|husband) of " r"(.+)",
        title,
        re.I,
    ):
        name = _NAME_STOP.split(match.group(2))[0]
        candidate = _natural_name(name, match.group(1).lower(), "title")
        if candidate:
            found.append(candidate)

    # "Records related to Jacob Devault", "Photograph of Arthur E. Devault",
    # "Petition for Naturalization of Daniel John Mac donald"
    match = re.match(
        r"^(?:records related to|photograph of|petition for naturalization of"
        r"|declaration of intention of)\s+(.+)$",
        title,
        re.I,
    )
    if match:
        candidate = _natural_name(_NAME_STOP.split(match.group(1))[0], "", "title")
        if candidate:
            found.append(candidate)

    # "MacDonald, Lyman Angus - 1942", "Devault, John - State: Tennessee ..."
    if not found and "," in title:
        head = re.split(r" - | – ", title, maxsplit=1)[0]
        candidate = _inverted_name(head, "", "title")
        if candidate and candidate.given:
            found.append(candidate)

    # "Smith John William -- [Service Number] 0011712" (Navy service files)
    if not found:
        candidate = _service_file_name(title, "title")
        if candidate:
            found.append(candidate)

    # "MacDONALD Angus Daniel"
    if not found:
        candidate = _upper_index_name(title, "title")
        if candidate:
            found.append(candidate)

    # Descriptions: "Full Name: MacDonald, Angus; ...", "Birth Year: 1915"
    for match in re.finditer(r"full name:\s*([^;]+)", note, re.I):
        candidate = _inverted_name(match.group(1).strip(), "", "description")
        if candidate:
            found.append(candidate)
    birth = re.search(r"birth year:\s*(\d{4})", note, re.I)
    if birth and found:
        for candidate in found:
            if candidate.birth_year is None and candidate.source != "creator":
                candidate.birth_year = int(birth.group(1))
    return found


# ------------------------------------------------------------
#
# Scoring
#
# ------------------------------------------------------------
@dataclass
class MatchResult:
    """How well the best-matching person in a record fits the target."""

    score: float
    candidate: Candidate | None
    compared_years: bool


def record_candidate(candidate: Candidate) -> RecordCandidate:
    """
    Return a person a record names in the shared scoring form. The last
    middle name is also tried as a surname, where a married woman's maiden
    name usually sits ("Mary Kreizer Smith").
    """
    return RecordCandidate(
        given=candidate.given,
        middle=candidate.middle,
        surnames=[candidate.surname] if candidate.surname else [],
        birth_years=year_range(candidate.birth_year),
        death_years=year_range(candidate.death_year),
        maiden_from_middle=True,
    )


def score_candidate(query: RecordQuery, candidate: Candidate) -> tuple[float, bool]:
    """
    Return (score from 0 to 100, whether any year was compared) for one
    candidate. Only the parts both sides have count towards the score.
    """
    result = score_record(query, record_candidate(candidate))
    return result.score, result.compared_years


def best_match(query: RecordQuery, parsed: dict[str, Any]) -> MatchResult:
    """Return the best-matching person a record names, or no match."""
    best = MatchResult(0.0, None, False)
    for candidate in candidates_from_record(parsed):
        score, compared = score_candidate(query, candidate)
        if best.candidate is None or score > best.score:
            best = MatchResult(score, candidate, compared)
    return best


def match_text(result: MatchResult) -> str:
    """Return the Match column text, such as "92%" or "92% (name only)"."""
    if result.candidate is None:
        return "-"
    return record_match_text(RecordScore(result.score, result.compared_years))
