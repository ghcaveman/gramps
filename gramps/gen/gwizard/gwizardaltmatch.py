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
Candidate matching for the alternate (Alt) GWizard compare window.

The alternate window lists, for the selected incoming person, every person
in the tree that is a similar match, closest first, instead of the whole
tree. This module holds the matching settings and the ranking, kept free of
GTK so it can be tested on its own.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Iterable

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.lib import Person
from gramps.gen.soundex import soundex
from gramps.gen.gwizard.gwizard_base import CandidateMatcher, PersonProfile

# The highest score CandidateMatcher.score_profiles can give: given name
# (1.0) + surname (1.0) + exact birth date (1.0). Scores are shown and
# compared as a percentage of this.
MAX_SCORE = 3.0

# Where candidates are looked for (MatchSettings.scope).
SCOPE_SURNAME = "surname"
SCOPE_SURNAME_INITIAL = "surname_initial"
SCOPE_ALL = "all"
SCOPES = (SCOPE_SURNAME, SCOPE_SURNAME_INITIAL, SCOPE_ALL)


# ------------------------------------------------------------
#
# MatchSettings
#
# ------------------------------------------------------------
@dataclass
class MatchSettings:
    """
    The tolerances the alternate compare window matches people with.

    :ivar min_percent: Lowest match, as a percentage of MAX_SCORE, for a
        tree person to be listed as a candidate.
    :ivar use_birth_window: Leave out candidates whose birth year is further
        than ``birth_window`` years from the incoming person's. People
        without a known birth year are never left out by this.
    :ivar birth_window: Allowed birth-year difference, in years.
    :ivar scope: Which tree people are considered at all: SCOPE_SURNAME
        (similar-sounding surname), SCOPE_SURNAME_INITIAL (similar-sounding
        surname and the same first initial, as the standard compare window
        does) or SCOPE_ALL (everyone; slow on large trees).
    :ivar max_shown: Most candidates listed per incoming person.
    :ivar one_to_one: Pair each tree person with at most one incoming
        person when choosing the automatic matches.
    """

    min_percent: int = 25
    use_birth_window: bool = True
    birth_window: int = 10
    scope: str = SCOPE_SURNAME
    max_shown: int = 25
    one_to_one: bool = True

    @property
    def min_score(self) -> float:
        """The lowest listed score, on CandidateMatcher's scale."""
        return max(0, min(100, int(self.min_percent))) / 100.0 * MAX_SCORE


def score_percent(score: float) -> int:
    """Return a score as a whole percentage of MAX_SCORE (0 to 100)."""
    return max(0, min(100, int(round(score / MAX_SCORE * 100))))


def match_key(person: Person) -> tuple[str, str]:
    """
    Return the (soundex of first surname, first initial) key of a person.

    The same key the standard compare window indexes the tree by.
    """
    name = person.get_primary_name()
    surname = ""
    if name.surname_list:
        surname = name.surname_list[0].surname or ""
    try:
        sdx = soundex(surname) if surname else ""
    except Exception:  # pylint: disable=broad-except
        sdx = ""
    initial = (name.first_name or " ").strip()[:1].lower()
    return (sdx, initial)


def _birth_year(profile: PersonProfile) -> int:
    """Return the profile's birth year, or 0 when it is not known."""
    if not profile.birth:
        return 0
    try:
        return int(profile.birth[0] or 0)
    except (TypeError, ValueError):
        return 0


def rank_candidates(
    source: PersonProfile,
    pool: Iterable[Any],
    profiles: dict[Any, PersonProfile],
    settings: MatchSettings,
    rejected: Iterable[Any] = (),
    score_fn: Callable[[PersonProfile, PersonProfile], float] | None = None,
) -> list[tuple[float, Any]]:
    """
    Rank the tree people in ``pool`` as matches for one incoming person.

    :param source: Profile of the incoming person.
    :param pool: Handles of the tree people to consider.
    :param profiles: Profile of each tree person, by handle.
    :param settings: The tolerances to apply.
    :param rejected: Handles the user said are not this person.
    :param score_fn: Scoring function (CandidateMatcher.score_profiles).
    :returns: ``(score, handle)`` pairs, best first, at most
        ``settings.max_shown`` of them.
    """
    if score_fn is None:
        score_fn = CandidateMatcher.score_profiles
    rejected = set(rejected)
    min_score = settings.min_score
    source_year = _birth_year(source)
    seen: set[Any] = set()
    ranked: list[tuple[float, Any]] = []
    for handle in pool:
        if handle in seen or handle in rejected:
            continue
        seen.add(handle)
        target = profiles.get(handle)
        if target is None:
            continue
        if settings.use_birth_window and source_year:
            target_year = _birth_year(target)
            if target_year and abs(source_year - target_year) > max(
                0, int(settings.birth_window)
            ):
                continue
        score = score_fn(source, target)
        # A negative score means the genders disagree: never a candidate.
        if score < 0 or score < min_score:
            continue
        # With a 0% minimum a zero score still lists; otherwise it must
        # show at least some agreement.
        if score == 0 and min_score > 0:
            continue
        ranked.append((score, handle))
    ranked.sort(key=lambda item: (-item[0], str(item[1])))
    return ranked[: max(1, int(settings.max_shown))]


def pair_greedy(
    ranked: dict[Any, list[tuple[float, Any]]],
    order: Iterable[Any],
    one_to_one: bool = True,
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    """
    Choose the automatic match of every incoming person.

    All candidate pairs are taken best score first. With ``one_to_one`` a
    tree person already claimed by a better-scoring incoming person is
    skipped, so the incoming person falls back to its next candidate
    rather than being left unmatched.

    :param ranked: Ranked candidates of each incoming person (see
        rank_candidates).
    :param order: Every incoming person's handle, in display order; ties
        go to the one earlier in this order.
    :param one_to_one: Pair each tree person at most once.
    :returns: ``(pair_map, pair_map_rev)``: incoming handle -> tree handle
        (None when unmatched), and tree handle -> incoming handle.
    """
    order = list(order)
    position = {handle: index for index, handle in enumerate(order)}
    pairs = [
        (score, source, target)
        for source, candidates in ranked.items()
        for score, target in candidates
    ]
    pairs.sort(key=lambda item: (-item[0], position.get(item[1], len(order))))
    pair_map: dict[Any, Any] = {}
    pair_map_rev: dict[Any, Any] = {}
    for _score, source, target in pairs:
        if source in pair_map:
            continue
        if one_to_one and target in pair_map_rev:
            continue
        pair_map[source] = target
        pair_map_rev.setdefault(target, source)
    for handle in order:
        pair_map.setdefault(handle, None)
    return pair_map, pair_map_rev


# ------------------------------------------------------------
#
# AltCandidateFinder
#
# ------------------------------------------------------------
class AltCandidateFinder:
    """
    Index the tree's people once and rank candidates for incoming people.
    """

    def __init__(self, matcher: CandidateMatcher, settings: MatchSettings) -> None:
        self.matcher = matcher
        self.settings = settings
        self.profiles: dict[Any, PersonProfile] = {}
        self.by_key: dict[tuple[str, str], list[Any]] = {}
        self.by_surname: dict[str, list[Any]] = {}

    def add_target(self, handle: Any, person: Person, db: Any) -> None:
        """Index one tree person."""
        key = match_key(person)
        self.by_key.setdefault(key, []).append(handle)
        self.by_surname.setdefault(key[0], []).append(handle)
        self.profiles[handle] = self.matcher.profile(person, db)

    def pool(self, key: tuple[str, str]) -> Iterable[Any]:
        """Return the tree people the current scope considers for ``key``."""
        scope = self.settings.scope
        if scope == SCOPE_ALL:
            return self.profiles.keys()
        if scope == SCOPE_SURNAME_INITIAL:
            return self.by_key.get(key) or self.by_key.get(("", key[1]), [])
        return self.by_surname.get(key[0], [])

    def rank(
        self,
        source: PersonProfile,
        key: tuple[str, str],
        rejected: Iterable[Any] = (),
    ) -> list[tuple[float, Any]]:
        """Rank the candidates of one incoming person (see rank_candidates)."""
        return rank_candidates(
            source,
            self.pool(key),
            self.profiles,
            self.settings,
            rejected,
            self.matcher.score_profiles,
        )
