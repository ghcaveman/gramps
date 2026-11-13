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
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.plugins.tool.gwizardcitationshared import (
    detect_title_elements,
    is_debris_text,
    is_tree_source_title,
    normalize_source_title,
    note_text,
)

_ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext
LOG = logging.getLogger(__name__)


def _count(singular: str, plural: str, number: int, **values: Any) -> str:
    """Translate a sentence with a count, filling ``{number_of}`` and ``values``."""
    return ngettext(singular, plural, number).format(number_of=number, **values)


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


# Lowercase words that properly start a page: Evidence Explained style
# "entry for ...", and pinpoint detail such as "page 5" or "roll 12".
_LEGIT_LOWER_START = re.compile(
    r"^(?:entry|page|pages|pg|pp?\.|sheet|roll|frame|image|film|folio|vol|"
    r"volume|book|line|item|plot|section|lot|no\.|number|digital|record)\b",
    re.IGNORECASE,
)


def _page_is_fragment(page: str) -> bool:
    """True if the text looks cut off at the start (begins lowercase, or has a
    closing parenthesis before any opening one).

    A web address and the usual lowercase openers ("entry for ...",
    "page 5") are complete values, not fragments.
    """
    text = (page or "").strip()
    if not text:
        return False
    if _URL_RE.match(text):
        return False
    if text[0].islower():
        return not _LEGIT_LOWER_START.match(text)
    close, opened = text.find(")"), text.find("(")
    return close != -1 and (opened == -1 or close < opened)


def _page_looks_like_source_text(page: str) -> bool:
    """Collection-style wording with no pinpoint detail: probably belongs in the
    source title, not the citation page."""
    text = (page or "").strip()
    if not text or _ACCESS_RE.search(text) or _URL_RE.match(text):
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


def _known_site_names() -> set[str]:
    """Return lower-cased gold-standard repository names ("Legacy.com")."""
    try:
        from gramps.plugins.tool.gw_goldstandardrepos import GoldStandardRepositories

        return {name.casefold() for name in GoldStandardRepositories.get_names()}
    except Exception:  # pylint: disable=broad-except
        return set()


def kind_of_non_title(title: str) -> str:
    """Return 'url', 'filename', 'domain' when the title is not a real title.

    A proper site name that merely looks like a domain ("Legacy.com") is a
    real title, so names of known repositories are not flagged.
    """
    t = (title or "").strip()
    if _URL_RE.match(t):
        return "url"
    if _FILENAME_RE.search(t):
        return "filename"
    if " " not in t and _DOMAIN_RE.match(t) and t.casefold() not in _known_site_names():
        return "domain"
    return ""


_kind_of_non_title = kind_of_non_title  # backward-compatible private name


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
                    if street and (
                        len(street) > 60
                        or (
                            len(street) > len(name)
                            and _strip_the(street).startswith(_strip_the(name))
                        )
                    ):
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

        # Media & Citation hygiene -------------------------------------
        try:
            from gramps.plugins.tool.gwizardcitationmediaengine import (
                audit_existing_citation_media_links,
                find_promotable_gallery_media,
                find_unpackable_source_media,
            )

            promotable = find_promotable_gallery_media(db)
            unpackable = find_unpackable_source_media(db)
            suspect_links = audit_existing_citation_media_links(db)

            stats["media_in_galleries_promotable"] = len(promotable)
            stats["media_on_sources_unpackable"] = len(unpackable)
            stats["suspect_citation_media"] = [
                {
                    "citation_handle": s["citation_handle"],
                    "media_handle": s["media_handle"],
                    "cit_display": s["citation_identity"].source_title
                    + (
                        " " + s["citation_identity"].page
                        if s["citation_identity"].page
                        else ""
                    ),
                    "media_name": s["media_identity"].filename,
                    "conflicts": s["compatibility"].conflicts,
                }
                for s in suspect_links
            ]
        except Exception as exc:  # pylint: disable=broad-except
            self._errors.record("media: citation linking scan", exc, None)
            stats["media_in_galleries_promotable"] = 0
            stats["media_on_sources_unpackable"] = 0
            stats["suspect_citation_media"] = []

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
            return [_("Scan health: every check completed without errors."), ""]
        total = sum(e["count"] for e in errors)
        lines = [
            _count(
                "Scan health: {number_of} error in {places} place(s). Counts below "
                "for the affected steps may be incomplete.",
                "Scan health: {number_of} errors in {places} place(s). Counts below "
                "for the affected steps may be incomplete.",
                total,
                places=len(errors),
            )
        ]
        for err in errors[:10]:
            first_seen = (
                " " + _("[first seen on {object}]").format(object=err["example"])
                if err["example"]
                else ""
            )
            lines.append(
                "- %s: %dx %s in %s(): %s%s"
                % (
                    err["where"],
                    err["count"],
                    err["error_type"],
                    err["function"],
                    err["message"] or _("(no message)"),
                    first_seen,
                )
            )
        if len(errors) > 10:
            lines.append(
                "- "
                + _("... and {number_of} more (see the Gramps log).").format(
                    number_of=len(errors) - 10
                )
            )
        lines.append("")
        return lines

    @staticmethod
    def _format_placement(stats: dict[str, Any]) -> list[str]:
        """Report lines for the placement / hygiene checks."""
        get = stats.get
        out: list[str] = []

        def on_source(number: int, label: str) -> str:
            return "  ↳ " + _("{number_of} on {source}").format(
                number_of=number, source=label
            )

        def id_title(row: dict[str, Any], width: int) -> str:
            return "%s '%s'" % (row["gramps_id"], row["title"][:width])

        # Citation text in the wrong place
        frag = get("page_fragments", [])
        frag_total = sum(n for _label, n in frag)
        if frag_total:
            out.append(
                "- "
                + _count(
                    "Citation pages that start mid-sentence (text cut from the "
                    "source title): {number_of}.",
                    "Citation pages that start mid-sentence (text cut from the "
                    "source title): {number_of}.",
                    frag_total,
                )
            )
            out += [on_source(n, label) for label, n in frag[:3]]
        if get("page_access_dates"):
            out.append(
                "- "
                + _(
                    "Access dates typed into the page field: {number_of} "
                    "({no_date} of them have an empty citation Date)."
                ).format(
                    number_of=get("page_access_dates", 0),
                    no_date=get("page_access_dates_no_date", 0),
                )
            )
        templates = get("page_templates", [])
        if templates and get("citations_no_page", 0) < get("citations", 0):
            out.append(
                "- "
                + _(
                    "Page text is repetitive: {number_of} distinct values; most "
                    "common patterns:"
                ).format(number_of=get("page_distinct", 0))
            )
            for tmpl, n in templates[:3]:
                out.append("  ↳ %dx %s" % (n, tmpl[:90]))
        like_src = get("page_source_like", {})
        if like_src:
            out.append(
                "- "
                + _count(
                    "Citation pages that read like a collection name (belongs in "
                    "the source title?): {number_of} source affected.",
                    "Citation pages that read like a collection name (belongs in "
                    "the source title?): {number_of} sources affected.",
                    len(like_src),
                )
            )
            for label, pages in list(like_src.items())[:4]:
                out.append("  ↳ %s: %s" % (label, "; ".join(pages[:2])[:100]))
        if get("citations_empty"):
            out.append(
                "- "
                + _(
                    "Completely empty citations (no page, date, attribute, note "
                    "or media): {number_of} of {total}."
                ).format(number_of=get("citations_empty", 0), total=get("citations", 0))
            )
            out += [
                on_source(n, label)
                for label, n in get("citations_empty_by_source", [])[:3]
            ]

        # Source field hygiene
        bad = get("sources_bad_fields", [])
        if bad:
            out.append(
                "- "
                + _(
                    "Sources with markup, stray quotes or stray whitespace in a "
                    "field: {number_of}."
                ).format(number_of=len(bad))
            )
            for row in bad[:4]:
                detail = "; ".join(
                    "%s (%s)" % (f, ", ".join(p)) for f, p in row["problems"].items()
                )
                out.append("  ↳ %s: %s" % (id_title(row, 50), detail))
        cstyle = get("sources_citation_style", [])
        if cstyle:
            out.append(
                "- "
                + _(
                    "Source titles that look like a pasted citation string: "
                    "{number_of}."
                ).format(number_of=len(cstyle))
            )
            for row in cstyle[:3]:
                out.append(
                    "  ↳ %s (%s)"
                    % (
                        id_title(row, 60),
                        _count(
                            "{number_of} citation",
                            "{number_of} citations",
                            row["citations"],
                        ),
                    )
                )
        non_titles = get("sources_non_titles", [])
        if non_titles:
            out.append(
                "- "
                + _(
                    "Source titles that are really a URL, domain or filename: "
                    "{number_of}."
                ).format(number_of=len(non_titles))
            )
            for row in non_titles[:4]:
                out.append("  ↳ %s (%s)" % (id_title(row, 200), row["kind"]))
        placeholders = get("sources_placeholder", [])
        if placeholders:
            cites = sum(r["citations"] for r in placeholders)
            out.append(
                "- "
                + _count(
                    "Placeholder sources ('Unknown' / blank): {sources}, holding "
                    "{number_of} citation.",
                    "Placeholder sources ('Unknown' / blank): {sources}, holding "
                    "{number_of} citations.",
                    cites,
                    sources=len(placeholders),
                )
            )
        unused = get("sources_unused", [])
        if unused:
            out.append(
                "- "
                + _("Sources with no citations at all: {number_of}.").format(
                    number_of=len(unused)
                )
            )

        # Duplicates the strict title match misses
        for key, text, limit in (
            (
                "dupes_loose",
                _(
                    "Duplicate sources hidden by 'U.S.' / punctuation differences "
                    "(safe to merge): {number_of} clusters."
                ),
                5,
            ),
            (
                "dupes_year_variants",
                _(
                    "Same collection, different year range (check before "
                    "merging): {number_of} clusters."
                ),
                4,
            ),
        ):
            groups = get(key, [])
            if groups:
                out.append("- " + text.format(number_of=len(groups)))
                for group in groups[:limit]:
                    out.append("  ↳ " + "; ".join(id_title(r, 45) for r in group[:3]))

        # Repository hygiene
        for key, text in (
            ("repos_unused", _("Repositories not linked to any source: {number_of}.")),
            (
                "repos_address_is_name",
                _("Repositories whose address just repeats the name: {number_of}."),
            ),
            (
                "repos_packed_address",
                _(
                    "Repositories with a long address field (likely several "
                    "places or notes packed in): {number_of}."
                ),
            ),
        ):
            value = get(key)
            if value and hasattr(value, "__len__"):
                out.append("- " + text.format(number_of=len(value)))
        return out

    def format_analysis(self, stats: dict[str, Any]) -> str:
        """Formats the collected statistics dictionary into a deep, descriptive report body."""
        get = stats.get
        lines = []

        # 1. Database Totals Block
        lines.append(
            _(
                "Database totals: {people} people, {sources} sources, "
                "{repositories} repositories, {citations} citations, "
                "{notes} notes, {media} media."
            ).format(
                people=get("people", 0),
                sources=get("sources", 0),
                repositories=get("repositories", 0),
                citations=get("citations", 0),
                notes=get("notes", 0),
                media=get("media", 0),
            )
        )
        lines.append("")

        # 1b. Scan health: Gramps methods that raised exceptions
        lines.extend(self._format_scan_errors(stats))

        # 2. Positive Alignments / Best Practices
        lines.append(_("Where it matches best practice:"))
        lines.append(
            "- "
            + _(
                "Most sources are collection-level with specifics in citations "
                "(Evidence Explained approach)."
            )
        )
        lines.append("")

        # 3. Deficiencies / Diagnostic Room for Improvement
        lines.append(_("Where it falls short:"))

        def of_total(text: str, number: int, total: int) -> str:
            return "- " + text.format(number_of=number, total=total)

        lines.append(
            of_total(
                _("Sources without a repository link: {number_of} of {total}."),
                len(get("sources_no_repo", [])),
                get("sources", 0),
            )
        )

        conflated = get("conflated_sources", [])
        lines.append(
            "- "
            + _count(
                "Conflated fields: {number_of} source mixes repository, source "
                "and citation text.",
                "Conflated fields: {number_of} sources mix repository, source "
                "and citation text.",
                len(conflated),
            )
        )
        for row in conflated[:10]:
            lines.append(
                "  * %s: '%s'\n    ↳ %s"
                % (
                    row.get("gramps_id"),
                    row.get("title"),
                    _("Found elements: {elements}").format(
                        elements=", ".join(row.get("elements_detected", []))
                    ),
                )
            )

        lines.append(
            of_total(
                _(
                    "Citations with no pinpoint Volume/Page detail: {number_of} "
                    "of {total}."
                ),
                get("citations_no_page", 0),
                get("citations", 0),
            )
        )

        if get("tree_citations"):
            lines.append(
                "- "
                + _(
                    "Collaborative tree citations found: {number_of} (rated "
                    "High/Very High confidence: {high})."
                ).format(
                    number_of=get("tree_citations", 0), high=get("tree_conf_high", 0)
                )
            )

        lines.append(
            of_total(
                _(
                    "Individuals with zero attached source citations: {number_of} "
                    "of {total}."
                ),
                get("people_unsourced", 0),
                get("people", 0),
            )
        )

        dupes = get("near_duplicates", [])
        lines.append(
            "- "
            + _("Near-duplicate source title clusters found: {number_of}.").format(
                number_of=len(dupes)
            )
        )
        for group in dupes[:7]:
            joined = "; ".join(
                "%s '%s'" % (r.get("gramps_id"), r.get("title")) for r in group[:4]
            )
            lines.append("  ↳ " + _("Cluster: {titles}").format(titles=joined))

        # Extra placement & hygiene findings ----------------------------
        lines.extend(self._format_placement(stats))

        debris = get("notes_debris", [])
        lines.append(
            "- "
            + _count(
                "Import debris and migration logs inside notes: {number_of} note.",
                "Import debris and migration logs inside notes: {number_of} notes.",
                len(debris),
            )
        )
        for row in debris[:5]:
            lines.append(
                "  ↳ "
                + _("Note {gramps_id}: {preview}").format(
                    gramps_id=row.get("gramps_id"), preview=row.get("preview")
                )
            )

        long_notes = get("notes_long", [])
        if long_notes:
            lines.append("- " + _("Long life-sketch narrative notes:"))
            for row in long_notes[:3]:
                lines.append(
                    "  ↳ "
                    + _("Note {gramps_id} ({length} characters): {preview}...").format(
                        gramps_id=row.get("gramps_id"),
                        length=row.get("length"),
                        preview=row.get("preview"),
                    )
                )

        lines.append(
            "- "
            + _(
                "Media objects with absolute file paths: {number_of} (citations "
                "with attached media: {with_media} of {total})."
            ).format(
                number_of=get("media_absolute_count", 0),
                with_media=get("citations_with_media", 0),
                total=get("citations", 0),
            )
        )

        promotable_count = get("media_in_galleries_promotable", 0)
        if promotable_count:
            lines.append(
                "  ↳ "
                + _count(
                    "Document scans in Person/Event galleries matching "
                    "citations: {number_of} item.",
                    "Document scans in Person/Event galleries matching "
                    "citations: {number_of} items.",
                    promotable_count,
                )
            )

        unpackable_count = get("media_on_sources_unpackable", 0)
        if unpackable_count:
            lines.append(
                "  ↳ "
                + _count(
                    "Media on top-level sources that belongs on specific "
                    "citations: {number_of} item.",
                    "Media on top-level sources that belongs on specific "
                    "citations: {number_of} items.",
                    unpackable_count,
                )
            )

        suspect = get("suspect_citation_media", [])
        if suspect:
            lines.append(
                "- "
                + _count(
                    "Suspect media attachments on citations: {number_of} conflict.",
                    "Suspect media attachments on citations: {number_of} conflicts.",
                    len(suspect),
                )
            )
            for item in suspect[:5]:
                lines.append(
                    "  ⚠ "
                    + _(
                        "Citation '{citation}' <-> Media '{media}': {conflicts}"
                    ).format(
                        citation=item.get("cit_display"),
                        media=item.get("media_name"),
                        conflicts="; ".join(item.get("conflicts", [])),
                    )
                )

        dup_media = get("media_dup_basenames", {})
        if dup_media:
            lines.append(
                "- " + _("File names imported several times as different records:")
            )
            for base, count in list(dup_media.items())[:5]:
                lines.append(
                    "  * "
                    + _("{file_name} (imported {number_of} times)").format(
                        file_name=base, number_of=count
                    )
                )

        if get("custom_events_total"):
            lines.append(
                "- "
                + _("Custom (non-standard) event types in use: {number_of}.").format(
                    number_of=get("custom_events_total", 0)
                )
            )

        lines.append("")

        # 4. Suggested order: the wizard's steps, then any extra hand work.
        steps = [
            _("Run 'Unpack Conflated Source' to separate repository text from titles."),
            _("Run 'Repository Consolidate' to merge duplicate repositories."),
            _("Run 'Fix Repositories' to link every source to a repository."),
            _("Run 'Fix Sources' to merge duplicate census and collection sources."),
            _(
                "Run 'Unpack Conflated Citation' to separate access dates, URLs "
                "and Volume/Page text."
            ),
            _("Run 'Fix Citations' to lower the confidence of online tree citations."),
            _("Run 'Citation Attributes' to add GPS quality attributes."),
            _(
                "Run 'Link Citation Media' to link checked (locked) document "
                "scans to citations."
            ),
            _("Run 'Fix Notes' to remove leftover import logs from notes."),
        ]
        if (
            get("sources_bad_fields")
            or get("sources_citation_style")
            or get("page_fragments")
            or get("page_access_dates_no_date")
        ):
            steps.append(
                _(
                    "Clean source titles (markup, quotes) and move access dates "
                    "and entry detail out of the source and into the citation."
                )
            )
        if get("page_source_like") or get("sources_non_titles"):
            steps.append(
                _(
                    "Review the flagged pages and URL/filename titles by hand; "
                    "there are usually only a handful."
                )
            )
        if get("sources_placeholder"):
            steps.append(_("Merge or delete the placeholder 'Unknown' sources."))
        lines.append(_("Suggested order of fixes:"))
        lines += ["%d. %s" % (number, step) for number, step in enumerate(steps, 1)]

        return "\n".join(lines)


def collect_db_stats(db: Any) -> dict[str, Any]:
    """Module-level convenience wrapper used by the fix dialogs."""
    return GWizardCitationReport().collect_db_stats(db)
