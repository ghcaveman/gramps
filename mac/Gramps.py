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

"""Launch Gramps with resources from its py2app bundle."""

# -------------------------------------------------------------------------
#
# Python modules
#
# -------------------------------------------------------------------------
import os
from pathlib import Path
import sys

RESOURCE_DIR = Path.cwd()
SOURCE_DIR = RESOURCE_DIR / "gramps_source"
if SOURCE_DIR.is_dir():
    sys.path.insert(0, str(SOURCE_DIR))
else:
    ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(ROOT))
    RESOURCE_DIR = Path(os.environ.get("GRAMPS_RESOURCES", ROOT / "build" / "share"))

os.environ["GRAMPS_RESOURCES"] = str(RESOURCE_DIR)


def run_gramps() -> None:
    """Run the Gramps application."""
    from gramps.grampsapp import main

    main()


if __name__ == "__main__":
    run_gramps()
