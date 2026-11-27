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
Merge dialog for the GWizard FamilySearch Merge flow.

Subclasses GWizardMergeDialog to head the incoming column with the FamilySearch
person identifier or details.
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

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

_ = glocale.translation.sgettext


# ------------------------------------------------------------
#
# FamilySearchMergeDialog
#
# ------------------------------------------------------------
class FamilySearchMergeDialog(GWizardMergeDialog):
    """
    GWizardMergeDialog specialized for FamilySearch merge comparisons.
    """

    def _populate_fields(self) -> None:
        """
        Build the shared rows, then update the incoming header title.
        """
        GWizardMergeDialog._populate_fields(self)
        self._set_incoming_title()

    def _set_incoming_title(self) -> None:
        """
        Head the incoming column with the FamilySearch identifier.
        """
        title = self.gwizard.context.get("source_title")
        if not title:
            return
        label = self._grid.get_child_at(0, 0)
        if label is not None:
            label.set_markup(
                "<b>%s</b>"
                % GLib.markup_escape_text(_("Incoming FamilySearch: %s") % title)
            )
            label.set_selectable(True)
