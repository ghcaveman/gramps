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
WikiTree implementation of the GWizard import and merge framework.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import copy
import hashlib
import logging
import mimetypes
import os
import re
from typing import Any, Callable
from urllib.parse import urlparse

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.config import config
from gramps.gen.datehandler import parser as dateparser
from gramps.gen.lib import (
    Person,
    Name,
    Surname,
    Event,
    EventRef,
    EventType,
    Citation,
    Source,
    Repository,
    RepositoryType,
    RepoRef,
    Media,
    MediaRef,
    Note,
    NoteType,
    Place,
    PlaceName,
    PlaceRef,
    PlaceType,
    Attribute,
    AttributeType,
    Family,
    ChildRef,
    ChildRefType,
    Url,
    UrlType,
    Date,
    NameType,
)
from gramps.gen.lib.date import Today
from gramps.gen.utils.db import get_birth_or_fallback, get_death_or_fallback
from gramps.gen.utils.file import create_checksum, media_path, relative_path
from gramps.gen.const import GRAMPS_LOCALE as glocale

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .gwizardgedcom import GedGWizard

LOG = logging.getLogger(__name__)
_ = glocale.translation.gettext


# ------------------------------------------------------------
#
# WikiTree ID utilities
#
# ------------------------------------------------------------
# Kept here rather than in gwizard_base so the shared file-merge modules
# stay identical to the gwizard_filemerge branch.
_WT_ID_REGEX = re.compile(r"^[A-Za-z]+(?:[_-][A-Za-z]+)*-\d+$")

# ------------------------------------------------------------
#
# Biography source parsing
#
# ------------------------------------------------------------
# Name of the WikiTree repository and collection-level source. One source
# serves every WikiTree profile; the profile ID goes in the citation page.
WIKITREE_REPOSITORY_NAME = "WikiTree (Free Family Tree)"
WIKITREE_SOURCE_TITLE = "WikiTree"

# Repositories recognised from a source's web address: (domain part,
# repository name, other names the same repository goes by in a tree).
# A biography source with no recognised address is filed under WikiTree,
# where it was found.
_KNOWN_REPOSITORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("familysearch.org", "FamilySearch", ()),
    ("ancestry.", "Ancestry.com", ("Ancestry",)),
    ("newspapers.com", "Newspapers.com", ()),
    ("findagrave.com", "Find a Grave", ()),
    ("books.google.", "Google Books", ()),
    ("archive.org", "Internet Archive", ()),
    (
        "dar.org",
        "Daughters of the American Revolution (DAR)",
        ("Daughters of the American Revolution", "DAR"),
    ),
    (
        "archives.gov",
        "National Archives and Records Administration (NARA)",
        ("National Archives", "NARA"),
    ),
    ("wikitree.com", WIKITREE_REPOSITORY_NAME, ("WikiTree",)),
)

_URL_RE = re.compile(r"https?://[^\s()<>\"'\[\]{}|]+")
# Punctuation that ends a sentence or closes wiki markup, not the address.
_URL_TRAILING = ".,;:!?)]}'\""
# "p. 187", "pp. 54-55", "Pg. 42", "Pgs. xxi & 88-90", "page 12", "image 3"
_PAGE_RE = re.compile(
    r"\b(?:pp?|pgs?|pages?|image)\.?\s*"
    r"((?:\d+|[ivxlcdm]+)(?:\s*(?:[-–,&]|and)\s*(?:\d+|[ivxlcdm]+))*)\b",
    re.IGNORECASE,
)
_ACCESSED_RE = re.compile(
    r"\baccessed\s+(\d{1,2}\s+[A-Za-z]+\.?\s+\d{4}|[A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)
_QUOTED_TITLE_RE = re.compile(r"^\s*[\"“]([^\"”]{3,}?)[\s,.;:]*[\"”]")
_FS_TREE_RE = re.compile(
    r"familysearch\.org/tree/person/(?:details/)?([A-Z0-9]{4}-[A-Z0-9]{3,4})",
    re.IGNORECASE,
)
_DAR_RE = re.compile(r"\bDAR\s+Ancestor\s*#?\s*:?\s*([A-Z]?\d+)", re.IGNORECASE)
_NAME_CONNECTORS = {"and", "&", "with", "de", "van", "von", "der", "la", "le", "du"}
_TITLE_STARTERS = {"the", "a", "an"}
# Longest source title kept whole; longer ones are cut at a word.
_MAX_TITLE_LEN = 200


def repository_norm(name: str) -> str:
    """Return a repository name reduced to lower-case letters and digits."""
    return re.sub(r"[^a-z0-9]", "", (name or "").casefold())


def extract_url(text: str) -> str:
    """Return the first web address in text, without trailing punctuation."""
    match = _URL_RE.search(text or "")
    if not match:
        return ""
    return match.group(0).rstrip(_URL_TRAILING)


def extract_page(text: str) -> str:
    """Return the page/image part of a citation text ("p. 187"), or ''."""
    match = _PAGE_RE.search(_URL_RE.sub(" ", text or ""))
    return match.group(0).strip() if match else ""


def extract_accessed_date(text: str) -> str:
    """Return the "accessed ..." date text of a citation, or ''."""
    match = _ACCESSED_RE.search(text or "")
    return match.group(1) if match else ""


def repository_for_url(url: str) -> tuple[str, tuple[str, ...]]:
    """Return (repository name, other names) for a source web address."""
    host = (url or "").casefold()
    for domain, name, aliases in _KNOWN_REPOSITORIES:
        if domain in host:
            return name, aliases
    return WIKITREE_REPOSITORY_NAME, ("WikiTree",)


def _is_initial(token: str) -> bool:
    return bool(re.fullmatch(r"(?:[A-Z]\.)+", token))


def _is_name_token(token: str) -> bool:
    if token.casefold() in _NAME_CONNECTORS:
        return True
    core = token.rstrip(".,")
    return bool(core) and core[0].isupper() and not any(c.isdigit() for c in core)


def split_author(text: str) -> tuple[str, str]:
    """
    Split a leading author list ("Warner, Ralph F. Warner, R. David.") from
    a bibliographic citation. Returns (author, rest); author is '' when the
    text does not start with a "Surname, Given" author.
    """
    tokens = (text or "").split()
    if len(tokens) < 3 or not tokens[0].endswith(","):
        return "", text
    for index, token in enumerate(tokens[:12]):
        if not _is_name_token(token):
            return "", text
        if not token.endswith("."):
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if _is_initial(token):
            # "Ralph F. Warner," and "R. David." go on with the author list;
            # "Scott S. The ..." starts the title.
            if (
                following.endswith((",", "."))
                or following.casefold() in _NAME_CONNECTORS
                or _is_initial(following)
            ) and following.casefold() not in _TITLE_STARTERS:
                continue
        author = " ".join(tokens[: index + 1])
        if not _is_initial(tokens[index]):
            author = author.rstrip(".")
        rest = " ".join(tokens[index + 1 :])
        return (author, rest) if rest else ("", text)
    return "", text


def first_sentence(text: str) -> str:
    """Return text up to the first full stop that ends a word (not an initial)."""
    match = re.search(r"(?<![\s.][A-Z])(?<!^[A-Z])[.?!](?=\s|$)", text or "")
    sentence = text[: match.start()] if match else text
    return sentence.strip().rstrip(".,;:")


def shorten_title(title: str) -> str:
    """Cut a very long title at a word boundary."""
    title = " ".join((title or "").split()).rstrip(".,;:")
    if len(title) <= _MAX_TITLE_LEN:
        return title
    cut = title[: _MAX_TITLE_LEN - 3]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;:-") + "..."


def describe_bio_source(cleaned: str, raw: str = "") -> dict[str, str]:
    """
    Work out the Source and Citation fields of one biography source.

    :returns: dict with title, author, url, page, accessed (date text),
        fs_id (a FamilySearch tree person ID), and repository (name) plus
        repository_aliases (a tuple, as text joined by '|').
    """
    cleaned = (cleaned or "").strip()
    url = extract_url(raw or cleaned) or extract_url(cleaned)
    info = {
        "title": "",
        "author": "",
        "url": url,
        "page": extract_page(cleaned),
        "accessed": extract_accessed_date(cleaned),
        "fs_id": "",
    }
    fs_match = _FS_TREE_RE.search(raw or cleaned) or _FS_TREE_RE.search(cleaned)
    dar_match = _DAR_RE.search(cleaned)
    without_url = _URL_RE.sub("", cleaned).strip(" ;,.")
    quoted = _QUOTED_TITLE_RE.match(cleaned)
    if fs_match and not without_url:
        info["title"] = "FamilySearch Family Tree"
        info["fs_id"] = fs_match.group(1).upper()
    elif dar_match:
        info["title"] = "DAR Genealogical Research System, Ancestor Database"
        info["page"] = "Ancestor #%s" % dar_match.group(1).upper()
    elif quoted:
        info["title"] = quoted.group(1).strip()
    elif without_url:
        # The page clause ("..., page 12") is citation detail, not title.
        page_match = _PAGE_RE.search(without_url)
        if page_match and page_match.start() > 0:
            without_url = without_url[: page_match.start()].rstrip(" ,;:(")
        author, rest = split_author(without_url)
        info["author"] = author
        info["title"] = first_sentence(rest) or first_sentence(without_url)
    else:
        info["title"] = url
    info["title"] = shorten_title(info["title"]) or _("WikiTree Cited Source")
    name, aliases = repository_for_url(info["url"])
    if dar_match:
        name, aliases = repository_for_url("dar.org")
    info["repository"] = name
    info["repository_aliases"] = "|".join(aliases)
    return info


def is_wikitree_id(value: str | None) -> bool:
    """
    Check if a string matches the standard WikiTree ID pattern.

    :param value: String to test (e.g. 'Franklin-1').
    :returns: True if value matches '<Surname>-<Number>'.
    :rtype: bool
    """
    if not value:
        return False
    return bool(_WT_ID_REGEX.match(str(value).strip()))


def extract_wikitree_id(text: str | None) -> str:
    """
    Extract a WikiTree ID from text, URL, or identifier string.

    :param text: Text, URL, or identifier string.
    :returns: Extracted WikiTree ID or empty string if not found.
    :rtype: str
    """
    if not text:
        return ""
    clean = str(text).strip()
    if is_wikitree_id(clean):
        return clean

    # Match URL pattern (e.g. https://www.wikitree.com/wiki/Franklin-1)
    m = re.search(
        r"wikitree\.com/(?:wiki/|index\.php\?title=)([^/#?&\s]+)",
        clean,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip()
        if is_wikitree_id(candidate):
            return candidate

    # Match prefix pattern (e.g. WikiTree: Franklin-1 or WikiTree ID: Franklin-1)
    m = re.search(
        r"wikitree(?:\s*id)?[:\s]+([A-Za-z]+(?:[_-][A-Za-z]+)*-\d+)",
        clean,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip()
        if is_wikitree_id(candidate):
            return candidate

    return ""


def get_wikitree_id(gr_obj: Any) -> str:
    """
    Return the WikiTree ID of a Gramps object (e.g. Person), or empty string.
    Checks custom attributes and Internet URLs.

    :param gr_obj: Gramps object (Person, etc.).
    :returns: WikiTree ID string or empty string.
    :rtype: str
    """
    if not gr_obj:
        return ""

    # 1. Check custom attributes
    try:
        attrs = (
            gr_obj.get_attribute_list()
            if hasattr(gr_obj, "get_attribute_list")
            else getattr(gr_obj, "attribute_list", []) or []
        )
    except Exception:
        attrs = []

    for attr in attrs or []:
        try:
            attr_type = str(attr.get_type() or "").lower()
            val = str(attr.get_value() or "").strip()
            if "wikitree" in attr_type or attr_type == "_wtid":
                wt_id = extract_wikitree_id(val)
                if wt_id:
                    return wt_id
                if val and is_wikitree_id(val):
                    return val
        except Exception:
            continue

    # 2. Check Internet / URL list (Web Home)
    try:
        urls = (
            gr_obj.get_url_list()
            if hasattr(gr_obj, "get_url_list")
            else getattr(gr_obj, "urls", []) or []
        )
    except Exception:
        urls = []

    for url in urls or []:
        try:
            path = (
                url.get_path() if hasattr(url, "get_path") else getattr(url, "path", "")
            )
            wt_id = extract_wikitree_id(path)
            if wt_id:
                return wt_id
        except Exception:
            continue

    return ""


def store_wikitree_id(person: Any, wt_id: str) -> bool:
    """
    Record a WikiTree ID on a person: a "WikiTree ID" attribute (updating
    an existing WikiTree attribute) and a WikiTree profile Internet link,
    unless the person already has a link to that profile.

    :param person: Gramps Person to update (not committed here).
    :param wt_id: WikiTree ID, e.g. 'Franklin-1'.
    :returns: True if the person was changed.
    :rtype: bool
    """
    changed = False
    has_attr = False
    for attr in person.get_attribute_list():
        attr_type = str(attr.get_type() or "").lower()
        if "wikitree" in attr_type or attr_type == "_wtid":
            if attr.get_value() != wt_id:
                attr.set_value(wt_id)
                changed = True
            has_attr = True
            break
    if not has_attr:
        attr = Attribute()
        attr.set_type(AttributeType("WikiTree ID"))
        attr.set_value(wt_id)
        person.add_attribute(attr)
        changed = True

    for url in person.get_url_list():
        path = url.get_path() if hasattr(url, "get_path") else getattr(url, "path", "")
        if wt_id.lower() in (path or "").lower():
            return changed
    wt_url = Url()
    wt_url.set_path(f"https://www.wikitree.com/wiki/{wt_id}")
    wt_url.set_type(UrlType(UrlType.WEB_HOME))
    wt_url.set_description(_("WikiTree Profile"))
    person.add_url(wt_url)
    return True


_DEFAULT_FIELDS = (
    "Id,Name,FirstName,MiddleName,MiddleInitial,LastNameBirth,LastNameCurrent,LastNameOther,"
    "RealName,ColloquialName,Prefix,Suffix,Nicknames,Gender,BirthDate,DeathDate,BirthDateDecade,"
    "DeathDateDecade,BirthLocation,DeathLocation,BirthDateStatus,DeathDateStatus,"
    "IsLiving,Privacy,Touched,Manager,Created,Photo,PhotoData,Father,Mother,Parents,"
    "Children,Spouses,DataStatus,Templates,Categories,Bio"
)


# ------------------------------------------------------------
#
# Photos
#
# ------------------------------------------------------------
# WikiTree keeps full-size images MediaWiki-style, under two folders named
# from the MD5 of the file name: /photo.php/a/a6/Warner-1.jpg. The "/photo/
# jpg/<name>" address is the image's web page, not the image.
WIKITREE_IMAGE_BASE = "https://www.wikitree.com/photo.php"
# Folder under the media base path that photos are downloaded into first;
# a photo merged into the tree is then moved to the base media path and
# named with Media Fix's filename template.
WIKITREE_MEDIA_FOLDER = "WikiTree"
# Media attribute that records the address a photo came from, so a later
# merge of the same profile reuses the photo already in the tree.
WIKITREE_URL_ATTRIBUTE = "WikiTree URL"

# Media Fix's filename template setting and its default (gwizardmediafix.py).
MEDIAFIX_TEMPLATE_KEY = "preferences.gwizardmediafix-filename-template"
MEDIAFIX_DEFAULT_TEMPLATE = "{ref_id}_{surname}_{given}-{doc_type}-{year}.{ext}"


def wikitree_image_url(file_name: str) -> str:
    """Return the address of the full-size WikiTree image named file_name."""
    name = (file_name or "").strip().replace(" ", "_")
    if not name:
        return ""
    name = name[0].upper() + name[1:]
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    return "%s/%s/%s/%s" % (WIKITREE_IMAGE_BASE, digest[0], digest[:2], name)


def is_wikitree_url(path: str) -> bool:
    """Return True for a web address on wikitree.com."""
    host = urlparse(path or "").netloc.casefold()
    return host == "wikitree.com" or host.endswith(".wikitree.com")


def wikitree_media_description(given: str, surname: str, caption: str = "") -> str:
    """
    Return a media description Media Fix reads ("Surname, Given - Photo",
    or the caption in place of "Photo").
    """
    caption = " ".join((caption or "").split()) or "Photo"
    if surname or given:
        return "%s, %s - %s" % (surname, given, caption)
    return caption


# Media Fix's naming helpers, used when Media Fix is not installed. Kept the
# same as clean_token, extract_year_and_clean_doctype and
# format_standard_filename in gwizardmediafix.py; when Media Fix is
# installed its own functions are used instead.
def _clean_token(val: Any) -> str:
    if not val:
        return ""
    s = re.sub(r"[\s_]*-+[\s_]*", "-", str(val))
    clean = re.sub(r"[^\w\-]+", "_", s)
    clean = re.sub(r"_+", "_", clean)
    clean = re.sub(r"[-_]*-[_\s-]*", "-", clean)
    clean = re.sub(r"-+", "-", clean)
    return clean.strip("_-")


def _extract_year_and_clean_doctype(
    doc_type: str, surname: str = "", given: str = ""
) -> tuple[str, str]:
    if not doc_type:
        return "", ""
    year = ""
    y_match = re.search(r"(?:^|[^\d])(1[5-9]\d{2}|20\d{2})(?:[^\d]|$)", doc_type)
    if y_match:
        year = y_match.group(1)
        doc_type = doc_type[: y_match.start(1)] + " " + doc_type[y_match.end(1) :]
    sur_giv_m = re.match(
        r"^\s*(?:[^\W\d_]|[\s'\-])+?,\s*(?:[^\W\d_]|[\s'\-])+?\s*[-_:]+\s*(.+)$",
        doc_type,
    )
    if sur_giv_m:
        doc_type = sur_giv_m.group(1)
    if surname:
        pats = (
            [
                rf"(?i)^\s*{re.escape(surname)}\s*,\s*{re.escape(given)}\s*[-_:]*\s*",
                rf"(?i)^\s*{re.escape(given)}\s+{re.escape(surname)}\s*[-_:]*\s*",
                rf"(?i)^\s*{re.escape(surname)}\s*[-_:]*\s*",
                rf"(?i)[-_:]*\s*{re.escape(surname)}\s*,\s*{re.escape(given)}\s*$",
                rf"(?i)[-_:]*\s*{re.escape(surname)}\s*$",
            ]
            if given
            else [rf"(?i)^\s*{re.escape(surname)}\s*[-_:]*\s*"]
        )
        for pat in pats:
            doc_type = re.sub(pat, "", doc_type)
    clean = re.sub(r"[^\w\-]+", "_", doc_type)
    clean = re.sub(r"[\s_]*-+[\s_]*", "-", clean)
    clean = re.sub(r"[-_]*-[_\s-]*", "-", clean)
    clean = re.sub(r"_+", "_", clean).strip("_-")
    return clean, year


def _format_standard_filename(
    template: str, context: dict[str, str], max_stem_len: int = 85
) -> str:
    ext = _clean_token(context.get("ext", "jpg")).lower() or "jpg"
    safe_context = {k: _clean_token(v) for k, v in context.items() if k != "ext"}
    safe_context["ext"] = ext
    try:
        rendered = template.format(**safe_context)
    except (KeyError, ValueError, IndexError):
        rendered = f"{safe_context.get('ref_id', '')}_{safe_context.get('orig', 'media')}.{ext}"
    base = rendered.rsplit(".", 1)[0] if "." in rendered else rendered
    base = re.sub(r"[\s_]*-+[\s_]*", "-", base)
    base = re.sub(r"[^\w\-]+", "_", base)
    base = re.sub(r"_+", "_", base)
    base = re.sub(r"[-_]*-[_\s-]*", "-", base)
    base = re.sub(r"-+", "-", base)
    base = base.strip("_-")
    if not base:
        base = (
            _clean_token(safe_context.get("orig") or safe_context.get("id")) or "media"
        )
    if len(base) > max_stem_len:
        base = base[:max_stem_len].rstrip("_-")
    return f"{base}.{ext}"


def _mediafix_naming() -> tuple[Callable[..., Any], Callable[..., Any], str]:
    """
    Return Media Fix's (extract_year_and_clean_doctype,
    format_standard_filename, template), from Media Fix itself when it is
    installed, otherwise from the copies above.
    """
    template = MEDIAFIX_DEFAULT_TEMPLATE
    try:
        template = str(config.get(MEDIAFIX_TEMPLATE_KEY) or template)
    except Exception:  # pylint: disable=broad-except
        pass
    try:
        # pylint: disable=import-outside-toplevel
        from gramps.plugins.tool.gwizardmediafix import (
            extract_year_and_clean_doctype,
            format_standard_filename,
        )

        return extract_year_and_clean_doctype, format_standard_filename, template
    except Exception:  # pylint: disable=broad-except
        return _extract_year_and_clean_doctype, _format_standard_filename, template


def person_year(db: Any, person: Any) -> str:
    """
    Return the year Media Fix uses for a person's media without a date:
    birth (or fallback), else death (or fallback), else the first dated
    event. '' when there is none.
    """
    if db is None or person is None:
        return ""
    try:
        for event in (
            get_birth_or_fallback(db, person),
            get_death_or_fallback(db, person),
        ):
            if event is not None and event.get_date_object().get_year() > 0:
                return str(event.get_date_object().get_year())
        for event_ref in person.get_event_ref_list():
            event = db.get_event_from_handle(event_ref.ref)
            if event is not None and event.get_date_object().get_year() > 0:
                return str(event.get_date_object().get_year())
    except Exception:  # pylint: disable=broad-except
        pass
    return ""


def media_fix_filename(db: Any, person: Any, media: Any, ext: str) -> str:
    """
    Return the file name Media Fix gives a person's media object (its
    person-backlink naming): the year comes from the description, else the
    media date, else the person.
    """
    extract, format_name, template = _mediafix_naming()
    name = person.get_primary_name()
    surname = str(name.get_surname() or "")
    given = str(name.get_first_name() or "")
    description = str(media.get_description() or "")
    doc_type, found_year = extract(description or "Photo", surname, given)
    year = found_year
    if not year:
        media_year = media.get_date_object().get_year()
        year = str(media_year) if media_year > 0 else person_year(db, person)
    orig = os.path.splitext(os.path.basename(urlparse(media.get_path()).path))[0]
    context = {
        "id": str(media.get_gramps_id() or ""),
        "desc": description,
        "orig": orig,
        "ext": (ext or "jpg").lstrip(".").lower(),
        "ref_id": str(person.get_gramps_id() or ""),
        "surname": surname,
        "given": given,
        "doc_type": doc_type or "Photo",
        "year": year,
        "assoc": "",
        "hash": str(media.get_checksum() or "")[:8],
    }
    return format_name(template, context)


def place_file(cache_path: str, wanted_path: str) -> str:
    """
    Move a downloaded file from the download cache to wanted_path and
    return where it ended up. A different file already there is never
    replaced: the file gets the next free "-2", "-3", ... name. An identical
    file already there is reused. If the move fails the file stays in the
    cache, which is still a valid media path.
    """
    if not wanted_path or os.path.normcase(
        os.path.abspath(cache_path)
    ) == os.path.normcase(os.path.abspath(wanted_path)):
        return cache_path
    stem, ext = os.path.splitext(wanted_path)
    candidate = wanted_path
    number = 1
    try:
        new_sum = create_checksum(cache_path)
        while os.path.exists(candidate):
            if new_sum and create_checksum(candidate) == new_sum:
                os.remove(cache_path)
                _remove_empty_dir(cache_path, wanted_path)
                return candidate
            number += 1
            candidate = "%s-%d%s" % (stem, number, ext)
        os.makedirs(os.path.dirname(candidate) or ".", exist_ok=True)
        os.replace(cache_path, candidate)
    except OSError as err:
        LOG.warning("WikiTree photo %s could not be moved: %s", cache_path, err)
        return cache_path
    _remove_empty_dir(cache_path, wanted_path)
    return candidate


def _remove_empty_dir(cache_path: str, wanted_path: str) -> None:
    """Remove the download cache folder once it is empty."""
    folder = os.path.dirname(os.path.abspath(cache_path))
    if os.path.normcase(folder) != os.path.normcase(
        os.path.dirname(os.path.abspath(wanted_path))
    ):
        try:
            os.rmdir(folder)
        except OSError:
            pass


# ------------------------------------------------------------
#
# WikiTreeInterface
#
# ------------------------------------------------------------
class WikiTreeInterface:
    """
    Interface client for the WikiTree REST API.
    """

    DEFAULT_BASE_URL = "https://api.wikitree.com/api.php"
    DEFAULT_APP_ID = "Gramps_GWizard_1.0"
    # searchPerson limits from the WikiTree API documentation.
    MAX_SEARCH_LIMIT = 100
    MAX_DATE_SPREAD = 20

    def __init__(
        self,
        app_id: str = DEFAULT_APP_ID,
        base_url: str = DEFAULT_BASE_URL,
        verify_ssl: bool | str | None = None,
    ) -> None:
        """
        Initialize the WikiTree API client.

        :param app_id: Application identifier requested by WikiTree.
        :param base_url: Base URL for WikiTree API endpoint.
        :param verify_ssl: SSL certificate verification flag or CA bundle path.
        """
        self.app_id = app_id.strip() or self.DEFAULT_APP_ID
        self.base_url = base_url.rstrip("/")
        self.headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": f"Gramps-GWizard-WikiTree/{self.app_id}",
        }

        if verify_ssl is not None:
            self.verify_ssl = verify_ssl
        else:
            ca_env = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get(
                "SSL_CERT_FILE"
            )
            if ca_env and os.path.isfile(ca_env):
                self.verify_ssl = ca_env
            else:
                user_combined = os.path.expanduser(r"~\certs\COMBINED_PEM.pem")
                if os.path.isfile(user_combined):
                    self.verify_ssl = user_combined
                else:
                    self.verify_ssl = True

    def get_person(
        self,
        key: str,
        fields: str = _DEFAULT_FIELDS,
        timeout: int = 30,
        raise_errors: bool = False,
    ) -> dict[str, Any] | None:
        """
        Fetch profile details for a single WikiTree ID or key.

        :param key: WikiTree ID (e.g. 'Franklin-1' or integer ID).
        :param fields: Comma-separated list of profile fields to retrieve.
        :param timeout: HTTP request timeout in seconds.
        :param raise_errors: Raise RuntimeError when the request fails,
            instead of returning None (so a caller can tell a failure from
            a profile that does not exist).
        :returns: Dictionary of person fields, or None if not found or on error.
        """
        import requests

        params = {
            "action": "getPerson",
            "key": key,
            "fields": fields,
            "appId": self.app_id,
        }
        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    item = data[0]
                    if isinstance(item, dict) and item.get("status") == 0:
                        return item.get("person")
            else:
                LOG.warning("WikiTree API getPerson returned %d", response.status_code)
                if raise_errors:
                    raise RuntimeError(
                        f"WikiTree getPerson returned HTTP {response.status_code}"
                    )
        except Exception as err:
            LOG.error("WikiTree getPerson failed: %s", err)
            if raise_errors:
                raise RuntimeError(str(err)) from err
        return None

    def get_people(
        self,
        keys: str | list[str],
        ancestors: int = 0,
        descendants: int = 0,
        fields: str = _DEFAULT_FIELDS,
        timeout: int = 30,
    ) -> dict[str, dict[str, Any]]:
        """
        Query multiple IDs or ancestor/descendant trees simultaneously.

        :param keys: Single WikiTree key or list of keys.
        :param ancestors: Generations of ancestors to retrieve (0 to 10).
        :param descendants: Generations of descendants to retrieve (0 to 10).
        :param fields: Comma-separated list of fields.
        :param timeout: HTTP request timeout.
        :returns: Dictionary mapping person ID/key to profile dictionary.
        """
        import requests

        keys_str = ",".join(keys) if isinstance(keys, list) else str(keys)
        params: dict[str, Any] = {
            "action": "getPeople",
            "keys": keys_str,
            "fields": fields,
            "appId": self.app_id,
        }
        if ancestors > 0:
            params["ancestors"] = min(ancestors, 10)
        if descendants > 0:
            params["descendants"] = min(descendants, 10)

        results: dict[str, dict[str, Any]] = {}
        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    item = data[0]
                    if isinstance(item, dict) and "people" in item:
                        people_dict = item["people"]
                        if isinstance(people_dict, dict):
                            for pid, pdata in people_dict.items():
                                if isinstance(pdata, dict):
                                    results[str(pid)] = pdata
            else:
                LOG.warning("WikiTree getPeople returned %d", response.status_code)
        except Exception as err:
            LOG.error("WikiTree getPeople failed: %s", err)
        return results

    def search_person(
        self,
        first_name: str = "",
        last_name: str = "",
        birth_date: str = "",
        death_date: str = "",
        birth_location: str = "",
        death_location: str = "",
        father_first_name: str = "",
        mother_first_name: str = "",
        gender: str = "",
        last_name_match: str = "all",
        fields: str = "",
        limit: int = 25,
        timeout: int = 30,
        date_spread: int = 0,
        raise_errors: bool = False,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Fuzzy search for persons across names, dates, and locations.
        """
        import requests

        params: dict[str, Any] = {
            "action": "searchPerson",
            "limit": max(1, min(limit, self.MAX_SEARCH_LIMIT)),
            "appId": self.app_id,
        }
        if first_name:
            params["FirstName"] = first_name
        if last_name:
            params["LastName"] = last_name
            if last_name_match:
                params["lastNameMatch"] = last_name_match
        if birth_date:
            params["BirthDate"] = birth_date
        if death_date:
            params["DeathDate"] = death_date
        if birth_location:
            params["BirthLocation"] = birth_location
        if death_location:
            params["DeathLocation"] = death_location
        if father_first_name:
            params["fatherFirstName"] = father_first_name
        if mother_first_name:
            params["motherFirstName"] = mother_first_name
        if gender:
            params["Gender"] = gender
        if fields:
            params["fields"] = fields
        if date_spread > 0:
            params["dateSpread"] = min(date_spread, self.MAX_DATE_SPREAD)

        for key, val in kwargs.items():
            if val is not None:
                params[key] = val

        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    item = data[0]
                    if isinstance(item, dict) and item.get("status") == 0:
                        matches = item.get("matches", [])
                        if isinstance(matches, list):
                            return matches
            else:
                LOG.warning("WikiTree searchPerson returned %d", response.status_code)
                if raise_errors:
                    raise RuntimeError(
                        f"WikiTree searchPerson returned HTTP {response.status_code}"
                    )
        except Exception as err:
            LOG.error("WikiTree searchPerson failed: %s", err)
            if raise_errors:
                raise RuntimeError(str(err)) from err
        return []

    def download_image(self, url: str, path: str, timeout: int = 60) -> bool:
        """
        Download the image at url to path and return True on success.

        Only an image reply is saved: an HTML page (such as a photo's web
        page, or an error page) is refused, so it never becomes a media
        file. The file is written beside path first and renamed when
        complete.

        :param url: Address of the image.
        :param path: Absolute file path to save it to.
        :param timeout: HTTP request timeout in seconds.
        """
        import requests

        try:
            response = requests.get(
                url,
                headers={"User-Agent": self.headers["User-Agent"]},
                verify=self.verify_ssl,
                timeout=timeout,
            )
        except requests.RequestException as err:
            LOG.warning("WikiTree photo %s could not be downloaded: %s", url, err)
            return False
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if (
            response.status_code != 200
            or not content_type.startswith("image/")
            or not response.content
        ):
            LOG.warning(
                "WikiTree photo %s not downloaded (HTTP %s, %s)",
                url,
                response.status_code,
                content_type or "no content type",
            )
            return False
        partial = path + ".part"
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(partial, "wb") as out:
                out.write(response.content)
            os.replace(partial, path)
        except OSError as err:
            LOG.warning("WikiTree photo %s could not be saved: %s", path, err)
            try:
                os.remove(partial)
            except OSError:
                pass
            return False
        return True

    def get_bio(self, key: str, timeout: int = 30) -> str:
        """
        Retrieve biography markdown text for a person.

        :param key: WikiTree ID.
        :param timeout: HTTP request timeout.
        :returns: Biography text string.
        """
        import requests

        params = {
            "action": "getBio",
            "key": key,
            "appId": self.app_id,
        }
        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    item = data[0]
                    if isinstance(item, dict):
                        return str(item.get("bio") or "")
        except Exception as err:
            LOG.error("WikiTree getBio failed: %s", err)
        return ""


# ------------------------------------------------------------
#
# WikiTreeGWizard
#
# ------------------------------------------------------------
class WikiTreeGWizard(GedGWizard):
    """
    GWizard implementation for querying and merging WikiTree genealogical
    profiles into an active Gramps database.
    """

    WT_ID_REGEX = re.compile(r"^[A-Za-z]+-\d+$")

    def __init__(self, db: DbWriteBase) -> None:
        """
        Initialize the WikiTreeGWizard.

        :param db: The target Gramps database instance.
        """
        super().__init__(db)

    @classmethod
    def is_wikitree_id(cls, value: str) -> bool:
        """
        Check if a string matches the standard WikiTree ID pattern.

        :param value: String to test (e.g. 'Franklin-1').
        :returns: True if value matches '<Surname>-<Number>'.
        """
        return is_wikitree_id(value)

    def _connect(self, **kwargs: Any) -> bool:
        """
        Configure connection details for the WikiTree query.

        :param query: Search query or WikiTree ID (required).
        :param ancestors: Ancestor generations to crawl (0 to 10).
        :param include_relatives: Whether to fetch spouses and children.
        :param app_id: Custom WikiTree App ID.
        :param client: Optional pre-configured WikiTreeInterface instance.
        :param people_data: Optional pre-fetched list/dict of profile data for tests.
        :param download_media: Download the merged person's WikiTree photos
            after a merge (default: yes, unless people_data is given).
        :returns: True if query or people_data is configured.
        """
        query = kwargs.get("query", "").strip()
        extracted_query = extract_wikitree_id(query)
        if extracted_query:
            query = extracted_query
        people_data = kwargs.get("people_data")
        if not query and people_data is None:
            LOG.error("A search query or people data is required for WikiTree merge.")
            return False

        self.context["query"] = query
        self.context["ancestors"] = int(kwargs.get("ancestors", 0))
        self.context["include_relatives"] = bool(kwargs.get("include_relatives", False))
        self.context["app_id"] = kwargs.get("app_id", WikiTreeInterface.DEFAULT_APP_ID)
        self.context["client"] = kwargs.get("client")
        self.context["people_data"] = people_data
        self.context["download_media"] = bool(
            kwargs.get("download_media", people_data is None)
        )
        return True

    @staticmethod
    def _clean_date_str(raw_date: str) -> str:
        """
        Normalize WikiTree dates by removing unknown month/day zeros.

        :param raw_date: Date string (e.g. '1706-00-00' or '0000-00-00').
        :returns: Normalized date string for Gramps date parser.
        """
        val = raw_date.strip()
        if not val or val == "0000-00-00":
            return ""
        if val.endswith("-00-00"):
            return val[:-6]
        if val.endswith("-00"):
            return val[:-3]
        return val

    @staticmethod
    def wikitree_date_to_gramps(
        value: str | None,
        status: str | None = None,
        decade: str | None = None,
    ) -> Date:
        """
        Convert WikiTree date, status/certainty flag, and decade to a Date.

        :param value: Date string (e.g. '1706-01-17', '1706-00-00', or '1706').
        :param status: Certainty status ('certain', 'guess', 'before', 'after').
        :param decade: Fallback decade string (e.g. '1700s').
        :returns: Gramps Date object with appropriate modifier and quality.
        """
        date = Date()
        val = (value or "").strip()
        st = (status or "").strip().lower()

        modifier = Date.MOD_NONE
        quality = Date.QUAL_NONE
        if st in ("guess", "estimated", "about", "abt"):
            modifier = Date.MOD_ABOUT
            quality = Date.QUAL_ESTIMATED
        elif st in ("before", "bef"):
            modifier = Date.MOD_BEFORE
        elif st in ("after", "aft"):
            modifier = Date.MOD_AFTER

        # Check full ISO YYYY-MM-DD
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", val)
        if m:
            year, month, day = (int(p) for p in m.groups())
            if year > 0:
                if month == 0:
                    day = 0
                date.set(
                    quality=quality,
                    modifier=modifier,
                    calendar=Date.CAL_GREGORIAN,
                    value=(day, month, year, False),
                )
                return date

        # Check YYYY-MM
        m = re.match(r"^(\d{4})-(\d{2})$", val)
        if m:
            year, month = (int(p) for p in m.groups())
            if year > 0:
                date.set(
                    quality=quality,
                    modifier=modifier,
                    calendar=Date.CAL_GREGORIAN,
                    value=(0, month, year, False),
                )
                return date

        # Check year only
        m = re.match(r"^(\d{4})$", val)
        if m:
            year = int(m.group(1))
            if year > 0:
                date.set(
                    quality=quality,
                    modifier=modifier,
                    calendar=Date.CAL_GREGORIAN,
                    value=(0, 0, year, False),
                )
                return date

        # Try parsing with dateparser if non-empty and not all zero
        if val and val != "0000-00-00":
            clean = WikiTreeGWizard._clean_date_str(val)
            if clean:
                parsed = dateparser.parse(clean)
                if not parsed.is_empty():
                    if (
                        modifier != Date.MOD_NONE
                        and parsed.get_modifier() == Date.MOD_NONE
                    ):
                        parsed.set_modifier(modifier)
                    if (
                        quality != Date.QUAL_NONE
                        and parsed.get_quality() == Date.QUAL_NONE
                    ):
                        parsed.set_quality(quality)
                    return parsed

        # Fallback to decade if value was empty or 0000-00-00
        dec_val = (decade or "").strip()
        m_dec = re.match(r"^(\d{3}0)s$", dec_val, re.IGNORECASE)
        if m_dec:
            start_yr = int(m_dec.group(1))
            stop_yr = start_yr + 9
            date.set(
                quality=Date.QUAL_ESTIMATED,
                modifier=Date.MOD_RANGE,
                calendar=Date.CAL_GREGORIAN,
                value=(0, 0, start_yr, False, 0, 0, stop_yr, False),
            )
            return date

        return date

    @staticmethod
    def clean_source_text(raw_text: str) -> str:
        """
        Strip wikitext markup and normalize external source citation text.

        :param raw_text: Raw reference or source line from WikiTree.
        :returns: Cleaned human-readable citation text.
        """
        text = (raw_text or "").strip()
        # Convert [http://url Description] -> Description
        text = re.sub(r"\[(?:https?://[^\s\]]+)\s+([^\]]+)\]", r"\1", text)
        # Convert [http://url] -> http://url
        text = re.sub(r"\[(https?://[^\s\]]+)\]", r"\1", text)
        # Convert [[Target|Label]] -> Label, [[Target]] -> Target
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
        # Clean common templates like {{FindAGrave|123}}
        text = re.sub(
            r"\{\{FindAGrave\|(?:[^|]*\|)?(\d+)\}\}",
            r"Find A Grave memorial \1",
            text,
            flags=re.I,
        )
        text = re.sub(r"\{\{[^\}]+\}\}", "", text)
        # Clean HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Clean bold and italics
        text = re.sub(r"'''+|''", "", text)
        # Normalize whitespace
        return " ".join(text.split()).strip()

    @staticmethod
    def extract_source_title(cleaned_text: str) -> str:
        """
        Extract a concise, descriptive title for a Source record from citation text.

        :param cleaned_text: Cleaned citation text string.
        :returns: Abbreviated or full title string.
        """
        cleaned = (cleaned_text or "").strip()
        if not cleaned:
            return _("WikiTree Cited Source")
        return describe_bio_source(cleaned)["title"]

    @staticmethod
    def parse_bio_sources(bio_text: str) -> list[dict[str, str]]:
        """
        Extract inline <ref> citations and bibliography sources from a biography.

        :param bio_text: Raw WikiTree biography markup.
        :returns: List of dicts with keys 'name', 'text', and 'context'.
        """
        bio = (bio_text or "").strip()
        if not bio:
            return []

        sources: list[dict[str, str]] = []
        seen_texts: set[str] = set()

        # 1. Match full <ref> tags
        ref_pattern = re.compile(
            r"<ref(?:\s+name\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s/>]+)))?\s*>(.*?)</ref>",
            re.DOTALL | re.IGNORECASE,
        )
        for m in ref_pattern.finditer(bio):
            name = m.group(1) or m.group(2) or m.group(3) or ""
            content = m.group(4).strip()
            if content:
                norm = " ".join(content.split()).lower()
                if norm not in seen_texts:
                    seen_texts.add(norm)
                    # Extract surrounding context (100 chars before, 50 chars after)
                    start_pos = max(0, m.start() - 100)
                    end_pos = min(len(bio), m.end() + 50)
                    context_snippet = bio[start_pos:end_pos]
                    sources.append(
                        {
                            "name": name,
                            "text": content,
                            "context": context_snippet,
                        }
                    )

        # 2. Match sources section
        sec_match = re.search(
            r"==+\s*(?:Sources|References|Bibliography).*?==+(.*)",
            bio,
            re.DOTALL | re.IGNORECASE,
        )
        if sec_match:
            sec_text = sec_match.group(1)
            for line in sec_text.splitlines():
                line = line.strip()
                if line.startswith(("*", "#")):
                    item = line.lstrip("*# ").strip()
                    if item and not item.lower().startswith(
                        ("<references", "{{reflist", "see also:")
                    ):
                        norm = " ".join(item.split()).lower()
                        if norm not in seen_texts:
                            seen_texts.add(norm)
                            sources.append(
                                {
                                    "name": "",
                                    "text": item,
                                    "context": "sources_section",
                                }
                            )

        return sources

    @staticmethod
    def clean_bio_text(bio_text: str) -> str:
        """
        Clean wikitext markup and remove inline references to produce narrative text.

        :param bio_text: Raw WikiTree biography markup.
        :returns: Cleaned narrative text suitable for a Gramps Note.
        """
        bio = (bio_text or "").strip()
        if not bio:
            return ""

        # Remove everything starting at the Sources section
        bio = re.split(
            r"==+\s*(?:Sources|References|Bibliography).*?==+",
            bio,
            flags=re.IGNORECASE,
        )[0]

        # Remove inline <ref> tags and self-closing tags
        bio = re.sub(
            r"<ref(?:\s+[^>]*)?>.*?</ref>",
            "",
            bio,
            flags=re.DOTALL | re.IGNORECASE,
        )
        bio = re.sub(r"<ref(?:\s+[^>]*)?/>", "", bio, flags=re.IGNORECASE)

        # Remove categories [[Category:...]]
        bio = re.sub(r"\[\[Category:[^\]]+\]\]", "", bio, flags=re.IGNORECASE)

        # Remove templates {{...}}
        bio = re.sub(r"\{\{[^\}]+\}\}", "", bio)

        # Convert wiki links [[Target|Label]] -> Label, [[Target]] -> Target
        bio = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", bio)

        # Convert external links [http://url label] -> label
        bio = re.sub(r"\[(?:https?://[^\s\]]+)\s+([^\]]+)\]", r"\1", bio)
        bio = re.sub(r"\[(https?://[^\s\]]+)\]", r"\1", bio)

        # Clean bold and italics
        bio = re.sub(r"'''+|''", "", bio)

        # Convert section headers like == Biography == or === Birth === to headings
        bio = re.sub(r"==+\s*([^=]+?)\s*==+", r"\1:", bio)

        # Collapse excess empty lines
        lines = [line.strip() for line in bio.splitlines()]
        cleaned_lines: list[str] = []
        prev_empty = False
        for line in lines:
            if not line:
                if not prev_empty and cleaned_lines:
                    cleaned_lines.append("")
                    prev_empty = True
            else:
                cleaned_lines.append(line)
                prev_empty = False

        return "\n".join(cleaned_lines).strip()

    @staticmethod
    def parse_bio_templates(bio_text: str) -> list[dict[str, Any]]:
        """
        Parse WikiTree templates/stickers {{Name|param1|param2=val}} from bio text.

        :param bio_text: Raw biography wikitext markup.
        :returns: List of dicts with 'name' and 'params'.
        """
        templates: list[dict[str, Any]] = []
        if not bio_text:
            return templates
        for m in re.finditer(r"\{\{([A-Za-z0-9 _-]+)(?:\|([^}]+))?\}\}", bio_text):
            tname = m.group(1).strip()
            raw_params = m.group(2) or ""
            params: dict[str, str] = {}
            idx = 1
            for part in raw_params.split("|"):
                part = part.strip()
                if not part:
                    continue
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k.strip()] = v.strip()
                else:
                    params[str(idx)] = part
                    params[part] = ""
                    idx += 1
            templates.append({"name": tname, "params": params})
        return templates

    def process_templates(
        self,
        person: Person,
        templates: list[dict[str, Any]],
        source_db: DbWriteBase,
        trans: DbTxn,
    ) -> None:
        """
        Process WikiTree templates/stickers into Gramps Attributes, URLs, and Events.

        :param person: Target Person object being populated.
        :param templates: List of template dictionaries.
        :param source_db: In-memory source database.
        :param trans: Active database transaction.
        """
        existing_attrs = {
            (str(a.get_type()), str(a.get_value())) for a in person.get_attribute_list()
        }
        existing_urls = {u.get_path() for u in person.get_url_list()}

        for item in templates:
            if not isinstance(item, dict):
                continue
            tname = str(item.get("name") or "").strip()
            params = item.get("params") or {}
            if isinstance(params, list):
                params = {str(i + 1): v for i, v in enumerate(params)}
            elif not isinstance(params, dict):
                params = {}

            tname_lower = tname.lower()

            # 1. Find A Grave
            if "findagrave" in tname_lower or "find a grave" in tname_lower:
                mem_id = ""
                for k in ("id", "memorial", "memorial_id", "1"):
                    if k in params and str(params[k]).strip().isdigit():
                        mem_id = str(params[k]).strip()
                        break
                if not mem_id:
                    for k, v in params.items():
                        if str(k).strip().isdigit():
                            mem_id = str(k).strip()
                            break
                        if str(v).strip().isdigit():
                            mem_id = str(v).strip()
                            break

                if mem_id:
                    attr_val = mem_id
                    if ("Find A Grave ID", attr_val) not in existing_attrs:
                        attr = Attribute()
                        attr.set_type(AttributeType(_("Find A Grave ID")))
                        attr.set_value(attr_val)
                        person.add_attribute(attr)
                        existing_attrs.add(("Find A Grave ID", attr_val))

                    memorial_url = f"https://www.findagrave.com/memorial/{mem_id}"
                    if memorial_url not in existing_urls:
                        fg_url = Url()
                        fg_url.set_path(memorial_url)
                        fg_url.set_type(UrlType(UrlType.WEB_SEARCH))
                        fg_url.set_description(_("Find A Grave Memorial"))
                        person.add_url(fg_url)
                        existing_urls.add(memorial_url)

            # 2. Occupation
            elif tname_lower == "occupation":
                occ_raw = (
                    params.get("text")
                    or params.get("occupation")
                    or params.get("1")
                    or ""
                )
                occ_cleaned = self.clean_source_text(str(occ_raw))
                if occ_cleaned:
                    occ_evt = Event()
                    occ_evt.set_type(EventType(EventType.OCCUPATION))
                    occ_evt.set_description(occ_cleaned)
                    occ_h = source_db.add_event(occ_evt, trans)
                    occ_ref = EventRef()
                    occ_ref.ref = occ_h
                    person.add_event_ref(occ_ref)

                    if (
                        len(occ_cleaned) <= 60
                        and (str(AttributeType.OCCUPATION), occ_cleaned)
                        not in existing_attrs
                    ):
                        attr = Attribute()
                        attr.set_type(AttributeType(AttributeType.OCCUPATION))
                        attr.set_value(occ_cleaned)
                        person.add_attribute(attr)
                        existing_attrs.add((str(AttributeType.OCCUPATION), occ_cleaned))

            # 3. Succession / Public Office
            elif "succession" in tname_lower:
                for i in range(1, 10):
                    pos = params.get(f"position{i}") or params.get(f"office{i}")
                    yrs = params.get(f"years{i}") or params.get(f"dates{i}")
                    if pos:
                        pos_cleaned = self.clean_source_text(str(pos))
                        succ_evt = Event()
                        succ_evt.set_type(EventType(EventType.ELECTED))
                        succ_evt.set_description(pos_cleaned)
                        if yrs:
                            succ_evt.set_date_object(
                                self.wikitree_date_to_gramps(str(yrs))
                            )
                        succ_h = source_db.add_event(succ_evt, trans)
                        succ_ref = EventRef()
                        succ_ref.ref = succ_h
                        person.add_event_ref(succ_ref)

                        val_str = f"{pos_cleaned} ({yrs})" if yrs else pos_cleaned
                        if ("Public Office", val_str) not in existing_attrs:
                            attr = Attribute()
                            attr.set_type(AttributeType(_("Public Office")))
                            attr.set_value(val_str)
                            person.add_attribute(attr)
                            existing_attrs.add(("Public Office", val_str))

            # 4. Society Ancestor
            elif any(
                term in tname_lower
                for term in ("society ancestor", "dar sticker", "sar sticker")
            ):
                soc = params.get("society") or (
                    "DAR" if "dar" in tname_lower else "SAR"
                )
                anc = params.get("ancestor") or params.get("1") or ""
                val = f"{soc}: {anc}".strip(": ")
                if ("Society Ancestor", val) not in existing_attrs:
                    attr = Attribute()
                    attr.set_type(AttributeType(_("Society Ancestor")))
                    attr.set_value(val)
                    person.add_attribute(attr)
                    existing_attrs.add(("Society Ancestor", val))

            # 5. Military / Revolutionary / Civil War
            elif any(
                term in tname_lower
                for term in (
                    "1776 sticker",
                    "military",
                    "civil war",
                    "war of 1812",
                    "veteran",
                    "war sticker",
                )
            ):
                unit = (
                    params.get("unit")
                    or params.get("regiment")
                    or params.get("branch")
                    or ""
                )
                rank = params.get("rank") or ""
                parts = [tname]
                if rank:
                    parts.append(str(rank))
                if unit:
                    parts.append(str(unit))
                desc = (
                    ": ".join(parts[:1] + [" ".join(parts[1:])])
                    if len(parts) > 1
                    else parts[0]
                )
                mil_evt = Event()
                mil_evt.set_type(EventType(EventType.MILITARY_SERV))
                mil_evt.set_description(desc)
                mil_h = source_db.add_event(mil_evt, trans)
                mil_ref = EventRef()
                mil_ref.ref = mil_h
                person.add_event_ref(mil_ref)

            # 6. Notability
            elif tname_lower == "notability":
                notab_text = params.get("text") or params.get("1") or ""
                if notab_text:
                    cleaned_notab = self.clean_source_text(str(notab_text))[:250]
                    if ("Notability", cleaned_notab) not in existing_attrs:
                        attr = Attribute()
                        attr.set_type(AttributeType(_("Notability")))
                        attr.set_value(cleaned_notab)
                        person.add_attribute(attr)
                        existing_attrs.add(("Notability", cleaned_notab))

            # 7. Other project or ancestor stickers
            elif (
                tname.endswith("Sticker")
                or tname.endswith("Project")
                or any(
                    x in tname_lower
                    for x in ("mayflower", "huguenot", "puritan", "pioneer")
                )
            ):
                if tname_lower not in ("citation needed", "reflist", "references"):
                    if ("Project / Sticker", tname) not in existing_attrs:
                        attr = Attribute()
                        attr.set_type(AttributeType(_("Project / Sticker")))
                        attr.set_value(tname)
                        person.add_attribute(attr)
                        existing_attrs.add(("Project / Sticker", tname))

    @staticmethod
    def determine_place_type(
        name: str, level_from_top: int, total_levels: int
    ) -> PlaceType:
        """
        Infer a PlaceType based on locality name and hierarchical level.

        :param name: Specific name of the place part.
        :param level_from_top: Distance from top enclosing level (0 = country/state).
        :param total_levels: Total number of comma-separated components.
        :returns: PlaceType object.
        """
        nl = name.lower()
        if any(
            k in nl
            for k in (
                "cemetery",
                "burial ground",
                "burying ground",
                "memorial park",
                "churchyard",
                "church",
                "cathedral",
                "chapel",
                "hospital",
            )
        ):
            return PlaceType(PlaceType.BUILDING)
        if "parish" in nl:
            return PlaceType(PlaceType.PARISH)
        if "county" in nl or "co." in nl:
            return PlaceType(PlaceType.COUNTY)
        if "township" in nl or "twp" in nl:
            return PlaceType(PlaceType.TOWN)
        if "borough" in nl:
            return PlaceType(PlaceType.BOROUGH)

        if total_levels == 1:
            if any(
                k in nl
                for k in (
                    "united states",
                    "england",
                    "france",
                    "germany",
                    "canada",
                    "australia",
                    "ireland",
                    "scotland",
                    "wales",
                    "kingdom",
                    "colony",
                    "republic",
                )
            ):
                return PlaceType(PlaceType.COUNTRY)
            return PlaceType(PlaceType.UNKNOWN)

        if level_from_top == 0:
            if total_levels >= 4 or any(
                k in nl
                for k in (
                    "united states",
                    "england",
                    "france",
                    "germany",
                    "canada",
                    "australia",
                    "ireland",
                    "scotland",
                    "wales",
                    "kingdom",
                    "colony",
                    "republic",
                )
            ):
                return PlaceType(PlaceType.COUNTRY)
            return PlaceType(PlaceType.STATE)

        if level_from_top == 1:
            if total_levels >= 4:
                return PlaceType(PlaceType.STATE)
            return PlaceType(PlaceType.COUNTY)

        if level_from_top == 2:
            if total_levels >= 4:
                return PlaceType(PlaceType.COUNTY)
            return PlaceType(PlaceType.CITY)

        if level_from_top == 3:
            return PlaceType(PlaceType.CITY)

        return PlaceType(PlaceType.LOCALITY)

    @staticmethod
    def format_wikitree_timestamp(ts: str | None) -> str:
        """
        Format a WikiTree timestamp string (YYYYMMDDHHMMSS) to ISO format.

        :param ts: WikiTree timestamp string.
        :returns: Formatted timestamp string (YYYY-MM-DD HH:MM:SS) or original text.
        """
        val = (ts or "").strip()
        if len(val) == 14 and val.isdigit():
            return (
                f"{val[:4]}-{val[4:6]}-{val[6:8]} "
                f"{val[8:10]}:{val[10:12]}:{val[12:14]}"
            )
        if len(val) == 8 and val.isdigit():
            return f"{val[:4]}-{val[4:6]}-{val[6:8]}"
        return val

    @staticmethod
    def check_profile_drift(
        target_person: Person | None,
        remote_touched: str | None,
    ) -> dict[str, Any]:
        """
        Check whether a remote WikiTree profile has been modified since it was merged.

        :param target_person: Person in local Gramps database.
        :param remote_touched: Touched timestamp from WikiTree profile.
        :returns: Dictionary with 'has_drift', 'local_touched', 'remote_touched',
            and 'message'.
        """
        result = {
            "has_drift": False,
            "local_touched": "",
            "remote_touched": (remote_touched or "").strip(),
            "message": "",
        }
        if not target_person:
            return result

        local_ts = ""
        for attr in target_person.get_attribute_list():
            if str(attr.get_type()) == "WikiTree Touched":
                local_ts = str(attr.get_value() or "").strip()
                break

        result["local_touched"] = local_ts
        rem_ts = (remote_touched or "").strip()

        if local_ts and rem_ts:
            norm_local = re.sub(r"\D", "", local_ts)
            norm_rem = re.sub(r"\D", "", rem_ts)
            if norm_rem > norm_local:
                result["has_drift"] = True
                result["message"] = _(
                    "WikiTree profile was modified on %(remote)s (local copy from %(local)s)."
                ) % {
                    "remote": WikiTreeGWizard.format_wikitree_timestamp(rem_ts),
                    "local": WikiTreeGWizard.format_wikitree_timestamp(local_ts),
                }
            else:
                result["message"] = _("Local profile is up to date with WikiTree.")
        elif not local_ts and rem_ts:
            result["has_drift"] = True
            result["message"] = _("No prior synchronization timestamp found.")
        return result

    @staticmethod
    def _parse_query_names(query: str) -> tuple[str, str]:
        """
        Split a human name query into first name and last name.

        :param query: Search query string.
        :returns: Tuple of (first_name, last_name).
        """
        text = query.strip()
        if "," in text:
            parts = [p.strip() for p in text.split(",", 1)]
            return parts[1], parts[0]
        tokens = text.split()
        if len(tokens) >= 2:
            return " ".join(tokens[:-1]), tokens[-1]
        elif len(tokens) == 1:
            return "", tokens[0]
        return "", ""

    def _load(self, **kwargs: Any) -> list[Person]:
        """
        Load records from WikiTree into an in-memory database.

        :returns: A list of Person objects loaded from WikiTree.
        :rtype: list[Person]
        """
        query = self.context.get("query", "")
        people_data = self.context.get("people_data")
        client = self.context.get("client")
        ancestors_depth = int(self.context.get("ancestors", 0))

        if client is None:
            app_id = self.context.get("app_id", WikiTreeInterface.DEFAULT_APP_ID)
            client = WikiTreeInterface(app_id=app_id)

        raw_people: list[dict[str, Any]] = []

        if people_data is not None:
            if isinstance(people_data, dict):
                raw_people = list(people_data.values())
            elif isinstance(people_data, list):
                raw_people = people_data
        else:
            if self.is_wikitree_id(query):
                # Direct lookup by WikiTree ID
                if ancestors_depth > 0:
                    people_map = client.get_people(query, ancestors=ancestors_depth)
                    raw_people = list(people_map.values())
                else:
                    person_dict = client.get_person(query)
                    if person_dict:
                        raw_people = [person_dict]
            else:
                # Name search
                fn, ln = self._parse_query_names(query)
                matches = client.search_person(first_name=fn, last_name=ln, limit=10)
                for match in matches:
                    wt_id = match.get("Name")
                    if wt_id and self.is_wikitree_id(str(wt_id)):
                        full_prof = client.get_person(str(wt_id))
                        if full_prof:
                            raw_people.append(full_prof)
                        else:
                            raw_people.append(match)
                    else:
                        raw_people.append(match)

        # Expand raw_people with relatives if present in Parents or Spouses/Children
        existing_ids = {str(p.get("Id")) for p in raw_people if p.get("Id") is not None}
        existing_names = {str(p.get("Name")) for p in raw_people if p.get("Name")}

        for p in list(raw_people):
            parents_dict = p.get("Parents")
            if isinstance(parents_dict, dict):
                for par_id, par_data in parents_dict.items():
                    if isinstance(par_data, dict):
                        p_id = str(par_data.get("Id") or par_id)
                        p_name = str(par_data.get("Name") or "")
                        if p_id not in existing_ids and p_name not in existing_names:
                            raw_people.append(par_data)
                            if p_id:
                                existing_ids.add(p_id)
                            if p_name:
                                existing_names.add(p_name)

            children_val = p.get("Children")
            children_dict = children_val if isinstance(children_val, dict) else {}
            if isinstance(children_val, list):
                children_dict = {
                    str(i): ch
                    for i, ch in enumerate(children_val)
                    if isinstance(ch, dict)
                }
            for ch_id, ch_data in children_dict.items():
                if isinstance(ch_data, dict):
                    c_id = str(ch_data.get("Id") or ch_id)
                    c_name = str(ch_data.get("Name") or "")
                    if (c_id not in existing_ids or not c_id) and (
                        c_name not in existing_names or not c_name
                    ):
                        raw_people.append(ch_data)
                        if c_id:
                            existing_ids.add(c_id)
                        if c_name:
                            existing_names.add(c_name)

        if self.context.get("include_relatives") and client:
            missing_keys: list[str] = []
            for p in list(raw_people):
                spouses = p.get("Spouses")
                if isinstance(spouses, list):
                    for sp in spouses:
                        if isinstance(sp, dict):
                            sp_id = str(sp.get("Id") or sp.get("Name") or "")
                            if (
                                sp_id
                                and sp_id not in existing_ids
                                and sp_id not in existing_names
                                and sp_id not in missing_keys
                            ):
                                missing_keys.append(sp_id)
                children = p.get("Children")
                if isinstance(children, dict):
                    for ch_id, ch_data in children.items():
                        ch_key = str(
                            (ch_data.get("Name") if isinstance(ch_data, dict) else "")
                            or ch_id
                        )
                        if (
                            ch_key
                            and ch_key not in existing_ids
                            and ch_key not in existing_names
                            and ch_key not in missing_keys
                        ):
                            missing_keys.append(ch_key)
                elif isinstance(children, list):
                    for ch in children:
                        if isinstance(ch, dict):
                            ch_key = str(ch.get("Name") or ch.get("Id") or "")
                            if (
                                ch_key
                                and ch_key not in existing_ids
                                and ch_key not in existing_names
                                and ch_key not in missing_keys
                            ):
                                missing_keys.append(ch_key)

            if missing_keys:
                rel_people = client.get_people(missing_keys)
                for rk, rdata in rel_people.items():
                    rid = str(rdata.get("Id") or rk)
                    rname = str(rdata.get("Name") or "")
                    if rid not in existing_ids and rname not in existing_names:
                        raw_people.append(rdata)
                        if rid:
                            existing_ids.add(rid)
                        if rname:
                            existing_names.add(rname)

        source_db = make_database("sqlite")
        source_db.load(":memory:")
        # The tprefix setting (and the set_prefixes argument for it) only
        # exists in newer Gramps; as in GedGWizard, keep the database's
        # default prefixes when this version differs.
        try:
            source_db.set_prefixes(
                config.get("preferences.iprefix"),
                config.get("preferences.oprefix"),
                config.get("preferences.fprefix"),
                config.get("preferences.sprefix"),
                config.get("preferences.cprefix"),
                config.get("preferences.pprefix"),
                config.get("preferences.eprefix"),
                config.get("preferences.rprefix"),
                config.get("preferences.nprefix"),
                config.get("preferences.tprefix"),
                config.get("preferences.mprefix"),
            )
        except (AttributeError, TypeError):
            LOG.debug("ID prefixes not set: this Gramps version differs")

        place_cache: dict[str, str] = {}
        source_cache: dict[str, str] = {}
        media_cache: dict[str, str] = {}
        person_handle_map: dict[str, str] = {}  # wt_id or str(Id) -> person_handle

        def get_or_create_place(title: str, trans: DbTxn) -> str:
            clean = title.strip()
            if not clean:
                return ""
            cache_key = clean.lower()
            if cache_key in place_cache:
                return place_cache[cache_key]

            tokens = [p.strip() for p in clean.split(",") if p.strip()]
            if not tokens:
                return ""

            parent_handle = ""
            total = len(tokens)

            # Build from highest enclosing level (rightmost) down to locality (leftmost)
            for idx in range(total - 1, -1, -1):
                name = tokens[idx]
                current_title = ", ".join(tokens[idx:])
                ckey = current_title.lower()

                if ckey in place_cache:
                    parent_handle = place_cache[ckey]
                    continue

                p = Place()
                pname = PlaceName()
                pname.set_value(name)
                p.set_name(pname)
                p.set_title(current_title)

                level_from_top = total - 1 - idx
                p.set_type(self.determine_place_type(name, level_from_top, total))

                if parent_handle:
                    pref = PlaceRef()
                    pref.ref = parent_handle
                    p.add_placeref(pref)

                h = source_db.add_place(p, trans)
                place_cache[ckey] = h
                parent_handle = h

            place_cache[cache_key] = parent_handle
            return parent_handle

        with DbTxn(_("Load WikiTree Records"), source_db) as trans:
            repo_cache: dict[str, str] = {}

            def bare_tree_copy(obj: Any) -> Any:
                """
                Copy a tree object, keeping its handle, for the incoming
                database, so the merge reuses the tree's object instead of
                adding a duplicate. Its notes, media and tags stay behind.
                """
                duplicate = copy.deepcopy(obj)
                for setter in ("set_note_list", "set_media_list", "set_tag_list"):
                    if hasattr(duplicate, setter):
                        getattr(duplicate, setter)([])
                if hasattr(duplicate, "set_reporef_list"):
                    duplicate.set_reporef_list([])
                return duplicate

            def tree_repository(
                name: str, aliases: tuple[str, ...], trans: DbTxn
            ) -> str:
                """Return the repository handle for name, reusing the tree's."""
                key = repository_norm(name)
                if key in repo_cache:
                    return repo_cache[key]
                wanted = {repository_norm(n) for n in (name,) + tuple(aliases) if n}
                found = None
                for t_repo in self.db.iter_repositories():
                    if repository_norm(str(t_repo.get_name() or "")) in wanted:
                        found = t_repo
                        break
                if found is not None:
                    reused = bare_tree_copy(found)
                    source_db.add_repository(reused, trans)
                    handle = reused.get_handle()
                else:
                    new_repo = Repository()
                    new_repo.set_name(name)
                    new_repo.set_type(RepositoryType(RepositoryType.WEBSITE))
                    handle = source_db.add_repository(new_repo, trans)
                repo_cache[key] = handle
                return handle

            def tree_source(
                title: str, author: str, pubinfo: str, repo_h: str, trans: DbTxn
            ) -> str:
                """
                Return the source handle for title, reusing the tree's
                source when exactly one has that title.
                """
                key = " ".join(title.split()).casefold()
                if key in source_cache:
                    return source_cache[key]
                same = [
                    t_src
                    for t_src in self.db.iter_sources()
                    if " ".join(str(t_src.get_title() or "").split()).casefold() == key
                ]
                if len(same) == 1:
                    reused = bare_tree_copy(same[0])
                    source_db.add_source(reused, trans)
                    handle = reused.get_handle()
                else:
                    new_src = Source()
                    new_src.set_title(title)
                    if author:
                        new_src.set_author(author)
                    if pubinfo:
                        new_src.set_publication_info(pubinfo)
                    if repo_h:
                        r_ref = RepoRef()
                        r_ref.ref = repo_h
                        new_src.add_repo_reference(r_ref)
                    handle = source_db.add_source(new_src, trans)
                source_cache[key] = handle
                return handle

            def wikitree_media(
                url: str,
                description: str,
                trans: DbTxn,
                dimensions: str = "",
            ) -> str:
                """
                Return the media handle for a WikiTree photo address: the
                tree's copy when a tree photo came from that address
                (WIKITREE_URL_ATTRIBUTE), otherwise a new media object
                linked by the address (downloaded after the merge).
                """
                cached = media_cache.get(url)
                if cached:
                    return cached
                for t_media in self.db.iter_media():
                    if any(
                        str(a.get_type()) == WIKITREE_URL_ATTRIBUTE
                        and a.get_value() == url
                        for a in t_media.get_attribute_list()
                    ):
                        reused = bare_tree_copy(t_media)
                        source_db.add_media(reused, trans)
                        media_cache[url] = reused.get_handle()
                        return media_cache[url]
                new_media = Media()
                new_media.set_path(url)
                new_media.set_description(description)
                mime = mimetypes.guess_type(urlparse(url).path)[0]
                new_media.set_mime_type(mime or "image/jpeg")
                url_attr = Attribute()
                url_attr.set_type(AttributeType(WIKITREE_URL_ATTRIBUTE))
                url_attr.set_value(url)
                new_media.add_attribute(url_attr)
                if dimensions:
                    dim_attr = Attribute()
                    dim_attr.set_type(AttributeType(_("Dimensions")))
                    dim_attr.set_value(dimensions)
                    new_media.add_attribute(dim_attr)
                media_cache[url] = source_db.add_media(new_media, trans)
                return media_cache[url]

            # 1. The WikiTree repository and one collection-level source for
            # every profile (the profile ID goes in the citation page).
            repo_handle = tree_repository(
                WIKITREE_REPOSITORY_NAME, ("WikiTree",), trans
            )
            source_handle = tree_source(
                WIKITREE_SOURCE_TITLE,
                _("WikiTree Community"),
                "https://www.wikitree.com",
                repo_handle,
                trans,
            )

            # 3. Create Person records
            for pdata in raw_people:
                wt_key = str(pdata.get("Name") or "")
                num_id = str(pdata.get("Id") or "")
                first_name = str(pdata.get("FirstName") or "")
                middle_name = str(pdata.get("MiddleName") or "")
                middle_initial = str(pdata.get("MiddleInitial") or "")
                last_name_birth = str(
                    pdata.get("LastNameBirth") or pdata.get("LastNameAtBirth") or ""
                )
                last_name_current = str(pdata.get("LastNameCurrent") or "")
                last_name_other = str(pdata.get("LastNameOther") or "")
                prefix = str(pdata.get("Prefix") or "")
                suffix = str(pdata.get("Suffix") or "")
                nicknames = str(pdata.get("Nicknames") or "")
                real_name = str(
                    pdata.get("RealName") or pdata.get("ColloquialName") or ""
                ).strip()

                given = first_name
                if middle_name and middle_name not in given:
                    given = f"{given} {middle_name}".strip()
                elif middle_initial and middle_initial not in given:
                    given = f"{given} {middle_initial}.".strip()

                if not given and real_name:
                    given = real_name

                surname_val = last_name_birth or last_name_current

                person = Person()
                name_obj = Name()
                name_obj.set_first_name(given)
                if last_name_birth:
                    name_obj.set_type(NameType(NameType.BIRTH))
                if surname_val:
                    surn_obj = Surname()
                    surn_obj.set_surname(surname_val)
                    name_obj.add_surname(surn_obj)
                if prefix:
                    name_obj.set_title(prefix)
                if suffix:
                    name_obj.set_suffix(suffix)
                if nicknames:
                    name_obj.set_nick_name(nicknames)

                # Set call name if RealName/ColloquialName provided
                if real_name:
                    if real_name != given and real_name != first_name:
                        name_obj.set_call_name(real_name)
                    if not nicknames and real_name != given and real_name != first_name:
                        name_obj.set_nick_name(real_name)

                person.set_primary_name(name_obj)

                # Alternate name if current surname differs from birth surname
                if (
                    last_name_current
                    and last_name_birth
                    and last_name_current != last_name_birth
                ):
                    alt_name = Name()
                    alt_name.set_type(NameType(NameType.MARRIED))
                    alt_name.set_first_name(given)
                    alt_surn = Surname()
                    alt_surn.set_surname(last_name_current)
                    alt_name.add_surname(alt_surn)
                    if prefix:
                        alt_name.set_title(prefix)
                    if suffix:
                        alt_name.set_suffix(suffix)
                    person.add_alternate_name(alt_name)

                # Alternate names for LastNameOther (e.g. prior married names, aliases)
                if last_name_other:
                    other_surnames = [
                        s.strip()
                        for s in re.split(r"[,;/]+", last_name_other)
                        if s.strip()
                    ]
                    for oth_surn in other_surnames:
                        if (
                            oth_surn
                            and oth_surn != last_name_birth
                            and oth_surn != last_name_current
                        ):
                            alt_other = Name()
                            alt_other.set_type(NameType(NameType.AKA))
                            alt_other.set_first_name(given)
                            alt_surn_oth = Surname()
                            alt_surn_oth.set_surname(oth_surn)
                            alt_other.add_surname(alt_surn_oth)
                            if prefix:
                                alt_other.set_title(prefix)
                            if suffix:
                                alt_other.set_suffix(suffix)
                            person.add_alternate_name(alt_other)

                # If RealName differs significantly from given name, also add an AKA alternate name
                if real_name and real_name != given and real_name != first_name:
                    alt_real = Name()
                    alt_real.set_type(NameType(NameType.AKA))
                    alt_real.set_first_name(real_name)
                    if surname_val:
                        alt_s = Surname()
                        alt_s.set_surname(surname_val)
                        alt_real.add_surname(alt_s)
                    if prefix:
                        alt_real.set_title(prefix)
                    if suffix:
                        alt_real.set_suffix(suffix)
                    person.add_alternate_name(alt_real)

                # Gender
                gender_str = str(pdata.get("Gender") or "").strip().lower()
                if gender_str == "male":
                    person.set_gender(Person.MALE)
                elif gender_str == "female":
                    person.set_gender(Person.FEMALE)
                else:
                    person.set_gender(Person.UNKNOWN)

                # Privacy & Living Status
                privacy_val = pdata.get("Privacy")
                is_private = pdata.get("Privacy_IsPrivate")
                if is_private is True or (
                    isinstance(privacy_val, (int, str))
                    and str(privacy_val).isdigit()
                    and int(privacy_val) < 50
                ):
                    person.set_privacy(True)

                is_living_raw = (
                    pdata.get("IsLiving")
                    if pdata.get("IsLiving") is not None
                    else pdata.get("is_living")
                )
                is_living: bool | None = None
                if is_living_raw is not None:
                    try:
                        is_living = int(is_living_raw) == 1
                    except (ValueError, TypeError):
                        is_living = bool(is_living_raw)

                if is_living is True:
                    liv_attr = Attribute()
                    liv_attr.set_type(AttributeType(_("Living Status")))
                    liv_attr.set_value(_("Living"))
                    person.add_attribute(liv_attr)

                touched_raw = str(pdata.get("Touched") or "").strip()
                manager_raw = str(pdata.get("Manager") or "").strip()
                created_raw = str(pdata.get("Created") or "").strip()

                # WikiTree ID custom attribute and Internet Web Home URL
                if wt_key:
                    wt_attr = Attribute()
                    wt_attr.set_type(AttributeType("WikiTree ID"))
                    wt_attr.set_value(wt_key)
                    person.add_attribute(wt_attr)

                    wt_url = Url()
                    wt_url.set_path(f"https://www.wikitree.com/wiki/{wt_key}")
                    wt_url.set_type(UrlType(UrlType.WEB_HOME))
                    wt_url.set_description(_("WikiTree Profile"))
                    person.add_url(wt_url)

                # Synchronization metadata attributes
                if touched_raw:
                    touched_formatted = self.format_wikitree_timestamp(touched_raw)
                    touch_attr = Attribute()
                    touch_attr.set_type(AttributeType("WikiTree Touched"))
                    touch_attr.set_value(touched_formatted)
                    person.add_attribute(touch_attr)

                if manager_raw:
                    mgr_attr = Attribute()
                    mgr_attr.set_type(AttributeType("WikiTree Manager"))
                    mgr_attr.set_value(manager_raw)
                    person.add_attribute(mgr_attr)

                # Citation
                citation = Citation()
                citation.set_reference_handle(source_handle)
                citation.set_page(f"WikiTree: {wt_key}" if wt_key else f"ID: {num_id}")
                cit_lines = []
                if wt_key:
                    cit_lines.append(f"URL: https://www.wikitree.com/wiki/{wt_key}")
                if touched_raw:
                    cit_lines.append(
                        f"Last Modified: {self.format_wikitree_timestamp(touched_raw)}"
                    )
                if manager_raw:
                    cit_lines.append(f"Profile Manager ID: {manager_raw}")

                if cit_lines:
                    cit_note = Note()
                    cit_note.set_type(NoteType(NoteType.CITATION))
                    cit_note.set("\n".join(cit_lines))
                    cit_note_handle = source_db.add_note(cit_note, trans)
                    citation.add_note(cit_note_handle)

                # Primary Photo / Media. PhotoData's "path" is the
                # full-size image ("url" and "file" are the 75px thumbnail);
                # without it the full-size address is worked out from the
                # Photo file name.
                photo_file = str(pdata.get("Photo") or "").strip()
                photo_data = pdata.get("PhotoData")
                primary_media_url = ""
                orig_w = ""
                orig_h = ""

                if isinstance(photo_data, dict):
                    photo_path = str(photo_data.get("path") or "").strip()
                    if photo_path:
                        primary_media_url = (
                            f"https://www.wikitree.com{photo_path}"
                            if photo_path.startswith("/")
                            else photo_path
                        )
                    orig_w = str(
                        photo_data.get("orig_width") or photo_data.get("width") or ""
                    )
                    orig_h = str(
                        photo_data.get("orig_height") or photo_data.get("height") or ""
                    )

                if not primary_media_url and photo_file:
                    primary_media_url = wikitree_image_url(photo_file)

                if primary_media_url:
                    primary_media_h = wikitree_media(
                        primary_media_url,
                        wikitree_media_description(given, surname_val),
                        trans,
                        f"{orig_w}x{orig_h}" if orig_w and orig_h else "",
                    )

                    # Attach directly to Person (primary photo / avatar)
                    p_mref = MediaRef()
                    p_mref.ref = primary_media_h
                    person.add_media_reference(p_mref)

                    # Also attach to Citation
                    c_mref = MediaRef()
                    c_mref.ref = primary_media_h
                    citation.add_media_reference(c_mref)

                citation.set_date_object(Today())
                cit_handle = source_db.add_citation(citation, trans)
                person.add_citation(cit_handle)

                # Birth Event
                birth_status = str(
                    pdata.get("BirthDateStatus")
                    or (pdata.get("DataStatus") or {}).get("BirthDate")
                    or ""
                )
                birth_decade = str(pdata.get("BirthDateDecade") or "")
                b_date_obj = self.wikitree_date_to_gramps(
                    pdata.get("BirthDate"), birth_status, birth_decade
                )
                birth_loc = str(pdata.get("BirthLocation") or "").strip()
                b_ref = None
                if not b_date_obj.is_empty() or birth_loc:
                    b_evt = Event()
                    b_evt.set_type(EventType(EventType.BIRTH))
                    if not b_date_obj.is_empty():
                        b_evt.set_date_object(b_date_obj)
                    if birth_loc:
                        p_h = get_or_create_place(birth_loc, trans)
                        b_evt.set_place_handle(p_h)
                    b_evt.add_citation(cit_handle)
                    b_h = source_db.add_event(b_evt, trans)
                    b_ref = EventRef()
                    b_ref.ref = b_h
                    person.set_birth_ref(b_ref)

                # Death Event
                death_status = str(
                    pdata.get("DeathDateStatus")
                    or (pdata.get("DataStatus") or {}).get("DeathDate")
                    or ""
                )
                death_decade = str(pdata.get("DeathDateDecade") or "")
                d_date_obj = self.wikitree_date_to_gramps(
                    pdata.get("DeathDate"), death_status, death_decade
                )
                death_loc = str(pdata.get("DeathLocation") or "").strip()
                d_ref = None
                if not d_date_obj.is_empty() or death_loc:
                    d_evt = Event()
                    d_evt.set_type(EventType(EventType.DEATH))
                    if not d_date_obj.is_empty():
                        d_evt.set_date_object(d_date_obj)
                    if death_loc:
                        p_h = get_or_create_place(death_loc, trans)
                        d_evt.set_place_handle(p_h)
                    d_evt.add_citation(cit_handle)
                    d_h = source_db.add_event(d_evt, trans)
                    d_ref = EventRef()
                    d_ref.ref = d_h
                    person.set_death_ref(d_ref)
                elif is_living is False and d_date_obj.is_empty() and not death_loc:
                    d_evt = Event()
                    d_evt.set_type(EventType(EventType.DEATH))
                    d_evt.add_citation(cit_handle)
                    d_h = source_db.add_event(d_evt, trans)
                    d_ref = EventRef()
                    d_ref.ref = d_h
                    person.set_death_ref(d_ref)

                # Burial Event (from Categories or Bio Cemetery)
                cemetery_name = ""
                categories_val = pdata.get("Categories") or []
                if isinstance(categories_val, list):
                    for cat in categories_val:
                        cat_clean = str(cat).replace("_", " ").strip()
                        if any(
                            kw in cat_clean.lower()
                            for kw in (
                                "cemetery",
                                "burial ground",
                                "burying ground",
                                "memorial park",
                                "churchyard",
                            )
                        ):
                            cemetery_name = cat_clean
                            break

                raw_bio = str(pdata.get("Bio") or pdata.get("bio") or "").strip()
                if not cemetery_name and raw_bio:
                    cat_m = re.search(
                        r"\[\[Category:\s*([^\]]*(?:cemetery|burial ground|burying ground|memorial park|churchyard)[^\]]*)\]\]",
                        raw_bio,
                        re.IGNORECASE,
                    )
                    if cat_m:
                        cemetery_name = cat_m.group(1).replace("_", " ").strip()

                if cemetery_name:
                    bur_evt = Event()
                    bur_evt.set_type(EventType(EventType.BURIAL))
                    cem_p_h = get_or_create_place(cemetery_name, trans)
                    bur_evt.set_place_handle(cem_p_h)
                    bur_evt.add_citation(cit_handle)
                    bur_h = source_db.add_event(bur_evt, trans)
                    bur_ref = EventRef()
                    bur_ref.ref = bur_h
                    person.add_event_ref(bur_ref)

                # Biography & Sources from Bio Text
                if raw_bio:
                    # 1. Extract and create structured external Sources & Citations
                    bio_sources = self.parse_bio_sources(raw_bio)
                    for src_info in bio_sources:
                        s_raw = src_info.get("text") or ""
                        if not s_raw:
                            continue
                        s_cleaned = self.clean_source_text(s_raw)
                        if not s_cleaned:
                            continue
                        s_info = describe_bio_source(s_cleaned, s_raw)
                        s_repo_h = tree_repository(
                            s_info["repository"],
                            tuple(
                                a for a in s_info["repository_aliases"].split("|") if a
                            ),
                            trans,
                        )
                        s_h = tree_source(
                            s_info["title"],
                            s_info["author"],
                            s_info["url"],
                            s_repo_h,
                            trans,
                        )

                        cit_obj = Citation()
                        cit_obj.set_reference_handle(s_h)
                        # The citation date is when the record was seen
                        # ("accessed ..."), not the day of this merge.
                        if s_info["accessed"]:
                            try:
                                acc_date = dateparser.parse(s_info["accessed"])
                                if acc_date.get_year() > 0:
                                    cit_obj.set_date_object(acc_date)
                            except Exception:  # pylint: disable=broad-except
                                pass

                        s_page = s_info["page"]
                        if s_info["fs_id"]:
                            s_page = _("entry for %(name)s, person ID %(id)s") % {
                                "name": f"{given} {surname_val}".strip(),
                                "id": s_info["fs_id"],
                            }
                            if not any(
                                str(a.get_type()) == "_FSFTID"
                                for a in person.get_attribute_list()
                            ):
                                fs_attr = Attribute()
                                fs_attr.set_type(AttributeType("_FSFTID"))
                                fs_attr.set_value(s_info["fs_id"])
                                person.add_attribute(fs_attr)
                        if s_page:
                            cit_obj.set_page(s_page)

                        c_note = Note()
                        c_note.set_type(NoteType(NoteType.CITATION))
                        c_note.set(s_cleaned)
                        c_note_h = source_db.add_note(c_note, trans)
                        cit_obj.add_note(c_note_h)

                        ext_cit_h = source_db.add_citation(cit_obj, trans)
                        person.add_citation(ext_cit_h)

                        ctx = (src_info.get("context") or "").lower()
                        if b_ref and any(
                            kw in ctx
                            for kw in (
                                "born",
                                "birth",
                                "baptism",
                                "christen",
                                "baptized",
                            )
                        ):
                            b_ev = source_db.get_event_from_handle(b_ref.ref)
                            if b_ev and ext_cit_h not in b_ev.get_citation_list():
                                b_ev.add_citation(ext_cit_h)
                                source_db.commit_event(b_ev, trans)

                        if d_ref and any(
                            kw in ctx
                            for kw in (
                                "died",
                                "death",
                                "burial",
                                "buried",
                                "cemetery",
                                "grave",
                                "killed",
                                "probate",
                                "will",
                            )
                        ):
                            d_ev = source_db.get_event_from_handle(d_ref.ref)
                            if d_ev and ext_cit_h not in d_ev.get_citation_list():
                                d_ev.add_citation(ext_cit_h)
                                source_db.commit_event(d_ev, trans)

                    # 2. Clean narrative biography text for Person Note
                    clean_bio = self.clean_bio_text(raw_bio)
                    if clean_bio:
                        note = Note()
                        note.set_type(NoteType(NoteType.GENERAL))
                        note.set(clean_bio)
                        note_h = source_db.add_note(note, trans)
                        person.add_note(note_h)

                # 3. Process structured templates and stickers
                templates_data = pdata.get("Templates")
                if not templates_data and raw_bio:
                    templates_data = self.parse_bio_templates(raw_bio)
                if templates_data and isinstance(templates_data, list):
                    self.process_templates(person, templates_data, source_db, trans)

                # 4. Extract gallery images from bio text: [[Image:filename|caption]]
                if raw_bio:
                    for img_m in re.finditer(
                        r"\[\[(?:Image|File):([^\s|\]]+)(?:\|([^\]]+))?\]\]",
                        raw_bio,
                        re.IGNORECASE,
                    ):
                        img_file = img_m.group(1).strip()
                        raw_caption = img_m.group(2) or ""
                        clean_parts = [
                            p.strip()
                            for p in raw_caption.split("|")
                            if not re.match(
                                r"^\d+px$|^thumb$|^right$|^left$|^center$|^none$",
                                p.strip(),
                                re.IGNORECASE,
                            )
                        ]
                        img_desc = wikitree_media_description(
                            given, surname_val, " - ".join(clean_parts)
                        )
                        img_url = wikitree_image_url(img_file)

                        if not img_url or img_url == primary_media_url:
                            continue

                        g_media_h = wikitree_media(img_url, img_desc, trans)

                        if not any(r.ref == g_media_h for r in person.get_media_list()):
                            g_mref = MediaRef()
                            g_mref.ref = g_media_h
                            person.add_media_reference(g_mref)

                p_handle = source_db.add_person(person, trans)
                if wt_key:
                    person_handle_map[wt_key] = p_handle
                if num_id:
                    person_handle_map[num_id] = p_handle

            # 4. Link family relationships (parents, children, spouses)
            def get_or_create_family(
                father_h: str | None, mother_h: str | None
            ) -> Family:
                """Find an existing Family for father/mother or create a new one."""
                for existing_fam_h in source_db.iter_family_handles():
                    fam = source_db.get_family_from_handle(existing_fam_h)
                    if not fam:
                        continue
                    cur_f = fam.get_father_handle()
                    cur_m = fam.get_mother_handle()
                    if father_h and mother_h:
                        if (cur_f == father_h and cur_m == mother_h) or (
                            cur_f == mother_h and cur_m == father_h
                        ):
                            return fam
                    elif father_h and not mother_h:
                        if cur_f == father_h and not cur_m:
                            return fam
                    elif mother_h and not father_h:
                        if cur_m == mother_h and not cur_f:
                            return fam

                fam = Family()
                if father_h:
                    fam.set_father_handle(father_h)
                if mother_h:
                    fam.set_mother_handle(mother_h)
                fam_h = source_db.add_family(fam, trans)
                fam.handle = fam_h

                if father_h:
                    f_person = source_db.get_person_from_handle(father_h)
                    if f_person and fam_h not in f_person.get_family_handle_list():
                        f_person.add_family_handle(fam_h)
                        source_db.commit_person(f_person, trans)

                if mother_h:
                    m_person = source_db.get_person_from_handle(mother_h)
                    if m_person and fam_h not in m_person.get_family_handle_list():
                        m_person.add_family_handle(fam_h)
                        source_db.commit_person(m_person, trans)

                return fam

            def status_to_relation(status_val: str) -> ChildRefType:
                """Convert WikiTree relationship status to ChildRefType."""
                st = (status_val or "").strip().lower()
                if st in ("non-biological", "adopted"):
                    return ChildRefType(ChildRefType.ADOPTED)
                if st in ("foster",):
                    return ChildRefType(ChildRefType.FOSTER)
                if st in ("stepchild", "step"):
                    return ChildRefType(ChildRefType.STEPCHILD)
                return ChildRefType(ChildRefType.BIRTH)

            # 4a. Link spouses
            for pdata in raw_people:
                wt_key = str(pdata.get("Name") or "")
                num_id = str(pdata.get("Id") or "")
                p_handle = person_handle_map.get(wt_key) or person_handle_map.get(
                    num_id
                )
                if not p_handle:
                    continue

                spouses = pdata.get("Spouses")
                if isinstance(spouses, list):
                    for spouse_item in spouses:
                        if not isinstance(spouse_item, dict):
                            continue
                        s_key = str(spouse_item.get("Name") or "")
                        s_id = str(spouse_item.get("Id") or "")
                        s_handle = person_handle_map.get(
                            s_key
                        ) or person_handle_map.get(s_id)
                        if not s_handle or s_handle == p_handle:
                            continue

                        cur_p = source_db.get_person_from_handle(p_handle)
                        is_father = cur_p.get_gender() == Person.MALE
                        spouse_f_h = p_handle if is_father else s_handle
                        spouse_m_h = s_handle if is_father else p_handle

                        fam = get_or_create_family(spouse_f_h, spouse_m_h)

                        if not fam.get_event_ref_list():
                            m_status = str(
                                spouse_item.get("MarriageDateStatus")
                                or (spouse_item.get("DataStatus") or {}).get(
                                    "MarriageDate"
                                )
                                or (spouse_item.get("data_status") or {}).get(
                                    "marriage_date"
                                )
                                or ""
                            )
                            m_date_obj = self.wikitree_date_to_gramps(
                                spouse_item.get("MarriageDate")
                                or spouse_item.get("marriage_date"),
                                m_status,
                            )
                            m_loc = str(
                                spouse_item.get("MarriageLocation")
                                or spouse_item.get("marriage_location")
                                or ""
                            ).strip()
                            if not m_date_obj.is_empty() or m_loc:
                                m_evt = Event()
                                m_evt.set_type(EventType(EventType.MARRIAGE))
                                if not m_date_obj.is_empty():
                                    m_evt.set_date_object(m_date_obj)
                                if m_loc:
                                    m_evt.set_place_handle(
                                        get_or_create_place(m_loc, trans)
                                    )
                                m_handle = source_db.add_event(m_evt, trans)
                                m_ref = EventRef()
                                m_ref.ref = m_handle
                                fam.add_event_ref(m_ref)
                                source_db.commit_family(fam, trans)

                        # Check for MarriageEndDate (Divorce)
                        m_end_raw = self._clean_date_str(
                            str(
                                spouse_item.get("MarriageEndDate")
                                or spouse_item.get("marriage_end_date")
                                or ""
                            )
                        )
                        if m_end_raw:
                            m_end_status = str(
                                spouse_item.get("MarriageEndDateStatus")
                                or (spouse_item.get("DataStatus") or {}).get(
                                    "MarriageEndDate"
                                )
                                or (spouse_item.get("data_status") or {}).get(
                                    "marriage_end_date"
                                )
                                or ""
                            )
                            div_date_obj = self.wikitree_date_to_gramps(
                                m_end_raw, m_end_status
                            )
                            has_div = any(
                                source_db.get_event_from_handle(r.ref).get_type()
                                == EventType.DIVORCE
                                for r in fam.get_event_ref_list()
                                if source_db.get_event_from_handle(r.ref)
                            )
                            if not has_div:
                                div_evt = Event()
                                div_evt.set_type(EventType(EventType.DIVORCE))
                                if not div_date_obj.is_empty():
                                    div_evt.set_date_object(div_date_obj)
                                div_h = source_db.add_event(div_evt, trans)
                                div_ref = EventRef()
                                div_ref.ref = div_h
                                fam.add_event_ref(div_ref)
                                source_db.commit_family(fam, trans)

            # 4b. Link parents and children via ChildRef
            for pdata in raw_people:
                wt_key = str(pdata.get("Name") or "")
                num_id = str(pdata.get("Id") or "")
                child_h = person_handle_map.get(wt_key) or person_handle_map.get(num_id)
                if not child_h:
                    continue

                child_p = source_db.get_person_from_handle(child_h)
                if not child_p:
                    continue

                f_h: str | None = None
                m_h: str | None = None

                fat_val = pdata.get("Father")
                mot_val = pdata.get("Mother")
                if fat_val:
                    f_h = person_handle_map.get(str(fat_val))
                if mot_val:
                    m_h = person_handle_map.get(str(mot_val))

                parents_val = pdata.get("Parents")
                if isinstance(parents_val, dict):
                    for par_id, par_data in parents_val.items():
                        if isinstance(par_data, dict):
                            pk = str(
                                par_data.get("Name") or par_data.get("Id") or par_id
                            )
                            ph = person_handle_map.get(pk) or person_handle_map.get(
                                str(par_id)
                            )
                            if ph:
                                g = str(par_data.get("Gender") or "").lower()
                                if g == "male" and not f_h:
                                    f_h = ph
                                elif g == "female" and not m_h:
                                    m_h = ph

                if f_h or m_h:
                    fam = get_or_create_family(f_h, m_h)
                    if not any(cr.ref == child_h for cr in fam.get_child_ref_list()):
                        data_status = pdata.get("DataStatus") or {}
                        f_status = str(data_status.get("Father") or "").strip()
                        m_status = str(data_status.get("Mother") or "").strip()

                        child_ref = ChildRef()
                        child_ref.ref = child_h
                        child_ref.set_father_relation(status_to_relation(f_status))
                        child_ref.set_mother_relation(status_to_relation(m_status))

                        notes_to_add: list[str] = []
                        if f_status == "20" and m_status == "20":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Paternal and maternal relationships are confirmed with DNA."
                                )
                            )
                        elif f_status == "20":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Paternal relationship is confirmed with DNA."
                                )
                            )
                        elif m_status == "20":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Maternal relationship is confirmed with DNA."
                                )
                            )

                        if f_status == "10" and m_status == "10":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Paternal and maternal relationships are confirmed with sources."
                                )
                            )
                        elif f_status == "10":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Paternal relationship is confirmed with sources."
                                )
                            )
                        elif m_status == "10":
                            notes_to_add.append(
                                _(
                                    "WikiTree: Maternal relationship is confirmed with sources."
                                )
                            )

                        for note_text in notes_to_add:
                            note = Note()
                            note.set_type(NoteType(NoteType.GENERAL))
                            note.set(note_text)
                            note_h = source_db.add_note(note, trans)
                            child_ref.add_note(note_h)

                        fam.add_child_ref(child_ref)
                        source_db.commit_family(fam, trans)

                        if fam.handle not in child_p.get_parent_family_handle_list():
                            child_p.add_parent_family_handle(fam.handle)
                            source_db.commit_person(child_p, trans)

            # 4c. Link children from parent's Children list
            for pdata in raw_people:
                wt_key = str(pdata.get("Name") or "")
                num_id = str(pdata.get("Id") or "")
                parent_h = person_handle_map.get(wt_key) or person_handle_map.get(
                    num_id
                )
                if not parent_h:
                    continue

                parent_p = source_db.get_person_from_handle(parent_h)
                if not parent_p:
                    continue

                children = pdata.get("Children")
                children_list = []
                if isinstance(children, dict):
                    children_list = list(children.values())
                elif isinstance(children, list):
                    children_list = children

                is_fat = parent_p.get_gender() == Person.MALE
                for ch_data in children_list:
                    if not isinstance(ch_data, dict):
                        continue
                    c_key = str(ch_data.get("Name") or "")
                    c_id = str(ch_data.get("Id") or "")
                    c_h = person_handle_map.get(c_key) or person_handle_map.get(c_id)
                    if not c_h or c_h == parent_h:
                        continue

                    c_p = source_db.get_person_from_handle(c_h)
                    if not c_p:
                        continue

                    already_linked = False
                    for pf_h in c_p.get_parent_family_handle_list():
                        pfam = source_db.get_family_from_handle(pf_h)
                        if pfam and (
                            (is_fat and pfam.get_father_handle() == parent_h)
                            or (not is_fat and pfam.get_mother_handle() == parent_h)
                        ):
                            already_linked = True
                            break

                    if not already_linked:
                        p_f_h = parent_h if is_fat else None
                        p_m_h = None if is_fat else parent_h
                        fam = get_or_create_family(p_f_h, p_m_h)
                        if not any(cr.ref == c_h for cr in fam.get_child_ref_list()):
                            cr = ChildRef()
                            cr.ref = c_h
                            cr.set_father_relation(ChildRefType(ChildRefType.BIRTH))
                            cr.set_mother_relation(ChildRefType(ChildRefType.BIRTH))
                            fam.add_child_ref(cr)
                            source_db.commit_family(fam, trans)
                        if fam.handle not in c_p.get_parent_family_handle_list():
                            c_p.add_parent_family_handle(fam.handle)
                            source_db.commit_person(c_p, trans)

        self.context["source_db"] = source_db
        display_name = f"WikiTree: {query}" if query else _("WikiTree")
        self.context["source_title"] = display_name
        self.context["gedcom_path"] = display_name

        people: list[Person] = []
        for handle in source_db.iter_person_handles():
            p = source_db.get_person_from_handle(handle)
            if p:
                people.append(p)

        return people

    def download_person_media(self, person_handle: str) -> dict[str, Any]:
        """
        Download a person's WikiTree photos (media still linked by a
        wikitree.com address) and name them like Media Fix does.

        Each photo is downloaded into <media base path>/WikiTree/, then moved
        to the base media path under its Media Fix name (a different file
        already there is never replaced; see place_file) and its media
        object is pointed at the file. A photo that cannot be downloaded
        keeps its web address.

        :param person_handle: The person in the family tree.
        :returns: Counts: downloaded, failed (addresses).
        """
        found: dict[str, Any] = {"downloaded": 0, "failed": []}
        person = self.db.get_person_from_handle(person_handle)
        if person is None:
            return found
        client = self.context.get("client") or WikiTreeInterface(
            app_id=str(self.context.get("app_id") or WikiTreeInterface.DEFAULT_APP_ID)
        )
        base = media_path(self.db)
        for media_ref in person.get_media_list():
            media = self.db.get_media_from_handle(media_ref.ref)
            if media is None or not is_wikitree_url(media.get_path()):
                continue
            url = media.get_path()
            file_name = os.path.basename(urlparse(url).path) or "photo.jpg"
            cache = os.path.join(base, WIKITREE_MEDIA_FOLDER, file_name)
            if not client.download_image(url, cache):
                found["failed"].append(url)
                continue
            ext = os.path.splitext(file_name)[1] or ".jpg"
            final = place_file(
                cache,
                os.path.join(base, media_fix_filename(self.db, person, media, ext)),
            )
            with DbTxn(_("Download WikiTree photo"), self.db) as trans:
                media.set_path(relative_path(final, base))
                media.set_mime_type(
                    mimetypes.guess_type(final)[0]
                    or media.get_mime_type()
                    or "image/jpeg"
                )
                media.set_checksum(create_checksum(final))
                if not any(
                    str(a.get_type()) == WIKITREE_URL_ATTRIBUTE
                    for a in media.get_attribute_list()
                ):
                    url_attr = Attribute()
                    url_attr.set_type(AttributeType(WIKITREE_URL_ATTRIBUTE))
                    url_attr.set_value(url)
                    media.add_attribute(url_attr)
                self.db.commit_media(media, trans)
            found["downloaded"] += 1
        return found

    def _apply(self, **kwargs: Any) -> bool:
        """
        Apply resolutions for WikiTree merge, ensuring WikiTree ID is stored
        on the target person unless explicitly rejected.

        :param kwargs: Arguments passed to GedGWizard._apply.
        :returns: True if apply was successful.
        :rtype: bool
        """
        resolutions = kwargs.get("resolutions")
        target_person_handle = kwargs.get("target_person_handle")
        source_person_handle = kwargs.get("source_person_handle")

        # The WikiTree ID is stored unless explicitly rejected. The shared
        # GedGWizard._apply does not know the "wtid" resolution, so it is
        # taken out here and handled after the shared apply.
        store_wtid = True
        if resolutions is not None:
            store_wtid = resolutions.pop("wtid", "source") == "source"

        applied = super()._apply(**kwargs)

        if applied and self.context.get("download_media"):
            merged_handle = target_person_handle or self.context.get(
                "person_map", {}
            ).get(source_person_handle)
            if merged_handle:
                self.context["media_download"] = self.download_person_media(
                    merged_handle
                )

        if applied and target_person_handle and source_person_handle:
            source_db = self.context.get("source_db")
            if source_db:
                s_p = source_db.get_person_from_handle(source_person_handle)
                t_p = self.db.get_person_from_handle(target_person_handle)
                if s_p and t_p and store_wtid:
                    wt_id = get_wikitree_id(s_p)
                    if wt_id:
                        with DbTxn(_("Store WikiTree ID"), self.db) as trans:
                            if store_wikitree_id(t_p, wt_id):
                                self.db.commit_person(t_p, trans)
                        t_p = self.db.get_person_from_handle(target_person_handle)
                if s_p and t_p:
                    metadata_attrs = {}
                    for a in s_p.get_attribute_list():
                        if str(a.get_type()) in (
                            "WikiTree Touched",
                            "WikiTree Manager",
                        ):
                            metadata_attrs[str(a.get_type())] = str(a.get_value())

                    if metadata_attrs:
                        with DbTxn(
                            _("Update WikiTree Synchronization Metadata"),
                            self.db,
                        ) as trans:
                            for m_type, m_val in metadata_attrs.items():
                                found = False
                                for ta in t_p.get_attribute_list():
                                    if str(ta.get_type()) == m_type:
                                        ta.set_value(m_val)
                                        found = True
                                        break
                                if not found:
                                    new_attr = Attribute()
                                    new_attr.set_type(AttributeType(m_type))
                                    new_attr.set_value(m_val)
                                    t_p.add_attribute(new_attr)
                            self.db.commit_person(t_p, trans)

        return applied
