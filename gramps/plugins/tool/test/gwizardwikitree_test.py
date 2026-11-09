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

"""Unittests for the GWizard WikiTree merge tool plugin."""

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
    from gramps.plugins.tool.gwizardwikitree import (
        GWizardWikiTreeMergeToolOptions,
        GWizardWikiTreeMergeTool,
    )

    _HAS_GTK = True
except (ImportError, ModuleNotFoundError):
    _HAS_GTK = False


# ------------------------------------------------------------------
#
# GWizardWikiTreeToolTest
#
# ------------------------------------------------------------------
class GWizardWikiTreeToolTest(unittest.TestCase):
    """Test the GWizard WikiTree merge tool options and registration."""

    @unittest.skipUnless(_HAS_GTK, "GTK (gi) is required for tool classes")
    def test_tool_options_init(self) -> None:
        """Verify initialization of GWizardWikiTreeMergeToolOptions."""
        options = GWizardWikiTreeMergeToolOptions("GWizard WikiTree Merge")
        self.assertEqual(options.name, "GWizard WikiTree Merge")
        self.assertIsInstance(options.options_dict, dict)
        self.assertIsInstance(options.options_help, dict)

    @unittest.skipUnless(_HAS_GTK, "GTK (gi) is required for tool classes")
    def test_tool_class_attributes(self) -> None:
        """Verify GWizardWikiTreeMergeTool class attributes and docstring."""
        self.assertTrue(issubclass(GWizardWikiTreeMergeTool, object))
        self.assertIn("GWizard WikiTree Merge", GWizardWikiTreeMergeTool.__doc__ or "")

    def test_tools_gpr_registration(self) -> None:
        """Verify gwizardwikitree tool registration entry in tools.gpr.py."""
        gpr_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "tools.gpr.py"
        )
        self.assertTrue(os.path.isfile(gpr_path))

        with open(gpr_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn('id="gwizardwikitree"', content)
        self.assertIn('name=_("GWizard WikiTree Merge")', content)
        self.assertIn('fname="gwizardwikitree.py"', content)
        self.assertIn('toolclass="GWizardWikiTreeMergeTool"', content)
        self.assertIn('optionclass="GWizardWikiTreeMergeToolOptions"', content)
        self.assertIn("category=TOOL_DBPROC", content)


if __name__ == "__main__":
    unittest.main()
