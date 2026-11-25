import os
import sys
import requests

from gwizardnaraquerybuilder import (
    parse_gedcom_individuals,
    build_nara_queries,
    is_valid_nara_hit,
)

API_KEY = os.environ.get("NARA_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: NARA_API_KEY is not set.")
    sys.exit(1)

GED_PATH = r"C:\gramps_dev\gramps_gwizard_naramerge_plugin\White-Pittaluga_LegacyImport_Backup_2026-10-16_AfterGoatFix.ged"
URL = "https://" + "catalog.archives.gov" + "/api/v2/records/search"
HEADERS = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

print("Endpoint:", URL)
inds = parse_gedcom_individuals(GED_PATH)
test_ids = ["I00017", "I00125", "I500124", "I00297", "I00434"]

for pid in test_ids:
    ind = inds[pid]
    queries = build_nara_queries(ind)
    print(f"\n=== {pid} {ind['names']} (queries: {[q['q'] for q in queries]}) ===")
    seen_naids = set()
    for params in queries:
        resp = requests.get(URL, params=params, headers=HEADERS, timeout=20)
        if resp.status_code != 200 or not resp.text.strip().startswith("{"):
            print(f"  [HTTP {resp.status_code}] URL={resp.url}")
            continue
        hits = resp.json().get("body", {}).get("hits", {}).get("hits", [])
        print(f"  Query {params['q']!r} -> {len(hits)} raw hits")
        for h in hits:
            rec = h.get("_source", {}).get("record", {})
            naid = str(rec.get("naId") or "")
            title = str(rec.get("title") or "")
            note = str(rec.get("scopeAndContentNote") or "")
            if naid in seen_naids:
                continue
            seen_naids.add(naid)
            kept = is_valid_nara_hit(title, ind, note)
            print(f"    [{'KEEP' if kept else 'DROP'}] NAID {naid}: {title}")
