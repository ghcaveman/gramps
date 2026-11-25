import json
import os
import sys
import unittest

# Ensure the addon directory is importable whether run from repo root or test/
_HERE = os.path.dirname(os.path.abspath(__file__))
for candidate in (_HERE, os.path.dirname(_HERE)):
    if os.path.isfile(os.path.join(candidate, "gwizardnaraquerybuilder.py")):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        break

import gwizardnaraquerybuilder as qb
from gramps.gen.gwizard.gwizard_base import RecordQuery, score_record
from gramps.gen.gwizard.gwizardnaramatch import best_match, record_candidate
from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface


def _load_fixture_records() -> dict[str, dict]:
    """Load raw NARA records from naid_raw_fixtures.json if present, else use stubs."""
    for folder in (_HERE, os.path.dirname(_HERE)):
        fixture_path = os.path.join(folder, "naid_raw_fixtures.json")
        if os.path.isfile(fixture_path):
            with open(fixture_path, encoding="utf-8") as f:
                return json.load(f)

    return {
        "162205316": {
            "naId": 162205316,
            "title": "[Pennsylvania] Hellings, Jonathan W - 214th Infantry, Company K",
            "levelOfDescription": "fileUnit",
            "scopeAndContentNote": (
                "The volunteer's Enlistment Rank is listed as Pvt, "
                "and the Discharge Rank is listed as Pvt."
            ),
        },
        "525749641": {
            "naId": 525749641,
            "title": "Enrollee Files: Decristoforo, Mario Edward THRU Dedow, William Clifford",
            "levelOfDescription": "fileUnit",
            "scopeAndContentNote": None,
        },
    }


FIXTURES = _load_fixture_records()


class TestGWizardNaraQueryAndMatch(unittest.TestCase):
    """Tests for NARA query generation, roll filtering, and ground-truth matches."""

    def test_build_nara_queries_hellings_includes_middle_initial_and_state(self):
        ind = {
            "names": ["Jonathan William /Hellings/"],
            "married_surnames": set(),
            "sex": "M",
            "birth_year": 1847,
            "death_year": 1930,
            "places": ["Montgomery, Pennsylvania", "Philadelphia, Pennsylvania"],
            "tags": {"BIRT", "DEAT", "MILITARYSERVICE", "PENSION"},
        }
        queries = qb.build_nara_queries(ind)
        q_strings = [q["q"] for q in queries]

        self.assertEqual(q_strings[0], "Jonathan W Hellings Pennsylvania")
        self.assertIn("Jonathan William Hellings", q_strings)
        self.assertIn("Jonathan Hellings", q_strings)
        for q in q_strings:
            self.assertNotIn("(", q)
            self.assertNotIn(")", q)
            self.assertNotIn('"', q)

    def test_build_nara_queries_strips_nicknames_and_handles_aka(self):
        ind = {
            "names": ['Alphonse "Fred" /Altomari/', "Alfonso Fred /Altomari/"],
            "married_surnames": set(),
            "sex": "M",
            "birth_year": 1885,
            "death_year": 1943,
            "places": ["Philadelphia, Pennsylvania, USA"],
            "tags": {"BIRT", "DEAT", "IMMI", "NATU"},
        }
        queries = qb.build_nara_queries(ind)
        q_strings = [q["q"] for q in queries]

        self.assertTrue(any("Fred Altomari" in q for q in q_strings))
        self.assertTrue(any("Alphonse Altomari" in q for q in q_strings))
        for q in q_strings:
            self.assertNotIn('"', q)

    def test_build_nara_queries_skips_post_1955_and_foreign_only(self):
        post_1955 = {
            "names": ["Edoardo /Bagnasco/"],
            "married_surnames": set(),
            "sex": "M",
            "birth_year": 2022,
            "death_year": None,
            "places": ["Genova"],
            "tags": {"BIRT"},
        }
        foreign_only = {
            "names": ["Carlo /Pittaluga/"],
            "married_surnames": set(),
            "sex": "M",
            "birth_year": 1910,
            "death_year": 1991,
            "places": ["Genova"],
            "tags": {"BIRT", "DEAT"},
        }
        self.assertEqual(qb.build_nara_queries(post_1955), [])
        self.assertEqual(qb.build_nara_queries(foreign_only), [])

    def test_is_valid_nara_hit_filters_range_folders_and_rolls(self):
        ind_pittaluga = {
            "names": ["Luigi /Pittaluga/", "Louis /Pittaluga/"],
            "married_surnames": set(),
            "birth_year": 1898,
            "death_year": 1981,
        }
        noise_titles = [
            "Di Pietri, Mariano THRU Polesello, Silvio [2 of 2]",
            "1910-1929: Pitcairn, Raymond THRU Plantin, Paul",
            "Naturalization Index, 1927-1966, Pittaluga-Pizzuto",
            "Morning Reports for October 1943: Roll 599 (3 of 3)",
            "FICHE_655",
            "New York: NEW YORK County, Enumeration District 205, Sheet No. 6B",
        ]
        for title in noise_titles:
            with self.subTest(title=title):
                self.assertFalse(
                    qb.is_valid_nara_hit(
                        title, ind_pittaluga, scope_note="Pittaluga, Louis"
                    )
                )

    def test_is_valid_nara_hit_rejects_post_death_docket(self):
        ind_mario = {
            "names": ["Mario E /Decristoforo/"],
            "married_surnames": set(),
            "birth_year": 1922,
            "death_year": 1976,
        }
        self.assertFalse(
            qb.is_valid_nara_hit(
                "Docket No. 02-2162: In the Matter of Mario Decristoforo "
                "and the U.S. Postal Service, Post Office: Phoenix, Arizona, "
                "December 23, 2002",
                ind_mario,
            )
        )

    def test_ground_truth_naid_162205316_jonathan_hellings(self):
        raw_rec = FIXTURES["162205316"]
        parsed = NaraCatalogInterface.parse_record({"_source": {"record": raw_rec}})

        ind = {
            "names": ["Jonathan William /Hellings/"],
            "married_surnames": set(),
            "birth_year": 1847,
            "death_year": 1930,
        }
        self.assertTrue(
            qb.is_valid_nara_hit(
                str(parsed.get("title") or ""),
                ind,
                str(parsed.get("scope_note") or ""),
            )
        )

        query = RecordQuery(
            given="Jonathan",
            middle="William",
            surnames=["Hellings"],
            birth_year=1847,
            death_year=1930,
            gender="male",
        )
        best = best_match(query, parsed)
        self.assertIsNotNone(best.candidate)
        cand = record_candidate(best.candidate)
        score = score_record(query, cand).score
        self.assertGreaterEqual(score, 80.0)

    def test_ground_truth_naid_525749641_mario_decristoforo(self):
        raw_rec = FIXTURES["525749641"]
        parsed = NaraCatalogInterface.parse_record({"_source": {"record": raw_rec}})

        ind = {
            "names": ["Mario E /Decristoforo/"],
            "married_surnames": set(),
            "birth_year": 1922,
            "death_year": 1976,
        }
        self.assertTrue(
            qb.is_valid_nara_hit(
                str(parsed.get("title") or ""),
                ind,
                str(parsed.get("scope_note") or ""),
            )
        )


if __name__ == "__main__":
    unittest.main()
