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

"""End-to-end tests for the GWizard citation fix: every step on one tree.

These replace the old ``gw_smoke_import.py`` and ``gw_run_e2e.py`` scripts,
so they run with the rest of the suite and fail the build when they break.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import importlib
import json
import shutil
import tempfile
import unittest
from typing import Any

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
from gramps.gen.db.utils import make_database
from gramps.gen.lib import (
    Address,
    Citation,
    Note,
    NoteType,
    RepoRef,
    Repository,
    Source,
)
from gramps.plugins.tool import gwizardcitationfix as fix
from gramps.plugins.tool.gw_repoconsolidatedialog import apply_repo_consolidations

CITATION_FIX_MODULES = (
    "gw_citationattributesdialog",
    "gw_citationsfixdialog",
    "gw_goldstandardrepos",
    "gw_linkcitationmediadialog",
    "gw_notesfixdialog",
    "gw_repoconsolidatedialog",
    "gw_repomergedialog",
    "gw_sourcesfixdialog",
    "gw_unpackcitationsdialog",
    "gw_unpacksourcesdialog",
    "gwizardcitationfix",
    "gwizardcitationmediaengine",
    "gwizardcitationrepairengine",
    "gwizardcitationreport",
    "gwizardcitationshared",
)


class ImportTest(unittest.TestCase):
    """Every Citation Fix module imports (catches NameErrors at import time)."""

    def test_every_module_imports(self) -> None:
        """Import each module in turn."""
        for name in CITATION_FIX_MODULES:
            with self.subTest(module=name):
                importlib.import_module("gramps.plugins.tool." + name)


class CitationFixEndToEndTest(unittest.TestCase):
    """Run every automatic step on a small tree with typical problems."""

    def setUp(self) -> None:
        self.tree_dir = tempfile.mkdtemp()
        self.db = make_database("sqlite")
        self.db.load(self.tree_dir)
        self._build_tree()

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tree_dir, ignore_errors=True)

    # -- test data --------------------------------------------------------
    def _build_tree(self) -> None:
        """Add repositories, sources, citations and notes with known problems."""
        db = self.db
        with DbTxn("Setup", db) as trans:
            registries = self._repository(
                "Local Government and Municipal Registries "
                "(Genoa, IT / Broward County, FL)",
                trans,
            )
            nara = self._repository(
                "The National Archives and Records Administration (NARA)", trans
            )

            def source(title: str, repo: str = "", author: str = "", pub: str = ""):
                src = Source()
                src.set_title(title)
                src.set_author(author)
                src.set_publication_info(pub)
                if repo:
                    ref = RepoRef()
                    ref.set_reference_handle(repo)
                    src.add_repo_reference(ref)
                return db.add_source(src, trans)

            def citation(src: str, page: str = "", conf: int = 2, notes=()) -> str:
                cit = Citation()
                cit.set_reference_handle(src)
                cit.set_page(page)
                cit.set_confidence_level(conf)
                for text in notes:
                    note = Note()
                    note.set(text)
                    note.set_type(NoteType.CITATION)
                    cit.add_note(db.add_note(note, trans))
                return db.add_citation(cit, trans)

            # Duplicate sources with different text in their fields.
            pa1 = source(
                "Pennsylvania, U.S., Marriages, 1852-1968",
                nara,
                author="Ancestry.com",
                pub="Provo, UT",
            )
            pa2 = source(
                "Pennsylvania, Marriages, 1852-1968",
                nara,
                author="FamilySearch",
                pub="Salt Lake City",
            )
            citation(pa1, "Vol 1")
            citation(pa2, "Vol 2")
            # A title that mixes repository, source and labels.
            source(
                "Newspapers.com Obituary Index, 1800s-current "
                "(Repository: Newspapers.com, Source: Obituary Index)"
            )
            # An online tree source with conflated citation pages.
            tree = source("FamilySearch Family Tree", registries)
            for number in range(3):
                citation(
                    tree,
                    "(accessed 12 Jul 2026), entry for Person%d, person ID ABC-%d."
                    % (number, number),
                    conf=3,
                )
            grave = source("U.S., Find A Grave Index", nara)
            citation(
                grave,
                "",
                notes=["https://www.familysearch.org/ark:/61903/1:1:XYZ?view=index"],
            )
            citation(
                grave,
                "Entry for Edward https://www.familysearch.org/ark:/61903/1:1:QQQ "
                "accessed 3 Jan 2020",
                notes=["https://www.familysearch.org/ark:/61903/1:1:QQQ"],
            )
            citation(source("LoisWhite - PittalugaFAMILY TREE.jpg", nara), "")
            for text in (
                "Records not imported into REPO (repository) Gramps ID "
                "R00001:ADDR element ignored 'x'",
                "   ",
                "  padded  ",
            ):
                note = Note()
                note.set(text)
                db.add_note(note, trans)

    def _repository(self, name: str, trans: Any) -> str:
        repo = Repository()
        repo.set_name(name)
        address = Address()
        address.set_street(name)
        repo.add_address(address)
        return self.db.add_repository(repo, trans)

    def _snapshot(self) -> dict[str, list[str]]:
        """Return every source, citation, repository and note, serialized."""
        out = {}
        for name, iterate in (
            ("source", self.db.iter_sources),
            ("citation", self.db.iter_citations),
            ("repository", self.db.iter_repositories),
            ("note", self.db.iter_notes),
        ):
            out[name] = sorted(
                json.dumps(obj.serialize(), sort_keys=True, default=str)
                for obj in iterate()
            )
        return out

    def _run_all_steps(self) -> list[str]:
        return [fix.run_auto_layer(layer, self.db) for layer in fix.AUTO_STEP_LAYERS]

    # -- tests -----------------------------------------------------------
    def test_each_step_is_one_undo(self) -> None:
        """A step that changes the tree is reverted completely by one undo."""
        for layer in fix.AUTO_STEP_LAYERS:
            with self.subTest(step=layer):
                before = self._snapshot()
                fix.run_auto_layer(layer, self.db)
                if self._snapshot() == before:
                    continue  # nothing to do, so nothing to undo
                self.assertTrue(self.db.undo())
                self.assertEqual(self._snapshot(), before)
                self.assertTrue(self.db.redo())

    def test_results(self) -> None:
        """The steps fix the problems in the test tree."""
        self._run_all_steps()
        titles = sorted(src.get_title() for src in self.db.iter_sources())
        self.assertIn("Obituary Index, 1800s-current", titles)
        # The two Pennsylvania marriage sources were merged into one.
        self.assertEqual(sum(1 for t in titles if t.startswith("Pennsylvania")), 1)
        notes = [str(note.get()) for note in self.db.iter_notes()]
        self.assertNotIn("   ", notes)
        self.assertNotIn("  padded  ", notes)
        self.assertIn("padded", notes)
        self.assertFalse(any("ADDR element ignored" in note for note in notes))

    def test_second_run_changes_nothing(self) -> None:
        """Running every step again finds nothing more to do."""
        self._run_all_steps()
        snapshot = self._snapshot()
        self._run_all_steps()
        self.assertEqual(self._snapshot(), snapshot)

    def test_repository_merge_chain_and_cycle(self) -> None:
        """A -> B -> C ends in C; X <-> Y merges nothing and loses nothing."""
        with DbTxn("Setup", self.db) as trans:
            chain = [self._repository(name, trans) for name in ("A1", "B2", "C3")]
            cycle = [self._repository(name, trans) for name in ("X4", "Y5")]
        result = apply_repo_consolidations(
            self.db, [(chain[0], chain[1]), (chain[1], chain[2])]
        )
        self.assertEqual(result["merged"], 2)
        self.assertEqual(
            [self.db.has_repository_handle(h) for h in chain], [False, False, True]
        )
        result = apply_repo_consolidations(
            self.db, [(cycle[0], cycle[1]), (cycle[1], cycle[0])]
        )
        self.assertEqual((result["merged"], result["errors"]), (0, []))
        self.assertTrue(all(self.db.has_repository_handle(h) for h in cycle))


if __name__ == "__main__":
    unittest.main()
