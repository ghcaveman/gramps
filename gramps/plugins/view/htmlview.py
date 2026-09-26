#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  The Gramps Project
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
HTML view for capturing debug input and rendering simple HTML.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

import html
import urllib.parse
from typing import Any
import logging
from html.parser import HTMLParser

LOG = logging.getLogger(".htmlview")

# -------------------------------------------------------------------------
#
# GTK/Gnome modules
#
# -------------------------------------------------------------------------
try:
    from gi.repository import Gtk
    from gi.repository import Gdk
except ImportError:
    pass

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
try:
    from gramps.gui.views.pageview import PageView
    from gramps.gui.htmlbridge import HtmlBridge

    _HAS_GUI = True
except ImportError:

    class PageView:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass

    _HAS_GUI = False

from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext

# Determine if Selenium scraping support is available.  This mirrors the logic
# used in the html_view_playwright branch where the rendering engine label
# reflects the backend in use.
try:
    from gramps.plugins.gramplet.scraper import scrape_page_async  # noqa: F401
    _USE_SELENIUM = True
except Exception:  # pragma: no cover – Selenium not installed
    _USE_SELENIUM = False


# ------------------------------------------------------------
#
# HTMLToPangoParser
#
# ------------------------------------------------------------
class HTMLToPangoParser(HTMLParser):
    """
    A lightweight HTML parser that converts basic HTML markup to Pango markup.
    """

    # Formatting tags that nest and must be tracked on the open-tags stack.
    _STACKABLE = {"b", "strong", "i", "em", "u", "s", "sub", "sup"}

    # Map each start tag to the canonical form used on the stack.
    # "strong" and "b" both map to "b"; "em" and "i" both map to "i".
    _CANONICAL: dict[str, str] = {
        "strong": "b",
        "em": "i",
    }

    def __init__(self) -> None:
        """
        Initialise the parser.
        """
        super().__init__()
        self.result: list[str] = []
        self.ignore_content = False
        self.ignore_tags = {"script", "style", "head", "title"}
        # Set when inside an <a> tag without a href attribute.
        # Such anchors are rendered as plain text because Pango markup
        # requires href on every <a> element.
        self.in_bare_a = False
        # Stack of currently open formatting tags (canonical forms).
        # Used to auto-close tags in the correct order when the HTML
        # contains improperly nested tags (e.g. <b><i>text</b></i>).
        self._open_tags: list[str] = []

    def _canonical(self, tag: str) -> str:
        """Return the canonical stack key for *tag*."""
        return self._CANONICAL.get(tag, tag)

    def _close_open_until(self, tag: str) -> None:
        """Close formatting tags from the top of the stack down to and
        including *tag* (canonical form).

        Tags that are not on the stack are not closed.
        """
        while self._open_tags:
            top = self._open_tags[-1]
            if top == tag:
                self._open_tags.pop()
                self.result.append(f"</{top}>")
                return
            self._open_tags.pop()
            self.result.append(f"</{top}>")

    def _emit_start(self, tag: str) -> None:
        """Emit a start tag and push its canonical form onto the stack."""
        canon = self._canonical(tag)
        self.result.append(f"<{canon}>")
        self._open_tags.append(canon)

    def done(self) -> None:
        """Call after feeding all HTML to close any still-open formatting
        tags. This ensures the resulting Pango markup is well-formed.
        """
        self._close_open_until(None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """
        Handle start tags.
        """
        if tag in self.ignore_tags:
            self.ignore_content = True
            return
        if self.ignore_content:
            return

        if tag in ("b", "strong"):
            self._emit_start("b")
        elif tag in ("i", "em"):
            self._emit_start("i")
        elif tag == "u":
            self._emit_start("u")
        elif tag == "s":
            self._emit_start("s")
        elif tag == "sub":
            self._emit_start("sub")
        elif tag == "sup":
            self._emit_start("sup")
        elif tag in ("h1", "h2", "h3"):
            self.result.append("\n\n<big>")
            self._emit_start("b")
        elif tag in ("h4", "h5", "h6"):
            self._emit_start("b")
        elif tag in ("p", "div"):
            # Browsers break inline formatting at block boundaries:
            # close any open formatting tags before appending a paragraph break.
            self._close_open_until(None)
            self.result.append("\n\n")
        elif tag == "br":
            self.result.append("\n")
        elif tag == "a":
            href = ""
            for name, val in attrs:
                if name == "href" and val:
                    href = html.escape(val)
                    break
            if href:
                self._emit_start("a")
                self.result[-1] = f'<a href="{href}">'
            else:
                # No href: render the link text as plain text only.
                self.in_bare_a = True

    def handle_endtag(self, tag: str) -> None:
        """
        Handle end tags.
        """
        if tag in self.ignore_tags:
            self.ignore_content = False
            return
        if self.ignore_content:
            return

        if tag in ("b", "strong"):
            self._close_open_until("b")
        elif tag in ("i", "em"):
            self._close_open_until("i")
        elif tag == "u":
            self._close_open_until("u")
        elif tag == "s":
            self._close_open_until("s")
        elif tag == "sub":
            self._close_open_until("sub")
        elif tag == "sup":
            self._close_open_until("sup")
        elif tag in ("h1", "h2", "h3"):
            # Close any still-open formatting tags before the heading close.
            self._close_open_until(None)
            self.result.append("</big>\n")
        elif tag in ("h4", "h5", "h6"):
            self._close_open_until(None)
        elif tag in ("p", "div"):
            self._close_open_until(None)
            self.result.append("\n")
        elif tag == "a":
            if not self.in_bare_a:
                self._close_open_until("a")
            self.in_bare_a = False

    def handle_data(self, data: str) -> None:
        """
        Handle textual data.
        """
        if self.ignore_content:
            return
        self.result.append(html.escape(data))

    def get_pango_markup(self) -> str:
        """
        Get the resulting Pango markup.

        :returns: Pango XML markup text.
        :rtype: str
        """
        self.done()
        text = "".join(self.result).strip()
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text


# ------------------------------------------------------------
#
# HTMLView
#
# ------------------------------------------------------------
class HTMLView(PageView):
    """
    HTMLView interface for developer/debug usage.
    """

    _instance: HTMLView | None = None

    def __init__(self, pdata, dbstate, uistate):
        """
        Create an HTMLView with the current dbstate and uistate.
        """
        PageView.__init__(self, _("HTML"), pdata, dbstate, uistate)
        # Keep the default PageView ui_def so the View menu offers the
        # standard Sidebar/Bottombar toggles like every other view.
        HTMLView._instance = self
        if _HAS_GUI:
            HtmlBridge.register_view(self)

        self.text_view = None
        self.text_buffer = None
        self.render_label = None
        self.header_label = None
        self._search_url = ""

    @classmethod
    def set_html_text(cls, text: str, url: str = "") -> None:
        """
        Set the HTML text of the active HTMLView instance.

        :param text: The HTML content to display.
        :param url: Optional origin URL of the content; when given it is
            shown in the header and used to pick the result filter.
        """
        if cls._instance is not None:
            if url:
                cls._instance.set_search_url(url)
            cls._instance.set_text(text)

    @classmethod
    def append_html_text(cls, text: str, url: str = "") -> None:
        """
        Append text to the active HTMLView instance.

        :param text: The HTML content to append.
        :param url: Optional origin URL of the content.
        """
        if cls._instance is not None:
            if url:
                cls._instance.set_search_url(url)
            cls._instance.append_text(text)

    def set_active(self) -> None:
        """
        Set the view active and deliver any content routed to the
        bridge before this page was opened.
        """
        PageView.set_active(self)
        self._update_header()
        if _HAS_GUI:
            HtmlBridge.flush_pending(self)

    def set_inactive(self) -> None:
        """
        Mark the view inactive.
        """
        PageView.set_inactive(self)

    def on_delete(self, *args):
        """
        Unregister from the bridge when the view page is destroyed.
        """
        if _HAS_GUI:
            HtmlBridge.unregister_view(self)
        return PageView.on_delete(self, *args)

    def build_widget(self) -> Gtk.Box:
        """
        Builds the container widget for the interface.
        Returns a gtk container widget.

        :returns: The built container widget.
        :rtype: Gtk.Box
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Person / search context header at the very top of the view
        self.header_label = Gtk.Label()
        self.header_label.set_xalign(0.0)
        self.header_label.set_line_wrap(True)
        self.header_label.set_selectable(True)
        self.header_label.set_use_markup(True)
        self.header_label.set_margin_left(6)
        self.header_label.set_margin_right(6)
        self.header_label.set_margin_top(6)
        self.header_label.set_margin_bottom(0)
        self.header_label.set_visible(False)
        box.pack_start(self.header_label, False, False, 0)

        # Toolbar / Control box at the top
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_border_width(6)

        clear_btn = Gtk.Button(label=_("Clear"))
        clear_btn.connect("clicked", self.cb_clear_text)
        toolbar.pack_start(clear_btn, False, False, 0)

        paste_btn = Gtk.Button(label=_("Paste from Clipboard"))
        paste_btn.connect("clicked", self.cb_paste_text)
        toolbar.pack_start(paste_btn, False, False, 0)

        # Container for the info label and rendering‑engine textbox.
        top_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        top_hbox.set_homogeneous(False)

        info_label = Gtk.Label(
            label=_("Capturing debug input for WebSearch and Grizard functionality")
        )
        info_label.set_alignment(1.0, 0.5)
        # Align the label text to the right edge of its container.
        info_label.set_xalign(1.0)

        # Rendering engine display – mirrors the Playwright branch which shows the
        # name of the engine (e.g., "Selenium") in a non‑editable label.
        engine_label = Gtk.Label()
        engine_label.set_selectable(True)
        # Show the engine being used; fallback to "Selenium" if unknown.
        engine_name = "Selenium" if _USE_SELENIUM else "Pango"
        engine_label.set_markup(f"<b>{engine_name}</b>")

        top_hbox.pack_start(engine_label, False, False, 0)
        top_hbox.pack_end(info_label, False, False, 0)
        # Add the container to the toolbar so it becomes visible.
        toolbar.pack_start(top_hbox, True, True, 0)

        box.pack_start(toolbar, False, False, 0)

        # Notebook for Render and Source tabs
        notebook = Gtk.Notebook()
        notebook.connect("switch-page", self.cb_switch_tab)

        # Tab 1: Render View
        render_scroll = Gtk.ScrolledWindow()
        render_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        render_scroll.set_shadow_type(Gtk.ShadowType.IN)

        self.render_label = Gtk.Label()
        self.render_label.set_alignment(0.0, 0.0)
        self.render_label.set_xalign(0.0)
        self.render_label.set_yalign(0.0)
        self.render_label.set_line_wrap(True)
        self.render_label.set_selectable(True)
        self.render_label.set_use_markup(True)
        self.render_label.set_margin_top(12)
        self.render_label.set_margin_bottom(12)
        self.render_label.set_margin_left(12)
        self.render_label.set_margin_right(12)

        render_scroll.add(self.render_label)
        notebook.append_page(render_scroll, Gtk.Label(label=_("Render")))

        # Tab 2: Source View
        source_scroll = Gtk.ScrolledWindow()
        source_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        source_scroll.set_shadow_type(Gtk.ShadowType.IN)

        self.text_view = Gtk.TextView()
        self.text_view.set_monospace(True)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_buffer = self.text_view.get_buffer()

        source_scroll.add(self.text_view)
        notebook.append_page(source_scroll, Gtk.Label(label=_("Source")))

        box.pack_start(notebook, True, True, 0)

        self.widget = box
        return self.widget

    def set_search_url(self, url: str) -> None:
        """
        Record the URL whose content is being displayed in the view.

        The root of the URL (scheme + host) is shown in the header at the
        top of the view so the source website of the information is always
        visible.

        :param url: The origin URL of the displayed content.
        """
        self._search_url = url or ""
        self._update_header()

    def _get_active_person(self) -> tuple[Any, Any]:
        """
        Return the active person and the database, or ``(None, None)``.

        :returns: Tuple of ``(person, db)``.
        """
        try:
            db = self.dbstate.db
            if db and db.is_open():
                handle = self.uistate.get_active("Person")
                if handle:
                    return db.get_person_from_handle(handle), db
        except Exception:
            pass
        return None, None

    def _get_search_root_url(self) -> str:
        """
        Return the root of the last searched URL (scheme + host), if any.
        """
        if not self._search_url:
            return ""
        try:
            parts = urllib.parse.urlsplit(self._search_url)
            if parts.scheme and parts.netloc:
                return f"{parts.scheme}://{parts.netloc}/"
        except Exception:
            pass
        return self._search_url

    def _update_header(self) -> None:
        """
        Rebuild the person / search header shown at the top of the view.

        Displays the active person's name, birth date and location, death
        date (if any), and the root URL of the website that was searched
        for the information. Hidden when there is nothing to show.
        """
        if not _HAS_GUI or self.header_label is None:
            return

        try:
            self._build_header_markup()
        except Exception as err:
            LOG.warning("Failed to build HTMLView header: %s", err)
            self.header_label.set_markup("")
            self.header_label.set_visible(False)

    def _build_header_markup(self) -> None:
        """
        Build and set the person / search header markup.
        """
        parts = []
        person, db = self._get_active_person()
        if person is not None and db is not None:
            from gramps.gen.display.name import displayer as name_displayer
            from gramps.gen.display.place import displayer as place_displayer
            from gramps.gen.datehandler import get_date
            from gramps.gen.lib import EventType

            name_str = name_displayer.display(person)
            parts.append(
                f'<span size="large" weight="bold">{html.escape(name_str)}</span>'
            )

            birth_date = ""
            birth_place = ""
            death_date = ""
            for event_ref in person.get_event_ref_list():
                if not event_ref:
                    continue
                try:
                    event = db.get_event_from_handle(event_ref.ref)
                except Exception:
                    continue
                if event is None:
                    continue
                if int(event.type) == EventType.BIRTH and not birth_date:
                    birth_date = get_date(event) or ""
                    if event.get_place_handle():
                        place = db.get_place_from_handle(event.get_place_handle())
                        if place is not None:
                            birth_place = place_displayer.display(db, place)
                elif int(event.type) == EventType.DEATH and not death_date:
                    death_date = get_date(event) or ""

            if birth_date or birth_place:
                born = _("Born:")
                birth_text = " ".join(
                    part for part in (birth_date, birth_place) if part
                )
                parts.append(f"{born} {html.escape(birth_text)}")
            if death_date:
                parts.append(f"{_('Died:')} {html.escape(death_date)}")

        root_url = self._get_search_root_url()
        if root_url:
            searched = _("Website searched:")
            parts.append(
                f'{searched} <a href="{html.escape(root_url)}">'
                f"{html.escape(root_url)}</a>"
            )

        if parts:
            self.header_label.set_markup("\n".join(parts))
            self.header_label.set_visible(True)
        else:
            self.header_label.set_markup("")
            self.header_label.set_visible(False)

    def set_text(self, text: str) -> None:
        """
        Set the text in the text view buffer and update the rendered view.

        :param text: The text to set.
        :type text: str
        """
        if self.text_buffer is not None:
            self.text_buffer.set_text(text)
        self._update_rendered_html()
        self._maybe_append_filtered_results()

    def append_text(self, text: str) -> None:
        """
        Append the text to the text view buffer and update the rendered view.

        :param text: The text to append.
        :type text: str
        """
        if self.text_buffer is not None:
            end_iter = self.text_buffer.get_end_iter()
            self.text_buffer.insert(end_iter, text)
        self._update_rendered_html()

    def _update_rendered_html(self) -> None:
        """
        Parse raw HTML from the text buffer and update the Pango-formatted label.
        """
        if self.text_buffer is None or self.render_label is None:
            return

        start_iter, end_iter = self.text_buffer.get_bounds()
        raw_html = self.text_buffer.get_text(start_iter, end_iter, True)

        if not raw_html.strip():
            self.render_label.set_markup("")
            return

        parser = HTMLToPangoParser()
        try:
            parser.feed(raw_html)
            pango_markup = parser.get_pango_markup()
            self.render_label.set_markup(pango_markup)
        except Exception as err:
            LOG.warning("Failed parsing HTML to Pango: %s", err)
            self.render_label.set_text(raw_html)

    def clear(self) -> None:
        """
        Clear the view content and reset the search context.
        """
        self._search_url = ""
        if self.text_buffer is not None:
            self.text_buffer.set_text("")
        if self.render_label is not None:
            self.render_label.set_markup("")

    def cb_clear_text(self, widget: Gtk.Button) -> None:
        """
        Callback for clear button clicked.

        :param widget: The button widget.
        :type widget: Gtk.Button
        """
        if self.text_buffer is not None:
            self.text_buffer.set_text("")
        if self.render_label is not None:
            self.render_label.set_markup("")

    def cb_paste_text(self, widget: Gtk.Button) -> None:
        """
        Callback for paste button clicked.

        :param widget: The button widget.
        :type widget: Gtk.Button
        """
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = clipboard.wait_for_text()
        if text:
            self.set_text(text)

    def cb_switch_tab(
        self, notebook: Gtk.Notebook, page: Gtk.Widget, page_num: int
    ) -> None:
        """
        Callback for when notebook tabs are switched.

        :param notebook: The notebook widget.
        :type notebook: Gtk.Notebook
        :param page: The page widget being switched to.
        :type page: Gtk.Widget
        :param page_num: The index of the page being switched to.
        :type page_num: int
        """
        if page_num == 0:  # Render tab
            self._update_rendered_html()

    # -------------------------------------------------------------------------
    #
    # Grizard - WebSearch display methods
    #
    # -------------------------------------------------------------------------

    def set_search_person_header(
        self, person: Any, website_name: str, website_url: str = ""
    ) -> None:
        """
        Set the HTML content to display a person search header.

        This displays the person's name, birth/death info, and the website
        being searched at the top of the view.

        :param person: The Person object to display.
        :param website_name: Name of the website (e.g., "FamilySearch").
        :param website_url: Optional URL to the website.
        """
        from gramps.gen.display.name import displayer as name_displayer
        from gramps.gen.display.place import displayer as place_displayer
        from gramps.gen.datehandler import get_date

        db = person.handle.get_db() if hasattr(person, "handle") else None

        # Get person name
        name_str = name_displayer.display(db, person) if db else str(person)

        # Get birth info
        birth_date = ""
        birth_place = ""
        if db:
            for event_ref in person.event_ref_list:
                if not event_ref:
                    continue
                event = db.get_event_from_handle(event_ref.ref)
                if event and event.type.value == "BIRTH":
                    birth_date = get_date(event.date) or ""
                    if event.place:
                        place = db.get_place_from_handle(event.place)
                        if place:
                            birth_place = place_displayer.display(db, place)
                    break

        # Get death info
        death_date = ""
        if db:
            for event_ref in person.event_ref_list:
                if not event_ref:
                    continue
                event = db.get_event_from_handle(event_ref.ref)
                if event and event.type.value == "DEATH":
                    death_date = get_date(event.date) or ""
                    break

        # Build HTML header
        html_parts = [
            '<div style="',
            "margin-bottom: 20px; ",
            "padding: 12px; ",
            "border: 1px solid #ccc; ",
            "background: #f8f9fa; ",
            'border-radius: 4px;">',
            f'<h2 style="margin-top: 0; color: #333;">Searching for: {html.escape(name_str)}</h2>',
            '<table border="0" cellpadding="4" style="width: 100%;">',
            '<tr><td style="width: 120px; vertical-align: top; color: #666;"><b>Website:</b></td>',
            f'<td style="color: #0066cc; font-weight: bold;">{html.escape(website_name)}</td></tr>',
        ]

        if birth_date or birth_place:
            html_parts.append(
                '<tr><td style="vertical-align: top; color: #666;"><b>Born:</b></td><td>'
            )
            if birth_date:
                html_parts.append(html.escape(birth_date))
            if birth_place:
                if birth_date:
                    html_parts.append(" - ")
                html_parts.append(html.escape(birth_place))
            html_parts.append("</td></tr>")

        if death_date:
            html_parts.append(
                '<tr><td style="vertical-align: top; color: #666;"><b>Died:</b></td>'
                f"<td>{html.escape(death_date)}</td></tr>"
            )

        # Add website link if provided
        if website_url:
            html_parts.append(
                '<tr><td style="vertical-align: top; color: #666;"><b>Link:</b></td>'
                f'<td><a href="{html.escape(website_url)}" style="color: #0066cc;">{html.escape(website_url)}</a></td></tr>'
            )

        html_parts.append("</table></div>")

        self.set_text("\n".join(html_parts))

    def add_filter_results_table(
        self,
        results: list[dict[str, Any]],
        clear_first: bool = True,
        title: str = "",
    ) -> None:
        """
        Add a filter results table to the view.

        Displays search results in a table format with columns for name,
        birth, death, details, and a link to the source.

        :param results: List of result dictionaries with keys:
            - name: Person name
            - birth: Birth date/string
            - death: Death date/string
            - details: Description/details
            - url: Optional URL to the record
            - website: Website name (optional, defaults to "Source")
        :param clear_first: If True, clear existing content first.
        :param title: Optional heading shown above the table.
        """
        if clear_first:
            self.clear()

        if not results:
            self.set_text("<p>No search results</p>")
            return

        # Build table HTML
        html_parts = []
        if title:
            html_parts.append(f'<h3 style="color: #333;">{html.escape(title)}</h3>')
        html_parts = html_parts + [
            '<table border="1" cellpadding="4" cellspacing="0" '
            'style="border-collapse: collapse; width: 100%; margin-top: 20px;">'
        ]
        html_parts.append(
            "<thead><tr>"
            '<th style="background-color: #f0f0f0; padding: 8px;">Name</th>'
            '<th style="background-color: #f0f0f0; padding: 8px;">Birth</th>'
            '<th style="background-color: #f0f0f0; padding: 8px;">Death</th>'
            '<th style="background-color: #f0f0f0; padding: 8px;">Details</th>'
            '<th style="background-color: #f0f0f0; padding: 8px;">Source</th>'
            "</tr></thead>"
        )
        html_parts.append("<tbody>")

        for result in results:
            name = html.escape(str(result.get("name", "Unknown")))
            birth = html.escape(str(result.get("birth", "-")))
            death = html.escape(str(result.get("death", "-")))
            details = html.escape(str(result.get("details", "")))
            result_url = html.escape(str(result.get("url", "")))
            website = html.escape(str(result.get("website", "Source")))

            # Create link if URL provided
            if result_url:
                link_html = (
                    f'<a href="{result_url}" style="color: #0066cc;">{website}</a>'
                )
            else:
                link_html = website

            html_parts.append(
                "<tr>"
                f'<td style="padding: 6px;">{name}</td>'
                f'<td style="padding: 6px;">{birth}</td>'
                f'<td style="padding: 6px;">{death}</td>'
                f'<td style="padding: 6px;">{details}</td>'
                f'<td style="padding: 6px;">{link_html}</td>'
                "</tr>"
            )

        html_parts.append("</tbody></table>")
        self.set_text("\n".join(html_parts))

    def append_filter_results_table(
        self, results: list[dict[str, Any]], title: str = ""
    ) -> None:
        """
        Append a filter results table at the bottom of the current content.

        Used to display search results extracted (filtered) from the web
        page shown in the view, below the page content itself.

        :param results: List of result dictionaries (same keys as
            add_filter_results_table).
        :param title: Optional heading shown above the table.
        """
        if not results:
            return

        html_parts = ["<hr>"]
        if title:
            html_parts.append(f'<h3 style="color: #333;">{html.escape(title)}</h3>')
        else:
            html_parts.append(f'<h3 style="color: #333;">{_("Search results")}</h3>')

        html_parts.append(
            '<table border="1" cellpadding="4" cellspacing="0" '
            'style="border-collapse: collapse; width: 100%; margin-top: 10px;">'
        )
        html_parts.append(
            "<thead><tr>"
            '<th style="background-color: #f0f0f0; padding: 8px;">Name</th>'
            '<th style="background-color: #f0f0f0; padding: 8px;">Birth</th>'
            '<th style="background-color: #f0f0f0; padding: 8px;">Death</th>'
            '<th style="background-color: #f0f0f0; padding: 8px;">Details</th>'
            '<th style="background-color: #f0f0f0; padding: 8px;">Source</th>'
            "</tr></thead>"
        )
        html_parts.append("<tbody>")

        for result in results:
            name = html.escape(str(result.get("name", "Unknown")))
            birth = html.escape(str(result.get("birth", "-")) or "-")
            death = html.escape(str(result.get("death", "-")) or "-")
            details = html.escape(str(result.get("details", "")))
            result_url = html.escape(str(result.get("url", "")))
            website = html.escape(str(result.get("website", "Source")))

            if result_url:
                link_html = (
                    f'<a href="{result_url}" style="color: #0066cc;">{website}</a>'
                )
            else:
                link_html = website

            html_parts.append(
                "<tr>"
                f'<td style="padding: 6px;">{name}</td>'
                f'<td style="padding: 6px;">{birth}</td>'
                f'<td style="padding: 6px;">{death}</td>'
                f'<td style="padding: 6px;">{details}</td>'
                f'<td style="padding: 6px;">{link_html}</td>'
                "</tr>"
            )

        html_parts.append("</tbody></table>")
        self.append_text("\n".join(html_parts))

    def _maybe_append_filtered_results(self) -> None:
        """
        Filter the current page content through the matching WebSearch
        filter and append a results table at the bottom of the view.

        The filter is picked by the URL the content came from; when no
        URL is known (e.g. pasted content), each known filter's link
        pattern is tried against the content itself.
        """
        if self.text_buffer is None:
            return
        try:
            from gramps.gen.filters.rules.websearch import (
                WEBSEARCH_FILTER_CLASSES,
                get_websearch_filter_for_url,
            )

            start_iter, end_iter = self.text_buffer.get_bounds()
            page_html = self.text_buffer.get_text(start_iter, end_iter, True)
            if not page_html.strip():
                return

            web_filter = None
            if self._search_url:
                web_filter = get_websearch_filter_for_url(self._search_url)
            else:
                # No URL known: sniff the content for result links
                for filter_class in WEBSEARCH_FILTER_CLASSES:
                    candidate = filter_class()
                    if candidate.RESULT_HREF_PATTERN and candidate.parse_results(
                        page_html, ""
                    ):
                        web_filter = candidate
                        break

            if web_filter is None or not web_filter.RESULT_HREF_PATTERN:
                return

            results = web_filter.parse_results(page_html, self._search_url)
            if results:
                self.append_filter_results_table(
                    results,
                    title=_("Search results (%s)") % web_filter.WEBSITE_NAME,
                )
                LOG.info(
                    "HTMLView: appended %d filtered result(s) from %s",
                    len(results),
                    web_filter.WEBSITE_NAME,
                )
        except Exception as err:
            LOG.warning("Failed to filter web page results: %s", err)

    def add_filter_result(
        self,
        name: str,
        birth: str = "",
        death: str = "",
        details: str = "",
        url: str = "",
        website: str = "Source",
        clear_first: bool = True,
    ) -> None:
        """
        Add a single filter result to the view.

        Convenience method that wraps a single result in a list and calls
        add_filter_results_table.

        :param name: Person name.
        :param birth: Birth date/string.
        :param death: Death date/string.
        :param details: Description/details.
        :param url: Optional URL to the record.
        :param website: Website name.
        :param clear_first: If True, clear existing content first.
        """
        result = {
            "name": name,
            "birth": birth,
            "death": death,
            "details": details,
            "url": url,
            "website": website,
        }
        self.add_filter_results_table([result], clear_first=clear_first)

    def build_tree(self) -> None:
        """
        Rebuilds the current display.
        """
        pass

    def build_interface(self):
        """
        Builds the container widget for the interface.
        Returns a gtk container widget.
        """
        top = PageView.build_interface(self)
        top.show_all()
        return top

    def get_default_gramplets(self):
        """
        Define the default gramplets for the sidebar and bottombar.

        Matches the People view so its gramplets (Details, Attributes,
        Events, etc.) carry over, with GrizardResults added at the end.
        """
        return (
            ("Person Filter",),
            (
                "Person Details",
                "Person Gallery",
                "Person Events",
                "Person Children",
                "Person Citations",
                "Person Notes",
                "Person Attributes",
                "Person Backlinks",
                "GrizardResults",
            ),
        )

    def navigation_type(self):
        """
        Indicate the navigation type of this view.

        Uses "Person" (like the Relationship and Charts views) so the
        Person gramplets from the People view are available here and the
        active person carries over.

        :returns: The navigation type.
        """
        return "Person"

    def get_title(self) -> str:
        """
        Used to set the titlebar in the configuration window.

        :returns: The title of the view.
        :rtype: str
        """
        return _("HTML")

    def get_stock(self) -> str:
        """
        Return image associated with the view, which is used for the
        icon for the button.

        :returns: Stock icon name.
        :rtype: str
        """
        return "gramps-view"

    def get_viewtype_stock(self) -> str:
        """
        Type of view in category.

        :returns: Stock icon name.
        :rtype: str
        """
        return "gramps-view"

    def define_actions(self) -> None:
        """
        Define the standard view actions (Sidebar/Bottombar toggles).
        """
        PageView.define_actions(self)
