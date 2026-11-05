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

"""Tests for CitationAttributesDialog and suggest_citation_attributes."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import sys
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# GTK mock fallback when running without display or PyGObject
#
# -------------------------------------------------------------------------
if "gi" not in sys.modules:
    gi_mock = MagicMock()

    class _FakeDialog:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_content_area(self) -> MagicMock:
            return MagicMock()

        def add_button(self, *args: Any, **kwargs: Any) -> None:
            pass

        def add_action_widget(self, *args: Any, **kwargs: Any) -> None:
            pass

        def connect(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_default_size(self, *args: Any, **kwargs: Any) -> None:
            pass

        def show_all(self) -> None:
            pass

    gi_mock.repository.Gtk.Dialog = _FakeDialog
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.utils import make_database
from gramps.gen.db.generic import DbWriteBase
from gramps.gen.db import DbTxn
from gramps.gen.lib import Source, Citation, SrcAttribute
from gramps.plugins.tool.citationattributesdialog import (
    CitationAttributesDialog,
    suggest_citation_attributes,
    build_citation_attribute_rows,
)


class FakeDbState:
    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class CitationAttributesDialogTest(unittest.TestCase):
    """Test CitationAttributesDialog suggestion engine, UI grid, hints, and apply logic."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = FakeDbState(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_suggest_citation_attributes_gps_matrix(self) -> None:
        """GPS matrix suggestions match genealogical evidence types according to standard."""
        # 1. Vital Certificate -> Original, Primary, Direct, QUAY 3
        sug_cert = suggest_citation_attributes(
            "State Birth Certificate", "cert 402", "", 3
        )
        self.assertEqual(sug_cert["source_type"], "Original")
        self.assertEqual(sug_cert["info_type"], "Primary")
        self.assertEqual(sug_cert["evidence_type"], "Direct")
        self.assertEqual(sug_cert["quay"], "3")

        # 2. Census database/index -> Derivative, Secondary, Direct, QUAY 2
        sug_census = suggest_citation_attributes(
            "1900 US Federal Census Index", "p. 15", "", 2
        )
        self.assertEqual(sug_census["source_type"], "Derivative")
        self.assertEqual(sug_census["info_type"], "Secondary")
        self.assertEqual(sug_census["evidence_type"], "Direct")
        self.assertEqual(sug_census["quay"], "2")

        # 3. Online tree -> Authored, Secondary, Indirect, QUAY 1
        sug_tree = suggest_citation_attributes("FamilySearch Family Tree", "", "", 1)
        self.assertEqual(sug_tree["source_type"], "Authored")
        self.assertEqual(sug_tree["info_type"], "Secondary")
        self.assertEqual(sug_tree["evidence_type"], "Indirect")
        self.assertEqual(sug_tree["quay"], "1")

        # 4. Cemetery database -> Derivative, Secondary, Direct, QUAY 2
        sug_cem = suggest_citation_attributes("Find A Grave Memorial", "12345", "", 2)
        self.assertEqual(sug_cem["source_type"], "Derivative")
        self.assertEqual(sug_cem["info_type"], "Secondary")
        self.assertEqual(sug_cem["evidence_type"], "Direct")

        # 5. Compiled book/history -> Authored, Secondary, Indirect, QUAY 2
        sug_book = suggest_citation_attributes(
            "History of Lincoln Family in America", "p. 100", "", 2
        )
        self.assertEqual(sug_book["source_type"], "Authored")
        self.assertEqual(sug_book["info_type"], "Secondary")
        self.assertEqual(sug_book["evidence_type"], "Indirect")

    def test_build_citation_attribute_rows(self) -> None:
        """Rows are created with current attributes and suggested GPS attributes."""
        with DbTxn("Create source and citation", self.db) as trans:
            src = Source()
            src.set_title("1900 Census Index")
            s_handle = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_handle)
            cit.set_page("Page 12")
            cit.set_confidence_level(2)
            c_handle = self.db.add_citation(cit, trans)

        rows = build_citation_attribute_rows(self.db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["citation_handle"], c_handle)
        self.assertEqual(row["suggested_src_type"], "Derivative")
        self.assertEqual(row["suggested_info_type"], "Secondary")
        self.assertEqual(row["suggested_ev_type"], "Direct")
        self.assertEqual(row["suggested_quay"], "2")

    def test_build_rows_and_accept_hints(self) -> None:
        """Target textboxes start empty by default, and accept_hints populates them."""
        dlg = CitationAttributesDialog.__new__(CitationAttributesDialog)
        dlg.dbstate = self.dbstate
        dlg.row_targets = []

        entries = [
            {
                "citation_handle": "c1",
                "display_text": "Census Index (S0001)\nCitation: p. 12 (C0001) | Conf: 2",
                "suggested_src_type": "Derivative",
                "suggested_info_type": "Secondary",
                "suggested_ev_type": "Direct",
                "suggested_quay": "2",
                "hint_text": "Census index (suggest Derivative, Secondary, Direct)",
            }
        ]

        grid_mock = MagicMock()
        with (
            patch(
                "gramps.plugins.tool.citationattributesdialog.Gtk.Grid",
                return_value=grid_mock,
            ),
            patch(
                "gramps.plugins.tool.citationattributesdialog.Gtk.Entry",
                side_effect=lambda: MagicMock(),
            ),
        ):
            dlg.build_rows(entries)

        self.assertEqual(len(dlg.row_targets), 1)
        target = dlg.row_targets[0]
        target["st_entry"].set_text.assert_called_with("")
        target["it_entry"].set_text.assert_called_with("")
        target["et_entry"].set_text.assert_called_with("")
        target["quay_entry"].set_text.assert_called_with("")

        # Simulate empty entries
        target["st_entry"].get_text.return_value = ""
        target["it_entry"].get_text.return_value = ""
        target["et_entry"].get_text.return_value = ""
        target["quay_entry"].get_text.return_value = ""

        with patch("gramps.plugins.tool.citationattributesdialog.OkDialog"):
            dlg.cb_accept_hints(MagicMock())

        target["st_entry"].set_text.assert_called_with("Derivative")
        target["it_entry"].set_text.assert_called_with("Secondary")
        target["et_entry"].set_text.assert_called_with("Direct")
        target["quay_entry"].set_text.assert_called_with("2")

    def test_cb_apply_commits_src_attributes_to_database(self) -> None:
        """Applying target entries saves SrcAttribute objects and confidence on citation."""
        with DbTxn("Create citation for apply", self.db) as trans:
            src = Source()
            src.set_title("Parish Register")
            s_handle = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_handle)
            cit.set_page("Entry 50")
            c_handle = self.db.add_citation(cit, trans)

        dlg = CitationAttributesDialog.__new__(CitationAttributesDialog)
        dlg.dbstate = self.dbstate
        dlg.destroy = MagicMock()

        mock_st = MagicMock()
        mock_st.get_text.return_value = "Original"
        mock_it = MagicMock()
        mock_it.get_text.return_value = "Primary"
        mock_et = MagicMock()
        mock_et.get_text.return_value = "Direct"
        mock_qy = MagicMock()
        mock_qy.get_text.return_value = "3"

        dlg.row_targets = [
            {
                "entry": {"citation_handle": c_handle},
                "st_entry": mock_st,
                "it_entry": mock_it,
                "et_entry": mock_et,
                "quay_entry": mock_qy,
            }
        ]

        with patch("gramps.plugins.tool.citationattributesdialog.OkDialog"):
            dlg.cb_apply(MagicMock())

        updated_cit = self.db.get_citation_from_handle(c_handle)
        attr_dict = {
            str(a.get_type() or ""): str(a.get_value() or "")
            for a in (updated_cit.get_attribute_list() or [])
        }
        self.assertEqual(attr_dict.get("Source Type"), "Original")
        self.assertEqual(attr_dict.get("Information Type"), "Primary")
        self.assertEqual(attr_dict.get("Evidence Type"), "Direct")
        self.assertEqual(updated_cit.get_confidence_level(), 3)


if __name__ == "__main__":
    unittest.main()
