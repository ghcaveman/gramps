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

"""Tools/Family Tree Processing/GWizard Deconflate Sources Worker."""

from __future__ import annotations
import logging
import re
from typing import Any
from gwizardcitationreport import GWizardCitationReport

LOG = logging.getLogger(__name__)

# Re-use the exact same pattern regex highlighters declared in your engine
_FIELD_REPO_PATTERNS = re.compile(r'https?://|www\.|familysearch|ancestry|newspapers\.com|find\s?a\s?grave|myheritage|legacy\.com', re.IGNORECASE)
_FIELD_SOURCE_PATTERNS = re.compile(r'census|death\s+certificate|birth\s+record|marriage\s+index|vital\s+records|church\s+records|obituary\s+index', re.IGNORECASE)
_FIELD_CITATION_PATTERNS = re.compile(r'page\s+\d+|vol(ume)?\s+\d+|cert(ificate)?\s+\d+|accessed\s+\d+|entry\s+for|household\s+\d+|line\s+\d+|memorial\s+id', re.IGNORECASE)


class GWizardCitationRepairEngine:
    """Handles the safe database transformation layer for unpacking combined fields."""

    def unpack_conflated_sources(self, db: Any) -> int:
        """Iterates over all conflated sources, creates missing Repository objects,

        and re-links them safely using standard Gramps DbTxn structures.
        """
        from gramps.gen.const import GRAMPS_LOCALE as glocale
        from gramps.gen.db import DbTxn
        from gramps.gen.lib import Repository, RepoRef

        _ = glocale.translation.sgettext

        # Call the existing report collector to pull our bad fields target list
        report_engine = GWizardCitationReport()
        stats = report_engine.collect_db_stats(db)
        conflated = stats.get("conflated_sources", [])
        if not conflated:
            return 0

        repo_name_to_handle = {}
        for repo in db.iter_repositories():
            repo_name_to_handle[str(repo.get_name() or "").strip().lower()] = (
                repo.get_handle()
            )

        success_count = 0

        # Initialize explicit low-level transaction matrix
        trans = DbTxn(_("Unpack Conflated Fields"), db)
        try:
            for row in conflated:
                handle = row["handle"]
                source = db.get_source_from_handle(handle)
                if not source:
                    continue

                title = str(source.get_title() or "")
                parts = [
                    p.strip()
                    for p in re.split(
                        r"[;|\(\)]|(?<=[\w]),\s*(?=[A-Za-z])", title
                    )
                    if p.strip()
                ]
                if len(parts) < 2:
                    continue

                extracted_repo_name = parts[0]
                extracted_source_title = " ".join(parts[1:]).strip(" .)")

                repo_key = extracted_repo_name.strip().lower()
                repo_handle = repo_name_to_handle.get(repo_key)

                if not repo_handle:
                    new_repo = Repository()
                    new_repo.set_name(extracted_repo_name)
                    db.add_repository(new_repo, trans)
                    repo_handle = new_repo.get_handle()
                    repo_name_to_handle[repo_key] = repo_handle

                already_linked = False
                for ref in source.get_reporef_list():
                    if ref.get_reference_handle() == repo_handle:
                        already_linked = True
                        break

                if not already_linked:
                    repo_ref = RepoRef()
                    repo_ref.set_reference_handle(repo_handle)
                    source.add_reporef(repo_ref)

                source.set_title(extracted_source_title)
                db.commit_source(source, trans)
                success_count += 1

            db.transaction_commit(trans)
        except Exception:
            db.transaction_abort(trans)
            raise

        return success_count

    def consolidate_duplicate_repositories(self, db: Any) -> int:
        """
        Finds repositories with near-identical names, picks a master,
        reroutes all referencing sources to the master, and deletes duplicates.
        """
        from gramps.gen.const import GRAMPS_LOCALE as glocale
        from gramps.gen.db import DbTxn
        _ = glocale.translation.sgettext

        repos = list(db.iter_repositories())
        norm_groups = defaultdict(list)
        
        for repo in repos:
            name = str(repo.get_name() or "").strip()
            if not name:
                continue
            # Use the existing normalize_repo_name logic
            key = (name or "").lower().strip()
            key = key.replace("&", "and")
            key = re.sub(r"\bu\.?\s*s\.?\b", " ", key)
            key = re.sub(r"[^a-z0-9 ]+", " ", key)
            norm_key = re.sub(r"\s+", " ", key).strip()
            norm_groups[norm_key].append(repo)
            
        merge_count = 0
        
        # Explicitly initialize Gramps transactional batch tracking
        trans = DbTxn(_("Consolidate Repositories"), db)
        try:
            for norm_key, group in norm_groups.items():
                if len(group) < 2:
                    continue
                
                # Pick the master (the one with the oldest/lowest Gramps ID or handle)
                group.sort(key=lambda r: str(r.get_gramps_id() or ""))
                master_repo = group[0]
                master_handle = master_repo.get_handle()
                
                # Reroute pointers from duplicate repositories to master_handle
                for duplicate_repo in group[1:]:
                    dup_handle = duplicate_repo.get_handle()
                    
                    # Search for sources linking to the duplicate repository
                    for source in db.iter_sources():
                        modified = False
                        for ref in source.get_reporef_list():
                            if ref.get_reference_handle() == dup_handle:
                                ref.set_reference_handle(master_handle)
                                modified = True
                        if modified:
                            # Pass trans to ensure changes are bundled together safely
                            db.commit_source(source, trans)
                            
                    # Remove the duplicate repository record safely using trans
                    db.remove_repository(dup_handle, trans)
                    merge_count += 1
                    
            db.transaction_commit(trans)
        except Exception:
            db.transaction_abort(trans)
            raise
                    
        return merge_count

    def consolidate_duplicate_sources(self, db: Any) -> int:
        """
        Finds sources with near-identical titles, picks a master,
        reroutes all referencing citations to the master, and deletes duplicates.
        """
        from gramps.gen.const import GRAMPS_LOCALE as glocale
        from gramps.gen.db import DbTxn
        _ = glocale.translation.sgettext

        sources = list(db.iter_sources())
        norm_groups = defaultdict(list)
        
        for src in sources:
            title = str(src.get_title() or "")
            key = self.normalize_source_title(title)
            if key:
                norm_groups[key].append(src)
                
        merge_count = 0
        
        # Explicitly initialize Gramps transactional batch tracking
        trans = DbTxn(_("Consolidate Sources"), db)
        try:
            for norm_key, group in norm_groups.items():
                if len(group) < 2:
                    continue
                
                # Sort by Gramps ID and prioritize records that already carry citations
                group.sort(key=lambda s: str(s.get_gramps_id() or ""))
                master_source = group[0]
                master_handle = master_source.get_handle()
                
                for duplicate_source in group[1:]:
                    dup_handle = duplicate_source.get_handle()
                    
                    # Search for citations linking to the duplicate source handle
                    for citation in db.iter_citations():
                        if citation.get_reference_handle() == dup_handle:
                            citation.set_reference_handle(master_handle)
                            # Pass trans to bundle the citation updates safely
                            db.commit_citation(citation, trans)
                            
                    # Remove the duplicate source record safely using trans
                    db.remove_source(dup_handle, trans)
                    merge_count += 1
                    
            db.transaction_commit(trans)
        except Exception:
            db.transaction_abort(trans)
            raise
                    
        return merge_count

    def clean_and_rate_citations(self, db: Any) -> int:
        """
        Scans all citations in the database. If a citation points to an online
        family tree source, it safely lowers its confidence level. It also strips
        messy automation artifacts out of the pinpoint Volume/Page field.
        """
        from gramps.gen.const import GRAMPS_LOCALE as glocale
        from gramps.gen.db import DbTxn
        _ = glocale.translation.sgettext

        citations = list(db.iter_citations())
        fix_count = 0
        
        # Build a rapid lookup cache of source handles that represent user family trees
        tree_source_handles = set()
        for src in db.iter_sources():
            title = str(src.get_title() or "").lower()
            if "familysearch" in title and "family tree" in title:
                tree_source_handles.add(str(src.get_handle()))
            elif "ancestry member tree" in title or "public member tree" in title:
                tree_source_handles.add(str(src.get_handle()))

        # Explicitly initialize Gramps transactional batch tracking
        trans = DbTxn(_("Clean Citations and Confidence"), db)
        try:
            for citation in citations:
                modified = False
                src_handle = str(citation.get_reference_handle() or "")
                
                # Layer A: Check and downgrade user-tree confidence settings
                if src_handle in tree_source_handles:
                    # Gramps confidence ranges from 0 (Very Low) to 4 (Very High)
                    # Downrate highly confident entries from derivative trees to 1 (Low) or 2 (Normal)
                    if int(citation.get_confidence_level()) >= 3:
                        citation.set_confidence_level(2)
                        modified = True
                
                # Layer B: Clean pinpoint formatting artifacts out of the Volume/Page field
                page = str(citation.get_page() or "")
                if page:
                    cleaned_page = page.strip()
                    # Remove trailing unparsed brackets or messy punctuation strings left over from exports
                    cleaned_page = re.sub(r'^[,\.\s;]+|[,\.\s;]+$', '', cleaned_page)
                    cleaned_page = re.sub(r'\s+', ' ', cleaned_page)
                    
                    if cleaned_page != page:
                        citation.set_page(cleaned_page)
                        modified = True
                        
                if modified:
                    # Pass trans to bundle the citation updates safely
                    db.commit_citation(citation, trans)
                    fix_count += 1
                    
            db.transaction_commit(trans)
        except Exception:
            db.transaction_abort(trans)
            raise
                    
        return fix_count

    def purge_import_debris_notes(self, db: Any) -> int:
        """
        Scans all notes in the database. If a note matches known legacy import
        software debris patterns or broken log headers, it safely strips it from
        referencing objects and purges the note from the database entirely.
        """
        from gramps.gen.const import GRAMPS_LOCALE as glocale
        from gramps.gen.db import DbTxn
        _ = glocale.translation.sgettext

        notes = list(db.iter_notes())
        purge_count = 0
        
        # Identification match phrases for system export junk
        debris_indicators = [
            "records not imported into repo",
            "tag recognized but not supported",
            "birth type:",
            "passed away exactly on his"
        ]

        # Explicitly initialize Gramps transactional batch tracking
        trans = DbTxn(_("Purge Import Debris Notes"), db)
        try:
            for note in notes:
                text = self._note_text(note).strip()
                if not text:
                    continue
                    
                text_lower = text.lower()
                is_debris = any(indicator in text_lower for indicator in debris_indicators)
                
                if is_debris:
                    note_handle = note.get_handle()
                    
                    # Safe backlink cleanup: remove pointers linking to this junk note from all objects
                    if hasattr(db, "find_backlink_handles"):
                        try:
                            backlinks = list(db.find_backlink_handles(note_handle))
                            for bl_handle, obj_type in backlinks:
                                # Dynamically fetch and clean the parent object row
                                if obj_type == "Person":
                                    parent = db.get_person_from_handle(bl_handle)
                                    if parent:
                                        parent.remove_note_handle(note_handle)
                                        db.commit_person(parent, trans) # Pass trans
                                elif obj_type == "Source":
                                    parent = db.get_source_from_handle(bl_handle)
                                    if parent:
                                        parent.remove_note_handle(note_handle)
                                        db.commit_source(parent, trans) # Pass trans
                                elif obj_type == "Citation":
                                    parent = db.get_citation_from_handle(bl_handle)
                                    if parent:
                                        parent.remove_note_handle(note_handle)
                                        db.commit_citation(parent, trans) # Pass trans
                        except Exception:
                            LOG.exception("Failed to disconnect backlink for note %s", note_handle)

                    # Purge the actual note row record permanently passing trans
                    db.remove_note(note_handle, trans)
                    purge_count += 1
                    
            db.transaction_commit(trans)
        except Exception:
            db.transaction_abort(trans)
            raise
                    
        return purge_count
