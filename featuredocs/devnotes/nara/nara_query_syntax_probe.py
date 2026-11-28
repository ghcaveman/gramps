"""
Check which query forms the NARA Catalog API v2 search accepts.

Sends five searches for "John Smith" (five of the key's monthly queries;
the GWizard usage counter does not see them) and prints, for each, the
HTTP status, the content type, the body size and the number of hits, or
the start of the body when it is not JSON.

Run from an MSYS2 shell with NARA_API_KEY set:
    python featuredocs/devnotes/nara/nara_query_syntax_probe.py
"""

import json
import os
import sys

import requests

URL = "https://catalog.archives.gov/api/v2/records/search"
YEARS = "1879 TO 1973"

PROBES = [
    ("loose words", "John Smith", YEARS),
    ("one phrase", '"John Smith"', YEARS),
    ("phrases with OR", '"John Smith" OR "Smith John"', YEARS),
    ("phrases with OR, no years", '"John Smith" OR "Smith John"', ""),
    ("grouped with AND", '("John Smith" OR "Smith John") AND pension', YEARS),
]


def main() -> int:
    key = os.environ.get("NARA_API_KEY", "").strip()
    if not key:
        print("NARA_API_KEY is not set.")
        return 1
    headers = {
        "Accept": "application/json",
        "User-Agent": "Gramps-GWizard-NARA/1.0",
        "x-api-key": key,
    }
    for label, query, years in PROBES:
        params = {"q": query, "limit": 3}
        if years:
            params["dateRange"] = years
        try:
            response = requests.get(URL, params=params, headers=headers, timeout=30)
        except requests.RequestException as err:
            print(f"{label:28} request failed: {err}")
            continue
        kind = response.headers.get("Content-Type", "?")
        size = len(response.content or b"")
        try:
            body = response.json()
        except ValueError:
            snippet = (response.text or "")[:200].replace("\n", " ")
            print(
                f"{label:28} HTTP {response.status_code} {kind} {size} bytes, NOT JSON: {snippet!r}"
            )
            continue
        hits = body.get("body", {}).get("hits", {})
        total = hits.get("total", {})
        total = total.get("value", total) if isinstance(total, dict) else total
        print(f"{label:28} HTTP {response.status_code} {size} bytes, {total} hits")
        if response.status_code != 200:
            print("    ", json.dumps(body)[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
