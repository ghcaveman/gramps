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
GWizard Multi-Archive Record Scan: check every person in the Family Tree against the
installed record sources (WikiTree, NARA, ...) and count how many likely
matches each source has, at three match levels.

Record sources
--------------
A record source is any object with the RecordSource interface. An addon
offers its sources to the scan by registering a GENERAL plugin in its
``.gpr.py`` with ``category="GWizardRecordSource"`` and ``load_on_reg=True``,
whose module has a ``load_on_reg(dbstate, uistate, plugin)`` function that
returns a list of sources. ``discover_sources()`` collects them, so the scan
needs no list of the sites it can search.

Threads
-------
Everything that reads the database (``build_scan_items``, the source's
``linked_key``) runs on the main thread. ``scan_item`` only calls the
source's ``search``/``lookup`` with what was read before, so a dialog can run
it in a worker thread while the window stays responsive.

This module has no GTK dependency; the window is in
gramps/gui/gwizard/gwizard_filemerge_recordscandialog.py.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import abc
import dataclasses
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import USER_DATA
from gramps.gen.lib import NameType, Person
from gramps.gen.gwizard.gwizard_base import (
    ALL_TIERS,
    RECORD_TIERS,
    RecordCandidate,
    RecordQuery,
    RecordScore,
    score_record,
    score_record_tier,
    surname_text,
)

LOG = logging.getLogger(__name__)

# The GENERAL plugin category record sources register under.
RECORD_SOURCE_CATEGORY = "GWizardRecordSource"

# Default threshold (percent) for counting a match.
DEFAULT_THRESHOLD = 70

# Scan outcomes for one person and source.
STATUS_OK = "ok"  # searched (or looked up), results stored
STATUS_LINKED = "linked"  # already linked; the linked record was looked up
STATUS_SKIPPED = "skipped"  # nothing to search with (no name)
STATUS_ERROR = "error"  # the search failed
STATUS_CITED = "cited"  # not searched: the person already cites the source

_CACHE_VERSION = 1


# ------------------------------------------------------------
#
# SourceMatch
#
# ------------------------------------------------------------
@dataclass
class SourceMatch:
    """
    One record a source found for a person.

    ``key`` identifies the record on its site (a WikiTree ID, a NARA NAID);
    ``data`` is whatever the source needs to open its merge window for it
    later, and must be JSON-serializable so it can be cached.
    """

    key: str
    label: str
    candidate: RecordCandidate
    url: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form of the match."""
        return {
            "key": self.key,
            "label": self.label,
            "url": self.url,
            "data": self.data,
            "candidate": dataclasses.asdict(self.candidate),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SourceMatch:
        """Return a match from its to_dict() form."""
        cand = dict(raw.get("candidate") or {})
        for key in ("birth_years", "death_years"):
            if cand.get(key) is not None:
                cand[key] = (int(cand[key][0]), int(cand[key][1]))
        known = {f.name for f in dataclasses.fields(RecordCandidate)}
        candidate = RecordCandidate(**{k: v for k, v in cand.items() if k in known})
        return cls(
            key=str(raw.get("key") or ""),
            label=str(raw.get("label") or ""),
            candidate=candidate,
            url=str(raw.get("url") or ""),
            data=dict(raw.get("data") or {}),
        )


# ------------------------------------------------------------
#
# RecordSource
#
# ------------------------------------------------------------
class RecordSource(abc.ABC):
    """
    A site the Multi-Archive Record Scan can search for the people in the Family Tree.

    Subclasses set ``source_id`` (short, stable, used in the cache) and
    ``title`` (the column heading), and implement ``search``. ``search`` and
    ``lookup`` run in a worker thread and must not touch the database.
    """

    source_id: str = ""
    title: str = ""
    # Seconds to wait between two requests to the site.
    min_interval: float = 1.0
    # Whether the source can tell that a person is already linked to one of
    # its records (shows the "Linked" column).
    has_links: bool = False
    # Skip the search for a person who already cites one of the source's
    # records (see cited_keys), to save requests on sites with an allowance.
    skip_cited: bool = False
    # The score columns the scan shows for this source, from ALL_TIERS
    # (gwizard_base). A source whose records rarely have middle names or
    # birth years can show just TIER_SCORE.
    tiers: tuple[str, ...] = RECORD_TIERS

    def available(self) -> tuple[bool, str]:
        """Return (whether the source can be used now, why not)."""
        return True, ""

    def linked_key(self, db: Any, person: Person) -> str:
        """
        Return the key of the record the person is already linked to, or
        ''. Runs on the main thread, so it may read the person.
        """
        return ""

    def cited_keys(self, db: Any, person: Person) -> list[str]:
        """
        Return the keys of the source's records the person already cites
        (NARA NAIDs on the person's citations, say). A person may cite many.
        The scan hides these records from its results, as they are already
        in the tree. Runs on the main thread, so it may read the database.
        """
        return []

    @abc.abstractmethod
    def search(self, query: RecordQuery) -> list[SourceMatch]:
        """Return the records on the site that may be this person."""

    def lookup(self, key: str) -> SourceMatch | None:
        """Return the linked record with this key, or None."""
        return None

    def usage_text(self) -> str:
        """
        Return a short note on how much of the site's request allowance
        has been used (such as "1,234 of 10,000 queries used in November"),
        or '' when the source has no allowance to report. Called on the
        main thread, also while a scan runs, so it must be quick.
        """
        return ""

    def open_merge(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        match: SourceMatch,
        parent: Any = None,
    ) -> bool:
        """
        Open the source's merge window for this record and person. Return
        True when the person may have changed (so the row is refreshed).
        """
        raise NotImplementedError

    def open_search(
        self, dbstate: Any, uistate: Any, person_handle: str, parent: Any = None
    ) -> bool:
        """
        Open the source's own search window for this person. Return True
        when the person may have changed.
        """
        raise NotImplementedError


def source_tiers(source: RecordSource) -> tuple[str, ...]:
    """Return the score columns to show for a source (see RecordSource.tiers)."""
    tiers = tuple(
        tier for tier in (getattr(source, "tiers", None) or ()) if tier in ALL_TIERS
    )
    return tiers or RECORD_TIERS


def discover_sources(plugin_manager: Any = None) -> list[RecordSource]:
    """
    Return the record sources installed addons register (see the module
    docstring), each once, in title order.

    A source registered by a plugin whose ``load_on_reg`` has not run yet
    (Gramps runs it only at start-up) is loaded here.
    """
    if plugin_manager is None:
        from gramps.gen.plug import BasePluginManager

        plugin_manager = BasePluginManager.get_instance()
    found: dict[str, RecordSource] = {}
    for pdata in plugin_manager.get_reg_general(category=RECORD_SOURCE_CATEGORY):
        items = getattr(pdata, "data", None) or []
        if not items:
            module = plugin_manager.load_plugin(pdata)
            loader = getattr(module, "load_on_reg", None) if module else None
            if loader is None:
                continue
            try:
                items = loader(None, None, pdata) or []
            except Exception:
                LOG.exception("Record source plugin %s failed to load", pdata.id)
                continue
        if not isinstance(items, (list, tuple)):
            items = [items]
        for item in items:
            source_id = getattr(item, "source_id", "")
            if source_id and callable(getattr(item, "search", None)):
                found.setdefault(source_id, item)
    return sorted(found.values(), key=lambda src: src.title.casefold())


# ------------------------------------------------------------
#
# Reading the Family Tree
#
# ------------------------------------------------------------
@dataclass
class ScanItem:
    """What the scan needs to know about one person, read up front."""

    handle: str
    gramps_id: str
    surname: str
    given: str
    birth_year: int | None
    death_year: int | None
    change: int
    query: RecordQuery
    links: dict[str, str] = field(default_factory=dict)
    # source id -> keys of that source's records the person already cites
    cited: dict[str, list[str]] = field(default_factory=dict)

    def sort_key(self) -> tuple[str, str, int]:
        """Surname, then given name, then birth year (unknown last)."""
        return (
            self.surname.casefold(),
            self.given.casefold(),
            self.birth_year or 9999,
        )

    def display_name(self) -> str:
        """Return "Surname, Given"."""
        if self.surname and self.given:
            return f"{self.surname}, {self.given}"
        return self.surname or self.given


def _event_year(db: Any, ref: Any) -> int | None:
    """Return the year of the event a reference points at, or None."""
    if not ref:
        return None
    try:
        event = db.get_event_from_handle(ref.ref)
    except Exception:
        return None
    if event is None:
        return None
    year = event.get_date_object().get_year()
    return year if year and year > 0 else None


def _vital_year(db: Any, person: Person, kind: str) -> int | None:
    """
    Return the birth (or death) year, falling back to a baptism or
    christening (burial or cremation) when there is none.
    """
    if kind == "birth":
        year = _event_year(db, person.get_birth_ref())
    else:
        year = _event_year(db, person.get_death_ref())
    if year:
        return year
    from gramps.gen.utils.db import get_birth_or_fallback, get_death_or_fallback

    getter = get_birth_or_fallback if kind == "birth" else get_death_or_fallback
    try:
        event = getter(db, person)
    except Exception:
        event = None
    if event is None:
        return None
    year = event.get_date_object().get_year()
    return year if year and year > 0 else None


def married_surnames(db: Any, person: Person) -> list[str]:
    """
    Return the person's married surnames: those of Married Name alternate
    names and, for a woman, the surname of each husband.
    """
    found: list[str] = []
    for alt_name in person.get_alternate_names():
        if int(alt_name.get_type()) == NameType.MARRIED:
            married = surname_text(alt_name).strip()
            if married and married not in found:
                found.append(married)
    if person.get_gender() != Person.FEMALE:
        return found
    for family_handle in person.get_family_handle_list():
        try:
            family = db.get_family_from_handle(family_handle)
        except Exception:
            continue
        husband_handle = family.get_father_handle() if family else None
        if not husband_handle or husband_handle == person.get_handle():
            continue
        husband = db.get_person_from_handle(husband_handle)
        if husband:
            married = surname_text(husband.get_primary_name()).strip()
            if married and married not in found:
                found.append(married)
    return found


def _person_places_and_tags(db: Any, person: Person) -> tuple[list[str], set[str]]:
    """Extract place strings and normalized event tags from a Gramps Person."""
    places: list[str] = []
    tags: set[str] = set()
    event_map = {
        "Immigration": "IMMI",
        "Naturalization": "NATU",
        "Census": "CENS",
        "Military Service": "MILITARY",
        "Residence": "RESI",
    }
    for ref in person.get_event_ref_list() or []:
        try:
            event = db.get_event_from_handle(ref.ref)
        except Exception:
            continue
        if event is None:
            continue
        etype = str(event.get_type() or "").strip()
        if etype in event_map:
            tags.add(event_map[etype])
        elif etype:
            tags.add(etype.upper())

        phandle = event.get_place_handle()
        if phandle:
            try:
                place = db.get_place_from_handle(phandle)
            except Exception:
                place = None
            if place is not None:
                from gramps.gen.display.place import displayer as place_displayer

                ptitle = (
                    place_displayer.display(db, place)
                    or place.get_title()
                    or place.get_name().get_value()
                )
                if ptitle and ptitle not in places:
                    places.append(str(ptitle))
    return places, tags


def _parent_given_names(db: Any, person: Person) -> tuple[str, str]:
    """Return the given names of the person's father and mother (main family)."""
    family_handle = person.get_main_parents_family_handle()
    family = db.get_family_from_handle(family_handle) if family_handle else None
    if family is None:
        return "", ""
    names = []
    for handle in (family.get_father_handle(), family.get_mother_handle()):
        parent = db.get_person_from_handle(handle) if handle else None
        given = parent.get_primary_name().get_first_name() if parent else ""
        names.append(str(given or "").strip())
    return names[0], names[1]


def query_for_person(db: Any, person: Person) -> RecordQuery:
    """
    Return the details a person is matched on: the first given name, the
    other given names as middle names, the birth surname followed by any
    married surnames, the birth and death years, the gender, the parents'
    given names (main family), and the places and event types (as tags)
    from the person's events.
    """
    name = person.get_primary_name()
    given_names = str(name.get_first_name() or "").split()
    surnames: list[str] = []
    birth_surname = surname_text(name).strip()
    if birth_surname:
        surnames.append(birth_surname)
    for married in married_surnames(db, person):
        if married not in surnames:
            surnames.append(married)
    gender = {Person.MALE: "male", Person.FEMALE: "female"}.get(person.get_gender(), "")
    places, tags = _person_places_and_tags(db, person)
    father, mother = _parent_given_names(db, person)
    return RecordQuery(
        given=given_names[0] if given_names else "",
        middle=" ".join(given_names[1:]),
        surnames=surnames,
        birth_year=_vital_year(db, person, "birth"),
        death_year=_vital_year(db, person, "death"),
        gender=gender,
        father_first_name=father,
        mother_first_name=mother,
        places=places,
        tags=tags,
    )


def build_scan_items(
    db: Any,
    handles: Iterable[str] | None = None,
    sources: Iterable[RecordSource] = (),
) -> list[ScanItem]:
    """
    Read the people to scan (all people when ``handles`` is None) and return
    them sorted by surname, given name and birth year. Must run on the main
    thread.
    """
    sources = list(sources)
    items: list[ScanItem] = []
    for handle in db.iter_person_handles() if handles is None else handles:
        person = db.get_person_from_handle(handle)
        if person is None:
            continue
        name = person.get_primary_name()
        query = query_for_person(db, person)
        links: dict[str, str] = {}
        cited: dict[str, list[str]] = {}
        for source in sources:
            if source.has_links:
                try:
                    key = source.linked_key(db, person)
                except Exception:
                    key = ""
                if key:
                    links[source.source_id] = key
            try:
                keys = list(source.cited_keys(db, person) or [])
            except Exception:
                LOG.warning("%s: could not read citations", source.title, exc_info=True)
                keys = []
            if keys:
                cited[source.source_id] = keys
        items.append(
            ScanItem(
                handle=str(handle),
                gramps_id=person.get_gramps_id(),
                surname=surname_text(name).strip(),
                given=str(name.get_first_name() or "").strip(),
                birth_year=query.birth_year,
                death_year=query.death_year,
                change=int(person.get_change_time() or 0),
                query=query,
                links=links,
                cited=cited,
            )
        )
    items.sort(key=ScanItem.sort_key)
    return items


# ------------------------------------------------------------
#
# Scanning
#
# ------------------------------------------------------------
@dataclass
class PersonScan:
    """The outcome of scanning one person on one source."""

    source_id: str
    handle: str
    status: str
    change: int = 0
    matches: list[SourceMatch] = field(default_factory=list)
    linked_key: str = ""
    error: str = ""
    scanned_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form for the cache."""
        return {
            "status": self.status,
            "change": self.change,
            "linked_key": self.linked_key,
            "error": self.error,
            "scanned_at": self.scanned_at,
            "matches": [match.to_dict() for match in self.matches],
        }

    @classmethod
    def from_dict(cls, source_id: str, handle: str, raw: dict[str, Any]) -> PersonScan:
        """Return a scan from its to_dict() form."""
        return cls(
            source_id=source_id,
            handle=handle,
            status=str(raw.get("status") or STATUS_OK),
            change=int(raw.get("change") or 0),
            matches=[SourceMatch.from_dict(m) for m in raw.get("matches") or []],
            linked_key=str(raw.get("linked_key") or ""),
            error=str(raw.get("error") or ""),
            scanned_at=float(raw.get("scanned_at") or 0.0),
        )


# ------------------------------------------------------------
#
# RateLimiter
#
# ------------------------------------------------------------
class RateLimiter:
    """Keep at least ``min_interval`` seconds between calls to ``wait``."""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Set up the limiter; clock and sleep can be replaced in tests."""
        self.min_interval = max(0.0, float(min_interval))
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self, cancel: threading.Event | None = None) -> None:
        """Sleep until the next call is allowed (in short steps, so a
        cancel is noticed)."""
        if self._last is not None:
            remaining = self._last + self.min_interval - self._clock()
            while remaining > 0:
                if cancel is not None and cancel.is_set():
                    return
                self._sleep(min(remaining, 0.1))
                remaining = self._last + self.min_interval - self._clock()
        self._last = self._clock()


def scan_item(source: RecordSource, item: ScanItem) -> PersonScan:
    """
    Search one source for one person. Safe to run in a worker thread: it
    only uses what build_scan_items read. Errors are returned, not raised.
    """
    now = time.time()
    linked = item.links.get(source.source_id, "")
    try:
        if linked:
            match = source.lookup(linked)
            matches = [match] if match is not None else []
            return PersonScan(
                source.source_id,
                item.handle,
                STATUS_LINKED,
                item.change,
                matches,
                linked_key=linked,
                scanned_at=now,
            )
        if getattr(source, "skip_cited", False) and item.cited.get(source.source_id):
            return PersonScan(
                source.source_id,
                item.handle,
                STATUS_CITED,
                item.change,
                scanned_at=now,
            )
        if not item.query.has_name():
            return PersonScan(
                source.source_id,
                item.handle,
                STATUS_SKIPPED,
                item.change,
                scanned_at=now,
            )
        matches = source.search(item.query)
    except Exception as err:
        LOG.warning("%s scan failed for %s: %s", source.title, item.display_name(), err)
        return PersonScan(
            source.source_id,
            item.handle,
            STATUS_ERROR,
            item.change,
            error=str(err),
            scanned_at=now,
        )
    return PersonScan(
        source.source_id,
        item.handle,
        STATUS_OK,
        item.change,
        list(matches),
        scanned_at=now,
    )


def split_cited(
    matches: Iterable[SourceMatch], cited: Iterable[str]
) -> tuple[list[SourceMatch], list[SourceMatch]]:
    """
    Return (new matches, matches the person already cites), keeping the
    order of ``matches``.
    """
    known = {str(key) for key in cited}
    new: list[SourceMatch] = []
    old: list[SourceMatch] = []
    for match in matches:
        (old if match.key in known else new).append(match)
    return new, old


# ------------------------------------------------------------
#
# Scores
#
# ------------------------------------------------------------
@dataclass
class ScoredMatch:
    """A match with its full score and its score at each tier."""

    match: SourceMatch
    full: RecordScore
    tiers: dict[str, RecordScore | None]


@dataclass
class TierCell:
    """
    What one tier column shows for a person: how many matches reach the
    threshold, the best score (None when no match could be judged at this
    tier) and whether any match could be judged.
    """

    count: int
    best: float | None

    @property
    def judged(self) -> bool:
        """Whether any match had the parts this tier needs."""
        return self.best is not None


def score_matches(
    query: RecordQuery,
    matches: Iterable[SourceMatch],
    tiers: Iterable[str] = RECORD_TIERS,
) -> list[ScoredMatch]:
    """
    Score each match in full and at each of ``tiers`` (the source's score
    columns), best full score first.
    """
    tiers = tuple(tiers)
    scored = [
        ScoredMatch(
            match,
            score_record(query, match.candidate),
            {tier: score_record_tier(query, match.candidate, tier) for tier in tiers},
        )
        for match in matches
    ]
    # Equal scores: a match whose years were compared is the better one.
    scored.sort(key=lambda s: (s.full.score, s.full.compared_years), reverse=True)
    return scored


def tier_cell(scored: Iterable[ScoredMatch], tier: str, threshold: float) -> TierCell:
    """Return the TierCell for one tier."""
    count = 0
    best: float | None = None
    for item in scored:
        result = item.tiers.get(tier)
        if result is None:
            continue
        best = result.score if best is None else max(best, result.score)
        if result.score >= threshold:
            count += 1
    return TierCell(count, best)


def matches_for_tier(
    scored: Iterable[ScoredMatch], tier: str | None, threshold: float
) -> list[ScoredMatch]:
    """
    Return the matches worth offering for a tier column (all matches when
    ``tier`` is None), best first: those reaching the threshold, or, when
    none does, every match.
    """
    scored = list(scored)

    def score_of(item: ScoredMatch) -> float:
        if tier is None:
            return item.full.score
        result = item.tiers.get(tier)
        return result.score if result is not None else -1.0

    passing = [s for s in scored if score_of(s) >= threshold]
    chosen = passing or scored
    return sorted(chosen, key=score_of, reverse=True)


# ------------------------------------------------------------
#
# ScanCache
#
# ------------------------------------------------------------
def default_cache_path(db: Any) -> str:
    """Return the cache file for a Family Tree, in the Gramps user folder."""
    try:
        dbid = str(db.get_dbid() or "")
    except Exception:
        dbid = ""
    safe = "".join(c for c in dbid if c.isalnum() or c in "-_") or "default"
    return os.path.join(USER_DATA, "gwizard", "recordscan", f"{safe}.json")


class ScanCache:
    """
    Scan results kept between sessions, one JSON file per Family Tree.

    An entry is used only while the person is unchanged since the scan (same
    change time), so editing a person makes it be scanned again.
    """

    def __init__(self, path: str | None) -> None:
        """Load the cache at ``path`` (None keeps it in memory only)."""
        self.path = path
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self.dirty = False
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    raw = json.load(handle)
                if raw.get("version") == _CACHE_VERSION:
                    self._data = dict(raw.get("sources") or {})
            except (OSError, ValueError, AttributeError) as err:
                LOG.warning("Ignoring unreadable record scan cache %s: %s", path, err)

    def get(self, source_id: str, item: ScanItem) -> PersonScan | None:
        """Return the stored scan of an unchanged person, else None."""
        raw = self._data.get(source_id, {}).get(item.handle)
        if not raw or int(raw.get("change") or 0) != item.change:
            return None
        # A person linked (or unlinked) since the scan is scanned again.
        if str(raw.get("linked_key") or "") != item.links.get(source_id, ""):
            return None
        try:
            return PersonScan.from_dict(source_id, item.handle, raw)
        except (TypeError, ValueError, KeyError):
            return None

    def put(self, scan: PersonScan) -> None:
        """Store a scan (errors are not stored, so they are retried)."""
        if scan.status == STATUS_ERROR:
            return
        self._data.setdefault(scan.source_id, {})[scan.handle] = scan.to_dict()
        self.dirty = True

    def forget(self, source_id: str, handle: str) -> None:
        """Drop the stored scan of one person."""
        if self._data.get(source_id, {}).pop(handle, None) is not None:
            self.dirty = True

    def clear(self, source_id: str | None = None) -> None:
        """Drop every stored scan (of one source, or of all)."""
        if source_id is None:
            self._data = {}
        else:
            self._data.pop(source_id, None)
        self.dirty = True

    def save(self) -> None:
        """Write the cache file, if anything changed."""
        if not self.path or not self.dirty:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"version": _CACHE_VERSION, "sources": self._data}, handle)
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError as err:
            LOG.warning("Could not save the record scan cache %s: %s", self.path, err)


# ------------------------------------------------------------
#
# RecordScanner
#
# ------------------------------------------------------------
class RecordScanner:
    """
    Run a scan of some people on some sources, using and filling the cache.

    ``run`` works through the people in order and calls ``on_result`` after
    each person and source. It can be called from a worker thread; the
    callbacks then run in that thread too.
    """

    def __init__(self, cache: ScanCache | None = None) -> None:
        """Set up a scanner; with no cache nothing is kept."""
        self.cache = cache if cache is not None else ScanCache(None)
        self._lock = threading.Lock()

    def cached(self, source: RecordSource, item: ScanItem) -> PersonScan | None:
        """Return the cached scan of a person, if still valid."""
        with self._lock:
            return self.cache.get(source.source_id, item)

    def run(
        self,
        sources: Iterable[RecordSource],
        items: Iterable[ScanItem],
        on_result: Callable[[ScanItem, PersonScan, bool], None],
        use_cache: bool = True,
        cancel: threading.Event | None = None,
        limiters: dict[str, RateLimiter] | None = None,
    ) -> int:
        """
        Scan each person on each source and return how many were scanned
        (cached results count). ``on_result(item, scan, from_cache)`` is
        called for each one; ``cancel`` stops the scan between people.
        """
        sources = list(sources)
        limiters = dict(limiters or {})
        for source in sources:
            limiters.setdefault(source.source_id, RateLimiter(source.min_interval))
        done = 0
        for item in items:
            if cancel is not None and cancel.is_set():
                break
            for source in sources:
                if cancel is not None and cancel.is_set():
                    break
                scan = self.cached(source, item) if use_cache else None
                from_cache = scan is not None
                if scan is None:
                    limiters[source.source_id].wait(cancel)
                    if cancel is not None and cancel.is_set():
                        break
                    scan = scan_item(source, item)
                    with self._lock:
                        self.cache.put(scan)
                on_result(item, scan, from_cache)
            done += 1
        return done
