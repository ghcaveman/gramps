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

"""Unit tests for GWizardCitationReport (gwizardcitationreport.py)."""

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
from unittest.mock import MagicMock

# -------------------------------------------------------------------------
#
# GTK mock fallback when running without display or PyGObject
#
# -------------------------------------------------------------------------
if "gi" not in sys.modules:
    gi_mock = MagicMock()
    sys.modules["gi"] = gi_mock
    sys.modules["gi.repository"] = gi_mock.repository

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
from gramps.plugins.tool.gwizardcitationmediaengine import (
    apply_link_media_to_citation,
)
from gramps.plugins.tool.gwizardcitationreport import (
    GWizardCitationReport,
    collect_db_stats,
)


class GWizardCitationReportTest(unittest.TestCase):
    """Test suite for citation and media reporting."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        self.db.close()

    def test_collect_stats_empty_db(self) -> None:
        """collect_db_stats returns zero counts and clean health on empty database."""
        report = GWizardCitationReport()
        stats = report.collect_db_stats(self.db)

        self.assertEqual(stats["people"], 0)
        self.assertEqual(stats["sources"], 0)
        self.assertEqual(stats["citations"], 0)
        self.assertEqual(stats["media"], 0)
        self.assertEqual(stats["media_in_galleries_promotable"], 0)
        self.assertEqual(stats["media_on_sources_unpackable"], 0)
        self.assertEqual(len(stats["suspect_citation_media"]), 0)

        text = report.format_analysis(stats)
        self.assertIn("Database totals: 0 people", text)
        self.assertIn("Suggested order of fixes:", text)
        self.assertIn("Link Citation Media", text)

    def test_collect_and_format_media_hygiene_stats(self) -> None:
        """collect_db_stats and format_analysis report promotable gallery media and suspect attachments."""
        with DbTxn("Setup test data", self.db) as trans:
            src = Source()
            src.set_title("1940 Federal Population Schedule")
            s_h = self.db.add_source(src, trans)

            cit1 = Citation()
            cit1.set_reference_handle(s_h)
            cit1.set_page("Sheet 04A")
            c1_h = self.db.add_citation(cit1, trans)

            # Promotable document in Person gallery
            person = Person()
            name = Name()
            sname = Surname()
            sname.set_surname("Franklin")
            name.add_surname(sname)
            name.set_first_name("Benjamin")
            person.set_primary_name(name)
            person.add_citation(c1_h)

            m_doc = Media()
            m_doc.set_path("Franklin_1940_Census_Sheet_04A.jpg")
            m_doc_h = self.db.add_media(m_doc, trans)

            ref = MediaRef()
            ref.set_reference_handle(m_doc_h)
            person.add_media_reference(ref)
            self.db.add_person(person, trans)

            # Suspect attachment: Citation 2 with conflicting Death Certificate
            cit2 = Citation()
            cit2.set_reference_handle(s_h)
            cit2.set_page("Sheet 10B")
            c2_h = self.db.add_citation(cit2, trans)

            m_bad = Media()
            m_bad.set_path("Death_Certificate_1860.jpg")
            m_bad_h = self.db.add_media(m_bad, trans)
            apply_link_media_to_citation(self.db, trans, c2_h, m_bad_h)

        report = GWizardCitationReport()
        stats = report.collect_db_stats(self.db)

        self.assertEqual(stats["media_in_galleries_promotable"], 1)
        self.assertEqual(len(stats["suspect_citation_media"]), 1)
        suspect_item = stats["suspect_citation_media"][0]
        self.assertEqual(suspect_item["citation_handle"], c2_h)
        self.assertEqual(suspect_item["media_handle"], m_bad_h)

        text = report.format_analysis(stats)
        self.assertIn(
            "Document scans in Person/Event galleries matching citations: 1 items", text
        )
        self.assertIn(
            "Suspect media attachments on citations: 1 conflicts detected", text
        )
        self.assertIn("Death_Certificate_1860", text)
        self.assertIn("Link Citation Media", text)


if __name__ == "__main__":
    unittest.main()
