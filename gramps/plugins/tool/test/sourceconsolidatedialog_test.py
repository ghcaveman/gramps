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

"""Tests for SourceConsolidateDialog and its Hint column."""

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
from gramps.plugins.tool.sourceconsolidatedialog import SourceConsolidateDialog


# ------------------------------------------------------------
#
# Mock database objects
#
# ------------------------------------------------------------
class FakeRepoRef:
    """Mock repository reference."""

    def __init__(self, repo_handle: str) -> None:
        self.ref = repo_handle


class FakeSource:
    """Mock Source object for consolidate tests."""

    def __init__(
        self,
        handle: str,
        title: str,
        gramps_id: str = "S0001",
        author: str = "",
        repo_handles: list[str] | None = None,
    ) -> None:
        self.handle = handle
        self.title = title
        self.gramps_id = gramps_id
        self.author = author
        self.repo_refs = [FakeRepoRef(rh) for rh in (repo_handles or [])]

    def get_handle(self) -> str:
        return self.handle

    def get_title(self) -> str:
        return self.title

    def get_gramps_id(self) -> str:
        return self.gramps_id

    def get_author(self) -> str:
        return self.author

    def get_reporef_list(self) -> list[FakeRepoRef]:
        return self.repo_refs


class FakeCitation:
    """Mock Citation object."""

    def __init__(self, handle: str, source_handle: str) -> None:
        self.handle = handle
        self.source_handle = source_handle

    def get_reference_handle(self) -> str:
        return self.source_handle


class FakeRepository:
    """Mock Repository object."""

    def __init__(self, handle: str, name: str) -> None:
        self.handle = handle
        self.name = name

    def get_name(self) -> str:
        return self.name


class FakeDb:
    """Mock database providing sources, citations, and repositories."""

    def __init__(
        self,
        sources: list[FakeSource],
        citations: list[FakeCitation] | None = None,
        repositories: list[FakeRepository] | None = None,
    ) -> None:
        self.sources = {s.get_handle(): s for s in sources}
        self.citations = citations or []
        self.repositories = {r.handle: r for r in (repositories or [])}

    def get_source_handles(self) -> list[str]:
        return list(self.sources.keys())

    def get_source_from_handle(self, handle: str) -> FakeSource | None:
        return self.sources.get(handle)

    def get_citation_handles(self) -> list[str]:
        return [c.handle for c in self.citations]

    def get_citation_from_handle(self, handle: str) -> FakeCitation | None:
        for c in self.citations:
            if c.handle == handle:
                return c
        return None

    def get_repository_from_handle(self, handle: str) -> FakeRepository | None:
        return self.repositories.get(handle)


class FakeDbState:
    """Mock dbstate holding the fake database."""

    def __init__(self, db: FakeDb) -> None:
        self.db = db


# ------------------------------------------------------------
#
# SourceConsolidateDialog tests
#
# ------------------------------------------------------------
class SourceConsolidateDialogTest(unittest.TestCase):
    """Test hint computation and Hint column in SourceConsolidateDialog."""

    def test_hint_exact_title_match(self) -> None:
        """Exact duplicate title should be suggested as hint keeper."""
        s1 = FakeSource("s1", "1900 United States Census", "S0001")
        s2 = FakeSource("s2", "1900 United States Census", "S0002")
        # s2 has 5 citations, s1 has 1
        cits = [
            FakeCitation("c1", "s1"),
            FakeCitation("c2", "s2"),
            FakeCitation("c3", "s2"),
            FakeCitation("c4", "s2"),
            FakeCitation("c5", "s2"),
            FakeCitation("c6", "s2"),
        ]
        db = FakeDb([s1, s2], cits)
        dlg = SourceConsolidateDialog(FakeDbState(db))
        dlg.target_handles = ["s2"]

        hint = dlg.compute_hint("s1")
        self.assertIsNotNone(hint)
        target_handle, reason = hint  # type: ignore[misc]
        self.assertEqual(target_handle, "s2")
        self.assertIn("Exact title match", reason)
        self.assertIn("5 citations vs 1", reason)

    def test_hint_normalized_title_match(self) -> None:
        """Normalized title match (e.g. punctuation, U.S. vs US) should be suggested."""
        s1 = FakeSource("s1", "U.S., Find A Grave Index", "S0001")
        s2 = FakeSource("s2", "Find A Grave Index", "S0002")
        cits = [FakeCitation("c1", "s2"), FakeCitation("c2", "s2")]
        db = FakeDb([s1, s2], cits)
        dlg = SourceConsolidateDialog(FakeDbState(db))
        dlg.target_handles = ["s2"]

        hint = dlg.compute_hint("s1")
        self.assertIsNotNone(hint)
        target_handle, reason = hint  # type: ignore[misc]
        self.assertEqual(target_handle, "s2")
        self.assertIn("Matching normalized title", reason)

    def test_hint_shared_repository_and_similar_title(self) -> None:
        """Sources sharing a repository with similar title should be suggested."""
        repo = FakeRepository("r1", "Ancestry.com")
        s1 = FakeSource(
            "s1", "California Death Index, 1940-1997", "S0001", repo_handles=["r1"]
        )
        s2 = FakeSource(
            "s2", "California Death Records 1940-1997", "S0002", repo_handles=["r1"]
        )
        db = FakeDb([s1, s2], [], [repo])
        dlg = SourceConsolidateDialog(FakeDbState(db))
        dlg.target_handles = ["s2"]

        hint = dlg.compute_hint("s1")
        self.assertIsNotNone(hint)
        target_handle, reason = hint  # type: ignore[misc]
        self.assertEqual(target_handle, "s2")
        self.assertIn("Ancestry.com", reason)

    def test_hint_no_match(self) -> None:
        """Unrelated sources should return None for hint."""
        s1 = FakeSource("s1", "Family Bible", "S0001")
        s2 = FakeSource("s2", "1900 US Federal Census", "S0002")
        db = FakeDb([s1, s2])
        dlg = SourceConsolidateDialog(FakeDbState(db))
        dlg.target_handles = ["s2"]

        hint = dlg.compute_hint("s1")
        self.assertIsNone(hint)

    def test_accept_hint_callback(self) -> None:
        """cb_accept_hint should set combo active index to the hinted target."""
        s1 = FakeSource("s1", "Census 1900", "S0001")
        s2 = FakeSource("s2", "Census 1900", "S0002")
        s3 = FakeSource("s3", "Birth Index", "S0003")
        db = FakeDb([s1, s2, s3])
        dlg = SourceConsolidateDialog(FakeDbState(db))
        dlg.target_handles = ["s3", "s2"]
        dlg.hint_target_handle = "s2"

        dlg.cb_accept_hint(MagicMock())
        dlg.combo.set_active.assert_called_with(1)
