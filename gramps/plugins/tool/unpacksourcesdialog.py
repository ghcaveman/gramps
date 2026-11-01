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

"""Step 1 dialog: review and unpack conflated source titles."""

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
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# Column indexes of the list store.
COL_APPLY, COL_ID, COL_OLD, COL_REPO, COL_NEW, COL_MOVED = range(6)


# ------------------------------------------------------------
#
# UnpackSourcesDialog
#
# ------------------------------------------------------------
class UnpackSourcesDialog(Gtk.Dialog):
    """Show the proposed repository/title splits and apply the ticked ones."""

    def __init__(
        self,
        title: str,
        dbstate: Any,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        super().__init__(
            title=title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.engine = GWizardCitationRepairEngine()
        self.plan = self.engine.plan_unpack_conflated_sources(dbstate.db)
        self.store = Gtk.ListStore(bool, str, str, str, str, str)
        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        info = Gtk.Label(
            label=description
            or str(
                _(
                    "Source titles that mix repository, source and citation "
                    "text are split below. Untick a row to skip it; double-click "
                    "the repository or new title to edit it."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not self.plan:
            done = Gtk.Label(label=str(_("No conflated source titles found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        for entry in self.plan:
            self.store.append(
                [
                    True,
                    entry["gramps_id"],
                    entry["old_title"],
                    entry["repo_name"],
                    entry["new_title"],
                    entry["moved_text"],
                ]
            )
        content.add(self.build_tree())
        hint = Gtk.Label(
            label=str(
                _(
                    "Citation-style text (page, volume, memorial ID...) taken out "
                    "of a title is kept in the source's publication information."
                )
            )
        )
        hint.set_line_wrap(True)
        hint.set_halign(Gtk.Align.START)
        content.add(hint)
        apply_button = Gtk.Button(label=str(_("Apply")))
        apply_button.connect("clicked", self.cb_apply)
        content.add(apply_button)

    def build_tree(self) -> Gtk.ScrolledWindow:
        tree = Gtk.TreeView(model=self.store)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self.cb_toggled)
        tree.append_column(Gtk.TreeViewColumn(str(_("Apply")), toggle, active=COL_APPLY))
        specs = [
            (COL_ID, str(_("ID")), False),
            (COL_OLD, str(_("Current title")), False),
            (COL_REPO, str(_("Repository")), True),
            (COL_NEW, str(_("New title")), True),
            (COL_MOVED, str(_("Moved to publication info")), False),
        ]
        for col, label, editable in specs:
            renderer = Gtk.CellRendererText()
            renderer.set_property("editable", editable)
            if editable:
                renderer.connect("edited", self.cb_edited, col)
            column = Gtk.TreeViewColumn(label, renderer, text=col)
            column.set_resizable(True)
            tree.append_column(column)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(300)
        scrolled.set_min_content_width(900)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(tree)
        return scrolled

    def cb_toggled(self, _renderer: Gtk.CellRendererToggle, path: str) -> None:
        self.store[path][COL_APPLY] = not self.store[path][COL_APPLY]

    def cb_edited(
        self, _renderer: Gtk.CellRendererText, path: str, text: str, column: int
    ) -> None:
        self.store[path][column] = text.strip()

    def cb_apply(self, _button: Gtk.Button) -> None:
        for entry, row in zip(self.plan, self.store):
            entry["apply"] = bool(row[COL_APPLY])
            entry["repo_name"] = row[COL_REPO]
            entry["new_title"] = row[COL_NEW]
        try:
            count = self.engine.apply_unpack_plan(self.dbstate.db, self.plan)
        except Exception as error:  # pylint: disable=broad-except
            LOG.exception("Unpack failed")
            ErrorDialog(str(_("Unpack failed")), str(error), parent=self)
            return
        OkDialog(
            str(_("Field Unpacking Complete")),
            str(_("Unpacked %d source titles into repository and source fields."))
            % count,
            parent=self,
        )
        self.destroy()

    def show_dialog(self) -> None:
        self.show_all()
        self.run()
        self.destroy()
