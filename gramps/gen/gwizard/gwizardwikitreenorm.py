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
# with this program; if not, see <https://www.gnu.org/licenses/>.
#

"""Normalization helpers for WikiTree person searches."""

from __future__ import annotations

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from dataclasses import dataclass, field
import re

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.gwizard.gwizard_base import RecordQuery

_PLACEHOLDER_SURNAMES = {"unknown", "unk", "?", "none", "n/a", "nn"}
_PLACEHOLDER_GIVENS = (
    "unknown",
    "child",
    "baby",
    "infant",
    "son",
    "daughter",
    "boy",
    "girl",
    "stillborn",
)

_GIVEN_VARIANTS = {
    "nickolas": ["Nicholas"],
    "nicholas": ["Nickolas"],
    "emanuale": ["Emanuele"],
    "barbera": ["Barbara"],
    "giacento": ["Giacinto", "Jean"],
}

_US_STATES = {
    "al": "Alabama",
    "ak": "Alaska",
    "az": "Arizona",
    "ar": "Arkansas",
    "ca": "California",
    "co": "Colorado",
    "ct": "Connecticut",
    "de": "Delaware",
    "fl": "Florida",
    "ga": "Georgia",
    "hi": "Hawaii",
    "id": "Idaho",
    "il": "Illinois",
    "in": "Indiana",
    "ia": "Iowa",
    "ks": "Kansas",
    "ky": "Kentucky",
    "la": "Louisiana",
    "me": "Maine",
    "md": "Maryland",
    "ma": "Massachusetts",
    "mi": "Michigan",
    "mn": "Minnesota",
    "ms": "Mississippi",
    "mo": "Missouri",
    "mt": "Montana",
    "ne": "Nebraska",
    "nv": "Nevada",
    "nh": "New Hampshire",
    "nj": "New Jersey",
    "nm": "New Mexico",
    "ny": "New York",
    "nc": "North Carolina",
    "nd": "North Dakota",
    "oh": "Ohio",
    "ok": "Oklahoma",
    "or": "Oregon",
    "pa": "Pennsylvania",
    "ri": "Rhode Island",
    "sc": "South Carolina",
    "sd": "South Dakota",
    "tn": "Tennessee",
    "tx": "Texas",
    "ut": "Utah",
    "vt": "Vermont",
    "va": "Virginia",
    "wa": "Washington",
    "wv": "West Virginia",
    "wi": "Wisconsin",
    "wy": "Wyoming",
    "dc": "District of Columbia",
}

_CITY_ABBREVS = {
    "phila": "Philadelphia",
    "phila.": "Philadelphia",
    "st.": "Saint",
    "ft": "Fort",
    "ft.": "Fort",
    "mt": "Mount",
    "mt.": "Mount",
}

_PARTICLE_RE = re.compile(
    r"^(Mc|Mac|O|Di|De|Da|Del|Della|Van|Von|Le|La)\s+([A-Za-z])", re.I
)


# ------------------------------------------------------------
#
# WikiTreeSearchPlan
#
# ------------------------------------------------------------
@dataclass
class WikiTreeSearchPlan:
    """Thread-safe normalized search plan built from a RecordQuery."""

    given: str = ""
    middle: str = ""
    nicknames: list[str] = field(default_factory=list)
    surnames: list[str] = field(default_factory=list)
    birth_year: int | None = None
    death_year: int | None = None
    date_spread: int = 2
    gender: str = ""
    skip: bool = False


def clean_given_and_nicknames(
    raw_given: str, raw_nick: str = ""
) -> tuple[str, str, list[str]]:
    """Split given names and extract nicknames written in quotes or parentheses."""
    text = (raw_given or "").strip()
    nicknames: list[str] = []

    if raw_nick and raw_nick.strip():
        nicknames.append(raw_nick.strip().strip('"'))

    for match in re.finditer(r'"([^"]+)"', text):
        nickname = match.group(1).strip()
        if nickname and nickname not in nicknames:
            nicknames.append(nickname)
    text = re.sub(r'"[^"]*"', " ", text)

    for match in re.finditer(r"\(([^)]+)\)", text):
        nickname = match.group(1).strip()
        if nickname and nickname not in nicknames:
            nicknames.append(nickname)
    text = re.sub(r"\([^)]*\)", " ", text)

    tokens = [token.rstrip(".,?") for token in text.split() if token.rstrip(".,?")]
    if not tokens:
        return "", "", nicknames

    return tokens[0], " ".join(tokens[1:]), nicknames


def expand_given_variants(first_name: str) -> list[str]:
    """Return a given name followed by its known spelling variants."""
    clean = (first_name or "").strip()
    if not clean:
        return []

    variants = [clean]
    for alternate in _GIVEN_VARIANTS.get(clean.casefold(), []):
        if alternate not in variants:
            variants.append(alternate)
    return variants


def expand_surname_variants(raw_surnames: list[str]) -> list[str]:
    """Remove placeholder markers and add common surname particle variants."""
    variants: list[str] = []

    def add_variant(value: str) -> None:
        variant = value.strip()
        if (
            variant
            and variant.lower() not in _PLACEHOLDER_SURNAMES
            and variant not in variants
        ):
            variants.append(variant)

    for raw_surname in raw_surnames:
        clean = re.sub(r"[?()\"]", "", raw_surname or "").strip()
        if not clean or clean.lower() in _PLACEHOLDER_SURNAMES:
            continue
        add_variant(clean)

        match = _PARTICLE_RE.match(clean)
        if match:
            prefix, rest_first = match.group(1), match.group(2)
            tail = clean[match.end() :]
            add_variant(f"{prefix}{rest_first}{tail}")
            if prefix.lower() == "o":
                add_variant(f"O'{rest_first}{tail}")

        # Split unspaced Italian/French particles: "Decristoforo" -> "De Cristoforo"
        m_split = re.match(r"^(De|Di|Da|Del|Della|La|Le)([a-z]{3,})$", clean, re.I)
        if m_split:
            add_variant(f"{m_split.group(1)} {m_split.group(2).capitalize()}")

        # German -dt / -d surname variants: "Schmidt" <-> "Schmid"
        if clean.lower().endswith("dt"):
            add_variant(clean[:-1])
        elif clean.lower().endswith("d"):
            add_variant(f"{clean}t")

    return variants


def normalize_wikitree_location(raw_place: str) -> str:
    """Normalize a place string for WikiTree's literal substring filter."""
    text = (raw_place or "").strip().lstrip(",").strip()
    if not text or text.lower() in (
        "<unknown>",
        "unknown",
        "same place",
        "same house",
    ):
        return ""

    text = re.sub(r"\([A-Z]{2,3}\)", "", text).strip()
    if any(
        keyword in text.lower()
        for keyword in ("cemetery", "memorial", "mausoleum", "hospital")
    ):
        parts = [part.strip() for part in text.split(",") if part.strip()]
        if len(parts) > 1:
            text = ", ".join(parts[1:])

    text = re.sub(r"\bCO\.?\b", "", text, flags=re.I)
    raw_parts = [part.strip() for part in text.split(",") if part.strip()]

    cleaned_parts: list[str] = []
    for part in raw_parts:
        low = part.lower().rstrip(".")
        if low in (
            "usa",
            "u.s.a",
            "us",
            "united states",
            "united states of america",
            "italia",
        ):
            if low == "italia":
                cleaned_parts.append("Italy")
            continue
        if low in _US_STATES:
            cleaned_parts.append(_US_STATES[low])
            continue
        tokens = part.split()
        state_abbreviation = tokens[-1].lower().rstrip(".") if tokens else ""
        if len(tokens) >= 2 and state_abbreviation in _US_STATES:
            state = _US_STATES[state_abbreviation]
            city = " ".join(
                _CITY_ABBREVS.get(token.lower(), token) for token in tokens[:-1]
            )
            cleaned_parts.extend([city, state])
            continue
        expanded = " ".join(_CITY_ABBREVS.get(token.lower(), token) for token in tokens)
        if expanded and (
            not cleaned_parts or cleaned_parts[-1].lower() != expanded.lower()
        ):
            cleaned_parts.append(expanded)

    return ", ".join(cleaned_parts[-2:]) if cleaned_parts else ""


def build_search_plan(query: RecordQuery) -> WikiTreeSearchPlan:
    """Build a thread-safe WikiTreeSearchPlan strictly from a RecordQuery."""
    raw_given = f"{query.given} {query.middle}".strip()
    given, middle, nicknames = clean_given_and_nicknames(raw_given)
    surnames = expand_surname_variants(list(query.surnames))

    if not surnames or given.lower().startswith(_PLACEHOLDER_GIVENS):
        return WikiTreeSearchPlan(skip=True)

    gender_low = (query.gender or "").strip().casefold()
    wikitree_gender = (
        "Male" if gender_low == "male" else ("Female" if gender_low == "female" else "")
    )

    return WikiTreeSearchPlan(
        given=given,
        middle=middle,
        nicknames=nicknames,
        surnames=surnames,
        birth_year=query.birth_year,
        death_year=query.death_year,
        date_spread=2,
        gender=wikitree_gender,
    )
