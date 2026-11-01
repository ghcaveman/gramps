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
import re
from typing import Any
from urllib.parse import urlparse

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.plugins.tool.goldstandardrepos import GoldStandardRepositories

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
