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
Media file naming shared by the GWizard tools.

GWizard Media Fix names media files from a template of tokens
(``{ref_id}_{surname}_{given}-{doc_type}-{year}.{ext}`` by default), and
the record-source tools (NARA, WikiTree, ...) name the images they download
the same way, so a file they save is already where and what Media Fix would
make it. This module is that one naming: the template setting, the token
cleaning, the year and document type read from a description, the person
year used when a file has no date of its own, and moving a downloaded file
to its name without replacing a different file already there.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import hashlib
import logging
import os
import re
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.config import config
from gramps.gen.utils.db import get_birth_or_fallback, get_death_or_fallback
from gramps.gen.utils.file import create_checksum

LOG = logging.getLogger(__name__)

# -------------------------------------------------------------------------
#
# The filename template
#
# -------------------------------------------------------------------------
# Media Fix's Preferences setting. Registering it here as well as in Media
# Fix is harmless (a second register only sets the same default again), and
# lets a record-source tool read it when Media Fix is not loaded.
FILENAME_TEMPLATE_KEY = "preferences.gwizardmediafix-filename-template"
DEFAULT_FILENAME_TEMPLATE = "{ref_id}_{surname}_{given}-{doc_type}-{year}.{ext}"
config.register(FILENAME_TEMPLATE_KEY, DEFAULT_FILENAME_TEMPLATE)

# Longest file name (without the extension) a template may produce.
MAX_STEM_LEN = 85


def filename_template() -> str:
    """Return the filename template set in Media Fix's Preferences."""
    try:
        return str(config.get(FILENAME_TEMPLATE_KEY) or DEFAULT_FILENAME_TEMPLATE)
    except Exception:  # pylint: disable=broad-except
        return DEFAULT_FILENAME_TEMPLATE


# -------------------------------------------------------------------------
#
# Tokens
#
# -------------------------------------------------------------------------
def clean_token(val: Any) -> str:
    """Sanitize an individual token value to contain only alphanumeric characters, underscores, and hyphens."""
    if not val:
        return ""
    s = re.sub(r"[\s_]*-+[\s_]*", "-", str(val))
    clean = re.sub(r"[^\w\-]+", "_", s)
    clean = re.sub(r"_+", "_", clean)
    clean = re.sub(r"[-_]*-[_\s-]*", "-", clean)
    clean = re.sub(r"-+", "-", clean)
    return clean.strip("_-")


def extract_year_and_clean_doctype(
    doc_type: str, surname: str = "", given: str = ""
) -> tuple[str, str]:
    """Extract 4-digit document year and strip redundant person names from doc_type."""
    if not doc_type:
        return "", ""

    year = ""
    y_match = re.search(r"(?:^|[^\d])(1[5-9]\d{2}|20\d{2})(?:[^\d]|$)", doc_type)
    if y_match:
        year = y_match.group(1)
        doc_type = doc_type[: y_match.start(1)] + " " + doc_type[y_match.end(1) :]

    # Strip any leading 'Surname, Given -' pattern from doc_type
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


def format_standard_filename(
    template: str, context: dict[str, str], max_stem_len: int = MAX_STEM_LEN
) -> str:
    """
    Format and sanitize a filename using template tokens and context.

    The extension is ``context["ext"]``, or jpg when the context has none;
    an empty ``ext`` (a file without an extension) gives a name without one.
    """
    ext = clean_token(context.get("ext", "jpg")).lower()

    safe_context = {k: clean_token(v) for k, v in context.items() if k != "ext"}
    safe_context["ext"] = ext

    try:
        rendered = template.format(**safe_context)
    except (KeyError, ValueError, IndexError):
        rendered = f"{safe_context.get('ref_id', '')}_{safe_context.get('orig', 'media')}.{ext}"

    if "." in rendered:
        base, _ext = rendered.rsplit(".", 1)
    else:
        base = rendered

    base = re.sub(r"[\s_]*-+[\s_]*", "-", base)
    base = re.sub(r"[^\w\-]+", "_", base)
    base = re.sub(r"_+", "_", base)
    base = re.sub(r"[-_]*-[_\s-]*", "-", base)
    base = re.sub(r"-+", "-", base)
    base = base.strip("_-")

    if not base:
        base = safe_context.get("orig") or safe_context.get("id") or "media"
        base = clean_token(base) or "media"

    if len(base) > max_stem_len:
        base = base[:max_stem_len].rstrip("_-")

    return f"{base}.{ext}" if ext else base


def file_content_hash(path: str, length: int = 6) -> str:
    """Short, stable content hash of a file ("" if it cannot be read)."""
    try:
        digest = hashlib.sha1()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()[:length]
    except OSError:
        return ""


# -------------------------------------------------------------------------
#
# Naming a person's media
#
# -------------------------------------------------------------------------
def person_year(db: Any, person: Any) -> str:
    """
    Return the year used for a person's media without a date of its own:
    the birth (or its fallback), else the death (or its fallback), else the
    first dated event. '' when there is none.
    """
    if not person or not db:
        return ""
    try:
        for event in (
            get_birth_or_fallback(db, person),
            get_death_or_fallback(db, person),
        ):
            if (
                event
                and event.get_date_object()
                and event.get_date_object().get_year() > 0
            ):
                return str(event.get_date_object().get_year())
    except Exception:  # pylint: disable=broad-except
        pass
    if hasattr(person, "get_event_ref_list"):
        for eref in person.get_event_ref_list():
            if getattr(eref, "ref", None):
                try:
                    evt = db.get_event_from_handle(eref.ref)
                    if (
                        evt
                        and evt.get_date_object()
                        and evt.get_date_object().get_year() > 0
                    ):
                        return str(evt.get_date_object().get_year())
                except Exception:  # pylint: disable=broad-except
                    continue
    return ""


def person_media_filename(
    db: Any,
    person: Any,
    description: str,
    ext: str,
    year: int | str = "",
    media_id: str = "",
    orig: str = "",
    file_path: str = "",
    template: str | None = None,
) -> str:
    """
    Return the file name Media Fix gives a media object of ``person`` (its
    person-backlink naming).

    :param db: The database holding the person, for the person's year; may
        be None.
    :param person: The person the media is of; may be None (the name then
        starts with ``media_id``).
    :param description: The media description, e.g. "Smith, John - Census
        1920"; a year in it is the file's year.
    :param ext: The file extension, with or without the dot.
    :param year: The media's own date's year, used when the description
        names none; without either, the person's year (see person_year).
    :param media_id: The media object's Gramps ID ({id}).
    :param orig: The file's original name without the extension ({orig}).
    :param file_path: The file, for a template that uses {hash}.
    :param template: The template; Media Fix's setting when None.
    """
    tmpl = template or filename_template()
    surname = given = ref_id = ""
    if person is not None:
        name = person.get_primary_name()
        surname = str(name.get_surname() or "")
        given = str(name.get_first_name() or "")
        ref_id = str(person.get_gramps_id() or "")
    doc_type, found_year = extract_year_and_clean_doctype(
        description or "Photo", surname, given
    )
    the_year = found_year or (str(year) if year and str(year) != "0" else "")
    if not the_year:
        the_year = person_year(db, person)
    context = {
        "id": media_id,
        "desc": description,
        "orig": orig,
        "ext": (ext or "").lstrip(".").lower(),
        "ref_id": ref_id or media_id,
        "surname": surname,
        "given": given,
        "doc_type": doc_type or ("Photo" if surname else "Media"),
        "year": the_year,
        "assoc": "",
        "hash": file_content_hash(file_path) if file_path and "{hash}" in tmpl else "",
    }
    return format_standard_filename(tmpl, context)


# -------------------------------------------------------------------------
#
# Putting a downloaded file in place
#
# -------------------------------------------------------------------------
def place_file(cache_path: str, wanted_path: str, cache_levels: int = 1) -> str:
    """
    Move a downloaded file from its download cache to ``wanted_path`` and
    return where it ended up.

    A different file already at ``wanted_path`` is never replaced: the file
    gets the next free "-2", "-3", ... name. An identical file already there
    is reused (the download is removed). If the move fails the file stays in
    the cache, which is still a valid media path.

    :param cache_levels: How many empty cache folders above the file to
        remove afterwards (e.g. 2 for ``NARA/<NAID>/``), never going up into
        the folder the file was moved to.
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
                remove_empty_dirs(cache_path, wanted_path, cache_levels)
                return candidate
            number += 1
            candidate = "%s-%d%s" % (stem, number, ext)
        os.makedirs(os.path.dirname(candidate) or ".", exist_ok=True)
        os.replace(cache_path, candidate)
    except OSError as err:
        LOG.warning("Downloaded file %s could not be moved: %s", cache_path, err)
        return cache_path
    remove_empty_dirs(cache_path, wanted_path, cache_levels)
    return candidate


def remove_empty_dirs(cache_path: str, wanted_path: str, levels: int = 1) -> None:
    """
    Remove up to ``levels`` empty folders above ``cache_path``, stopping at
    the folder ``wanted_path`` is in.
    """
    base = os.path.normcase(os.path.dirname(os.path.abspath(wanted_path)))
    folder = os.path.dirname(os.path.abspath(cache_path))
    for _level in range(levels):
        if os.path.normcase(folder) == base:
            return
        try:
            os.rmdir(folder)
        except OSError:
            return
        folder = os.path.dirname(folder)
