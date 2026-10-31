import os
import logging
from typing import Any

from gi.repository import Gtk

from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db import DbTxn
from gramps.gui.dialog import OkDialog

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


class RepoConsolidateDialog(Gtk.Dialog):
    def __init__(self, dbstate: Any, transient_for: Gtk.Window | None = None) -> None:
        super().__init__(title="Repository Consolidate", transient_for=transient_for, modal=True, destroy_with_parent=True)
        self.dbstate = dbstate
        self.add_button(str(_("Close")), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dlg, resp: dlg.destroy())
        content = self.get_content_area()
        content.set_border_width(12)
        self.repos = list(dbstate.db.get_repository_handles()) if hasattr(dbstate.db, "get_repository_handles") else []
        self.repos.sort(key=lambda h: self._repo_name(h))
        names = [self._repo_name(h) for h in self.repos]
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        content.add(box)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        left_scroll.add(left)
        box.pack_start(left_scroll, True, True, 0)
        self.radio_group = None
        self.radio_buttons: dict[str, Gtk.RadioButton] = {}
        for h in self.repos:
            name = self._repo_name(h)
            rb = Gtk.RadioButton.new_with_label_from_widget(self.radio_group, name) if self.radio_group is not None else Gtk.RadioButton.new_with_label(None, name)
            if self.radio_group is None:
                self.radio_group = rb
            self.radio_buttons[h] = rb
            left.pack_start(rb, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(right, True, True, 0)
        self.combo = Gtk.ComboBoxText()
        right.pack_start(self.combo, False, False, 0)
        apply_btn = Gtk.Button(label=str(_("Apply")))
        apply_btn.set_size_request(60, -1)
        apply_btn.connect("clicked", self.cb_apply)
        right.pack_start(apply_btn, False, False, 0)
        self.show_all()

    def _repo_name(self, handle: str) -> str:
        try:
            repo = self.dbstate.db.get_repository_from_handle(handle)
            return repo.get_name() if repo else handle
        except Exception:
            return handle

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
        for h in self.repos:
            if self._repo_name(h) == target_name:
                target_handle = h
                break
        if target_handle is None or target_handle == selected:
            return
        db = self.dbstate.db
        with DbTxn("Consolidate repository", db, batch=True) as trans:
            for sh in db.get_source_handles():
                src = db.get_source_from_handle(sh)
                if src.get_repository_handle() == selected:
                    src.set_repository_handle(target_handle)
                    db.commit_source(src, trans)
            # remove selected repo
            try:
                repo = db.get_repository_from_handle(selected)
                db.remove_repository(repo, trans)
            except Exception:
                LOG.exception("Failed removing repository")
        OkDialog(str(_("Done")), str(_("Consolidated")), parent=self)
        self.destroy()

    def update_combo(self) -> None:
        self.combo.remove_all()
        selected = None
        for h, rb in self.radio_buttons.items():
            if rb.get_active():
                selected = h
                break
        for h in self.repos:
            if h == selected:
                continue
            self.combo.append_text(self._repo_name(h))
        if self.combo.get_model() and len(self.combo.get_model()) > 0:
            self.combo.set_active(0)

    def show_all(self) -> None:
        super().show_all()
        for rb in self.radio_buttons.values():
            rb.connect("toggled", lambda _b: self.update_combo())
        self.update_combo()
