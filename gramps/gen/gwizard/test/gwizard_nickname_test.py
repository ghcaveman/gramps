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
Tests for comparing and merging the nickname and call name of a person.

The incoming Kid Doe has the nickname "Kiddo" and the call name "Kid"; the
tree's Kid Doe has neither unless a test gives one.
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
from gramps.gen.user import User

HEADER = "0 HEAD\n1 CHAR UTF-8\n"

SOURCE_GED = HEADER + """0 @I1@ INDI
1 NAME Kid /Doe/
2 NICK Kiddo
2 _RUFNAME Kid
1 SEX M
0 TRLR
"""

TARGET_GED = HEADER + """0 @I1@ INDI
1 NAME Kid /Doe/
1 SEX M
0 TRLR
"""

FIELDS = ("nickname", "call_name")


class GWizardNicknameTest(unittest.TestCase):
    """Nickname and call name are compared and merged."""

    def setUp(self) -> None:
        self._paths: list[str] = []
        self.db: Any = None
        self.gwizard: GedGWizard | None = None

    def tearDown(self) -> None:
        if self.gwizard is not None:
            source_db = self.gwizard.context.get("source_db")
            if source_db is not None:
                source_db.close()
        if self.db is not None:
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

    def _open(self, target_ged: str = TARGET_GED, source_ged: str = SOURCE_GED) -> None:
        self.db = import_as_dict(self._write(target_ged), User())
        self.gwizard = GedGWizard(self.db)
        self.assertTrue(
            self.gwizard.run_step("connect", gedcom_path=self._write(source_ged))
        )
        self.gwizard.run_step("load")

    @property
    def source_db(self) -> Any:
        return self.gwizard.context["source_db"]

    def _kid(self, db: Any) -> Any:
        (person,) = [p for p in db.iter_people()]
        return person

    def _set_target(self, nick: str = "", call: str = "") -> None:
        kid = self._kid(self.db)
        kid.get_primary_name().set_nick_name(nick)
        kid.get_primary_name().set_call_name(call)
        with DbTxn("names", self.db) as trans:
            self.db.commit_person(kid, trans)

    def _rows(self) -> dict[str, Any]:
        rows = self.gwizard.run_step(
            "compare",
            source_person_handle=self._kid(self.source_db).handle,
            target_person_handle=self._kid(self.db).handle,
        )
        return {row.field_type: row for row in rows if row.field_type in FIELDS}

    def _merge(self, keys: list[str]) -> None:
        self.assertTrue(
            self.gwizard.run_step(
                "apply",
                source_person_handle=self._kid(self.source_db).handle,
                target_person_handle=self._kid(self.db).handle,
                resolutions={key: "source" for key in keys},
            )
        )

    def test_source_has_names_the_tree_lacks(self) -> None:
        """The incoming nickname and call name are source_only rows."""
        self._open()
        rows = self._rows()
        self.assertEqual(set(rows), set(FIELDS))
        self.assertEqual(rows["nickname"].status, "source_only")
        self.assertEqual(rows["nickname"].source_val, "Kiddo")
        self.assertEqual(rows["call_name"].status, "source_only")
        self.assertEqual(rows["call_name"].source_val, "Kid")

    def test_different_values_differ_and_equal_values_match(self) -> None:
        """A different nickname differs; the same call name (any case) matches."""
        self._open()
        self._set_target(nick="Junior", call="KID")
        rows = self._rows()
        self.assertEqual(rows["nickname"].status, "differ")
        self.assertEqual(rows["nickname"].target_val, "Junior")
        self.assertEqual(rows["call_name"].status, "match")

    def test_no_row_when_the_source_has_no_value(self) -> None:
        """A value only the tree has is not listed, so it flags no difference."""
        source = SOURCE_GED.replace("2 NICK Kiddo\n", "").replace(
            "2 _RUFNAME Kid\n", ""
        )
        self._open(source_ged=source)
        self._set_target(nick="Junior", call="Jun")
        self.assertEqual(self._rows(), {})

    def test_merge_copies_only_the_chosen_value(self) -> None:
        """Choosing the nickname leaves the call name alone."""
        self._open()
        self._set_target(nick="Junior", call="Jun")

        self._merge(["nickname"])

        name = self._kid(self.db).get_primary_name()
        self.assertEqual(name.get_nick_name(), "Kiddo")
        self.assertEqual(name.get_call_name(), "Jun")

    def test_merge_call_name(self) -> None:
        """Choosing the call name leaves the nickname alone."""
        self._open()
        self._set_target(nick="Junior")

        self._merge(["call_name"])

        name = self._kid(self.db).get_primary_name()
        self.assertEqual(name.get_nick_name(), "Junior")
        self.assertEqual(name.get_call_name(), "Kid")

    def test_nothing_chosen_changes_nothing(self) -> None:
        """Without a resolution the tree's names stay as they are."""
        self._open()
        self._set_target(nick="Junior")

        self._merge(["given_name"])

        name = self._kid(self.db).get_primary_name()
        self.assertEqual(name.get_nick_name(), "Junior")
        self.assertEqual(name.get_call_name(), "")


if __name__ == "__main__":
    unittest.main()
