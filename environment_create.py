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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""Set up a Gramps-from-source debug env. Run: python environment_create.py."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)

MSYS_ROOT = Path(r"C:\Program Files\Msys64")
MSYS_PYTHON = MSYS_ROOT / "mingw64" / "bin" / "python3.exe"
MSYS_PATHS = [
    str(MSYS_ROOT / "mingw64" / "bin"),
    str(MSYS_ROOT / "ucrt64" / "bin"),
    str(MSYS_ROOT / "usr" / "bin"),
]

LAUNCH_JSON = {
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug Gramps outside MSYS2",
            "type": "debugpy",
            "request": "launch",
            "python": str(MSYS_PYTHON),
            "program": "${workspaceFolder}/Gramps.py",
            "cwd": "${workspaceFolder}",
            "console": "integratedTerminal",
            "env": {
                "GIO_USE_VFS": "local",
                "GRAMPS_RESOURCES": "${workspaceFolder}/build/share",
                "PATH": ";".join(MSYS_PATHS + ["${env:PATH}"]),
            },
        }
    ],
}

SETTINGS_JSON = {
    "python.testing.unittestArgs": ["-v", "-s", ".", "-p", "*test*.py"],
    "python.testing.pytestEnabled": False,
    "python.testing.unittestEnabled": True,
}


# ------------------------------------------------------------
#
# Helpers
#
# ------------------------------------------------------------
def find_msys_python() -> Path:
    """Return MSYS2 mingw64 python, falling back to PATH."""
    if MSYS_PYTHON.is_file():
        return MSYS_PYTHON
    found = shutil.which("python3")
    if found:
        return Path(found)
    raise FileNotFoundError("MSYS2 python not found at %s." % MSYS_PYTHON)


def write_vscode(target: Path) -> None:
    """Write the .vscode files needed for F5."""
    vscode = target / ".vscode"
    vscode.mkdir(exist_ok=True)
    (vscode / "launch.json").write_text(json.dumps(LAUNCH_JSON, indent=4) + "\n")
    (vscode / "settings.json").write_text(json.dumps(SETTINGS_JSON, indent=2) + "\n")
    LOG.info("Wrote %s", vscode / "launch.json")


def resources_ok(target: Path) -> bool:
    """Check build/share satisfies resourcepath.py."""
    return (target / "build" / "share" / "gramps" / "authors.xml").is_file()


def build_resources(target: Path, msys_python: Path) -> None:
    """Run wheel build whose hook generates build/share."""
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(MSYS_PATHS + [env.get("PATH", "")])
    cmd = [str(msys_python), "-m", "build", "--wheel", "--no-isolation"]
    LOG.info("Building resources in %s ...", target)
    subprocess.run(cmd, cwd=str(target), env=env, check=True)


def create_environment(target: Path, no_build: bool = False) -> None:
    """Create everything needed for F5 in a Gramps checkout."""
    target = target.resolve()
    if not (target / "Gramps.py").is_file():
        raise ValueError("Not a Gramps checkout: %s" % target)
    msys_python = find_msys_python()
    LOG.info("Target: %s", target)
    write_vscode(target)
    if resources_ok(target):
        LOG.info("build/share present, skipping build.")
    elif no_build:
        LOG.warning("build/share missing; re-run without --no-build.")
    else:
        build_resources(target, msys_python)
    if not resources_ok(target):
        raise RuntimeError("build/share/gramps/authors.xml still missing.")
    LOG.info("Done. Press F5 in VS Code.")


def main(argv: list[str] | None = None) -> int:
    """Parse args and create the debug environment."""
    parser = argparse.ArgumentParser(description="Set up Gramps F5 debug env.")
    parser.add_argument("--target", default=".", help="Gramps checkout dir.")
    parser.add_argument("--no-build", action="store_true", help="Only write .vscode.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        create_environment(Path(args.target), no_build=args.no_build)
    except Exception as exc:
        LOG.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
