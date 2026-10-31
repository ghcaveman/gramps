import os
import logging
from typing import Any

from gi.repository import Gtk

from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db import DbTxn
from gramps.gui.dialog import OkDialog

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


class SourceConsolidateDialog(Gtk.Dialog):
    def __init__(self, dbstate: Any, transient_for: Gtk.Window | None = None) -> None:
        super().__init__(title="Source Consolidate", transient_for=transient_for, modal=True, destroy_with_parent=True)
        self.dbstate = dbstate
        self.add_button(str(_("Close")), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dlg, resp: dlg.destroy())
        self.set_default_size(800, 918)
        content = self.get_content_area()
        content.set_border_width(12)
        self.items = list(dbstate.db.get_source_handles()) if hasattr(dbstate.db, "get_source_handles") else []
        self.items.sort(key=lambda h: self._name(h))
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_vexpand(True)
        box.set_hexpand(True)
        content.add(box)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        left_scroll.add(left)
        box.pack_start(left_scroll, True, True, 0)
        self.radio_group = None
        self.radio_buttons: dict[str, Gtk.RadioButton] = {}
        for h in self.items:
            name = self._name(h)
            rb = Gtk.RadioButton.new_with_label_from_widget(self.radio_group, name) if self.radio_group is not None else Gtk.RadioButton.new_with_label(None, name)
            if self.radio_group is None:
                self.radio_group = rb
            self.radio_buttons[h] = rb
            left.pack_start(rb, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(right, False, False, 0)
        self.combo = Gtk.ComboBoxText()
        self.combo.set_size_request(200, -1)
        right.pack_start(self.combo, False, False, 0)
        apply_btn = Gtk.Button(label=str(_("Apply")))
        apply_btn.set_size_request(60, -1)
        apply_btn.connect("clicked", self.cb_apply)
        right.pack_start(apply_btn, False, False, 0)
        self.show_all()
        for rb in self.radio_buttons.values():
            rb.connect("toggled", lambda _b: self.update_combo())
        self.update_combo()

    def _name(self, handle: str) -> str:
        try:
            obj = self.dbstate.db.get_source_from_handle(handle)
            return obj.get_title() if obj else handle
        except Exception:
            return handle

    def update_combo(self) -> None:
        self.combo.remove_all()
        selected = None
        for h, rb in self.radio_buttons.items():
            if rb.get_active():
                selected = h
                break
        for h in self.items:
            if h == selected:
                continue
            self.combo.append_text(self._name(h))
        if self.combo.get_model() and len(self.combo.get_model()) > 0:
            self.combo.set_active(0)

    def cb_apply(self, _button: Gtk.Button) -> None:
        selected = None
        for h, rb in self.radio_buttons.items():
            if rb.get_active():
                selected = h
                break
        if selected is None:
            return
        target_name = self.combo.get_active_text()
        target_handle = None
        for h in self.items:
            if self._name(h) == target_name:
                target_handle = h
                break
        if target_handle is None or target_handle == selected:
            return
        db = self.dbstate.db
        with DbTxn("Consolidate source", db, batch=True) as trans:
            for ch in db.get_citation_handles():
                cit = db.get_citation_from_handle(ch)
                if cit.get_source_handle() == selected:
                    cit.set_source_handle(target_handle)
                    db.commit_citation(cit, trans)
            try:
                src = db.get_source_from_handle(selected)
                db.remove_source(src, trans)
            except Exception:
                LOG.exception("Failed removing source")
        OkDialog(str(_("Done")), str(_("Consolidated")), parent=self)
        self.destroy()
