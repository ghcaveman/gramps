#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Kevin White
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Unit tests for scoring FamilySearch search results (gwizardfsmatch.py).
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import unittest

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.gwizard.gwizard_base import RecordQuery
from gramps.gen.gwizard.gwizardfsmatch import (
    ID_MATCH_SORT_SCORE,
    _life_years,
    candidate_from_result,
    id_match_text,
    match_text,
    score_result,
)


# ------------------------------------------------------------------
#
# FamilySearchMatchTest
#
# ------------------------------------------------------------------
class FamilySearchMatchTest(unittest.TestCase):
    """Turning FamilySearch results into candidates and scoring them."""

    def setUp(self) -> None:
        self.query = RecordQuery(
            given="Henry", surnames=["Schmidt"], birth_year=1890, gender="male"
        )

    def test_life_years(self):
        self.assertEqual(_life_years("1809 - 1865"), (1809, 1865))
        self.assertEqual(_life_years("1809-"), (1809, None))
        self.assertEqual(_life_years("1900"), (1900, None))
        self.assertEqual(_life_years(""), (None, None))

    def test_candidate_uses_dates_before_lifespan(self):
        cand = candidate_from_result(
            {
                "name": "George Henry Schmidt",
                "life": "1889-1960",
                "birth_date": "25 December 1890",
                "gender": "Male",
            }
        )
        self.assertEqual(cand.given, "George")
        self.assertEqual(cand.middle, "Henry")
        self.assertEqual(cand.surnames, ["Schmidt"])
        self.assertEqual(cand.birth_years, (1890, 1890))
        self.assertEqual(cand.death_years, (1960, 1960))
        self.assertEqual(cand.gender, "male")

    def test_candidate_single_name(self):
        cand = candidate_from_result({"name": "Henry"})
        self.assertEqual(cand.given, "Henry")
        self.assertEqual(cand.surnames, [])
        self.assertIsNone(cand.birth_years)

    def test_exact_match_scores_100(self):
        result = score_result(
            self.query,
            {
                "name": "Henry Schmidt",
                "birth_date": "1 September 1890",
                "gender": "Male",
            },
        )
        self.assertEqual(result.score, 100.0)
        self.assertEqual(match_text(result), "100%")

    def test_differences_lower_the_score(self):
        exact = score_result(
            self.query, {"name": "Henry Schmidt", "birth_date": "1890"}
        ).score
        later = score_result(
            self.query, {"name": "Henry Schmidt", "birth_date": "about 1895"}
        ).score
        other_given = score_result(
            self.query, {"name": "Martin Henry Schmidt", "birth_date": "1890"}
        ).score
        female = score_result(
            self.query,
            {"name": "Henry Schmidt", "birth_date": "1890", "gender": "Female"},
        ).score
        self.assertGreater(exact, later)
        self.assertGreater(exact, other_given)
        self.assertLess(female, exact / 2 + 1)

    def test_name_only_match_is_marked(self):
        result = score_result(self.query, {"name": "Henry Schmidt"})
        self.assertEqual(match_text(result), "100% (name only)")

    def test_id_match_sorts_above_any_score(self):
        self.assertGreater(ID_MATCH_SORT_SCORE, 100.0)
        self.assertEqual(id_match_text(), "100% (FamilySearch ID)")


if __name__ == "__main__":
    unittest.main()
