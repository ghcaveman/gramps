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
import logging
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk

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
    ) -> None:
        super().__init__(
            title=title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
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

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
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
        box.pack_start(left_scroll, True, True, 0)
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
        self.combo.remove_all()
        selected = self.selected_handle()
        self.target_handles = [h for h in self.handles if h != selected]
        for handle in self.target_handles:
            self.combo.append_text(self.get_label(handle))
        if self.target_handles:
            self.combo.set_active(0)

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
