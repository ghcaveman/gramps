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

"""Tests for the NARA API request counter (gwizardnarausage)."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import datetime
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
import requests

from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface
from gramps.gen.gwizard.gwizardnarausage import (
    KIND_RECORD,
    KIND_SEARCH,
    KIND_VALIDATE,
    NaraUsage,
    limit_headers,
    month_key,
    next_reset,
)

_UTC = datetime.timezone.utc


class _Clock:
    """A settable clock for NaraUsage."""

    def __init__(self, when: datetime.datetime) -> None:
        self.when = when

    def __call__(self) -> datetime.datetime:
        return self.when


def _response(status: int = 200, headers: dict | None = None) -> requests.Response:
    """Return a real requests.Response with a status and headers."""
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response._content = b'{"body": {"hits": {"hits": []}}}'
    return response


# ------------------------------------------------------------------
#
# NaraUsageTest
#
# ------------------------------------------------------------------
class NaraUsageTest(unittest.TestCase):
    """Counting requests by month in the usage file."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "nara", "usage.json")
        self.clock = _Clock(datetime.datetime(2026, 11, 26, 15, 0, tzinfo=_UTC))
        self.usage = NaraUsage(self.path, clock=self.clock)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_month_helpers(self) -> None:
        """Months are keyed YYYY-MM and reset on the 1st of the next."""
        self.assertEqual(month_key(self.clock()), "2026-11")
        self.assertEqual(next_reset(self.clock()), datetime.date(2026, 12, 1))
        december = datetime.datetime(2026, 12, 31, tzinfo=_UTC)
        self.assertEqual(next_reset(december), datetime.date(2027, 1, 1))

    def test_counts_and_saves(self) -> None:
        """Each request adds one, by kind, and is written to the file."""
        self.assertEqual(self.usage.used(), 0)
        self.assertEqual(self.usage.record(KIND_SEARCH, 200), 1)
        self.usage.record(KIND_SEARCH, 200)
        self.usage.record(KIND_RECORD, 200)
        self.assertEqual(self.usage.used(), 3)
        self.assertEqual(self.usage.remaining(), 9997)
        detail = self.usage.month_detail()
        self.assertEqual(detail[KIND_SEARCH], 2)
        self.assertEqual(detail[KIND_RECORD], 1)
        with open(self.path, encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertEqual(stored["months"]["2026-11"]["total"], 3)
        # A second counter on the same file (another window) sees the count.
        self.assertEqual(NaraUsage(self.path, clock=self.clock).used(), 3)

    def test_new_month_starts_at_zero(self) -> None:
        """The count starts again on the first of the month."""
        self.usage.record(KIND_SEARCH, 200)
        self.clock.when = datetime.datetime(2026, 12, 1, 0, 1, tzinfo=_UTC)
        self.assertEqual(self.usage.used(), 0)
        self.usage.record(KIND_SEARCH, 200)
        self.assertEqual(self.usage.used(), 1)

    def test_failures_and_block(self) -> None:
        """Refused requests count, by status; 429 marks the month blocked."""
        self.usage.record(KIND_SEARCH, 403)
        self.assertFalse(self.usage.blocked())
        self.usage.record(KIND_SEARCH, 429)
        self.assertTrue(self.usage.blocked())
        self.assertEqual(self.usage.month_detail()["failed"], {"403": 1, "429": 1})
        self.assertIn("over the limit", self.usage.summary_text())

    def test_limit_headers_kept(self) -> None:
        """Rate-limit headers NARA sends are saved; others are not."""
        self.usage.record(
            KIND_VALIDATE,
            200,
            {"X-RateLimit-Remaining": "9000", "Content-Type": "application/json"},
        )
        self.assertEqual(
            self.usage.last_limit_headers(), {"X-RateLimit-Remaining": "9000"}
        )
        self.assertEqual(limit_headers(None), {})

    def test_summary_text(self) -> None:
        """The summary shows used, limit and the reset day."""
        for _i in range(1234):
            self.usage.record(KIND_SEARCH, 200)
        text = self.usage.summary_text()
        self.assertIn("1,234 of 10,000", text)
        self.assertIn("Dec 1", text)

    def test_unreadable_file_starts_over(self) -> None:
        """A damaged file is ignored rather than stopping the search."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(self.usage.used(), 0)
        self.assertEqual(self.usage.record(KIND_SEARCH, 200), 1)

    def test_memory_only(self) -> None:
        """Without a path the count is kept in memory."""
        usage = NaraUsage(None, clock=self.clock)
        usage.record(KIND_SEARCH, 200)
        self.assertEqual(usage.used(), 1)


# ------------------------------------------------------------------
#
# NaraClientCountingTest
#
# ------------------------------------------------------------------
class NaraClientCountingTest(unittest.TestCase):
    """The catalog client counts the requests NARA answers."""

    def setUp(self) -> None:
        self.usage = NaraUsage(None)
        self.client = NaraCatalogInterface(api_key="key", usage=self.usage)

    @patch("gramps.gen.gwizard.gwizardnaramerge.requests.get")
    def test_search_and_record_text_counted(self, get: Mock) -> None:
        """Searches and page-text requests each count once."""
        get.return_value = _response(200)
        self.client.search_records("John Smith")
        self.client.fetch_record_text("123")
        detail = self.usage.month_detail()
        self.assertEqual(detail["total"], 2)
        self.assertEqual(detail[KIND_SEARCH], 1)
        self.assertEqual(detail[KIND_RECORD], 1)

    @patch("gramps.gen.gwizard.gwizardnaramerge.requests.get")
    def test_validate_counted(self, get: Mock) -> None:
        """The API key check is a request too."""
        get.return_value = _response(403)
        self.assertIsNotNone(self.client.validate_api_key())
        self.assertEqual(self.usage.month_detail()["failed"], {"403": 1})

    @patch("gramps.gen.gwizard.gwizardnaramerge.requests.get")
    def test_refused_request_counted(self, get: Mock) -> None:
        """A 429 answer counts and marks the month as blocked."""
        get.return_value = _response(429)
        self.assertIsNone(self.client.search_records("John Smith"))
        self.assertEqual(self.usage.used(), 1)
        self.assertTrue(self.usage.blocked())

    @patch("gramps.gen.gwizard.gwizardnaramerge.requests.get")
    def test_unanswered_request_not_counted(self, get: Mock) -> None:
        """A request that never reached NARA is not counted."""
        get.side_effect = requests.exceptions.ConnectionError("down")
        self.assertIsNone(self.client.search_records("John Smith"))
        self.assertEqual(self.usage.used(), 0)

    @patch("gramps.gen.gwizard.gwizardnaramerge.shared_usage")
    @patch("gramps.gen.gwizard.gwizardnaramerge.requests.get")
    def test_stand_in_answers_not_counted(self, get: Mock, shared: Mock) -> None:
        """With the shared counter, test stand-ins never add to the count."""
        get.return_value = Mock(status_code=200, headers={})
        NaraCatalogInterface(api_key="key").search_records("John Smith")
        shared.assert_not_called()


if __name__ == "__main__":
    unittest.main()
