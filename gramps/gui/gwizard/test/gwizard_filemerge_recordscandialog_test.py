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
Unit tests for the GWizard Multi-Archive Record Scan window. The window tests need a
display and are skipped without one; cell_values runs everywhere.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import csv
import os
import sys
import tempfile
import time
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.gwizard.gwizard_base import (
    TIER_GMSB,
    TIER_GS,
    TIER_GSB,
    RecordCandidate,
    RecordQuery,
)
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    STATUS_ERROR,
    STATUS_OK,
    PersonScan,
    RecordSource,
    ScanCache,
    SourceMatch,
    score_matches,
)
from gramps.gen.lib import Name, Person, Surname


def _has_gtk_display() -> bool:
    """Return True only if a real Gtk display is available."""
    if sys.platform not in ("win32", "darwin"):
        if not os.environ.get("DISPLAY") or os.environ.get("GDK_BACKEND") == "-":
            return False
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        return bool(Gtk.init_check([])[0])
    except Exception:
        return False


_HAS_GTK_DISPLAY = _has_gtk_display()


def _match(key: str, given: str, surname: str, birth: int | None) -> SourceMatch:
    """A match for a person."""
    return SourceMatch(
        key,
        f"{given} {surname}",
        RecordCandidate(
            given=given,
            surnames=[surname],
            birth_years=(birth, birth) if birth else None,
        ),
    )


# ------------------------------------------------------------
#
# FakeSource
#
# ------------------------------------------------------------
class FakeSource(RecordSource):
    """Answers from a dict and records merges opened."""

    source_id = "fake"
    title = "Fake"
    min_interval = 0.0

    def __init__(self) -> None:
        """Two candidates for White, one for Devault."""
        self.records = {
            "White": [
                _match("W1", "Kevin", "White", 1958),
                _match("W2", "Kevin", "White", None),
            ],
            "Devault": [_match("D1", "Thomas", "Devault", 1842)],
        }
        self.opened: list[tuple[str, str]] = []
        self.delay = 0.0
        self.searched: list[str] = []

    def search(self, query: RecordQuery) -> list[SourceMatch]:
        """Return the records for the first surname, a little slowly."""
        time.sleep(self.delay)
        return list(self.records.get(query.surnames[0] if query.surnames else "", []))

    def open_merge(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        match: SourceMatch,
        parent: Any = None,
    ) -> bool:
        """Record the merge instead of opening a window."""
        self.opened.append((person_handle, match.key))
        return True

    def open_search(
        self, dbstate: Any, uistate: Any, person_handle: str, parent: Any = None
    ) -> bool:
        """Record the search instead of opening a window."""
        self.searched.append(person_handle)
        return False


# ------------------------------------------------------------
#
# FakeMeter
#
# ------------------------------------------------------------
class FakeMeter:
    """A ProgressMeter stand-in that can cancel after some steps."""

    def __init__(self, *_args: Any, cancel_after: int = 0, **_kwargs: Any) -> None:
        """Count steps."""
        self.steps = 0
        self.cancel_after = cancel_after
        self.closed = False

    def set_pass(self, _header: str = "", _total: int = 0) -> None:
        """Ignore."""

    def set_header(self, _text: str) -> None:
        """Ignore."""

    def step(self) -> bool:
        """Count; return True (cancel) after cancel_after steps."""
        self.steps += 1
        return bool(self.cancel_after) and self.steps >= self.cancel_after

    def get_cancelled(self) -> bool:
        """Cancelled after cancel_after steps."""
        return bool(self.cancel_after) and self.steps >= self.cancel_after

    def close(self) -> None:
        """Remember it was closed."""
        self.closed = True


# ------------------------------------------------------------
#
# CellValuesTest
#
# ------------------------------------------------------------
class CellValuesTest(unittest.TestCase):
    """What a tier cell shows."""

    def test_cells(self) -> None:
        """Not scanned, error, below threshold and matched cells."""
        from gramps.gui.gwizard.gwizard_filemerge_recordscandialog import (
            cell_values,
        )

        query = RecordQuery(given="Kevin", surnames=["White"], birth_year=1958)
        scored = score_matches(query, [_match("W1", "Kevin", "White", 1958)])
        scan = PersonScan("fake", "h", STATUS_OK, matches=[])
        self.assertEqual(cell_values(None, [], TIER_GS, 80)[0], "")
        self.assertEqual(cell_values(scan, [], TIER_GS, 80)[0], "–")
        error = PersonScan("fake", "h", STATUS_ERROR, error="x")
        self.assertEqual(cell_values(error, [], TIER_GS, 80)[0], "error")
        text, sort, colour = cell_values(scan, scored, TIER_GSB, 80)
        self.assertEqual(text, "1 · 100%")
        self.assertEqual(sort, 100.0)
        self.assertIsNotNone(colour)
        self.assertEqual(cell_values(scan, scored, TIER_GSB, 101)[0], "0 · 100%")
        self.assertEqual(cell_values(scan, scored, TIER_GMSB, 80)[0], "n/a")

    def test_tier_gap(self) -> None:
        """The tooltip names what is missing, in the tree or the records."""
        from gramps.gui.gwizard.gwizard_filemerge_recordscandialog import tier_gap

        query = RecordQuery(given="Kevin", surnames=["White"], birth_year=1958)
        scored = score_matches(query, [_match("W1", "Kevin", "White", 1958)])
        self.assertIn("no middle name in the tree", tier_gap(query, scored, TIER_GMSB))
        query.middle = "Lee"
        scored = score_matches(query, [_match("W1", "Kevin", "White", 1958)])
        self.assertIn("records found has a middle", tier_gap(query, scored, TIER_GMSB))
        query.birth_year = None
        self.assertIn("no birth year in the tree", tier_gap(query, scored, TIER_GSB))


# ------------------------------------------------------------
#
# RecordScanDialogTest
#
# ------------------------------------------------------------
@unittest.skipUnless(_HAS_GTK_DISPLAY, "needs a Gtk display")
class RecordScanDialogTest(unittest.TestCase):
    """The window with a fake source."""

    def setUp(self) -> None:
        """A tree with three people."""
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.handles: dict[str, str] = {}
        with DbTxn("people", self.db) as trans:
            for given, surname in (
                ("Kevin", "White"),
                ("Thomas", "Devault"),
                ("Ann", "Abbot"),
            ):
                person = Person()
                name = Name()
                name.set_first_name(given)
                surn = Surname()
                surn.set_surname(surname)
                name.add_surname(surn)
                person.set_primary_name(name)
                person.set_gender(Person.MALE)
                self.db.add_person(person, trans)
                self.handles[surname] = person.get_handle()

        class DbState:
            """Minimal dbstate."""

            db = self.db

        self.dbstate = DbState()
        self.source = FakeSource()
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.tmp.name, "scan.json")

    def tearDown(self) -> None:
        """Close everything."""
        self.db.close()
        self.tmp.cleanup()

    def _dialog(self) -> Any:
        """Open the window on the fake source."""
        from gramps.gui.gwizard.gwizard_filemerge_recordscandialog import (
            RecordScanDialog,
        )

        dialog = RecordScanDialog(
            self.dbstate, sources=[self.source], cache=ScanCache(self.cache_path)
        )
        self.addCleanup(dialog.destroy)
        return dialog

    def _cell(self, dialog: Any, surname: str, tier: str) -> str:
        """Return a tier cell's text."""
        group = dialog.columns[0]
        return dialog.store.get_value(
            dialog.rows[self.handles[surname]], group.tiers[tier][0]
        )

    def test_scan_fills_cells_and_summary(self) -> None:
        """A scan fills the cells; the summary counts people per tier."""
        dialog = self._dialog()
        self.assertEqual(len(dialog.rows), 3)
        done = dialog.run_scan(
            [self.source], list(dialog.items.values()), True, FakeMeter
        )
        self.assertEqual(done, 3)
        self.assertEqual(self._cell(dialog, "White", TIER_GS), "2 · 100%")
        self.assertEqual(self._cell(dialog, "Devault", TIER_GS), "1 · 100%")
        self.assertEqual(self._cell(dialog, "Abbot", TIER_GS), "–")
        self.assertEqual(self._cell(dialog, "White", TIER_GMSB), "n/a")
        self.assertIn("3 of 3 scanned", dialog.summary_label.get_text())
        self.assertIn("2 g/s", dialog.summary_label.get_text())

    def test_saved_results_shown_on_open(self) -> None:
        """Results saved by one window are shown by the next."""
        first = self._dialog()
        first.run_scan([self.source], list(first.items.values()), True, FakeMeter)
        second = self._dialog()
        self.assertEqual(self._cell(second, "White", TIER_GS), "2 · 100%")

    def test_threshold_and_filter(self) -> None:
        """A higher threshold redraws; matches-only hides empty rows."""
        dialog = self._dialog()
        dialog.run_scan([self.source], list(dialog.items.values()), True, FakeMeter)
        dialog.threshold_spin.set_value(100)
        self.assertEqual(self._cell(dialog, "White", TIER_GS), "2 · 100%")
        dialog.matches_only_check.set_active(True)
        self.assertEqual(len(dialog.filter_model), 2)
        dialog.matches_only_check.set_active(False)
        self.assertEqual(len(dialog.filter_model), 3)

    def test_cancel(self) -> None:
        """Cancelling stops the scan early."""
        dialog = self._dialog()
        self.source.delay = 0.2
        meter = FakeMeter(cancel_after=1)
        done = dialog.run_scan(
            [self.source], list(dialog.items.values()), True, lambda *a, **k: meter
        )
        self.assertLess(done, 3)
        self.assertTrue(meter.closed)
        self.assertIn("cancelled", dialog.status_label.get_text())

    def test_open_merge_single_and_offer(self) -> None:
        """One match opens directly; the source records the merge."""
        dialog = self._dialog()
        dialog.run_scan([self.source], list(dialog.items.values()), True, FakeMeter)
        dialog.offer_matches(self.handles["Devault"], self.source, TIER_GSB)
        self.assertEqual(self.source.opened, [(self.handles["Devault"], "D1")])
        # Two matches for White: a menu is offered and nothing opens yet.
        dialog.offer_matches(self.handles["White"], self.source, TIER_GS)
        self.assertEqual(len(self.source.opened), 1)
        scored = dialog.scored[("fake", self.handles["White"])]
        dialog.cb_menu_merge(None, self.handles["White"], self.source, scored[0])
        self.assertEqual(self.source.opened[-1][0], self.handles["White"])

    def test_export_csv(self) -> None:
        """The CSV has a header and one row per person."""
        dialog = self._dialog()
        dialog.run_scan([self.source], list(dialog.items.values()), True, FakeMeter)
        path = os.path.join(self.tmp.name, "out.csv")
        self.assertEqual(dialog.export_csv(path), 3)
        with open(path, encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(len(rows), 4)
        self.assertIn("Fake g/s", rows[0])
        self.assertEqual(rows[1][0], "Abbot")


if __name__ == "__main__":
    unittest.main()
