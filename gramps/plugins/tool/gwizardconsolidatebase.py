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

"""Shared base dialog for the GWizard repository / source consolidate steps."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
from html import escape
import logging
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
from gramps.gui.dialog import ErrorDialog, OkDialog

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# ConsolidateDialogBase
#
# ------------------------------------------------------------
class ConsolidateDialogBase(Gtk.Dialog):
    """Pick one record on the left and merge it into a target on the right.

    Subclasses provide get_handles, get_label and merge.
    """

    def __init__(
        self,
        title: str,
        dbstate: Any,
        transient_for: Gtk.Window | None = None,
        default_size: tuple[int, int] | None = None,
        has_hint_column: bool = False,
    ) -> None:
        super().__init__(
            title=title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.has_hint_column = has_hint_column
        self.hint_target_handle: str | None = None
        self.target_handles: list[str] = []
        self.radio_buttons: dict[str, Gtk.RadioButton] = {}
        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dlg, resp: dlg.destroy())
        if default_size:
            self.set_default_size(*default_size)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        intro = Gtk.Label(
            label=str(
                _(
                    "Select the record to remove on the left, then choose the "
                    "record to merge it into on the right."
                )
            )
        )
        intro.set_line_wrap(True)
        intro.set_halign(Gtk.Align.START)
        content.add(intro)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_vexpand(True)
        box.set_hexpand(True)
        content.add(box)

        self.handles = sorted(
            self.get_handles(), key=lambda h: self.get_label(h).lower()
        )
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_min_content_height(240)
        left_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        left_scroll.add(left)
        group = None
        for handle in self.handles:
            radio = Gtk.RadioButton.new_with_label_from_widget(
                group, self.get_label(handle)
            )
            if group is None:
                group = radio
            radio.connect("toggled", self.cb_selection_changed)
            self.radio_buttons[handle] = radio
            left.pack_start(radio, False, False, 0)

        if self.has_hint_column:
            # Column 1: Record to remove
            col1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            col1_head = Gtk.Label()
            col1_head.set_markup("<b>%s</b>" % str(_("Source to remove")))
            col1_head.set_halign(Gtk.Align.START)
            col1.pack_start(col1_head, False, False, 0)
            col1.pack_start(left_scroll, True, True, 0)
            box.pack_start(col1, True, True, 0)

            # Column 2: Merge target
            col2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            col2_head = Gtk.Label()
            col2_head.set_markup("<b>%s</b>" % str(_("Merge into (target)")))
            col2_head.set_halign(Gtk.Align.START)
            col2.pack_start(col2_head, False, False, 0)
            self.combo = Gtk.ComboBoxText()
            self.combo.set_size_request(320, -1)
            cells = self.combo.get_cells()
            if cells:
                cells[0].set_property("ellipsize", Pango.EllipsizeMode.END)
                cells[0].set_property("max-width-chars", 40)
            col2.pack_start(self.combo, False, False, 0)
            apply_btn = Gtk.Button(label=str(_("Apply")))
            apply_btn.connect("clicked", self.cb_apply)
            col2.pack_start(apply_btn, False, False, 0)
            box.pack_start(col2, False, False, 0)

            # Column 3: Hint
            col3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            col3.set_size_request(340, -1)
            col3_head = Gtk.Label()
            col3_head.set_markup("<b>%s</b>" % str(_("Hint")))
            col3_head.set_halign(Gtk.Align.START)
            col3.pack_start(col3_head, False, False, 0)
            self.hint_label = Gtk.Label()
            self.hint_label.set_halign(Gtk.Align.START)
            self.hint_label.set_line_wrap(True)
            self.hint_label.set_max_width_chars(40)
            col3.pack_start(self.hint_label, False, False, 0)
            self.accept_hint_btn = Gtk.Button(label=str(_("Accept hint")))
            self.accept_hint_btn.connect("clicked", self.cb_accept_hint)
            col3.pack_start(self.accept_hint_btn, False, False, 0)
            box.pack_start(col3, False, False, 0)
        else:
            box.pack_start(left_scroll, True, True, 0)
            right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.pack_start(right, False, False, 0)
            self.combo = Gtk.ComboBoxText()
            self.combo.set_size_request(240, -1)
            right.pack_start(self.combo, False, False, 0)
            apply_btn = Gtk.Button(label=str(_("Apply")))
            apply_btn.connect("clicked", self.cb_apply)
            right.pack_start(apply_btn, False, False, 0)

        self.update_combo()
        self.show_all()

    # -- hooks for subclasses -------------------------------------------
    def get_handles(self) -> list[str]:
        raise NotImplementedError

    def get_label(self, handle: str) -> str:
        raise NotImplementedError

    def merge(self, keeper_handle: str, discard_handle: str) -> bool:
        raise NotImplementedError

    # -- behaviour ------------------------------------------------------
    def selected_handle(self) -> str | None:
        for handle, radio in self.radio_buttons.items():
            if radio.get_active():
                return handle
        return None

    def cb_selection_changed(self, _radio: Gtk.RadioButton) -> None:
        self.update_combo()

    def update_combo(self) -> None:
        """Refresh the target combo box with available merge candidates."""
        self.combo.remove_all()
        selected = self.selected_handle()
        self.target_handles = [h for h in self.handles if h != selected]
        for handle in self.target_handles:
            self.combo.append_text(self.get_label(handle))
        if self.target_handles:
            self.combo.set_active(0)
        if getattr(self, "has_hint_column", False):
            self.update_hint()

    def compute_hint(self, selected_handle: str) -> tuple[str, str] | None:
        """Return (target_handle, reason) suggested for the selected record."""
        return None

    def update_hint(self) -> None:
        """Update the hint column with the suggested target and reason."""
        selected = self.selected_handle()
        hint = self.compute_hint(selected) if selected else None
        if hint is not None:
            self.hint_target_handle, reason = hint
            target_label = self.get_label(self.hint_target_handle)
            self.hint_label.set_markup(
                "<b>%s</b>\n(%s)" % (escape(target_label), escape(reason))
            )
            self.accept_hint_btn.set_sensitive(
                self.hint_target_handle in self.target_handles
            )
        else:
            self.hint_target_handle = None
            self.hint_label.set_text(str(_("(no suggestion)")))
            self.accept_hint_btn.set_sensitive(False)

    def cb_accept_hint(self, _button: Gtk.Button) -> None:
        """Set the target dropdown to the suggested hint target."""
        if self.hint_target_handle and self.hint_target_handle in self.target_handles:
            idx = self.target_handles.index(self.hint_target_handle)
            self.combo.set_active(idx)

    def cb_apply(self, _button: Gtk.Button) -> None:
        discard = self.selected_handle()
        index = self.combo.get_active()
        if discard is None or index < 0 or index >= len(self.target_handles):
            return
        keeper = self.target_handles[index]
        try:
            merged = self.merge(keeper, discard)
        except Exception as error:  # pylint: disable=broad-except
            LOG.exception("Consolidate failed")
            ErrorDialog(str(_("Consolidate failed")), str(error), parent=self)
            return
        if merged:
            OkDialog(str(_("Done")), str(_("Consolidated")), parent=self)
        self.destroy()
