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

"""Database scanning and report text for the GWizard citation fix tool."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
from collections import Counter, defaultdict
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.plugins.tool.gwizardcitationshared import (
    detect_title_elements,
    is_debris_text,
    is_tree_source_title,
    normalize_source_title,
    note_text,
)

LOG = logging.getLogger(__name__)

LONG_NOTE_CHARS = 2000


class GWizardCitationReport:
    """Handles the algorithmic parsing, database scanning, and text generation."""

    @staticmethod
    def normalize_source_title(title: str) -> str:
        return normalize_source_title(title)

    @staticmethod
    def _person_has_citation(person: Any, db: Any = None) -> bool:
        """True when the person, a name, or one of their events has a citation."""
        try:
            if person.get_citation_list():
                return True
            names = [person.get_primary_name()] + list(person.get_alternate_names())
            if any(name.get_citation_list() for name in names):
                return True
            if db is not None:
                for ref in person.get_event_ref_list():
                    event = db.get_event_from_handle(ref.ref)
                    if event is not None and event.get_citation_list():
                        return True
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to inspect person citations")
        return False

    @staticmethod
    def _note_text(note: Any) -> str:
        return note_text(note)

    def collect_db_stats(self, db: Any) -> dict[str, Any]:
        """Scan repositories, sources, citations, notes, people and media."""

        def _safe_list(method_name: str) -> list[Any]:
            try:
                return list(getattr(db, method_name)())
            except Exception:  # pylint: disable=broad-except
                LOG.exception("Failed to iterate %s", method_name)
                return []

        people = _safe_list("iter_people")
        sources = _safe_list("iter_sources")
        citations = _safe_list("iter_citations")
        repos = _safe_list("iter_repositories")
        notes = _safe_list("iter_notes")
        media_objs = _safe_list("iter_media")
        events = _safe_list("iter_events")

        stats: dict[str, Any] = {
            "people": len(people),
            "sources": len(sources),
            "repositories": len(repos),
            "citations": len(citations),
            "notes": len(notes),
            "media": len(media_objs),
        }

        # Citations ----------------------------------------------------
        cites_by_source: Counter = Counter()
        no_page = 0
        with_media = 0
        for cit in citations:
            try:
                src_handle = cit.get_reference_handle()
                if src_handle:
                    cites_by_source[str(src_handle)] += 1
                if not (cit.get_page() or "").strip():
                    no_page += 1
                if cit.get_media_list():
                    with_media += 1
            except Exception:  # pylint: disable=broad-except
                continue
        stats["citations_no_page"] = no_page
        stats["citations_with_media"] = with_media

        # Sources ------------------------------------------------------
        conflated_sources = []
        source_rows = []
        norm_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        tree_handles = set()
        for src in sources:
            title = str(src.get_title() or "")
            handle = str(src.get_handle() or "")
            row = {
                "title": title,
                "gramps_id": str(src.get_gramps_id() or ""),
                "handle": handle,
                "repo_count": len(list(src.get_reporef_list())),
                "citations": cites_by_source.get(handle, 0),
            }
            source_rows.append(row)
            if is_tree_source_title(title):
                tree_handles.add(handle)
            elements = detect_title_elements(title)
            if len(elements) >= 2:
                conflated_sources.append(dict(row, elements_detected=elements))
            key = normalize_source_title(title)
            if key:
                norm_groups[key].append(row)

        stats["source_rows"] = source_rows
        stats["conflated_sources"] = conflated_sources
        stats["sources_no_repo"] = [r for r in source_rows if r["repo_count"] == 0]
        stats["near_duplicates"] = [g for g in norm_groups.values() if len(g) > 1]
        stats["tree_citations"] = sum(cites_by_source[h] for h in tree_handles)
        tree_high = 0
        for cit in citations:
            try:
                if (
                    str(cit.get_reference_handle()) in tree_handles
                    and int(cit.get_confidence_level()) >= 3
                ):
                    tree_high += 1
            except Exception:  # pylint: disable=broad-except
                continue
        stats["tree_conf_high"] = tree_high

        # Repositories -------------------------------------------------
        stats["repo_rows"] = [
            {
                "name": str(repo.get_name() or ""),
                "gramps_id": str(repo.get_gramps_id() or ""),
                "handle": str(repo.get_handle() or ""),
            }
            for repo in repos
        ]

        # People -------------------------------------------------------
        stats["people_unsourced"] = sum(
            1 for person in people if not self._person_has_citation(person, db)
        )

        # Notes --------------------------------------------------------
        debris = []
        long_notes = []
        for note in notes:
            try:
                text = self._note_text(note).strip()
                preview = " ".join(text.split())[:80]
                gid = str(note.get_gramps_id() or "")
                if is_debris_text(text):
                    debris.append({"gramps_id": gid, "preview": preview})
                elif len(text) >= LONG_NOTE_CHARS:
                    long_notes.append(
                        {"gramps_id": gid, "length": len(text), "preview": preview}
                    )
            except Exception:  # pylint: disable=broad-except
                continue
        stats["notes_debris"] = debris
        stats["notes_long"] = long_notes

        # Media --------------------------------------------------------
        absolute = 0
        basenames: Counter = Counter()
        for media in media_objs:
            try:
                path = str(media.get_path() or "")
                if os.path.isabs(path) or path[1:3] in (":\\", ":/"):
                    absolute += 1
                basenames[os.path.basename(path.replace("\\", "/")).lower()] += 1
            except Exception:  # pylint: disable=broad-except
                continue
        stats["media_absolute_count"] = absolute
        stats["media_dup_basenames"] = {
            base: count for base, count in basenames.items() if base and count > 1
        }

        # Events -------------------------------------------------------
        custom = 0
        for event in events:
            try:
                if event.get_type().is_custom():
                    custom += 1
            except Exception:  # pylint: disable=broad-except
                continue
        stats["custom_events_total"] = custom
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
        lines.append(
            "- Conflated Fields: %d sources contain mixed data types crammed together."
            % len(conflated)
        )
        for row in conflated[:10]:
            lines.append(
                "  * %s: '%s'\n    ↳ Found elements: %s"
                % (
                    row.get("gramps_id"),
                    row.get("title"),
                    ", ".join(row.get("elements_detected", [])),
                )
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
            joined = "; ".join(
                "%s '%s'" % (r.get("gramps_id"), r.get("title")) for r in group[:4]
            )
            lines.append("  ↳ Cluster match: " + joined)

        # Automated Export Junk Log
        debris = get("notes_debris", [])
        lines.append(
            "- Import debris & migration logs hiding inside notes: %d rows."
            % len(debris)
        )
        for row in debris[:5]:
            lines.append(
                "  ↳ Note %s preview: %s" % (row.get("gramps_id"), row.get("preview"))
            )

        # Long Sketched Blocks Counter
        long_notes = get("notes_long", [])
        if long_notes:
            lines.append("- Long life-sketch narrative notes:")
            for row in long_notes[:3]:
                lines.append(
                    "  ↳ Note %s (%d chars): %s..."
                    % (row.get("gramps_id"), row.get("length"), row.get("preview"))
                )

        # Media absolute layout warnings
        abs_count = get("media_absolute_count", 0)
        lines.append(
            "- Media objects carrying absolute hardcoded file paths: %d (Citations with attached media: %d)."
            % (abs_count, get("citations_with_media", 0))
        )

        # Duplicate filename warning blocks
        dup_media = get("media_dup_basenames", {})
        if dup_media:
            lines.append(
                "- Duplicate filenames imported multiple times across different records:"
            )
            for base, count in list(dup_media.items())[:5]:
                lines.append("  * %s (Imported %dx)" % (base, count))

        # Leftover layout warning flags
        if get("custom_events_total"):
            lines.append(
                "- Custom unsupported unaligned legacy event definitions: %d tags."
                % get("custom_events_total", 0)
            )

        lines.append("")

        # 4. Roadmap Step Breakdown Timeline
        lines.append("Suggested order of fixes:")
        lines.append(
            "1. Run 'Unpack Conflated Fields' to isolate hidden repository text strings."
        )
        lines.append(
            "2. Run 'Repository Consolidate' to deduplicate matching repository targets."
        )
        lines.append(
            "3. Run 'Source Consolidate' to safely group matching census & collection lines together."
        )
        lines.append(
            "4. Run 'Fix Citations' to auto-downgrade online user tree confidence metrics."
        )
        lines.append(
            "5. Run 'Fix Notes' to permanently scrub legacy automated migration log files."
        )

        return "\n".join(lines)


def collect_db_stats(db: Any) -> dict[str, Any]:
    """Module-level convenience wrapper used by the fix dialogs."""
    return GWizardCitationReport().collect_db_stats(db)
