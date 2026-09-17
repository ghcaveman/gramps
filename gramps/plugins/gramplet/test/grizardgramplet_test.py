#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Brian Caudill
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

"""Unittests for Grizard gramplet helper functions."""

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
from gramps.plugins.gramplet.grizardgramplet import (
    build_status_text,
    clamp_threshold,
    format_candidate_label,
)


# ------------------------------------------------------------------
#
# GrizardGrampletHelperTest
#
# ------------------------------------------------------------------
class GrizardGrampletHelperTest(unittest.TestCase):
    """Test the GTK-free helpers used by the Grizard gramplet."""

    def test_format_candidate_label_with_birth(self) -> None:
        """A candidate with name, year and score formats fully."""
        label = format_candidate_label(
            {"name": "John Smith", "birth_year": "1901", "score": 2.5}
        )
        self.assertEqual(label, "John Smith (b. 1901) [2.50]")

    def test_format_candidate_label_without_birth(self) -> None:
        """A candidate without a birth year omits the birth part."""
        label = format_candidate_label({"name": "Jane Doe", "score": 1.0})
        self.assertEqual(label, "Jane Doe [1.00]")

    def test_build_status_text_without_path(self) -> None:
        """No path produces the empty-state prompt."""
        self.assertIn("GEDCOM", build_status_text(None, 0, 0))

    def test_build_status_text_with_counts(self) -> None:
        """Loaded files report counts and the active name."""
        text = build_status_text("/tmp/test.ged", 10, 3, "John Smith")
        self.assertIn("10", text)
        self.assertIn("3", text)
        self.assertIn("John Smith", text)

    def test_clamp_threshold_bounds(self) -> None:
        """Thresholds clamp into range with a sane fallback."""
        self.assertEqual(clamp_threshold(1.5), 1.5)
        self.assertEqual(clamp_threshold(99.0), 4.0)
        self.assertEqual(clamp_threshold(-1.0), 0.0)
        self.assertEqual(clamp_threshold("bad"), 0.5)


if __name__ == "__main__":
    unittest.main()
