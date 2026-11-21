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

The score follows a weighted scheme: surname 35, given and middle names 30,
birth year 25 (fading to nothing at 5 years apart) and death year 10
(fading at 3 years), counting only the parts both sides have. Names are
compared with Jaro-Winkler similarity plus a sound-alike bonus from Gramps'
Soundex, all in plain Python so the addon needs no extra packages.
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
class MatchQuery:
    """The target person's details used for matching."""

    given: str = ""
    middle: str = ""
    surnames: list[str] = field(default_factory=list)
    birth_year: int | None = None
    death_year: int | None = None


@dataclass
class MatchResult:
    """How well the best-matching person in a record fits the target."""

    score: float
    candidate: Candidate | None
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
    """
    Best similarity of any of the target's surnames (birth or married) to the
    candidate's surname, or to the last of the candidate's middle names,
    where a married woman's maiden name usually sits ("Mary Kreizer Smith").
    """
    best = 0.0
    maiden = candidate.middle.split()[-1] if candidate.middle else ""
    for surname in query.surnames:
        best = max(best, name_similarity(surname, candidate.surname))
        if maiden and len(maiden) > 1:
            best = max(best, name_similarity(surname, maiden) * 0.95)
    return best


def score_candidate(query: MatchQuery, candidate: Candidate) -> tuple[float, bool]:
    """
    Return (score from 0 to 100, whether any year was compared) for one
    candidate. Only the parts both sides have count towards the score.
    """
    score = 0.0
    possible = 0.0
    if query.surnames and candidate.surname:
        possible += 35.0
        score += 35.0 * _surname_similarity(query, candidate)
    if query.given and candidate.given:
        possible += 30.0
        score += 30.0 * _given_similarity(query, candidate)
    compared_years = False
    if query.birth_year and candidate.birth_year:
        compared_years = True
        possible += 25.0
        diff = abs(query.birth_year - candidate.birth_year)
        if diff <= 5:
            score += 25.0 * (1.0 - diff * 0.18)
    if query.death_year and candidate.death_year:
        compared_years = True
        possible += 10.0
        diff = abs(query.death_year - candidate.death_year)
        if diff <= 3:
            score += 10.0 * (1.0 - diff * 0.25)
    if not possible:
        return 0.0, False
    return round(score / possible * 100.0, 1), compared_years


def best_match(query: MatchQuery, parsed: dict[str, Any]) -> MatchResult:
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
    text = f"{result.score:.0f}%"
    return text if result.compared_years else f"{text} (name only)"
