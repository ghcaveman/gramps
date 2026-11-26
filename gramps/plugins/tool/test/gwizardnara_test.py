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

"""Unittests for the GWizard NARA merge tool plugin."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
import re
import unittest

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
try:
    from gramps.plugins.tool.gwizardnara import (
        GWizardNaraMergeOptions,
        GWizardNaraMerge,
    )

    _HAS_GTK = True
except (ImportError, ModuleNotFoundError):
    _HAS_GTK = False


# ------------------------------------------------------------------
#
# GWizardNaraToolTest
#
# ------------------------------------------------------------------
class GWizardNaraToolTest(unittest.TestCase):
    """Test the GWizard NARA merge tool options and registration."""

    @unittest.skipUnless(_HAS_GTK, "GTK (gi) is required for tool classes")
    def test_tool_options_init(self) -> None:
        """Verify initialization of GWizardNaraMergeOptions."""
        options = GWizardNaraMergeOptions("GWizard NARA Merge")
        self.assertEqual(options.name, "GWizard NARA Merge")
        self.assertIsInstance(options.options_dict, dict)
        self.assertIsInstance(options.options_help, dict)

    @unittest.skipUnless(_HAS_GTK, "GTK (gi) is required for tool classes")
    def test_tool_class_attributes(self) -> None:
        """Verify GWizardNaraMerge class attributes and docstring."""
        self.assertTrue(issubclass(GWizardNaraMerge, object))
        self.assertIn("GWizard NARA Merge", GWizardNaraMerge.__doc__ or "")

    def test_tools_gpr_registration(self) -> None:
        """
        Verify the gwizardnara registration: tools.gpr.py in the source
        tree, or the generated GWizardNaraMerge.gpr.py in the addon.
        """
        parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [
            os.path.join(parent, name)
            for name in ("tools.gpr.py", "GWizardNaraMerge.gpr.py")
        ]
        existing = [path for path in candidates if os.path.isfile(path)]
        self.assertTrue(existing, "No registration file in %s" % parent)
        with open(existing[0], "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn('id="gwizardnara"', content)
        self.assertIn('name=_("GWizard NARA Merge")', content)
        self.assertIn('fname="gwizardnara.py"', content)
        self.assertIn('toolclass="GWizardNaraMerge"', content)
        self.assertIn('optionclass="GWizardNaraMergeOptions"', content)

    def test_addon_package_registration(self) -> None:
        """
        Verify addon_package_nara.toml registers the NARA tool, the
        Multi-Archive Record Scan and the NARA record source.
        """
        path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "..",
                "addon_package_nara.toml",
            )
        )
        if not os.path.isfile(path):
            self.skipTest("addon_package_nara.toml is only in the source tree")
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn('id = "gwizardnara"', content)
        self.assertIn('name = "GWizard NARA Merge"', content)
        self.assertIn('fname = "gwizardnara.py"', content)
        self.assertIn('toolclass = "GWizardNaraMerge"', content)
        self.assertIn('optionclass = "GWizardNaraMergeOptions"', content)
        ids = []
        for section in content.split("[[extra_registrations]]")[1:]:
            match = re.search(r'^id = "([^"]+)"', section, re.MULTILINE)
            if match:
                ids.append(match.group(1))
        self.assertEqual(ids, ["gwizardrecordscan", "gwizardnarasource"])


if __name__ == "__main__":
    unittest.main()
