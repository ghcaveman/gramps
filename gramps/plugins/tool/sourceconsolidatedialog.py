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
from collections import Counter
import difflib
import logging
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
from gramps.plugins.tool.gwizardcitationshared import (
    normalize_source_title,
    suggest_source_merge_target,
)
from gramps.plugins.tool.gwizardconsolidatebase import ConsolidateDialogBase

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# SourceConsolidateDialog
#
# ------------------------------------------------------------
class SourceConsolidateDialog(ConsolidateDialogBase):
    """Merge one source into another, moving its citations."""

    def __init__(self, dbstate: Any, transient_for: Gtk.Window | None = None) -> None:
        self.engine = GWizardCitationRepairEngine()
        self._cites_by_source: Counter[str] | None = None
        super().__init__(
            str(_("Source Consolidate")),
            dbstate,
            transient_for=transient_for,
            default_size=(1260, 600),
            has_hint_column=True,
        )

    def get_handles(self) -> list[str]:
        """Return all source handles in the database."""
        return list(self.dbstate.db.get_source_handles())

    def get_label(self, handle: str) -> str:
        """Return display title and gramps_id for a source handle."""
        source = self.dbstate.db.get_source_from_handle(handle)
        if source is None:
            return handle
        return "%s (%s)" % (
            source.get_title() or str(_("(unnamed)")),
            source.get_gramps_id(),
        )

    def merge(self, keeper_handle: str, discard_handle: str) -> bool:
        """Merge discard source into keeper source."""
        return self.engine.merge_sources(self.dbstate.db, keeper_handle, discard_handle)

    def _get_citations_count(self, handle: str) -> int:
        """Return the number of citations referencing this source handle."""
        if self._cites_by_source is None:
            self._cites_by_source = Counter()
            try:
                db = self.dbstate.db
                if hasattr(db, "get_citation_handles"):
                    for cit_handle in db.get_citation_handles():
                        cit = db.get_citation_from_handle(cit_handle)
                        if cit is not None:
                            src_h = cit.get_reference_handle()
                            if src_h:
                                self._cites_by_source[str(src_h)] += 1
            except Exception:
                LOG.exception("Failed to collect citation counts")
        if handle in self._cites_by_source:
            return self._cites_by_source[handle]
        try:
            db = self.dbstate.db
            if hasattr(db, "find_backlink_handles"):
                return len(list(db.find_backlink_handles(handle, ["Citation"])))
        except Exception:
            pass
        return 0

    def compute_hint(self, selected_handle: str) -> tuple[str, str] | None:
        """Suggest a merge target source with a reason, similar to RepoMergeDialog."""
        if self._cites_by_source is None:
            self._get_citations_count(selected_handle)
        return suggest_source_merge_target(
            selected_handle,
            self.target_handles,
            self.dbstate.db,
            self._cites_by_source,
        )
