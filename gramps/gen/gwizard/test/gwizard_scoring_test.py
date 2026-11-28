#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026       GWizard contributors
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
Tests for the shared record score (gwizard_base.score_record): different
given names and clearly wrong years must pull the score down.
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
from gramps.gen.gwizard.gwizard_base import (
    RecordCandidate,
    RecordQuery,
    score_record,
    sharpened,
    year_range,
)


def _score(
    query: RecordQuery,
    given: str,
    surname: str,
    birth: int | None = None,
    death: int | None = None,
    gender: str = "",
) -> float:
    """Return the score of one candidate."""
    candidate = RecordCandidate(
        given=given,
        surnames=[surname],
        birth_years=year_range(birth),
        death_years=year_range(death),
        gender=gender,
    )
    return score_record(query, candidate).score


class SharpenedTest(unittest.TestCase):
    """Name similarity credit."""

    def test_curve(self) -> None:
        """Full credit from 0.9 up, falling to nothing at 0.6."""
        self.assertEqual(sharpened(1.0), 1.0)
        self.assertEqual(sharpened(0.95), 0.95)
        self.assertAlmostEqual(sharpened(0.9), 0.9)
        self.assertAlmostEqual(sharpened(0.75), 0.45)
        self.assertEqual(sharpened(0.6), 0.0)
        self.assertEqual(sharpened(0.3), 0.0)


class ScoreTest(unittest.TestCase):
    """Whole-record scores."""

    def setUp(self) -> None:
        self.query = RecordQuery(
            given="Mary", surnames=["Smith"], birth_year=1845, death_year=1927
        )

    def test_same_person(self) -> None:
        """A full match scores 100, and a spelling variant stays high."""
        self.assertEqual(_score(self.query, "Mary", "Smith", 1845, 1927), 100.0)
        self.assertGreater(_score(self.query, "Marie", "Smith", 1845, 1927), 95.0)

    def test_different_given_name(self) -> None:
        """Another given name with the same surname is not a near match."""
        name_only = RecordQuery(given="Mary", surnames=["Smith"])
        self.assertLess(_score(name_only, "Edward", "Smith"), 60.0)

    def test_birth_years_far_apart_halve_the_score(self) -> None:
        """Up to 10 years apart loses the birth credit; past 10 halves it."""
        query = RecordQuery(given="John", surnames=["Smith"], birth_year=1855)
        eight = _score(query, "John", "Smith", 1863)
        far = _score(query, "John", "Smith", 1833)
        self.assertAlmostEqual(eight, 65 / 90 * 100, places=1)
        self.assertAlmostEqual(far, 65 / 90 * 100 / 2, places=1)

    def test_death_years_far_apart_halve_the_score(self) -> None:
        """Death years more than 5 apart halve the score."""
        query = RecordQuery(given="John", surnames=["Smith"], death_year=1910)
        self.assertAlmostEqual(
            _score(query, "John", "Smith", death=1918), 65 / 75 * 100 / 2, places=1
        )

    def test_wrong_years_and_gender_combine(self) -> None:
        """Wrong years and a wrong gender each halve the score."""
        query = RecordQuery(
            given="John", surnames=["Smith"], birth_year=1855, gender="male"
        )
        self.assertAlmostEqual(
            _score(query, "John", "Smith", 1833, gender="female"),
            65 / 90 * 100 / 4,
            places=1,
        )


if __name__ == "__main__":
    unittest.main()
