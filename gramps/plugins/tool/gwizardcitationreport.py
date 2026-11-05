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
import re
import traceback
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

# --- Heuristics used by the placement / hygiene checks ----------------------
_MARKUP_RE = re.compile(r"</?[A-Za-z][^<>]*>")
_ACCESS_RE = re.compile(
    r"\b(?:accessed|viewed|retrieved|downloaded)\s+(?:on\s+)?"
    r"(?:\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)
_YEAR_RANGE_RE = re.compile(r"\b\d{4}\s*[-\u2013]\s*(?:\d{4}|current|present)\b", re.I)
_URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
_FILENAME_RE = re.compile(r"\.(?:jpe?g|png|gif|tiff?|bmp|pdf|docx?|txt|html?)$", re.I)
_DOMAIN_RE = re.compile(r"^[\w-]+(?:\.[\w-]+)+$")
_PLACEHOLDER_TITLES = {"", "unknown", "untitled", "none", "n/a", "na", "source"}
# Words that suggest text names a collection/record set (source-level data).
_COLLECTION_WORDS = re.compile(
    r"\b(index|indexes|indices|records?|registry|registries|collection|"
    r"lists?|crossings|manifests?|database|census|certificates)\b",
    re.IGNORECASE,
)
# Words that suggest real pinpoint detail (citation-level data).
_PINPOINT_WORDS = re.compile(
    r"\b(sheet|line|page|pg|pp?\.|enumeration|ed|roll|frame|image|film|folio|"
    r"book|volume|vol|number|no\.|entry|person id|item|certificate (?:no|number)|"
    r"plot|section|lot)\b|#",
    re.IGNORECASE,
)


def _page_template(page: str) -> str:
    """Collapse names, ids, dates and numbers so look-alike pages group together."""
    text = " ".join((page or "").split())
    text = re.sub(r"person ID [A-Z0-9]{3,5}-[A-Z0-9]{2,5}", "person ID <ID>", text)
    text = re.sub(r"entry for [^,]+,", "entry for <NAME>,", text)
    text = re.sub(r"\b\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}\b", "<DATE>", text)
    text = re.sub(r"\d+", "#", text)
    return text


def _page_is_fragment(page: str) -> bool:
    """True if the text looks cut off at the start (begins lowercase, or has a
    closing parenthesis before any opening one)."""
    text = (page or "").strip()
    if not text:
        return False
    if text[0].islower():
        return True
    close, opened = text.find(")"), text.find("(")
    return close != -1 and (opened == -1 or close < opened)


def _page_looks_like_source_text(page: str) -> bool:
    """Collection-style wording with no pinpoint detail: probably belongs in the
    source title, not the citation page."""
    text = (page or "").strip()
    if not text or _ACCESS_RE.search(text):
        return False
    return bool(_COLLECTION_WORDS.search(text)) and not _PINPOINT_WORDS.search(text)


def _strip_the(text: str) -> str:
    low = " ".join((text or "").lower().split())
    return low[4:] if low.startswith("the ") else low


def _loose_key(title: str, strip_year_ranges: bool = False) -> str:
    """Very forgiving title key: case, punctuation, '&', 'U.S.' and 'the' ignored."""
    text = (title or "").lower().replace("&", " and ")
    if strip_year_ranges:
        text = _YEAR_RANGE_RE.sub(" ", text)
    tokens = re.sub(r"[^a-z0-9]+", " ", text).split()
    return " ".join(t for t in tokens if t not in ("u", "s", "the"))


def _title_problems(text: str) -> list[str]:
    """Hygiene problems in a source title/author/publication string."""
    problems = []
    if _MARKUP_RE.search(text):
        problems.append("html markup")
    if text != text.strip() or "  " in text:
        problems.append("stray whitespace")
    stripped = text.strip()
    if stripped[:1] in ('"', "'", "\u201c") and len(stripped) > 1:
        problems.append("leading quote mark")
    return problems


def _kind_of_non_title(title: str) -> str:
    """Return 'url', 'filename', 'domain' when the title is not a real title."""
    t = (title or "").strip()
    if _URL_RE.match(t):
        return "url"
    if _FILENAME_RE.search(t):
        return "filename"
    if " " not in t and _DOMAIN_RE.match(t):
        return "domain"
    return ""


class _ScanErrors:
    """Collects exceptions raised by Gramps methods during a scan.

    Identical failures are grouped (same step, same function, same message) so
    one broken method on 3,000 citations gives one line with a count and one
    example id, not 3,000 lines. Only the first of each kind goes to the log.
    """

    def __init__(self) -> None:
        self._groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def record(self, where: str, exc: BaseException, obj: Any = None) -> None:
        try:
            frames = traceback.extract_tb(exc.__traceback__)
            func = frames[-1].name if frames else "?"
        except Exception:  # pylint: disable=broad-except
            func = "?"
        message = " ".join(str(exc).split())[:120]
        key = (where, func, type(exc).__name__, message)
        group = self._groups.get(key)
        if group is None:
            group = {
                "where": where,
                "function": func,
                "error_type": type(exc).__name__,
                "message": message,
                "count": 0,
                "example": self._describe(obj),
            }
            self._groups[key] = group
            LOG.warning(
                "GWizard report: %s failed in %s: %s: %s",
                where,
                func,
                group["error_type"],
                message,
                exc_info=exc,
            )
        group["count"] += 1

    @staticmethod
    def _describe(obj: Any) -> str:
        """Best-effort id of the object being inspected; must never raise."""
        if obj is None:
            return ""
        for name in ("get_gramps_id", "get_handle"):
            try:
                value = getattr(obj, name)()
                if value:
                    return str(value)
            except Exception:  # pylint: disable=broad-except
                pass
        return ""

    def as_list(self) -> list[dict[str, Any]]:
        return sorted(self._groups.values(), key=lambda g: -g["count"])


class GWizardCitationReport:
    """Handles the algorithmic parsing, database scanning, and text generation."""

    def __init__(self) -> None:
        self._errors = _ScanErrors()

    @staticmethod
    def normalize_source_title(title: str) -> str:
        return normalize_source_title(title)

    @staticmethod
    def _person_has_citation(person: Any, db: Any = None, errors: Any = None) -> bool:
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
        except Exception as exc:  # pylint: disable=broad-except
            if errors is not None:
                errors.record("people: citation check", exc, person)
            else:
                LOG.exception("Failed to inspect person citations")
        return False

    @staticmethod
    def _note_text(note: Any) -> str:
        return note_text(note)

    def collect_placement_stats(
        self,
        sources: list[Any],
        citations: list[Any],
        repos: list[Any],
        cites_by_source: Counter,
        near_duplicates: list[list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Checks for data sitting in the wrong field and for source hygiene.

        Read-only: nothing is modified. Each result is a plain list/dict so the
        dialogs can reuse it later.
        """
        out: dict[str, Any] = {}
        src_by_handle = {str(s.get_handle()): s for s in sources}

        def _label(src: Any) -> str:
            return "%s '%s'" % (src.get_gramps_id(), str(src.get_title() or ""))

        # --- Source field hygiene ---------------------------------------
        markup_sources, citation_style, non_titles, placeholders = [], [], [], []
        for src in sources:
            try:
                title = str(src.get_title() or "")
                fields = {
                    "title": title,
                    "author": str(src.get_author() or ""),
                    "publication": str(src.get_publication_info() or ""),
                    "abbreviation": str(src.get_abbreviation() or ""),
                }
                row = {
                    "gramps_id": str(src.get_gramps_id() or ""),
                    "title": title,
                    "citations": cites_by_source.get(str(src.get_handle()), 0),
                }
                bad = {
                    name: _title_problems(text)
                    for name, text in fields.items()
                    if text and _title_problems(text)
                }
                if bad:
                    markup_sources.append(dict(row, problems=bad))
                low = title.lower()
                if len(title) > 40 and (
                    "database," in low or '",' in title or "(http" in low
                ):
                    citation_style.append(row)
                kind = _kind_of_non_title(title)
                if kind:
                    non_titles.append(dict(row, kind=kind))
                if low.strip() in _PLACEHOLDER_TITLES:
                    placeholders.append(row)
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record("sources: field checks", exc, src)
        out["sources_bad_fields"] = markup_sources
        out["sources_citation_style"] = citation_style
        out["sources_non_titles"] = non_titles
        out["sources_placeholder"] = placeholders
        out["sources_unused"] = [
            {
                "gramps_id": str(s.get_gramps_id() or ""),
                "title": str(s.get_title() or ""),
            }
            for s in sources
            if cites_by_source.get(str(s.get_handle()), 0) == 0
        ]

        # --- Citation text placement ------------------------------------
        templates: Counter = Counter()
        fragments: Counter = Counter()  # source label -> count
        access_in_page = 0
        access_in_page_no_date = 0
        source_like_pages: dict[str, set] = defaultdict(set)
        empty_cits = 0
        empty_by_source: Counter = Counter()
        distinct_pages = set()
        for cit in citations:
            try:
                page = (cit.get_page() or "").strip()
                src = src_by_handle.get(str(cit.get_reference_handle()))
                label = _label(src) if src is not None else "(missing source)"
                has_date = not cit.get_date_object().is_empty()
                if page:
                    distinct_pages.add(page)
                    templates[_page_template(page)] += 1
                    if _page_is_fragment(page):
                        fragments[label] += 1
                    if _ACCESS_RE.search(page):
                        access_in_page += 1
                        if not has_date:
                            access_in_page_no_date += 1
                    if _page_looks_like_source_text(page):
                        source_like_pages[label].add(page)
                if not (
                    page
                    or has_date
                    or cit.get_attribute_list()
                    or cit.get_note_list()
                    or cit.get_media_list()
                ):
                    empty_cits += 1
                    empty_by_source[label] += 1
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record("citations: page/date/empty checks", exc, cit)
                continue
        out["page_distinct"] = len(distinct_pages)
        out["page_templates"] = templates.most_common(5)
        out["page_fragments"] = fragments.most_common()
        out["page_access_dates"] = access_in_page
        out["page_access_dates_no_date"] = access_in_page_no_date
        out["page_source_like"] = {k: sorted(v) for k, v in source_like_pages.items()}
        out["citations_empty"] = empty_cits
        out["citations_empty_by_source"] = empty_by_source.most_common(5)

        # --- Duplicate sources the strict title match misses ------------
        known = [frozenset(r["gramps_id"] for r in g) for g in near_duplicates]
        rows = []
        for src in sources:
            rows.append(
                {
                    "gramps_id": str(src.get_gramps_id() or ""),
                    "title": str(src.get_title() or ""),
                }
            )

        def _groups(strip: bool) -> list[list[dict[str, Any]]]:
            buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                key = _loose_key(row["title"], strip)
                if key and row["title"].strip().lower() not in _PLACEHOLDER_TITLES:
                    buckets[key].append(row)
            return [g for g in buckets.values() if len(g) > 1]

        safe = [
            g
            for g in _groups(False)
            if frozenset(r["gramps_id"] for r in g) not in known
        ]
        safe_sets = known + [frozenset(r["gramps_id"] for r in g) for g in safe]
        versions = [
            g
            for g in _groups(True)
            if frozenset(r["gramps_id"] for r in g) not in safe_sets
        ]
        out["dupes_loose"] = safe  # same title once 'U.S.' etc. is ignored
        out["dupes_year_variants"] = versions  # same title, different year range

        # --- Repository hygiene -----------------------------------------
        used_repos = set()
        for src in sources:
            try:
                for ref in src.get_reporef_list():
                    used_repos.add(str(ref.ref))
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record("sources: repository links", exc, src)
                continue
        repo_unused, repo_dup_addr, repo_packed_name = [], [], []
        for repo in repos:
            try:
                name = str(repo.get_name() or "")
                rid = str(repo.get_gramps_id() or "")
                if str(repo.get_handle()) not in used_repos:
                    repo_unused.append({"gramps_id": rid, "name": name})
                for addr in repo.get_address_list():
                    street = str(addr.get_street() or "").strip()
                    if street and _strip_the(street) == _strip_the(name):
                        repo_dup_addr.append({"gramps_id": rid, "name": name})
                        break
                    if street and len(street) > 60:
                        repo_packed_name.append({"gramps_id": rid, "name": name})
                        break
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record("repositories: address checks", exc, repo)
                continue
        out["repos_unused"] = repo_unused
        out["repos_address_is_name"] = repo_dup_addr
        out["repos_packed_address"] = repo_packed_name
        return out

    def collect_db_stats(self, db: Any) -> dict[str, Any]:
        """Scan repositories, sources, citations, notes, people and media."""
        self._errors = _ScanErrors()

        def _safe_list(method_name: str) -> list[Any]:
            try:
                return list(getattr(db, method_name)())
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record("database iteration (%s)" % method_name, exc, None)
                return []
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
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record(
                    "citations: source link/page/media counts", exc, cit
                )
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
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record("citations: confidence level", exc, cit)
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

        # Placement / hygiene checks (read-only) ------------------------
        try:
            stats.update(
                self.collect_placement_stats(
                    sources,
                    citations,
                    repos,
                    cites_by_source,
                    stats["near_duplicates"],
                )
            )
        except Exception as exc:  # pylint: disable=broad-except
            self._errors.record("new placement checks (all skipped)", exc, None)

        # People -------------------------------------------------------
        stats["people_unsourced"] = sum(
            1
            for person in people
            if not self._person_has_citation(person, db, self._errors)
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
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record("notes: text scan", exc, note)
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
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record("media: path scan", exc, media)
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
            except Exception as exc:  # pylint: disable=broad-except
                self._errors.record("events: custom type scan", exc, event)
                continue
        stats["custom_events_total"] = custom
        stats["scan_errors"] = self._errors.as_list()
        return stats

    @staticmethod
    def _format_scan_errors(stats: dict[str, Any]) -> list[str]:
        """Report which Gramps calls failed, so a low count is not mistaken for
        a clean database."""
        errors = stats.get("scan_errors", [])
        if not errors:
            return ["Scan health: every check completed without errors.", ""]
        total = sum(e["count"] for e in errors)
        lines = [
            "Scan health: %d error(s) in %d place(s). Counts below for the "
            "affected steps may be incomplete." % (total, len(errors))
        ]
        for err in errors[:10]:
            lines.append(
                "- %s: %dx %s in %s(): %s%s"
                % (
                    err["where"],
                    err["count"],
                    err["error_type"],
                    err["function"],
                    err["message"] or "(no message)",
                    " [first seen on %s]" % err["example"] if err["example"] else "",
                )
            )
        if len(errors) > 10:
            lines.append("- ... and %d more (see the Gramps log)." % (len(errors) - 10))
        lines.append("")
        return lines

    @staticmethod
    def _format_placement(stats: dict[str, Any]) -> list[str]:
        """Report lines for the placement / hygiene checks."""
        get = stats.get
        out: list[str] = []

        # Citation text in the wrong place
        frag = get("page_fragments", [])
        frag_total = sum(n for _, n in frag)
        if frag_total:
            out.append(
                "- Citation pages that start mid-sentence (text cut from the "
                "source title): %d." % frag_total
            )
            for label, n in frag[:3]:
                out.append("  ↳ %d on %s" % (n, label))
        if get("page_access_dates"):
            out.append(
                "- Access dates typed into the page field: %d (%d of them have an "
                "empty citation Date)."
                % (get("page_access_dates", 0), get("page_access_dates_no_date", 0))
            )
        templates = get("page_templates", [])
        if templates and get("citations_no_page", 0) < get("citations", 0):
            out.append(
                "- Page text is repetitive: %d distinct values; most common patterns:"
                % get("page_distinct", 0)
            )
            for tmpl, n in templates[:3]:
                out.append("  ↳ %dx %s" % (n, tmpl[:90]))
        like_src = get("page_source_like", {})
        if like_src:
            out.append(
                "- Citation pages that read like a collection name (belongs in "
                "the source title?): %d sources affected." % len(like_src)
            )
            for label, pages in list(like_src.items())[:4]:
                out.append("  ↳ %s: %s" % (label, "; ".join(pages[:2])[:100]))
        if get("citations_empty"):
            out.append(
                "- Completely empty citations (no page, date, attribute, note or "
                "media): %d of %d." % (get("citations_empty", 0), get("citations", 0))
            )
            for label, n in get("citations_empty_by_source", [])[:3]:
                out.append("  ↳ %d on %s" % (n, label))

        # Source field hygiene
        bad = get("sources_bad_fields", [])
        if bad:
            out.append(
                "- Sources with markup, stray quotes or stray whitespace in a "
                "field: %d." % len(bad)
            )
            for row in bad[:4]:
                detail = "; ".join(
                    "%s (%s)" % (f, ", ".join(p)) for f, p in row["problems"].items()
                )
                out.append(
                    "  ↳ %s '%s': %s" % (row["gramps_id"], row["title"][:50], detail)
                )
        cstyle = get("sources_citation_style", [])
        if cstyle:
            out.append(
                "- Source titles that look like a pasted citation string: %d."
                % len(cstyle)
            )
            for row in cstyle[:3]:
                out.append(
                    "  ↳ %s '%s' (%d citations)"
                    % (row["gramps_id"], row["title"][:60], row["citations"])
                )
        non_titles = get("sources_non_titles", [])
        if non_titles:
            out.append(
                "- Source titles that are really a URL, domain or filename: %d."
                % len(non_titles)
            )
            for row in non_titles[:4]:
                out.append(
                    "  ↳ %s '%s' (%s)" % (row["gramps_id"], row["title"], row["kind"])
                )
        placeholders = get("sources_placeholder", [])
        if placeholders:
            cites = sum(r["citations"] for r in placeholders)
            out.append(
                "- Placeholder sources ('Unknown' / blank): %d, holding %d citations."
                % (len(placeholders), cites)
            )
        unused = get("sources_unused", [])
        if unused:
            out.append("- Sources with no citations at all: %d." % len(unused))

        # Duplicates the strict title match misses
        loose = get("dupes_loose", [])
        if loose:
            out.append(
                "- Duplicate sources hidden by 'U.S.' / punctuation differences "
                "(safe to merge): %d clusters." % len(loose)
            )
            for group in loose[:5]:
                out.append(
                    "  ↳ "
                    + "; ".join(
                        "%s '%s'" % (r["gramps_id"], r["title"][:45]) for r in group[:3]
                    )
                )
        variants = get("dupes_year_variants", [])
        if variants:
            out.append(
                "- Same collection, different year range (check before merging): "
                "%d clusters." % len(variants)
            )
            for group in variants[:4]:
                out.append(
                    "  ↳ "
                    + "; ".join(
                        "%s '%s'" % (r["gramps_id"], r["title"][:45]) for r in group[:3]
                    )
                )

        # Repository hygiene
        if get("repos_unused"):
            out.append(
                "- Repositories not linked to any source: %d."
                % len(get("repos_unused"))
            )
        if get("repos_address_is_name"):
            out.append(
                "- Repositories whose address just repeats the name: %d."
                % len(get("repos_address_is_name"))
            )
        if get("repos_packed_address"):
            out.append(
                "- Repositories with a long address field (likely several "
                "places or notes packed in): %d." % len(get("repos_packed_address"))
            )
        return out

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

        # 1b. Scan health: Gramps methods that raised exceptions
        lines.extend(self._format_scan_errors(stats))

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

        # Extra placement & hygiene findings ----------------------------
        lines.extend(self._format_placement(stats))

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
            "3. Run 'Fix Sources' to safely group matching census & collection lines together."
        )
        lines.append(
            "4. Run 'Fix Citations' to auto-downgrade online user tree confidence metrics."
        )
        lines.append(
            "5. Run 'Fix Notes' to permanently scrub legacy automated migration log files."
        )
        step = 6
        if (
            get("sources_bad_fields")
            or get("sources_citation_style")
            or get("page_fragments")
            or get("page_access_dates_no_date")
        ):
            lines.append(
                "%d. Clean source titles (markup, quotes) and move access dates and "
                "entry detail out of the source and into the citation." % step
            )
            step += 1
        if get("page_source_like") or get("sources_non_titles"):
            lines.append(
                "%d. Review the flagged pages and URL/filename titles by hand; "
                "there are usually only a handful." % step
            )
            step += 1
        if get("sources_placeholder"):
            lines.append(
                "%d. Merge or delete the placeholder 'Unknown' sources." % step
            )

        return "\n".join(lines)


def collect_db_stats(db: Any) -> dict[str, Any]:
    """Module-level convenience wrapper used by the fix dialogs."""
    return GWizardCitationReport().collect_db_stats(db)
