import os
import sys
import requests

API_KEY = os.environ.get("NARA_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: NARA_API_KEY is not set.")
    sys.exit(1)

BASE_URL = "https://catalog.archives.gov/api/v2/records/search"
HEADERS = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

test_queries = {
    "I500124 - Luigi Pittaluga": "Luigi Pittaluga",
    "I500124 - Louis Pittaluga": "Louis Pittaluga",
    "I00297 - Alphonse Altomari": "Alphonse Altomari",
    "I00297 - Alfonso Altomari": "Alfonso Altomari",
    "I00017 - Jonathan Hellings": "Jonathan Hellings",
    "I00116 - Giacento Di Lauro": "Giacento Di Lauro",
    "I00123 - Sebastian Decristoforo": "Sebastian Decristoforo",
    "I00434 - Gilbert Warner White": "Gilbert Warner White",
}

for label, q in test_queries.items():
    resp = requests.get(
        BASE_URL,
        params={"q": q, "limit": 10},
        headers=HEADERS,
        timeout=20,
    )
    print(f"\n=== {label} [HTTP {resp.status_code}] ===")
    if not resp.text.strip().startswith("{"):
        print(f"  Unexpected HTML response for q={q!r}")
        continue
    data = resp.json()
    hits = data.get("body", {}).get("hits", {}).get("hits", [])
    print(f"  Hits returned: {len(hits)}")
    for h in hits:
        rec = h.get("_source", {}).get("record", {})
        naid = rec.get("naId")
        level = rec.get("levelOfDescription")
        title = rec.get("title")
        print(f"  - NAID {naid} [{level}]: {title}")
