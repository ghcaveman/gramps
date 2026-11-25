import re
from typing import Dict, List, Optional, Any

# Standard U.S. State names and abbreviations for location extraction
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


def _clean_name_variants(raw_names: List[str], married_surnames: set) -> List[str]:
    """Generates clean 'First Last' and 'Last, First' variants without nicknames/suffixes."""
    variants = set()
    given_names = set()
    surnames = set(married_surnames)

    for raw in raw_names:
        # Extract surname inside /.../
        s_match = re.search(r"/([^/]+)/", raw)
        surname = s_match.group(1).strip() if s_match else ""
        # Remove trailing ? or parenthetical notes like (AZ) or (Montevideo)
        surname = re.sub(r"\(.*?\)|\?", "", surname).strip()
        if not surname or surname.lower() == "unknown":
            continue
        surnames.add(surname)

        # Extract given part before /.../
        given_part = raw.split("/")[0].strip()
        # Extract quoted or parenthetical nicknames as alternate given names
        nicks = re.findall(r'["\']([^"\']+)["\']|\(([^)]+)\)', given_part)
        for n1, n2 in nicks:
            nick = (n1 or n2).strip()
            if len(nick) > 1:
                given_names.add(nick)

        # Strip nicknames and punctuation from primary given name
        clean_given = re.sub(r'["\'].*?["\']|\(.*?\)', "", given_part).strip()
        clean_given = re.sub(r"\s+", " ", clean_given)
        if clean_given and not clean_given.lower().startswith(
            ("unknown", "child", "baby")
        ):
            given_names.add(clean_given)
            # Also add first token only if middle name exists (e.g. "Luigi" from "Luigi Emmanual")
            first_token = clean_given.split(" ")[0].rstrip(".")
            if len(first_token) > 1:
                given_names.add(first_token)

    for g in given_names:
        for s in surnames:
            variants.add(f'"{g} {s}"')
            variants.add(f'"{s}, {g}"')

    return sorted(variants)


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


def build_nara_query(ind: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Returns NARA API v2 query parameters for an individual,
    or None if the profile should be skipped (non-U.S., post-1955, or missing name).
    """
    byear = ind["birth_year"]
    dyear = ind["death_year"]
    states = _extract_us_states(ind["places"])
    tags = ind["tags"]
    sex = ind["sex"]

    # 1. Pre-filter: Skip post-1955 births (72-year privacy rule)
    if byear and byear > 1955:
        return None

    # 2. Pre-filter: Skip individuals with places listed, none of which are U.S. states,
    #    unless they have U.S. immigration/naturalization tags
    has_us_events = bool(states) or bool(tags & {"IMMI", "NATU", "CENS"})
    if ind["places"] and not has_us_events:
        return None

    # 3. Build Name Variants
    name_clauses = _clean_name_variants(ind["names"], ind["married_surnames"])
    if not name_clauses:
        return None

    q_parts = [f"({' OR '.join(name_clauses)})"]

    # 4. Build Record-Type & Geographic Anchors
    anchors = []
    if states:
        anchors.extend(f'"{st}"' for st in states)

    # Immigration / Naturalization anchors
    if "IMMI" in tags or "NATU" in tags:
        anchors.extend(
            [
                '"naturalization"',
                '"petition"',
                '"declaration"',
                '"manifest"',
                '"crossing"',
            ]
        )

    # Military / Draft / Pension anchors based on birth cohort
    if sex == "M" and byear:
        if 1820 <= byear <= 1848:
            anchors.extend(['"pension"', '"infantry"', '"cavalry"', '"regiment"'])
        elif 1872 <= byear <= 1927:
            anchors.extend(['"draft"', '"selective service"', '"enlistment"'])

    if any("MILITARY" in t or "PENSION" in t for t in tags):
        anchors.extend(['"pension"', '"military"', '"service"'])

    if anchors:
        # Deduplicate while preserving order
        unique_anchors = list(dict.fromkeys(anchors))
        q_parts.append(f"({' OR '.join(unique_anchors)})")

    return {
        "q": " AND ".join(q_parts),
        "availableOnline": "true",
        "levelOfDescription": "item,fileUnit",
        "limit": 25,
    }


def is_valid_nara_hit(nara_title: str, ind: Dict[str, Any]) -> bool:
    """
    Post-filter to discard alphabetical microfilm range folders (e.g., 'Smith THRU Snyder')
    unless the person's actual given name appears in the record title.
    """
    title_upper = nara_title.upper()
    is_range_folder = " THRU " in title_upper or title_upper.startswith(
        "NATURALIZATION INDEX"
    )

    if is_range_folder:
        # Check if any of the person's given names explicitly appear in the title
        for raw in ind["names"]:
            given_part = re.sub(r'["\'].*?["\']|\(.*?\)', "", raw.split("/")[0]).strip()
            for token in given_part.split():
                clean_tok = token.strip(".").upper()
                if len(clean_tok) > 2 and clean_tok in title_upper:
                    return True
        return False
    return True
