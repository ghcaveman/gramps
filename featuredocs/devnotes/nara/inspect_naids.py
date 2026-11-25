import json
import os
import sys
import requests

API_KEY = os.environ.get("NARA_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: NARA_API_KEY is not set.")
    sys.exit(1)

URL = "https://" + "catalog.archives.gov" + "/api/v2/records/search"
HEADERS = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

for naid in ["162205316", "525749641", "132721642"]:
    resp = requests.get(URL, params={"naId": naid}, headers=HEADERS, timeout=20)
    hits = resp.json().get("body", {}).get("hits", {}).get("hits", [])
    print(f"\n================ NAID {naid} ================")
    if not hits:
        print("  Not found.")
        continue
    rec = hits[0].get("_source", {}).get("record", {})
    summary = {
        "naId": rec.get("naId"),
        "title": rec.get("title"),
        "levelOfDescription": rec.get("levelOfDescription"),
        "recordGroupNumber": rec.get("ancestors", [{}])[0].get("recordGroupNumber"),
        "seriesTitle": next(
            (
                a.get("title")
                for a in rec.get("ancestors", [])
                if a.get("levelOfDescription") == "series"
            ),
            None,
        ),
        "inclusiveStartDate": rec.get("inclusiveStartDate"),
        "inclusiveEndDate": rec.get("inclusiveEndDate"),
        "scopeAndContentNote": rec.get("scopeAndContentNote"),
        "generalRecordsTypes": rec.get("generalRecordsTypes"),
        "digitalObjectCount": len(rec.get("digitalObjects") or []),
    }
    print(json.dumps(summary, indent=2))
