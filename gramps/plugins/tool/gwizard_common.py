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

"""Shared UI widgets and utilities for GWizard tools."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
import shutil
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk, Pango

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db import DbTxn
from gramps.gen.lib import Tag

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# SelectableLabel
#
# ------------------------------------------------------------
class SelectableLabel(Gtk.Label):
    """Gtk.Label subclass that is selectable, left-aligned, and wrappable by default."""

    def __init__(
        self,
        label: str = "",
        selectable: bool = True,
        wrap: bool = True,
        xalign: float = 0.0,
        markup: bool = False,
        can_focus: bool = False,
        max_width_chars: int | None = None,
        size_request: tuple[int, int] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the selectable label with standard formatting defaults."""
        super().__init__(**kwargs)
        if markup:
            self.set_markup(label)
        else:
            self.set_text(label)

        self.set_selectable(selectable)
        self.set_halign(Gtk.Align.START)
        self.set_xalign(xalign)
        self.set_can_focus(can_focus)

        if wrap:
            self.set_line_wrap(True)
            self.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)

        if max_width_chars is not None:
            self.set_max_width_chars(max_width_chars)

        if size_request is not None:
            self.set_size_request(*size_request)


# ------------------------------------------------------------
#
# TableLabel
#
# ------------------------------------------------------------
class TableLabel(SelectableLabel):
    """Selectable label tailored for table and grid data cells."""

    def __init__(
        self,
        label: str = "",
        width_chars: int | None = None,
        width_request: int | None = None,
        selectable: bool = True,
        wrap: bool = True,
        markup: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize a table cell label with standard alignment, wrapping, and width constraints."""
        size_req = (width_request, -1) if width_request is not None else None
        super().__init__(
            label=label,
            selectable=selectable,
            wrap=wrap,
            xalign=0.0,
            markup=markup,
            can_focus=False,
            max_width_chars=width_chars,
            size_request=size_req,
            **kwargs,
        )


# ------------------------------------------------------------
#
# HeaderLabel
#
# ------------------------------------------------------------
class HeaderLabel(SelectableLabel):
    """Header label displaying bold markup text for table column headers."""

    def __init__(self, title: str = "", **kwargs: Any) -> None:
        """Initialize a header label with bold markup."""
        super().__init__(
            label=f"<b>{title}</b>",
            selectable=True,
            wrap=False,
            xalign=0.0,
            markup=True,
            can_focus=False,
            **kwargs,
        )


# ------------------------------------------------------------
#
# Table Grid helper
#
# ------------------------------------------------------------
def create_table_grid(col_spacing: int = 6, row_spacing: int = 6) -> Gtk.Grid:
    """Return a standard Gtk.Grid configured for wizard tables."""
    grid = Gtk.Grid()
    grid.set_column_spacing(col_spacing)
    grid.set_row_spacing(row_spacing)
    grid.set_hexpand(True)
    grid.set_vexpand(True)
    return grid


# ------------------------------------------------------------
#
# Pure path helpers (no GTK / Gramps dependency; unit-testable)
#
# ------------------------------------------------------------
def clean_path(path: str | None) -> str:
    """Strip whitespace and surrounding quotes from a path string.

    Matched pairs of quotes are removed.  An unmatched double quote is removed
    (never valid in a Windows filename), but an unmatched apostrophe is kept
    because it can legitimately end a folder name ("Grandma's").
    """
    if not path:
        return ""
    p = str(path).strip()
    while len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'":
        p = p[1:-1].strip()
    if p.startswith('"'):
        p = p[1:].strip()
    if p.endswith('"'):
        p = p[:-1].strip()
    return p


def is_absolute_path(path: str | None) -> bool:
    """Return True for drive-absolute AND rooted drive-less paths.

    Python 3.13+ on Windows no longer treats "/Users/x" as absolute, but GEDCOM
    imports commonly produce exactly such paths (drive letter stripped).  Treat
    them as absolute so they are not mistaken for paths relative to the media
    base directory.
    """
    p = clean_path(path)
    if not p:
        return False
    return os.path.isabs(p) or p[0] in ("/", "\\")


def path_key(path: str) -> str:
    """Normalised, case-folded key for comparing two paths."""
    return os.path.normcase(os.path.normpath(clean_path(path)))


def to_db_path(full_path: str, base_dir: str) -> str:
    """Return full_path relative to base_dir (forward slashes) when inside it.

    Paths outside base_dir (or on another drive) are returned unchanged.
    """
    if not full_path or not base_dir:
        return full_path
    try:
        abs_full = os.path.abspath(full_path)
        abs_base = os.path.abspath(base_dir)
        nf = os.path.normcase(os.path.normpath(abs_full))
        nb = os.path.normcase(os.path.normpath(abs_base))
        if nf == nb or os.path.commonpath([nf, nb]) != nb:
            return full_path
        return os.path.relpath(abs_full, abs_base).replace("\\", "/")
    except (ValueError, OSError):
        return full_path


def unique_destination(dest: str, claimed: set[str], src: str | None = None) -> str:
    """Return dest, or dest with _2, _3 ... appended to the stem, such that the
    result neither exists on disk (unless it is src itself) nor was already
    claimed by another record in the current batch.  The result is claimed."""

    def taken(p: str) -> bool:
        if path_key(p) in claimed:
            return True
        if os.path.exists(p):
            try:
                if src and os.path.exists(src) and os.path.samefile(src, p):
                    return False
            except OSError:
                pass
            return True
        return False

    stem, ext = os.path.splitext(dest)
    cand, n = dest, 2
    while taken(cand):
        cand = f"{stem}_{n}{ext}"
        n += 1
    claimed.add(path_key(cand))
    return cand


def relocate_file(src: str, dest: str, copy: bool = False) -> tuple[bool, str]:
    """Move or copy src to dest WITHOUT ever overwriting an existing file.

    Returns (ok, error_message).  ok is also True when dest already is the
    same file as src.
    """
    try:
        if os.path.exists(dest):
            try:
                same = os.path.samefile(src, dest)
            except OSError:
                same = False
            if not same:
                return False, "destination already exists"
            if not copy and os.path.basename(src) != os.path.basename(dest):
                os.rename(src, dest)  # case-only rename on a case-insensitive FS
            return True, ""
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if copy:
            shutil.copy2(src, dest)
        else:
            shutil.move(src, dest)
        return True, ""
    except Exception as err:  # noqa: BLE001 - report any OS/shutil error
        return False, str(err)


def build_basename_index(base_dir: str, limit: int = 50000) -> dict[str, list[str]]:
    """Map lower-cased file name -> full paths for every file below base_dir."""
    index: dict[str, list[str]] = {}
    seen = 0
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.startswith("."):
                continue
            index.setdefault(fname.lower(), []).append(os.path.join(root, fname))
            seen += 1
            if seen >= limit:
                return index
    return index


# ------------------------------------------------------------
#
# GWizard Standard Tags and Locking Helpers
#
# ------------------------------------------------------------
TAG_MEDIA_FIXED = "GWizard: MediaFixed"
TAG_MEDIA_FIXED_COLOR = "#2E8B57"

TAG_LOCKED = "GWizard: Locked"
TAG_LOCKED_COLOR = "#B22222"


def create_gwizard_tag(name: str, color: str = "") -> Tag:
    """Create a new Tag instance configured with the specified name and color."""
    tag = Tag()
    tag.set_name(name)
    if color:
        tag.set_color(color)
    return tag


def ensure_tag(
    db: Any,
    name: str,
    color: str = "",
    txn: Any = None,
) -> Tag | None:
    """Ensure a Tag with name and color exists in the database.

    If it exists, return it. If not, create, add, and commit it, then return it.
    """
    if not db or not hasattr(db, "get_tag_from_name"):
        return None
    try:
        tag = db.get_tag_from_name(name)
        if tag:
            return tag
    except Exception:
        pass

    if not hasattr(db, "add_tag"):
        return None

    tag = create_gwizard_tag(name, color)
    if hasattr(db, "get_number_of_tags"):
        try:
            tag.set_priority(db.get_number_of_tags())
        except Exception:
            pass

    try:
        if txn is not None:
            db.add_tag(tag, txn)
            if hasattr(db, "commit_tag"):
                db.commit_tag(tag, txn)
        else:
            with DbTxn(_("Create GWizard Tag"), db) as trans:
                db.add_tag(tag, trans)
                if hasattr(db, "commit_tag"):
                    db.commit_tag(tag, trans)
        return tag
    except Exception as err:
        LOG.warning("Failed to create tag '%s': %s", name, err)
        return None


def ensure_gwizard_tags(db: Any, txn: Any = None) -> tuple[Tag | None, Tag | None]:
    """Ensure both standard GWizard tags ('GWizard: MediaFixed' and 'GWizard: Locked') exist."""
    t_fixed = ensure_tag(db, TAG_MEDIA_FIXED, TAG_MEDIA_FIXED_COLOR, txn=txn)
    t_locked = ensure_tag(db, TAG_LOCKED, TAG_LOCKED_COLOR, txn=txn)
    return t_fixed, t_locked


def is_media_locked(db: Any, media: Any) -> bool:
    """Return True if media has the 'GWizard: Locked' tag."""
    if not db or not media or not hasattr(media, "get_tag_list"):
        return False
    tag_list = media.get_tag_list()
    if not tag_list:
        return False

    if hasattr(db, "get_tag_from_name"):
        try:
            lock_tag = db.get_tag_from_name(TAG_LOCKED)
            if lock_tag and lock_tag.get_handle() in tag_list:
                return True
        except Exception:
            pass

    if hasattr(db, "get_tag_from_handle"):
        for th in tag_list:
            try:
                t = db.get_tag_from_handle(th)
                if t and getattr(t, "name", None) == TAG_LOCKED:
                    return True
            except Exception:
                pass

    return False


def has_media_fixed_tag(db: Any, media: Any) -> bool:
    """Return True if media has the 'GWizard: MediaFixed' tag."""
    if not db or not media or not hasattr(media, "get_tag_list"):
        return False
    tag_list = media.get_tag_list()
    if not tag_list:
        return False

    if hasattr(db, "get_tag_from_name"):
        try:
            fixed_tag = db.get_tag_from_name(TAG_MEDIA_FIXED)
            if fixed_tag and fixed_tag.get_handle() in tag_list:
                return True
        except Exception:
            pass

    if hasattr(db, "get_tag_from_handle"):
        for th in tag_list:
            try:
                t = db.get_tag_from_handle(th)
                if t and getattr(t, "name", None) == TAG_MEDIA_FIXED:
                    return True
            except Exception:
                pass

    return False


def add_media_fixed_tag(
    db: Any,
    media: Any,
    txn: Any = None,
    commit: bool = False,
) -> bool:
    """Add the 'GWizard: MediaFixed' tag to media if not already tagged.

    Returns True if the tag was newly added, False otherwise.
    """
    if not db or not media or not hasattr(media, "add_tag"):
        return False
    tag = ensure_tag(db, TAG_MEDIA_FIXED, TAG_MEDIA_FIXED_COLOR, txn=txn)
    if not tag or not tag.get_handle():
        return False
    tag_list = media.get_tag_list() or []
    if tag.get_handle() in tag_list:
        return False

    media.add_tag(tag.get_handle())
    if commit and hasattr(db, "commit_media"):
        if txn is not None:
            db.commit_media(media, txn)
        else:
            with DbTxn(_("Tag Media Fixed"), db) as trans:
                db.commit_media(media, trans)
    return True


def lock_media(
    db: Any,
    media: Any,
    txn: Any = None,
    commit: bool = False,
) -> bool:
    """Add the 'GWizard: Locked' tag to media if not already tagged.

    Returns True if the tag was newly added, False otherwise.
    """
    if not db or not media or not hasattr(media, "add_tag"):
        return False
    tag = ensure_tag(db, TAG_LOCKED, TAG_LOCKED_COLOR, txn=txn)
    if not tag or not tag.get_handle():
        return False
    tag_list = media.get_tag_list() or []
    if tag.get_handle() in tag_list:
        return False

    media.add_tag(tag.get_handle())
    if commit and hasattr(db, "commit_media"):
        if txn is not None:
            db.commit_media(media, txn)
        else:
            with DbTxn(_("Lock Media"), db) as trans:
                db.commit_media(media, trans)
    return True


def unlock_media(
    db: Any,
    media: Any,
    txn: Any = None,
    commit: bool = False,
) -> bool:
    """Remove the 'GWizard: Locked' tag from media.

    Returns True if the tag was removed, False otherwise.
    """
    if not db or not media or not hasattr(media, "remove_tag"):
        return False
    tag_list = list(media.get_tag_list() or [])
    if not tag_list:
        return False

    tag_handle = None
    if hasattr(db, "get_tag_from_name"):
        try:
            tag = db.get_tag_from_name(TAG_LOCKED)
            if tag and tag.get_handle() in tag_list:
                tag_handle = tag.get_handle()
        except Exception:
            pass

    if not tag_handle and hasattr(db, "get_tag_from_handle"):
        for th in tag_list:
            try:
                t = db.get_tag_from_handle(th)
                if t and getattr(t, "name", None) == TAG_LOCKED:
                    tag_handle = th
                    break
            except Exception:
                pass

    if not tag_handle:
        return False

    media.remove_tag(tag_handle)
    if commit and hasattr(db, "commit_media"):
        if txn is not None:
            db.commit_media(media, txn)
        else:
            with DbTxn(_("Unlock Media"), db) as trans:
                db.commit_media(media, trans)
    return True
