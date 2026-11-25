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

"""Tests for SourceFixDialog, hint generation, and source fix planning."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import sys
import tempfile
import unittest
from unittest.mock import patch

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
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.errors import HandleError
from gramps.gen.lib import Source, Citation, Repository, RepoRef
from gramps.plugins.tool.gw_sourcesfixdialog import (
    SourceFixDialog,
    auto_fix_sources,
    build_source_fix_rows,
    plan_source_fixes,
    apply_source_fixes,
)
from gramps.plugins.tool.gwizardcitationshared import (
    YEAR_TOLERANCE,
    extract_years,
    same_collection_titles,
    suggest_source_merge_target,
    years_compatible,
)

_ = glocale.translation.sgettext


# ------------------------------------------------------------
#
# SourceFixDialogTest
#
# ------------------------------------------------------------
class SourceFixDialogTest(unittest.TestCase):
    """Test suite for source fix dialog row building and hints."""

    def setUp(self) -> None:
        """Create in-memory database."""
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        """Close database."""
        self.db.close()

    def test_build_source_fix_rows_near_duplicates(self) -> None:
        """Verify near duplicates produce one row per member with default=self and keeper hinted."""
        stats = {
            "near_duplicates": [
                [
                    {
                        "handle": "s1",
                        "title": "1900 US Census",
                        "gramps_id": "S0001",
                        "citations": 10,
                        "repo_count": 1,
                    },
                    {
                        "handle": "s2",
                        "title": "1900 US Census",
                        "gramps_id": "S0002",
                        "citations": 1,
                        "repo_count": 0,
                    },
                ]
            ],
            "source_rows": [],
        }

        rows = build_source_fix_rows(stats)
        self.assertEqual(len(rows), 2)

        # Keeper row (s1)
        r1 = rows[0]
        self.assertEqual(r1["handle"], "s1")
        self.assertTrue(r1["is_keeper"])
        self.assertEqual(r1["options"][0][1], "s1")  # Default choice is s1
        self.assertEqual(r1["hint_target"], "")  # No hint
        self.assertEqual(r1["hint_display"], "")  # Blank hint!

        # Duplicate row (s2)
        r2 = rows[1]
        self.assertEqual(r2["handle"], "s2")
        self.assertFalse(r2["is_keeper"])
        self.assertEqual(r2["options"][0][1], "s2")  # Default choice is s2
        self.assertEqual(r2["hint_target"], "s1")  # Hinted to keeper s1
        self.assertIn("S0001", r2["hint_display"])
        self.assertIn("Keeper", r2["hint_reason"])

    def test_build_source_fix_rows_quarantine(self) -> None:
        """Verify orphan / unrepositoryed sources get a quarantine hint."""
        stats = {
            "near_duplicates": [],
            "source_rows": [
                {
                    "handle": "s3",
                    "title": "Unlinked Record",
                    "gramps_id": "S0003",
                    "citations": 0,
                    "repo_count": 0,
                }
            ],
        }

        rows = build_source_fix_rows(stats)
        self.assertEqual(len(rows), 1)

        r3 = rows[0]
        self.assertEqual(r3["handle"], "s3")
        self.assertEqual(
            r3["options"][0][1], "s3"
        )  # Default choice is s3 (database value)
        self.assertEqual(r3["options"][1][1], "quarantine")
        self.assertEqual(r3["hint_target"], "quarantine")
        self.assertIn("Quarantine", r3["hint_display"])

    def test_plan_source_fixes_default_vs_accepted(self) -> None:
        """Verify plan has no merges when choices unchanged, but plans fixes when hints accepted."""
        stats = {
            "near_duplicates": [
                [
                    {
                        "handle": "s1",
                        "title": "Census",
                        "gramps_id": "S0001",
                        "citations": 5,
                        "repo_count": 1,
                    },
                    {
                        "handle": "s2",
                        "title": "Census",
                        "gramps_id": "S0002",
                        "citations": 0,
                        "repo_count": 0,
                    },
                ]
            ],
            "source_rows": [],
        }
        rows = build_source_fix_rows(stats)

        # Default choices: every row's chosen target is its own handle
        for r in rows:
            r["chosen_target"] = r["handle"]
        plan_default = plan_source_fixes(rows)
        self.assertEqual(len(plan_default["merge"]), 0)
        self.assertEqual(len(plan_default["quarantine"]), 0)

        # Accepted hints: row with hint gets hint_target
        for r in rows:
            r["chosen_target"] = r["hint_target"] or r["handle"]
        plan_accepted = plan_source_fixes(rows)
        self.assertEqual(len(plan_accepted["merge"]), 1)
        self.assertEqual(plan_accepted["merge"][0]["keeper_handle"], "s1")
        self.assertEqual(plan_accepted["merge"][0]["discard_handles"], ["s2"])

    def test_apply_source_fixes(self) -> None:
        """Verify apply_source_fixes merges sources and moves citations."""
        with DbTxn("Create test sources", self.db) as trans:
            repo = Repository()
            repo.set_name("National Archives")
            r_h = self.db.add_repository(repo, trans)

            s1 = Source()
            s1.set_title("Census 1900")
            rref = RepoRef()
            rref.set_reference_handle(r_h)
            s1.add_repo_reference(rref)
            s1_h = self.db.add_source(s1, trans)

            s2 = Source()
            s2.set_title("Census 1900")
            s2_h = self.db.add_source(s2, trans)

            s3 = Source()
            s3.set_title("Orphan Document")
            s3_h = self.db.add_source(s3, trans)

            cit = Citation()
            cit.set_reference_handle(s2_h)
            c_h = self.db.add_citation(cit, trans)

        class DummyDbState:
            def __init__(self, db: DbWriteBase) -> None:
                self.db = db

        plan = {
            "merge": [{"keeper_handle": s1_h, "discard_handles": [s2_h]}],
            "quarantine": [{"source_handle": s3_h, "target_repo_name": "Quarantine"}],
        }

        merged, quarantined, trimmed = apply_source_fixes(DummyDbState(self.db), plan)
        self.assertEqual(merged, 1)
        self.assertEqual(quarantined, 1)
        self.assertEqual(trimmed, 0)

        # Verify s2 was merged into s1 (citation moved to s1, s2 deleted)
        with self.assertRaises(HandleError):
            self.db.get_source_from_handle(s2_h)
        updated_cit = self.db.get_citation_from_handle(c_h)
        self.assertEqual(updated_cit.get_reference_handle(), s1_h)

        # Verify s3 was assigned to Quarantine repository
        updated_s3 = self.db.get_source_from_handle(s3_h)
        self.assertTrue(len(updated_s3.get_reporef_list()) >= 1)
        q_repo = self.db.get_repository_from_handle(
            updated_s3.get_reporef_list()[0].get_reference_handle()
        )
        self.assertEqual(q_repo.get_name(), "Quarantine")

    def test_build_source_fix_rows_whitespace(self) -> None:
        """Verify sources with leading/trailing whitespace produce a trim row."""
        stats = {
            "near_duplicates": [],
            "source_rows": [
                {
                    "handle": "s_ws",
                    "title": "  Military Service Records  ",
                    "gramps_id": "S0099",
                    "citations": 3,
                    "repo_count": 1,
                }
            ],
        }

        rows = build_source_fix_rows(stats)
        self.assertEqual(len(rows), 1)

        r = rows[0]
        self.assertEqual(r["handle"], "s_ws")
        self.assertEqual(r["problem"], "trim")
        self.assertEqual(r["options"][0][1], "s_ws")  # Default choice is self
        self.assertEqual(r["options"][1][1], "trim")  # Option to trim
        self.assertEqual(r["hint_target"], "trim")
        self.assertIn("Trim whitespace", r["hint_display"])

    def test_apply_source_fixes_trim(self) -> None:
        """Verify apply_source_fixes trims leading/trailing whitespace."""
        with DbTxn("Create whitespace source", self.db) as trans:
            s = Source()
            s.set_title("  World War I Draft Registration  ")
            s.set_author("  Selective Service System  ")
            s_h = self.db.add_source(s, trans)

        class DummyDbState:
            def __init__(self, db: DbWriteBase) -> None:
                self.db = db

        plan = {
            "merge": [],
            "quarantine": [],
            "trim": [{"source_handle": s_h}],
        }

        merged, quarantined, trimmed = apply_source_fixes(DummyDbState(self.db), plan)
        self.assertEqual(trimmed, 1)

        updated_s = self.db.get_source_from_handle(s_h)
        self.assertEqual(updated_s.get_title(), "World War I Draft Registration")
        self.assertEqual(updated_s.get_author(), "Selective Service System")

    def test_build_source_fix_rows_fuzzy_heuristic_match(self) -> None:
        """Verify fuzzy and heuristic similarity matches produce keeper/duplicate rows with reasons."""
        with DbTxn("Create fuzzy matching sources", self.db) as trans:
            repo = Repository()
            repo.set_name("Ancestry.com")
            r_h = self.db.add_repository(repo, trans)

            s1 = Source()
            s1.set_title("California Death Index, 1940-1997")
            rref1 = RepoRef()
            rref1.set_reference_handle(r_h)
            s1.add_repo_reference(rref1)
            s1_h = self.db.add_source(s1, trans)

            s2 = Source()
            s2.set_title("California Death Records 1940-1997")
            rref2 = RepoRef()
            rref2.set_reference_handle(r_h)
            s2.add_repo_reference(rref2)
            s2_h = self.db.add_source(s2, trans)

        # stats without near_duplicates (since titles are not exact normalized matches)
        stats = {
            "near_duplicates": [],
            "source_rows": [
                {
                    "handle": s1_h,
                    "title": "California Death Index, 1940-1997",
                    "gramps_id": "S0001",
                    "citations": 5,
                    "repo_count": 1,
                },
                {
                    "handle": s2_h,
                    "title": "California Death Records 1940-1997",
                    "gramps_id": "S0002",
                    "citations": 1,
                    "repo_count": 1,
                },
            ],
        }

        rows = build_source_fix_rows(stats, self.db)
        self.assertEqual(len(rows), 2)

        # S1 is the keeper (5 citations vs 1)
        r_keeper = next(r for r in rows if r["handle"] == s1_h)
        self.assertTrue(r_keeper["is_keeper"])
        self.assertEqual(r_keeper["hint_target"], "")
        self.assertEqual(r_keeper["hint_display"], "")  # Blank hint!

        # S2 is the duplicate suggested to merge into S1
        r_dup = next(r for r in rows if r["handle"] == s2_h)
        self.assertFalse(r_dup["is_keeper"])
        self.assertEqual(r_dup["hint_target"], s1_h)
        self.assertIn("Ancestry.com", r_dup["hint_reason"])
        self.assertEqual(
            r_dup["options"][0][1], s2_h
        )  # Default choice is self (DB value)

    def test_apply_source_fixes_transitive_and_deleted_safety(self) -> None:
        """Verify apply_source_fixes resolves transitive chains and handles missing/deleted handles without crashing."""
        with DbTxn("Create sources for chain", self.db) as trans:
            s1 = Source()
            s1.set_title("Target Master Source")
            s1_h = self.db.add_source(s1, trans)

            s2 = Source()
            s2.set_title("Intermediate Source")
            s2_h = self.db.add_source(s2, trans)

            s3 = Source()
            s3.set_title("Leaf Source")
            s3_h = self.db.add_source(s3, trans)

        # Plan with transitive chain s3 -> s2, s2 -> s1, plus an already-nonexistent handle
        rows = [
            {"handle": s1_h, "chosen_target": s1_h},
            {"handle": s2_h, "chosen_target": s1_h},
            {"handle": s3_h, "chosen_target": s2_h},
            {"handle": "nonexistent_h", "chosen_target": s1_h},
        ]
        plan = plan_source_fixes(rows)

        class DummyDbState:
            def __init__(self, db: DbWriteBase) -> None:
                self.db = db

        # Should merge s2 and s3 into s1, skip nonexistent_h gracefully without HandleError
        merged, quarantined, trimmed = apply_source_fixes(DummyDbState(self.db), plan)
        self.assertEqual(merged, 2)
        self.assertEqual(quarantined, 0)
        self.assertEqual(trimmed, 0)

        # s1 should still exist, s2 and s3 should be gone
        self.assertIsNotNone(self.db.get_source_from_handle(s1_h))
        with self.assertRaises(HandleError):
            self.db.get_source_from_handle(s2_h)
        with self.assertRaises(HandleError):
            self.db.get_source_from_handle(s3_h)

    def test_dialog_buttons_and_footer(self) -> None:
        """Verify buttons in action area next to close, and footer text at bottom."""
        with DbTxn("Create sources for dialog test", self.db) as trans:
            s1 = Source()
            s1.set_title("1900 US Census")
            self.db.add_source(s1, trans)

            s2 = Source()
            s2.set_title("1900 US Census")
            self.db.add_source(s2, trans)

        class DummyDbState:
            def __init__(self, db: DbWriteBase) -> None:
                self.db = db

        with (
            patch.object(SourceFixDialog, "add_action_widget") as mock_action,
            patch.object(SourceFixDialog, "add_button") as mock_add_button,
            patch(
                "gramps.plugins.tool.gw_sourcesfixdialog.SelectableLabel"
            ) as mock_label_cls,
        ):
            dlg = SourceFixDialog("Fix Sources", DummyDbState(self.db))
            self.assertTrue(hasattr(dlg, "accept_button"))
            self.assertTrue(hasattr(dlg, "apply_button"))
            self.assertEqual(mock_action.call_count, 2)
            mock_add_button.assert_called_with(
                str(_("_Close")),
                sys.modules["gi.repository"].Gtk.ResponseType.CLOSE,
            )

            labels_created = [
                call.kwargs.get("label", "") for call in mock_label_cls.call_args_list
            ]
            footer_found = any(
                "Merge near-duplicates and quarantine non-sources." in text
                for text in labels_created
            )
            self.assertTrue(footer_found)


class SourceYearRuleTest(unittest.TestCase):
    """Years in titles keep different collections apart."""

    def setUp(self) -> None:
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")

    def tearDown(self) -> None:
        self.db.close()

    def test_extract_years(self) -> None:
        """Four-digit numbers starting 1 or 20 are years; others are not."""
        self.assertEqual(
            extract_years("Scotland, Births and Baptisms, 1564-1950"), [1564, 1950]
        )
        self.assertEqual(extract_years("1900 Census, roll 3412, 20155"), [1900])
        self.assertEqual(extract_years("Volume 3, page 112"), [])

    def test_years_compatible(self) -> None:
        """Years within YEAR_TOLERANCE agree; text without years agrees."""
        cases = [
            ("1900 Federal Census", "1930 Federal Census", False),
            ("1900 Federal Census", "1910 Federal Census", False),
            ("1900 Federal Census", "1904 Federal Census", True),
            ("1900 Federal Census", "1905 Federal Census", False),
            ("Marriages, 1852-1968", "Marriages, 1852-1970", True),
            ("Marriages, 1852-1968", "Marriages, 1852", False),
            ("Ohio Death Certificates", "Ohio Death Certificates, 1908-1953", True),
        ]
        self.assertEqual(YEAR_TOLERANCE, 4)
        for title_a, title_b, expected in cases:
            with self.subTest(a=title_a, b=title_b):
                self.assertEqual(years_compatible(title_a, title_b), expected)
                self.assertEqual(years_compatible(title_b, title_a), expected)

    def test_same_collection_titles_uses_the_year_rule(self) -> None:
        """Different census years are different collections."""
        self.assertFalse(
            same_collection_titles(
                "1900 United States Federal Census", "1930 United States Federal Census"
            )
        )
        self.assertTrue(
            same_collection_titles(
                "Pennsylvania, Marriages, 1852-1968",
                "Pennsylvania, U.S., Marriages, 1852-1968",
            )
        )

    def _sources(self, repo_name: str, *titles: str) -> list[str]:
        handles = []
        with DbTxn("Setup", self.db) as trans:
            repo = Repository()
            repo.set_name(repo_name)
            repo_handle = self.db.add_repository(repo, trans)
            for title in titles:
                source = Source()
                source.set_title(title)
                ref = RepoRef()
                ref.set_reference_handle(repo_handle)
                source.add_repo_reference(ref)
                handles.append(self.db.add_source(source, trans))
        return handles

    def test_shared_repository_does_not_merge_different_years(self) -> None:
        """The 1900 and 1930 census at Ancestry.com are not duplicates."""
        census_1900, census_1930, census_us = self._sources(
            "Ancestry.com",
            "1900 United States Federal Census",
            "1930 United States Federal Census",
            "1900 U.S. Federal Census",
        )
        match = suggest_source_merge_target(
            census_1900, [census_1930, census_us], self.db
        )
        assert match is not None
        self.assertEqual(match[0], census_us)
        self.assertIsNone(
            suggest_source_merge_target(census_1930, [census_1900], self.db)
        )

    def test_accept_all_hints_keeps_census_years_apart(self) -> None:
        """Fix Sources' no-review path leaves both census sources in place."""
        self._sources(
            "Ancestry.com",
            "1900 United States Federal Census",
            "1930 United States Federal Census",
        )
        auto_fix_sources(self.db)
        self.assertEqual(
            sorted(s.get_title() for s in self.db.iter_sources()),
            ["1900 United States Federal Census", "1930 United States Federal Census"],
        )


class SourceFixTransactionTest(unittest.TestCase):
    """Source fixes are one transaction: one undo restores everything."""

    def test_trim_is_one_undo_step(self) -> None:
        """Trimming runs once, inside the caller's transaction."""
        db: DbWriteBase = make_database("sqlite")
        db.load(tempfile.mkdtemp(), None)
        try:
            with DbTxn("Setup", db) as trans:
                src = Source()
                src.set_title("  Padded title  ")
                src.set_author(" Someone ")
                handle = db.add_source(src, trans)
            plan = {"trim": [{"source_handle": handle}], "merge": [], "quarantine": []}
            self.assertEqual(apply_source_fixes(db, plan), (0, 0, 1))
            fixed = db.get_source_from_handle(handle)
            self.assertEqual(fixed.get_title(), "Padded title")
            self.assertEqual(fixed.get_author(), "Someone")
            self.assertTrue(db.undo())
            self.assertEqual(
                db.get_source_from_handle(handle).get_title(), "  Padded title  "
            )
        finally:
            db.close()


# Test discovery imports every test module before running any, so take the
# fakes off Gtk again now that the GWizard modules are imported; other Gramps
# tests need the real widgets.  setUpModule puts them back for this module.
gwizard_gtk_fakes.uninstall()


if __name__ == "__main__":
    unittest.main()
