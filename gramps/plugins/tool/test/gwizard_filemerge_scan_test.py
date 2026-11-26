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

"""Unit tests for the GWizard Multi-Archive Record Scan tool registration."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
import unittest

_TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------
#
# GWizardRecordScanToolTest
#
# ------------------------------------------------------------------
class GWizardRecordScanToolTest(unittest.TestCase):
    """The tool module and its registration."""

    def test_module_defines_tool_classes(self) -> None:
        """The module names the tool and options classes it registers."""
        path = os.path.join(_TOOL_DIR, "gwizard_filemerge_scan.py")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("class GWizardRecordScan(tool.Tool)", content)
        self.assertIn("class GWizardRecordScanOptions(tool.ToolOptions)", content)

    def test_tools_gpr_registration(self) -> None:
        """
        tools.gpr.py registers the Record Scan correctly, where it does.

        The tool code lives in gwizard_filemerge, but only the record-source
        branches (WikiTree, NARA, FamilySearch) register its menu entry, so
        in gwizard_filemerge itself there is nothing to check.
        """
        path = os.path.join(_TOOL_DIR, "tools.gpr.py")
        if not os.path.isfile(path):
            self.skipTest("no tools.gpr.py next to the tool (addon layout)")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        if 'id="gwizardrecordscan"' not in content:
            self.skipTest("registered by the record-source branches")
        self.assertIn('fname="gwizard_filemerge_scan.py"', content)
        self.assertIn('toolclass="GWizardRecordScan"', content)


if __name__ == "__main__":
    unittest.main()
