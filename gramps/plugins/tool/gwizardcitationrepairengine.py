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

"""Database repair engine for the GWizard citation fix tool (no GUI)."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import re
from collections import defaultdict
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db import DbTxn
from gramps.gen.lib import Repository, RepositoryType, RepoRef, Url, UrlType
from gramps.plugins.tool.goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizardcitationshared import (
    detect_title_elements,
    is_debris_text,
    is_tree_source_title,
    normalize_repo_name,
    normalize_source_title,
    note_text,
    split_conflated_title,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# Gold-standard "type" text -> Gramps repository type constant.
_GOLD_REPO_TYPES = {
    "Web site": RepositoryType.WEBSITE,
    "Archive": RepositoryType.ARCHIVE,
    "Library": RepositoryType.LIBRARY,
}


# ------------------------------------------------------------
#
# GWizardCitationRepairEngine
#
# ------------------------------------------------------------
class GWizardCitationRepairEngine:
    """Safe database transformations for each step of the citation fix tool.

    Every public method that changes the database does so inside one
    DbTxn, so a whole step can be undone with Edit > Undo.
    """

    # ------------------------------------------------------------
    # Step 1: unpack conflated source titles
    # ------------------------------------------------------------
    def plan_unpack_conflated_sources(self, db: Any) -> list[dict[str, Any]]:
        """Return the proposed splits without touching the database."""
        plan: list[dict[str, Any]] = []
        for source in db.iter_sources():
            title = str(source.get_title() or "")
            if len(detect_title_elements(title)) < 2:
                continue
            result = split_conflated_title(title)
            if result is None:
                continue
            plan.append(
                {
                    "handle": source.get_handle(),
                    "gramps_id": str(source.get_gramps_id() or ""),
                    "old_title": title,
                    "repo_name": result["repo_name"],
                    "new_title": result["new_title"],
                    "moved_text": result["moved_text"],
                    "apply": True,
                }
            )
        return plan

    def apply_unpack_plan(self, db: Any, plan: list[dict[str, Any]]) -> int:
        """Apply the entries of an unpack plan that are marked ``apply``."""
        repo_map: dict[str, str] = {}
        for repo in db.iter_repositories():
            key = normalize_repo_name(str(repo.get_name() or ""))
            if key:
                repo_map.setdefault(key, repo.get_handle())

        count = 0
        with DbTxn(_("Unpack Conflated Fields"), db) as trans:
            for entry in plan:
                if not entry.get("apply", True):
                    continue
                repo_name = str(entry.get("repo_name") or "").strip()
                new_title = str(entry.get("new_title") or "").strip()
                if not repo_name or not new_title:
                    continue
                try:
                    source = db.get_source_from_handle(entry["handle"])
                    if source is None:
                        continue
                    key = normalize_repo_name(repo_name)
                    repo_handle = repo_map.get(key)
                    if not repo_handle:
                        repo_handle = self._create_repository(db, repo_name, trans)
                        repo_map[key] = repo_handle
                    linked = any(
                        ref.get_reference_handle() == repo_handle
                        for ref in source.get_reporef_list()
                    )
                    if not linked:
                        repo_ref = RepoRef()
                        repo_ref.set_reference_handle(repo_handle)
                        source.add_repo_reference(repo_ref)
                    source.set_title(new_title)
                    moved = str(entry.get("moved_text") or "").strip()
                    if moved:
                        pubinfo = str(source.get_publication_info() or "").strip()
                        source.set_publication_info(
                            "%s; %s" % (pubinfo, moved) if pubinfo else moved
                        )
                    db.commit_source(source, trans)
                    count += 1
                except Exception:  # pylint: disable=broad-except
                    LOG.exception("Failed to unpack source %s", entry.get("handle"))
        return count

    def unpack_conflated_sources(self, db: Any) -> int:
        """Plan and apply the unpack step with no review."""
        return self.apply_unpack_plan(db, self.plan_unpack_conflated_sources(db))

    @staticmethod
    def _create_repository(db: Any, name: str, trans: Any) -> str:
        """Add a repository, filling type and URL for gold-standard names."""
        repo = Repository()
        repo.set_name(name)
        gold = GoldStandardRepositories.get_by_name(name)
        if gold:
            repo_type = _GOLD_REPO_TYPES.get(gold.get("type", ""))
            if repo_type is not None:
                repo.set_type(repo_type)
            if gold.get("url"):
                url = Url()
                url.set_path(gold["url"])
                url.set_type(UrlType.WEB_HOME)
                repo.add_url(url)
        db.add_repository(repo, trans)
        return repo.get_handle()

    # ------------------------------------------------------------
    # Step 2: repositories
    # ------------------------------------------------------------
    def merge_repositories(
        self, db: Any, keeper_handle: str, discard_handle: str, trans: Any = None
    ) -> bool:
        """Merge one repository into another, re-pointing every source."""
        if trans is None:
            with DbTxn(_("Merge repositories"), db) as new_trans:
                return self.merge_repositories(
                    db, keeper_handle, discard_handle, new_trans
                )
        if keeper_handle == discard_handle:
            return False
        keeper = db.get_repository_from_handle(keeper_handle)
        discard = db.get_repository_from_handle(discard_handle)
        if keeper is None or discard is None:
            return False
        for _cls, source_handle in list(
            db.find_backlink_handles(discard_handle, ["Source"])
        ):
            source = db.get_source_from_handle(source_handle)
            if source is not None:
                source.replace_repo_references(discard_handle, keeper_handle)
                db.commit_source(source, trans)
        keeper.merge(discard)
        db.commit_repository(keeper, trans)
        db.remove_repository(discard_handle, trans)
        return True

    def consolidate_duplicate_repositories(self, db: Any) -> int:
        """Merge repositories whose names normalize to the same text."""
        groups: dict[str, list[Any]] = defaultdict(list)
        for repo in db.iter_repositories():
            key = normalize_repo_name(str(repo.get_name() or ""))
            if key:
                groups[key].append(repo)

        golden_names = set(GoldStandardRepositories.get_names())

        def rank(repo: Any) -> tuple[Any, ...]:
            uses = len(list(db.find_backlink_handles(repo.get_handle(), ["Source"])))
            return (
                str(repo.get_name() or "") not in golden_names,
                -uses,
                str(repo.get_gramps_id() or ""),
            )

        merged = 0
        with DbTxn(_("Consolidate Repositories"), db) as trans:
            for group in groups.values():
                if len(group) < 2:
                    continue
                group.sort(key=rank)
                keeper = group[0]
                for duplicate in group[1:]:
                    if self.merge_repositories(
                        db, keeper.get_handle(), duplicate.get_handle(), trans
                    ):
                        merged += 1
        return merged

    # ------------------------------------------------------------
    # Step 3: sources
    # ------------------------------------------------------------
    def merge_sources(
        self, db: Any, keeper_handle: str, discard_handle: str, trans: Any = None
    ) -> bool:
        """Merge one source into another, re-pointing every citation."""
        if trans is None:
            with DbTxn(_("Merge sources"), db) as new_trans:
                return self.merge_sources(db, keeper_handle, discard_handle, new_trans)
        if keeper_handle == discard_handle:
            return False
        keeper = db.get_source_from_handle(keeper_handle)
        discard = db.get_source_from_handle(discard_handle)
        if keeper is None or discard is None:
            return False
        for _cls, citation_handle in list(
            db.find_backlink_handles(discard_handle, ["Citation"])
        ):
            citation = db.get_citation_from_handle(citation_handle)
            if citation is not None:
                citation.set_reference_handle(keeper_handle)
                db.commit_citation(citation, trans)
        keeper.merge(discard)
        db.commit_source(keeper, trans)
        db.remove_source(discard_handle, trans)
        return True

    def consolidate_duplicate_sources(self, db: Any) -> int:
        """Merge sources whose titles normalize to the same text."""
        groups: dict[str, list[Any]] = defaultdict(list)
        for source in db.iter_sources():
            key = normalize_source_title(str(source.get_title() or ""))
            if key:
                groups[key].append(source)

        def rank(source: Any) -> tuple[Any, ...]:
            cites = len(list(db.find_backlink_handles(source.get_handle(), ["Citation"])))
            return (
                -len(list(source.get_reporef_list())),
                -cites,
                str(source.get_gramps_id() or ""),
            )

        merged = 0
        with DbTxn(_("Consolidate Sources"), db) as trans:
            for group in groups.values():
                if len(group) < 2:
                    continue
                group.sort(key=rank)
                keeper = group[0]
                for duplicate in group[1:]:
                    if self.merge_sources(
                        db, keeper.get_handle(), duplicate.get_handle(), trans
                    ):
                        merged += 1
        return merged

    # ------------------------------------------------------------
    # Step 4: citations
    # ------------------------------------------------------------
    def clean_and_rate_citations(self, db: Any) -> int:
        """Downrate user-tree citations and tidy the Volume/Page text."""
        tree_handles = {
            str(src.get_handle())
            for src in db.iter_sources()
            if is_tree_source_title(str(src.get_title() or ""))
        }
        fixed = 0
        with DbTxn(_("Clean Citations and Confidence"), db) as trans:
            for citation in list(db.iter_citations()):
                modified = False
                if str(citation.get_reference_handle() or "") in tree_handles:
                    # Gramps confidence: 0 Very Low ... 4 Very High.
                    if int(citation.get_confidence_level()) >= 3:
                        citation.set_confidence_level(2)
                        modified = True
                page = str(citation.get_page() or "")
                if page:
                    cleaned = re.sub(r"^[,\.\s;]+|[,\.\s;]+$", "", page.strip())
                    cleaned = re.sub(r"\s+", " ", cleaned)
                    if cleaned != page:
                        citation.set_page(cleaned)
                        modified = True
                if modified:
                    db.commit_citation(citation, trans)
                    fixed += 1
        return fixed

    # ------------------------------------------------------------
    # Step 5: notes
    # ------------------------------------------------------------
    def purge_import_debris_notes(self, db: Any) -> int:
        """Remove import-debris notes and every reference to them."""
        purged = 0
        with DbTxn(_("Purge Import Debris Notes"), db) as trans:
            for note in list(db.iter_notes()):
                if not is_debris_text(note_text(note).strip()):
                    continue
                note_handle = note.get_handle()
                for cls_name, parent_handle in list(
                    db.find_backlink_handles(note_handle)
                ):
                    getter = getattr(db, "get_%s_from_handle" % cls_name.lower(), None)
                    commit = getattr(db, "commit_%s" % cls_name.lower(), None)
                    if getter is None or commit is None:
                        LOG.warning("Cannot detach note from %s", cls_name)
                        continue
                    parent = getter(parent_handle)
                    if parent is not None:
                        parent.remove_handle_references("Note", [note_handle])
                        commit(parent, trans)
                db.remove_note(note_handle, trans)
                purged += 1
        return purged
