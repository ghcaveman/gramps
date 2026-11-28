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
Tests for reusing a citation the tree already has.

Merging the same record twice (a WikiTree profile merged again, say) loads
it afresh, so its citations and notes arrive with new handles. A citation
the tree already has (the same source, page and notes) is reused, instead
of a copy of it and its notes being added, even when the merge replaces the
event that carries it.
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
from gramps.gen.db.utils import import_as_dict
from gramps.gen.gwizard.gwizardgedcom import GedGWizard
from gramps.gen.user import User

NOTE = "URL: https://example.org/Smith-1\nLast Modified: 2025-12-04 21:31:05"


def ged(note: str = NOTE, page: str = "Record Smith-1") -> str:
    """John Smith, his birth and the person both citing the record."""
    lines = [
        "0 HEAD",
        "1 CHAR UTF-8",
        "0 @I1@ INDI",
        "1 NAME John /Smith/",
        "1 SEX M",
        "1 BIRT",
        "2 DATE 10 MAR 1753",
        "2 SOUR @S1@",
        "3 PAGE %s" % page,
        "3 NOTE @N1@",
        "1 SOUR @S1@",
        "2 PAGE %s" % page,
        "2 NOTE @N1@",
        "0 @S1@ SOUR",
        "1 TITL Example Family Records",
        "0 @N1@ NOTE %s" % note.split("\n")[0],
    ]
    lines += ["1 CONT %s" % line for line in note.split("\n")[1:]]
    lines.append("0 TRLR")
    return "\n".join(lines) + "\n"


class CitationReuseTest(unittest.TestCase):
    """John Smith merged again from the same record."""

    def setUp(self) -> None:
        self._paths: list[str] = []
        self._wizards: list[GedGWizard] = []
        self.db: Any = import_as_dict(self._write(ged()), User())

    def tearDown(self) -> None:
        for gwizard in self._wizards:
            source_db = gwizard.context.get("source_db")
            if source_db is not None:
                source_db.close()
        self.db.close()
        for path in self._paths:
            if os.path.exists(path):
                os.remove(path)

    def _write(self, text: str) -> str:
        with tempfile.NamedTemporaryFile(
            suffix=".ged", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write(text)
        self._paths.append(handle.name)
        return handle.name

    def _merge(self, incoming: str, resolutions: dict[str, str]) -> None:
        gwizard = GedGWizard(self.db)
        self._wizards.append(gwizard)
        gwizard.run_step("connect", gedcom_path=self._write(incoming))
        gwizard.run_step("load")
        source_db = gwizard.context["source_db"]
        (s_person,) = list(source_db.iter_people())
        (t_person,) = list(self.db.iter_people())
        self.assertTrue(
            gwizard.run_step(
                "apply",
                source_person_handle=s_person.handle,
                target_person_handle=t_person.handle,
                resolutions=resolutions,
            )
        )

    def _counts(self) -> tuple[int, int]:
        return self.db.get_number_of_citations(), self.db.get_number_of_notes()

    def _birth_citations(self) -> list[str]:
        (person,) = list(self.db.iter_people())
        birth = self.db.get_event_from_handle(person.get_birth_ref().ref)
        return birth.get_citation_list()

    def test_merging_the_same_birth_again_adds_no_copies(self) -> None:
        """The replaced birth keeps the tree's citation and its note."""
        before = self._birth_citations()
        citations, notes = self._counts()
        self._merge(ged(), {"birth_event": "source", "person_sources": "source"})
        self.assertEqual(self._birth_citations(), before)
        self.assertEqual(self._counts(), (citations, notes))

    def test_a_changed_note_is_a_new_citation(self) -> None:
        """New text in the record's note is new information: it is added."""
        changed = NOTE.replace("2025-12-04 21:31:05", "2026-11-27 20:00:00")
        citations, notes = self._counts()
        self._merge(ged(note=changed), {"birth_event": "source"})
        self.assertEqual(self._counts(), (citations + 1, notes + 1))

    def test_another_page_is_a_new_citation(self) -> None:
        citations, notes = self._counts()
        self._merge(ged(page="Record Smith-2"), {"person_sources": "source"})
        self.assertEqual(self._counts(), (citations + 1, notes))


if __name__ == "__main__":
    unittest.main()
