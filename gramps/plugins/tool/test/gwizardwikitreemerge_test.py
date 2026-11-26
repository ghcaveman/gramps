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
import re
import unittest

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
try:
    from gramps.plugins.tool.gwizardwikitreemerge import (
        GWizardWikiTreeMergeOptions,
        GWizardWikiTreeMerge,
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
        """Verify initialization of GWizardWikiTreeMergeOptions."""
        options = GWizardWikiTreeMergeOptions("GWizard WikiTree Merge")
        self.assertEqual(options.name, "GWizard WikiTree Merge")
        self.assertIsInstance(options.options_dict, dict)
        self.assertIsInstance(options.options_help, dict)

    @unittest.skipUnless(_HAS_GTK, "GTK (gi) is required for tool classes")
    def test_tool_class_attributes(self) -> None:
        """Verify GWizardWikiTreeMerge class attributes and docstring."""
        self.assertTrue(issubclass(GWizardWikiTreeMerge, object))
        self.assertIn("GWizard WikiTree Merge", GWizardWikiTreeMerge.__doc__ or "")

    def test_tools_gpr_registration(self) -> None:
        """
        Verify the gwizardwikitree registration: tools.gpr.py in the source
        tree, or the generated GWizardWikiTreeMerge.gpr.py in the addon.
        """
        parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [
            os.path.join(parent, name)
            for name in ("tools.gpr.py", "GWizardWikiTreeMerge.gpr.py")
        ]
        existing = [path for path in candidates if os.path.isfile(path)]
        self.assertTrue(existing, "No registration file in %s" % parent)
        gpr_path = existing[0]

        with open(gpr_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn('id="gwizardwikitree"', content)
        self.assertIn('name=_("GWizard WikiTree Merge")', content)
        self.assertIn('fname="gwizardwikitreemerge.py"', content)
        self.assertIn('toolclass="GWizardWikiTreeMerge"', content)
        self.assertIn('optionclass="GWizardWikiTreeMergeOptions"', content)
        self.assertIn("category=TOOL_DBPROC", content)

    def test_addon_package_registration(self) -> None:
        """
        Verify addon_package_wikitree.toml registers the WikiTree tool, the
        Multi-Archive Record Scan and the WikiTree record source.
        """
        content = _read_config("addon_package_wikitree.toml", self)
        self.assertIn('id = "gwizardwikitree"', content)
        self.assertIn('name = "GWizard WikiTree Merge"', content)
        self.assertIn('fname = "gwizardwikitreemerge.py"', content)
        self.assertIn('toolclass = "GWizardWikiTreeMerge"', content)
        self.assertIn('optionclass = "GWizardWikiTreeMergeOptions"', content)
        self.assertEqual(
            _extra_registration_ids(content),
            ["gwizardrecordscan", "gwizardwikitreesource"],
        )


def _read_config(name: str, test: unittest.TestCase) -> str:
    """
    Return the text of a packaging config in the repository root, skipping
    the test when it is not there (the built addon does not include it).
    """
    path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", name)
    )
    if not os.path.isfile(path):
        test.skipTest("%s is only in the source tree" % name)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _extra_registration_ids(content: str) -> list[str]:
    """The id of each [[extra_registrations]] table, in order."""
    ids = []
    for section in content.split("[[extra_registrations]]")[1:]:
        match = re.search(r'^id = "([^"]+)"', section, re.MULTILINE)
        if match:
            ids.append(match.group(1))
    return ids


if __name__ == "__main__":
    unittest.main()
