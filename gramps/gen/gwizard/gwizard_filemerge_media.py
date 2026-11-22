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
Media file handling for GWizard merges.

A media object only records a path; the picture itself is a file on disk.
A path written in the incoming file means something relative to where that
file came from (its folder, or the media path a Gramps XML file names),
while the same path in the family tree is read relative to the tree's base
media path. The helpers here find the file a path points at, work out how
to record it in the family tree, and recognise the same file under
different paths or names (by MD5 checksum, as Gramps computes it).

Only core Gramps helpers (``gramps.gen.utils.file``) are used: renaming,
moving and copying files is left to GWizard Media Fix.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.utils.file import (
    create_checksum,
    expand_path,
    media_path,
    relative_path,
)

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)

_ = glocale.translation.gettext

# The attribute set on an incoming (in-memory) database that records the
# folder of the file it was loaded from.
INCOMING_DIR_ATTR = "gwizard_incoming_dir"

# Checksums already computed, keyed by (path, size, modification time).
_CHECKSUMS: dict[tuple[str, int, int], str] = {}


# -------------------------------------------------------------------------
#
# Paths
#
# -------------------------------------------------------------------------
def is_url(path: str) -> bool:
    """
    Return True when ``path`` is a web address rather than a file.

    A one-letter scheme is a Windows drive letter, and ``file:`` names a
    file, as the GEDCOM importer treats them.
    """
    if not path:
        return False
    scheme = urlparse(path).scheme
    return len(scheme) > 1 and scheme != "file"


def _native(path: str) -> str:
    """Return ``path`` with the separators of this system."""
    return path.replace("\\", os.sep).replace("/", os.sep)


def _key(path: str) -> str:
    """Return a key under which two spellings of one path are equal."""
    return os.path.normcase(os.path.normpath(path))


def _media_dir(db: Any) -> str:
    """
    Return ``media_path(db)`` with the case of the path as it was set.

    On Windows media_path() lower-cases the whole path; a file found under
    it, and recorded with its full path, would otherwise lose its case.
    """
    full = media_path(db)
    try:
        raw = expand_path(db.get_mediapath() or "", False)
    except Exception:  # pylint: disable=broad-except
        return full
    if raw and os.path.isabs(raw):
        cased = os.path.normpath(raw)
        if _key(cased) == _key(full):
            return cased
    return full


def mark_incoming(db: Any, incoming_file: str) -> None:
    """Record on ``db`` that it was loaded from ``incoming_file``."""
    try:
        setattr(db, INCOMING_DIR_ATTR, os.path.dirname(os.path.abspath(incoming_file)))
    except (AttributeError, TypeError):
        LOG.debug("Could not mark the incoming database", exc_info=True)


def incoming_dir(db: Any) -> str | None:
    """Return the folder of the file ``db`` was loaded from, if it is marked."""
    return getattr(db, INCOMING_DIR_ATTR, None)


def base_path_configured(db: Any) -> bool:
    """
    Return True when the family tree has a base media path of its own.

    Without one, Gramps reads relative media paths from the user's
    Pictures folder.
    """
    try:
        return bool((db.get_mediapath() or "").strip())
    except Exception:  # pylint: disable=broad-except
        return False


def _candidates(db: Any, path: str) -> Iterator[str]:
    """Yield the places a media path can point at, as read by ``db``."""
    native = _native(path)
    folder = incoming_dir(db)
    if folder is None:
        # The family tree: relative paths are read from its base path.
        yield native if os.path.isabs(native) else os.path.join(_media_dir(db), native)
        return
    # The incoming file, looked for the way the GEDCOM importer does: as
    # written, from the incoming file's media path, from its folder (with
    # any drive letter dropped), and by file name alone in that folder.
    if os.path.isabs(native):
        yield native
    stripped = native[2:] if len(native) > 3 and native[1] == ":" else native
    stripped = stripped.lstrip(os.sep)
    if base_path_configured(db):
        yield os.path.join(_media_dir(db), stripped)
    yield os.path.join(folder, stripped)
    yield os.path.join(folder, os.path.basename(native))
    if not base_path_configured(db):
        # The importer also tries its own default media path.
        yield os.path.join(_media_dir(db), stripped)


def find_file(db: Any, path: str, fallback_db: Any = None) -> str | None:
    """
    Return the full path of the existing file ``path`` points at.

    ``db`` reads the path (an incoming database reads it from where the
    incoming file came from; the family tree reads it from its base media
    path). ``fallback_db`` is tried next: a file exported from the family
    tree itself has paths relative to the tree's base path. Returns None
    for web addresses and when no file is found.
    """
    if not path or is_url(path):
        return None
    sources: list[Any] = [db] + ([fallback_db] if fallback_db is not None else [])
    for reader in sources:
        try:
            for candidate in _candidates(reader, path):
                if os.path.isfile(candidate):
                    return os.path.normpath(os.path.abspath(candidate))
        except (OSError, ValueError):
            continue
    return None


def target_path(full_path: str, target_db: Any) -> str:
    """
    Return how to record the existing file ``full_path`` in the family tree.

    A file under the tree's base media path is recorded relative to it, as
    the Gramps media editor does. Anything else, or every file when the tree
    has no base media path set, is recorded with its full path, so the path
    keeps its meaning if a base path is set later.
    """
    if not base_path_configured(target_db):
        return full_path
    base = media_path(target_db)
    try:
        common = os.path.commonpath([_key(full_path), _key(base)])
    except ValueError:  # different drives
        return full_path
    if common != _key(base):
        return full_path
    return relative_path(full_path, base)


# -------------------------------------------------------------------------
#
# Checksums
#
# -------------------------------------------------------------------------
def file_checksum(full_path: str | None) -> str:
    """Return the MD5 checksum of a file, or "" when it cannot be read."""
    if not full_path:
        return ""
    try:
        stat = os.stat(full_path)
    except OSError:
        return ""
    key = (_key(full_path), stat.st_size, stat.st_mtime_ns)
    checksum = _CHECKSUMS.get(key)
    if checksum is None:
        checksum = create_checksum(full_path) or ""
        _CHECKSUMS[key] = checksum
    return checksum


def media_full_path(media: Any, db: Any, fallback_db: Any = None) -> str | None:
    """Return the full path of the file a media object points at."""
    return find_file(db, media.get_path() or "", fallback_db)


def media_checksum(media: Any, full_path: str | None) -> str:
    """Return the media's recorded checksum, or that of its file."""
    return (media.get_checksum() or "").strip() or file_checksum(full_path)


def _raw_key(path: str) -> str:
    """Return the media path as written, normalised for comparison."""
    return " ".join((path or "").replace("\\", "/").split()).casefold()


def same_media(s_media: Any, s_db: Any, t_media: Any, t_db: Any) -> bool:
    """
    Return True when two media objects are the same picture.

    They are when their paths are written the same (whatever the slashes
    and case), when they point at the same file, or when their files have
    the same checksum.
    """
    if _raw_key(s_media.get_path()) == _raw_key(t_media.get_path()):
        return True
    s_full = media_full_path(s_media, s_db, fallback_db=t_db)
    t_full = media_full_path(t_media, t_db)
    if s_full and t_full and _key(s_full) == _key(t_full):
        return True
    s_sum = media_checksum(s_media, s_full)
    return bool(s_sum) and s_sum == media_checksum(t_media, t_full)


# -------------------------------------------------------------------------
#
# Finding a picture the family tree already has
#
# -------------------------------------------------------------------------
class TargetMediaIndex:
    """
    Look up the family tree's media by file, path or checksum.

    Built on first use. Files without a recorded checksum are indexed by
    size and only hashed when an incoming file of the same size is looked
    up, so a large tree is not hashed up front.
    """

    def __init__(self, db: Any) -> None:
        self.db = db
        self._built = False
        self._by_file: dict[str, str] = {}
        self._by_path: dict[str, str] = {}
        self._by_checksum: dict[str, str] = {}
        self._by_size: dict[int, list[tuple[str, str]]] = {}

    def _index(self, media: Any, full_path: str | None) -> None:
        handle = media.get_handle()
        if full_path:
            self._by_file.setdefault(_key(full_path), handle)
        raw = _raw_key(media.get_path())
        if raw:
            self._by_path.setdefault(raw, handle)
        checksum = (media.get_checksum() or "").strip()
        if checksum:
            self._by_checksum.setdefault(checksum, handle)
        elif full_path:
            try:
                size = os.path.getsize(full_path)
            except OSError:
                return
            self._by_size.setdefault(size, []).append((handle, full_path))

    def _build(self) -> None:
        if self._built:
            return
        self._built = True
        for media in self.db.iter_media():
            self._index(media, media_full_path(media, self.db))

    def _live(self, handle: str | None) -> str | None:
        if handle and self.db.has_media_handle(handle):
            return handle
        return None

    def find(
        self, full_path: str | None, checksum: str, recorded_path: str
    ) -> str | None:
        """
        Return the handle of the tree's media for this picture, if any.

        :param full_path: The incoming file, when it was found.
        :param checksum: Its checksum ("" when unknown).
        :param recorded_path: The path the copy would be recorded with.
        """
        self._build()
        if full_path:
            hit = self._live(self._by_file.get(_key(full_path)))
            if hit:
                return hit
        hit = self._live(self._by_path.get(_raw_key(recorded_path)))
        if hit:
            return hit
        if not checksum:
            return None
        hit = self._live(self._by_checksum.get(checksum))
        if hit:
            return hit
        if full_path:
            try:
                size = os.path.getsize(full_path)
            except OSError:
                return None
            for handle, t_full in self._by_size.get(size, []):
                if file_checksum(t_full) == checksum and self._live(handle):
                    return handle
        return None

    def add(self, media: Any) -> None:
        """Index a media object just added to the family tree."""
        self._build()
        self._index(media, media_full_path(media, self.db))


# -------------------------------------------------------------------------
#
# Telling the user
#
# -------------------------------------------------------------------------
def media_handles_of(obj: Any, db: Any) -> list[str]:
    """
    Return the media handles an incoming person refers to: their own and
    those of their events.
    """
    handles: list[str] = [ref.get_reference_handle() for ref in obj.get_media_list()]
    for event_ref in getattr(obj, "get_event_ref_list", lambda: [])():
        try:
            event = db.get_event_from_handle(event_ref.ref)
        except Exception:  # pylint: disable=broad-except
            continue
        if event is not None:
            handles.extend(ref.get_reference_handle() for ref in event.get_media_list())
    # dict.fromkeys drops repeats and keeps the first-seen order.
    return list(dict.fromkeys(h for h in handles if h))


def media_note(media_handles: Iterable[str], source_db: Any, target_db: Any) -> str:
    """
    Return what the user should know before incoming media is copied:
    pictures whose file cannot be found, and a family tree without a base
    media path. Returns "" when there is nothing to say.
    """
    total = missing = 0
    for handle in media_handles:
        try:
            media = source_db.get_media_from_handle(handle)
        except Exception:  # pylint: disable=broad-except
            continue
        if media is None or is_url(media.get_path() or ""):
            continue
        total += 1
        if find_file(source_db, media.get_path() or "", fallback_db=target_db) is None:
            missing += 1
    lines = []
    if missing:
        lines.append(
            glocale.translation.ngettext(
                "%(missing)d of %(total)d media files could not be found; "
                "its path is kept as written in the incoming file.",
                "%(missing)d of %(total)d media files could not be found; "
                "their paths are kept as written in the incoming file.",
                missing,
            )
            % {"missing": missing, "total": total}
        )
    if total and not base_path_configured(target_db):
        lines.append(
            _(
                "Your family tree has no base media path set, so media files "
                "are recorded with their full paths. You can set a base media "
                "path in the Preferences."
            )
        )
    return "\n".join(lines)
