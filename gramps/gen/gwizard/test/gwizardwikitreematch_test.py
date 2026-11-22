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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
"""Tests for scoring WikiTree profiles against the target person."""

# ------------------------------------------------------------
#
# Python modules
#
# ------------------------------------------------------------
import unittest

# ------------------------------------------------------------
#
# Local imports
#
# ------------------------------------------------------------
from ..gwizardwikitreematch import (
    MatchQuery,
    candidate_from_profile,
    jaro_winkler,
    match_text,
    score_profile,
)

FRANKLIN = {
    "Name": "Franklin-1",
    "FirstName": "Benjamin",
    "LastNameAtBirth": "Franklin",
    "LastNameCurrent": "Franklin",
    "Gender": "Male",
    "BirthDate": "1706-01-17",
    "DeathDate": "1790-04-17",
}


class TestWikiTreeMatch(unittest.TestCase):
    """Test the Match column score."""

    def test_jaro_winkler(self) -> None:
        """Verify the textbook values."""
        self.assertAlmostEqual(jaro_winkler("MARTHA", "MARHTA"), 0.961, places=3)
        self.assertEqual(jaro_winkler("same", "SAME"), 1.0)
        self.assertEqual(jaro_winkler("", "x"), 0.0)

    def test_exact_match(self) -> None:
        """Verify a profile matching on every part scores 100%."""
        query = MatchQuery("Benjamin", "", ["Franklin"], 1706, 1790, "Male")
        result = score_profile(query, FRANKLIN)
        self.assertEqual(result.score, 100.0)
        self.assertEqual(match_text(result), "100%")

    def test_years_fade(self) -> None:
        """Verify the score drops as the birth year moves away."""
        near = score_profile(MatchQuery("Benjamin", "", ["Franklin"], 1708), FRANKLIN)
        far = score_profile(MatchQuery("Benjamin", "", ["Franklin"], 1720), FRANKLIN)
        self.assertLess(near.score, 100.0)
        self.assertGreater(near.score, far.score)
        self.assertAlmostEqual(far.score, 65 / 90 * 100, places=1)

    def test_name_only(self) -> None:
        """Verify a profile without dates is marked name only."""
        profile = dict(FRANKLIN, BirthDate="0000-00-00", DeathDate="")
        result = score_profile(MatchQuery("Benjamin", "", ["Franklin"], 1706), profile)
        self.assertEqual(match_text(result), "100% (name only)")

    def test_decade_only_dates(self) -> None:
        """Verify a private profile's decade counts the years inside it."""
        profile = dict(FRANKLIN, BirthDate="", BirthDateDecade="1700s")
        inside = score_profile(MatchQuery("Benjamin", "", ["Franklin"], 1706), profile)
        outside = score_profile(MatchQuery("Benjamin", "", ["Franklin"], 1712), profile)
        self.assertEqual(inside.score, 100.0)
        self.assertLess(outside.score, 100.0)

    def test_married_surname_matches(self) -> None:
        """Verify a target's married name matches the profile's current name."""
        profile = {
            "FirstName": "Mary",
            "LastNameAtBirth": "Kreizer",
            "LastNameCurrent": "Smith",
            "LastNameOther": "Smyth, Schmidt",
        }
        self.assertEqual(
            candidate_from_profile(profile).surnames,
            ["Kreizer", "Smith", "Smyth", "Schmidt"],
        )
        result = score_profile(MatchQuery("Mary", "", ["Jones", "Smith"]), profile)
        self.assertEqual(result.score, 100.0)

    def test_sound_alike_names(self) -> None:
        """Verify spelling variants score high and other surnames low."""
        profile = dict(FRANKLIN, BirthDate="")
        variant = score_profile(MatchQuery("Benjamin", "", ["Frankline"]), profile)
        other = score_profile(MatchQuery("Benjamin", "", ["Fletcher"]), profile)
        self.assertGreater(variant.score, 95.0)
        self.assertLess(other.score, 85.0)

    def test_different_gender_halves_score(self) -> None:
        """Verify a known gender that differs halves the score."""
        query = MatchQuery("Benjamin", "", ["Franklin"], 1706, 1790, "Female")
        self.assertEqual(score_profile(query, FRANKLIN).score, 50.0)
        query.gender = ""
        self.assertEqual(score_profile(query, FRANKLIN).score, 100.0)

    def test_first_name_with_middle(self) -> None:
        """Verify a first name holding two names is split."""
        candidate = candidate_from_profile({"FirstName": "Mary Ann"})
        self.assertEqual((candidate.given, candidate.middle), ("Mary", "Ann"))

    def test_initial_and_middle_name(self) -> None:
        """Verify initials and middle names adjust the given-name score."""
        profile = {"FirstName": "John", "MiddleName": "Adam", "LastNameAtBirth": "Doe"}
        same = score_profile(MatchQuery("John", "Adam", ["Doe"]), profile).score
        initial = score_profile(MatchQuery("J", "", ["Doe"]), profile).score
        other = score_profile(MatchQuery("John", "Robert", ["Doe"]), profile).score
        self.assertEqual(same, 100.0)
        self.assertLess(initial, same)
        self.assertLess(other, same)

    def test_nothing_to_compare(self) -> None:
        """Verify a profile with none of the target's parts scores 0."""
        result = score_profile(MatchQuery(birth_year=1800), {"FirstName": "Ann"})
        self.assertEqual(result.score, 0.0)
        self.assertFalse(MatchQuery().has_name())


if __name__ == "__main__":
    unittest.main()
