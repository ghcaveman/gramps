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

"""Source consolidate dialog for the GWizard citation fix tool."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
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
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardconsolidatebase import ConsolidateDialogBase

_ = glocale.translation.sgettext


# ------------------------------------------------------------
#
# SourceConsolidateDialog
#
# ------------------------------------------------------------
class SourceConsolidateDialog(ConsolidateDialogBase):
    """Merge one source into another, moving its citations."""

    def __init__(self, dbstate: Any, transient_for: Gtk.Window | None = None) -> None:
        super().__init__(
            str(_("Source Consolidate")),
            dbstate,
            transient_for=transient_for,
            default_size=(800, 600),
        )
        self.engine = GWizardCitationRepairEngine()

    def get_handles(self) -> list[str]:
        return list(self.dbstate.db.get_source_handles())

    def get_label(self, handle: str) -> str:
        source = self.dbstate.db.get_source_from_handle(handle)
        if source is None:
            return handle
        return "%s (%s)" % (source.get_title() or str(_("(unnamed)")), source.get_gramps_id())

    def merge(self, keeper_handle: str, discard_handle: str) -> bool:
        return self.engine.merge_sources(self.dbstate.db, keeper_handle, discard_handle)
