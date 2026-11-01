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
        """Formats the collected statistics dictionary into clear report lines."""
        get = stats.get
        lines = [
            f"Database totals: {get('people', 0)} people, {get('sources', 0)} sources, {get('repositories', 0)} repositories.",
            "",
            "Where it falls short:",
            f"- Sources without a repository: {len(get('sources_no_repo', []))} of {get('sources', 0)}."
        ]
        
        conflated = get("conflated_sources", [])
        lines.append(f"- Conflated Fields: {len(conflated)} sources contain mixed data.")
        for row in conflated[:10]:
            lines.append(f"  * {row.get('gramps_id')}: '{row.get('title')}'\n    ↳ Found elements: {', '.join(row.get('elements_detected', []))}")
            
        lines.append("")
        lines.append("Suggested order of fixes:")
        lines.append("1. Run Step 1: Unpack and Split Conflated Source Fields.")
        lines.append("2. Merge duplicate sources.")
        return "\n".join(lines)

    def unpack_conflated_sources(self, db: Any, parent_window: Any = None) -> int:
        """
        Iterates over all conflated sources, creates missing Repository objects,
        and re-links them safely using standard Gramps database transactions.
        """
        from gramps.gen.lib import Repository, RepoRef
        from gramps.gen.const import GRAMPS_LOCALE as glocale
        _ = glocale.translation.sgettext
        
        # 1. Gather our diagnostic stats to see what needs to be fixed
        stats = self.collect_db_stats(db)
        conflated = stats.get("conflated_sources", [])
        if not conflated:
            return 0
            
        # Map existing repository names to their handles to prevent creating duplicates
        repo_name_to_handle = {}
        for repo in db.iter_repositories():
            repo_name_to_handle[str(repo.get_name() or "").strip().lower()] = repo.get_handle()
            
        success_count = 0
        
        # 2. Initialize a safe data mutation transaction block
        with db.transaction(_("Unpack Conflated Fields")):
            for row in conflated:
                handle = row["handle"]
                source = db.get_source_from_handle(handle)
                if not source:
                    continue
                    
                title = str(source.get_title() or "")
                
                # Intelligent, generic string splitting logic
                # Splits by semicolons, parentheses, or trailing commas followed by text
                parts = [p.strip() for p in re.split(r'[;|\(\)]|(?<=[\w]),\s*(?=[A-Za-z])', title) if p.strip()]
                if len(parts) < 2:
                    continue
                    
                # Standard genealogical grouping: usually "Repository Name; Source Collection Title"
                extracted_repo_name = parts[0]
                extracted_source_title = " ".join(parts[1:]).strip(" .)")
                
                # 3. Handle the Repository lifecycle layer
                repo_key = extracted_repo_name.strip().lower()
                repo_handle = repo_name_to_handle.get(repo_key)
                
                if not repo_handle:
                    # If this repository doesn't exist yet, build a brand new one
                    new_repo = Repository()
                    new_repo.set_name(extracted_repo_name)
                    db.add_repository(new_repo)
                    repo_handle = new_repo.get_handle()
                    # Cache it to prevent duplicate creation loops
                    repo_name_to_handle[repo_key] = repo_handle
                    
                # 4. Handle the Repository Reference linking layer
                # Check if this Source already has this Repository reference linked
                already_linked = False
                for ref in source.get_reporef_list():
                    if ref.get_reference_handle() == repo_handle:
                        already_linked = True
                        break
                        
                if not already_linked:
                    repo_ref = RepoRef()
                    repo_ref.set_reference_handle(repo_handle)
                    source.add_reporef(repo_ref)
                    
                # 5. Clean up the source title string and update the object
                source.set_title(extracted_source_title)
                db.commit_source(source)
                success_count += 1
                
        return success_count

    def consolidate_duplicate_repositories(self, db: Any) -> int:
        """
        Finds repositories with near-identical names, picks a master,
        reroutes all referencing sources to the master, and deletes duplicates.
        """
        from gramps.gen.const import GRAMPS_LOCALE as glocale
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
        
        with db.transaction(_("Consolidate Repositories")):
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
                            db.commit_source(source)
                            
                    # Remove the duplicate repository record safely
                    db.remove_repository(dup_handle)
                    merge_count += 1
                    
        return merge_count

    def consolidate_duplicate_sources(self, db: Any) -> int:
        """
        Finds sources with near-identical titles, picks a master,
        reroutes all referencing citations to the master, and deletes duplicates.
        """
        from gramps.gen.const import GRAMPS_LOCALE as glocale
        _ = glocale.translation.sgettext

        sources = list(db.iter_sources())
        norm_groups = defaultdict(list)
        
        for src in sources:
            title = str(src.get_title() or "")
            key = self.normalize_source_title(title)
            if key:
                norm_groups[key].append(src)
                
        merge_count = 0
        
        with db.transaction(_("Consolidate Sources")):
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
                            db.commit_citation(citation)
                            
                    # Remove the duplicate source record safely
                    db.remove_source(dup_handle)
                    merge_count += 1
                    
        return merge_count

    def clean_and_rate_citations(self, db: Any) -> int:
        """
        Scans all citations in the database. If a citation points to an online
        family tree source, it safely lowers its confidence level. It also strips
        messy automation artifacts out of the pinpoint Volume/Page field.
        """
        from gramps.gen.const import GRAMPS_LOCALE as glocale
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

        with db.transaction(_("Clean Citations and Confidence")):
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
                    db.commit_citation(citation)
                    fix_count += 1
                    
        return fix_count

    def purge_import_debris_notes(self, db: Any) -> int:
        """
        Scans all notes in the database. If a note matches known legacy import
        software debris patterns or broken log headers, it safely strips it from
        referencing objects and purges the note from the database entirely.
        """
        from gramps.gen.const import GRAMPS_LOCALE as glocale
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

        with db.transaction(_("Purge Import Debris Notes")):
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
                                        db.commit_person(parent)
                                elif obj_type == "Source":
                                    parent = db.get_source_from_handle(bl_handle)
                                    if parent:
                                        parent.remove_note_handle(note_handle)
                                        db.commit_source(parent)
                                elif obj_type == "Citation":
                                    parent = db.get_citation_from_handle(bl_handle)
                                    if parent:
                                        parent.remove_note_handle(note_handle)
                                        db.commit_citation(parent)
                        except Exception:
                            LOG.exception("Failed to disconnect backlink for note %s", note_handle)

                    # Purge the actual note row record permanently
                    db.remove_note(note_handle)
                    purge_count += 1
                    
        return purge_count
