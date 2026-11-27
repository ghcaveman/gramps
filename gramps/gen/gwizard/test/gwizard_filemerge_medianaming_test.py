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

"""Tests for the media file naming the GWizard tools share."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import shutil
import tempfile
import unittest

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.config import config
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Date, Event, EventRef, EventType, Name, Person, Surname

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from ..gwizard_filemerge_medianaming import (
    DEFAULT_FILENAME_TEMPLATE,
    FILENAME_TEMPLATE_KEY,
    MAX_STEM_LEN,
    extract_year_and_clean_doctype,
    file_content_hash,
    filename_template,
    format_standard_filename,
    person_media_filename,
    person_year,
    place_file,
)


def _person(given: str = "John", surname: str = "Smith", gid: str = "I0042") -> Person:
    person = Person()
    name = Name()
    name.set_first_name(given)
    part = Surname()
    part.set_surname(surname)
    name.add_surname(part)
    person.set_primary_name(name)
    person.set_gramps_id(gid)
    return person


class FormatTest(unittest.TestCase):
    """format_standard_filename and the tokens it is given."""

    CONTEXT = {
        "ref_id": "I0042",
        "surname": "Smith",
        "given": "John",
        "doc_type": "Census",
        "year": "1920",
        "id": "O0001",
        "orig": "scan 1",
    }

    def test_default_template(self) -> None:
        context = dict(self.CONTEXT, ext="JPG")
        self.assertEqual(
            format_standard_filename(DEFAULT_FILENAME_TEMPLATE, context),
            "I0042_Smith_John-Census-1920.jpg",
        )

    def test_missing_extension_is_jpg(self) -> None:
        self.assertEqual(
            format_standard_filename(DEFAULT_FILENAME_TEMPLATE, self.CONTEXT),
            "I0042_Smith_John-Census-1920.jpg",
        )

    def test_empty_extension_gives_none(self) -> None:
        """A file without an extension keeps having none."""
        context = dict(self.CONTEXT, ext="")
        self.assertEqual(
            format_standard_filename(DEFAULT_FILENAME_TEMPLATE, context),
            "I0042_Smith_John-Census-1920",
        )
        self.assertEqual(format_standard_filename("{orig}.{ext}", context), "scan_1")

    def test_long_names_are_cut(self) -> None:
        context = dict(self.CONTEXT, ext="png", doc_type="Census " * 30)
        name = format_standard_filename(DEFAULT_FILENAME_TEMPLATE, context)
        stem, ext = os.path.splitext(name)
        self.assertEqual(ext, ".png")
        self.assertLessEqual(len(stem), MAX_STEM_LEN)
        self.assertFalse(stem.endswith(("_", "-")))

    def test_year_and_name_are_taken_out_of_the_document_type(self) -> None:
        self.assertEqual(
            extract_year_and_clean_doctype(
                "Smith, John - Census 1920", "Smith", "John"
            ),
            ("Census", "1920"),
        )

    def test_template_setting(self) -> None:
        old = config.get(FILENAME_TEMPLATE_KEY)
        try:
            config.set(FILENAME_TEMPLATE_KEY, "{surname}-{year}.{ext}")
            self.assertEqual(filename_template(), "{surname}-{year}.{ext}")
        finally:
            config.set(FILENAME_TEMPLATE_KEY, old)


class PersonMediaTest(unittest.TestCase):
    """person_media_filename: Media Fix's naming of a person's media."""

    def setUp(self) -> None:
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.person = _person()
        with DbTxn("setup", self.db) as trans:
            birth = Event()
            birth.set_type(EventType.BIRTH)
            date = Date()
            date.set_yr_mon_day(1880, 5, 2)
            birth.set_date_object(date)
            self.db.add_event(birth, trans)
            ref = EventRef()
            ref.ref = birth.handle
            self.person.add_event_ref(ref)
            self.person.set_birth_ref(ref)
            self.db.add_person(self.person, trans)

    def tearDown(self) -> None:
        self.db.close()

    def _name(self, description: str, year: int | str = "") -> str:
        return person_media_filename(
            self.db,
            self.person,
            description,
            ".JPG",
            year=year,
            template=DEFAULT_FILENAME_TEMPLATE,
        )

    def test_year_from_the_description(self) -> None:
        self.assertEqual(
            self._name("Smith, John - Census 1920", 1925),
            "I0042_Smith_John-Census-1920.jpg",
        )

    def test_year_from_the_media_date(self) -> None:
        self.assertEqual(
            self._name("Smith, John - Census", 1925), "I0042_Smith_John-Census-1925.jpg"
        )

    def test_year_from_the_person(self) -> None:
        self.assertEqual(person_year(self.db, self.person), "1880")
        self.assertEqual(
            self._name("Smith, John - Photo"), "I0042_Smith_John-Photo-1880.jpg"
        )

    def test_no_description_is_a_photo(self) -> None:
        self.assertEqual(self._name(""), "I0042_Smith_John-Photo-1880.jpg")

    def test_no_person(self) -> None:
        name = person_media_filename(
            None, None, "", "png", media_id="O0007", template=DEFAULT_FILENAME_TEMPLATE
        )
        self.assertEqual(name, "O0007-Photo.png")

    def test_hash_token(self) -> None:
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = os.path.join(folder, "scan.jpg")
        with open(path, "wb") as handle:
            handle.write(b"image bytes")
        name = person_media_filename(
            self.db,
            self.person,
            "",
            "jpg",
            file_path=path,
            template="{surname}-{hash}.{ext}",
        )
        self.assertEqual(name, "Smith-%s.jpg" % file_content_hash(path))


class PlaceFileTest(unittest.TestCase):
    """place_file: moving a download to its name without replacing a file."""

    def setUp(self) -> None:
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base)

    def _download(self, data: bytes, *folders: str) -> str:
        folder = os.path.join(self.base, *folders)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "download.jpg")
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def _write(self, name: str, data: bytes) -> str:
        path = os.path.join(self.base, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_moves_and_removes_the_cache_folder(self) -> None:
        cache = self._download(b"one", "WikiTree")
        wanted = os.path.join(self.base, "I1_Smith_John-Photo-1880.jpg")
        self.assertEqual(place_file(cache, wanted), wanted)
        self.assertTrue(os.path.isfile(wanted))
        self.assertFalse(os.path.exists(os.path.join(self.base, "WikiTree")))

    def test_two_cache_levels(self) -> None:
        cache = self._download(b"one", "NARA", "12345")
        wanted = os.path.join(self.base, "I1_Smith_John-Military-1899.jpg")
        place_file(cache, wanted, cache_levels=2)
        self.assertEqual(os.listdir(self.base), ["I1_Smith_John-Military-1899.jpg"])

    def test_a_different_file_is_never_replaced(self) -> None:
        wanted = self._write("I1_Smith_John-Photo-1880.jpg", b"older picture")
        final = place_file(self._download(b"new picture", "WikiTree"), wanted)
        self.assertEqual(
            final, os.path.join(self.base, "I1_Smith_John-Photo-1880-2.jpg")
        )
        with open(wanted, "rb") as handle:
            self.assertEqual(handle.read(), b"older picture")

    def test_the_same_file_is_reused(self) -> None:
        wanted = self._write("I1_Smith_John-Photo-1880.jpg", b"same picture")
        cache = self._download(b"same picture", "WikiTree")
        self.assertEqual(place_file(cache, wanted), wanted)
        self.assertFalse(os.path.exists(cache))
        self.assertEqual(os.listdir(self.base), ["I1_Smith_John-Photo-1880.jpg"])


if __name__ == "__main__":
    unittest.main()
