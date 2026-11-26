from __future__ import annotations
import re
from dataclasses import dataclass, field

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
    gender: str = ""  # "Male", "Female", or ""
    skip: bool = False


def clean_given_and_nicknames(
    raw_given: str, raw_nick: str = ""
) -> tuple[str, str, list[str]]:
    """
    Strip inline quotes/parentheticals from given names (e.g. 'Mary L. "Mamie"',
    'Harry Jay (Buzz)') and return (first_name, middle_name, nicknames).
    """
    text = (raw_given or "").strip()
    nicks: list[str] = []

    if raw_nick and raw_nick.strip():
        nicks.append(raw_nick.strip().strip('"'))

    for m in re.finditer(r'"([^"]+)"', text):
        val = m.group(1).strip()
        if val and val not in nicks:
            nicks.append(val)
    text = re.sub(r'"[^"]*"', " ", text)

    for m in re.finditer(r"\(([^)]+)\)", text):
        val = m.group(1).strip()
        if val and val not in nicks:
            nicks.append(val)
    text = re.sub(r"\([^)]*\)", " ", text)

    tokens = [t.rstrip(".,?") for t in text.split() if t.rstrip(".,?")]
    if not tokens:
        return "", "", nicks

    return tokens[0], " ".join(tokens[1:]), nicks


def expand_surname_variants(raw_surnames: list[str]) -> list[str]:
    """
    Remove '?' markers ('Macellari ?') and add collapsed/apostrophe particle
    forms ('Di Lauro' -> 'Dilauro', 'O Neill' -> \"O'Neill\").
    """
    variants: list[str] = []

    def _add(val: str) -> None:
        v = val.strip()
        if v and v.lower() not in _PLACEHOLDER_SURNAMES and v not in variants:
            variants.append(v)

    for raw in raw_surnames:
        clean = re.sub(r"[?()\"]", "", raw or "").strip()
        if not clean or clean.lower() in _PLACEHOLDER_SURNAMES:
            continue
        _add(clean)

        m = _PARTICLE_RE.match(clean)
        if m:
            prefix, rest_first = m.group(1), m.group(2)
            tail = clean[m.end() :]
            _add(f"{prefix}{rest_first}{tail}")
            if prefix.lower() == "o":
                _add(f"O'{rest_first}{tail}")

    return variants


def normalize_wikitree_location(raw_place: str) -> str:
    """
    Normalize GEDCOM PLAC strings for WikiTree's literal substring filter:
      ', Philadelphia, Philadelphia, Pennsylvania, USA' -> 'Philadelphia, Pennsylvania'
      'Racine. WV' -> 'West Virginia'
      'Voltaggio (AL)' -> 'Voltaggio'
    """
    text = (raw_place or "").strip().lstrip(",").strip()
    if not text or text.lower() in ("<unknown>", "unknown", "same place", "same house"):
        return ""

    text = re.sub(r"\([A-Z]{2,3}\)", "", text).strip()
    if any(
        k in text.lower() for k in ("cemetery", "memorial", "mausoleum", "hospital")
    ):
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) > 1:
            text = ", ".join(parts[1:])

    text = re.sub(r"\bCO\.?\b", "", text, flags=re.I)
    raw_parts = [p.strip() for p in text.split(",") if p.strip()]

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
        if len(tokens) >= 2 and tokens[-1].lower().rstrip(".") in _US_STATES:
            state = _US_STATES[tokens[-1].lower().rstrip(".")]
            city = " ".join(_CITY_ABBREVS.get(t.lower(), t) for t in tokens[:-1])
            cleaned_parts.extend([city, state])
            continue
        expanded = " ".join(_CITY_ABBREVS.get(t.lower(), t) for t in tokens)
        if expanded and (
            not cleaned_parts or cleaned_parts[-1].lower() != expanded.lower()
        ):
            cleaned_parts.append(expanded)

    return ", ".join(cleaned_parts[-2:]) if cleaned_parts else ""


def build_search_plan(query: RecordQuery) -> WikiTreeSearchPlan:
    """Build a thread-safe WikiTreeSearchPlan strictly from a RecordQuery."""
    raw_given = f"{query.given} {query.middle}".strip()
    given, middle, nicks = clean_given_and_nicknames(raw_given)
    surnames = expand_surname_variants(list(query.surnames))

    if not surnames or given.lower().startswith(_PLACEHOLDER_GIVENS):
        return WikiTreeSearchPlan(skip=True)

    gender_low = (query.gender or "").strip().casefold()
    wt_gender = (
        "Male" if gender_low == "male" else ("Female" if gender_low == "female" else "")
    )

    return WikiTreeSearchPlan(
        given=given,
        middle=middle,
        nicknames=nicks,
        surnames=surnames,
        birth_year=query.birth_year,
        death_year=query.death_year,
        date_spread=2,
        gender=wt_gender,
    )
