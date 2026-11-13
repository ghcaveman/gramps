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
from gramps.gen.errors import HandleError
from gramps.gen.lib import (
    Note,
    NoteType,
    Repository,
    RepositoryType,
    RepoRef,
    Url,
    UrlType,
)
from gramps.plugins.tool.gw_goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizardcitationshared import (
    clean_source_title,
    detect_title_elements,
    is_debris_text,
    is_tree_source_title,
    normalize_repo_name,
    normalize_source_title,
    note_text,
    split_conflated_title,
    unpacked_abbreviation,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# Gold-standard "type" text -> Gramps repository type constant.
_GOLD_REPO_TYPES = {
    "Web site": RepositoryType.WEBSITE,
    "Archive": RepositoryType.ARCHIVE,
    "Library": RepositoryType.LIBRARY,
    "Collection": RepositoryType.COLLECTION,
    "Government Office": RepositoryType.ARCHIVE,
}


# ------------------------------------------------------------
#
# GWizardCitationRepairEngine
#
# ------------------------------------------------------------
class GWizardCitationRepairEngine:
    """Safe database transformations for each step of the citation fix tool.

    Every public method that changes the database does so inside one
    DbTxn, so a whole step can be undone with Edit > Undo. Methods that
    take a ``trans`` argument join that transaction instead of opening
    their own, so callers can group several operations into one undo.
    """

    last_abbreviations_updated: int = 0

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
        # Titles with markup, citation-style quotes or a bare website address
        # are cleaned too, for sources the split above did not already plan.
        planned = {str(item["handle"]) for item in plan}
        for source in db.iter_sources():
            handle = str(source.get_handle())
            if handle in planned:
                continue
            old_title = str(source.get_title() or "")
            new_title, moved, repo_name, reason = clean_source_title(old_title)
            if not new_title and not moved and not repo_name:
                continue
            plan.append(
                {
                    "handle": handle,
                    "gramps_id": str(source.get_gramps_id() or ""),
                    "old_title": old_title,
                    "repo_name": repo_name,
                    "new_title": new_title or old_title.strip(),
                    "moved_text": moved,
                    "reason": reason,
                    "apply": True,
                }
            )
        return plan

    def apply_unpack_plan(self, db: Any, plan: list[dict[str, Any]]) -> int:
        """Apply the entries of an unpack plan that are marked ``apply``."""
        return self.apply_unpack_entries(
            db, [entry for entry in plan if entry.get("apply", True)]
        )

    def apply_unpack_entries(
        self, db: Any, entries: list[dict[str, Any]], trans: Any = None
    ) -> int:
        """Apply unpack entries; the one implementation used by every caller.

        Each entry holds ``handle`` and any of ``repo_name``, ``new_title``
        and ``moved_text``. A blank field is left alone, so the review
        dialog (which may leave some target columns empty) and the
        no-review path behave identically. Returns the number of sources
        changed.
        """
        if trans is None:
            self.last_abbreviations_updated = 0
            with DbTxn(_("Unpack Conflated Source"), db) as new_trans:
                return self.apply_unpack_entries(db, entries, new_trans)
        repo_map: dict[str, str] = {}
        for repo in db.iter_repositories():
            key = normalize_repo_name(str(repo.get_name() or ""))
            if key:
                repo_map.setdefault(key, repo.get_handle())

        count = 0
        for entry in entries:
            repo_name = str(entry.get("repo_name") or "").strip()
            new_title = str(entry.get("new_title") or "").strip()
            moved = str(entry.get("moved_text") or "").strip()
            if not repo_name and not new_title and not moved:
                continue
            source = db.get_source_from_handle(entry["handle"])
            if source is None:
                continue
            before = source.serialize()
            # A title-only entry (markup or quotes) has no repository.
            if repo_name:
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
            if new_title:
                new_abbrev = unpacked_abbreviation(
                    str(source.get_abbreviation() or ""),
                    str(source.get_title() or ""),
                    new_title,
                    repo_name,
                )
                source.set_title(new_title)
                if new_abbrev is not None:
                    source.set_abbreviation(new_abbrev)
                    self.last_abbreviations_updated += 1
            if moved:
                pubinfo = str(source.get_publication_info() or "").strip()
                source.set_publication_info(
                    "%s; %s" % (pubinfo, moved) if pubinfo else moved
                )
            if source.serialize() == before:
                continue  # already unpacked; leave it alone
            db.commit_source(source, trans)
            count += 1
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
            if str(gold.get("url") or "").startswith(("http://", "https://")):
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
        """Merge repositories whose names normalize to the same text.

        Name-only scripting helper. The GUI steps use the hint-based
        ``auto_consolidate_repositories`` in gw_repoconsolidatedialog instead.
        """
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
            self.apply_gold_standard_details(db, trans)
        return merged

    def apply_gold_standard_details(self, db: Any, trans: Any = None) -> int:
        """Give repositories matching the golden list its type and web address.

        GEDCOM carries no repository type, so imported repositories all start
        as Gramps' default (Library). Only that default is replaced; a type
        you chose yourself is never overwritten, and existing URLs are kept.
        """
        if trans is None:
            with DbTxn(_("Apply Gold Standard Repository Details"), db) as new_trans:
                return self.apply_gold_standard_details(db, new_trans)
        catalog = {
            normalize_repo_name(entry["name"]): entry
            for entry in GoldStandardRepositories.get_all()
        }
        changed = 0
        for repo in list(db.iter_repositories()):
            entry = catalog.get(normalize_repo_name(str(repo.get_name() or "")))
            if entry is None:
                continue
            modified = False
            wanted = _GOLD_REPO_TYPES.get(entry.get("type", ""))
            if (
                wanted is not None
                and repo.get_type().value == RepositoryType.LIBRARY
                and wanted != RepositoryType.LIBRARY
            ):
                repo.set_type(wanted)
                modified = True
            url_text = str(entry.get("url") or "")
            if url_text.startswith(("http://", "https://")) and not repo.get_url_list():
                url = Url()
                url.set_path(url_text)
                url.set_type(UrlType.WEB_HOME)
                repo.add_url(url)
                modified = True
            if modified:
                db.commit_repository(repo, trans)
                changed += 1
        return changed

    def reassign_source_repositories(
        self, db: Any, changes: list[dict[str, str]], trans: Any = None
    ) -> tuple[int, int]:
        """Point individual sources at the repositories chosen for them.

        Each change is ``{"source_handle", "old_repo_handle", "target_name"}``.
        ``old_repo_handle`` is the repository the row currently shows (empty
        for a source that has none). The target repository is found by name
        (ignoring case and punctuation) and created, with the type and web
        address from the golden list, when it does not exist yet.

        Returns ``(sources changed, repositories created)``.
        """
        if trans is None:
            with DbTxn(_("Change Source Repositories"), db) as new_trans:
                return self.reassign_source_repositories(db, changes, new_trans)
        repo_map: dict[str, str] = {}
        for repo in db.iter_repositories():
            key = normalize_repo_name(str(repo.get_name() or ""))
            if key:
                repo_map.setdefault(key, repo.get_handle())

        changed = 0
        created = 0
        for change in changes:
            target = str(change.get("target_name") or "").strip()
            if not target:
                continue
            source = db.get_source_from_handle(change["source_handle"])
            if source is None:
                continue
            key = normalize_repo_name(target)
            new_handle = repo_map.get(key)
            if not new_handle:
                new_handle = self._create_repository(db, target, trans)
                repo_map[key] = new_handle
                created += 1
            old_handle = str(change.get("old_repo_handle") or "")
            if old_handle == new_handle:
                continue
            current = [ref.get_reference_handle() for ref in source.get_reporef_list()]
            if old_handle and old_handle in current:
                source.replace_repo_references(old_handle, new_handle)
            elif new_handle not in current:
                repo_ref = RepoRef()
                repo_ref.set_reference_handle(new_handle)
                source.add_repo_reference(repo_ref)
            else:
                continue
            db.commit_source(source, trans)
            changed += 1
        return changed, created

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
        try:
            keeper = db.get_source_from_handle(keeper_handle)
        except HandleError:
            keeper = None
        try:
            discard = db.get_source_from_handle(discard_handle)
        except HandleError:
            discard = None
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
        # Source.merge keeps notes, media, tags and repositories but not the
        # text fields, so fill any the keeper lacks from the discarded source.
        if not str(keeper.get_author() or "").strip() and discard.get_author():
            keeper.set_author(discard.get_author())
        if (
            not str(keeper.get_publication_info() or "").strip()
            and discard.get_publication_info()
        ):
            keeper.set_publication_info(discard.get_publication_info())
        if (
            not str(keeper.get_abbreviation() or "").strip()
            and discard.get_abbreviation()
        ):
            keeper.set_abbreviation(discard.get_abbreviation())
        # Where both sources had text and it differs, the discarded wording
        # would vanish. Keep it in a note on the surviving source instead.
        self._keep_conflicting_source_text(db, keeper, discard, trans)
        LOG.info(
            "Merged source %s '%s' into %s '%s'",
            discard.get_gramps_id(),
            discard.get_title(),
            keeper.get_gramps_id(),
            keeper.get_title(),
        )
        db.commit_source(keeper, trans)
        db.remove_source(discard_handle, trans)
        return True

    @staticmethod
    def _keep_conflicting_source_text(
        db: Any, keeper: Any, discard: Any, trans: Any
    ) -> bool:
        """Add a note to ``keeper`` holding discarded text that differs.

        Compares author, publication info and abbreviation (ignoring case
        and spacing). Nothing is added when the fields agree or when the
        keeper had no text of its own (that case is copied across instead).
        Returns True when a note was added.
        """

        def squash(text: Any) -> str:
            return " ".join(str(text or "").split()).casefold()

        fields = (
            (_("Author"), keeper.get_author, discard.get_author),
            (
                _("Publication info"),
                keeper.get_publication_info,
                discard.get_publication_info,
            ),
            (_("Abbreviation"), keeper.get_abbreviation, discard.get_abbreviation),
        )
        lost: list[str] = []
        for label, get_keep, get_drop in fields:
            kept_text = " ".join(str(get_keep() or "").split())
            dropped_text = " ".join(str(get_drop() or "").split())
            if dropped_text and kept_text and squash(kept_text) != squash(dropped_text):
                lost.append("%s: %s" % (label, dropped_text))
        if not lost:
            return False
        text = str(
            _(
                "Merged from source %(gid)s '%(title)s'. Text not kept in "
                "the fields above:\n%(lost)s"
            )
        ) % {
            "gid": str(discard.get_gramps_id() or ""),
            "title": str(discard.get_title() or ""),
            "lost": "\n".join(lost),
        }
        for note_handle in keeper.get_note_list():
            existing = db.get_note_from_handle(note_handle)
            if existing is not None and existing.get() == text:
                return False
        note = Note()
        note.set(text)
        note.set_type(NoteType.SOURCE)
        keeper.add_note(db.add_note(note, trans))
        return True

    def consolidate_duplicate_sources(self, db: Any) -> int:
        """Merge sources whose titles normalize to the same text.

        Title-only scripting helper. The GUI steps use the hint-based
        ``auto_fix_sources`` in gw_sourcesfixdialog instead.
        """
        groups: dict[str, list[Any]] = defaultdict(list)
        for source in db.iter_sources():
            key = normalize_source_title(str(source.get_title() or ""))
            if key:
                groups[key].append(source)

        def rank(source: Any) -> tuple[Any, ...]:
            cites = len(
                list(db.find_backlink_handles(source.get_handle(), ["Citation"]))
            )
            return (
                -len(list(source.get_reporef_list())),
                -int(bool(re.search(r"\bU\.S\.", str(source.get_title() or "")))),
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
        """Downrate user-tree citations and tidy the Volume/Page text.

        Scripting helper. The GUI steps use ``auto_fix_citations`` in
        gw_citationsfixdialog instead.
        """
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
                    # Gramps confidence: 0 Very Low ... 4 Very High. User trees
                    # are lowered to Low (1), the same as the Fix Citations
                    # dialog.
                    if int(citation.get_confidence_level()) >= 3:
                        citation.set_confidence_level(1)
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
        """Remove import-debris notes and every reference to them.

        Scripting helper. The GUI steps use ``auto_fix_notes`` in
        gw_notesfixdialog instead.
        """
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

    # ------------------------------------------------------------
    # Step: media to citation linking & auditing
    # ------------------------------------------------------------
    def plan_link_citation_media(self, db: Any) -> list[dict[str, Any]]:
        """Collect all candidate media-to-citation link operations across all sources."""
        from .gwizardcitationmediaengine import (
            find_promotable_gallery_media,
            find_unpackable_source_media,
            find_orphan_media_matches,
        )

        plan: list[dict[str, Any]] = []
        plan.extend(find_promotable_gallery_media(db))
        plan.extend(find_unpackable_source_media(db))
        plan.extend(find_orphan_media_matches(db))
        return plan

    def auto_link_citation_media(self, db: Any, min_score: int = 70) -> int:
        """Automatically link high-confidence, non-conflicting media to citations.

        Only links with score >= min_score and zero conflicts are applied.
        One DbTxn, single undo.
        """
        from .gwizardcitationmediaengine import (
            apply_promote_media_to_citation,
            apply_unpack_source_media,
            apply_link_media_to_citation,
        )

        plan = self.plan_link_citation_media(db)
        linked_count = 0
        with DbTxn(_("Link Media to Citations"), db) as trans:
            for item in plan:
                compat = item.get("compatibility")
                if not compat or not compat.is_match or compat.conflicts:
                    continue
                if compat.score < min_score:
                    continue

                action = item.get("action", "")
                c_h = item.get("citation_handle", "")
                m_h = item.get("media_handle", "")
                success = False

                if action in ("promote_from_person", "promote_from_event"):
                    success = apply_promote_media_to_citation(
                        db,
                        trans,
                        c_h,
                        m_h,
                        detach_from_owner=False,
                        owner_type=item.get("owner_type", ""),
                        owner_handle=item.get("owner_handle", ""),
                    )
                elif action == "unpack_from_source":
                    success = apply_unpack_source_media(
                        db,
                        trans,
                        source_handle=item.get("owner_handle", ""),
                        citation_handle=c_h,
                        media_handle=m_h,
                        detach_from_source=False,
                    )
                elif action == "link_orphan":
                    success = apply_link_media_to_citation(db, trans, c_h, m_h)

                if success:
                    linked_count += 1

        return linked_count

    def audit_citation_media_links(self, db: Any) -> list[dict[str, Any]]:
        """Audit existing citation media links for potential mismatches or conflicts."""
        from .gwizardcitationmediaengine import audit_existing_citation_media_links

        return audit_existing_citation_media_links(db)
