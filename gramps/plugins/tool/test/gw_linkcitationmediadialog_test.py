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

"""Unit tests for GWLinkCitationMediaDialog and related functions."""

from __future__ import annotations

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
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

    gi_mock.repository.Gtk.Dialog = _FakeDialog
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository

from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.utils import make_database
from gramps.gen.lib import (
    Citation,
    Date,
    Media,
    MediaRef,
    Name,
    Person,
    Source,
    Surname,
)
from gramps.plugins.tool.gw_linkcitationmediadialog import (
    GWLinkCitationMediaDialog,
    apply_citation_media_fixes,
    auto_link_citation_media,
    build_link_citation_media_rows,
    unlocked_media_message,
)
from gramps.plugins.tool.gwizard_common import lock_media


class DummyDbState:
    """Mock dbstate wrapping a Gramps database."""

    def __init__(self, db: DbWriteBase) -> None:
        self.db = db


class GWLinkCitationMediaDialogTest(unittest.TestCase):
    """Test suite for GWLinkCitationMediaDialog."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = DummyDbState(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_build_rows_empty_db(self) -> None:
        """build_link_citation_media_rows returns empty list when no candidates exist."""
        rows = build_link_citation_media_rows(self.db)
        self.assertEqual(len(rows), 0)

    def test_build_rows_with_candidates(self) -> None:
        """build_link_citation_media_rows finds candidates and builds structured row dictionaries."""
        with DbTxn("Setup candidate", self.db) as trans:
            src = Source()
            src.set_title("1940 Federal Population Schedule")
            s_h = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_h)
            cit.set_page("Sheet 12A")
            c_h = self.db.add_citation(cit, trans)

            person = Person()
            name = Name()
            sname = Surname()
            sname.set_surname("Adams")
            name.add_surname(sname)
            name.set_first_name("John")
            person.set_primary_name(name)
            person.add_citation(c_h)

            m = Media()
            m.set_path("Adams_John_1940_Census_Sheet_12A.jpg")
            lock_media(self.db, m, txn=trans)
            m_h = self.db.add_media(m, trans)

            mref = MediaRef()
            mref.set_reference_handle(m_h)
            person.add_media_reference(mref)
            self.db.add_person(person, trans)

        rows = build_link_citation_media_rows(self.db)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["status"], "safe")
        self.assertEqual(r["media_handle"], m_h)
        self.assertEqual(r["citation_handle"], c_h)
        self.assertIn("Adams", r["media_display"])
        self.assertIn("1940", r["cit_display"])
        self.assertIn("Sheet 12A", r["cit_display"])

    def test_apply_citation_media_fixes_link_and_detach(self) -> None:
        """apply_citation_media_fixes links media to citation and detaches from owner if requested."""
        with DbTxn("Setup link and detach", self.db) as trans:
            src = Source()
            src.set_title("1930 Census")
            s_h = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_h)
            cit.set_page("Sheet 1A")
            c_h = self.db.add_citation(cit, trans)

            person = Person()
            m = Media()
            m.set_path("Baker_1930_Census_Sheet_1A.jpg")
            m_h = self.db.add_media(m, trans)

            ref = MediaRef()
            ref.set_reference_handle(m_h)
            person.add_media_reference(ref)
            p_h = self.db.add_person(person, trans)

        plan = [
            {
                "chosen_action": "link_detach",
                "action": "promote_from_person",
                "citation_handle": c_h,
                "media_handle": m_h,
                "owner_handle": p_h,
                "owner_type": "Person",
                "is_locked": False,
            }
        ]

        linked, detached = apply_citation_media_fixes(self.dbstate, plan)
        self.assertEqual(linked, 1)
        self.assertEqual(detached, 1)

        # Citation has media
        c_obj = self.db.get_citation_from_handle(c_h)
        self.assertEqual(len(c_obj.get_media_list()), 1)

        # Person gallery detached
        p_obj = self.db.get_person_from_handle(p_h)
        self.assertEqual(len(p_obj.get_media_list()), 0)

    def _add_census_candidate(self, surname: str, year: str, locked: bool) -> tuple:
        """Add a person gallery scan that matches one of their citations."""
        with DbTxn("Setup candidate", self.db) as trans:
            src = Source()
            src.set_title("%s Federal Census" % year)
            s_h = self.db.add_source(src, trans)
            cit = Citation()
            cit.set_reference_handle(s_h)
            cit.set_page("Sheet 3B")
            c_h = self.db.add_citation(cit, trans)
            person = Person()
            name = Name()
            sname = Surname()
            sname.set_surname(surname)
            name.add_surname(sname)
            person.set_primary_name(name)
            person.add_citation(c_h)
            m = Media()
            m.set_path("%s_%s_Census_Sheet_3B.jpg" % (surname, year))
            if locked:
                lock_media(self.db, m, txn=trans)
            m_h = self.db.add_media(m, trans)
            ref = MediaRef()
            ref.set_reference_handle(m_h)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)
        return c_h, m_h

    def test_unlocked_media_is_not_offered(self) -> None:
        """Media not yet locked in Media Fix is left out and counted."""
        c_h, _m_h = self._add_census_candidate("Evans", "1930", locked=False)
        stats: dict[str, int] = {}
        self.assertEqual(build_link_citation_media_rows(self.db, stats), [])
        self.assertEqual(stats["unlocked_media"], 1)
        stats = {}
        self.assertEqual(auto_link_citation_media(self.db, stats), 0)
        self.assertEqual(stats["unlocked_media"], 1)
        c_obj = self.db.get_citation_from_handle(c_h)
        self.assertEqual(len(c_obj.get_media_list()), 0)
        self.assertIn("1 media file was left out", unlocked_media_message(1))
        self.assertEqual(unlocked_media_message(0), "")

    def test_rerun_picks_up_newly_locked_media(self) -> None:
        """Locking more media later and running again links only the new ones."""
        c1, _m1 = self._add_census_candidate("Fox", "1920", locked=True)
        c2, m2 = self._add_census_candidate("Gray", "1910", locked=False)
        stats: dict[str, int] = {}
        self.assertEqual(auto_link_citation_media(self.db, stats), 1)
        self.assertEqual(stats["unlocked_media"], 1)

        lock_media(self.db, self.db.get_media_from_handle(m2), commit=True)
        stats = {}
        self.assertEqual(auto_link_citation_media(self.db, stats), 1)
        self.assertEqual(stats["unlocked_media"], 0)
        for c_h in (c1, c2):
            c_obj = self.db.get_citation_from_handle(c_h)
            self.assertEqual(len(c_obj.get_media_list()), 1)
        # Nothing left to offer: the linked citations are not listed again.
        self.assertEqual(build_link_citation_media_rows(self.db), [])

    def test_wizard_reports_unlocked_media(self) -> None:
        """The auto step and the review list both name media left unlocked."""
        # pylint: disable=import-outside-toplevel
        from gramps.plugins.tool import gwizardcitationfix as fix

        self._add_census_candidate("Irwin", "1940", locked=False)
        msg = fix.run_auto_layer("link_citation_media", self.db)
        self.assertIn("Linked 0 media objects", msg)
        self.assertIn("1 media file was left out", msg)
        review = "\n".join(fix.find_items_needing_review(self.db))
        self.assertIn("Link Citation Media (1): media files are not locked", review)

    def test_locked_media_can_be_detached(self) -> None:
        """The lock means "checked", so the user may still detach from a gallery."""
        c_h, m_h = self._add_census_candidate("Hall", "1900", locked=True)
        rows = build_link_citation_media_rows(self.db)
        self.assertEqual(len(rows), 1)
        self.assertIn("link_detach", [code for _label, code in rows[0]["options"]])
        rows[0]["chosen_action"] = "link_detach"
        linked, detached = apply_citation_media_fixes(self.dbstate, rows)
        self.assertEqual((linked, detached), (1, 1))
        person = next(self.db.iter_people())
        self.assertEqual(person.get_media_list(), [])

    def test_auto_link_citation_media(self) -> None:
        """auto_link_citation_media applies only safe candidates in a single transaction."""
        with DbTxn("Setup auto link", self.db) as trans:
            src = Source()
            src.set_title("1920 Federal Census")
            s_h = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_h)
            cit.set_page("Sheet 02A")
            c_h = self.db.add_citation(cit, trans)

            person = Person()
            name = Name()
            sname = Surname()
            sname.set_surname("Clark")
            name.add_surname(sname)
            person.set_primary_name(name)
            person.add_citation(c_h)

            m = Media()
            m.set_path("Clark_1920_Census_Sheet_02A.jpg")
            lock_media(self.db, m, txn=trans)
            m_h = self.db.add_media(m, trans)

            ref = MediaRef()
            ref.set_reference_handle(m_h)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)

        count = auto_link_citation_media(self.db)
        self.assertEqual(count, 1)

        c_obj = self.db.get_citation_from_handle(c_h)
        self.assertEqual(len(c_obj.get_media_list()), 1)

    def test_dialog_initialization_and_accept_hints(self) -> None:
        """GWLinkCitationMediaDialog initializes widgets and accept hints selects safe options."""
        with DbTxn("Setup dialog test", self.db) as trans:
            src = Source()
            src.set_title("1910 Census")
            s_h = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_h)
            cit.set_page("Sheet 5A")
            c_h = self.db.add_citation(cit, trans)

            person = Person()
            name = Name()
            sname = Surname()
            sname.set_surname("Davis")
            name.add_surname(sname)
            person.set_primary_name(name)
            person.add_citation(c_h)

            m = Media()
            m.set_path("Davis_1910_Census_Sheet_5A.jpg")
            lock_media(self.db, m, txn=trans)
            m_h = self.db.add_media(m, trans)

            ref = MediaRef()
            ref.set_reference_handle(m_h)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)

        dlg = GWLinkCitationMediaDialog.__new__(GWLinkCitationMediaDialog)
        dlg.dbstate = self.dbstate
        dlg.rows = build_link_citation_media_rows(self.db)
        dlg.row_combos = []
        dlg.preview_image = MagicMock()
        dlg.preview_text = MagicMock()
        dlg.preview_score = MagicMock()

        self.assertEqual(len(dlg.rows), 1)
        mock_combo = MagicMock()
        mock_combo.get_active_id.return_value = "link"
        dlg.row_combos.append((dlg.rows[0], mock_combo))

        dlg.cb_accept_hints(MagicMock())
        mock_combo.set_active_id.assert_called_with("link")
        self.assertEqual(dlg.rows[0]["chosen_action"], "link")

        # Test inspector update
        dlg._update_inspector(dlg.rows[0])
        dlg.preview_score.set_markup.assert_called_once()
        dlg.preview_text.set_markup.assert_called_once()

        # Test apply
        with patch("gramps.plugins.tool.gw_linkcitationmediadialog.OkDialog"):
            dlg.response = MagicMock()
            dlg.destroy = MagicMock()
            dlg.cb_apply(MagicMock())
            dlg.destroy.assert_called_once()

        c_obj = self.db.get_citation_from_handle(c_h)
        self.assertEqual(len(c_obj.get_media_list()), 1)


if __name__ == "__main__":
    unittest.main()
