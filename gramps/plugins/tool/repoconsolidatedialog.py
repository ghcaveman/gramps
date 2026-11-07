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
from gramps.gen.lib import Note, NoteType
from gramps.gui.dialog import ErrorDialog, OkDialog
from gramps.plugins.tool.goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardconsolidatebase import ConsolidateDialogBase

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


def _strip_the(text: str) -> str:
    """Return text lower-cased with a leading 'the ' removed."""
    low = " ".join((text or "").split()).casefold()
    return low[4:] if low.startswith("the ") else low


def classify_repo_street(repo_name: str, street: str) -> tuple[str, str]:
    """Decide what to do with a repository address street line.

    :returns: ``(action, detail)`` where action is ``"keep"`` (a real
        address), ``"drop"`` (it only repeats the repository name) or
        ``"move"`` (it is the name followed by extra text, returned as
        *detail*, which belongs in a note rather than an address).
    """
    street = " ".join((street or "").split())
    if not street:
        return "keep", ""
    name_key = _strip_the(repo_name)
    street_key = _strip_the(street)
    if not name_key:
        return "keep", ""
    if street_key == name_key:
        return "drop", ""
    if street_key.startswith(name_key):
        # Use the original text for the remainder, minus any leading 'The'.
        base = street[4:] if street.casefold().startswith("the ") else street
        name_base = (
            " ".join(repo_name.split())[4:]
            if " ".join(repo_name.split()).casefold().startswith("the ")
            else " ".join(repo_name.split())
        )
        remainder = base[len(name_base) :].strip(" \t-:;,")
        remainder = remainder.strip("()[] ").strip()
        if remainder:
            return "move", remainder
        return "drop", ""
    return "keep", ""


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

    def _tidy_keeper_address(self, keeper_handle: str) -> tuple[int, int]:
        """Clean address lines on the surviving repository.

        An address line that only repeats the repository name is removed.
        When it is the name followed by extra text (for example
        "Registries (Genoa, IT / Broward County, FL)"), the extra text is
        saved in a repository note so the detail is kept, and the address
        line is cleared. Real addresses are left alone.

        :returns: ``(removed, moved)`` counts.
        """
        db = self.dbstate.db
        repo = db.get_repository_from_handle(keeper_handle)
        if repo is None:
            return 0, 0
        name = repo.get_name() or ""
        removed = moved = 0
        kept = []
        details: list[str] = []
        for addr in repo.get_address_list():
            action, detail = classify_repo_street(name, addr.get_street())
            if action == "keep":
                kept.append(addr)
                continue
            if action == "move":
                details.append(detail)
            addr.set_street("")
            others = (
                addr.get_locality(),
                addr.get_city(),
                addr.get_county(),
                addr.get_state(),
                addr.get_country(),
                addr.get_postal_code(),
                addr.get_phone(),
            )
            if any((value or "").strip() for value in others):
                kept.append(addr)
            else:
                removed += 1
        try:
            with DbTxn(_("Tidy repository address"), db) as trans:
                repo.set_address_list(kept)
                for detail in details:
                    text = str(_("Place detail from address: %s")) % detail
                    if any(
                        (db.get_note_from_handle(n_handle) is not None)
                        and db.get_note_from_handle(n_handle).get() == text
                        for n_handle in repo.get_note_list()
                    ):
                        continue
                    note = Note()
                    note.set(text)
                    note.set_type(NoteType.REPO)
                    note_handle = db.add_note(note, trans)
                    repo.add_note(note_handle)
                    moved += 1
                db.commit_repository(repo, trans)
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to tidy address for repository %s", name)
            return 0, 0
        return removed, moved

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
        created_keeper = False
        if index < len(self.target_handles):
            keeper = self.target_handles[index]
        else:
            golden_index = index - len(self.target_handles)
            golden_name = self.golden_targets[golden_index]
            existed = any(
                (db.get_repository_from_handle(h) is not None)
                and db.get_repository_from_handle(h).get_name() == golden_name
                for h in db.get_repository_handles()
            )
            keeper = self._resolve_golden_keeper(db, golden_name)
            if keeper is None:
                ErrorDialog(
                    str(_("Consolidate failed")),
                    str(_("Could not create repository '%s'.")) % golden_name,
                    parent=self,
                )
                return
            created_keeper = not existed
        if keeper == discard:
            ErrorDialog(
                str(_("Consolidate failed")),
                str(_("Choose a different repository to merge into.")),
                parent=self,
            )
            return
        try:
            merged = self.merge(keeper, discard)
        except Exception as error:  # pylint: disable=broad-except
            LOG.exception("Consolidate failed")
            self._discard_unused_keeper(keeper, created_keeper)
            ErrorDialog(str(_("Consolidate failed")), str(error), parent=self)
            return
        if not merged:
            self._discard_unused_keeper(keeper, created_keeper)
            ErrorDialog(
                str(_("Consolidate failed")),
                str(_("The repositories were not merged. Nothing was changed.")),
                parent=self,
            )
            return
        removed, moved = self._tidy_keeper_address(keeper)
        message = str(_("Consolidated."))
        if removed:
            message += " " + str(_("Removed %d address line that repeated the name.")) % removed
        if moved:
            message += " " + str(_("Moved place detail from %d address into a note.")) % moved
        OkDialog(str(_("Done")), message, parent=self)
        self.destroy()

    def _discard_unused_keeper(self, keeper_handle: str, created: bool) -> None:
        """Remove a gold-standard repository created just for a failed merge."""
        if not created:
            return
        db = self.dbstate.db
        try:
            repo = db.get_repository_from_handle(keeper_handle)
            if repo is None or any(True for _ in db.find_backlink_handles(keeper_handle)):
                return
            with DbTxn(_("Remove unused repository"), db) as trans:
                db.remove_repository(keeper_handle, trans)
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Could not remove unused repository %s", keeper_handle)
