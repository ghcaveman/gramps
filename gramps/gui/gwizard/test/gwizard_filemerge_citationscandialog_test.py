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
Unit tests for the GWizard Citation Improvement Scan window
(gwizard_filemerge_citationscandialog). The window
tests need a display and are skipped without one; confidence_cell runs
everywhere.
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
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.gwizard.gwizard_base import RecordCandidate, RecordQuery
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    STATUS_ERROR,
    STATUS_OK,
    PersonScan,
    RecordSource,
    ScanCache,
    SourceMatch,
)
from gramps.gen.lib import Attribute, Citation, Name, Person, Source, Surname
from gramps.gen.gwizard.gwizard_filemerge_citationscan import (
    CitationItem,
    CitationMatch,
    CitationSource,
)


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


def _match(key: str, given: str, surname: str) -> SourceMatch:
    """Return a record for a person."""
    return SourceMatch(
        key=key,
        label=f"Record {key}",
        candidate=RecordCandidate(given=given, surnames=[surname]),
    )


class FakeSource(RecordSource):
    """A record source answering by surname, recording what it opened."""

    source_id = "fake"
    title = "Fake"
    min_interval = 0.0

    def __init__(self) -> None:
        """Records: two for Smith, none for Jones."""
        self.records = {
            "Smith": [_match("S1", "John", "Smith"), _match("S2", "John", "Smyth")],
            "Brown": [_match("B1", "Peter", "Brown")],
        }
        self.searched: list[str] = []
        self.opened: list[tuple[str, str]] = []
        self.searches_opened: list[str] = []

    def search(self, query: RecordQuery) -> list[SourceMatch]:
        """Return the stored records for the first surname."""
        surname = query.surnames[0] if query.surnames else ""
        self.searched.append(surname)
        return list(self.records.get(surname, []))

    def open_merge(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        match: SourceMatch,
        parent: Any = None,
    ) -> bool:
        """Record the merge."""
        self.opened.append((person_handle, match.key))
        return False

    def open_search(
        self, dbstate: Any, uistate: Any, person_handle: str, parent: Any = None
    ) -> bool:
        """Record the search."""
        self.searches_opened.append(person_handle)
        return False


class RecordIdSource(CitationSource):
    """FakeSource's citation adapter: a RECORDID attribute cites a record."""

    source_id = "fake"

    def record_keys(self, db: Any, citation: Citation) -> list[str]:
        """Return the RECORDID attributes."""
        return [
            str(a.get_value())
            for a in citation.get_attribute_list()
            if str(a.get_type()) == "RECORDID"
        ]


class FakeMeter:
    """A progress meter that never shows."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        """Nothing to set up."""
        self.closed = False

    def set_pass(self, _header: str = "", _total: int = 0) -> None:
        """Ignore."""

    def set_header(self, _text: str) -> None:
        """Ignore."""

    def step(self) -> bool:
        """Never cancel."""
        return False

    def get_cancelled(self) -> bool:
        """Never cancelled."""
        return False

    def close(self) -> None:
        """Remember it closed."""
        self.closed = True


# ------------------------------------------------------------
#
# confidence_cell
#
# ------------------------------------------------------------
class ConfidenceCellTest(unittest.TestCase):
    """The text of a confidence cell."""

    def test_cells(self) -> None:
        """Each state of a cell."""
        try:
            from gramps.gui.gwizard.gwizard_filemerge_citationscandialog import (
                confidence_cell,
            )
        except (ImportError, ValueError):
            self.skipTest("Gtk is not available")
        item = CitationItem("c", "C1", people=[("p", "John Smith")])
        ok = PersonScan("fake", "p", STATUS_OK)
        match = CitationMatch(_match("S1", "John", "Smith"), 90, 0.5, 97.5)
        weak = CitationMatch(_match("S2", "John", "Smyth"), 50, 0, 50)
        self.assertEqual(confidence_cell(item, "fake", None, [], 70)[0], "")
        self.assertEqual(confidence_cell(item, "fake", ok, [], 70)[0], "–")
        self.assertEqual(
            confidence_cell(item, "fake", ok, [match, weak], 70)[0], "1 · 98%"
        )
        self.assertEqual(confidence_cell(item, "fake", ok, [weak], 70)[0], "0 · 50%")
        error = PersonScan("fake", "p", STATUS_ERROR)
        self.assertEqual(confidence_cell(item, "fake", error, [], 70)[0], "error")
        item.record_keys = {"fake": ["S9"]}
        self.assertEqual(confidence_cell(item, "fake", ok, [], 70)[0], "cited")
        self.assertEqual(
            confidence_cell(CitationItem("d", "C2"), "fake", ok, [], 70)[0],
            "no person",
        )


# ------------------------------------------------------------
#
# CitationScanDialog
#
# ------------------------------------------------------------
@unittest.skipUnless(_HAS_GTK_DISPLAY, "needs a Gtk display")
class CitationScanDialogTest(unittest.TestCase):
    """The window with a fake source."""

    def setUp(self) -> None:
        """Three people, each with one citation of different quality."""
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.people: dict[str, str] = {}
        self.cites: dict[str, str] = {}
        with DbTxn("tree", self.db) as trans:
            source = Source()
            source.set_title("Census")
            self.db.add_source(source, trans)
            for given, surname, page in (
                ("John", "Smith", ""),
                ("Mary", "Jones", "Sheet 1, line 2"),
                ("Peter", "Brown", "Sheet 3, line 4"),
            ):
                citation = Citation()
                citation.set_reference_handle(source.get_handle())
                citation.set_page(page)
                if surname == "Brown":
                    attribute = Attribute()
                    attribute.set_type("RECORDID")
                    attribute.set_value("B1")
                    citation.add_attribute(attribute)
                self.db.add_citation(citation, trans)
                person = Person()
                name = Name()
                name.set_first_name(given)
                surn = Surname()
                surn.set_surname(surname)
                name.add_surname(surn)
                person.set_primary_name(name)
                person.add_citation(citation.get_handle())
                self.db.add_person(person, trans)
                self.people[surname] = person.get_handle()
                self.cites[surname] = citation.get_handle()

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
        """Open the window on the fake source with its citation adapter."""
        from gramps.gui.gwizard.gwizard_filemerge_citationscandialog import (
            CitationScanDialog,
        )

        adapter = RecordIdSource()
        dialog = CitationScanDialog(
            self.dbstate,
            sources=[self.source],
            adapters={"fake": adapter},
            cache=ScanCache(self.cache_path),
        )
        self.addCleanup(dialog.destroy)
        return dialog

    def _cell(self, dialog: Any, surname: str) -> str:
        """Return a citation's confidence cell."""
        group = dialog.columns[0]
        return dialog.store.get_value(dialog.rows[self.cites[surname]], group.text)

    def test_worst_first_with_person(self) -> None:
        """The list starts with the citation needing the most work."""
        from gramps.gui.gwizard.gwizard_filemerge_citationscandialog import (
            COL_ID,
            COL_PERSON,
        )

        dialog = self._dialog()
        first = dialog.sort_model[0]
        self.assertEqual(first[COL_PERSON], "Smith, John")
        works = [row[1] for row in dialog.sort_model]
        self.assertEqual(works, sorted(works, reverse=True))
        self.assertTrue(first[COL_ID])

    def test_scan_and_cited(self) -> None:
        """A scan fills confidence cells; a NAID citation shows cited."""
        dialog = self._dialog()
        dialog.work_spin.set_value(0)
        people, skipped = dialog.scan_plan([self.source])
        self.assertEqual(skipped, 0)
        dialog.run_scan([self.source], people, True, FakeMeter)
        self.assertRegex(self._cell(dialog, "Smith"), r"^\d · \d+%$")
        self.assertEqual(self._cell(dialog, "Jones"), "–")
        self.assertEqual(self._cell(dialog, "Brown"), "cited")
        self.assertIn("3 of 3 people searched", dialog.summary_label.get_text())

    def test_people_limit(self) -> None:
        """Only the worst citations' people are searched, up to the limit."""
        dialog = self._dialog()
        dialog.work_spin.set_value(0)
        dialog.max_people_spin.set_value(1)
        people, skipped = dialog.scan_plan([self.source])
        self.assertEqual([p.surname for p in people], ["Smith"])
        self.assertEqual(skipped, 2)
        dialog.run_scan([self.source], people, True, FakeMeter, skipped=skipped)
        self.assertIn("left for the next scan", dialog.status_label.get_text())
        # Smith is saved now and free, so the next plan adds one new person.
        people, skipped = dialog.scan_plan([self.source])
        self.assertEqual(len(people), 2)

    def test_results_shared_through_cache(self) -> None:
        """A second window shows results saved by the first."""
        first = self._dialog()
        first.work_spin.set_value(0)
        people, _skipped = first.scan_plan([self.source])
        first.run_scan([self.source], people, True, FakeMeter)
        first.cache.save()
        second = self._dialog()
        self.assertRegex(self._cell(second, "Smith"), r"^\d · \d+%$")

    def test_open_record(self) -> None:
        """Opening a found record calls the source's merge for the person."""
        dialog = self._dialog()
        dialog.work_spin.set_value(0)
        people, _skipped = dialog.scan_plan([self.source])
        dialog.run_scan([self.source], people, True, FakeMeter)
        group = dialog.columns[0]
        entries = dialog._record_entries(dialog.items[self.cites["Smith"]], [group])
        self.assertTrue(entries)
        entries[0][1]()
        self.assertEqual(self.source.opened[0][0], self.people["Smith"])
        dialog.open_search(self.cites["Jones"], self.source)
        self.assertEqual(self.source.searches_opened, [self.people["Jones"]])

    def test_refresh_after_edit(self) -> None:
        """Editing a citation (here, adding a page) lowers its work."""
        dialog = self._dialog()
        before = dialog.items[self.cites["Smith"]].work
        citation = self.db.get_citation_from_handle(self.cites["Smith"])
        citation.set_page("Sheet 9, line 1")
        with DbTxn("edit", self.db) as trans:
            self.db.commit_citation(citation, trans)
        dialog.refresh_citation(self.cites["Smith"])
        self.assertLess(dialog.items[self.cites["Smith"]].work, before)

    def test_filters_and_export(self) -> None:
        """'Hide the rest' hides low-work citations; CSV has every row."""
        dialog = self._dialog()
        works = sorted(item.work for item in dialog.items.values())
        dialog.work_spin.set_value(works[-1])
        dialog.hide_check.set_active(True)
        self.assertEqual(len(dialog.filter_model), works.count(works[-1]))
        path = os.path.join(self.tmp.name, "out.csv")
        self.assertEqual(dialog.export_csv(path), 3)
        with open(path, encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertIn("Fake Confidence", rows[0])
        self.assertEqual(len(rows), 4)

    def test_tooltips(self) -> None:
        """The issue tooltip lists weights; the source one explains."""
        dialog = self._dialog()
        text = dialog.tooltip_text(self.cites["Smith"], None)
        self.assertIn("Work", text)
        self.assertIn("+", text)
        group = dialog.columns[0]
        self.assertIn(
            "not been searched", dialog.tooltip_text(self.cites["Jones"], group)
        )
        self.assertIn("Cites Fake B1", dialog.tooltip_text(self.cites["Brown"], group))

    def test_show_check_boxes(self) -> None:
        """
        Each source has a "show" check box, on by default; unchecking one
        hides its columns and leaves it out of Scan All, the summary, the
        record choices and the CSV.
        """
        from gramps.gui.gwizard.gwizard_filemerge_citationscandialog import (
            CitationScanDialog,
        )

        class OtherSource(FakeSource):
            source_id = "other"
            title = "Other"

        other = OtherSource()
        dialog = CitationScanDialog(
            self.dbstate,
            sources=[self.source, other],
            adapters={"fake": RecordIdSource()},
            cache=ScanCache(self.cache_path),
        )
        self.addCleanup(dialog.destroy)
        self.assertTrue(all(c.get_active() for c in dialog.show_checks.values()))
        dialog.work_spin.set_value(0)
        people, _skipped = dialog.scan_plan([self.source, other])
        dialog.run_scan([self.source, other], people, True, FakeMeter)
        smith = dialog.items[self.cites["Smith"]]
        self.assertEqual(
            {g.source.source_id for g in dialog._openable(smith)}, {"fake", "other"}
        )

        dialog.show_checks["other"].set_active(False)
        self.assertFalse(
            any(c.get_visible() for c in dialog.source_view_columns["other"])
        )
        self.assertTrue(
            all(c.get_visible() for c in dialog.source_view_columns["fake"])
        )
        self.assertNotIn("Other:", dialog.summary_label.get_text())
        self.assertFalse(dialog.scan_buttons["other"].get_sensitive())
        self.assertEqual(
            [g.source.source_id for g in dialog._openable(smith)], ["fake"]
        )
        from unittest import mock

        with mock.patch.object(dialog, "run_scan") as run_scan:
            dialog.cb_scan(None, None)
        self.assertEqual([s.source_id for s in run_scan.call_args.args[0]], ["fake"])
        path = os.path.join(self.tmp.name, "shown.csv")
        dialog.export_csv(path)
        with open(path, encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        self.assertIn("Fake Confidence", header)
        self.assertFalse(any(name.startswith("Other") for name in header))

        dialog.show_checks["other"].set_active(True)
        self.assertIn("Other:", dialog.summary_label.get_text())


if __name__ == "__main__":
    unittest.main()
