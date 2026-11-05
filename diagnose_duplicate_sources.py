#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026
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
Diagnostic script: check whether a Gramps ID (e.g. S00032) appears more than
once among the sources in a database.

Usage:
    python diagnose_duplicate_sources.py <database_directory> [gramps_id]

Example:
    python diagnose_duplicate_sources.py "C:/Users/Name/.gramps/grampsdb/familytree1" S00032

If no gramps_id is given, the script lists every source whose gramps ID appears
more than once.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

import argparse
import sys

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.generic import DBMODE_R
from gramps.gen.db.utils import make_database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check for duplicate source Gramps IDs in a database."
    )
    parser.add_argument(
        "dbdir",
        help="Path to the Gramps family tree database directory.",
    )
    parser.add_argument(
        "gramps_id",
        nargs="?",
        default=None,
        help="Specific Gramps ID to check (e.g. S00032). "
        "If omitted, all duplicate IDs are reported.",
    )
    args = parser.parse_args()

    db = make_database("sqlite")
    try:
        # Open read-only so we don't need a write lock; this works even if
        # Gramps has the database open.
        db.load(args.dbdir, mode=DBMODE_R)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"ERROR: could not open database '{args.dbdir}'")
        print(f"  Exception type: {type(exc).__name__}")
        print(f"  Exception repr: {exc!r}")
        print(f"  Exception str:  {str(exc)!r}")
        return 1

    try:
        handles = list(db.get_source_handles())
    except Exception as exc:  # pylint: disable=broad-except
        print(f"ERROR: could not read sources: {exc}")
        db.close()
        return 1

    # Build a mapping: gramps_id -> list of (handle, title)
    id_map: dict[str, list[tuple[str, str]]] = {}
    for handle in handles:
        source = db.get_source_from_handle(handle)
        if source is None:
            continue
        gid = source.get_gramps_id()
        title = source.get_title() or ""
        id_map.setdefault(gid, []).append((handle, title))

    if args.gramps_id:
        # Report only the requested ID
        entries = id_map.get(args.gramps_id, [])
        if not entries:
            print(f"Source {args.gramps_id} not found in the database.")
        else:
            print(f"Source {args.gramps_id} appears {len(entries)} time(s):")
            for handle, title in entries:
                print(f"  handle={handle}  title={title!r}")
    else:
        # Report all duplicate IDs
        duplicates = {gid: ents for gid, ents in id_map.items() if len(ents) > 1}
        if not duplicates:
            print("No duplicate source Gramps IDs found.")
        else:
            print(f"Found {len(duplicates)} duplicate source Gramps ID(s):")
            for gid in sorted(duplicates):
                ents = duplicates[gid]
                print(f"\n  {gid} appears {len(ents)} time(s):")
                for handle, title in ents:
                    print(f"    handle={handle}  title={title!r}")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
