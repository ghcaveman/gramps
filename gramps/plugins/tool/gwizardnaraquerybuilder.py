import re
from typing import Dict, List, Optional, Any

# Standard U.S. State names and abbreviations for location extraction
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"
}
STATE_LOOKUP = {k.lower(): v for k, v in US_STATES.items()}
STATE_LOOKUP.update({v.lower(): v for v in US_STATES.values()})

# Title patterns that indicate bulk microfilm rolls, census EDs, or box containers
# rather than an individual's record—unless the person's full name appears verbatim.
_BULK_ROLL_PREFIXES = (
    "morning reports",
    "fiche_",
    "roll ",
    "number ",
    "1950 census",
    "1940 census",
    "1930 census",
    "1920 census",
    "1910 census",
    "1900 census",
    "naturalization index",
    "[last names:",
    "muster rolls",
    "alphabetical listing",
)


def parse_gedcom_individuals(ged_path: str) -> Dict[str, Dict[str, Any]]:
    """Lightweight GEDCOM parser extracting names, events, places, and family links."""
    individuals: Dict[str, Dict[str, Any]] = {}
    families: Dict[str, Dict[str, Any]] = {}

    curr_id: Optional[str] = None
    curr_type: Optional[str] = None
    curr_tag: Optional[str] = None

    with open(ged_path, "r", encoding="utf-8-sig", errors="replace") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split(" ", 2)
            level = int(parts[0])
            tag = parts[1]
            val = parts[2] if len(parts) > 2 else ""

            if level == 0:
                curr_tag = None
                if val == "INDI":
                    curr_id = tag.strip("@")
                    curr_type = "INDI"
                    individuals[curr_id] = {
                        "id": curr_id, "names": [], "sex": None,
                        "birth_year": None, "death_year": None,
                        "places": [], "tags": set(), "fams": []
                    }
                elif val == "FAM":
                    curr_id = tag.strip("@")
                    curr_type = "FAM"
                    families[curr_id] = {"husb": None, "wife": None}
                else:
                    curr_id = None
                    curr_type = None

            elif level == 1 and curr_id:
                curr_tag = tag
                if curr_type == "INDI":
                    ind = individuals[curr_id]
                    ind["tags"].add(tag)
                    if tag == "NAME":
                        ind["names"].append(val)
                    elif tag == "SEX":
                        ind["sex"] = val.strip()
                    elif tag == "FAMS":
                        ind["fams"].append(val.strip("@"))
                elif curr_type == "FAM":
                    if tag == "HUSB":
                        families[curr_id]["husb"] = val.strip("@")
                    elif tag == "WIFE":
                        families[curr_id]["wife"] = val.strip("@")

            elif level == 2 and curr_id and curr_type == "INDI":
                ind = individuals[curr_id]
                if tag == "DATE" and curr_tag in ("BIRT", "DEAT"):
                    m = re.search(r"\b(1[6-9]\d{2}|20[0-2]\d)\b", val)
                    if m:
                        yr = int(m.group(1))
                        if curr_tag == "BIRT" and not ind["birth_year"]:
                            ind["birth_year"] = yr
                        elif curr_tag == "DEAT" and not ind["death_year"]:
                            ind["death_year"] = yr
                elif tag == "PLAC":
                    ind["places"].append(val)
                elif tag == "TYPE" and curr_tag == "EVEN":
                    ind["tags"].add(val.strip().upper())

    # Attach spouse surnames for married women
    for ind_id, ind in individuals.items():
        ind["married_surnames"] = set()
        if ind["sex"] == "F":
            for fam_id in ind["fams"]:
                husb_id = families.get(fam_id, {}).get("husb")
                if husb_id and husb_id in individuals:
                    for h_name in individuals[husb_id]["names"]:
                        m = re.search(r"/([^/]+)/", h_name)
                        if m and m.group(1).strip():
                            ind["married_surnames"].add(m.group(1).strip())

    return individuals


def _extract_name_parts(
    raw_names: List[str], married_surnames: set
) -> tuple[List[str], List[str]]:
    """
    Return (cleaned_given_variants, cleaned_surnames) without embedded quotes,
    parenthetical notes, or placeholder strings.
    """
    given_names: list[str] = []
    surnames: list[str] = []

    def add_given(val: str) -> None:
        cleaned = re.sub(r"\s+", " ", val).strip(" .,")
        if (
            cleaned
            and not cleaned.lower().startswith(("unknown", "child", "baby"))
            and cleaned not in given_names
        ):
            given_names.append(cleaned)

    def add_surname(val: str) -> None:
        cleaned = re.sub(r"\(.*?\)|\?", "", val).strip(" .,")
        if cleaned and cleaned.lower() != "unknown" and cleaned not in surnames:
            surnames.append(cleaned)

    for raw in raw_names:
        s_match = re.search(r"/([^/]+)/", raw)
        if s_match:
            add_surname(s_match.group(1))

        given_part = raw.split("/")[0].strip()
        # Extract quoted or parenthetical nicknames as alternate given names
        for n1, n2 in re.findall(r'["\']([^"\']+)["\']|\(([^)]+)\)', given_part):
            nick = (n1 or n2).strip()
            if len(nick) > 1:
                add_given(nick)

        # Strip nicknames from primary given string
        clean_given = re.sub(r'["\'].*?["\']|\(.*?\)', " ", given_part).strip()
        clean_given = re.sub(r"\s+", " ", clean_given)
        if clean_given:
            tokens = [t.strip(".") for t in clean_given.split() if t.strip(".")]
            if len(tokens) >= 2:
                # e.g., "Jonathan W Hellings" and "Jonathan William Hellings"
                add_given(f"{tokens[0]} {tokens[1][0]}")
                add_given(" ".join(tokens))
            if tokens:
                add_given(tokens[0])

    for ms in sorted(married_surnames):
        add_surname(ms)

    return given_names, surnames


def _extract_us_states(places: List[str]) -> List[str]:
    """Maps GEDCOM place strings to standardized U.S. State names."""
    found_states = set()
    for place in places:
        tokens = [t.strip(" .") for t in re.split(r"[,/]", place)]
        for tok in tokens:
            low = tok.lower()
            if low in STATE_LOOKUP:
                found_states.add(STATE_LOOKUP[low])
    return sorted(found_states)


def build_nara_queries(ind: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return an ordered list of clean, WAF-safe NARA API v2 query parameter dicts
    for an individual (from most specific to broadest), or [] if skipped.

    Avoids parentheses and double quotes in `q` because NARA's CloudFront/API
    Gateway routes URL-encoded parentheses/quotes to the React HTML frontend.
    """
    byear = ind["birth_year"]
    states = _extract_us_states(ind["places"])
    tags = ind["tags"]

    # 1. Pre-filter: Skip post-1955 births (72-year privacy rule)
    if byear and byear > 1955:
        return []

    # 2. Pre-filter: Skip individuals with places listed, none of which are U.S. states,
    #    unless they have U.S. immigration/naturalization tags
    has_us_events = bool(states) or bool(tags & {"IMMI", "NATU", "CENS"})
    if ind["places"] and not has_us_events:
        return []

    given_variants, surnames = _extract_name_parts(ind["names"], ind["married_surnames"])
    if not given_variants or not surnames:
        return []

    primary_state = states[0] if len(states) == 1 else ""
    queries: List[Dict[str, Any]] = []
    seen_q: set[str] = set()

    # 4. Build Record-Type & Geographic Anchors
    anchors: List[str] = []
    if states:
        anchors.extend(f'"{st}"' for st in states)

    # Tier 1: Most specific given variant (e.g., "Jonathan W" or "Mario E") + surname + single state
    for s in surnames:
        if primary_state:
            push_query(f"{given_variants[0]} {s} {primary_state}")
        # Tier 2: Given variants + surname (without state, in case state isn't indexed)
        for g in given_variants[:3]:
            push_query(f"{g} {s}")

    return queries


def build_nara_query(ind: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Backward-compatible helper returning the primary NARA API query dict, or None."""
    queries = build_nara_queries(ind)
    return queries[0] if queries else None


def is_valid_nara_hit(
    nara_title: str, ind: Dict[str, Any], scope_note: str = ""
) -> bool:
    """
    Filter out bulk microfilm rolls, census EDs, morning reports, and alphabetical
    range folders (e.g., 'Di Pietri THRU Polesello') unless BOTH the person's
    surname and given name appear explicitly in the title or scope note.
    """
    title_clean = (nara_title or "").strip()
    if not title_clean:
        return False
    title_lower = title_clean.casefold()
    haystack = f"{title_clean} {scope_note}".casefold()
    given_variants, surnames = _extract_name_parts(
        ind["names"], ind["married_surnames"]
    )
    if not given_variants or not surnames:
        return False
    # Extract individual given tokens of length >= 3 (e.g. "mario", "jonathan", "luigi")
    given_tokens = {
        tok.casefold()
        for g in given_variants
        for tok in g.split()
        if len(tok) >= 3
    }
    surname_tokens = {s.casefold() for s in surnames if len(s) >= 2}
    has_surname = any(
        re.search(rf"\b{re.escape(s)}\b", haystack) for s in surname_tokens
    )
    has_given = any(
        re.search(rf"\b{re.escape(g)}\b", haystack) for g in given_tokens
    )
    is_range_or_roll = (
        " thru " in title_lower
        or title_lower.startswith(_BULK_ROLL_PREFIXES)
        or bool(re.search(r"\b[a-z]{2,}\s*-\s*[a-z]{2,}\b", title_lower))
        and "index" in title_lower
    )
    if is_range_or_roll:
        # Only keep a range folder if BOTH surname AND given name explicitly appear
        # (e.g., "Enrollee Files: Decristoforo, Mario Edward THRU Dedow, William Clifford")
        return has_surname and has_given
    # For regular items/fileUnits, require at least the surname to appear in title/note
    return has_surname