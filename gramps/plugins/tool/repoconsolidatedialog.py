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

"""Repository consolidate dialog for the GWizard citation fix tool."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
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
from gramps.gen.db import DbTxn
from gramps.gui.dialog import ErrorDialog, OkDialog
from gramps.plugins.tool.goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardconsolidatebase import ConsolidateDialogBase

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# RepoConsolidateDialog
#
# ------------------------------------------------------------
class RepoConsolidateDialog(ConsolidateDialogBase):
    """Merge one repository into another.

    Gold-standard repository names are offered as additional merge
    targets on the right-hand side. When a golden target that does not
    yet exist in the database is chosen, it is created before the merge.
    """

    def __init__(self, dbstate: Any, transient_for: Gtk.Window | None = None) -> None:
        # Initialise before super().__init__() because the base class calls
        # self.update_combo() during construction, which iterates
        # self.golden_targets.
        self.engine = GWizardCitationRepairEngine()
        self.golden_targets: list[str] = []
        super().__init__(
            str(_("Repository Consolidate")),
            dbstate,
            transient_for=transient_for,
            default_size=(1120, 600),
        )
        self._add_golden_targets()

    def _add_golden_targets(self) -> None:
        """Add gold-standard repository names as extra merge targets.

        Only names that do not already exist as repositories in the
        database are added, to avoid duplicating entries that are
        already reachable through their database handle. The names are
        sorted alphabetically and appear after the database repositories.
        """
        existing_names: set[str] = set()
        for handle in self.handles:
            repo = self.dbstate.db.get_repository_from_handle(handle)
            if repo is not None:
                name = repo.get_name()
                if name:
                    existing_names.add(name)
        self.golden_targets = sorted(
            (
                name
                for name in GoldStandardRepositories.get_names()
                if name not in existing_names
            ),
            key=str.lower,
        )
        for name in self.golden_targets:
            self.combo.append_text(name)

    def update_combo(self) -> None:
        """Refresh the target combo, re-adding golden targets after DB repos."""
        super().update_combo()
        for name in self.golden_targets:
            self.combo.append_text(name)

    def get_handles(self) -> list[str]:
        return list(self.dbstate.db.get_repository_handles())

    def get_label(self, handle: str) -> str:
        repo = self.dbstate.db.get_repository_from_handle(handle)
        if repo is None:
            return handle
        return "%s (%s)" % (
            repo.get_name() or str(_("(unnamed)")),
            repo.get_gramps_id(),
        )

    def _resolve_golden_keeper(self, db: Any, golden_name: str) -> str | None:
        """Return the handle for a golden repository, creating it if needed.

        :param db: The database.
        :param golden_name: The gold-standard repository name.
        :returns: The repository handle, or ``None`` on failure.
        """
        # Already exists in the database?
        for handle in db.get_repository_handles():
            repo = db.get_repository_from_handle(handle)
            if repo is not None and repo.get_name() == golden_name:
                return handle
        # Create it within a transaction.
        try:
            with DbTxn(_("Create repository"), db) as trans:
                return self.engine._create_repository(db, golden_name, trans)
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to create golden repository %s", golden_name)
            return None

    def merge(self, keeper_handle: str, discard_handle: str) -> bool:
        return self.engine.merge_repositories(
            self.dbstate.db, keeper_handle, discard_handle
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        discard = self.selected_handle()
        index = self.combo.get_active()
        total = len(self.target_handles) + len(self.golden_targets)
        if discard is None or index < 0 or index >= total:
            return
        db = self.dbstate.db
        if index < len(self.target_handles):
            keeper = self.target_handles[index]
        else:
            golden_index = index - len(self.target_handles)
            keeper = self._resolve_golden_keeper(db, self.golden_targets[golden_index])
            if keeper is None:
                return
        try:
            merged = self.merge(keeper, discard)
        except Exception as error:  # pylint: disable=broad-except
            LOG.exception("Consolidate failed")
            ErrorDialog(str(_("Consolidate failed")), str(error), parent=self)
            return
        if merged:
            OkDialog(str(_("Done")), str(_("Consolidated")), parent=self)
        self.destroy()
