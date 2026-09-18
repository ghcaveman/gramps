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

"""Unittests for Grizard merge tool helper functions."""

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
from gramps.plugins.tool.grizardmerge import (
    build_candidate_label,
    clamp_threshold,
    resolve_compare_pair,
)


# ------------------------------------------------------------------
#
# GrizardMergeToolHelperTest
#
# ------------------------------------------------------------------
class GrizardMergeToolHelperTest(unittest.TestCase):
    """Test the GTK-free helpers used by the Grizard merge tool."""

    def test_build_candidate_label_with_birth(self) -> None:
        """A candidate with name, year and score formats fully."""
        label = build_candidate_label(
            {"name": "John Smith", "birth_year": "1901", "score": 0.75}
        )
        self.assertEqual(label, "John Smith (b. 1901) [0.75]")

    def test_build_candidate_label_without_birth(self) -> None:
        """A candidate without a birth year omits the birth part."""
        label = build_candidate_label({"name": "Jane Doe", "score": 1.0})
        self.assertEqual(label, "Jane Doe [1.00]")

    def test_build_candidate_label_bad_score(self) -> None:
        """A non-numeric score renders as unknown."""
        label = build_candidate_label({"name": "Jane Doe", "score": "bad"})
        self.assertEqual(label, "Jane Doe [?]")

    def test_clamp_threshold_bounds(self) -> None:
        """Thresholds clamp into the 0.0-1.0 range with a sane fallback."""
        self.assertEqual(clamp_threshold(1.5), 1.0)
        self.assertEqual(clamp_threshold(99.0), 1.0)
        self.assertEqual(clamp_threshold(-1.0), 0.0)
        self.assertEqual(clamp_threshold(0.75), 0.75)
        self.assertEqual(clamp_threshold("bad"), 0.5)

    def test_resolve_compare_pair_selected(self) -> None:
        """Selected row target is used for the compare pair."""
        candidates = [{"handle": "t1", "score": 2.0}, {"handle": "t2"}]
        self.assertEqual(resolve_compare_pair(candidates, "s1", "t2"), ("s1", "t2"))

    def test_resolve_compare_pair_fallback_first(self) -> None:
        """No selection falls back to the top candidate."""
        candidates = [{"handle": "t1", "score": 2.0}]
        self.assertEqual(resolve_compare_pair(candidates, "s1", None), ("s1", "t1"))

    def test_resolve_compare_pair_add_as_new(self) -> None:
        """No candidates means Add-as-New with a None target."""
        self.assertEqual(resolve_compare_pair([], "s1", None), ("s1", None))

    def test_resolve_compare_pair_no_source(self) -> None:
        """No source handle resolves to an empty pair."""
        self.assertEqual(
            resolve_compare_pair([{"handle": "t1"}], None, "t1"), (None, None)
        )


if __name__ == "__main__":
    unittest.main()
