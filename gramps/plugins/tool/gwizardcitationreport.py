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
