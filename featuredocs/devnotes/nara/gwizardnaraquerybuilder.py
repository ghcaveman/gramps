import re
from typing import Dict, List, Optional, Any

US_STATES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}
STATE_LOOKUP = {k.lower(): v for k, v in US_STATES.items()}
STATE_LOOKUP.update({v.lower(): v for v in US_STATES.values()})

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
                        "id": curr_id,
                        "names": [],
                        "sex": None,
                        "birth_year": None,
                        "death_year": None,
                        "places": [],
                        "tags": set(),
                        "fams": [],
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
        for n1, n2 in re.findall(r'["\']([^"\']+)["\']|\(([^)]+)\)', given_part):
            nick = (n1 or n2).strip()
            if len(nick) > 1:
                add_given(nick)

        clean_given = re.sub(r'["\'].*?["\']|\(.*?\)', " ", given_part).strip()
        clean_given = re.sub(r"\s+", " ", clean_given)
        if clean_given:
            tokens = [t.strip(".") for t in clean_given.split() if t.strip(".")]
            if len(tokens) >= 2:
                add_given(f"{tokens[0]} {tokens[1][0]}")
                add_given(" ".join(tokens))
            if tokens:
                add_given(tokens[0])

    for ms in sorted(married_surnames):
        add_surname(ms)

    return given_names, surnames


def _extract_us_states(places: List[str]) -> List[str]:
    found_states = set()
    for place in places:
        tokens = [t.strip(" .") for t in re.split(r"[,/]", place)]
        for tok in tokens:
            low = tok.lower()
            if low in STATE_LOOKUP:
                found_states.add(STATE_LOOKUP[low])
    return sorted(found_states)


def build_nara_queries(ind: Dict[str, Any]) -> List[Dict[str, Any]]:
    byear = ind["birth_year"]
    states = _extract_us_states(ind["places"])
    tags = ind["tags"]

    if byear and byear > 1955:
        return []

    has_us_events = bool(states) or bool(tags & {"IMMI", "NATU", "CENS"})
    if ind["places"] and not has_us_events:
        return []

    given_variants, surnames = _extract_name_parts(
        ind["names"], ind["married_surnames"]
    )
    if not given_variants or not surnames:
        return []

    primary_state = states[0] if len(states) == 1 else ""
    queries: List[Dict[str, Any]] = []
    seen_q: set[str] = set()

    def push_query(q_str: str) -> None:
        q_clean = re.sub(r"\s+", " ", q_str).strip()
        if q_clean and q_clean not in seen_q:
            seen_q.add(q_clean)
            queries.append({"q": q_clean, "limit": 20})

    for s in surnames:
        if primary_state:
            push_query(f"{given_variants[0]} {s} {primary_state}")
        for g in given_variants[:3]:
            push_query(f"{g} {s}")

    return queries


def build_nara_query(ind: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    queries = build_nara_queries(ind)
    return queries[0] if queries else None


def is_valid_nara_hit(
    nara_title: str,
    ind: Dict[str, Any],
    scope_note: str = "",
    max_years_after_death: int = 5,
) -> bool:
    """
    Filter out bulk microfilm rolls, census EDs, morning reports, out-of-range years,
    and alphabetical range folders unless BOTH the person's surname and given name
    appear explicitly in the record title itself.
    """
    title_clean = (nara_title or "").strip()
    if not title_clean:
        return False

    title_lower = title_clean.casefold()
    haystack = f"{title_clean} {scope_note}".casefold()

    byear = ind.get("birth_year")
    dyear = ind.get("death_year")
    title_years = [
        int(y) for y in re.findall(r"\b(1[7-9]\d{2}|20[0-2]\d)\b", title_clean)
    ]
    if title_years:
        if byear and max(title_years) < byear:
            return False
        if dyear and min(title_years) > (dyear + max_years_after_death):
            return False

    given_variants, surnames = _extract_name_parts(
        ind["names"], ind["married_surnames"]
    )
    if not given_variants or not surnames:
        return False

    given_tokens = {
        tok.casefold() for g in given_variants for tok in g.split() if len(tok) >= 3
    }
    surname_tokens = {s.casefold() for s in surnames if len(s) >= 2}

    surname_in_title = any(
        re.search(rf"\b{re.escape(s)}\b", title_lower) for s in surname_tokens
    )
    given_in_title = any(
        re.search(rf"\b{re.escape(g)}\b", title_lower) for g in given_tokens
    )
    has_surname = surname_in_title or any(
        re.search(rf"\b{re.escape(s)}\b", haystack) for s in surname_tokens
    )

    is_range_or_roll = (
        " thru " in title_lower
        or "enumeration district" in title_lower
        or title_lower.startswith(_BULK_ROLL_PREFIXES)
        or title_lower.startswith("pension file number")
        or (
            bool(re.search(r"\b[a-z]{2,}\s*-\s*[a-z]{2,}\b", title_lower))
            and "index" in title_lower
        )
    )

    if is_range_or_roll:
        return surname_in_title and given_in_title

    return has_surname
