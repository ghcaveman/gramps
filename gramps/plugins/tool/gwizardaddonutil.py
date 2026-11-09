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

"""Shared launch logic for the GWizard tool wrappers."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import importlib
import logging
from typing import Any, Callable

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


def _show_error(title: str, message: str, parent: Any = None) -> None:
    """Show an error dialog; fall back to the log if no GUI is available."""
    try:
        from gramps.gui.dialog import ErrorDialog

        ErrorDialog(title, message, parent=parent)
    except Exception:  # pylint: disable=broad-except
        LOG.error("%s: %s", title, message)


def resolve_launcher(
    addon_module: str, core_module: str, func_name: str
) -> Callable[..., Any]:
    """
    Import the launcher function from the addon or, failing that, from core.

    Only a missing *launcher module* triggers the fallback.  If the launcher
    exists but one of its own imports is missing (``requests``, a sibling
    module, ...) that error propagates unchanged, so the user sees the real
    cause instead of a misleading error from the core path.
    """
    try:
        module = importlib.import_module(addon_module)
    except ModuleNotFoundError as err:
        if err.name != addon_module:
            raise
        module = importlib.import_module(core_module)
    return getattr(module, func_name)


def run_flow(
    uistate: Any,
    dbstate: Any,
    *,
    addon_module: str,
    core_module: str,
    func_name: str,
    title: str,
) -> None:
    """Check preconditions, then run the launcher with errors shown to the user."""
    parent = getattr(uistate, "window", None)
    if uistate is None:
        LOG.error("%s needs the Gramps GUI; it cannot run from the command line", title)
        return
    if not dbstate.is_open():
        _show_error(title, _("Open a Family Tree before running this tool."), parent)
        return
    try:
        launcher = resolve_launcher(addon_module, core_module, func_name)
        launcher(uistate, dbstate, parent=parent)
    except Exception as err:  # pylint: disable=broad-except
        LOG.exception("%s failed", title)
        _show_error(title, _("The tool could not finish: %s") % err, parent)
