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
from gramps.plugins.tool.gw_citationsfixdialog import (
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

    def test_extract_date_and_url_from_citation_data(self) -> None:
        """Date should be extracted and URL in page moved to notes."""
        src = FakeSource(handle="s1", title="Parish Register")
        cit = FakeCitation(
            handle="c4",
            ref_handle="s1",
            gramps_id="C0004",
            page="Page 10, https://www.example.org/records/1234",
            confidence=2,
        )
        cit.get_note_list = lambda: ["n2"]  # type: ignore[assignment]
        note = FakeNote(text="Marriage on 15 June 1895 accessed 15 June 1895")
        db = FakeDb(sources=[src], citations=[cit], notes={"n2": note})

        rows = build_citation_fix_rows(db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["suggested_date"], "15 June 1895")
        self.assertEqual(row["suggested_page"], "Page 10")
        self.assertEqual(row["suggested_notes"], "https://www.example.org/records/1234")
        self.assertIn("Extract date", row["hint_text"])
        self.assertIn("Move URL to notes", row["hint_text"])

    def test_url_in_note_not_extracted_to_page(self) -> None:
        """URLs in notes must stay in notes and not be extracted to Volume/Page."""
        src = FakeSource(handle="s1", title="Parish Register")
        cit = FakeCitation(
            handle="c5",
            ref_handle="s1",
            gramps_id="C0005",
            page="",
            confidence=2,
        )
        cit.get_note_list = lambda: ["n3"]  # type: ignore[assignment]
        note = FakeNote(text="See https://www.example.org/records/5678")
        db = FakeDb(sources=[src], citations=[cit], notes={"n3": note})

        rows = build_citation_fix_rows(db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["suggested_page"], "")
        self.assertEqual(row["suggested_notes"], "")
        self.assertNotIn("Extract URL", row["hint_text"])

    def test_build_header_columns(self) -> None:
        """Header should attach 7 columns aligned to data columns."""
        grid = MagicMock()
        dlg = CitationFixDialog.__new__(CitationFixDialog)
        dlg.build_header(grid)

        self.assertEqual(len(grid.attach.call_args_list), 7)
        cols = [call.args[1] for call in grid.attach.call_args_list]
        self.assertEqual(cols, [0, 1, 2, 3, 4, 5, 6])

    def test_build_rows_column_count_and_proportions(self) -> None:
        """build_rows should attach widgets to 7 columns with empty target entries."""
        grid_mock = MagicMock()
        dlg = CitationFixDialog.__new__(CitationFixDialog)
        dlg.combos = []
        dlg.row_targets = []

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
            "hint_text": "Lower to Confidence 1",
            "suggested_conf": "1",
        }

        # Mock Gtk.Grid and Gtk.Entry instantiated inside build_rows
        with (
            unittest.mock.patch(
                "gramps.plugins.tool.gw_citationsfixdialog.Gtk.Grid",
                return_value=grid_mock,
            ),
            unittest.mock.patch(
                "gramps.plugins.tool.gw_citationsfixdialog.Gtk.Entry",
                side_effect=lambda: MagicMock(),
            ),
        ):
            dlg.build_rows([row])

        attached_cols = [call.args[1] for call in grid_mock.attach.call_args_list]
        self.assertEqual(len(grid_mock.attach.call_args_list), 7)
        self.assertEqual(attached_cols, [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(len(dlg.row_targets), 1)

        # Target data entries start empty by default
        target = dlg.row_targets[0]
        target["page_entry"].set_text.assert_called_with("")
        target["conf_entry"].set_text.assert_called_with("")
        target["date_entry"].set_text.assert_called_with("")
        target["notes_entry"].set_text.assert_called_with("")
        self.assertIsNotNone(target["hint_label"])

    def test_accept_hints_populates_target_entries(self) -> None:
        """cb_accept_hints should populate empty target entries with suggested values."""
        dlg = CitationFixDialog.__new__(CitationFixDialog)
        mock_entry_conf = MagicMock()
        mock_entry_conf.get_text.return_value = ""
        mock_entry_page = MagicMock()
        mock_entry_page.get_text.return_value = ""
        mock_entry_date = MagicMock()
        mock_entry_date.get_text.return_value = ""
        mock_entry_notes = MagicMock()
        mock_entry_notes.get_text.return_value = ""
        mock_entry_hint = MagicMock()

        dlg.row_targets = [
            {
                "row": {
                    "hint_text": "Lower to Confidence 1",
                    "suggested_conf": "1",
                    "suggested_page": "p. 100",
                },
                "conf_entry": mock_entry_conf,
                "page_entry": mock_entry_page,
                "date_entry": mock_entry_date,
                "notes_entry": mock_entry_notes,
                "hint_entry": mock_entry_hint,
            }
        ]

        with unittest.mock.patch("gramps.plugins.tool.gw_citationsfixdialog.OkDialog"):
            dlg.cb_accept_hints(MagicMock())

        mock_entry_conf.set_text.assert_called_with("1")
        mock_entry_page.set_text.assert_called_with("p. 100")

    def test_manual_page_date_does_not_count_as_hint(self) -> None:
        """Citations with only missing page/date (no extracted data) should not count as hints on the button."""
        src = FakeSource(handle="s1", title="Parish Register")
        # Citation with no page, no date, no extractable URL/date in text
        cit1 = FakeCitation(
            handle="c1",
            ref_handle="s1",
            gramps_id="C0001",
            page="",
            confidence=2,
        )
        # Citation with URL in page that should be moved to notes
        cit2 = FakeCitation(
            handle="c2",
            ref_handle="s1",
            gramps_id="C0002",
            page="https://example.com/record",
            confidence=2,
        )
        cit2.get_note_list = lambda: []  # type: ignore[assignment]
        db = FakeDb(sources=[src], citations=[cit1, cit2], notes={})

        rows = build_citation_fix_rows(db)
        self.assertEqual(len(rows), 2)

        # cit1 has no actionable hint
        r1 = next(r for r in rows if r["citation_handle"] == "c1")
        self.assertEqual(r1["hint_text"], "")
        self.assertEqual(r1["suggested_page"], "")
        self.assertEqual(r1["suggested_date"], "")

        # cit2 has an actionable hint (URL moved to notes)
        r2 = next(r for r in rows if r["citation_handle"] == "c2")
        self.assertIn("Move URL", r2["hint_text"])
        self.assertEqual(r2["suggested_notes"], "https://example.com/record")

    def test_dialog_buttons_and_footer(self) -> None:
        """Verify buttons in action area next to close, and footer text at bottom without all-caps."""
        src = FakeSource(handle="s1", title="Census 1900")
        cit = FakeCitation(
            handle="c1",
            ref_handle="s1",
            gramps_id="C0001",
            page="p. 1",
            confidence=2,
        )
        db = FakeDb(sources=[src], citations=[cit], notes={})

        class DummyDbState:
            def __init__(self, db_obj: Any) -> None:
                self.db = db_obj

        with (
            unittest.mock.patch.object(
                CitationFixDialog, "add_action_widget"
            ) as mock_action,
            unittest.mock.patch.object(
                CitationFixDialog, "add_button"
            ) as mock_add_button,
            unittest.mock.patch(
                "gramps.plugins.tool.gw_citationsfixdialog.Gtk.Label"
            ) as mock_label_cls,
        ):
            dlg = CitationFixDialog("Fix Citations", DummyDbState(db))
            self.assertTrue(hasattr(dlg, "accept_button"))
            self.assertTrue(hasattr(dlg, "apply_button"))
            self.assertEqual(mock_action.call_count, 2)
            mock_add_button.assert_called_with(
                "_Close",
                sys.modules["gi.repository"].Gtk.ResponseType.CLOSE,
            )

            labels_created = [
                call.kwargs.get("label", "") for call in mock_label_cls.call_args_list
            ]
            footer_found = any(
                "Clean tree page/date and confidence." in text
                and "Press 'Accept hints' to populate suggested changes" in text
                for text in labels_created
            )
            self.assertTrue(footer_found)
            # Ensure no words are in all-caps
            for text in labels_created:
                self.assertNotIn("PAGE/DATE", text)
                self.assertNotIn("PAGE", text)
                self.assertNotIn("DATE", text)


if __name__ == "__main__":
    unittest.main()
