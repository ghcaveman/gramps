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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Review window for attaching a NARA catalog record to an existing person.

The left side lists the NARA citations the person already has; the right
side shows the selected record's citation and its images, each with a
checkbox, its page number, what the page probably is, whether it mentions
the person, its size and whether the tree already has it. The highlighted
page's machine-read text is shown below the list. Only the checked images
are downloaded and added.
"""

# ------------------------------------------------------------
#
# Python modules
#
# ------------------------------------------------------------
from __future__ import annotations
import logging
from typing import Any

# ------------------------------------------------------------
#
# GTK modules
#
# ------------------------------------------------------------
from gi.repository import GLib
from gi.repository import Gtk

# ------------------------------------------------------------
#
# Gramps modules
#
# ------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizardnaramerge import (
    IMAGE_IN_TREE,
    IMAGE_LINKED,
    IMAGE_NEW,
    AttachResult,
    NaraRecordAttacher,
    RecordReview,
    format_size,
)
from gramps.gen.gwizard.gwizardnarapages import (
    NO_TEXT,
    UNKNOWN,
    PageInfo,
    classify_pages,
    page_number,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# Image list columns
COL_SELECTED = 0
COL_NUMBER = 1
COL_FILENAME = 2
COL_SIZE = 3
COL_STATUS = 4
COL_INDEX = 5
COL_SELECTABLE = 6
COL_PROBABLY = 7
COL_MENTIONS = 8


def status_text(status: str) -> str:
    """Return the Status column text for an image status."""
    if status == IMAGE_LINKED:
        return _("Already attached")
    if status == IMAGE_IN_TREE:
        return _("In your tree (will be linked)")
    return _("New")


def citation_text(review: RecordReview) -> str:
    """Describe what attaching will do with the record's citation."""
    if review.citation_on_person:
        return _("Citation: already attached to this person.")
    if review.citation_handle:
        return _("Citation: already in your tree; it will be attached to this person.")
    return _("Citation: new; it will be added and attached to this person.")


def selection_summary(review: RecordReview, selected: set[int]) -> str:
    """Describe what the checked images will do."""
    chosen = [image for image in review.images if image.index in selected]
    new = [image for image in chosen if image.status == IMAGE_NEW]
    relink = [image for image in chosen if image.status == IMAGE_IN_TREE]
    size = sum(image.size for image in new)
    parts = [
        _("%(count)d new images selected (%(size)s).")
        % {"count": len(new), "size": format_size(size) or _("size unknown")}
    ]
    if relink:
        parts.append(_("%d images already in your tree will be linked.") % len(relink))
    linked = sum(1 for image in review.images if image.status == IMAGE_LINKED)
    if linked:
        parts.append(_("%d images are already attached.") % linked)
    return " ".join(parts)


def has_work(review: RecordReview, selected: set[int]) -> bool:
    """Return True when attaching would change anything."""
    if not review.citation_on_person:
        return True
    return any(
        image.index in selected and image.status != IMAGE_LINKED
        for image in review.images
    )


def person_names(person: Any) -> list[str]:
    """
    Return the names to look for on the pages: the given names, surname and
    any alternate (such as married) surnames of the person.
    """
    if person is None:
        return []
    names: list[str] = []
    for name in [person.get_primary_name()] + person.get_alternate_names():
        names.extend(str(name.get_first_name() or "").split())
        for surname in name.get_surname_list():
            names.append(str(surname.get_surname() or "").strip())
    unique: list[str] = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return unique


def page_description(title: str, info: PageInfo | None) -> str:
    """Return a media description such as "<title>, page 3: Claim brief"."""
    if info is None:
        return ""
    if info.label in (UNKNOWN, NO_TEXT):
        return _("%(title)s, page %(page)d") % {"title": title, "page": info.page}
    return _("%(title)s, page %(page)d: %(label)s") % {
        "title": title,
        "page": info.page,
        "label": info.label,
    }


# ------------------------------------------------------------
#
# NaraAttachDialog
#
# ------------------------------------------------------------
class NaraAttachDialog(Gtk.Dialog):
    """
    Show a NARA record next to the person's existing NARA citations and let
    the user choose which images to attach.
    """

    def __init__(
        self,
        parent: Any,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        parsed: dict[str, Any],
        attacher: NaraRecordAttacher | None = None,
        client: Any = None,
    ) -> None:
        """
        :param parent: The search dialog this window belongs to.
        :param dbstate: Gramps database state.
        :param uistate: Gramps UI state (for opening previews).
        :param person_handle: The person to attach the record to.
        :param parsed: The record, from NaraCatalogInterface.parse_record.
        :param attacher: The attacher to use; one is made for the open tree
            when omitted.
        :param client: NARA catalog client used to fetch the pages' text (one
            API call); without it the pages are not classified.
        """
        super().__init__(transient_for=parent, modal=True)
        self.set_title(_("Attach NARA Record"))
        self.set_default_size(1000, 600)
        self.set_resizable(True)
        self.set_border_width(10)

        self.dbstate = dbstate
        self.uistate = uistate
        self.person_handle = person_handle
        self.parsed = parsed
        self.attacher = attacher or NaraRecordAttacher(dbstate.db)
        self.review = self.attacher.review(person_handle, parsed)
        self.result: AttachResult | None = None
        self.pages, self.text_status = self._load_pages(client)

        content = self.get_content_area()
        content.set_spacing(8)
        content.pack_start(self._build_header(), False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.pack1(self._build_existing_side(), True, False)
        paned.pack2(self._build_record_side(), True, False)
        content.pack_start(paned, True, True, 0)

        self.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
        self.btn_attach = self.add_button(_("A_ttach"), Gtk.ResponseType.OK)
        self.btn_attach.get_style_context().add_class("suggested-action")
        self.btn_attach.set_tooltip_text(
            _(
                "Attach the citation to the person and add the checked images. "
                "Only new images are downloaded."
            )
        )

        self.cb_select_new()
        self.show_all()

    # ------------------------------------------------------------------
    # Page text
    # ------------------------------------------------------------------
    def _load_pages(self, client: Any) -> tuple[dict[int, PageInfo], str]:
        """
        Fetch the record's page text and classify each page.

        :returns: PageInfo by image index (empty without text) and a status
            line saying where the text came from.
        """
        naid = str(self.parsed.get("naid") or "")
        if client is None or not naid:
            return {}, _("Page text: not available.")
        try:
            texts = client.fetch_record_text(naid)
        except Exception as err:
            LOG.warning("NARA page text for %s failed: %s", naid, err)
            texts = None
        if texts is None:
            return {}, _(
                "Page text: NARA did not return it, so pages are not identified."
            )
        person = self.dbstate.db.get_person_from_handle(self.person_handle)
        filenames = [image.filename for image in self.review.images]
        page_texts = [texts.get(image.object_id, "") for image in self.review.images]
        infos = classify_pages(filenames, page_texts, person_names(person))
        with_text = sum(1 for text in page_texts if text.strip())
        status = _(
            "Page text: read from NARA (one API call); %(count)d of %(total)d "
            "pages have text. Page types are guesses from that text."
        ) % {"count": with_text, "total": len(page_texts)}
        return {
            image.index: info for image, info in zip(self.review.images, infos)
        }, status

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_header(self) -> Any:
        """Return the header: target person, record title and details."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        person = self.dbstate.db.get_person_from_handle(self.person_handle)
        name = person.get_primary_name().get_name() if person else ""
        gid = person.get_gramps_id() if person else ""
        target = Gtk.Label()
        target.set_xalign(0.0)
        target.set_markup(
            _("Attach to: <b>%(name)s</b> (%(id)s)")
            % {"name": GLib.markup_escape_text(name), "id": gid}
        )
        box.pack_start(target, False, False, 0)

        title = Gtk.Label()
        title.set_xalign(0.0)
        title.set_line_wrap(True)
        title.set_selectable(True)
        title.set_markup(
            "<big><b>%s</b></big>"
            % GLib.markup_escape_text(self.parsed.get("title") or "")
        )
        box.pack_start(title, False, False, 0)

        details = [_("NAID %s") % self.parsed.get("naid", "")]
        if self.parsed.get("series_title"):
            details.append(_("Series: %s") % self.parsed["series_title"])
        if self.parsed.get("date_str"):
            details.append(self.parsed["date_str"])
        details_label = Gtk.Label(label=" · ".join(details))
        details_label.set_xalign(0.0)
        details_label.set_line_wrap(True)
        details_label.set_selectable(True)
        box.pack_start(details_label, False, False, 0)

        if self.parsed.get("web_url"):
            link = Gtk.LinkButton(
                uri=self.parsed["web_url"],
                label=_("Open in the National Archives Catalog"),
            )
            link.set_halign(Gtk.Align.START)
            box.pack_start(link, False, False, 0)
        return box

    def _build_existing_side(self) -> Any:
        """Return the left side: the person's existing NARA citations."""
        frame = Gtk.Frame(label=_("Already in your tree for this person"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)
        frame.add(box)

        if not self.review.person_citations:
            empty = Gtk.Label(label=_("This person has no NARA citations yet."))
            empty.set_xalign(0.0)
            box.pack_start(empty, False, False, 0)
            return frame

        store = Gtk.ListStore(str, str, str, str)
        for existing in self.review.person_citations:
            page = existing.page
            if existing.is_this_record:
                page = _("%s (this record)") % page
            store.append(
                [page, existing.source_title, existing.naid, str(existing.media_count)]
            )
        view = Gtk.TreeView(model=store)
        for column, (heading, expand) in enumerate(
            [
                (_("Citation"), True),
                (_("Source"), True),
                (_("NAID"), False),
                (_("Images"), False),
            ]
        ):
            renderer = Gtk.CellRendererText()
            tree_column = Gtk.TreeViewColumn(heading, renderer, text=column)
            tree_column.set_resizable(True)
            tree_column.set_expand(expand)
            view.append_column(tree_column)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(view)
        box.pack_start(scroll, True, True, 0)
        return frame

    def _build_record_side(self) -> Any:
        """Return the right side: this record's citation and images."""
        frame = Gtk.Frame(label=_("This NARA record"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(6)
        frame.add(box)

        citation_label = Gtk.Label(label=citation_text(self.review))
        citation_label.set_xalign(0.0)
        citation_label.set_line_wrap(True)
        box.pack_start(citation_label, False, False, 0)

        self.image_store = Gtk.ListStore(bool, int, str, str, str, int, bool, str, str)
        for image in self.review.images:
            info = self.pages.get(image.index)
            self.image_store.append(
                [
                    False,
                    info.page if info else page_number(image.filename, image.index),
                    image.filename,
                    format_size(image.size),
                    status_text(image.status),
                    image.index,
                    image.status != IMAGE_LINKED,
                    info.label if info else "",
                    ", ".join(info.mentions) if info else "",
                ]
            )
        self.image_view = Gtk.TreeView(model=self.image_store)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self.cb_image_toggled)
        check_column = Gtk.TreeViewColumn(
            "", toggle, active=COL_SELECTED, activatable=COL_SELECTABLE
        )
        self.image_view.append_column(check_column)
        for heading, column, expand in [
            (_("Page"), COL_NUMBER, False),
            (_("Probably"), COL_PROBABLY, True),
            (_("Mentions"), COL_MENTIONS, False),
            (_("File"), COL_FILENAME, True),
            (_("Size"), COL_SIZE, False),
            (_("Status"), COL_STATUS, False),
        ]:
            renderer = Gtk.CellRendererText()
            tree_column = Gtk.TreeViewColumn(heading, renderer, text=column)
            tree_column.set_resizable(True)
            tree_column.set_expand(expand)
            self.image_view.append_column(tree_column)
        self.image_view.connect("row-activated", self.cb_row_activated)
        self.image_view.connect("cursor-changed", self.cb_cursor_changed)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.image_view)
        box.pack_start(scroll, True, True, 0)

        self.text_status_label = Gtk.Label(label=self.text_status)
        self.text_status_label.set_xalign(0.0)
        self.text_status_label.set_line_wrap(True)
        box.pack_start(self.text_status_label, False, False, 0)
        self.page_text_view = Gtk.TextView()
        self.page_text_view.set_editable(False)
        self.page_text_view.set_cursor_visible(False)
        self.page_text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.page_text_view.set_tooltip_text(
            _(
                "The highlighted page's text, machine-read by the National "
                "Archives Catalog. Handwriting often comes out garbled."
            )
        )
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_min_content_height(120)
        text_scroll.add(self.page_text_view)
        box.pack_start(text_scroll, False, True, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, tooltip, handler in [
            (
                _("Select _New"),
                _("Check only the images your tree does not have."),
                self.cb_select_new,
            ),
            (_("Select _All"), _("Check every image."), self.cb_select_all),
            (_("Select N_one"), _("Uncheck every image."), self.cb_select_none),
            (
                _("_Preview"),
                _(
                    "Download just the highlighted image and open it. A later "
                    "Attach reuses the downloaded copy."
                ),
                self.cb_preview,
            ),
        ]:
            button = Gtk.Button(label=label, use_underline=True)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", handler)
            buttons.pack_start(button, False, False, 0)
        box.pack_start(buttons, False, False, 0)

        self.download_check = Gtk.CheckButton(
            label=_("_Download the new images"), use_underline=True
        )
        self.download_check.set_active(True)
        self.download_check.set_tooltip_text(
            _(
                "Save the checked new images under the NARA folder of your media "
                "base path. Unchecked, they are linked by their web address."
            )
        )
        box.pack_start(self.download_check, False, False, 0)

        self.note_check = Gtk.CheckButton(
            label=_("Save each page's text as a _note on its image"),
            use_underline=True,
        )
        self.note_check.set_active(bool(self.pages))
        self.note_check.set_sensitive(bool(self.pages))
        self.note_check.set_tooltip_text(
            _(
                "Add NARA's machine-read text to each new image as a Transcript "
                "note, so it can be searched in Gramps."
            )
        )
        box.pack_start(self.note_check, False, False, 0)

        self.summary_label = Gtk.Label()
        self.summary_label.set_xalign(0.0)
        self.summary_label.set_line_wrap(True)
        box.pack_start(self.summary_label, False, False, 0)
        return frame

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def selected_indexes(self) -> set[int]:
        """Return the indexes of the checked images."""
        selected = set()
        tree_iter = self.image_store.get_iter_first()
        while tree_iter is not None:
            if self.image_store.get_value(tree_iter, COL_SELECTED):
                selected.add(int(self.image_store.get_value(tree_iter, COL_INDEX)))
            tree_iter = self.image_store.iter_next(tree_iter)
        return selected

    def _set_selection(self, wanted: set[int]) -> None:
        """Check exactly the images whose indexes are in 'wanted'."""
        tree_iter = self.image_store.get_iter_first()
        while tree_iter is not None:
            index = int(self.image_store.get_value(tree_iter, COL_INDEX))
            selectable = bool(self.image_store.get_value(tree_iter, COL_SELECTABLE))
            self.image_store.set_value(
                tree_iter, COL_SELECTED, selectable and index in wanted
            )
            tree_iter = self.image_store.iter_next(tree_iter)
        self._update_summary()

    def _update_summary(self) -> None:
        """Refresh the selection summary and the Attach button."""
        selected = self.selected_indexes()
        self.summary_label.set_text(selection_summary(self.review, selected))
        self.btn_attach.set_sensitive(has_work(self.review, selected))

    def cb_select_new(self, _widget: Any = None) -> None:
        """Check only the new images."""
        self._set_selection({image.index for image in self.review.new_images})

    def cb_select_all(self, _widget: Any = None) -> None:
        """Check every image that can be checked."""
        self._set_selection({image.index for image in self.review.images})

    def cb_select_none(self, _widget: Any = None) -> None:
        """Uncheck every image."""
        self._set_selection(set())

    def cb_image_toggled(self, _renderer: Any, path: str) -> None:
        """Flip one image's checkbox."""
        tree_iter = self.image_store.get_iter(path)
        if not self.image_store.get_value(tree_iter, COL_SELECTABLE):
            return
        current = bool(self.image_store.get_value(tree_iter, COL_SELECTED))
        self.image_store.set_value(tree_iter, COL_SELECTED, not current)
        self._update_summary()

    def page_text(self, index: int) -> str:
        """Return the text to show for an image (or why there is none)."""
        info = self.pages.get(index)
        if info is None:
            return _("No page text is available for this record.")
        if not info.text.strip():
            return _("NARA has no text for this page.")
        return info.text.strip()

    def cb_cursor_changed(self, _view: Any = None) -> None:
        """Show the highlighted page's text."""
        image = self._highlighted_image()
        text = self.page_text(image.index) if image is not None else ""
        self.page_text_view.get_buffer().set_text(text)

    def cb_row_activated(self, _view: Any, _path: Any, _column: Any) -> None:
        """Preview an image on double-click."""
        self.cb_preview()

    # ------------------------------------------------------------------
    # Preview and attach
    # ------------------------------------------------------------------
    def _highlighted_image(self) -> Any:
        """Return the ImageStatus of the highlighted row, or None."""
        model, tree_iter = self.image_view.get_selection().get_selected()
        if tree_iter is None:
            return None
        index = int(model.get_value(tree_iter, COL_INDEX))
        for image in self.review.images:
            if image.index == index:
                return image
        return None

    def cb_preview(self, _widget: Any = None) -> None:
        """Download the highlighted image (if needed) and open it."""
        image = self._highlighted_image()
        if image is None:
            self.summary_label.set_text(_("Highlight an image to preview it."))
            return
        from gramps.gen.utils.file import media_path_full
        from gramps.gui.utils import open_file_with_default_application

        if image.media_path:
            path = media_path_full(self.dbstate.db, image.media_path)
        else:
            self.summary_label.set_text(
                _("Downloading %s for preview...") % image.filename
            )
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            path = self.attacher.download_one(self.parsed, image)
        self._update_summary()
        if not path:
            self.summary_label.set_text(
                _("%s could not be downloaded for preview.") % image.filename
            )
            return
        open_file_with_default_application(path, self.uistate)

    def run_attach(self) -> AttachResult | None:
        """
        Attach the citation and the checked images, with a progress window
        for downloads, and return what was done (None on failure).
        """
        from gramps.gui.utils import ProgressMeter

        selected = self.selected_indexes()
        download = bool(self.download_check.get_active())
        to_download = [
            image for image in self.review.new_images if image.index in selected
        ]
        meter = None
        if download and to_download:
            meter = ProgressMeter(_("Attach NARA Record"), can_cancel=True, parent=self)
            meter.set_pass(
                _("Downloading %d images from NARA...") % len(to_download),
                len(to_download),
            )

        def progress(_done: int, _total: int) -> bool:
            if meter is None:
                return True
            meter.step()
            return not meter.get_cancelled()

        try:
            title = str(self.parsed.get("title") or self.parsed.get("naid") or "")
            descriptions = {
                index: page_description(title, info)
                for index, info in self.pages.items()
            }
            page_texts = (
                {index: info.text for index, info in self.pages.items()}
                if self.note_check.get_active()
                else {}
            )
            self.result = self.attacher.attach(
                self.person_handle,
                self.parsed,
                download=download,
                progress=progress,
                selected=sorted(selected),
                descriptions=descriptions,
                page_texts=page_texts,
            )
        except Exception as err:
            LOG.warning(
                "Failed to attach NARA record %s: %s", self.parsed.get("naid"), err
            )
            self.summary_label.set_text(
                _("Could not attach the NARA record: %s") % str(err)
            )
            self.result = None
        finally:
            if meter is not None:
                meter.close()
        return self.result
