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

"""
Unit tests for finding and scoring the people NARA records name
(gwizardnaramatch.py). The titles are real NARA catalog titles.
"""

# ------------------------------------------------------------
#
# Python modules
#
# ------------------------------------------------------------
import unittest

# ------------------------------------------------------------
#
# Gramps modules
#
# ------------------------------------------------------------
from ..gwizardnaramatch import (
    Candidate,
    MatchQuery,
    best_match,
    candidates_from_record,
    jaro_winkler,
    match_text,
    name_similarity,
    score_candidate,
    sounds_alike,
)


def _names(title: str, note: str = "") -> list[str]:
    """Return the display names found in a title and description."""
    return [
        c.display()
        for c in candidates_from_record({"title": title, "scope_note": note})
    ]


class TestSimilarity(unittest.TestCase):
    """Test the name similarity measures."""

    def test_jaro_winkler_known_values(self) -> None:
        """Verify the textbook Jaro-Winkler examples."""
        self.assertAlmostEqual(jaro_winkler("MARTHA", "MARHTA"), 0.9611, places=4)
        self.assertAlmostEqual(jaro_winkler("DWAYNE", "DUANE"), 0.84, places=4)
        self.assertAlmostEqual(jaro_winkler("DIXON", "DICKSONX"), 0.8133, places=4)
        self.assertEqual(jaro_winkler("smith", "SMITH"), 1.0)
        self.assertEqual(jaro_winkler("", "smith"), 0.0)
        self.assertEqual(jaro_winkler("abc", "xyz"), 0.0)

    def test_sound_alike_bonus(self) -> None:
        """Verify sound-alike names get the bonus, capped at 1.0."""
        self.assertTrue(sounds_alike("Schmidt", "Smith"))
        self.assertFalse(sounds_alike("Smith", "Jones"))
        self.assertGreater(
            name_similarity("Smyth", "Smith"), jaro_winkler("Smyth", "Smith")
        )
        self.assertEqual(name_similarity("Mac donald", "MacDonald"), 1.0)


class TestCandidates(unittest.TestCase):
    """Test finding names in real NARA titles and descriptions."""

    def test_pension_file_titles(self) -> None:
        """Verify the widow and the soldier are both found."""
        names = candidates_from_record(
            {
                "title": "Approved Pension Application File for Mary Kreizer Smith, "
                "Widow of John A Smith, Company B, 4th Maryland Infantry Regiment "
                "(Application No. WC47795)"
            }
        )
        self.assertEqual(
            [c.display() for c in names], ["Smith, Mary Kreizer", "Smith, John A"]
        )
        self.assertEqual([c.role for c in names], ["subject", "widow"])

    def test_index_and_related_titles(self) -> None:
        """Verify the common title shapes."""
        self.assertEqual(
            _names("MacDonald, Lyman Angus - 1942"), ["MacDonald, Lyman Angus"]
        )
        self.assertEqual(
            _names("Devault, John - State: Tennessee - Year: 1865"), ["Devault, John"]
        )
        self.assertEqual(_names("Records related to Jacob Devault"), ["Devault, Jacob"])
        self.assertEqual(
            _names("Photograph of Arthur E. Devault"), ["Devault, Arthur E"]
        )
        self.assertEqual(
            _names("[Connecticut] Hine, Lewis - 27th Infantry, Company C"),
            ["Hine, Lewis"],
        )
        self.assertEqual(
            _names("Petition for Naturalization of Daniel John Mac donald"),
            ["Mac donald, Daniel John"],
        )

    def test_index_card_with_birth_year(self) -> None:
        """Verify capitalised index titles and the description's birth year."""
        found = candidates_from_record(
            {
                "title": "MacDONALD Angus Daniel",
                "scope_note": "Birth Year: 1915 Spouse: [Blank]",
            }
        )
        self.assertEqual(found[0].display(), "MacDONALD, Angus Daniel")
        self.assertEqual(found[0].birth_year, 1915)

    def test_description_full_names(self) -> None:
        """Verify "Full Name:" entries in a description are found."""
        self.assertIn(
            "MacDonald, Angus",
            _names(
                "Pension File Number 1590419",
                "The following names are included on this card: Full Name: MacDonald, "
                "Angus; Conflict: Civil War",
            ),
        )

    def test_titles_without_people(self) -> None:
        """Verify titles that name no person give no candidates."""
        self.assertEqual(_names("Tennessee SP DeVault Tavern"), [])
        self.assertEqual(_names("Von Steuben (SSBN-632) - December 1978"), [])

    def test_person_creator_with_dates(self) -> None:
        """Verify a person creator's life years are used."""
        found = candidates_from_record(
            {"title": "", "person_creators": ["Lincoln, Abraham, 1809-1865"]}
        )
        self.assertEqual(found[0].display(), "Lincoln, Abraham")
        self.assertEqual((found[0].birth_year, found[0].death_year), (1809, 1865))


class TestScoring(unittest.TestCase):
    """Test match scores."""

    def test_maiden_name_in_middle_position(self) -> None:
        """Verify a widow indexed as "Mary Kreizer Smith" matches Mary Kreizer."""
        query = MatchQuery(given="Mary", surnames=["Kreizer"])
        score, compared = score_candidate(
            query, Candidate(given="Mary", middle="Kreizer", surname="Smith")
        )
        self.assertGreaterEqual(score, 95.0)
        self.assertFalse(compared)

    def test_birth_year_fades_over_five_years(self) -> None:
        """Verify the birth year counts fully when equal and not at all past 5."""
        query = MatchQuery(given="Angus", surnames=["MacDonald"], birth_year=1890)
        same = score_candidate(query, Candidate("Angus", "", "MacDonald", 1890))[0]
        three = score_candidate(query, Candidate("Angus", "", "MacDonald", 1893))[0]
        far = score_candidate(query, Candidate("Angus", "", "MacDonald", 1915))[0]
        self.assertEqual(same, 100.0)
        self.assertGreater(same, three)
        self.assertGreater(three, far)
        self.assertAlmostEqual(far, 72.2, places=1)

    def test_initials_and_swapped_names(self) -> None:
        """Verify initials and a given name used as a middle name still score."""
        query = MatchQuery(given="John", surnames=["Smith"])
        initial = score_candidate(query, Candidate(given="J", surname="Smith"))[0]
        swapped = score_candidate(
            query, Candidate(given="Adam", middle="John", surname="Smith")
        )[0]
        other = score_candidate(query, Candidate(given="Peter", surname="Smith"))[0]
        self.assertGreater(initial, other)
        self.assertGreater(swapped, other)

    def test_best_match_and_text(self) -> None:
        """Verify the best person wins and the text says what was compared."""
        query = MatchQuery(
            given="John", middle="A", surnames=["Smith"], death_year=1864
        )
        record = {
            "title": "Approved Pension Application File for Mary Kreizer Smith, "
            "Widow of John A Smith, Company B"
        }
        result = best_match(query, record)
        assert result.candidate is not None
        self.assertEqual(result.candidate.display(), "Smith, John A")
        self.assertEqual(match_text(result), "100% (name only)")
        none = best_match(query, {"title": "Tennessee SP DeVault Tavern"})
        self.assertIsNone(none.candidate)
        self.assertEqual(match_text(none), "-")
        self.assertEqual(
            score_candidate(MatchQuery(), Candidate(given="John")), (0.0, False)
        )


if __name__ == "__main__":
    unittest.main()
