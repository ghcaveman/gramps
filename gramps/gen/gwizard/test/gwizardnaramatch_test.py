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
    birth_year_from_age,
    candidates_from_record,
    in_name_range,
    jaro_winkler,
    match_text,
    name_range,
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

    def test_draft_register_titles_name_nobody(self) -> None:
        """Verify "State, 8th Congressional District, Class ..." is no name."""
        self.assertEqual(
            _names("Ohio, 8th Congressional District, Class No. 1, L-Z (Vol. 2 of 3)"),
            [],
        )
        self.assertEqual(
            _names("New York, 13th Congressional District, Class No. 2"), []
        )
        self.assertEqual(_names("Smith, John - 1942"), ["Smith, John"])

    def test_given_names_end_at_the_next_comma(self) -> None:
        """Verify ", Year: 1942" after the given names is not a middle name."""
        self.assertEqual(_names("Smith, Mary Ann, Year: 1942"), ["Smith, Mary Ann"])
        self.assertEqual(_names("Smith, Mary Ann, Year: [BLANK]"), ["Smith, Mary Ann"])

    def test_phrases_that_are_not_names(self) -> None:
        """Verify words after "Application for" must look like a name."""
        self.assertEqual(
            _names(
                "10467, John William Smith, Application for Enrollment with the "
                "California Indians"
            ),
            [],
        )
        self.assertEqual(
            _names("Approved Pension Application File for Mary Ann Smith"),
            ["Smith, Mary Ann"],
        )

    def test_age_and_year_give_a_birth_year(self) -> None:
        """Verify "Age 32, Year: 1865" titles give a birth year of 1833."""
        found = candidates_from_record(
            {"title": "Smith, John - Age 32, Year: 1865 - First Cavalry"}
        )
        self.assertEqual(found[0].display(), "Smith, John")
        self.assertEqual(found[0].birth_year, 1833)
        self.assertIsNone(
            birth_year_from_age("Smith, John - Age [Blank], Year: [Blank] - Roll")
        )
        self.assertIsNone(birth_year_from_age("Smith, John - Year: 1865"))

    def test_index_card_ranges(self) -> None:
        """Verify "Smith, Ann - Smithers, Paul (2 of 3)" is a range, not a person."""
        title = "Smith, Ann - Smithers, Paul S. (2 of 3)"
        self.assertEqual(_names(title), [])
        inside = MatchQuery(given="Mary", surnames=["Smith"], birth_year=1845)
        before = MatchQuery(given="Aaron", surnames=["Smith"])
        after = MatchQuery(given="Mary", surnames=["Smythe"])
        self.assertTrue(in_name_range(inside, title))
        self.assertFalse(in_name_range(before, title))
        self.assertFalse(in_name_range(after, title))
        result = best_match(inside, {"title": title})
        self.assertEqual(match_text(result), "in range")
        self.assertEqual(result.score, 50.0)
        self.assertEqual(result.candidate.display(), "Smith, Ann ... Smithers, Paul S")
        self.assertEqual(match_text(best_match(before, {"title": title})), "-")
        # A married surname counts too.
        married = MatchQuery(given="Mary", surnames=["Jones", "Smith"])
        self.assertTrue(in_name_range(married, title))
        # Not ranges: a name and a place, a name and a regiment.
        self.assertIsNone(name_range("Smith, Mary - New York - 1848 - File No. W271"))
        self.assertIsNone(name_range("Smith, John - 27th Infantry, Company C"))

    def test_service_file_titles(self) -> None:
        """Verify Navy service-file titles, surname first before " -- "."""
        self.assertEqual(
            _names("Smith John William -- [Service Number] 0011712 -- [Box 12]"),
            ["Smith, John William"],
        )
        self.assertEqual(
            _names("Smith John -- [Service Number] 0011712"), ["Smith, John"]
        )
        self.assertEqual(_names("Muster Rolls -- [Box 12] 1918"), [])

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
        """
        Verify the birth year counts fully when equal, not at all past 5
        years, and halves the score past 10 (a different person).
        """
        query = MatchQuery(given="Angus", surnames=["MacDonald"], birth_year=1890)
        same = score_candidate(query, Candidate("Angus", "", "MacDonald", 1890))[0]
        three = score_candidate(query, Candidate("Angus", "", "MacDonald", 1893))[0]
        eight = score_candidate(query, Candidate("Angus", "", "MacDonald", 1898))[0]
        far = score_candidate(query, Candidate("Angus", "", "MacDonald", 1915))[0]
        self.assertEqual(same, 100.0)
        self.assertGreater(same, three)
        self.assertGreater(three, eight)
        self.assertAlmostEqual(eight, 72.2, places=1)
        self.assertAlmostEqual(far, 36.1, places=1)

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
