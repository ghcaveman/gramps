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

"""Image preview pane for the GWizard Media Fix dialogs.

The pane shows the file a row would use, as Gramps' Photo widget does (the
same thumbnails, and a double-click opens the file in the default viewer),
and outlines the region of each media reference on it, so the user can see
which people or events a file is attached to before accepting a match or a
merge.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gdk, Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db import DbReadBase
from gramps.gen.mime import get_type
from gramps.gen.utils.db import navigation_label
from gramps.gen.utils.thumbnails import SIZE_LARGE, get_thumbnail_image

try:
    from .gwizard_mediafix_common import escape_markup
except (ImportError, ValueError):
    from gwizard_mediafix_common import (  # type: ignore[import-not-found,no-redef]
        escape_markup,
    )

# Addon translations (the package's locale/ folder) fall back to Gramps' own;
# as a built-in tool there is no locale/ folder and Gramps' are used.
try:
    _trans = glocale.get_addon_translator(__file__)
except ValueError:
    _trans = glocale.translation
_ = _trans.sgettext
LOG = logging.getLogger(__name__)

# Outline colours, one per media record (or per reference), chosen to stay
# distinguishable on photographs.
REGION_COLORS = (
    "#e6194b",
    "#3cb44b",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#42d4f4",
    "#f032e6",
    "#9a6324",
)

# The legend lists at most this many references; the rest are counted.
MAX_LEGEND = 12

Region = tuple[int, int, int, int]


# ------------------------------------------------------------
#
# Reference regions
#
# ------------------------------------------------------------
def region_of(rect: Any) -> Region | None:
    """
    Return a media reference's region, or ``None`` for the whole image.

    Gramps stores a region as ``(x1, y1, x2, y2)`` in percent of the image.
    No region, an empty one or the full frame all mean the whole image.

    :param rect: ``MediaRef.get_rectangle()``.
    :returns: The region, or ``None``.
    """
    if not rect or len(rect) != 4:
        return None
    try:
        x1, y1, x2, y2 = (max(0, min(100, int(v))) for v in rect)
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1 or (x1, y1, x2, y2) == (0, 0, 100, 100):
        return None
    return (x1, y1, x2, y2)


def media_reference_regions(
    db: DbReadBase | None, media_handle: str, record_label: str = ""
) -> list[dict[str, Any]]:
    """
    List every reference to a media record, with its region.

    :param db: The database.
    :param media_handle: The media record's handle.
    :param record_label: Text put before each label (e.g. the media record's
        Gramps ID, when several records are shown together).
    :returns: One dict per reference: ``label`` (e.g. "[I0001] Smith, John")
        and ``rect`` (a :data:`Region`, or ``None`` for the whole image).
    """
    found: list[dict[str, Any]] = []
    if not db or not media_handle:
        return found
    try:
        backlinks = list(db.find_backlink_handles(media_handle))
    except Exception:
        return found
    for class_name, handle in backlinks:
        try:
            obj = db.method("get_%s_from_handle", class_name)(handle)
        except Exception:
            obj = None
        if obj is None or not hasattr(obj, "get_media_list"):
            continue
        try:
            label = navigation_label(db, class_name, obj)[0]
        except Exception:
            label = None
        label = label or "[%s] %s" % (obj.get_gramps_id(), class_name)
        if record_label:
            label = "%s: %s" % (record_label, label)
        for ref in obj.get_media_list():
            if ref.get_reference_handle() == media_handle:
                found.append({"label": label, "rect": region_of(ref.get_rectangle())})
    return found


# ------------------------------------------------------------
#
# Drawing
#
# ------------------------------------------------------------
def _rgb(color: str) -> tuple[float, float, float]:
    """Return a "#rrggbb" colour as cairo RGB fractions."""
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def outline_regions(pixbuf: Any, regions: list[dict[str, Any]]) -> Any:
    """
    Draw each region's outline and number on a copy of an image.

    :param pixbuf: The image (``GdkPixbuf.Pixbuf``).
    :param regions: Dicts with ``rect`` (a :data:`Region` or ``None``),
        ``color`` and ``number``; whole-image references are not drawn.
    :returns: A new pixbuf, or *pixbuf* itself when there is nothing to draw
        or drawing is not possible.
    """
    boxes = [r for r in regions if r.get("rect")]
    if not boxes or pixbuf is None:
        return pixbuf
    try:
        import cairo

        width, height = pixbuf.get_width(), pixbuf.get_height()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context(surface)
        Gdk.cairo_set_source_pixbuf(ctx, pixbuf, 0, 0)
        ctx.paint()
        line = max(2.0, min(width, height) / 90.0)
        ctx.set_line_width(line)
        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(max(9.0, line * 5))
        for region in boxes:
            x1, y1, x2, y2 = region["rect"]
            left, top = x1 * width / 100.0, y1 * height / 100.0
            box_w, box_h = (x2 - x1) * width / 100.0, (y2 - y1) * height / 100.0
            red, green, blue = _rgb(region.get("color") or REGION_COLORS[0])
            # A dark halo keeps the outline visible on light and dark photos.
            ctx.set_source_rgba(0, 0, 0, 0.6)
            ctx.set_line_width(line + 2)
            ctx.rectangle(left, top, box_w, box_h)
            ctx.stroke()
            ctx.set_source_rgb(red, green, blue)
            ctx.set_line_width(line)
            ctx.rectangle(left, top, box_w, box_h)
            ctx.stroke()
            # The number, on a filled tab in the top-left corner.
            text = str(region.get("number", ""))
            if text:
                ext = ctx.text_extents(text)
                tab_w, tab_h = ext.x_advance + 2 * line, ext.height + 2 * line
                ctx.rectangle(left, top, tab_w, tab_h)
                ctx.fill()
                ctx.set_source_rgb(1, 1, 1)
                ctx.move_to(left + line, top + line - ext.y_bearing)
                ctx.show_text(text)
        surface.flush()
        return Gdk.pixbuf_get_from_surface(surface, 0, 0, width, height)
    except Exception:  # never let a preview break the dialog
        LOG.debug("could not draw media regions", exc_info=True)
        return pixbuf


def legend_markup(regions: list[dict[str, Any]]) -> str:
    """
    Build the legend: one line per reference, coloured like its outline.

    :param regions: Dicts with ``label``, ``rect``, ``color`` and ``number``.
    :returns: Pango markup.
    """
    lines = []
    for region in regions[:MAX_LEGEND]:
        where = str(_("region")) if region.get("rect") else str(_("whole image"))
        lines.append(
            '<span foreground="%s" weight="bold">■ %s</span> %s <i>(%s)</i>'
            % (
                region.get("color") or REGION_COLORS[0],
                region.get("number", ""),
                escape_markup(region.get("label", "")),
                escape_markup(where),
            )
        )
    extra = len(regions) - MAX_LEGEND
    if extra > 0:
        lines.append(escape_markup(str(_("… and %d more references")) % extra))
    return "\n".join(lines)


def number_regions(
    regions: list[dict[str, Any]], color_by: str = "reference"
) -> list[dict[str, Any]]:
    """
    Give each reference a number and an outline colour.

    :param regions: Dicts from :func:`media_reference_regions`; when
        *color_by* is ``"record"`` each also has a ``record`` index.
    :param color_by: ``"reference"`` (one colour per reference) or
        ``"record"`` (one colour per media record, to show what a merge
        brings together).
    :returns: New dicts with ``number`` and ``color`` added.
    """
    numbered = []
    for number, region in enumerate(regions, start=1):
        index = region.get("record", 0) if color_by == "record" else number - 1
        item = dict(region)
        item["number"] = number
        item["color"] = REGION_COLORS[index % len(REGION_COLORS)]
        numbered.append(item)
    return numbered


# ------------------------------------------------------------
#
# MediaPreviewPane
#
# ------------------------------------------------------------
class MediaPreviewPane(Gtk.Box):
    """
    A small preview: the file's image (or its file-type icon) on the left,
    the file name, a status line and the legend of reference regions on the
    right.  A double-click on the image opens the file in the default
    viewer, as in Gramps' Photo widget.
    """

    def __init__(self, uistate: Any = None) -> None:
        """
        Build the empty pane.

        :param uistate: Gramps' UI state (lets the viewer report errors).
        """
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.set_border_width(6)
        self.uistate = uistate
        self.full_path = ""
        # What is shown, for tests and for anyone extending the pane.
        self.shown: dict[str, Any] = {"full_path": "", "caption": "", "regions": []}

        self.event_box = Gtk.EventBox()
        self.event_box.set_size_request(190, 190)
        self.event_box.connect("button-press-event", self.cb_button_press)
        self.image = Gtk.Image()
        self.event_box.add(self.image)
        self.pack_start(self.event_box, False, False, 0)

        self.info = Gtk.Label()
        self.info.set_line_wrap(True)
        self.info.set_selectable(True)
        self.info.set_can_focus(False)  # selectable, but not a Tab stop
        self.info.set_xalign(0.0)
        self.info.set_yalign(0.0)
        self.info.set_halign(Gtk.Align.START)
        self.info.set_valign(Gtk.Align.START)
        self.pack_start(self.info, True, True, 0)
        self.show_nothing(str(_("Select a row to preview its file.")))

    def show_nothing(self, caption: str) -> None:
        """
        Show no image, only a message.

        :param caption: The message.
        """
        self.full_path = ""
        self.shown = {"full_path": "", "caption": caption, "regions": []}
        self.image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
        self.event_box.set_tooltip_text(None)
        self.info.set_markup(escape_markup(caption))

    def show_file(
        self, full_path: str, caption: str, regions: list[dict[str, Any]] | None = None
    ) -> None:
        """
        Show a file with its reference regions outlined.

        :param full_path: The file to show.
        :param caption: The status line (what this file is to the row).
        :param regions: Numbered regions (see :func:`number_regions`).
        """
        regions = regions or []
        if not full_path or not os.path.isfile(full_path):
            self.show_nothing(caption)
            self.shown["regions"] = regions
            if regions:
                self.info.set_markup(
                    escape_markup(caption) + "\n\n" + legend_markup(regions)
                )
            return
        self.full_path = full_path
        self.shown = {"full_path": full_path, "caption": caption, "regions": regions}
        mime = get_type(full_path)
        try:
            pixbuf = get_thumbnail_image(full_path, mime, None, SIZE_LARGE)
        except Exception:
            pixbuf = None
        if pixbuf is not None and mime and mime.startswith("image"):
            pixbuf = outline_regions(pixbuf, regions)
        if pixbuf is not None:
            self.image.set_from_pixbuf(pixbuf)
        else:
            self.image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
        self.event_box.set_tooltip_text(
            str(_("Double-click to open the file in the default viewer."))
        )
        text = "<b>%s</b>\n%s" % (
            escape_markup(os.path.basename(full_path)),
            escape_markup(caption),
        )
        if regions:
            text += "\n\n" + legend_markup(regions)
        self.info.set_markup(text)

    def cb_button_press(self, _widget: Any, event: Any) -> bool:
        """
        Open the shown file in the default viewer on a double-click.

        :param _widget: The image's event box.
        :param event: The button event.
        :returns: True when the click was handled.
        """
        if (
            self.full_path
            and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS
            and event.button == 1
        ):
            from gramps.gui.utils import open_file_with_default_application

            open_file_with_default_application(self.full_path, self.uistate)
            return True
        return False


# ------------------------------------------------------------
#
# PreviewRowsMixin
#
# ------------------------------------------------------------
class PreviewRowsMixin:
    """
    Show the preview of whichever table row has the keyboard focus.

    A dialog calls :meth:`init_preview` before building its table,
    :meth:`watch_row` for each row, :meth:`preview_layout` to place the
    table above the pane, and defines :meth:`update_preview`.  Focus moves
    to a row when the user clicks or tabs into any of its widgets.
    """

    preview: MediaPreviewPane
    preview_target: dict[str, Any] | None
    dbstate: Any

    def init_preview(self, uistate: Any = None) -> None:
        """
        Create the pane and the row bookkeeping.

        :param uistate: Gramps' UI state, for the default viewer.
        """
        self.preview = MediaPreviewPane(uistate)
        self.preview_target = None
        self._focus_rows: dict[Any, dict[str, Any]] = {}
        self._watched_grids: list[Any] = []
        self._region_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def watch_row(self, grid: Any, widgets: list[Any], target: dict[str, Any]) -> None:
        """
        Show *target*'s preview when any of *widgets* gets the focus.

        :param grid: The table the widgets are attached to.
        :param widgets: The row's widgets (the grid's direct children).
        :param target: The row.
        """
        if not any(g is grid for g in self._watched_grids):
            self._watched_grids.append(grid)
            grid.connect("set-focus-child", self.cb_row_focus)
        for widget in widgets:
            self._focus_rows[widget] = target

    def cb_row_focus(self, _grid: Any, child: Any) -> None:
        """
        Follow the focus to another row.

        :param _grid: The table.
        :param child: The table child that now holds the focus (or None).
        """
        target = self._focus_rows.get(child) if child is not None else None
        if target is not None and target is not self.preview_target:
            self.show_row_preview(target)

    def show_row_preview(self, target: dict[str, Any]) -> None:
        """
        Make *target* the previewed row and show it.

        :param target: The row.
        """
        self.preview_target = target
        try:
            self.update_preview(target)
        except Exception:  # a preview must never break the dialog
            LOG.debug("media preview failed", exc_info=True)
            self.preview.show_nothing(str(_("No preview available.")))

    def refresh_preview(self, target: dict[str, Any]) -> None:
        """
        Show *target* again if it is the previewed row (its file changed).

        :param target: The row that changed.
        """
        if target is self.preview_target:
            self.show_row_preview(target)

    def preview_layout(self, table: Any) -> Any:
        """
        Put the table above the preview, with a handle to resize them.

        :param table: The scrolled table.
        :returns: The container to add to the dialog.
        """
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.pack1(table, True, False)
        paned.pack2(self.preview, False, False)
        return paned

    def regions_for(
        self, media_handle: str, record_label: str = ""
    ) -> list[dict[str, Any]]:
        """
        Return a media record's references (cached for the dialog's life).

        :param media_handle: The media record.
        :param record_label: Text put before each label.
        :returns: See :func:`media_reference_regions`.
        """
        key = (media_handle, record_label)
        if key not in self._region_cache:
            db = self.dbstate.db if self.dbstate else None
            self._region_cache[key] = media_reference_regions(
                db, media_handle, record_label
            )
        return [dict(r) for r in self._region_cache[key]]

    def update_preview(self, target: dict[str, Any]) -> None:
        """
        Show *target*'s file and references in :attr:`preview`.

        :param target: The row.
        """
        raise NotImplementedError


__all__ = [
    "MAX_LEGEND",
    "REGION_COLORS",
    "MediaPreviewPane",
    "PreviewRowsMixin",
    "legend_markup",
    "media_reference_regions",
    "number_regions",
    "outline_regions",
    "region_of",
]
