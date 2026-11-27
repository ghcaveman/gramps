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
Unit tests for the NARA side of the GWizard Citation Improvement Scan:
gwizardnaracitesource.NaraCitationSource and
NaraCatalogInterface.fetch_record.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.gwizard.gwizard_base import RecordCandidate
from gramps.gen.gwizard.gwizard_filemerge_citationscan import (
    NO_MEDIA,
    RECORD_NO_MEDIA,
    CitationItem,
)
from gramps.gen.gwizard.gwizard_filemerge_recordscan import SourceMatch
from gramps.gen.lib import Attribute, Citation, MediaRef
from gramps.plugins.tool.gwizardnaracitesource import NaraCitationSource, load_on_reg


class NaraCitationSourceTest(unittest.TestCase):
    """Reading NAIDs, the images check and judging NARA records."""

    def setUp(self) -> None:
        """A census citation for John Smith, 1900."""
        self.item = CitationItem(
            handle="c1",
            gramps_id="C0001",
            source_title="1900 United States Census",
            page="Sheet 4A, Kent County",
            year=1900,
            people=[("p1", "Smith, John")],
        )

    @staticmethod
    def _citation(*naids: str) -> Citation:
        """Return a citation with these NAID attributes."""
        citation = Citation()
        for naid in naids:
            attribute = Attribute()
            attribute.set_type("NAID")
            attribute.set_value(naid)
            citation.add_attribute(attribute)
        return citation

    def test_record_keys(self) -> None:
        """Each NAID once, in order."""
        citation = self._citation("123", "456", "123")
        self.assertEqual(
            NaraCitationSource().record_keys(None, citation), ["123", "456"]
        )
        self.assertEqual(NaraCitationSource().record_keys(None, Citation()), [])

    def test_images_issue(self) -> None:
        """A NARA citation without an image may have images to download."""
        adapter = NaraCitationSource()
        citation = self._citation("123")
        issues = adapter.extra_issues(None, citation, ["123"])
        self.assertEqual([i.code for i in issues], [RECORD_NO_MEDIA])
        self.assertIn("123", issues[0].text)
        self.assertNotEqual(issues[0].code, NO_MEDIA)
        citation.add_media_reference(MediaRef())
        self.assertEqual(adapter.extra_issues(None, citation, ["123"]), [])
        self.assertEqual(adapter.extra_issues(None, Citation(), []), [])

    def test_registration(self) -> None:
        """load_on_reg offers one adapter for the "nara" record source."""
        found = load_on_reg(None, None, None)
        self.assertEqual([a.source_id for a in found], ["nara"])

    def test_nara_relevance_uses_record_dates(self) -> None:
        """NARA judges a record by its title and date range."""
        hit = {
            "_source": {
                "record": {
                    "naId": 99,
                    "title": "Kent County census schedules",
                    "coverageStartDate": {"year": 1900},
                    "coverageEndDate": {"year": 1900},
                }
            }
        }
        match = SourceMatch("99", "x", RecordCandidate(), data={"hit": hit})
        fit = NaraCitationSource().relevance(self.item, match)
        self.assertGreater(fit, 0)


# ------------------------------------------------------------
#
# NaraCatalogInterface.fetch_record
#
# ------------------------------------------------------------
class FetchRecordTest(unittest.TestCase):
    """Fetching one NARA record by its NAID (used to open a cited record)."""

    def test_fetch_record(self) -> None:
        """The hit with the asked NAID is returned; failures give None."""
        from unittest import mock

        from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface
        from gramps.gen.gwizard.gwizardnarausage import NaraUsage

        class Response:
            status_code = 200
            headers: dict[str, str] = {}

            def json(self) -> dict[str, Any]:
                return {
                    "body": {
                        "hits": {
                            "hits": [
                                {"_source": {"record": {"naId": 1, "title": "A"}}},
                                {"_source": {"record": {"naId": 2, "title": "B"}}},
                            ]
                        }
                    }
                }

        usage = mock.MagicMock(spec=NaraUsage)
        client = NaraCatalogInterface(api_key="k", usage=usage)
        with mock.patch(
            "gramps.gen.gwizard.gwizardnaramerge.requests.get",
            return_value=Response(),
        ) as get:
            hit = client.fetch_record("2")
        assert hit is not None
        self.assertEqual(NaraCatalogInterface.parse_record(hit)["title"], "B")
        self.assertEqual(get.call_args.kwargs["params"], {"naId": "2"})
        usage.record.assert_called_once()
        failed = Response()
        failed.status_code = 500
        with mock.patch(
            "gramps.gen.gwizard.gwizardnaramerge.requests.get", return_value=failed
        ):
            self.assertIsNone(client.fetch_record("2"))
