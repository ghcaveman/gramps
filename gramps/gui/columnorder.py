#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2000-2003  Donald N. Allingham
# Copyright (C) 2010       Benny Malengier
# Copyright (C) 2010       Nick Hall
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
# with this program; if not, see <https://www.gnu.org/licenses/>.
#
# gui/columnorder.py

"""
Handle the column ordering
"""

# -------------------------------------------------------------------------
#
# python modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.gettext
import logging

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk
from gi.repository import GObject

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from .managedwindow import ManagedWindow
from .glade import Glade
from .dialog import QuestionDialog2

# -------------------------------------------------------------------------
#
# set up logging
#
# -------------------------------------------------------------------------
__LOG = logging.getLogger(".ColumnOrder")


class ColumnOrder(Gtk.Box):
    """
    Column ordering selection widget
    """

    def __init__(
        self,
        config,
        column_names,
        widths,
        on_apply,
        tree=False,
        resizable=None,
        on_reset=None,
    ):
        """
        Create the Column Ordering widget based on config

        config: a configuration file with column data
        column_names: translated names for the possible columns
        widths: the widths of the visible columns
        on_apply: function to run when apply is clicked
        tree: are the columns for a treeview, if so, the first columns is not
            changable
        on_reset: optional function to run when Reset to Defaults is clicked;
            it must put the column settings back to their defaults and
            rebuild the view.  If not given, the column settings are reset
            here and on_apply is called.
        """
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)

        self.treeview = tree
        self.colnames = column_names
        self.config = config
        self.on_apply = on_apply
        self.on_reset = on_reset
        self.resizable = resizable

        self.pack_start(Gtk.Label(label=" "), False, False, 0)

        self.startrow = 0
        if self.treeview:
            label = Gtk.Label(
                label=_('Tree View: first column "%s" cannot be changed')
                % column_names[0]
            )
            self.startrow = 1
            self.pack_start(label, False, False, 0)
            self.pack_start(Gtk.Label(label=" "), False, False, 0)

        self.pack_start(
            Gtk.Label(label=_("Drag and drop the columns to change" " the order")),
            False,
            False,
            0,
        )
        self.pack_start(Gtk.Label(label=" "), False, False, 0)
        hbox = Gtk.Box()
        hbox.set_spacing(10)
        hbox.pack_start(Gtk.Label(label=" "), True, True, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(300, 300)
        hbox.pack_start(scroll, True, True, 0)
        self.tree = Gtk.TreeView()
        self.tree.set_reorderable(True)
        scroll.add(self.tree)
        self.apply_button = Gtk.Button.new_with_mnemonic(_("_Apply"))
        self.reset_button = Gtk.Button.new_with_mnemonic(_("_Reset to Defaults"))
        self.reset_button.set_tooltip_text(
            _("Restore this view's default columns, order and widths")
        )
        btns = Gtk.ButtonBox(orientation=Gtk.Orientation.VERTICAL)
        btns.set_layout(Gtk.ButtonBoxStyle.START)
        btns.set_spacing(6)
        btns.pack_start(self.apply_button, False, False, 0)
        btns.pack_start(self.reset_button, False, False, 0)
        hbox.pack_start(btns, False, True, 0)
        self.pack_start(hbox, True, True, 0)

        # Model holds:
        # bool: column visible or not
        # str : name of the column
        # int : order of the column
        # int : size (width) of the column
        self.model = Gtk.ListStore(
            GObject.TYPE_BOOLEAN,
            GObject.TYPE_STRING,
            GObject.TYPE_INT,
            GObject.TYPE_INT,
        )

        self.tree.set_model(self.model)

        checkbox = Gtk.CellRendererToggle()
        checkbox.connect("toggled", toggled, self.model)
        renderer = Gtk.CellRendererText()

        column_n = Gtk.TreeViewColumn(_("Display"), checkbox, active=0)
        column_n.set_min_width(50)
        self.tree.append_column(column_n)

        column_n = Gtk.TreeViewColumn(_("Column Name"), renderer, text=1)
        column_n.set_min_width(225)
        self.tree.append_column(column_n)

        self.apply_button.connect("clicked", self.__on_apply)
        self.reset_button.connect("clicked", self.__on_reset)
        # A drop onto (rather than between) rows can lose the dragged row
        self.tree.connect("drag-end", self.__restore_missing_rows)

        # obtain the columns from config file
        self.oldorder = self.config.get("columns.rank")
        oldsize = self.config.get("columns.size")
        # try to use the current columns size.
        if resizable:
            self.oldsize = []
            newsize = self.resizable.get_columns_size()
            nbc = 0
            for size in oldsize:
                if nbc < len(newsize):
                    if newsize[nbc] == 0:
                        self.oldsize.append(size)
                    else:
                        self.oldsize.append(newsize[nbc])
                else:
                    self.oldsize.append(size)
                nbc += 1
        else:
            self.oldsize = oldsize
        self.oldvis = self.config.get("columns.visible")
        self.__fill_model(widths)

    def __fill_model(self, widths=None):
        """
        Fill the list from oldorder/oldsize/oldvis.  If widths (the current
        widths of the visible columns) is given, use it in place of the
        stored sizes for the visible columns.
        """
        self.model.clear()
        self.sizes = {}
        colord = []
        index = 0
        sizes = list(self.oldsize)
        if len(sizes) < len(self.oldorder):
            sizes.extend([100] * (len(self.oldorder) - len(sizes)))
        for val, size in zip(self.oldorder, sizes):
            if not 0 <= val < len(self.colnames) or val in self.sizes:
                continue
            self.sizes[val] = size
            if val in self.oldvis:
                if widths is not None and val != self.oldvis[-1]:
                    # don't use last col width, its wrong
                    if index < len(widths):
                        size = widths[index]
                    index += 1
                colord.append((1, val, size))
            else:
                colord.append((0, val, size))
        for item in colord[self.startrow :]:
            node = self.model.append()
            self.model.set(
                node, 0, item[0], 1, self.colnames[item[1]], 2, item[1], 3, item[2]
            )
        self.__restore_missing_rows()

    def __restore_missing_rows(self, *args):
        """
        Make sure every column the view offers is in the list: add any that
        are missing (from the saved settings, or lost in a drag and drop)
        at the end, not displayed.
        """
        present = {row[2] for row in self.model}
        if self.treeview and self.oldorder:
            present.add(self.oldorder[0])  # fixed first column, not listed
        for col in range(len(self.colnames)):
            if col not in present:
                node = self.model.append()
                self.model.set(
                    node,
                    0,
                    False,
                    1,
                    self.colnames[col],
                    2,
                    col,
                    3,
                    self.sizes.get(col, 100),
                )

    def __on_reset(self, obj):
        """
        Called when the Reset to Defaults button is pressed.
        """
        parent = self.get_toplevel()
        if not isinstance(parent, Gtk.Window):
            parent = None
        if not QuestionDialog2(
            _("Reset columns to defaults?"),
            _(
                "This view's column choices, order and widths will be "
                "replaced by the defaults."
            ),
            _("_Reset"),
            _("_Cancel"),
            parent=parent,
        ).run():
            return

        if self.on_reset:
            self.on_reset()
        else:
            for key in ("columns.rank", "columns.size", "columns.visible"):
                self.config.reset(key)
            self.config.save()
            if self.on_apply:
                self.on_apply()

        self.oldorder = self.config.get("columns.rank")
        self.oldsize = self.config.get("columns.size")
        self.oldvis = self.config.get("columns.visible")
        self.__fill_model()

    def __on_apply(self, obj):
        """
        called with the OK button is pressed
        """
        neworder = []
        newsize = []
        newvis = []
        if self.treeview:
            # first row is fixed
            neworder.append(self.oldorder[0])
            newvis.append(self.oldvis[0])
            newsize.append(self.oldsize[0])
        self.__restore_missing_rows()
        for row in self.model:
            enable, index, size = row[0], row[2], row[3]
            if index in neworder:
                continue
            if enable:
                newvis.append(index)
            neworder.append(index)
            newsize.append(size)
        if len(newvis) > 0 and self.on_apply:
            self.config.set("columns.rank", neworder)
            self.config.set("columns.size", newsize)
            self.config.set("columns.visible", newvis)
            self.config.save()
            self.on_apply()
        self.resizable.save_column_info()


def toggled(cell, path, model):
    """
    Called when the cell information is changed, updating the
    data model so the that change occurs.
    """
    node = model.get_iter((int(path),))
    value = not model.get_value(node, 0)
    model.set(node, 0, value)
