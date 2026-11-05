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

"""Shared pure-logic helpers for the GWizard citation fix tool (no GUI, no DB)."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import difflib
import re
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlparse

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.plugins.tool.goldstandardrepos import GoldStandardRepositories

_ = glocale.translation.sgettext

# ------------------------------------------------------------
#
# Field detectors (single copy, used by the report and the repair engine)
#
# ------------------------------------------------------------
FIELD_REPO_PATTERNS = re.compile(
    r"https?://|www\.|familysearch|ancestry|newspapers\.com|find\s?a\s?grave"
    r"|myheritage|legacy\.com",
    re.IGNORECASE,
)
FIELD_SOURCE_PATTERNS = re.compile(
    r"census|death\s+certificate|birth\s+record|marriage\s+index|vital\s+records"
    r"|church\s+records|obituary\s+index",
    re.IGNORECASE,
)
FIELD_CITATION_PATTERNS = re.compile(
    r"page\s+\d+|vol(ume)?\s+\d+|cert(ificate)?\s+\d+|accessed\s+\d+|entry\s+for"
    r"|household\s+\d+|line\s+\d+|memorial\s+id",
    re.IGNORECASE,
)

# Text fragments that identify automated import debris inside notes.
DEBRIS_INDICATORS = (
    "records not imported into repo",
    "tag recognized but not supported",
    "birth type:",
    "passed away exactly on his",
)


# ------------------------------------------------------------
#
# Normalizers
#
# ------------------------------------------------------------
def normalize_text_key(text: str) -> str:
    """Return a normalized comparison key for a repository name or source title."""
    key = (text or "").lower().strip()
    key = key.replace("&", "and")
    key = re.sub(r"\bu\.?\s*s\.?\b", " ", key)
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


normalize_repo_name = normalize_text_key
normalize_source_title = normalize_text_key


def note_text(note: Any) -> str:
    """Return the plain text of a Gramps note."""
    try:
        styled = note.get_styledtext()
        if styled is not None and hasattr(styled, "get_string"):
            return str(styled.get_string())
    except Exception:  # pylint: disable=broad-except
        pass
    return str(note.get() or "")


def is_debris_text(text: str) -> bool:
    """Return True when note text looks like automated import debris."""
    lowered = (text or "").lower()
    return any(indicator in lowered for indicator in DEBRIS_INDICATORS)


def is_tree_source_title(title: str) -> bool:
    """Return True for titles of user-contributed online family trees."""
    lowered = (title or "").lower()
    if "familysearch" in lowered and "family tree" in lowered:
        return True
    return "ancestry member tree" in lowered or "public member tree" in lowered


def detect_title_elements(title: str) -> list[str]:
    """Return which kinds of element (Repository/Source/Citation) a title mixes."""
    found = []
    if FIELD_REPO_PATTERNS.search(title or ""):
        found.append("Repository")
    if FIELD_SOURCE_PATTERNS.search(title or ""):
        found.append("Source")
    if FIELD_CITATION_PATTERNS.search(title or ""):
        found.append("Citation")
    return found


# ------------------------------------------------------------
#
# Repository mention finder
#
# ------------------------------------------------------------
_GENERIC_HOST_LABELS = {"archives", "archive", "books", "www"}
_DOMAIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\."
    r"(?:com|org|net|gov|edu|info|ie|uk|nl|au|ca|eu|fr|de|il|se))\b",
    re.IGNORECASE,
)
_matcher_cache: list[tuple[str, re.Pattern]] | None = None


def _flex(text: str) -> str:
    return re.escape(text).replace(r"\ ", r"\s+")


def _build_matchers() -> list[tuple[str, re.Pattern]]:
    """Build (golden name, regex) pairs used to spot repository mentions."""
    matchers: list[tuple[str, re.Pattern]] = []
    for entry in GoldStandardRepositories.get_all():
        name = entry["name"]
        base = name.split(" (", 1)[0]
        pieces = [_flex(base)]
        host = urlparse(entry.get("url", "")).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        if host:
            pieces.append(re.escape(host))
            label = host.split(".", 1)[0]
            if len(label) >= 8 and label not in _GENERIC_HOST_LABELS:
                pieces.append(re.escape(label))
        matchers.append(
            (name, re.compile(r"\b(?:%s)" % "|".join(pieces), re.IGNORECASE))
        )
        if "(" in name and name.endswith(")"):
            abbr = name.rsplit("(", 1)[1].rstrip(")")
            if len(abbr) >= 3:
                matchers.append((name, re.compile(r"\b%s\b" % re.escape(abbr))))
    return matchers


def find_repository_mention(text: str) -> tuple[str, int, int] | None:
    """Find the earliest repository mention in text.

    Returns ``(repository name, start, end)`` or None. The name is the
    gold-standard name when one matches, otherwise the bare domain name.
    """
    global _matcher_cache  # pylint: disable=global-statement
    if _matcher_cache is None:
        _matcher_cache = _build_matchers()
    best: tuple[str, int, int] | None = None
    for name, pattern in _matcher_cache:
        match = pattern.search(text)
        if match and (
            best is None
            or match.start() < best[1]
            or (match.start() == best[1] and match.end() > best[2])
        ):
            best = (name, match.start(), match.end())
    if best is not None:
        return best
    match = _DOMAIN_RE.search(text)
    if match:
        return (match.group(1).lower(), match.start(), match.end())
    return None


_TOKEN_DELIMS = " \t;|()[]"


def _expand_url_token(text: str, start: int, end: int) -> tuple[int, int]:
    """Grow a match to the whole URL token when it sits inside one."""
    tstart = start
    while tstart > 0 and text[tstart - 1] not in _TOKEN_DELIMS:
        tstart -= 1
    tend = end
    while tend < len(text) and text[tend] not in _TOKEN_DELIMS:
        tend += 1
    token = text[tstart:tend]
    if re.match(r"(?:https?://|www\.)", token, re.IGNORECASE) or "/" in token:
        return (tstart, tend)
    return (start, end)


def _clean_fragment(text: str) -> str:
    text = re.sub(r"\(\s*\)|\[\s*\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t,.;:|-()")


def split_conflated_title(title: str) -> dict[str, str] | None:
    """Split a source title that mixes repository/source/citation text.

    Returns ``{"repo_name", "new_title", "moved_text"}`` or None when the
    title cannot be separated safely. ``moved_text`` holds citation-style
    fragments (page, volume, memorial id...) removed from the title so no
    information is lost.
    """
    title = title or ""
    mention = find_repository_mention(title)
    if mention is None:
        return None
    repo_name, start, end = mention
    start, end = _expand_url_token(title, start, end)
    remainder = title[:start] + " ; " + title[end:]

    kept: list[str] = []
    moved: list[str] = []
    for fragment in re.split(r"\s*[;|]\s*", remainder):
        fragment = _clean_fragment(fragment)
        if not fragment:
            continue
        if FIELD_CITATION_PATTERNS.search(
            fragment
        ) and not FIELD_SOURCE_PATTERNS.search(fragment):
            moved.append(fragment)
        else:
            kept.append(fragment)
    new_title = "; ".join(kept).strip()
    if not new_title or not repo_name:
        return None
    return {
        "repo_name": repo_name,
        "new_title": new_title,
        "moved_text": "; ".join(moved),
    }


# ------------------------------------------------------------
#
# Repository hints (suggest a golden repository for a source)
#
# ------------------------------------------------------------
_YEAR_RANGE = re.compile(
    r"\b\d{4}\s*[-\u2013]\s*(?:\d{4}|current|present)\b", re.IGNORECASE
)
_ANCESTRY_ONLY = re.compile(
    r"^(?:global|web)\s*[,:]|\s&\s|church and town records|^philadelphia, pennsylvania",
    re.IGNORECASE,
)
_CENSUS_TITLE = re.compile(r"\b\d{4} united states federal census\b", re.IGNORECASE)


def build_title_repo_index(
    rows: list[dict[str, str]],
) -> dict[str, list[tuple[str, str]]]:
    """Index which repositories sources of a given title are already linked to.

    ``rows`` are dicts with ``title``, ``source_handle`` and ``repo_name``
    (a source with no repository has an empty or placeholder name and is
    skipped by passing only linked rows).
    """
    index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in rows:
        key = normalize_source_title(row.get("title", ""))
        if key and row.get("repo_name"):
            index[key].append((row.get("source_handle", ""), row["repo_name"]))
    return dict(index)


def closest_golden_name(
    name: str, golden: list[str], threshold: float = 0.8
) -> str | None:
    """Return the golden name most similar to ``name`` when similar enough."""
    plain = normalize_repo_name(name)
    if not plain:
        return None
    best, best_score = None, 0.0
    for candidate in golden:
        key = normalize_repo_name(candidate)
        score = difflib.SequenceMatcher(None, plain, key).ratio()
        # A golden name inside a longer name (or the reverse) is a strong match,
        # e.g. "Local Government and Municipal Registries (Genoa, IT ...)".
        if len(key) >= 8 and (f" {key} " in f" {plain} " or f" {plain} " in f" {key} "):
            score = max(score, 0.95)
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score >= threshold else None


def suggest_repository(
    title: str,
    source_handle: str,
    current_repo: str,
    index: dict[str, list[tuple[str, str]]],
    golden: list[str],
) -> tuple[str, str] | None:
    """Suggest a golden repository for a source, with the reason.

    A repository the source already has outranks everything else when its
    name is close to a golden name (it is simply misnamed). After that the
    evidence is tried from strongest to weakest: another source with the
    same title that is already linked to a repository, Ancestry-only title
    wording, a repository named in the title, and FamilySearch-style
    collection titles. Returns ``(golden name, reason)`` or None when there
    is no evidence; a suggestion equal to the current repository is not
    returned.
    """
    lookup = {normalize_repo_name(name): name for name in golden}
    current_key = normalize_repo_name(current_repo or "")

    def result(name: str | None, reason: str) -> tuple[str, str] | None:
        if not name or normalize_repo_name(name) == current_key:
            return None
        return (name, reason)

    # 0. The source already has a repository whose name is close to a golden
    #    name: it is simply misnamed, and that outranks anything in the title.
    if current_repo:
        near = closest_golden_name(current_repo, golden)
        if near:
            return result(near, _("closest golden name to the current repository"))

    # 1. Another source with the same title already has a repository.
    votes: Counter = Counter()
    for other_handle, repo_name in index.get(normalize_source_title(title), []):
        golden_name = lookup.get(normalize_repo_name(repo_name))
        if other_handle != source_handle and golden_name:
            votes[golden_name] += 1
    if votes:
        name = votes.most_common(1)[0][0]
        return result(name, _("same title already linked to %s") % name)

    # 2. Ancestry-only naming (checked before a site named inside the title,
    #    because "U.S., Find A Grave Index" is an Ancestry database).
    if "Ancestry.com" in golden and (
        re.search(r"\bU\.S\.", title or "")
        or _CENSUS_TITLE.search(title or "")
        or _ANCESTRY_ONLY.search(title or "")
    ):
        return result("Ancestry.com", _("Ancestry-style database title"))

    # 3. A golden repository named in the title.
    mention = find_repository_mention(title or "")
    if mention and mention[0] in golden:
        return result(mention[0], _("title names %s") % mention[0])

    uspto = "United States Patent and Trademark Office (USPTO)"
    if uspto in golden and re.search(
        r"patent\s+(?:and\s+trademark\s+)?office|\buspto\b", title or "", re.IGNORECASE
    ):
        return result(uspto, _("title names the patent office"))

    # 4. State-style collection title without "U.S." is FamilySearch naming.
    if "FamilySearch" in golden and _YEAR_RANGE.search(title or ""):
        return result("FamilySearch", _("likely: FamilySearch-style collection title"))

    return None


def suggest_source_merge_target(
    selected_handle: str,
    candidate_handles: list[str],
    db: Any,
    cites_by_source: dict[str, int] | Counter[str] | None = None,
) -> tuple[str, str] | None:
    """Suggest a merge target source with a reason, using fuzzy & heuristic matching."""
    if not selected_handle or not candidate_handles or not db:
        return None

    try:
        source = db.get_source_from_handle(selected_handle)
    except Exception:
        return None
    if source is None:
        return None

    title = str(source.get_title() or "")
    norm_title = normalize_source_title(title)
    src_cites = cites_by_source.get(selected_handle, 0) if cites_by_source else 0
    src_repos = set()
    try:
        for ref in source.get_reporef_list() or []:
            if hasattr(ref, "ref") and ref.ref:
                src_repos.add(ref.ref)
    except Exception:
        pass
    src_author = str(source.get_author() or "").strip().lower()

    best_handle: str | None = None
    best_score = 0
    best_reason = ""

    for target_handle in candidate_handles:
        if target_handle == selected_handle:
            continue
        try:
            target = db.get_source_from_handle(target_handle)
        except Exception:
            continue
        if target is None:
            continue

        target_title = str(target.get_title() or "")
        target_norm = normalize_source_title(target_title)
        target_cites = cites_by_source.get(target_handle, 0) if cites_by_source else 0
        target_repos = set()
        try:
            for ref in target.get_reporef_list() or []:
                if hasattr(ref, "ref") and ref.ref:
                    target_repos.add(ref.ref)
        except Exception:
            pass

        score = 0
        reason = ""

        # 1. Exact or normalized title match
        if title and target_title and title.lower() == target_title.lower():
            score = 2000 + target_cites * 10 + len(target_repos)
            reason = str(
                _("Exact title match (%(target_cites)d citations vs %(src_cites)d)")
                % {"target_cites": target_cites, "src_cites": src_cites}
            )
        elif norm_title and target_norm and norm_title == target_norm:
            score = 1500 + target_cites * 10 + len(target_repos)
            reason = str(
                _(
                    "Matching normalized title (%(target_cites)d citations vs %(src_cites)d)"
                )
                % {"target_cites": target_cites, "src_cites": src_cites}
            )
        else:
            ratio = (
                difflib.SequenceMatcher(None, norm_title, target_norm).ratio()
                if norm_title and target_norm
                else 0.0
            )
            shared_repos = src_repos & target_repos
            if shared_repos and ratio >= 0.70:
                score = 1000 + int(ratio * 100) + target_cites * 5
                repo_name = ""
                for r_h in shared_repos:
                    try:
                        repo_obj = db.get_repository_from_handle(r_h)
                        if repo_obj and repo_obj.get_name():
                            repo_name = repo_obj.get_name()
                            break
                    except Exception:
                        pass
                if repo_name:
                    reason = str(
                        _("Shared repository '%(repo)s' (%(pct)d%% title match)")
                        % {"repo": repo_name, "pct": int(ratio * 100)}
                    )
                else:
                    reason = str(
                        _("Shared repository (%(pct)d%% title match)")
                        % {"pct": int(ratio * 100)}
                    )
            elif ratio >= 0.80:
                score = 500 + int(ratio * 100) + target_cites * 5
                reason = str(
                    _("%(pct)d%% title similarity (%(target_cites)d citations)")
                    % {"pct": int(ratio * 100), "target_cites": target_cites}
                )
            elif src_author and ratio >= 0.60:
                target_author = str(target.get_author() or "").strip().lower()
                if target_author and target_author == src_author:
                    score = 400 + int(ratio * 100) + target_cites * 5
                    reason = str(
                        _("Same author '%(author)s' and similar title")
                        % {"author": source.get_author()}
                    )

        if score > best_score:
            best_score = score
            best_handle = target_handle
            best_reason = reason

    if best_handle is not None and best_reason:
        return (best_handle, best_reason)
    return None
