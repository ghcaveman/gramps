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
import html
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
from gramps.gen.db import DbReadBase, DbWriteBase
from gramps.gen.lib import Date, Note, NoteType
from gramps.plugins.tool.gw_goldstandardrepos import GoldStandardRepositories

_ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext

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

# Text fragments that identify automated import debris inside notes. These
# are pure import logs, so they are safe to scrub automatically.
DEBRIS_INDICATORS = (
    "records not imported into repo",
    "tag recognized but not supported",
)

# Fragments that often mark an import artefact but can also hold real facts
# (a birth date, a remark about a death). These should be shown for review and
# never deleted automatically.
REVIEW_NOTE_INDICATORS = (
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


def is_review_note_text(text: str) -> bool:
    """Return True when a note may be an import artefact that holds real data."""
    lowered = (text or "").lower()
    return any(indicator in lowered for indicator in REVIEW_NOTE_INDICATORS)


def unpacked_abbreviation(
    current_abbrev: str, old_title: str, new_title: str, repo_name: str
) -> str | None:
    """Return a replacement abbreviation after a source title was unpacked.

    The abbreviation usually starts out as a copy of the conflated title
    (e.g. "Newspapers.com Obituary Index"), so it keeps the repository text
    that was just moved out. Return the new abbreviation, or None when the
    existing value should be left alone (a deliberate custom abbreviation).
    """
    abbrev = (current_abbrev or "").strip()
    old = (old_title or "").strip()
    new = (new_title or "").strip()
    repo = (repo_name or "").strip()
    if not new:
        return None
    if not abbrev:
        return None
    if abbrev.casefold() == old.casefold():
        return new if abbrev != new else None
    if repo and abbrev.casefold().startswith(repo.casefold()):
        rest = abbrev[len(repo) :].lstrip(" -:;,")
        if rest and rest != abbrev:
            return rest
    # "New title (https://site)": the abbreviation is the title plus a URL
    # or note in brackets, which belongs in the publication info instead.
    if abbrev.casefold().startswith(new.casefold()):
        tail = abbrev[len(new) :].strip()
        if tail.startswith(("(", "[")) and tail != "":
            return new
    return None


_TAG_RE = re.compile(r"<[^>]+>")
_QUOTE_CHARS = "\"'\u201c\u201d\u2018\u2019\u201e\u00ab\u00bb"
_BARE_DOMAIN_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?([\w-]+(?:\.[\w-]+)+)/?$", re.IGNORECASE
)
# Websites whose bare domain is used as a source title, mapped to the name
# that should be the repository and the title.
_KNOWN_SITES = {
    "familysearch.org": "FamilySearch",
    "legacy.com": "Legacy.com",
    "ancestry.com": "Ancestry.com",
    "newspapers.com": "Newspapers.com",
    "findagrave.com": "Find a Grave",
    "archives.gov": "National Archives and Records Administration (NARA)",
}


def clean_source_title(title: str) -> tuple[str, str, str, str]:
    """Clean markup, quotes and website addresses out of a source title.

    :returns: ``(new_title, moved_text, repo_name, reason)``. ``new_title``
        is empty when the title needs no change. ``moved_text`` is detail
        taken out of the title that should be kept in the publication info,
        ``repo_name`` is a known website to use as the repository (or empty)
        and ``reason`` is a short description of what was fixed.
    """
    original = title or ""
    text = html.unescape(_TAG_RE.sub("", original))
    text = " ".join(text.split())
    reasons: list[str] = []
    if text != " ".join(original.split()):
        reasons.append("html markup")
    moved = ""
    quoted = re.match('^[\u201c"]\\s*(.+?)[,.]?\\s*[\u201d"]\\s*,?\\s*(.*)$', text)
    if quoted:
        text = quoted.group(1).strip()
        moved = quoted.group(2).strip(" ,;")
        reasons.append("citation-style quotes")
    else:
        stripped = text.strip(_QUOTE_CHARS + " ,;")
        if stripped != text:
            reasons.append("stray quotes")
            text = stripped
    repo_name = ""
    domain = _BARE_DOMAIN_RE.match(text)
    if domain:
        site = _KNOWN_SITES.get(domain.group(1).casefold())
        if site:
            moved = "; ".join(part for part in (moved, text) if part)
            text = site
            repo_name = site
            reasons.append("website address used as title")
    if text == original.strip() and not moved:
        return "", "", "", ""
    if text == original.strip():
        text = ""
    return text, moved, repo_name, ", ".join(reasons)


_URL_REGEX = re.compile(r"https?://[^\s<>\"'()]+", re.IGNORECASE)
# Real month names only, so a time such as "10:42 UTC 2025" is never a date.
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DATE_FULL_REGEX = re.compile(
    r"\b(?:\d{1,2}\s+" + _MONTH + r"\s+\d{4}|" + _MONTH + r"\s+\d{1,2},?\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
# "Wed Aug 13 16:16:42 UTC 2025", the timestamp FamilySearch puts after a URL.
_TIMESTAMP_REGEX = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+(" + _MONTH + r")\s+(\d{1,2})\s+"
    r"\d{1,2}:\d{2}(?::\d{2})?\s+[A-Z]{2,5}\s+(\d{4})\b",
    re.IGNORECASE,
)
ACCESS_DATE_REGEX = re.compile(
    r"\b(?:accessed|access\s+date|viewed|retrieved|imported|downloaded)[\s:]+(.+?)(?:[;,\.]|$)",
    re.IGNORECASE,
)
# '..."Title", Site (https://url : date), Entry for Jane Doe, 1910.'
_NOTE_ENTRY_REGEX = re.compile(r"https?://[^)]*\)\s*,\s*(.+?)\s*\.?\s*$", re.DOTALL)


def extract_url(text: str) -> str:
    """Extract first URL from text."""
    if not text:
        return ""
    m = _URL_REGEX.search(text)
    return m.group(0).rstrip(".,;:") if m else ""


def extract_access_date(text: str, allow_timestamp: bool = False) -> str:
    """Extract an access date, and nothing else, from text.

    Only a date that follows "accessed", "retrieved" and similar words counts
    (and, for note text, a FamilySearch timestamp). A bare year, or any other
    date in the text, is evidence about the record, not when it was viewed,
    so it is never taken, and years inside a collection name such as
    "Public Records, 1970-2009" are left alone.
    """
    if not text:
        return ""
    m_acc = ACCESS_DATE_REGEX.search(text)
    if m_acc:
        full = _DATE_FULL_REGEX.search(m_acc.group(1))
        if full:
            return full.group(0).strip()
    if allow_timestamp:
        stamp = _TIMESTAMP_REGEX.search(text)
        if stamp:
            return "%s %s %s" % (
                stamp.group(2),
                stamp.group(1).rstrip(".").title(),
                stamp.group(3),
            )
    return ""


def extract_note_entry(notes_text: str) -> str:
    """Return the "Entry for ..." detail from a full citation kept in a note."""
    match = _NOTE_ENTRY_REGEX.search((notes_text or "").strip())
    return match.group(1).strip() if match else ""


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
        # Longest first, so "familysearch.org" wins over "FamilySearch".
        pieces.sort(key=len, reverse=True)
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


def _balance_brackets(text: str) -> str:
    """Drop any bracket that has no partner, so cutting text never leaves "(" behind."""
    pairs = {")": "(", "]": "["}
    stack: list[int] = []
    drop: set[int] = set()
    for index, char in enumerate(text):
        if char in "([":
            stack.append(index)
        elif char in pairs:
            if stack and text[stack[-1]] == pairs[char]:
                stack.pop()
            else:
                drop.add(index)
    drop.update(stack)
    return "".join(char for index, char in enumerate(text) if index not in drop)


_DANGLING_WORD_RE = re.compile(
    r"^(?:from|via|at|courtesy of|provided by)\s+|"
    r"\s+(?:from|via|at|courtesy of|provided by)$",
    re.IGNORECASE,
)


def _clean_fragment(text: str) -> str:
    text = _balance_brackets(text)
    text = re.sub(r"\(\s*\)|\[\s*\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" \t,.;:|-()[]")
    # A connecting word left behind by a cut repository name: "(from X)".
    text = _DANGLING_WORD_RE.sub("", text)
    return text.strip(" \t,.;:|-()[]")


# "(Repository: Newspapers.com, Source: Obituary Index)" style groups.
_LABELLED_GROUP_RE = re.compile(
    r"[(\[]\s*((?:repository|source|citation)\s*:[^()\[\]]*)[)\]]?",
    re.IGNORECASE,
)
_LABEL_RE = re.compile(r"\b(repository|source|citation)\s*:\s*", re.IGNORECASE)


def _take_labelled_groups(title: str) -> tuple[str, str, list[str]]:
    """Remove labelled groups such as ``(Repository: X, Source: Y)``.

    :returns: ``(rest, repository_text, moved)``. ``rest`` is the title
        with the groups cut out, ``repository_text`` the first value
        labelled Repository, and ``moved`` the Citation values and any
        Source value whose text is not already in the title.
    """
    repo_text = ""
    moved: list[str] = []
    source_values: list[str] = []
    for match in _LABELLED_GROUP_RE.finditer(title):
        parts = _LABEL_RE.split(match.group(1))
        for label, value in zip(parts[1::2], parts[2::2]):
            value = value.strip(" ,;")
            if not value:
                continue
            label = label.lower()
            if label == "repository":
                repo_text = repo_text or value
            elif label == "citation":
                moved.append(value)
            else:
                source_values.append(value)
    rest = _LABELLED_GROUP_RE.sub(" ; ", title)
    rest_key = normalize_text_key(rest)
    for value in source_values:
        if normalize_text_key(value) not in rest_key:
            moved.append(value)
    return rest, repo_text, moved


def _cut_repository_mentions(text: str) -> tuple[str, list[str], list[str]]:
    """Cut every repository mention (and URLs around it) out of text.

    :returns: ``(text, names, urls)``: the names of the repositories found,
        in the order they first appear, and the full web addresses cut out
        (kept so a record link is never lost).
    """
    names: list[str] = []
    urls: list[str] = []
    for _attempt in range(20):
        mention = find_repository_mention(text)
        if mention is None:
            break
        if mention[0] not in names:
            names.append(mention[0])
        start, end = _expand_url_token(text, mention[1], mention[2])
        if (start, end) != (mention[1], mention[2]):
            urls.append(text[start:end])
        text = text[:start] + " ; " + text[end:]
    return text, names, urls


def golden_repository_for(name: str) -> str:
    """Return the gold-standard repository that ``name`` plainly is, or "".

    A name counts only when it is the golden name, its web address, its
    abbreviation or its short host name, with nothing else left over
    except "The" and punctuation: "ancestry.com", "Ancestry" and
    "The National Archives and Records Administration (NARA)" match, while
    "Pennsylvania State Archives" or "Archives" do not. Use this before
    merging without asking; looser similarity is only a hint to review.
    """
    text = (name or "").strip()
    if not text:
        return ""
    key = normalize_text_key(text)
    for gold in GoldStandardRepositories.get_names():
        if normalize_text_key(gold) == key:
            return gold
    rest, names, _urls = _cut_repository_mentions(text)
    if len(names) != 1:
        return ""
    leftover = normalize_text_key(rest)
    leftover = re.sub(r"\bthe\b", " ", leftover).strip()
    gold = names[0]
    if leftover and "(" in gold:
        abbr = normalize_text_key(gold.rsplit("(", 1)[1].rstrip(")"))
        leftover = re.sub(r"\b%s\b" % re.escape(abbr), " ", leftover).strip()
    golden = set(GoldStandardRepositories.get_names())
    return gold if not leftover and gold in golden else ""


def split_conflated_title(title: str) -> dict[str, str] | None:
    """Split a source title that mixes repository/source/citation text.

    Returns ``{"repo_name", "new_title", "moved_text"}`` or None when the
    title cannot be separated safely. ``moved_text`` holds citation-style
    fragments (page, volume, memorial id...) removed from the title so no
    information is lost.

    Every mention of the repository is removed, along with labelled groups
    such as ``(Repository: X, Source: Y)``, so splitting the new title
    again finds nothing more to do.
    """
    rest, repo_text, moved = _take_labelled_groups(title or "")
    remainder, mentioned, urls = _cut_repository_mentions(rest)
    repo_name = ""
    if repo_text:
        labelled = find_repository_mention(repo_text)
        repo_name = labelled[0] if labelled else repo_text
    elif mentioned:
        repo_name = mentioned[0]
    if not repo_name:
        return None
    # A second repository named in the title is kept as text, not lost.
    moved.extend(name for name in mentioned if name != repo_name)
    moved.extend(urls)

    kept: list[str] = []
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
    if not new_title:
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


def is_ancestry_style_title(title: str) -> bool:
    """Return True for titles worded the way Ancestry names its databases."""
    return bool(
        re.search(r"\bU\.S\.", title or "")
        or _CENSUS_TITLE.search(title or "")
        or _ANCESTRY_ONLY.search(title or "")
    )


def build_family_titles(titles: list[str]) -> dict[str, list[str]]:
    """Group source titles that normalise to the same text.

    Titles that differ only by "U.S." (an older and a newer name for the same
    collection) land in one group, whatever repository they are linked to.
    """
    families: dict[str, list[str]] = defaultdict(list)
    for title in titles:
        key = normalize_source_title(title or "")
        if key:
            families[key].append(title)
    return dict(families)


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
    family_titles: dict[str, list[str]] | None = None,
) -> tuple[str, str] | None:
    """Suggest a golden repository for a source, with the reason.

    ``family_titles`` (from ``build_family_titles``) lets a title without
    "U.S." follow a same-collection title that is worded like Ancestry,
    even before either source has a repository.

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
    already_golden = False
    if current_repo:
        near = closest_golden_name(current_repo, golden)
        if near and normalize_repo_name(near) != current_key:
            return result(near, _("closest golden name to the current repository"))
        # Already on a golden repository: only a same-collection source may
        # suggest a change, never the title wording.
        already_golden = bool(near)

    # 1. Another source with the same title already has a repository.
    votes: Counter = Counter()
    for other_handle, repo_name in index.get(normalize_source_title(title), []):
        golden_name = lookup.get(normalize_repo_name(repo_name))
        if other_handle != source_handle and golden_name:
            votes[golden_name] += 1
    # A title worded like Ancestry's is the newer name of its collection, so
    # an existing choice for it is not overridden by an older-named sibling
    # (otherwise two sources would each suggest moving to the other).
    if votes and not (already_golden and is_ancestry_style_title(title)):
        name = votes.most_common(1)[0][0]
        return result(
            name, _("same title already linked to {repository}").format(repository=name)
        )
    if already_golden:
        return None

    # 2. Ancestry-only naming (checked before a site named inside the title,
    #    because "U.S., Find A Grave Index" is an Ancestry database).
    if "Ancestry.com" in golden and is_ancestry_style_title(title):
        return result("Ancestry.com", _("Ancestry-style database title"))

    # 3. A golden repository named in the title.
    mention = find_repository_mention(title or "")
    if mention and mention[0] in golden:
        return result(
            mention[0], _("title names {repository}").format(repository=mention[0])
        )

    uspto = "United States Patent and Trademark Office (USPTO)"
    if uspto in golden and re.search(
        r"patent\s+(?:and\s+trademark\s+)?office|\buspto\b", title or "", re.IGNORECASE
    ):
        return result(uspto, _("title names the patent office"))

    # 3b. A same-collection title worded like Ancestry's (for example the
    #     "U.S." version of this title) means this source is on Ancestry too.
    if "Ancestry.com" in golden and family_titles:
        siblings = family_titles.get(normalize_source_title(title or ""), [])
        if any(other != title and is_ancestry_style_title(other) for other in siblings):
            return result(
                "Ancestry.com", _("same collection as an Ancestry-style title")
            )

    # 4. State-style collection title without "U.S." is FamilySearch naming.
    if "FamilySearch" in golden and _YEAR_RANGE.search(title or ""):
        return result("FamilySearch", _("likely: FamilySearch-style collection title"))

    return None


_YEAR_TOKEN = re.compile(r"^(?:1[5-9]\d\d|20\d\d|\d{3,4}s|current|present)$")
_LOOSE_WORDS = {"records", "record", "database", "and", "the", "of", "in", "a"}


def same_collection_titles(title_a: str, title_b: str) -> bool:
    """Return True only when two source titles name the same collection.

    A fuzzy title match is not enough to merge sources: "California Birth
    Index" and "Maine, Marriage Index", or the 1900 and 1940 census, are very
    similar as text but are different collections. Titles count as the same
    collection when:

    * they have the same words once years, filler such as "records" and
      "U.S." are ignored (so "Volume 1" and "Volume 2", or an "Index" and a
      "Collection", stay different) (so "Pennsylvania, Marriages, 1852-1968" and
      "Pennsylvania, U.S., Marriages, 1852-1968" match, and "Philadelphia,
      Pennsylvania, Death Certificates" and "Pennsylvania, Death
      Certificates" do not), and
    * they do not start with different years (the census of 1900 and 1940).
    """
    key_a = normalize_source_title(title_a or "")
    key_b = normalize_source_title(title_b or "")
    if not key_a or not key_b:
        return False
    lead_a = re.match(r"^(1[5-9]\d\d|20\d\d)\b", key_a)
    lead_b = re.match(r"^(1[5-9]\d\d|20\d\d)\b", key_b)
    if lead_a and lead_b and lead_a.group(1) != lead_b.group(1):
        return False

    def words(key: str) -> set[str]:
        return {
            word
            for word in key.split()
            if word not in _LOOSE_WORDS and not _YEAR_TOKEN.match(word)
        }

    return words(key_a) == words(key_b)


def suggest_source_merge_target(
    selected_handle: str,
    candidate_handles: list[str],
    db: DbReadBase,
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
                    "Matching normalized title (%(target_cites)d citations vs "
                    "%(src_cites)d)"
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
            if not shared_repos and not same_collection_titles(title, target_title):
                # Similar wording is not enough: different collections stay apart.
                continue
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


# ------------------------------------------------------------
#
# Shared apply helpers (used by the dialogs and the no-review paths)
#
# ------------------------------------------------------------
_BARE_URL_NOTE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def is_bare_url_text(text: str) -> bool:
    """Return True when the text is nothing but one web address."""
    return bool(_BARE_URL_NOTE.match((text or "").strip()))


def parse_citation_date(text: str) -> Any:
    """Parse date text into a Gramps Date, or return None if unparseable."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        from gramps.gen.datehandler import parser as dateparser

        date_obj = dateparser.parse(text)
    except Exception:  # pylint: disable=broad-except
        return None
    if date_obj is None or date_obj.get_modifier() == Date.MOD_TEXTONLY:
        return None
    return date_obj


def add_note_once(
    db: DbWriteBase,
    trans: Any,
    obj: Any,
    text: str,
    note_type: Any = NoteType.CITATION,
    skip_if_contained: bool = False,
) -> bool:
    """Attach a note with this text to ``obj`` unless it already has one.

    With ``skip_if_contained`` a note on ``obj`` whose text merely contains
    the new text (a full citation string that includes the URL, say) also
    counts as already present.

    An identical note anywhere else in the database is reused (linked)
    rather than duplicated. The caller commits ``obj``. Returns True when
    the object gained a note reference.
    """
    text = (text or "").strip()
    if not text:
        return False
    for note_handle in obj.get_note_list():
        existing = db.get_note_from_handle(note_handle)
        if existing is None:
            continue
        have = note_text(existing).strip()
        if have == text or (skip_if_contained and text in have):
            return False
    for existing in db.iter_notes():
        if note_text(existing).strip() == text and existing.get_type() == note_type:
            obj.add_note(existing.get_handle())
            return True
    note = Note()
    note.set(text)
    note.set_type(note_type)
    obj.add_note(db.add_note(note, trans))
    return True


def delete_note_if_unused(db: DbWriteBase, trans: Any, note_handle: str) -> bool:
    """Delete a note when no object refers to it any more.

    Call this after committing the objects the note was detached from, so
    the database no longer lists them as users. Returns True if deleted.
    """
    if list(db.find_backlink_handles(note_handle)):
        return False
    db.remove_note(note_handle, trans)
    return True
