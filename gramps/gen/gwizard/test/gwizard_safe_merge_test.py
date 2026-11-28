#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026       GWizard contributors
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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Tests that a merge never loses good data in the tree or brings in junk.

A merge chosen field by field must not blank a value the tree has, must
keep the sources and notes of a tree event it replaces, and must not add
a second copy of something the tree already holds (an event, a
repository, an empty note). Each test builds both trees from small inline
GEDCOM text.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import tempfile
import unittest
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import import_as_dict
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.lib import EventType, Note, Person
from gramps.gen.user import User

# The tree: John Smith with a sourced, annotated birth, a residence, a
# nickname and a repository.
TARGET_GED = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME John /Smith/
2 NICK Jack
1 SEX M
1 BIRT
2 DATE 1900
2 SOUR @S1@
3 PAGE p. 12
2 NOTE Baptised the same week.
1 RESI
2 DATE 1920
2 PLAC Reno, NV
0 @S1@ SOUR
1 TITL Parish register of St Mary
1 REPO @R1@
0 @R1@ REPO
1 NAME National Archives
0 TRLR
"""

# The incoming record: the same John Smith with an exact birth date, no
# nickname, an unknown gender, the same residence, and a new source held
# by the same repository.
SOURCE_GED = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME John /Smith/
1 SEX U
1 BIRT
2 DATE 1 JAN 1900
2 PLAC Reno, NV
1 RESI
2 DATE 1920
2 PLAC Reno, NV
1 CENS
2 DATE 1930
2 PLAC Reno, NV
1 SOUR @S9@
2 PAGE Sheet 4
0 @S9@ SOUR
1 TITL Pension file of John Smith
1 REPO @R9@
0 @R9@ REPO
1 NAME National Archives
0 TRLR
"""


class SafeMergeTest(unittest.TestCase):
    """A merge keeps the tree's good data and adds no junk."""

    def setUp(self) -> None:
        self._paths: list[str] = []
        self.db: Any = None
        self.gwizard: GedGWizard
        self.db = import_as_dict(self._write(TARGET_GED), User())
        self.gwizard = GedGWizard(self.db)
        self.assertTrue(
            self.gwizard.run_step("connect", gedcom_path=self._write(SOURCE_GED))
        )
        self.gwizard.run_step("load")
        self.source_db = self.gwizard.context["source_db"]

    def tearDown(self) -> None:
        self.source_db.close()
        self.db.close()
        for path in self._paths:
            if os.path.exists(path):
                os.remove(path)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _write(self, text: str) -> str:
        with tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write(text)
        self._paths.append(handle.name)
        return handle.name

    @staticmethod
    def _john(db: Any) -> Any:
        (person,) = list(db.iter_people())
        return person

    def _apply(self, resolutions: dict[str, str]) -> Any:
        """Merge the incoming John into the tree's John; return him."""
        self.assertTrue(
            self.gwizard.run_step(
                "apply",
                source_person_handle=self._john(self.source_db).handle,
                target_person_handle=self._john(self.db).handle,
                resolutions=resolutions,
            )
        )
        return self._john(self.db)

    def _events(self, db: Any, person: Any, event_type: int) -> list[Any]:
        events = [
            db.get_event_from_handle(ref.ref) for ref in person.get_event_ref_list()
        ]
        return [event for event in events if event.get_type() == event_type]

    def _source_event(self, event_type: int) -> Any:
        (event,) = self._events(self.source_db, self._john(self.source_db), event_type)
        return event

    # ------------------------------------------------------------------
    # replacing a vital event
    # ------------------------------------------------------------------
    def test_replaced_birth_keeps_tree_citations_and_notes(self) -> None:
        """The new birth carries the old birth's citation and note."""
        john = self._apply({"birth_event": "source"})
        birth = self.db.get_event_from_handle(john.get_birth_ref().ref)
        self.assertEqual(birth.get_date_object().get_year(), 1900)
        self.assertEqual(birth.get_date_object().get_day(), 1)
        titles = []
        for handle in birth.get_citation_list():
            citation = self.db.get_citation_from_handle(handle)
            source = self.db.get_source_from_handle(citation.get_reference_handle())
            titles.append((source.get_title(), citation.get_page()))
        self.assertIn(("Parish register of St Mary", "p. 12"), titles)
        notes = [self.db.get_note_from_handle(h).get() for h in birth.get_note_list()]
        self.assertIn("Baptised the same week.", notes)

    def test_replaced_birth_tree_sources_not_duplicated(self) -> None:
        """Merging the birth twice leaves one copy of each tree citation."""
        self._apply({"birth_event": "source"})
        john = self._apply({"birth_event": "source"})
        birth = self.db.get_event_from_handle(john.get_birth_ref().ref)
        self.assertEqual(len(birth.get_citation_list()), 1)
        self.assertEqual(len(birth.get_note_list()), 1)

    # ------------------------------------------------------------------
    # blank incoming values
    # ------------------------------------------------------------------
    def test_unknown_gender_does_not_replace_known(self) -> None:
        """An incoming Unknown gender leaves the tree's gender as it is."""
        john = self._apply({"gender": "source"})
        self.assertEqual(john.get_gender(), Person.MALE)

    def test_known_gender_replaces_unknown(self) -> None:
        """A known incoming gender still replaces an Unknown one."""
        with DbTxn("unknown", self.db) as trans:
            john = self._john(self.db)
            john.set_gender(Person.UNKNOWN)
            self.db.commit_person(john, trans)
        with DbTxn("female", self.source_db) as trans:
            incoming = self._john(self.source_db)
            incoming.set_gender(Person.FEMALE)
            self.source_db.commit_person(incoming, trans)
        john = self._apply({"gender": "source"})
        self.assertEqual(john.get_gender(), Person.FEMALE)

    def test_empty_nickname_does_not_blank_tree(self) -> None:
        """An incoming empty nickname or call name keeps the tree's."""
        john = self._apply({"nickname": "source", "call_name": "source"})
        self.assertEqual(john.get_primary_name().get_nick_name(), "Jack")

    # ------------------------------------------------------------------
    # no second copies
    # ------------------------------------------------------------------
    def test_same_event_not_added_twice(self) -> None:
        """An incoming event the person already has is not added again."""
        resi = self._source_event(EventType.RESIDENCE)
        cens = self._source_event(EventType.CENSUS)
        john = self._apply(
            {"event:" + resi.handle: "source", "event:" + cens.handle: "source"}
        )
        self.assertEqual(len(self._events(self.db, john, EventType.RESIDENCE)), 1)
        self.assertEqual(len(self._events(self.db, john, EventType.CENSUS)), 1)

    def test_repository_with_same_name_is_reused(self) -> None:
        """A new source's repository joins the tree's one of the same name."""
        john = self._apply({"person_sources": "source"})
        names = [repo.get_name() for repo in self.db.iter_repositories()]
        self.assertEqual(names, ["National Archives"])
        titles = {}
        for handle in john.get_citation_list():
            citation = self.db.get_citation_from_handle(handle)
            source = self.db.get_source_from_handle(citation.get_reference_handle())
            titles[source.get_title()] = source
        pension = titles["Pension file of John Smith"]
        (repo_ref,) = pension.get_reporef_list()
        (repo,) = list(self.db.iter_repositories())
        self.assertEqual(repo_ref.ref, repo.handle)

    def test_empty_note_not_copied(self) -> None:
        """An empty note on an incoming event is left out."""
        cens = self._source_event(EventType.CENSUS)
        with DbTxn("notes", self.source_db) as trans:
            empty = Note()
            empty.set("   ")
            self.source_db.add_note(empty, trans)
            kept = Note()
            kept.set("Enumerated with his brother.")
            self.source_db.add_note(kept, trans)
            cens.add_note(empty.handle)
            cens.add_note(kept.handle)
            self.source_db.commit_event(cens, trans)
        notes_before = self.db.get_number_of_notes()
        john = self._apply({"event:" + cens.handle: "source"})
        (event,) = self._events(self.db, john, EventType.CENSUS)
        texts = [self.db.get_note_from_handle(h).get() for h in event.get_note_list()]
        self.assertEqual(texts, ["Enumerated with his brother."])
        self.assertEqual(self.db.get_number_of_notes(), notes_before + 1)


if __name__ == "__main__":
    unittest.main()
