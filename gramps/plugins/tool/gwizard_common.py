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
import os
import shutil
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk, Pango


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
