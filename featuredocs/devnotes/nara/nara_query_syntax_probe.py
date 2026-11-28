"""
Check which query forms the NARA Catalog API v2 search accepts.

Sends the searches in PROBES for "John Smith" (one of the key's monthly
queries each; the GWizard usage counter does not see them) and prints, for
each, the HTTP status, the content type, the body size and the number of
hits, or the start of the body when it is not JSON. The results found so far
are noted above PROBES; gwizardnaraquerybuilder.py (the scan) and
gwizardnaralauncher.py (the search window) build their queries from them.

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
    # Results with dateRange 1879 TO 1973 (Nov 28, 2026):
    #   John Smith (loose words)                    1,078,648 hits
    #   "John Smith"                                   45,725
    #   "Smith John"                                  108,220
    #   "John Smith" OR "Smith John"                        4  OR is a word
    #   "John Smith" OR "Smith John", no dateRange          4
    #   "John Smith" | "Smith John"                       680  | acts as AND
    #   "John Smith"~2                                 43,104  no either-order
    #   "John Smith" pension                           17,832  space = AND
    #   ("John Smith" | "Smith John") pension               0
    #   ("John Smith" OR "Smith John") AND pension  web page (HTML), not JSON
    # So: one exact phrase per request, surname first finds the most;
    # further words narrow (AND); there is no OR and no grouping.
    ("other order, one phrase", '"Smith John"', YEARS),
    ("phrases with |", '"John Smith" | "Smith John"', YEARS),
    ("phrase in either order ~2", '"John Smith"~2', YEARS),
    ("phrase and a word", '"John Smith" pension', YEARS),
    ("| group and a word", '("John Smith" | "Smith John") pension', YEARS),
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
