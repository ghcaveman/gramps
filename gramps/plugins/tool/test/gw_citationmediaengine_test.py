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

"""Unit tests for GWizard Citation Media Engine (gwizardcitationmediaengine.py)."""

from __future__ import annotations

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import unittest

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
    Date,
    Media,
    MediaRef,
    Name,
    Person,
    Source,
    Surname,
)
from gramps.plugins.tool.gwizard_common import lock_media
from gramps.plugins.tool.gwizardcitationmediaengine import (
    CitationIdentity,
    MediaIdentity,
    apply_link_media_to_citation,
    apply_promote_media_to_citation,
    audit_existing_citation_media_links,
    compute_citation_media_compatibility,
    detect_category,
    extract_citation_identity,
    extract_media_identity,
    extract_sheet_page,
    extract_year,
    find_orphan_media_matches,
    find_promotable_gallery_media,
    find_unpackable_source_media,
)
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)


# ------------------------------------------------------------
#
# Test cases
#
# ------------------------------------------------------------
class GWizardCitationMediaEngineTest(unittest.TestCase):
    """Test suite for media-citation analysis, heuristics, and scanners."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        self.db.close()

    def test_extract_year_and_category(self) -> None:
        """extract_year and detect_category extract appropriate tokens."""
        self.assertEqual(extract_year("1940 US Federal Census Sheet 12A"), "1940")
        self.assertEqual(extract_year("No year in this title"), "")
        self.assertEqual(extract_year("Marriage on 15 Jun 1912"), "1912")

        self.assertEqual(detect_category("1930 Census Population Schedule"), "census")
        self.assertEqual(detect_category("Death Certificate of John Doe"), "death")
        self.assertEqual(
            detect_category("Marriage License and Certificate"), "marriage"
        )
        self.assertEqual(detect_category("Headstone at Oakridge Cemetery"), "death")
        self.assertEqual(detect_category("John Doe Portrait Photograph"), "portrait")

    def test_extract_sheet_page(self) -> None:
        """extract_sheet_page extracts sheet, page, and ED numbers."""
        self.assertEqual(extract_sheet_page("Sheet 14B line 4"), "14B")
        self.assertEqual(extract_sheet_page("ED 16-100, page 12"), "12")
        self.assertEqual(extract_sheet_page("cert 402"), "402")
        self.assertEqual(extract_sheet_page("Just some generic notes"), "")

    def test_extract_sheet_page_ignores_years(self) -> None:
        """A year after "certificate" or "line" is not a sheet or page number."""
        self.assertEqual(extract_sheet_page("Death_Certificate_1860"), "")
        self.assertEqual(extract_sheet_page("Certificate_1860_page_7"), "7")
        self.assertEqual(extract_sheet_page("Adams_1940_Census_Sheet_12A"), "12A")

    def test_year_in_file_name_is_not_a_sheet_mismatch(self) -> None:
        """A death certificate is flagged for its category, not a sheet number."""
        media = MediaIdentity(
            filename="Death_Certificate_1860",
            sheet_page=extract_sheet_page("Death_Certificate_1860"),
            category="death",
            year="1860",
        )
        citation = CitationIdentity(
            source_title="1940 Federal Population Schedule",
            page="Sheet 10B",
            sheet_page="10B",
            category="census",
            year="1940",
        )
        result = compute_citation_media_compatibility(media, citation)
        self.assertEqual(result.status, "conflict")
        self.assertFalse(any("Sheet/Page" in text for text in result.conflicts))

    def test_extract_media_identity(self) -> None:
        """extract_media_identity captures filename, year, category, and portrait flags."""
        with DbTxn("Create media", self.db) as trans:
            m1 = Media()
            m1.set_path("Smith_John_1940_Census_Sheet_12A.jpg")
            m1.set_description("1940 Census record for John Smith")
            h1 = self.db.add_media(m1, trans)

            m2 = Media()
            m2.set_path("Doe_Jane_Portrait.jpg")
            m2.set_description("Profile photograph of Jane Doe")
            h2 = self.db.add_media(m2, trans)

            m3 = Media()
            m3.set_path("Miller_William_1880.png")
            lock_media(self.db, m3, txn=trans)
            h3 = self.db.add_media(m3, trans)

        id1 = extract_media_identity(self.db.get_media_from_handle(h1), self.db)
        self.assertEqual(id1.year, "1940")
        self.assertEqual(id1.category, "census")
        self.assertEqual(id1.surname, "smith")
        self.assertEqual(id1.given, "john")
        self.assertEqual(id1.sheet_page, "12A")
        self.assertFalse(id1.is_portrait)
        self.assertFalse(id1.is_locked)

        id2 = extract_media_identity(self.db.get_media_from_handle(h2), self.db)
        self.assertTrue(id2.is_portrait)
        self.assertEqual(id2.category, "portrait")

        id3 = extract_media_identity(self.db.get_media_from_handle(h3), self.db)
        self.assertTrue(id3.is_locked)

    def test_extract_citation_identity(self) -> None:
        """extract_citation_identity extracts source metadata and backlinked person names."""
        with DbTxn("Create citation hierarchy", self.db) as trans:
            src = Source()
            src.set_title("1940 United States Federal Census")
            s_handle = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_handle)
            cit.set_page("ED 16-432, Sheet 12A, household 45")
            d = Date()
            d.set_year(1940)
            cit.set_date_object(d)
            c_handle = self.db.add_citation(cit, trans)

            person = Person()
            name = Name()
            sname = Surname()
            sname.set_surname("Smith")
            name.add_surname(sname)
            name.set_first_name("John")
            person.set_primary_name(name)
            person.add_citation(c_handle)
            self.db.add_person(person, trans)

        c_obj = self.db.get_citation_from_handle(c_handle)
        c_id = extract_citation_identity(self.db, c_obj)

        self.assertEqual(c_id.source_title, "1940 United States Federal Census")
        self.assertEqual(c_id.year, "1940")
        self.assertEqual(c_id.category, "census")
        self.assertEqual(c_id.sheet_page, "12A")
        self.assertIn("smith", c_id.surnames)
        self.assertIn("john", c_id.givens)

    def test_compatibility_scoring_safe_match(self) -> None:
        """Matching year, category, surname, and sheet yields a high safe score."""
        media = MediaIdentity(
            year="1940",
            category="census",
            surname="smith",
            given="john",
            sheet_page="12A",
            raw_tokens=["1940", "census", "smith", "john", "sheet", "12a"],
        )
        cit = CitationIdentity(
            year="1940",
            category="census",
            surnames=["smith"],
            givens=["john"],
            sheet_page="12A",
            raw_tokens=["1940", "census", "cook", "sheet", "12a"],
        )
        res = compute_citation_media_compatibility(media, cit)
        self.assertEqual(res.status, "safe")
        self.assertTrue(res.is_match)
        self.assertGreaterEqual(res.score, 80)
        self.assertEqual(len(res.conflicts), 0)

    def test_compatibility_scoring_severe_category_conflict(self) -> None:
        """Incompatible category pairing (e.g. Census vs Marriage) triggers severe conflict."""
        media = MediaIdentity(
            year="1920",
            category="marriage",
            surname="jones",
        )
        cit = CitationIdentity(
            year="1920",
            category="census",
            surnames=["jones"],
        )
        res = compute_citation_media_compatibility(media, cit)
        self.assertEqual(res.status, "conflict")
        self.assertFalse(res.is_match)
        self.assertTrue(any("category conflict" in c.lower() for c in res.conflicts))

    def test_compatibility_scoring_year_mismatch(self) -> None:
        """Chronological mismatch between image and citation triggers conflict."""
        media = MediaIdentity(
            year="1940",
            category="census",
            surname="smith",
        )
        cit = CitationIdentity(
            year="1910",
            category="census",
            surnames=["smith"],
        )
        res = compute_citation_media_compatibility(media, cit)
        self.assertEqual(res.status, "conflict")
        self.assertTrue(any("year mismatch" in c.lower() for c in res.conflicts))

    def test_compatibility_scoring_surname_mismatch(self) -> None:
        """Conflicting surnames penalize score and produce conflict warning."""
        media = MediaIdentity(
            year="1940",
            category="census",
            surname="smith",
        )
        cit = CitationIdentity(
            year="1940",
            category="census",
            surnames=["williams", "brown"],
        )
        res = compute_citation_media_compatibility(media, cit)
        self.assertEqual(res.status, "conflict")
        self.assertTrue(any("surname mismatch" in c.lower() for c in res.conflicts))

    def test_find_promotable_gallery_media(self) -> None:
        """find_promotable_gallery_media detects document scans in Person gallery matching citation."""
        with DbTxn("Create person with doc in gallery", self.db) as trans:
            src = Source()
            src.set_title("1940 United States Census")
            s_handle = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_handle)
            cit.set_page("Sheet 4B")
            c_handle = self.db.add_citation(cit, trans)

            # Document scan in gallery
            m_doc = Media()
            m_doc.set_path("Smith_1940_Census_Sheet_4B.jpg")
            m_doc.set_description("1940 Census Sheet 4B")
            m_doc_h = self.db.add_media(m_doc, trans)

            # Portrait in gallery
            m_port = Media()
            m_port.set_path("Smith_Portrait_Photo.jpg")
            m_port.set_description("Portrait photo")
            m_port_h = self.db.add_media(m_port, trans)

            person = Person()
            name = Name()
            sname = Surname()
            sname.set_surname("Smith")
            name.add_surname(sname)
            person.set_primary_name(name)
            person.add_citation(c_handle)

            ref1 = MediaRef()
            ref1.set_reference_handle(m_doc_h)
            person.add_media_reference(ref1)

            ref2 = MediaRef()
            ref2.set_reference_handle(m_port_h)
            person.add_media_reference(ref2)

            self.db.add_person(person, trans)

        promotable = find_promotable_gallery_media(self.db)
        self.assertEqual(len(promotable), 1)
        item = promotable[0]
        self.assertEqual(item["media_handle"], m_doc_h)
        self.assertEqual(item["citation_handle"], c_handle)
        self.assertEqual(item["action"], "promote_from_person")

    def test_apply_promote_locked_media_detaches(self) -> None:
        """Locked (checked) media is linked to the citation and can leave the gallery."""
        with DbTxn("Setup locked media promote test", self.db) as trans:
            cit = Citation()
            c_handle = self.db.add_citation(cit, trans)

            m = Media()
            m.set_path("Certificate_1912.jpg")
            lock_media(self.db, m, txn=trans)
            m_handle = self.db.add_media(m, trans)

            person = Person()
            ref = MediaRef()
            ref.set_reference_handle(m_handle)
            person.add_media_reference(ref)
            p_handle = self.db.add_person(person, trans)

        with DbTxn("Promote media", self.db) as trans:
            success = apply_promote_media_to_citation(
                self.db,
                trans,
                citation_handle=c_handle,
                media_handle=m_handle,
                detach_from_owner=True,
                owner_type="Person",
                owner_handle=p_handle,
            )
            self.assertTrue(success)

        # Citation should now have the media reference
        cit_after = self.db.get_citation_from_handle(c_handle)
        c_refs = [str(r.ref) for r in cit_after.get_media_list() or []]
        self.assertIn(m_handle, c_refs)

        # The lock means "checked in Media Fix"; detaching changes the
        # person, not the media, so the gallery reference is removed.
        person_after = self.db.get_person_from_handle(p_handle)
        p_refs = [str(r.ref) for r in person_after.get_media_list() or []]
        self.assertNotIn(m_handle, p_refs)

    def test_find_unpackable_source_media(self) -> None:
        """find_unpackable_source_media matches media on master Source to matching child citation."""
        with DbTxn("Setup source unpack test", self.db) as trans:
            src = Source()
            src.set_title("1930 Census Population Schedules")

            m1 = Media()
            m1.set_path("Census_1930_Sheet_12A.jpg")
            m1_h = self.db.add_media(m1, trans)

            ref1 = MediaRef()
            ref1.set_reference_handle(m1_h)
            src.add_media_reference(ref1)
            s_handle = self.db.add_source(src, trans)

            # Child citation matching sheet 12A
            c1 = Citation()
            c1.set_reference_handle(s_handle)
            c1.set_page("Sheet 12A")
            c1_h = self.db.add_citation(c1, trans)

            # Child citation with different sheet
            c2 = Citation()
            c2.set_reference_handle(s_handle)
            c2.set_page("Sheet 04B")
            self.db.add_citation(c2, trans)

        items = find_unpackable_source_media(self.db)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["media_handle"], m1_h)
        self.assertEqual(items[0]["citation_handle"], c1_h)

    def test_find_orphan_media_matches(self) -> None:
        """find_orphan_media_matches matches unlinked media files to media-less citations."""
        with DbTxn("Setup orphan media test", self.db) as trans:
            src = Source()
            src.set_title("1920 US Census")
            s_h = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_h)
            cit.set_page("Sheet 10A")
            d = Date()
            d.set_year(1920)
            cit.set_date_object(d)
            c_h = self.db.add_citation(cit, trans)

            person = Person()
            name = Name()
            sname = Surname()
            sname.set_surname("Johnson")
            name.add_surname(sname)
            person.set_primary_name(name)
            person.add_citation(c_h)
            self.db.add_person(person, trans)

            # Orphan media with matching tokens
            orphan = Media()
            orphan.set_path("Johnson_1920_Census_Sheet_10A.jpg")
            orphan_h = self.db.add_media(orphan, trans)

        orphans = find_orphan_media_matches(self.db)
        self.assertEqual(len(orphans), 1)
        self.assertEqual(orphans[0]["media_handle"], orphan_h)
        self.assertEqual(orphans[0]["citation_handle"], c_h)

    def test_audit_existing_citation_media_links(self) -> None:
        """audit_existing_citation_media_links detects conflict in existing bad attachment."""
        with DbTxn("Setup bad attachment", self.db) as trans:
            src = Source()
            src.set_title("1940 Federal Census")
            s_h = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_h)
            cit.set_page("Sheet 1A")
            c_h = self.db.add_citation(cit, trans)

            # Incompatible media: Death Certificate from 1880
            bad_media = Media()
            bad_media.set_path("Death_Certificate_1880.jpg")
            bm_h = self.db.add_media(bad_media, trans)

            apply_link_media_to_citation(self.db, trans, c_h, bm_h)

        issues = audit_existing_citation_media_links(self.db)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["citation_handle"], c_h)
        self.assertEqual(issues[0]["media_handle"], bm_h)
        self.assertEqual(issues[0]["compatibility"].status, "conflict")

    def test_repair_engine_auto_link_citation_media(self) -> None:
        """GWizardCitationRepairEngine auto_link_citation_media links safe candidates in one transaction."""
        with DbTxn("Setup repair engine test", self.db) as trans:
            src = Source()
            src.set_title("1930 US Census")
            s_h = self.db.add_source(src, trans)

            cit = Citation()
            cit.set_reference_handle(s_h)
            cit.set_page("Sheet 05A")
            c_h = self.db.add_citation(cit, trans)

            person = Person()
            name = Name()
            sname = Surname()
            sname.set_surname("Taylor")
            name.add_surname(sname)
            person.set_primary_name(name)
            person.add_citation(c_h)

            m = Media()
            m.set_path("Taylor_1930_Census_Sheet_05A.jpg")
            m_h = self.db.add_media(m, trans)

            mref = MediaRef()
            mref.set_reference_handle(m_h)
            person.add_media_reference(mref)
            self.db.add_person(person, trans)

        engine = GWizardCitationRepairEngine()
        linked = engine.auto_link_citation_media(self.db, min_score=70)
        self.assertEqual(linked, 1)

        updated_cit = self.db.get_citation_from_handle(c_h)
        self.assertEqual(len(updated_cit.get_media_list()), 1)
        self.assertEqual(str(updated_cit.get_media_list()[0].ref), m_h)


if __name__ == "__main__":
    unittest.main()
