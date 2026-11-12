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

"""Build the standalone ``MediaFix.zip`` addon package.

This script mirrors ``package_gwizard_filemerge.py`` but bundles the
media‑fix related tools listed in ``changed_files.txt``.  It collects the
relevant source modules, rewrites their imports to flat sibling imports, and
produces a zip file that can be installed as a Gramps addon.
"""

# -------------------------------------------------------------------------
# Standard Python modules
# -------------------------------------------------------------------------
from __future__ import annotations
import argparse
import logging
import re
import zipfile
from pathlib import Path

LOG = logging.getLogger(__name__)

PACKAGE = "MediaFix"
GPR_FILENAME = "MediaFix.gpr.py"

# Minimal registration template – the real plugin registration is already
# present in ``gramps/plugins/tool/tools.gpr.py``; we embed a tiny stub that
# points to the main tool module.
GPR_TEMPLATE = """\
# Gramps registration file for the MediaFix tool.

from gramps.gen.plug._pluginreg import TOOL, TOOL_DBPROC, TOOL_MODE_GUI, EXPERIMENTAL, EXPERT
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.version import major_version, VERSION_TUPLE

_ = glocale.translation.gettext

if (5, 2, 0) <= VERSION_TUPLE <= (6, 2, 0):
    register(
        TOOL,
        id="gwizardmediafix",
        name=_("Media Fix"),
        description=_("Fix media references in a Gramps database."),
        version="__MEDIAFIX_VERSION__",
        gramps_target_version=major_version,
        status=EXPERIMENTAL,
        audience=EXPERT,
        fname="gwizardmediafix.py",
        authors=["Kevin White"],
        authors_email=["gocaveman@gmail.com"],
        category=TOOL_DBPROC,
        toolclass="GWizardMediaFixTool",
        optionclass="GWizardMediaFixOptions",
        tool_modes=[TOOL_MODE_GUI],
    )
"""

# Map of archive member name -> source file relative to the repo root.
SOURCES: dict[str, str] = {
    "gwizardmediafix.py": "gramps/plugins/tool/gwizardmediafix.py",
    "gwizard_common.py": "gramps/plugins/tool/gwizard_common.py",
    "gw_fixmediareferencesdialog.py": "gramps/plugins/tool/gw_fixmediareferencesdialog.py",
}

# Simple import rewrite rules – flatten imports from ``gramps.plugins.tool``
REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"from\s+gramps\.plugins\.tool\.gwizardmediafix\s+import\b"),
        "from gwizardmediafix import",
    ),
    (
        re.compile(r"from\s+gramps\.plugins\.tool\.gwizard_common\s+import\b"),
        "from gwizard_common import",
    ),
    (
        re.compile(
            r"from\s+gramps\.plugins\.tool\.gw_fixmediareferencesdialog\s+import\b"
        ),
        "from gw_fixmediareferencesdialog import",
    ),
    (
        re.compile(
            r"from\s+\.+(gwizardmediafix|gwizard_common|gw_fixmediareferencesdialog)\s+import\b"
        ),
        r"from \1 import",
    ),
)


def rewrite_imports(text: str) -> str:
    """Rewrite plugin imports to flat sibling imports."""
    for pattern, replacement in REWRITES:
        text = pattern.sub(replacement, text)
    return text


def rewrite_imports_bytes(data: bytes) -> bytes:
    lines = data.decode("utf-8").splitlines(keepends=False)
    rewritten = [rewrite_imports(line) for line in lines]
    return ("\n".join(rewritten) + "\n").encode("utf-8")


def build_gpr(version: str = "0.0.1") -> bytes:
    return GPR_TEMPLATE.replace("__MEDIAFIX_VERSION__", version).encode("utf-8")


def build_zip(repo_root: Path, output: Path, version: str = "0.0.1") -> Path:
    """Create the addon zip file.

    Returns the path to the created zip.  Raises ``FileNotFoundError`` if any
    source file is missing.
    """
    members: dict[str, bytes] = {}
    for member, source in SOURCES.items():
        path = repo_root / source
        if not path.is_file():
            raise FileNotFoundError(f"Missing source file: {path}")
        members[member] = rewrite_imports_bytes(path.read_bytes())
        LOG.debug("Added %s (%d bytes)", source, len(members[member]))

    # Ensure a clean slate.
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PACKAGE + "/", b"")
        archive.writestr(f"{PACKAGE}/{GPR_FILENAME}", build_gpr(version))
        for member in sorted(members):
            archive.writestr(f"{PACKAGE}/{member}", members[member])

    LOG.info("Successfully wrote %s (%d bytes)", output, output.stat().st_size)
    print(f"✅ Built addon zip: {output} ({output.stat().st_size} bytes)")
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the MediaFix addon zip.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Destination zip file (default: MediaFix_v<version>.zip next to script).",
    )
    parser.add_argument(
        "--version",
        dest="version_opt",
        default="0.0.1",
        help="MediaFix plugin version (default: 0.0.1).",
    )
    parser.add_argument(
        "version_pos",
        nargs="?",
        default=None,
        help="Positional version overrides --version.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output (debug logging).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Configure logging based on the verbose flag.
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    # args already parsed above
    repo_root = Path(__file__).resolve().parent
    version = args.version_pos if args.version_pos is not None else args.version_opt
    output = (
        repo_root / f"MediaFix_v{version}.zip"
        if args.output is None
        else (args.output if args.output.is_absolute() else repo_root / args.output)
    )
    try:
        built = build_zip(repo_root, output, version)
    except FileNotFoundError as err:
        LOG.error("Error: %s", err)
        print(f"❌ Build failed: {err}")
        return 1
    # The build_zip function already prints a success line.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
