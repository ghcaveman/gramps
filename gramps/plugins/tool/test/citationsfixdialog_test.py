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

"""Tests for CitationFixDialog and citation fix row construction."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
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

    class _FakeDialog:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_content_area(self) -> MagicMock:
            return MagicMock()

        def add_button(self, *args: Any, **kwargs: Any) -> None:
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
from gramps.plugins.tool.citationsfixdialog import (
    CitationFixDialog,
    build_citation_fix_rows,
)


# ------------------------------------------------------------
#
# Fake database objects for testing
#
# ------------------------------------------------------------
class FakeSource:
    """Mock Source object."""

    def __init__(self, handle: str, title: str) -> None:
        self.handle = handle
        self.title = title

    def get_handle(self) -> str:
        """Return the mock handle."""
        return self.handle

    def get_title(self) -> str:
        """Return the mock title."""
        return self.title


class FakeCitation:
    """Mock Citation object."""

    def __init__(
        self,
        handle: str,
        ref_handle: str,
        gramps_id: str,
        page: str,
        confidence: int = 2,
    ) -> None:
        self.handle = handle
        self.ref_handle = ref_handle
        self.gramps_id = gramps_id
        self.page = page
        self.confidence = confidence

    def get_handle(self) -> str:
        """Return the mock handle."""
        return self.handle

    def get_reference_handle(self) -> str:
        """Return the mock referenced source handle."""
        return self.ref_handle

    def get_gramps_id(self) -> str:
        """Return the mock Gramps ID."""
        return self.gramps_id

    def get_page(self) -> str:
        """Return the mock page or URL string."""
        return self.page

    def get_date_object(self) -> None:
        """Return None for date object."""
        return None

    def get_confidence_level(self) -> int:
        """Return the mock confidence level."""
        return self.confidence

    def get_media_list(self) -> list[str]:
        """Return empty media list."""
        return []

    def get_note_list(self) -> list[str]:
        """Return empty note list."""
        return []

    def get_attribute_list(self) -> list[str]:
        """Return empty attribute list."""
        return []


class FakeNote:
    """Mock Note object."""

    def __init__(self, text: str, note_type: int | None = None) -> None:
        self.text = text
        self.type = note_type

    def get_styledtext(self) -> str:
        return self.text

    def get(self) -> str:
        return self.text


class FakeDb:
    """Mock Gramps database."""

    def __init__(
        self,
        sources: list[FakeSource],
        citations: list[FakeCitation],
        notes: dict[str, FakeNote] | None = None,
    ) -> None:
        self.sources = sources
        self.citations = citations
        self.notes = notes or {}

    def iter_sources(self) -> list[FakeSource]:
        """Return mock sources."""
        return self.sources

    def iter_citations(self) -> list[FakeCitation]:
        """Return mock citations."""
        return self.citations

    def get_note_from_handle(self, handle: str) -> FakeNote | None:
        """Return mock note if present."""
        return self.notes.get(handle)


# ------------------------------------------------------------
#
# Test cases
#
# ------------------------------------------------------------
class CitationFixDialogTest(unittest.TestCase):
    """Verify CitationFixDialog and build_citation_fix_rows behavior."""

    def test_volume_page_separated_from_citation_display(self) -> None:
        """Volume/page or URL should be stored in 'page' and included in multi-line citation_display."""
        src = FakeSource(handle="s1", title="Census 1900")
        cit = FakeCitation(
            handle="c1",
            ref_handle="s1",
            gramps_id="C0001",
            page="https://www.familysearch.org/ark:/61903/1:1:M9123",
            confidence=2,
        )
        db = FakeDb(sources=[src], citations=[cit])

        rows = build_citation_fix_rows(db)
        self.assertEqual(len(rows), 1)
        row = rows[0]

        self.assertEqual(
            row["page"], "https://www.familysearch.org/ark:/61903/1:1:M9123"
        )
        self.assertIn("(C0001) |", row["citation_display"])
        self.assertIn(
            "https://www.familysearch.org/ark:/61903/1:1:M9123 |",
            row["citation_display"],
        )

    def test_empty_volume_page(self) -> None:
        """When volume/page is empty, 'page' should be empty string and display uses placeholder."""
        src = FakeSource(handle="s1", title="Parish Register")
        cit = FakeCitation(
            handle="c2",
            ref_handle="s1",
            gramps_id="C0002",
            page="",
            confidence=3,
        )
        db = FakeDb(sources=[src], citations=[cit])

        rows = build_citation_fix_rows(db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["page"], "")
        self.assertIn("(C0002) |", row["citation_display"])
        self.assertNotIn("Confidence", row["citation_display"])

    def test_citation_text_displayed_with_id_in_parens(self) -> None:
        """Actual citation text should be displayed with Gramps ID in parens and combined lines."""
        src = FakeSource(handle="s1", title="Census 1900")
        cit = FakeCitation(
            handle="c3",
            ref_handle="s1",
            gramps_id="C123456",
            page="p. 15B",
            confidence=4,
        )
        cit.get_note_list = lambda: ["n1"]  # type: ignore[assignment]
        note = FakeNote(text="Household record for Lincoln family")
        db = FakeDb(sources=[src], citations=[cit], notes={"n1": note})

        rows = build_citation_fix_rows(db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        expected_lines = [
            "Household record for Lincoln family (C123456) |",
            "p. 15B | conf:  4(3) | — |",
            "Household record for Lincoln family",
        ]
        self.assertEqual(
            row["citation_display"],
            "\n".join(expected_lines),
        )
        self.assertNotIn("Confidence", row["citation_display"])

    def test_build_header_columns(self) -> None:
        """Header should attach 5 columns with proportional spans: Source (3), Citation (12), Conf (2), Date (2), Hint (5)."""
        grid = MagicMock()
        dlg = CitationFixDialog.__new__(CitationFixDialog)
        dlg.build_header(grid)

        self.assertEqual(len(grid.attach.call_args_list), 5)
        cols = [call.args[1] for call in grid.attach.call_args_list]
        spans = [call.args[3] for call in grid.attach.call_args_list]
        self.assertEqual(cols, [0, 3, 15, 17, 19])
        self.assertEqual(spans, [3, 12, 2, 2, 5])
        self.assertEqual(sum(spans), 24)

    def test_build_rows_column_count_and_proportions(self) -> None:
        """build_rows should attach widgets with proportional spans covering 24 units."""
        grid_mock = MagicMock()
        dlg = CitationFixDialog.__new__(CitationFixDialog)
        dlg.combos = []

        row = {
            "source_name": "Test Source",
            "options": ["Option 1"],
            "citation_display": "C0001 |\n— | conf:  2(-) | — |\n—",
            "page": "https://www.familysearch.org/ark:/61903/1:1:M9123",
            "date": "1900",
            "notes_preview": "Some note",
            "notes_text": "Some note text",
            "confidence_display": "2(-)",
            "citation_handle": "c1",
            "best_guess": "Option 1",
        }

        # Mock Gtk.Grid instantiated inside build_rows
        with unittest.mock.patch(
            "gramps.plugins.tool.citationsfixdialog.Gtk.Grid",
            return_value=grid_mock,
        ):
            dlg.build_rows([row])

        attached_cols = [call.args[1] for call in grid_mock.attach.call_args_list]
        attached_spans = [call.args[3] for call in grid_mock.attach.call_args_list]
        self.assertEqual(len(grid_mock.attach.call_args_list), 5)
        self.assertEqual(attached_cols, [0, 3, 15, 17, 19])
        self.assertEqual(attached_spans, [3, 12, 2, 2, 5])
        self.assertEqual(sum(attached_spans), 24)
        self.assertEqual(len(dlg.combos), 1)


if __name__ == "__main__":
    unittest.main()
