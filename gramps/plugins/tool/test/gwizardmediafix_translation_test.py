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

"""GWizard Media Fix uses the addon's own translations.

As an addon, each module must translate through
``glocale.get_addon_translator(__file__)`` so the ``locale/`` folder shipped
with the addon is used (falling back to Gramps' own catalogue); as a
built-in tool the same call simply uses Gramps' catalogue.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.plugins.tool.test import gwizard_gtk_fakes as fakes

fakes.install()

from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.plugins.tool import gw_fixmediareferencesdialog as refs
from gramps.plugins.tool import gw_mediapreview as preview
from gramps.plugins.tool import gwizard_common as common
from gramps.plugins.tool import gwizardmediafix as mediafix

MODULES = (mediafix, refs, common, preview)


def setUpModule() -> None:
    """Install the GTK fakes for this module's tests."""
    fakes.install()


def tearDownModule() -> None:
    """Restore the real GTK classes for other test modules."""
    fakes.uninstall()


def load_copy(path: str, name: str) -> ModuleType:
    """Import a copy of a module file under another name."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


class AddonTranslatorTest(unittest.TestCase):
    """Every GWizard Media Fix module translates through the addon translator."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        # An addon package folder with a copy of the shared module in it.
        self.copy = os.path.join(self.tmp, "MediaFix", "gwizard_common.py")
        os.makedirs(os.path.dirname(self.copy))
        shutil.copy(common.__file__, self.copy)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_modules_bind_their_translator(self) -> None:
        """``_`` (and ``ngettext`` where used) come from the module's translator."""
        for module in MODULES:
            with self.subTest(module=module.__name__):
                self.assertTrue(hasattr(module, "_trans"))
                self.assertIs(module._.__self__, module._trans)
                if hasattr(module, "ngettext"):
                    self.assertIs(module.ngettext.__self__, module._trans)

    def test_addon_folder_translation_is_used(self) -> None:
        """The translator is asked for the module's own folder, and is used."""
        translator = MagicMock()
        translator.sgettext.side_effect = lambda text: "[fr] " + text
        with patch.object(
            glocale, "get_addon_translator", return_value=translator
        ) as get_translator:
            module = load_copy(self.copy, "gwizard_common_addon_copy")
        get_translator.assert_called_once_with(self.copy)
        self.assertIs(module._trans, translator)
        self.assertEqual(module._("Hello"), "[fr] Hello")

    def test_falls_back_to_gramps_translation(self) -> None:
        """When the addon has no usable translation, Gramps' own is used."""
        with patch.object(glocale, "get_addon_translator", side_effect=ValueError):
            module = load_copy(self.copy, "gwizard_common_no_locale")
        self.assertIs(module._trans, glocale.translation)

    def test_no_module_uses_gramps_translation_directly(self) -> None:
        """The old ``glocale.translation.sgettext`` binding does not come back."""
        direct = re.compile(r"^\s*(_|ngettext)\s*=\s*glocale\.translation\.", re.M)
        for module in MODULES:
            with self.subTest(module=module.__name__):
                assert module.__file__ is not None
                with open(module.__file__, encoding="utf-8") as handle:
                    source = handle.read()
                self.assertIn("glocale.get_addon_translator(__file__)", source)
                self.assertIsNone(direct.search(source))


fakes.uninstall()

if __name__ == "__main__":
    unittest.main()
