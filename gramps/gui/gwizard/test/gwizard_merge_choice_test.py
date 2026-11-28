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
Tests for the merge window's "=>" choice buttons (run without a display).
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog


class MergeChoiceTest(unittest.TestCase):
    """A choice made by mistake can be taken back with another click."""

    def setUp(self) -> None:
        self.dialog = SimpleNamespace(_resolutions={})
        self.button = Mock()

    def click(self, key: str, alternate: bool = False) -> None:
        GWizardMergeDialog.cb_field_clicked(
            self.dialog, self.button, key, alternate  # type: ignore[arg-type]
        )

    def test_second_click_keeps_tree_value(self) -> None:
        """Click once to take the incoming value, again to keep the tree's."""
        self.click("gender")
        self.assertEqual(self.dialog._resolutions, {"gender": "source"})
        self.button.set_label.assert_called_with("✓")
        self.click("gender")
        self.assertEqual(self.dialog._resolutions, {})
        self.button.set_label.assert_called_with("=>")
        self.button.set_sensitive.assert_not_called()

    def test_event_buttons_still_cycle(self) -> None:
        """Birth and death cycle merge, +ALT, keep tree value."""
        self.click("birth_event", alternate=True)
        self.assertEqual(self.dialog._resolutions, {"birth_event": "source"})
        self.click("birth_event", alternate=True)
        self.assertEqual(self.dialog._resolutions, {"birth_event": "alternate"})
        self.click("birth_event", alternate=True)
        self.assertEqual(self.dialog._resolutions, {})


if __name__ == "__main__":
    unittest.main()
