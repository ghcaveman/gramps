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

"""Build a standalone Gramps addon zip from a core-Gramps feature branch.

Shared by every feature repo: copy this file unchanged from gramps_devutil
into the repo root and describe the addon in ``addon_package.toml`` next to
it (see ``addon_package.example.toml``). Nothing project-specific lives here.

What a build does:

* Collects the addon's modules (spread over ``gramps/gen``, ``gramps/gui``,
  ``gramps/plugins``, ...) into one flat ``<package>/`` directory, because
  Gramps imports an addon's tool module top-level with the addon directory
  on ``sys.path``.
* Rewrites imports line by line so they resolve in the flat layout. The
  rules come from each file's own path, so the config needs no regexes:
  ``gramps/gui/gwizard/gwizardcompare.py`` turns
  ``from gramps.gui.gwizard.gwizardcompare import X``,
  ``from gramps.gui.gwizard import gwizardcompare`` and
  ``from .gwizardcompare import X`` into ``from gwizardcompare import X`` /
  ``import gwizardcompare``. Modules provided by an addon this one depends
  on are flattened the same way but not bundled.
* Bundles unit tests into ``<package>/tests/`` (test helpers next to them,
  imported package-relative) with a ``tests/__init__.py`` that makes the
  flat modules importable, plus an optional test-data tree.
* Generates ``<package>/<package>.gpr.py`` from ``[registration]``.
* Generates ``<package>/po/template.pot`` with xgettext over the flattened
  files, the way addons-source ``make.py init`` does, so references read
  ``<package>/<file>.py:<line>``.
* Warns about lines that still reference the core tree after rewriting, and,
  in a git checkout, about files changed on the branch that the bundle
  neither includes nor ignores (the ``changed_files.txt`` check).

Newlines are normalized to LF so the zip is identical whatever the
checkout's line-ending setting. Requires Python 3.11+ (``tomllib``).

Usage::

    python package_addon.py 0.1.0            # version positional or --version
    python package_addon.py --config addon_package_mediafix.toml 0.1.0
    python package_addon.py --check          # only report, write no zip
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

LOG = logging.getLogger(__name__)

DEFAULT_CONFIG = "addon_package.toml"

# When the config names no base branch, every local or remote branch whose
# name matches this is a candidate, and the one the branch differs from
# least is used: that is the branch it was started from (for example
# origin/maintenance/gramps61 rather than origin/master).
CANDIDATE_BASE = re.compile(r"^(?:[^/]+/)?(?:master|main|maintenance/[^/]+)$")

# Suffixes copied byte-for-byte from the test-data tree; any other file that
# is not valid UTF-8 is copied raw as well.
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".pdf",
        ".zip",
        ".gz",
        ".gpkg",
        ".ico",
        ".svgz",
        ".mp3",
        ".wav",
        ".db",
        ".sqlite",
    }
)

# xgettext keywords: addons-source ``make.py init`` uses ``_`` and ``N_``;
# the rest are gettext helpers Gramps code commonly uses.
DEFAULT_KEYWORDS = ("_", "N_", "_T_", "sgettext", "ngettext:1,2", "pgettext:1c,2")

# Registration fields whose values are Gramps constants (written unquoted
# and imported from gramps.gen.plug._pluginreg).
CONSTANT_FIELDS = ("type", "status", "audience", "category")
CONSTANT_LIST_FIELDS = ("tool_modes",)
# Registration fields wrapped in _() for translation.
TRANSLATED_FIELDS = ("name", "description")
# Order of the generated register() arguments; anything else from
# [registration] (or [registration.extra]) follows in config order.
FIELD_ORDER = (
    "id",
    "name",
    "description",
    "version",
    "gramps_target_version",
    "status",
    "audience",
    "fname",
    "authors",
    "authors_email",
    "category",
    "toolclass",
    "optionclass",
    "tool_modes",
    "depends_on",
    "help_url",
)
# Config-only keys of [registration] that are not register() arguments.
NON_FIELD_KEYS = ("type", "gramps_versions", "extra")

TESTS_INIT_TEMPLATE = '''\
"""Make the flat {package} addon modules importable when running the tests.

Gramps puts the addon directory on sys.path when it loads the plugin, but
``python3 -m unittest {package}.tests.<module>`` run from the directory that
holds the addon does not, so this package initializer adds it (and the
directories of the addons it depends on, when they sit alongside).
"""
import os
import sys

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_ADDON_DIR)
for _path in [os.path.join(_PARENT, _name) for _name in {dependency_dirs!r}] + [
    _ADDON_DIR
]:
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
'''


# -------------------------------------------------------------------------
#
# Glob helpers
#
# -------------------------------------------------------------------------
def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """
    Compile a repo-relative POSIX glob to a regex.

    ``*`` and ``?`` stay within one path segment, ``**`` spans any number of
    segments (``a/**/b`` also matches ``a/b``), ``[...]`` is a character
    class.
    """
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append(re.escape(pattern[i]))
                i += 1
            else:
                out.append(pattern[i : end + 1])
                i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matches_any(rel: str, patterns: list[str]) -> bool:
    """Whether a repo-relative POSIX path matches any glob."""
    return any(glob_to_regex(p).match(rel) for p in patterns)


def expand_globs(repo_root: Path, patterns: list[str]) -> list[str]:
    """
    Expand globs to sorted repo-relative POSIX file paths.

    Only the literal directory prefix of each pattern is walked, so a broad
    repo is not scanned. A pattern with no wildcard must name an existing
    file.

    :raises FileNotFoundError: If a literal path does not exist.
    """
    found: set[str] = set()
    for pattern in patterns:
        if not re.search(r"[*?\[]", pattern):
            if not (repo_root / pattern).is_file():
                raise FileNotFoundError(f"Missing file: {repo_root / pattern}")
            found.add(pattern)
            continue
        parts = PurePosixPath(pattern).parts
        prefix = []
        for part in parts:
            if re.search(r"[*?\[]", part):
                break
            prefix.append(part)
        base = repo_root.joinpath(*prefix)
        if not base.is_dir():
            continue
        regex = glob_to_regex(pattern)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            for name in filenames:
                rel = (Path(dirpath) / name).relative_to(repo_root).as_posix()
                if regex.match(rel):
                    found.add(rel)
    return sorted(found)


# -------------------------------------------------------------------------
#
# Configuration
#
# -------------------------------------------------------------------------
@dataclass
class Dependency:
    """An addon this addon depends on (``[[dependencies]]``)."""

    id: str
    package: str
    modules: list[str]


@dataclass
class Plan:
    """Everything a build needs, resolved against the repo."""

    repo_root: Path
    config_path: Path
    package: str
    zip_name: str
    registration: dict[str, Any]
    modules: dict[str, str] = field(default_factory=dict)  # member -> rel
    tests: dict[str, str] = field(default_factory=dict)
    helpers: dict[str, str] = field(default_factory=dict)
    data: dict[str, str] = field(default_factory=dict)  # member under data/
    data_target: str = "data"
    dependencies: list[Dependency] = field(default_factory=list)
    dependency_modules: list[str] = field(default_factory=list)  # rel paths
    keep_unrewritten: list[re.Pattern[str]] = field(default_factory=list)
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS
    check_base: list[str] = field(default_factory=list)
    check_ignore: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)  # rel paths


def _flat_members(rels: list[str], kind: str) -> dict[str, str]:
    """
    Map flat member names to source paths, rejecting name clashes.

    :raises ValueError: If two sources would land on the same member name.
    """
    members: dict[str, str] = {}
    for rel in rels:
        name = PurePosixPath(rel).name
        if name in members:
            raise ValueError(
                f"Two {kind} files flatten to the same name '{name}':\n"
                f"  {members[name]}\n  {rel}\n"
                "Rename one, or exclude the one that should not ship."
            )
        members[name] = rel
    return members


def load_plan(config_path: Path) -> Plan:
    """
    Read an ``addon_package.toml`` and resolve its globs against the repo.

    The repo root is the directory holding the config file.

    :raises FileNotFoundError: For missing config, files or test data.
    :raises ValueError: For an invalid config or a flat-name clash.
    """
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing config file: {config_path}")
    with config_path.open("rb") as handle:
        cfg = tomllib.load(handle)
    repo_root = config_path.resolve().parent

    package = cfg.get("package")
    if not package:
        raise ValueError(f"{config_path.name}: 'package' is required")
    registration = dict(cfg.get("registration", {}))
    for key in ("id", "name", "fname"):
        if key not in registration:
            raise ValueError(f"{config_path.name}: [registration] needs '{key}'")

    files = cfg.get("files", {})
    exclude = list(files.get("exclude", []))

    def resolve(key: str) -> list[str]:
        rels = expand_globs(repo_root, list(files.get(key, [])))
        return [
            r
            for r in rels
            if PurePosixPath(r).name != "__init__.py" and not matches_any(r, exclude)
        ]

    modules = resolve("modules")
    if not modules:
        raise ValueError(f"{config_path.name}: [files] modules matched no files")
    helpers = resolve("test_helpers")
    tests = [r for r in resolve("tests") if r not in helpers]

    plan = Plan(
        repo_root=repo_root,
        config_path=config_path,
        package=package,
        zip_name=cfg.get("zip_name", "{package}_v{version}.zip"),
        registration=registration,
        modules=_flat_members(modules, "module"),
        tests=_flat_members(tests + helpers, "test"),
        helpers=_flat_members(helpers, "test helper"),
        keep_unrewritten=[re.compile(p) for p in files.get("keep_unrewritten", [])],
        keywords=tuple(cfg.get("translations", {}).get("keywords", DEFAULT_KEYWORDS)),
    )
    if f"{registration['fname']}" not in plan.modules:
        raise ValueError(
            f"{config_path.name}: registration fname '{registration['fname']}' "
            "is not among the bundled modules"
        )

    data_cfg = files.get("test_data")
    if data_cfg:
        source = data_cfg["source"]
        plan.data_target = data_cfg.get("target", "data")
        root = repo_root / source
        if not root.is_dir():
            raise FileNotFoundError(f"Missing test data directory: {root}")
        for required in data_cfg.get("required", []):
            if not (root / required).is_file():
                raise FileNotFoundError(f"Missing test fixture file: {root / required}")
        for rel in expand_globs(repo_root, [f"{source}/**"]):
            plan.data[PurePosixPath(rel).relative_to(source).as_posix()] = rel

    for dep in cfg.get("dependencies", []):
        dep_modules = expand_globs(repo_root, list(dep.get("modules", [])))
        plan.dependencies.append(
            Dependency(id=dep["id"], package=dep["package"], modules=dep_modules)
        )
        plan.dependency_modules.extend(dep_modules)
    clash = set(PurePosixPath(m).name for m in plan.dependency_modules) & set(
        plan.modules
    )
    if clash:
        raise ValueError(
            f"{config_path.name}: bundled modules also provided by a "
            f"dependency: {', '.join(sorted(clash))}"
        )

    check = cfg.get("check", {})
    base = check.get("base", [])
    plan.check_base = [base] if isinstance(base, str) else list(base)
    plan.check_ignore = list(check.get("ignore", []))
    plan.excluded = exclude
    return plan


# -------------------------------------------------------------------------
#
# Import rewriting
#
# -------------------------------------------------------------------------
def _dotted(rel: str) -> str:
    """``gramps/gui/gwizard/x.py`` -> ``gramps.gui.gwizard.x``."""
    return ".".join(PurePosixPath(rel).with_suffix("").parts)


def _alternation(names: list[str]) -> str:
    """Regex alternation, longest first, so prefixes never win early."""
    return "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))


class Rewriter:
    """Line-by-line import rewriting for one addon."""

    def __init__(self, plan: Plan) -> None:
        flat = list(plan.modules.values()) + plan.dependency_modules
        helpers = list(plan.helpers.values())
        self.keep = plan.keep_unrewritten
        self.rules: list[tuple[re.Pattern[str], Any]] = []

        def add_rules(rels: list[str], relative_prefix: str) -> None:
            if not rels:
                return
            by_dotted = {_dotted(r): PurePosixPath(r).stem for r in rels}
            stems = sorted(set(by_dotted.values()))
            # from pkg.mod import X  ->  from mod import X
            self.rules.append(
                (
                    re.compile(
                        rf"\bfrom\s+({_alternation(list(by_dotted))})\s+import\b"
                    ),
                    lambda m, d=by_dotted, p=relative_prefix: f"from {p}{d[m.group(1)]} import",
                )
            )
            # from pkg import mod  ->  import mod   (or: from . import mod)
            parents: dict[str, list[str]] = {}
            for dotted, stem in by_dotted.items():
                parents.setdefault(dotted.rpartition(".")[0], []).append(stem)
            for parent, names in parents.items():
                target = "from . import" if relative_prefix else "import"
                self.rules.append(
                    (
                        re.compile(
                            rf"\bfrom\s+{re.escape(parent)}\s+import\s+"
                            rf"(?=(?:{_alternation(names)})\b)"
                        ),
                        f"{target} ",
                    )
                )
            if not relative_prefix:
                # from .mod import X / from ..mod import X  ->  from mod import X
                self.rules.append(
                    (
                        re.compile(rf"\bfrom\s+\.+({_alternation(stems)})\s+import\b"),
                        r"from \1 import",
                    )
                )

        add_rules(flat, "")
        add_rules(helpers, ".")
        # Dotted references outside import statements -- mock.patch target
        # strings such as "gramps.plugins.tool.foo.OkDialog", or
        # "import gramps.plugins.tool.foo" -- point at the flat module too.
        if flat:
            by_dotted = {_dotted(r): PurePosixPath(r).stem for r in flat}
            self.rules.append(
                (
                    re.compile(rf"(?<![\w.])({_alternation(list(by_dotted))})(?!\w)"),
                    lambda m, d=by_dotted: d[m.group(1)],
                )
            )
        # Anything still naming one of these through the core tree afterwards
        # (a mock.patch target string, an unusual import) is reported.
        self.leftover = re.compile(
            rf"\b(?:{_alternation([_dotted(r) for r in flat + helpers])})\b"
        )

    def line(self, text: str) -> str:
        """Rewrite one line (unless a keep_unrewritten pattern matches it)."""
        if any(p.search(text) for p in self.keep):
            return text
        for pattern, replacement in self.rules:
            text = pattern.sub(replacement, text)
        return text

    def file(self, data: bytes) -> bytes:
        """Rewrite a UTF-8 source file, normalizing newlines to LF."""
        lines = data.decode("utf-8").splitlines()
        return ("\n".join(self.line(l) for l in lines) + "\n").encode("utf-8")

    def leftovers(self, name: str, data: bytes) -> list[str]:
        """``name:line: text`` for lines that still reference the core tree."""
        found = []
        for number, text in enumerate(data.decode("utf-8").splitlines(), start=1):
            if self.leftover.search(text) and not any(
                p.search(text) for p in self.keep
            ):
                found.append(f"{name}:{number}: {text.strip()}")
        return found


# -------------------------------------------------------------------------
#
# Generated files
#
# -------------------------------------------------------------------------
def build_gpr(plan: Plan, version: str) -> bytes:
    """Render ``<package>.gpr.py`` from ``[registration]``."""
    reg = dict(plan.registration)
    extra = dict(reg.get("extra", {}))
    reg.setdefault("type", "TOOL")
    reg.setdefault("status", "EXPERIMENTAL")
    reg.setdefault("audience", "EXPERT")
    if reg["type"] == "TOOL":
        reg.setdefault("category", "TOOL_DBPROC")
        reg.setdefault("tool_modes", ["TOOL_MODE_GUI"])
    reg["version"] = version
    if plan.dependencies:
        deps = list(reg.get("depends_on", []))
        deps += [d.id for d in plan.dependencies if d.id not in deps]
        reg["depends_on"] = deps
    low, high = reg.get("gramps_versions", ["5.2.0", "6.2.0"])

    constants = {reg["type"]}
    for key in CONSTANT_FIELDS:
        if key in reg:
            constants.add(reg[key])
    for key in CONSTANT_LIST_FIELDS:
        constants.update(reg.get(key, []))

    def value(key: str, val: Any) -> str:
        if key in CONSTANT_FIELDS:
            return str(val)
        if key in CONSTANT_LIST_FIELDS:
            return "[" + ", ".join(val) + "]"
        if key in TRANSLATED_FIELDS:
            literal = py_literal(val)
            if len(f"        {key}=_({literal}),") <= 88:
                return f"_({literal})"
            chunks = "\n".join(f"            {c}" for c in wrap_string(val, 66))
            return f"_(\n{chunks}\n        )"
        return py_literal(val)

    keys = [k for k in FIELD_ORDER if k in reg or k == "gramps_target_version"]
    keys += [k for k in reg if k not in keys and k not in NON_FIELD_KEYS]
    args = [f"        {reg['type']},"]
    for key in keys:
        if key == "gramps_target_version":
            args.append("        gramps_target_version=major_version,")
        else:
            args.append(f"        {key}={value(key, reg[key])},")
    for key, val in extra.items():
        args.append(f"        {key}={py_literal(val)},")

    def tup(text: str) -> str:
        return "(" + ", ".join(str(int(p)) for p in text.split(".")) + ")"

    lines = [
        f"# Gramps registration file for {plan.registration['name']}.",
        f"# Generated by package_addon.py from {plan.config_path.name};",
        "# edit that file, not this one.",
        "",
        "from gramps.gen.plug._pluginreg import (",
        *[f"    {c}," for c in sorted(constants)],
        ")",
        "from gramps.gen.const import GRAMPS_LOCALE as glocale",
        "from gramps.version import major_version, VERSION_TUPLE",
        "",
        "_ = glocale.translation.gettext",
        "",
        f"if {tup(low)} <= VERSION_TUPLE <= {tup(high)}:",
        "    register(",
        *args,
        "    )",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def py_literal(value: Any) -> str:
    """Python literal in Black style (double-quoted strings)."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool) or value is None:
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(py_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(f"{py_literal(k)}: {py_literal(v)}" for k, v in value.items())
            + "}"
        )
    return repr(value)


def wrap_string(text: str, width: int) -> list[str]:
    """Split a long string into implicitly concatenated literals."""
    chunks, current = [], ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if current and len(candidate) + 1 > width:
            chunks.append(current + " ")
            current = word
        else:
            current = candidate
    chunks.append(current)
    return [py_literal(c) for c in chunks]


def build_tests_init(plan: Plan) -> bytes:
    """Render ``tests/__init__.py``."""
    return TESTS_INIT_TEMPLATE.format(
        package=plan.package,
        dependency_dirs=[d.package for d in plan.dependencies],
    ).encode("utf-8")


def build_translations(plan: Plan, members: dict[str, bytes], gpr: bytes) -> bytes:
    """
    Generate ``po/template.pot`` the way addons-source ``make.py init`` does.

    The flattened members and the ``.gpr.py`` are written into a temporary
    ``<package>/`` directory and xgettext runs from its parent with relative
    paths, so references read ``<package>/<file>.py:<line>`` and, because
    rewriting is line-for-line, match the shipped files.

    :raises FileNotFoundError: If xgettext is not on PATH.
    :raises subprocess.CalledProcessError: If xgettext fails.
    """
    xgettext = shutil.which("xgettext")
    if xgettext is None:
        raise FileNotFoundError(
            "xgettext not found on PATH; install GNU gettext "
            "(or rerun with --skip-pot to build without po/template.pot)"
        )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        (tmp_root / plan.package).mkdir()
        files = dict(members)
        files[f"{plan.package}.gpr.py"] = gpr
        for name, data in files.items():
            (tmp_root / plan.package / name).write_bytes(data)
        cmd = [
            xgettext,
            "--language=Python",
            "--from-code=UTF-8",
            "--add-comments=Translators",
            *(f"--keyword={kw}" for kw in plan.keywords),
            "-o",
            "template.pot",
            *(f"{plan.package}/{name}" for name in sorted(files)),
        ]
        LOG.debug("Running %s", " ".join(cmd))
        subprocess.run(cmd, cwd=tmp_root, check=True)
        pot = tmp_root / "template.pot"
        if not pot.is_file():
            raise FileNotFoundError("xgettext found no translatable strings")
        lines = pot.read_bytes().decode("utf-8").splitlines()
    return ("\n".join(lines) + "\n").encode("utf-8")


def read_data_file(path: Path) -> bytes:
    """Test-data file: binary copied raw, text normalized to LF."""
    raw = path.read_bytes()
    if path.suffix.lower() in BINARY_SUFFIXES:
        return raw
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return ("\n".join(text.splitlines()) + "\n").encode("utf-8")


# -------------------------------------------------------------------------
#
# Branch check
#
# -------------------------------------------------------------------------
def _git(repo_root: Path, *args: str) -> list[str] | None:
    """Run git, returning output lines, or None if git is unavailable/fails."""
    if shutil.which("git") is None:
        return None
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        LOG.debug(
            "git %s failed (%s): %s",
            " ".join(args),
            result.returncode,
            result.stderr.strip(),
        )
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def _branch_changes(repo_root: Path, base: str, head: str) -> list[str] | None:
    """Files changed on HEAD since it split from ``base`` (None on failure)."""
    merge_base = _git(repo_root, "merge-base", base, head)
    if not merge_base:
        return None
    return _git(repo_root, "diff", "--name-only", merge_base[0], head)


def changed_files(repo_root: Path, bases: list[str]) -> tuple[list[str] | None, str]:
    """
    Files changed on this branch: committed since it split from its base
    branch, plus uncommitted and untracked files.

    With ``bases`` empty the base is detected: of all branches matching
    ``CANDIDATE_BASE``, the one giving the fewest changed files. Otherwise
    the first of ``bases`` that exists is used.

    Uses plain ``rev-parse``/``merge-base``/``diff A B`` calls (no ``^{}`` or
    ``...`` syntax) so it behaves the same from any shell on Windows.

    :returns: (paths, description of the base used), or
        (None, reason the check was skipped).
    """
    if shutil.which("git") is None:
        return None, "git is not on PATH"
    if _git(repo_root, "rev-parse", "--is-inside-work-tree") is None:
        return None, "not a git checkout"
    head = _git(repo_root, "rev-parse", "--verify", "HEAD")
    if not head:
        return None, "the branch has no commits yet"

    committed: list[str] | None = None
    used = ""
    if bases:
        for base in bases:
            if _git(repo_root, "rev-parse", "--verify", "--quiet", base):
                committed = _branch_changes(repo_root, base, head[0])
                if committed is None:
                    return None, (
                        f"{base} shares no history with this branch "
                        "(shallow clone?); run with -v for git's message"
                    )
                used = base
                break
        else:
            return None, (
                f"none of {', '.join(bases)} exists; fix base under [check] "
                "(run 'git branch -a' to see the names)"
            )
    else:
        current = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or [""]
        refs = _git(
            repo_root,
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
            "refs/remotes",
        )
        best: tuple[int, int, str, list[str]] | None = None
        for order, ref in enumerate(refs or []):
            if ref == current[0] or not CANDIDATE_BASE.match(ref):
                continue
            changes = _branch_changes(repo_root, ref, head[0])
            if changes is None:
                continue
            key = (len(changes), order, ref, changes)
            if best is None or key[:2] < best[:2]:
                best = key
        if best is None:
            return None, (
                "no master, main or maintenance/* branch found; set base under "
                "[check] (run 'git branch -a' to see the names)"
            )
        committed, used = best[3], f"{best[2]} (detected automatically)"

    working = _git(repo_root, "diff", "--name-only", "HEAD") or []
    untracked = _git(repo_root, "ls-files", "--others", "--exclude-standard") or []
    return sorted(set(committed) | set(working) | set(untracked)), used


def unaccounted_files(plan: Plan, changed: list[str]) -> list[str]:
    """
    Changed files that no ``addon_package*.toml`` in the repo bundles,
    provides as a dependency, excludes or ignores.

    Sibling configs count, so a repo that builds two addons (CitationFix and
    its MediaFix dependency) does not report each addon's files from the
    other's build.
    """
    accounted: set[str] = set()
    ignore: list[str] = []
    for config in sorted(plan.repo_root.glob("addon_package*.toml")):
        if config.name.endswith(".example.toml"):
            continue
        try:
            other = (
                plan
                if config.resolve() == plan.config_path.resolve()
                else load_plan(config)
            )
        except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
            LOG.warning("Skipping %s in the branch check: %s", config.name, error)
            continue
        accounted |= set(other.modules.values()) | set(other.tests.values())
        accounted |= set(other.data.values()) | set(other.dependency_modules)
        accounted.add(other.config_path.name)
        # The addon's own build output.
        ignore.append(other.zip_name.format(package=other.package, version="*"))
        ignore += other.check_ignore + other.excluded
    ignore += ["package_addon.py", "addon_package.example.toml", "**/__init__.py"]
    return [
        rel
        for rel in changed
        if rel not in accounted
        and not matches_any(rel, ignore)
        and (plan.repo_root / rel).exists()
    ]


# -------------------------------------------------------------------------
#
# Build
#
# -------------------------------------------------------------------------
def collect(
    plan: Plan,
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, bytes], int]:
    """
    Read and rewrite every member, logging warnings.

    :returns: (modules, tests, data, warning count).
    """
    rewriter = Rewriter(plan)
    warnings = 0
    modules = {
        name: rewriter.file((plan.repo_root / rel).read_bytes())
        for name, rel in plan.modules.items()
    }
    tests = {
        name: rewriter.file((plan.repo_root / rel).read_bytes())
        for name, rel in plan.tests.items()
    }
    data = {
        name: read_data_file(plan.repo_root / rel) for name, rel in plan.data.items()
    }
    for name, content in list(modules.items()) + [
        (f"tests/{n}", c) for n, c in tests.items()
    ]:
        for leftover in rewriter.leftovers(name, content):
            LOG.warning("Unrewritten core reference: %s", leftover)
            warnings += 1

    changed, detail = changed_files(plan.repo_root, plan.check_base)
    if changed is None:
        LOG.info("Branch check skipped: %s", detail)
    else:
        LOG.info("Branch check against %s", detail)
        for rel in unaccounted_files(plan, changed):
            LOG.warning("Changed on branch but not bundled or ignored: %s", rel)
            warnings += 1
    return modules, tests, data, warnings


def build_zip(plan: Plan, output: Path, version: str, pot: bool = True) -> Path:
    """
    Write the addon zip.

    The translation template is built before the output is touched, so a
    failed build leaves any previous zip in place.
    """
    modules, tests, data, _warnings = collect(plan)
    gpr = build_gpr(plan, version)
    po_template = build_translations(plan, modules, gpr) if pot else None
    pkg = plan.package

    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{pkg}/", b"")
        archive.writestr(f"{pkg}/{pkg}.gpr.py", gpr)
        for name in sorted(modules):
            archive.writestr(f"{pkg}/{name}", modules[name])
        if tests:
            archive.writestr(f"{pkg}/tests/", b"")
            archive.writestr(f"{pkg}/tests/__init__.py", build_tests_init(plan))
            for name in sorted(tests):
                archive.writestr(f"{pkg}/tests/{name}", tests[name])
        if data:
            archive.writestr(f"{pkg}/tests/{plan.data_target}/", b"")
            for name in sorted(data):
                archive.writestr(f"{pkg}/tests/{plan.data_target}/{name}", data[name])
        if po_template is not None:
            archive.writestr(f"{pkg}/po/", b"")
            archive.writestr(f"{pkg}/po/template.pot", po_template)
    LOG.info(
        "Wrote %s (%d modules, %d tests, %d data files, %d bytes)",
        output,
        len(modules),
        len(tests),
        len(data),
        output.stat().st_size,
    )
    return output


# -------------------------------------------------------------------------
#
# Command line
#
# -------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build a standalone Gramps addon zip from addon_package.toml."
    )
    parser.add_argument(
        "version_pos",
        nargs="?",
        default=None,
        metavar="VERSION",
        help="Addon version (default: 0.0.1); overrides --version.",
    )
    parser.add_argument(
        "--version",
        dest="version_opt",
        default="0.0.1",
        help="Addon version (default: 0.0.1).",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help=f"Config file (default: {DEFAULT_CONFIG} next to this script).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Destination zip (default: zip_name from the config, in the repo root).",
    )
    parser.add_argument(
        "--skip-pot", action="store_true", help="Do not generate po/template.pot."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only report what would be bundled and any warnings.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        metavar="FILE",
        help="Also write all output to FILE (e.g. package_output.txt).",
    )
    return parser.parse_args(argv)


def fix_windows_console() -> None:
    """
    Make a Windows console process line breaks and wrap long lines.

    A console left with "processed output" off shows CR/LF as the symbols
    ♪◙ and cuts every line at the window width. Turning the two flags back
    on is harmless when they are already set, and the calls simply fail
    when output is redirected to a file or pipe.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        processed_output, wrap_at_eol = 0x0001, 0x0002
        for std_handle in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(std_handle)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(
                    handle, mode.value | processed_output | wrap_at_eol
                )
    except (AttributeError, OSError):
        pass


def setup_logging(verbose: bool, log_file: Path | None) -> None:
    """
    Send all messages to standard output (so a plain ``> file`` captures
    everything, in order) and optionally to a log file as well.
    """
    fix_windows_console()
    for stream in (sys.stdout, sys.stderr):
        try:
            # Non-UTF-8 consoles: replace characters they cannot show
            # instead of crashing.
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file, mode="w", encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    """Build (or check) the addon and report the result."""
    args = parse_args(argv)
    setup_logging(args.verbose, args.log)
    script_dir = Path(__file__).resolve().parent
    config = args.config or script_dir / DEFAULT_CONFIG
    if not config.is_absolute():
        config = Path.cwd() / config
    version = args.version_pos if args.version_pos is not None else args.version_opt
    try:
        plan = load_plan(config)
        if args.log is not None:
            # The log file is this run's own output, not a branch change.
            try:
                log_rel = args.log.resolve().relative_to(plan.repo_root).as_posix()
                plan.check_ignore.append(log_rel)
            except ValueError:
                pass
        if args.check:
            LOG.info("Config: %s", plan.config_path)
            for label, items in (
                ("Module", plan.modules.values()),
                ("Test", plan.tests.values()),
                ("Data", plan.data.values()),
                ("From dependency", plan.dependency_modules),
            ):
                for rel in items:
                    LOG.info("%-15s %s", label, rel)
            _m, _t, _d, warnings = collect(plan)
            LOG.info("%d warning(s)", warnings)
            return 1 if warnings else 0
        output = args.output
        if output is None:
            output = plan.repo_root / plan.zip_name.format(
                package=plan.package, version=version
            )
        elif not output.is_absolute():
            output = plan.repo_root / output
        built = build_zip(plan, output, version, pot=not args.skip_pot)
    except (FileNotFoundError, ValueError, tomllib.TOMLDecodeError) as error:
        LOG.error("%s", error)
        return 1
    except subprocess.CalledProcessError as error:
        LOG.error("xgettext failed (exit %s)", error.returncode)
        return 1
    print(str(built))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
