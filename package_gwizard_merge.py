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

"""Build the standalone ``GWizardMerge.zip`` addon package.

Collects the GWizard backend, GUI, and tool modules scattered across
``gramps/gen/gwizard``, ``gramps/gui/gwizard``, and ``gramps/plugins/tool``
into a single flat ``GWizardDataMerge/`` addon directory inside a zip file,
rewriting the ``gramps.gen.gwizard`` / ``gramps.gui.gwizard`` absolute
imports and intra-package relative imports to flat sibling imports so the
bundle loads under Gramps' plugin importer (which imports the tool module
top-level via ``__import__`` with the addon directory on ``sys.path``).
Also embeds the standalone addon registration file
``GWizardDataMerge/GWizardDataMerge.gpr.py`` (mirroring the ``gwizardmerge``
entry in ``gramps/plugins/tool/tools.gpr.py``). Newlines are normalized to
LF so the output is identical regardless of the checkout's line-ending
setting.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import argparse
import logging
import re
import zipfile
from pathlib import Path

LOG = logging.getLogger(__name__)

PACKAGE = "GWizardDataMerge"

GPR_FILENAME = "GWizardDataMerge.gpr.py"

# Standalone addon registration file, written into the bundle as
# ``GWizardDataMerge/GWizardDataMerge.gpr.py``. Mirrors the template in
# ``GWizardDataMerge.gpr.py`` at the repo root: version-gated with
# ``VERSION_TUPLE``, ``EXPERIMENTAL`` status and ``EXPERT`` audience, dynamic
# ``gramps_target_version``, forum ``help_url``, and the full side-by-side
# description. No formatting placeholders: the template is emitted verbatim
# so the root file stays the single source of truth for registration content.
GPR_TEMPLATE = """\
# Gramps registration file for the GWizard Data Merge tool.

from gramps.gen.plug._pluginreg import (
    TOOL,
    TOOL_DBPROC,
    TOOL_MODE_GUI,
    EXPERIMENTAL,
    EXPERT,
)
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.version import major_version, VERSION_TUPLE

_ = glocale.translation.gettext

if (5, 2, 0) <= VERSION_TUPLE <= (6, 2, 0):
    register(
        TOOL,
        id="gwizardmerge",
        name=_("GWizard Data Merge"),
        description=_(
            "Family Tree Processing Tool to compare another genealogy file "
            "(GEDCOM, Gramps XML, ...) side-by-side with the open Family Tree "
            "and merge selected differences person by person."
        ),
        version="0.0.1",
        gramps_target_version=major_version,
        status=EXPERIMENTAL,
        audience=EXPERT,
        fname="gwizardmerge.py",
        authors=["Kevin White"],
        authors_email=["gocaveman@gmail.com"],
        category=TOOL_DBPROC,
        toolclass="GWizardMergeTool",
        optionclass="GWizardMergeToolOptions",
        tool_modes=[TOOL_MODE_GUI],
        help_url=("https://gramps.discourse.group/t/10027")
    )
"""

DEFAULT_GRAMPS_TARGET = "6.0"

# Map of archive member name -> source file relative to the repo root.
SOURCES: dict[str, str] = {
    "gwizardgedcom.py": "gramps/gen/gwizard/gwizardgedcom.py",
    "gwizard.py": "gramps/gen/gwizard/gwizard.py",
    "gwizardcompare.py": "gramps/gui/gwizard/gwizardcompare.py",
    "gwizardlauncher.py": "gramps/gui/gwizard/gwizardlauncher.py",
    "gwizardmerge.py": "gramps/plugins/tool/gwizardmerge.py",
    "gwizardmergedialog.py": "gramps/gui/gwizard/gwizardmergedialog.py",
}

# GWizard sibling modules bundled flat in the addon directory. Gramps loads
# the tool module top-level (``__import__("gwizardmerge")`` with the addon
# directory on ``sys.path``), so intra-bundle imports must be flat as well:
# both ``gramps.gen.gwizard.X`` / ``gramps.gui.gwizard.X`` absolute imports
# and ``.X`` relative imports become ``X`` sibling imports.
SIBLINGS = (
    "gwizardgedcom",
    "gwizard",
    "gwizardcompare",
    "gwizardlauncher",
    "gwizardmerge",
    "gwizardmergedialog",
)

# Absolute imports that must become flat sibling imports in the bundle.
# Order matters: longest prefixes first.
REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"from\s+gramps\.gen\.gwizard\.gwizardgedcom\s+import\b"),
        "from gwizardgedcom import",
    ),
    (
        re.compile(r"from\s+gramps\.gen\.gwizard\.gwizard\s+import\b"),
        "from gwizard import",
    ),
    (
        re.compile(r"from\s+gramps\.gui\.gwizard\.gwizardcompare\s+import\b"),
        "from gwizardcompare import",
    ),
    (
        re.compile(
            r"from\s+gramps\.gui\.gwizard\.gwizardlauncher\s+import\b" r"(?!\s*\()",
        ),
        "from gwizardlauncher import",
    ),
    (
        re.compile(r"from\s+gramps\.gui\.gwizard\.gwizardmergedialog\s+import\b"),
        "from gwizardmergedialog import",
    ),
    (
        re.compile(
            r"from\s+\.(gwizardgedcom|gwizard|gwizardcompare|gwizardlauncher|"
            r"gwizardmerge|gwizardmergedialog)\s+import\b"
        ),
        r"from \1 import",
    ),
)


def rewrite_imports(text: str) -> str:
    """Rewrite GWizard imports to flat sibling imports."""
    for pattern, replacement in REWRITES:
        text = pattern.sub(replacement, text)
    return text


def rewrite_imports_bytes(data: bytes) -> bytes:
    """Rewrite GWizard imports, normalizing to LF newlines."""
    lines = data.decode("utf-8").splitlines(keepends=False)
    rewritten = [rewrite_imports(line) for line in lines]
    return ("\n".join(rewritten) + "\n").encode("utf-8")


def build_gpr() -> bytes:
    """Render the standalone addon registration file."""
    return GPR_TEMPLATE.encode("utf-8")


def build_zip(repo_root: Path, output: Path) -> Path:
    """Build the ``GWizardMerge.zip`` bundle next to this script."""
    members: dict[str, bytes] = {}
    for member, source in SOURCES.items():
        path = repo_root / source
        if not path.is_file():
            raise FileNotFoundError(f"Missing source file: {path}")
        text = path.read_bytes()
        members[member] = rewrite_imports_bytes(text)
        LOG.debug("Added %s (%d bytes)", source, len(members[member]))
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PACKAGE + "/", b"")
        archive.writestr(PACKAGE + "/__init__.py", b"")
        archive.writestr(f"{PACKAGE}/{GPR_FILENAME}", build_gpr())
        for member in sorted(members):
            archive.writestr(f"{PACKAGE}/{member}", members[member])
    LOG.info("Wrote %s (%d bytes)", output, output.stat().st_size)
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build the standalone GWizardMerge.zip addon package."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "GWizardMerge.zip",
        help="Destination zip file (default: GWizardMerge.zip next to the script).",
    )
    parser.add_argument(
        "--gramps-target",
        default=DEFAULT_GRAMPS_TARGET,
        help=(
            "Accepted for compatibility; the bundled registration file now "
            "uses Gramps' dynamic major_version with a VERSION_TUPLE gate, "
            f"so this value (default: {DEFAULT_GRAMPS_TARGET}) is ignored."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build the bundle and report the result."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent
    output: Path = args.output
    if not output.is_absolute():
        output = repo_root / output
    try:
        built = build_zip(repo_root, output)
    except FileNotFoundError as error:
        LOG.error("%s", error)
        return 1
    print(str(built))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
