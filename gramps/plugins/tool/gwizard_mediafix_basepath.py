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

"""
Ask for the family tree's base media path before a GWizard tool opens.

A freshly imported family tree has no base media path, and Gramps then
reads (and the GWizard tools would write) relative media paths in the
user's Pictures folder. Each GWizard tool (Media Fix, Citation Fix and the
record-source merges) calls :func:`ensure_base_media_path` before opening
its window: when no base media path is set it offers to choose the folder
now. The tool opens either way; anything that needs the folder is skipped
until one is set.

The folder is saved with Media Fix's set_base_media_path, so media records
that already point at files keep pointing at them.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.dialog import OkDialog, QuestionDialog2

# -------------------------------------------------------------------------
#
# GWizard modules
#
# -------------------------------------------------------------------------
try:
    from .gwizard_mediafix_common import clean_path
    from .gwizardmediafix import (
        base_change_summary,
        get_media_base_path,
        set_base_media_path,
    )
except (ImportError, ValueError):
    from gwizard_mediafix_common import (  # type: ignore[import-not-found,no-redef]
        clean_path,
    )
    from gwizardmediafix import (  # type: ignore[import-not-found,no-redef]
        base_change_summary,
        get_media_base_path,
        set_base_media_path,
    )

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


def base_media_path_set(db: Any) -> bool:
    """Return True when the family tree has a base media path of its own."""
    try:
        return bool((db.get_mediapath() or "").strip())
    except Exception:  # pylint: disable=broad-except
        return False


def choose_base_media_path(db: Any, parent: Any = None) -> bool:
    """
    Let the user pick the base media folder and save it to the tree.

    :param db: The database.
    :param parent: Parent window.
    :returns: Whether a base media path was saved.
    """
    chooser = Gtk.FileChooserDialog(
        title=str(_("Select the base media folder")),
        transient_for=parent,
        action=Gtk.FileChooserAction.SELECT_FOLDER,
        buttons=(
            str(_("_Cancel")),
            Gtk.ResponseType.CANCEL,
            str(_("_Select")),
            Gtk.ResponseType.OK,
        ),
    )
    start = get_media_base_path(db)
    if start and os.path.isdir(start):
        chooser.set_current_folder(start)
    folder = chooser.get_filename() if chooser.run() == Gtk.ResponseType.OK else ""
    chooser.destroy()
    if not folder:
        return False
    rebased = set_base_media_path(db, clean_path(folder))
    extra = base_change_summary(rebased)
    if extra:
        OkDialog(str(_("Base media path saved")), extra, parent=parent)
    return True


def ask_for_base_path(db: Any, parent: Any, message: str) -> bool:
    """
    Explain that no base media path is set and offer to choose one.

    :param db: The database.
    :param parent: Parent window.
    :param message: Why the folder is needed, and what happens without it.
    :returns: Whether a base media path was set.
    """
    question = QuestionDialog2(
        str(_("No base media path")),
        message,
        str(_("_Choose folder...")),
        str(_("_Continue without")),
        parent=parent,
    )
    if not question.run():
        return False
    return choose_base_media_path(db, parent)


def ensure_base_media_path(dbstate: Any, parent: Any, tool_name: str) -> bool:
    """
    Before a GWizard tool opens: offer to set the base media path when the
    open family tree has none.

    Nothing is asked when no tree is open or a base media path is set. The
    caller opens its window whatever the answer.

    :param dbstate: The Gramps database state.
    :param parent: Parent window for the question.
    :param tool_name: The tool's name, as shown in the menu.
    :returns: Whether the tree has a base media path afterwards.
    """
    db = getattr(dbstate, "db", None)
    try:
        if db is None or not dbstate.is_open():
            return False
    except Exception:  # pylint: disable=broad-except
        return False
    if base_media_path_set(db):
        return True
    message = str(
        _(
            "No base media path is set for this family tree, so %(tool)s has "
            "no folder to save, move or rename media files in (Gramps would "
            "use %(default)s).\n\n"
            "Choose the folder now? It is saved to this family tree (the same "
            "setting as Edit > Preferences > Family Tree > Base media path). "
            "If you continue without one, %(tool)s still opens, and anything "
            "that needs the folder is skipped."
        )
    ) % {"tool": tool_name, "default": get_media_base_path(None)}
    return ask_for_base_path(db, parent, message)


def ensure_base_media_path_for(uistate: Any, dbstate: Any, tool_name: str) -> bool:
    """
    Call :func:`ensure_base_media_path` from a tool's ``__init__``: the
    question's parent is the Gramps main window. Any error is logged, never
    raised, so the tool still opens.
    """
    try:
        return ensure_base_media_path(
            dbstate, getattr(uistate, "window", None), tool_name
        )
    except Exception as err:  # pylint: disable=broad-except
        LOG.warning("Could not check the base media path: %s", err)
        return False
