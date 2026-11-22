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

"""Build the standalone ``GWizardFileMerge.zip`` addon package.

The GWizard plugin version is controlled by the ``--version`` command-line
argument (default: 0.0.1).

Collects the GWizard backend, GUI, and tool modules scattered across
``gramps/gen/gwizard``, ``gramps/gui/gwizard``, and ``gramps/plugins/tool``
into a single flat ``GWizardFileMerge/`` addon directory inside a zip file,
rewriting the ``gramps.gen.gwizard`` / ``gramps.gui.gwizard`` absolute
imports and intra-package relative imports to flat sibling imports so the
bundle loads under Gramps' plugin importer (which imports the tool module
top-level via ``__import__`` with the addon directory on ``sys.path``).
Also embeds the standalone addon registration file
``GWizardFileMerge/GWizardFileMerge.gpr.py`` (mirroring the ``gwizardmerge``
entry in ``gramps/plugins/tool/tools.gpr.py``). The unit tests are copied
into ``GWizardFileMerge/tests/`` inside the bundle, with the same GWizard
import rewriting applied so they resolve the flat sibling modules, and the
test fixture tree (the ``.ged`` source fixture and its ``media/`` images)
is copied verbatim into ``GWizardFileMerge/tests/data/`` so the
fixture-based tests run against the extracted bundle instead of skipping.
Newlines are normalized to LF so the output is identical regardless of the
checkout's line-ending setting.
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
import subprocess
import zipfile
from pathlib import Path

LOG = logging.getLogger(__name__)

PACKAGE = "GWizardFileMerge"

GPR_FILENAME = "GWizardFileMerge.gpr.py"

# Standalone addon registration file, embedded in the bundle as
# ``GWizardFileMerge/GWizardFileMerge.gpr.py``. This template is the single
# source of truth for the generated registration; no standalone GPR file is
# written to the repository.
GPR_TEMPLATE = """\
# Gramps registration file for the GWizard File Merge tool.

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
        name=_("GWizard File Merge"),
        description=_(
            "Family Tree Processing Tool to compare another genealogy file "
            "(GEDCOM, Gramps XML, ...) side-by-side with the open Family Tree "
            "and merge selected differences person by person."
        ),
        version="__GWIZARD_VERSION__",
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
        help_url=("https://gramps-project.org/wiki/index.php/Addon:GWizardFileMerge_Tool")
    )
"""

# Contents of ``GWizardFileMerge/tests/__init__.py`` inside the bundle. The
# bundled tests use flat sibling imports (``from gwizard import ...``), which
# only resolve when the addon directory itself is on ``sys.path``. Gramps puts
# it there when loading the plugin, but a plain
# ``python3 -m unittest GWizardFileMerge.tests.<module>`` run from the
# ``addons-source`` directory does not, so the package initializer adds it.
TESTS_INIT = """\
\"\"\"Make the flat GWizard addon modules importable when running the tests.\"\"\"
import os
import sys

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ADDON_DIR not in sys.path:
    sys.path.insert(0, _ADDON_DIR)
"""

DEFAULT_GRAMPS_TARGET = "6.0"

# Map of archive member name -> source file relative to the repo root.
SOURCES: dict[str, str] = {
    "gwizardgedcom.py": "gramps/gen/gwizard/gwizardgedcom.py",
    "gwizard_base.py": "gramps/gen/gwizard/gwizard_base.py",
    "gwizard_base.py": "gramps/gen/gwizard/gwizard_base.py",
    "gwizard_base.py": "gramps/gen/gwizard/gwizard_base.py",
    "gwizardmerge.py": "gramps/plugins/tool/gwizardmerge.py",
    "gwizardmergedialog.py": "gramps/gui/gwizard/gwizardmergedialog.py",
}

# Unit-test modules bundled into ``GWizardFileMerge/tests/`` inside the zip.
# Keyed by test file name; the value is the source path relative to the repo
# root. These are placed under the ``tests/`` subdirectory rather than flat,
# and receive the same GWizard import rewriting as the tool modules.
TEST_SOURCES: dict[str, str] = {
    "gwizard_test.py": "gramps/gen/gwizard/test/gwizard_test.py",
    "gwizard_merge_fields_test.py": (
        "gramps/gui/gwizard/test/gwizard_merge_fields_test.py"
    ),
    "gwizard_styling_test.py": "gramps/gui/gwizard/test/gwizard_styling_test.py",
    "gwizardmerge_test.py": "gramps/plugins/tool/test/gwizardmerge_test.py",
}

# Fixture tree bundled into ``GWizardFileMerge/tests/data/`` inside the zip,
# relative to the repo root. The bundled ``GWizardSourceMediaMergeTest``
# resolves it as ``os.path.join(os.path.dirname(__file__), "data")`` next to
# ``gwizard_test.py``, and the GEDCOM's relative ``FILE media/...`` paths
# resolve against the ``.ged`` file's own directory, so the whole tree is
# copied across preserving its layout. Files are copied verbatim (no import
# rewriting): text files only get newline normalization, and the ``.png``
# images are byte-for-byte copies since import rewriting assumes UTF-8 text.
TEST_DATA_DIR = "gramps/gen/gwizard/test/data"

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
    # Relative imports: one or more leading dots both flatten to a flat
    # sibling import -- single dot (``from .gwizard import``) as used by the
    # tool modules, double dot (``from ..gwizard import``) as used by the
    # bundled unit tests.
    (
        re.compile(
            r"from\s+\.+(gwizardgedcom|gwizard|gwizardcompare|gwizardlauncher|"
            r"gwizardmerge|gwizardmergedialog)\s+import\b"
        ),
        r"from \1 import",
    ),
    # Module-from-package imports (``from gramps.gui.gwizard import
    # gwizardmergedialog``) become a bare ``import <module>`` sibling import.
    (
        re.compile(
            r"from\s+gramps\.(?:gen|gui)\.gwizard\s+import\s+"
            r"(gwizardgedcom|gwizard|gwizardcompare|gwizardlauncher|"
            r"gwizardmerge|gwizardmergedialog)\b"
        ),
        r"import \1",
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


def build_gpr(version: str = "0.0.1") -> bytes:
    """Render the standalone addon registration file."""
    return GPR_TEMPLATE.replace("__GWIZARD_VERSION__", version).encode("utf-8")


def build_test_data(repo_root: Path) -> dict[str, bytes]:
    """
    Collect the test fixture tree for ``tests/data/`` in the bundle.

    :param repo_root: Repository root holding the fixture tree.
    :returns: Map of archive-relative POSIX path to file bytes.
    :raises FileNotFoundError: If the fixture tree or GEDCOM fixture is
        missing from the repository.
    """
    data_root = repo_root / TEST_DATA_DIR
    if not data_root.is_dir():
        raise FileNotFoundError(f"Missing test data directory: {data_root}")
    ged_fixture = data_root / "gwizard_mergefrom_sources.ged"
    if not ged_fixture.is_file():
        raise FileNotFoundError(f"Missing test fixture file: {ged_fixture}")
    members: dict[str, bytes] = {}
    for path in sorted(data_root.rglob("*")):
        if not path.is_file():
            continue
        member = path.relative_to(data_root).as_posix()
        raw = path.read_bytes()
        if path.suffix.lower() == ".png":
            # Binary image: byte-for-byte copy, import rewriting would
            # corrupt it (rewrite_imports_bytes decodes UTF-8 text).
            members[member] = raw
        else:
            # Text fixture (GEDCOM, generator script): normalize newlines
            # like the code members so the bundle is deterministic.
            lines = raw.decode("utf-8").splitlines(keepends=False)
            members[member] = ("\n".join(lines) + "\n").encode("utf-8")
        LOG.debug("Added data %s (%d bytes)", member, len(members[member]))
    return members


def build_translations(repo_root: Path) -> bytes:
    """
    Generate the translation template (po/template.pot) from source .py files.

    This function extracts translatable strings (wrapped in ``_()``) from the
    source .py files that are bundled in the zip (not the test files) and
    generates a valid ``.pot`` (portable object template) file.

    The standalone addon registration file (GWizardFileMerge.gpr.py) is
    generated separately by ``build_gpr()``. This function instead produces
    the gettext translation template so the addon can be translated by
    translators.

    :param repo_root: Repository root holding the source files.
    :returns: The rendered translation template content.
    """
    import ast
    import datetime

    # Files that go into the bundle (not the test files).
    source_files = [
        "gramps/gen/gwizard/gwizardgedcom.py",
        "gramps/gen/gwizard/gwizard_base.py",
        "gramps/gui/gwizard/gwizardcompare.py",
        "gramps/gui/gwizard/gwizardlauncher.py",
        "gramps/plugins/tool/gwizardmerge.py",
        "gramps/gui/gwizard/gwizardmergedialog.py",
    ]

    # Collect translatable strings from each source file.
    # Each entry is (file_path, line_number, string_value).
    entries: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for rel_path in source_files:
        full_path = repo_root / rel_path
        if not full_path.is_file():
            continue
        source_code = full_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source_code, filename=rel_path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match calls to _(...) for translation.
            if isinstance(func, ast.Name) and func.id == "_":
                if node.args:
                    arg = node.args[0]
                    msgid: str | None = None
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        msgid = arg.value
                    elif isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod):
                        # Handle "string % var" pattern.
                        if isinstance(arg.left, ast.Constant) and isinstance(
                            arg.left.value, str
                        ):
                            msgid = arg.left.value
                    if msgid is not None and msgid not in seen:
                        seen.add(msgid)
                        entries.append((rel_path, node.lineno, msgid))

    # Generate the .pot file content.
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M%z")
    lines: list[str] = [
        "# SOME DESCRIPTIVE TITLE.",
        "# Copyright (C) YEAR THE PACKAGE'S COPYRIGHT HOLDER",
        "# This file is distributed under the same license as the PACKAGE package.",
        "# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.",
        "#",
        "#, fuzzy",
        'msgid ""',
        'msgstr ""',
        f'"Project-Id-Version: PACKAGE VERSION\\n"',
        '"Report-Msgid-Bugs-To: \\n"',
        f'"POT-Creation-Date: {now}\\n"',
        '"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"',
        '"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"',
        '"Language-Team: LANGUAGE <LL@li.org>\\n"',
        '"Language: \\n"',
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        '"Plural-Forms: nplurals=INTEGER; plural=EXPRESSION;\\n"',
        "",
    ]

    for file_path, line_no, msgid in entries:
        lines.append(f"#: {file_path}:{line_no}")
        # Escape special characters in msgid.
        escaped = msgid.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'msgid "{escaped}"')
        lines.append('msgstr ""')
        lines.append("")

    content = "\n".join(lines).encode("utf-8")

    # Create the po/ directory and write po/template.pot.
    po_dir = repo_root / "po"
    po_dir.mkdir(exist_ok=True)
    target_po = po_dir / "template.pot"
    target_po.write_bytes(content)

    result = target_po.read_bytes()

    target_po.unlink(missing_ok=True)
    try:
        po_dir.rmdir()
    except OSError:
        pass

    return result


def build_zip(repo_root: Path, output: Path, version: str = "0.0.1") -> Path:
    """Build the ``GWizardFileMerge.zip`` bundle next to this script."""
    members: dict[str, bytes] = {}
    for member, source in SOURCES.items():
        path = repo_root / source
        if not path.is_file():
            raise FileNotFoundError(f"Missing source file: {path}")
        text = path.read_bytes()
        members[member] = rewrite_imports_bytes(text)
        LOG.debug("Added %s (%d bytes)", source, len(members[member]))

    test_members: dict[str, bytes] = {}
    for member, source in TEST_SOURCES.items():
        path = repo_root / source
        if not path.is_file():
            raise FileNotFoundError(f"Missing test source file: {path}")
        text = path.read_bytes()
        test_members[member] = rewrite_imports_bytes(text)
        LOG.debug("Added test %s (%d bytes)", source, len(test_members[member]))

    data_members = build_test_data(repo_root)

    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PACKAGE + "/", b"")
        archive.writestr(f"{PACKAGE}/{GPR_FILENAME}", build_gpr(version))
        for member in sorted(members):
            archive.writestr(f"{PACKAGE}/{member}", members[member])
        if test_members:
            archive.writestr(PACKAGE + "/tests/", b"")
            archive.writestr(PACKAGE + "/tests/__init__.py", TESTS_INIT.encode("utf-8"))
            for member in sorted(test_members):
                archive.writestr(f"{PACKAGE}/tests/{member}", test_members[member])
        if data_members:
            archive.writestr(f"{PACKAGE}/tests/data/", b"")
            for member in sorted(data_members):
                archive.writestr(f"{PACKAGE}/tests/data/{member}", data_members[member])

        # Include the translation template (po/template.pot) generated from the
        # source .py files.
        po_template = build_translations(repo_root)
        archive.writestr(f"{PACKAGE}/po/template.pot", po_template)

    LOG.info("Wrote %s (%d bytes)", output, output.stat().st_size)
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build the standalone GWizardFileMerge.zip addon package."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Destination zip file (default: GWizardFileMerge_v<version>.zip next to the script, where <version> is the plugin version).",
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
    parser.add_argument(
        "--version",
        dest="version_opt",
        default="0.0.1",
        help="GWizard plugin version for the registration file (default: 0.0.1).",
    )
    parser.add_argument(
        "version_pos",
        nargs="?",
        default=None,
        help="GWizard plugin version for the registration file (default: 0.0.1), "
        "alternative to --version.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build the bundle and report the result."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent
    # Bare positional version takes precedence over --version; both default to
    # "0.0.1" when neither is supplied.
    version = args.version_pos if args.version_pos is not None else args.version_opt
    # Default output name embeds the plugin version: GWizardFileMerge_v<version>.zip.
    if args.output is None:
        output = repo_root / f"GWizardFileMerge_v{version}.zip"
    else:
        output = args.output
        if not output.is_absolute():
            output = repo_root / output
    try:
        built = build_zip(repo_root, output, version=version)
    except FileNotFoundError as error:
        LOG.error("%s", error)
        return 1
    print(str(built))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
