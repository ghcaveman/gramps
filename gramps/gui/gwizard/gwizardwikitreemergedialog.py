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

"""
Merge dialog for the GWizard WikiTree Merge flow.

The shared GWizardMergeDialog (from the file-merge feature) with the WikiTree
additions layered on top, so the shared module stays identical to the
gwizard_filemerge branch: the incoming column is headed with the WikiTree
query, and a WikiTree section shows the WikiTree ID of both people.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations

# -------------------------------------------------------------------------
#
# GTK/Gnome modules
#
# -------------------------------------------------------------------------
from gi.repository import GLib
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizardwikitree import get_wikitree_id
from gramps.gui.gwizard.gwizardmergedialog import (
    GWizardMergeDialog,
    create_diff_cell,
)

_ = glocale.translation.sgettext

# Resolution key for the WikiTree ID row (see WikiTreeGWizard._apply).
WTID_KEY = "wtid"


# ------------------------------------------------------------
#
# WikiTreeMergeDialog
#
# ------------------------------------------------------------
class WikiTreeMergeDialog(GWizardMergeDialog):
    """
    GWizardMergeDialog with a WikiTree heading and WikiTree ID row.
    """

    def _populate_fields(self) -> None:
        """
        Build the shared rows, then add the WikiTree parts.
        """
        GWizardMergeDialog._populate_fields(self)
        self._set_incoming_title()
        self._add_wikitree_id_row()

    def _set_incoming_title(self) -> None:
        """
        Head the incoming column with the WikiTree query (the shared dialog
        heads it with a GEDCOM file name).
        """
        title = self.gwizard.context.get("source_title")
        if not title:
            return
        label = self._grid.get_child_at(0, 0)
        if label is not None:
            label.set_markup(
                "<b>%s</b>" % GLib.markup_escape_text(_("Incoming: %s") % title)
            )

    def _add_wikitree_id_row(self) -> None:
        """
        Add a WikiTree section with both people's WikiTree ID.

        Like the FamilySearch ID row, it gets an arrow only when the
        incoming person has an ID and the tree person has none.
        """
        left_id = get_wikitree_id(self.source_person)
        right_id = (
            get_wikitree_id(self.target_person)
            if self.target_person is not None
            else ""
        )
        if not (left_id or right_id):
            return
        grid = self._grid
        label = _("WikiTree ID")

        heading = Gtk.Label()
        heading.set_xalign(0.5)
        heading.set_halign(Gtk.Align.FILL)
        heading.set_hexpand(True)
        heading.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("WikiTree")))
        grid.attach(heading, 0, self._row_index, 3, 1)
        self._row_index += 1
        grid.attach(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            0,
            self._row_index,
            3,
            1,
        )
        self._row_index += 1

        differs = bool(left_id) != bool(right_id)
        left_cell = create_diff_cell(
            self._format_diff_line(label, left_id, right_id, True, is_left=True),
            differs,
            0.0,
        )
        right_cell = create_diff_cell(
            self._format_diff_line(label, right_id, left_id, True, is_left=False),
            differs,
            0.0,
        )
        self._value_column_size_group.add_widget(left_cell)
        self._value_column_size_group.add_widget(right_cell)
        gap: Gtk.Widget = Gtk.Label(label="")
        if left_id and not right_id:
            gap = self._make_arrow(WTID_KEY, label)
            self._mergeable_count += 1
        grid.attach(left_cell, 0, self._row_index, 1, 1)
        grid.attach(gap, 1, self._row_index, 1, 1)
        grid.attach(right_cell, 2, self._row_index, 1, 1)
        self._row_index += 1
