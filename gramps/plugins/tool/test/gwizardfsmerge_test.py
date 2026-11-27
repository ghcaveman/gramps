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

"""Unittests for the GWizard FamilySearch merge tool plugin."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
import unittest

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
try:
    from gramps.plugins.tool.gwizardfsmerge import (
        GWizardFamilySearchMergeOptions,
        GWizardFamilySearchMerge,
    )

    _HAS_GTK = True
except (ImportError, ModuleNotFoundError):
    _HAS_GTK = False


# ------------------------------------------------------------------
#
# GWizardFamilySearchToolTest
#
# ------------------------------------------------------------------
class GWizardFamilySearchToolTest(unittest.TestCase):
    """Test the GWizard FamilySearch merge tool options and registration."""

    @unittest.skipUnless(_HAS_GTK, "GTK (gi) is required for tool classes")
    def test_tool_options_init(self) -> None:
        """Verify initialization of GWizardFamilySearchMergeOptions."""
        options = GWizardFamilySearchMergeOptions("GWizard FamilySearch Merge")
        self.assertEqual(options.name, "GWizard FamilySearch Merge")
        self.assertIsInstance(options.options_dict, dict)
        self.assertIsInstance(options.options_help, dict)

    @unittest.skipUnless(_HAS_GTK, "GTK (gi) is required for tool classes")
    def test_tool_class_attributes(self) -> None:
        """Verify GWizardFamilySearchMerge class attributes and docstring."""
        self.assertTrue(issubclass(GWizardFamilySearchMerge, object))
        self.assertIn(
            "GWizard FamilySearch Merge", GWizardFamilySearchMerge.__doc__ or ""
        )

    def test_tools_gpr_registration(self) -> None:
        """Verify the gwizardfsmerge and gwizardfssource registrations in tools.gpr.py."""
        parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        gpr_path = os.path.join(parent, "tools.gpr.py")
        if not os.path.isfile(gpr_path):
            self.skipTest("no tools.gpr.py next to the tool (addon layout)")

        with open(gpr_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        # Tool registration
        self.assertIn('id="gwizardfsmerge"', content)
        self.assertIn('name=_("GWizard FamilySearch Merge")', content)
        self.assertIn('fname="gwizardfsmerge.py"', content)
        self.assertIn('toolclass="GWizardFamilySearchMerge"', content)
        self.assertIn('optionclass="GWizardFamilySearchMergeOptions"', content)
        self.assertIn("category=TOOL_DBPROC", content)

        # Record source registration
        self.assertIn('id="gwizardfssource"', content)
        self.assertIn('name=_("GWizard FamilySearch record source")', content)
        self.assertIn('fname="gwizardfssource.py"', content)
        self.assertIn('category="GWizardRecordSource"', content)


if __name__ == "__main__":
    unittest.main()
