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

"""GWizard tool tests.

To test an add-on copy of the GWizard tools instead of the ones in this
tree, set ``GWIZARD_PLUGIN_DIR`` to the folder that holds the add-on's
``.py`` files. Its modules are then found first as ``gramps.plugins.tool.*``.
"""

import os

import gramps.plugins.tool as _tool_package

_PLUGIN_DIR = os.environ.get("GWIZARD_PLUGIN_DIR", "")
if _PLUGIN_DIR and _PLUGIN_DIR not in _tool_package.__path__:
    _tool_package.__path__.insert(0, _PLUGIN_DIR)
