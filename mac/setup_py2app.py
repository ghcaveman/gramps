#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Gramps Development Team
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
# along with this program; if not, see <https://www.gnu.org/licenses/>.

"""py2app configuration for the macOS Gramps application."""

# -------------------------------------------------------------------------
#
# Python modules
#
# -------------------------------------------------------------------------
from pathlib import Path
import sys

# -------------------------------------------------------------------------
#
# Build modules
#
# -------------------------------------------------------------------------
from setuptools import setup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OPTIONS = {
    "iconfile": str(ROOT / "mac" / "gramps.icns"),
    "packages": ["gramps"],
    "resources": [
        str(ROOT / "build" / "share" / "doc"),
        str(ROOT / "build" / "share" / "gramps"),
        str(ROOT / "build" / "share" / "locale"),
    ],
    "plist": {
        "CFBundleIdentifier": "org.gramps-project.gramps",
        "CFBundleName": "Gramps",
    },
}

setup(
    name="Gramps",
    app=[str(ROOT / "mac" / "Gramps.py")],
    options={"py2app": OPTIONS},
)
