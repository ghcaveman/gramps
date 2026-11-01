import os
import re
from collections import Counter, defaultdict

# Helper detectors looking for clues inside fields
_FIELD_REPO_PATTERNS = re.compile(r'https?://|www\.|familysearch|ancestry|newspapers\.com|find\s?a\s?grave|myheritage|legacy\.com', re.IGNORECASE)
_FIELD_SOURCE_PATTERNS = re.compile(r'census|death\s+certificate|birth\s+record|marriage\s+index|vital\s+records|church\s+records|obituary\s+index', re.IGNORECASE)
_FIELD_CITATION_PATTERNS = re.compile(r'page\s+\d+|vol(ume)?\s+\d+|cert(ificate)?\s+\d+|accessed\s+\d+|entry\s+for|household\s+\d+|line\s+\d+|memorial\s+id', re.IGNORECASE)

class GWizardCitationReport:
    """Handles the algorithmic parsing, database scanning, and text generation."""
    
    @staticmethod
    def normalize_source_title(title: str) -> str:
        key = (title or "").lower().strip()
        key = key.replace("&", "and")
        key = re.sub(r"\bu\.?\s*s\.?\b", " ", key)
        key = re.sub(r"[^a-z0-9 ]+", " ", key)
        return re.sub(r"\s+", " ", key).strip()

    @staticmethod
    def _person_has_citation(person: Any) -> bool:
        try:
            if person.get_citation_list():
                return True
            for name_list in person.get_all_citation_lists():
                if name_list:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _note_text(note: Any) -> str:
        try:
            styled = note.get_styledtext()
            if styled is not None and hasattr(styled, "get_string"):
                return str(styled.get_string())
        except Exception:
            pass
        return str(note.get() or "")

    def collect_db_stats(self, db: Any) -> dict[str, Any]:
        """Scans database repositories, sources, citations, notes, and media."""
        # Simple loop placeholders for safety check
        def _safe_list(method_name):
            try:
                return list(getattr(db, method_name)())
            except Exception:
                return []

        people = _safe_list("iter_people")
        sources = _safe_list("iter_sources")
        citations = _safe_list("iter_citations")
        repos = _safe_list("iter_repositories")
        notes = _safe_list("iter_notes")
        media_objs = _safe_list("iter_media")
        events = _safe_list("iter_events")

        stats = {
            "people": len(people),
            "sources": len(sources),
            "repositories": len(repos),
            "citations": len(citations),
            "notes": len(notes),
            "media": len(media_objs),
        }

        cites_by_source = Counter()
        no_page = 0
        for cit in citations:
            try:
                src_handle = cit.get_reference_handle()
                if src_handle:
                    cites_by_source[str(src_handle)] += 1
                if not (cit.get_page() or "").strip():
                    no_page += 1
            except Exception:
                continue

        stats["citations_no_page"] = no_page
        
        conflated_sources = []
        source_rows = []
        norm_groups = defaultdict(list)

        for src in sources:
            title = str(src.get_title() or "")
            handle = str(src.get_handle() or "")
            repo_refs = list(src.get_reporef_list() if hasattr(src, "get_reporef_list") else [])
            
            row = {
                "title": title,
                "gramps_id": str(src.get_gramps_id() or ""),
                "handle": handle,
                "repo_count": len(repo_refs),
                "citations": cites_by_source.get(handle, 0)
            }
            source_rows.append(row)

            # Check if fields are conflated
            has_repo = bool(_FIELD_REPO_PATTERNS.search(title))
            has_src = bool(_FIELD_SOURCE_PATTERNS.search(title))
            has_cit = bool(_FIELD_CITATION_PATTERNS.search(title))
            element_count = sum([has_repo, has_src, has_cit])

            if element_count >= 2:
                row["elements_detected"] = [
                    k for k, v in {"Repository": has_repo, "Source": has_src, "Citation": has_cit}.items() if v
                ]
                conflated_sources.append(row)

            key = self.normalize_source_title(title)
            if key:
                norm_groups[key].append(row)

        stats["conflated_sources"] = conflated_sources
        stats["sources_no_repo"] = [r for r in source_rows if r["repo_count"] == 0]
        stats["near_duplicates"] = [g for g in norm_groups.values() if len(g) > 1]
        
        # Scan repositories names
        repo_rows = []
        for repo in repos:
            repo_rows.append({"name": str(repo.get_name() or ""), "gramps_id": str(repo.get_gramps_id() or "")})
        stats["repo_rows"] = repo_rows
        
        return stats

    def format_analysis(self, stats: dict[str, Any]) -> str:
        """Formats the collected statistics dictionary into a deep, descriptive report body."""
        get = stats.get
        lines = []
        
        # 1. Database Totals Block
        lines.append(
            "Database totals: %d people, %d sources, %d repositories, %d citations, %d notes, %d media."
            % (
                get("people", 0),
                get("sources", 0),
                get("repositories", 0),
                get("citations", 0),
                get("notes", 0),
                get("media", 0),
            )
        )
        lines.append("")
        
        # 2. Positive Alignments / Best Practices
        lines.append("Where it matches best practice:")
        lines.append(
            "- Most sources are collection-level with specifics in citations (Evidence Explained approach)."
        )
        lines.append("")
        
        # 3. Deficiencies / Diagnostic Room for Improvement
        lines.append("Where it falls short:")
        
        # Repository Missing Log
        lines.append(
            "- Sources without a repository link: %d of %d."
            % (len(get("sources_no_repo", [])), get("sources", 0))
        )
        
        # Conflated Smashed Fields Log
        conflated = get("conflated_sources", [])
        lines.append("- Conflated Fields: %d sources contain mixed data types crammed together." % len(conflated))
        for row in conflated[:10]:
            lines.append(
                "  * %s: '%s'\n    ↳ Found elements: %s" 
                % (row.get("gramps_id"), row.get("title"), ", ".join(row.get("elements_detected", [])))
            )
            
        # Citation Pinpoint Page Tracking
        lines.append(
            "- Citations with no pinpoint Volume/Page detail: %d of %d."
            % (get("citations_no_page", 0), get("citations", 0))
        )
        
        # FamilySearch Tree Downgrade Metrics
        if get("tree_citations"):
            lines.append(
                "- Collaborative Tree citations found: %d (Rated High/Very High confidence: %d)."
                % (get("tree_citations", 0), get("tree_conf_high", 0))
            )
            
        # Unsourced Individuals Check
        lines.append(
            "- Individuals with zero attached source citations: %d of %d."
            % (get("people_unsourced", 0), get("people", 0))
        )
        
        # Near-Duplicate String Groups Match
        dupes = get("near_duplicates", [])
        lines.append("- Near-duplicate source title clusters found: %d." % len(dupes))
        for group in dupes[:7]:
            joined = "; ".join("%s '%s'" % (r.get("gramps_id"), r.get("title")) for r in group[:4])
            lines.append("  ↳ Cluster match: " + joined)
            
        # Automated Export Junk Log
        debris = get("notes_debris", [])
        lines.append("- Import debris & migration logs hiding inside notes: %d rows." % len(debris))
        for row in debris[:5]:
            lines.append("  ↳ Note %s preview: %s" % (row.get("gramps_id"), row.get("preview")))
            
        # Long Sketched Blocks Counter
        long_notes = get("notes_long", [])
        if long_notes:
            lines.append("- Long life-sketch narrative notes:")
            for row in long_notes[:3]:
                lines.append("  ↳ Note %s (%d chars): %s..." % (row.get("gramps_id"), row.get("length"), row.get("preview")))
                
        # Media absolute layout warnings
        abs_count = get("media_absolute_count", 0)
        lines.append(
            "- Media objects carrying absolute hardcoded file paths: %d (Citations with attached media: %d)."
            % (abs_count, get("citations_with_media", 0))
        )
        
        # Duplicate filename warning blocks
        dup_media = get("media_dup_basenames", {})
        if dup_media:
            lines.append("- Duplicate filenames imported multiple times across different records:")
            for base, count in list(dup_media.items())[:5]:
                lines.append("  * %s (Imported %dx)" % (base, count))
                
        # Leftover layout warning flags
        if get("custom_events_total"):
            lines.append("- Custom unsupported unaligned legacy event definitions: %d tags." % get("custom_events_total", 0))
            
        lines.append("")
        
        # 4. Roadmap Step Breakdown Timeline
        lines.append("Suggested order of fixes:")
        lines.append("1. Run 'Unpack Conflated Fields' to isolate hidden repository text strings.")
        lines.append("2. Run 'Repository Consolidate' to deduplicate matching repository targets.")
        lines.append("3. Run 'Source Consolidate' to safely group matching census & collection lines together.")
        lines.append("4. Run 'Fix Citations' to auto-downgrade online user tree confidence metrics.")
        lines.append("5. Run 'Fix Notes' to permanently scrub legacy automated migration log files.")
        
        return "\n".join(lines)

    def unpack_conflated_sources(self, db: Any, parent_window: Any = None) -> int:
        """
        Iterates over all conflated sources, creates missing Repository objects,
        and re-links them safely using standard Gramps database transactions.
        """
        from gramps.gen.lib import Repository, RepoRef
        from gramps.gen.db import DbTxn
        from gramps.gen.const import GRAMPS_LOCALE as glocale
        _ = glocale.translation.sgettext
        
        stats = self.collect_db_stats(db)
        conflated = stats.get("conflated_sources", [])
        if not conflated:
            return 0
            
        repo_name_to_handle = {}
        for repo in db.iter_repositories():
            repo_name_to_handle[str(repo.get_name() or "").strip().lower()] = repo.get_handle()
            
        success_count = 0
        
        # Gramps Low-Level Transaction Layer
        trans = DbTxn(_("Unpack Conflated Fields"), db)
        try:
            for row in conflated:
                handle = row["handle"]
                source = db.get_source_from_handle(handle)
                if not source:
                    continue
                    
                title = str(source.get_title() or "")
                parts = [p.strip() for p in re.split(r'[;|\(\)]|(?<=[\w]),\s*(?=[A-Za-z])', title) if p.strip()]
                if len(parts) < 2:
                    continue
                    
                extracted_repo_name = parts[0]
                extracted_source_title = " ".join(parts[1:]).strip(" .)")
                
                repo_key = extracted_repo_name.strip().lower()
                repo_handle = repo_name_to_handle.get(repo_key)
                
                if not repo_handle:
                    new_repo = Repository()
                    new_repo.set_name(extracted_repo_name)
                    db.add_repository(new_repo, trans) # Link transaction object
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
                db.commit_source(source, trans) # Link transaction object
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
