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
import shutil
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# GTK test doubles (shared with the Media Fix tests)
#
# -------------------------------------------------------------------------
from gramps.plugins.tool.test import gwizard_gtk_fakes

# Install before importing a GWizard module, so its dialogs subclass the fakes.
Gtk = gwizard_gtk_fakes.install()


def setUpModule() -> None:  # pylint: disable=invalid-name
    """Put the fake widgets back on Gtk for this module's tests."""
    gwizard_gtk_fakes.install()


def tearDownModule() -> None:  # pylint: disable=invalid-name
    """Restore Gtk so other Gramps tests see the real widgets."""
    gwizard_gtk_fakes.uninstall()


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
    media_fix_problems,
    media_problems_message,
)


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
        # Media that passes Media Fix: relative path, file inside the base
        # media path, one record per file.
        self.base_dir = tempfile.mkdtemp(prefix="gw_linkmedia_")
        self.db.set_mediapath(self.base_dir)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def _media(self, filename: str, create: bool = True) -> Media:
        """
        Return a new media record with a path relative to the base path.

        :param filename: The file name.
        :param create: Whether to create the file on disk.
        :returns: The (not yet added) media record.
        """
        if create:
            with open(os.path.join(self.base_dir, filename), "wb") as handle:
                handle.write(b"scan")
        media = Media()
        media.set_path(filename)
        return media

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

            m = self._media("Adams_John_1940_Census_Sheet_12A.jpg")
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
            m = self._media("Baker_1930_Census_Sheet_1A.jpg")
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

    def _add_census_candidate(
        self, surname: str, year: str, file_present: bool = True, path: str = ""
    ) -> tuple:
        """Add a person gallery scan that matches one of their citations.

        :param surname: The person's surname (also used in the file name).
        :param year: The census year.
        :param file_present: Whether the scan exists in the base media path.
        :param path: Store this path instead (e.g. an absolute one).
        :returns: ``(citation handle, media handle)``.
        """
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
            m = self._media(
                "%s_%s_Census_Sheet_3B.jpg" % (surname, year), create=file_present
            )
            if path:
                m.set_path(path)
            m_h = self.db.add_media(m, trans)
            ref = MediaRef()
            ref.set_reference_handle(m_h)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)
        return c_h, m_h

    def test_media_breaking_rules_is_not_offered(self) -> None:
        """Media whose file is missing is left out and listed with the reason."""
        c_h, _m_h = self._add_census_candidate("Evans", "1930", file_present=False)
        stats: dict = {}
        self.assertEqual(build_link_citation_media_rows(self.db, stats), [])
        self.assertEqual(len(stats["media_problems"]), 1)
        self.assertIn("file not found", stats["media_problems"][0]["problems"][0])
        stats = {}
        self.assertEqual(auto_link_citation_media(self.db, stats), 0)
        self.assertEqual(len(stats["media_problems"]), 1)
        c_obj = self.db.get_citation_from_handle(c_h)
        self.assertEqual(len(c_obj.get_media_list()), 0)
        msg = media_problems_message(stats["media_problems"])
        self.assertIn("1 media file was left out", msg)
        self.assertIn("Evans_1930_Census_Sheet_3B.jpg", msg)
        self.assertIn("Find missing media", msg)
        self.assertEqual(media_problems_message([]), "")

    def test_media_fix_rules(self) -> None:
        """Each Media Fix rule is reported on its own."""
        with DbTxn("Setup rules", self.db) as trans:
            good = self._media("good.jpg")
            self.db.add_media(good, trans)
            absolute = self._media("abs.jpg")
            absolute.set_path(os.path.join(self.base_dir, "abs.jpg"))
            self.db.add_media(absolute, trans)
            outside = self._media("out.jpg", create=False)
            outside.set_path("../out.jpg")
            self.db.add_media(outside, trans)
            dup1 = self._media("shared.jpg")
            self.db.add_media(dup1, trans)
            dup2 = self._media("shared.jpg")
            self.db.add_media(dup2, trans)
        self.assertEqual(media_fix_problems(self.db, good), [])
        self.assertIn("absolute path", media_fix_problems(self.db, absolute)[0])
        out_problems = " ".join(media_fix_problems(self.db, outside))
        self.assertIn("outside the base media path", out_problems)
        self.assertIn("file not found", out_problems)
        dup_problems = media_fix_problems(self.db, dup1)
        self.assertEqual(len(dup_problems), 1)
        self.assertIn(dup2.get_gramps_id(), dup_problems[0])
        self.assertIn("Fix media references", dup_problems[0])

    def test_no_base_media_path_is_a_problem(self) -> None:
        """Without a base media path nothing passes Media Fix."""
        with DbTxn("Setup no base", self.db) as trans:
            m = self._media("nobase.jpg")
            self.db.add_media(m, trans)
        self.db.set_mediapath(None)
        self.assertIn("no base media path is set", media_fix_problems(self.db, m))

    def test_rerun_picks_up_fixed_media(self) -> None:
        """Fixing more media later and running again links only the new ones."""
        c1, _m1 = self._add_census_candidate("Fox", "1920")
        c2, _m2 = self._add_census_candidate("Gray", "1910", file_present=False)
        stats: dict = {}
        self.assertEqual(auto_link_citation_media(self.db, stats), 1)
        self.assertEqual(len(stats["media_problems"]), 1)

        # The user finds the file (Media Fix: Find missing media).
        self._media("Gray_1910_Census_Sheet_3B.jpg")
        stats = {}
        self.assertEqual(auto_link_citation_media(self.db, stats), 1)
        self.assertEqual(stats["media_problems"], [])
        for c_h in (c1, c2):
            c_obj = self.db.get_citation_from_handle(c_h)
            self.assertEqual(len(c_obj.get_media_list()), 1)
        # Nothing left to offer: the linked citations are not listed again.
        self.assertEqual(build_link_citation_media_rows(self.db), [])

    def test_wizard_reports_media_problems(self) -> None:
        """The auto step and the review list both name media that breaks rules."""
        # pylint: disable=import-outside-toplevel
        from gramps.plugins.tool import gwizardcitationfix as fix

        self._add_census_candidate(
            "Irwin", "1940", path="C:/Users/someone/Irwin_1940_Census_Sheet_3B.jpg"
        )
        msg = fix.run_auto_layer("link_citation_media", self.db)
        self.assertIn("Linked 0 media objects", msg)
        self.assertIn("1 media file was left out", msg)
        self.assertIn("absolute path", msg)
        review = "\n".join(fix.find_items_needing_review(self.db))
        self.assertIn(
            "Link Citation Media (1): media files do not follow the Media Fix rules",
            review,
        )

    def test_gallery_media_can_be_detached(self) -> None:
        """Media that passes Media Fix may be detached from a gallery."""
        c_h, m_h = self._add_census_candidate("Hall", "1900")
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

            m = self._media("Clark_1920_Census_Sheet_02A.jpg")
            m_h = self.db.add_media(m, trans)

            ref = MediaRef()
            ref.set_reference_handle(m_h)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)

        count = auto_link_citation_media(self.db)
        self.assertEqual(count, 1)

        c_obj = self.db.get_citation_from_handle(c_h)
        self.assertEqual(len(c_obj.get_media_list()), 1)

    def test_review_rows_start_on_skip(self) -> None:
        """A Review (ambiguous) match is not linked unless the user picks it.

        The dialog's default, its Accept hints and Accept all hints agree.
        """
        import dataclasses

        from gramps.plugins.tool import gw_linkcitationmediadialog as linkmod

        with DbTxn("Setup review candidate", self.db) as trans:
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
            m_h = self.db.add_media(
                self._media("Clark_1920_Census_Sheet_02A.jpg"), trans
            )
            ref = MediaRef()
            ref.set_reference_handle(m_h)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)

        real_find = linkmod.find_promotable_gallery_media

        def as_review(db: Any) -> list[dict[str, Any]]:
            items = real_find(db)
            for item in items:
                item["compatibility"] = dataclasses.replace(
                    item["compatibility"], status="ambiguous"
                )
            return items

        with patch.object(linkmod, "find_promotable_gallery_media", as_review):
            rows = build_link_citation_media_rows(self.db)
            self.assertEqual([r["status"] for r in rows], ["ambiguous"])
            self.assertEqual(rows[0]["hint_target"], "skip")
            self.assertEqual(rows[0]["chosen_action"], "skip")
            self.assertEqual(auto_link_citation_media(self.db), 0)
        self.assertEqual(self.db.get_citation_from_handle(c_h).get_media_list(), [])

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

            m = self._media("Davis_1910_Census_Sheet_5A.jpg")
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


# Test discovery imports every test module before running any, so take the
# fakes off Gtk again now that the GWizard modules are imported; other Gramps
# tests need the real widgets.  setUpModule puts them back for this module.
gwizard_gtk_fakes.uninstall()


if __name__ == "__main__":
    unittest.main()
