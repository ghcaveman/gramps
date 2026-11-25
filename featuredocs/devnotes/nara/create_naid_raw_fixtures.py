import json
import os
import requests

API_KEY = os.environ.get("NARA_API_KEY", "").strip()
URL = "https://" + "catalog.archives.gov" + "/api/v2/records/search"
HEADERS = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

fixtures = {}
for naid in ["162205316", "525749641", "132721642"]:
    resp = requests.get(URL, params={"naId": naid}, headers=HEADERS, timeout=20)
    hits = resp.json().get("body", {}).get("hits", {}).get("hits", [])
    if hits:
        fixtures[naid] = hits[0].get("_source", {}).get("record", {})

with open("naid_raw_fixtures.json", "w", encoding="utf-8") as f:
    json.dump(fixtures, f, indent=2)

print("Saved naid_raw_fixtures.json with NAIDs:", list(fixtures.keys()))
