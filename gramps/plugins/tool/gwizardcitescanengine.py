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

"""
GWizard Citation Improvement Scan: the Multi-Archive Record Scan seen from
the citations' side.

Every citation in the Family Tree is checked for missing or poor data (no
page, no date, no image, a source title that is a web address, a source
with no repository, ...). Each problem has a weight; the weights add up to
a "work" score from 0 (nothing to fix) to 100, and the window lists the
citations worst first.

Record sources
--------------
Online records are found through the Multi-Archive Record Scan's record
sources (WikiTree, NARA, ...; see gwizard_filemerge_recordscan), searched
for the person a citation is attached to. Results are shared with that
scan through its cache, so a person searched by either window costs no
second request.

Citation sources
----------------
A record source can be given a citation adapter (a CitationSource with the
same ``source_id``), registered as a GENERAL plugin with
``category="GWizardCitationSource"``, the same way record sources are. An
adapter knows which of its records a citation already points at (a NARA
NAID, say), adds its own checks (a cited NARA record whose images are not
attached), judges how well a record fits a citation, and can open a cited
record. A record source without an adapter still works: GenericCitationSource
judges records from their titles and years.

Confidence
----------
The confidence of a record for a citation is the record's match score for
the citation's person (gwizard_base.score_record), moved up or down by up
to RELEVANCE_POINTS by how well the record fits the citation itself (its
source title and date). A record the citation already cites is 100.

This module has no GTK dependency; the window is gwizardcitescandialog.py.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import abc
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.display.name import displayer as name_displayer
from gramps.gen.gwizard.gwizard_base import score_record
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    PersonScan,
    RecordSource,
    SourceMatch,
)
from gramps.gen.lib import Citation

# The Citation Fix report's checks, reused so both tools judge a page or a
# source title the same way. They are private there, and that file belongs
# to the gwizard_citationfix branch, so they are imported under their own
# names rather than renamed here.
from gramps.plugins.tool.gwizardcitationreport import (
    _PLACEHOLDER_TITLES as PLACEHOLDER_TITLES,
    _page_is_fragment as page_is_fragment,
    _page_looks_like_source_text as page_looks_like_source_text,
    kind_of_non_title,
)
from gramps.plugins.tool.gwizardcitationshared import is_tree_source_title

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# The GENERAL plugin category citation adapters register under.
CITATION_SOURCE_CATEGORY = "GWizardCitationSource"

# Citations with at least this much work are searched by default.
DEFAULT_MIN_WORK = 20
# People searched online per scan click, by default (cached people are
# free). Keeps one click from using up a site's monthly allowance.
DEFAULT_MAX_PEOPLE = 25
# How far (in points) a record's fit with the citation moves its confidence.
RELEVANCE_POINTS = 15.0
# Records below this confidence are not offered.
MIN_CONFIDENCE = 40.0
# A cited record's confidence.
CITED_CONFIDENCE = 100.0

# Gramps citation confidence levels (Citation.CONF_*).
_CONF_LOW = Citation.CONF_LOW

_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20[0-4]\d)\b")
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset("""
    the and for from with into this that records record index indexes
    united states state county national archives collection database
    online family tree film image images page list lists
    """.split())


# ------------------------------------------------------------
#
# Issues
#
# ------------------------------------------------------------
# Issue codes, their weights (work points) and which part needs the fix.
NO_SOURCE = "no_source"
SOURCE_PLACEHOLDER = "source_placeholder"
SOURCE_NOT_TITLE = "source_not_title"
SOURCE_TREE = "source_tree"
SOURCE_NO_REPO = "source_no_repo"
SOURCE_NO_AUTHOR = "source_no_author"
NO_PAGE = "no_page"
PAGE_FRAGMENT = "page_fragment"
PAGE_SOURCE_TEXT = "page_source_text"
NO_DATE = "no_date"
NO_MEDIA = "no_media"
MEDIA_MISSING = "media_missing"
MEDIA_WEB_ONLY = "media_web_only"
NO_NOTE = "no_note"
LOW_CONFIDENCE = "low_confidence"
NOT_USED = "not_used"
RECORD_NO_MEDIA = "record_no_media"

PART_SOURCE = "source"
PART_CITATION = "citation"
PART_MEDIA = "media"
PART_RECORD = "record"

WEIGHTS: dict[str, int] = {
    NO_SOURCE: 40,
    SOURCE_PLACEHOLDER: 25,
    SOURCE_TREE: 25,
    SOURCE_NOT_TITLE: 20,
    SOURCE_NO_REPO: 10,
    SOURCE_NO_AUTHOR: 3,
    NO_PAGE: 15,
    PAGE_FRAGMENT: 10,
    PAGE_SOURCE_TEXT: 8,
    NO_DATE: 8,
    NO_MEDIA: 20,
    MEDIA_MISSING: 15,
    MEDIA_WEB_ONLY: 5,
    NO_NOTE: 4,
    LOW_CONFIDENCE: 8,
    NOT_USED: 10,
    RECORD_NO_MEDIA: 20,
}


@dataclass
class Issue:
    """One problem with a citation, and how much it adds to the work score."""

    code: str
    text: str
    part: str
    weight: int = 0

    def __post_init__(self) -> None:
        """Take the weight from WEIGHTS when none is given."""
        if not self.weight:
            self.weight = WEIGHTS.get(self.code, 5)


def make_issue(code: str, part: str, text: str = "") -> Issue:
    """Return an Issue with its usual text."""
    return Issue(code, text or issue_text(code), part)


def issue_text(code: str) -> str:
    """Return the usual description of an issue."""
    texts = {
        NO_SOURCE: _("The citation has no source."),
        SOURCE_PLACEHOLDER: _("The source title is a placeholder."),
        SOURCE_NOT_TITLE: _("The source title is a web address or file name."),
        SOURCE_TREE: _("The source is someone's online family tree."),
        SOURCE_NO_REPO: _("The source has no repository."),
        SOURCE_NO_AUTHOR: _("The source has no author or publication facts."),
        NO_PAGE: _("No page (volume/page/line, or entry) is given."),
        PAGE_FRAGMENT: _("The page looks cut off."),
        PAGE_SOURCE_TEXT: _(
            "The page names a collection; it may belong in the source."
        ),
        NO_DATE: _("The citation has no date."),
        NO_MEDIA: _("No image of the record is attached."),
        MEDIA_MISSING: _("An attached image file is missing on disk."),
        MEDIA_WEB_ONLY: _("An attached image is only a web link, not downloaded."),
        NO_NOTE: _("No transcription or note."),
        LOW_CONFIDENCE: _("The citation's confidence is low."),
        NOT_USED: _("Nothing cites this citation (no person, event or family)."),
        RECORD_NO_MEDIA: _(
            "No image is attached, but the citation names an online record "
            "that may have images to download."
        ),
    }
    return texts.get(code, code)


# ------------------------------------------------------------
#
# CitationItem
#
# ------------------------------------------------------------
@dataclass
class CitationItem:
    """What the scan knows about one citation, read up front."""

    handle: str
    gramps_id: str
    source_handle: str = ""
    source_id: str = ""
    source_title: str = ""
    page: str = ""
    date_text: str = ""
    year: int | None = None
    confidence: int = Citation.CONF_NORMAL
    media_count: int = 0
    # (person handle, display name), most important first
    people: list[tuple[str, str]] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    # record source id -> keys of that source's records this citation cites
    record_keys: dict[str, list[str]] = field(default_factory=dict)

    @property
    def work(self) -> int:
        """The work score: the issue weights added up, at most 100."""
        return min(100, sum(issue.weight for issue in self.issues))

    @property
    def quality(self) -> int:
        """100 minus the work score."""
        return 100 - self.work

    @property
    def person_handle(self) -> str:
        """The person a search is made for ('' when none)."""
        return self.people[0][0] if self.people else ""

    def person_text(self) -> str:
        """Return the first person's name, and how many others there are."""
        if not self.people:
            return ""
        name = self.people[0][1]
        others = len(self.people) - 1
        return f"{name} (+{others})" if others else name

    def sort_key(self) -> tuple[int, str]:
        """Most work first, then by ID."""
        return (-self.work, self.gramps_id)

    def issue_summary(self) -> str:
        """Return the issues, heaviest first, as one short line."""
        ordered = sorted(self.issues, key=lambda issue: -issue.weight)
        return "; ".join(issue.text.rstrip(".") for issue in ordered)


# ------------------------------------------------------------
#
# Reading the Family Tree
#
# ------------------------------------------------------------
def _display_name(person: Any) -> str:
    """Return a person's display name, or their ID."""
    try:
        return name_displayer.display(person) or person.get_gramps_id()
    except Exception:
        return str(person.get_gramps_id() or "")


def citation_people(db: Any, citation_handle: str) -> list[tuple[str, str]]:
    """
    Return the people a citation is about: people citing it directly (on
    the person, a name, an attribute or an event reference), then the
    people of events citing it, then the parents of families citing it.
    """
    direct: list[str] = []
    via_event: list[str] = []
    via_family: list[str] = []
    try:
        backlinks = list(db.find_backlink_handles(citation_handle))
    except Exception:
        LOG.warning("Could not read what cites %s", citation_handle, exc_info=True)
        backlinks = []

    def add_family(handle: str, found: list[str]) -> None:
        family = db.get_family_from_handle(handle)
        if family is None:
            return
        for parent in (family.get_father_handle(), family.get_mother_handle()):
            if parent:
                found.append(parent)

    for obj_class, handle in backlinks:
        if obj_class == "Person":
            direct.append(handle)
        elif obj_class == "Event":
            for ev_class, ev_ref in db.find_backlink_handles(
                handle, include_classes=["Person", "Family"]
            ):
                if ev_class == "Person":
                    via_event.append(ev_ref)
                else:
                    add_family(ev_ref, via_family)
        elif obj_class == "Family":
            add_family(handle, via_family)
    people: list[tuple[str, str]] = []
    for handle in dict.fromkeys(direct + via_event + via_family):
        person = db.get_person_from_handle(handle)
        if person is not None:
            people.append((handle, _display_name(person)))
    return people


def _is_web_path(path: str) -> bool:
    """Whether a media path is a web address."""
    return path.lower().startswith(("http://", "https://", "www."))


def _media_issues(db: Any, citation: Citation, base: str) -> list[Issue]:
    """Return the image problems of a citation."""
    refs = citation.get_media_list()
    if not refs:
        return [make_issue(NO_MEDIA, PART_MEDIA)]
    missing = web = 0
    for ref in refs:
        media = db.get_media_from_handle(ref.ref)
        path = str(media.get_path() or "").strip() if media else ""
        if not path:
            missing += 1
        elif _is_web_path(path):
            web += 1
        else:
            full = path if os.path.isabs(path) else os.path.join(base, path)
            if not os.path.exists(full):
                missing += 1
    issues: list[Issue] = []
    if missing:
        issues.append(make_issue(MEDIA_MISSING, PART_MEDIA))
    if web and web == len(refs):
        issues.append(make_issue(MEDIA_WEB_ONLY, PART_MEDIA))
    return issues


def _source_issues(db: Any, source: Any) -> list[Issue]:
    """Return the problems of a citation's source."""
    if source is None:
        return [make_issue(NO_SOURCE, PART_SOURCE)]
    issues: list[Issue] = []
    title = str(source.get_title() or "").strip()
    if title.casefold() in PLACEHOLDER_TITLES:
        issues.append(make_issue(SOURCE_PLACEHOLDER, PART_SOURCE))
    elif kind_of_non_title(title):
        issues.append(make_issue(SOURCE_NOT_TITLE, PART_SOURCE))
    if is_tree_source_title(title):
        issues.append(make_issue(SOURCE_TREE, PART_SOURCE))
    if not source.get_reporef_list():
        issues.append(make_issue(SOURCE_NO_REPO, PART_SOURCE))
    if not (
        str(source.get_author() or "").strip()
        or str(source.get_publication_info() or "").strip()
    ):
        issues.append(make_issue(SOURCE_NO_AUTHOR, PART_SOURCE))
    return issues


def check_citation(
    db: Any, citation: Citation, source: Any = None, media_base: str = ""
) -> list[Issue]:
    """
    Return everything that could be better about a citation and its source
    (not counting what citation adapters add, or whether anything cites it).
    """
    issues = _source_issues(db, source)
    page = str(citation.get_page() or "").strip()
    if not page:
        issues.append(make_issue(NO_PAGE, PART_CITATION))
    else:
        if page_is_fragment(page):
            issues.append(make_issue(PAGE_FRAGMENT, PART_CITATION))
        if page_looks_like_source_text(page):
            issues.append(make_issue(PAGE_SOURCE_TEXT, PART_CITATION))
    if citation.get_date_object().is_empty():
        issues.append(make_issue(NO_DATE, PART_CITATION))
    issues.extend(_media_issues(db, citation, media_base))
    if not citation.get_note_list():
        issues.append(make_issue(NO_NOTE, PART_CITATION))
    if int(citation.get_confidence_level()) <= _CONF_LOW:
        issues.append(make_issue(LOW_CONFIDENCE, PART_CITATION))
    return issues


def _media_base(db: Any) -> str:
    """Return the media base folder of the Family Tree."""
    try:
        from gramps.gen.utils.file import media_path

        return str(media_path(db) or "")
    except Exception:
        return ""


def read_citation(
    db: Any,
    handle: str,
    adapters: Mapping[str, CitationSource] | None = None,
    media_base: str | None = None,
) -> CitationItem | None:
    """Read one citation into a CitationItem (main thread only)."""
    citation = db.get_citation_from_handle(handle)
    if citation is None:
        return None
    if media_base is None:
        media_base = _media_base(db)
    source_handle = str(citation.get_reference_handle() or "")
    source = db.get_source_from_handle(source_handle) if source_handle else None
    date = citation.get_date_object()
    year = date.get_year() if not date.is_empty() else 0
    item = CitationItem(
        handle=str(handle),
        gramps_id=str(citation.get_gramps_id() or ""),
        source_handle=source_handle,
        source_id=str(source.get_gramps_id() or "") if source else "",
        source_title=str(source.get_title() or "") if source else "",
        page=str(citation.get_page() or ""),
        date_text=_date_text(date),
        year=year if year and year > 0 else None,
        confidence=int(citation.get_confidence_level()),
        media_count=len(citation.get_media_list()),
        people=citation_people(db, handle),
        issues=check_citation(db, citation, source, media_base),
    )
    if not item.people and not _is_cited_elsewhere(db, handle):
        item.issues.append(make_issue(NOT_USED, PART_CITATION))
    for source_id, adapter in (adapters or {}).items():
        try:
            keys = [str(k) for k in adapter.record_keys(db, citation) or [] if k]
        except Exception:
            LOG.warning("%s: could not read record keys", source_id, exc_info=True)
            keys = []
        if keys:
            item.record_keys[source_id] = keys
        try:
            item.issues.extend(adapter.extra_issues(db, citation, keys) or [])
        except Exception:
            LOG.warning("%s: extra checks failed", source_id, exc_info=True)
    # An adapter's more specific "record has images" replaces "no image".
    if any(issue.code == RECORD_NO_MEDIA for issue in item.issues):
        item.issues = [issue for issue in item.issues if issue.code != NO_MEDIA]
    return item


def _is_cited_elsewhere(db: Any, handle: str) -> bool:
    """Whether anything at all (a place, a media object, ...) cites it."""
    try:
        return any(True for _ in db.find_backlink_handles(handle))
    except Exception:
        return True


def _date_text(date: Any) -> str:
    """Return a date as text ('' when empty)."""
    if date.is_empty():
        return ""
    try:
        from gramps.gen.datehandler import displayer as date_displayer

        return str(date_displayer.display(date))
    except Exception:
        return str(date.get_year() or "")


def build_citation_items(
    db: Any,
    handles: Iterable[str] | None = None,
    adapters: Mapping[str, CitationSource] | None = None,
    progress: Callable[[int], Any] | None = None,
) -> list[CitationItem]:
    """
    Read the citations (all when ``handles`` is None) and return them worst
    first. Must run on the main thread. ``progress(count)`` is called every
    100 citations.
    """
    base = _media_base(db)
    items: list[CitationItem] = []
    for count, handle in enumerate(
        db.iter_citation_handles() if handles is None else handles, 1
    ):
        item = read_citation(db, handle, adapters, base)
        if item is not None:
            items.append(item)
        if progress is not None and count % 100 == 0:
            progress(count)
    items.sort(key=CitationItem.sort_key)
    return items


# ------------------------------------------------------------
#
# CitationSource
#
# ------------------------------------------------------------
def text_relevance(item: CitationItem, text: str, years: Iterable[int] = ()) -> float:
    """
    Return how well a record (its title and other text, and its years) fits
    a citation, from -1 (clearly another record) to 1 (clearly this one):
    shared words with the source title and page, and whether the citation's
    year is among the record's years.
    """
    score = 0.0
    record_words = set(_WORD_RE.findall((text or "").casefold()))
    cite_words = {
        word
        for word in _WORD_RE.findall(f"{item.source_title} {item.page}".casefold())
        if len(word) > 3 and word not in _STOP_WORDS and not word.isdigit()
    }
    if cite_words:
        shared = len(cite_words & record_words) / len(cite_words)
        if shared >= 0.5:
            score += 0.5
        elif shared > 0:
            score += 0.25
    year_list = sorted(set(int(y) for y in years)) or sorted(
        int(y) for y in _YEAR_RE.findall(text or "")
    )
    if item.year and year_list:
        first, last = year_list[0], year_list[-1]
        if first - 2 <= item.year <= last + 2:
            score += 0.5
        elif item.year < first - 10 or item.year > last + 10:
            score -= 0.5
    return max(-1.0, min(1.0, score))


class CitationSource(abc.ABC):
    """
    What a record source knows about citations (see the module docstring).

    ``source_id`` must be the record source's id. ``record_keys`` and
    ``extra_issues`` run on the main thread and may read the database;
    ``relevance`` may run anywhere and must not.
    """

    source_id: str = ""

    def record_keys(self, db: Any, citation: Citation) -> list[str]:
        """Return the keys of this source's records the citation cites."""
        return []

    def extra_issues(self, db: Any, citation: Citation, keys: list[str]) -> list[Issue]:
        """Return this source's own checks of a citation."""
        return []

    def relevance(self, item: CitationItem, match: SourceMatch) -> float:
        """Return how well a record fits a citation, from -1 to 1."""
        return text_relevance(item, match.label)

    def open_record(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        key: str,
        parent: Any = None,
    ) -> bool:
        """
        Open a record the citation already cites (to add its images, say).
        Return True when the tree may have changed.
        """
        raise NotImplementedError


class GenericCitationSource(CitationSource):
    """The adapter used for a record source that registered none."""

    def __init__(self, source_id: str) -> None:
        """Adapt the record source with this id."""
        self.source_id = source_id


def discover_citation_sources(
    record_sources: Iterable[RecordSource], plugin_manager: Any = None
) -> dict[str, CitationSource]:
    """
    Return a citation adapter for each record source: the one an addon
    registers for it (see the module docstring), else a generic one.
    """
    found: dict[str, CitationSource] = {}
    try:
        if plugin_manager is None:
            from gramps.gen.plug import BasePluginManager

            plugin_manager = BasePluginManager.get_instance()
        registered = plugin_manager.get_reg_general(category=CITATION_SOURCE_CATEGORY)
    except Exception:
        LOG.warning("Could not list the citation sources", exc_info=True)
        registered = []
    for pdata in registered:
        items = getattr(pdata, "data", None) or []
        if not items:
            module = plugin_manager.load_plugin(pdata)
            loader = getattr(module, "load_on_reg", None) if module else None
            if loader is None:
                continue
            try:
                items = loader(None, None, pdata) or []
            except Exception:
                LOG.exception("Citation source plugin %s failed to load", pdata.id)
                continue
        if not isinstance(items, (list, tuple)):
            items = [items]
        for item in items:
            source_id = getattr(item, "source_id", "")
            if source_id and callable(getattr(item, "relevance", None)):
                found.setdefault(source_id, item)
    return {
        source.source_id: found.get(source.source_id)
        or GenericCitationSource(source.source_id)
        for source in record_sources
    }


# ------------------------------------------------------------
#
# Confidence
#
# ------------------------------------------------------------
@dataclass
class CitationMatch:
    """A record found for a citation's person, judged for the citation."""

    match: SourceMatch
    person_score: float
    relevance: float
    confidence: float
    cited: bool = False

    def label(self) -> str:
        """Return a menu label: the record and its confidence."""
        text = self.match.label or self.match.key
        if self.cited:
            return _("%s  (cited)") % text
        return _(
            "%(record)s  (%(conf).0f%%: person %(person).0f%%, fit %(fit)+.1f)"
        ) % {
            "record": text,
            "conf": self.confidence,
            "person": self.person_score,
            "fit": self.relevance,
        }


def confidence(person_score: float, relevance: float) -> float:
    """Return a record's confidence for a citation, from 0 to 100."""
    return max(0.0, min(100.0, person_score + RELEVANCE_POINTS * relevance))


def match_citation(
    item: CitationItem,
    scan: PersonScan | None,
    query: Any,
    adapter: CitationSource,
    person_cited: Iterable[str] = (),
    min_confidence: float = MIN_CONFIDENCE,
) -> list[CitationMatch]:
    """
    Judge the records a person scan found for one citation, best first.

    Records this citation cites come first, at 100. Records the person
    cites through other citations are dropped (they are in the tree
    already), and so are records below ``min_confidence``.
    """
    own = set(item.record_keys.get(adapter.source_id, []))
    elsewhere = {str(k) for k in person_cited} - own
    found: list[CitationMatch] = []
    for match in scan.matches if scan is not None else []:
        if match.key in elsewhere:
            continue
        if match.key in own:
            found.append(CitationMatch(match, 100.0, 1.0, CITED_CONFIDENCE, True))
            continue
        person = score_record(query, match.candidate).score if query else 0.0
        try:
            fit = float(adapter.relevance(item, match))
        except Exception:
            LOG.warning("%s: relevance failed", adapter.source_id, exc_info=True)
            fit = 0.0
        conf = confidence(person, fit)
        if conf >= min_confidence:
            found.append(CitationMatch(match, person, fit, conf))
    found.sort(key=lambda m: (m.cited, m.confidence), reverse=True)
    return found


# ------------------------------------------------------------
#
# Planning a scan
#
# ------------------------------------------------------------
def people_to_search(
    items: Iterable[CitationItem],
    min_work: int,
    max_new: int,
    is_cached: Callable[[str], bool],
) -> tuple[list[str], int]:
    """
    Return (the people to scan, how many people were left out by the
    limit), going down the citations worst first.

    Only citations with at least ``min_work`` and a person count. People
    with saved results are always included (they cost no request); at most
    ``max_new`` others are (0 means no limit).
    """
    chosen: list[str] = []
    seen: set[str] = set()
    new = skipped = 0
    for item in sorted(items, key=CitationItem.sort_key):
        handle = item.person_handle
        if item.work < min_work or not handle or handle in seen:
            continue
        seen.add(handle)
        if is_cached(handle):
            chosen.append(handle)
        elif not max_new or new < max_new:
            chosen.append(handle)
            new += 1
        else:
            skipped += 1
    return chosen, skipped


def work_band(work: int) -> str:
    """Return 'high', 'medium', 'low' or 'none' for a work score."""
    if work >= 60:
        return "high"
    if work >= 35:
        return "medium"
    if work >= 15:
        return "low"
    return "none"
