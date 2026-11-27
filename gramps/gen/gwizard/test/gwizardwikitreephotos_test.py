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
Tests for WikiTree photos: the full-size image address, Media Fix
descriptions, downloading after a merge under Media Fix's file name, and
reusing a photo already in the tree on a later merge.
"""

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
from typing import Any
from unittest.mock import Mock, patch

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Date, Event, EventRef, EventType, Name, Person, Surname

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from ..gwizardwikitree import (
    WIKITREE_MEDIA_FOLDER,
    WIKITREE_URL_ATTRIBUTE,
    WikiTreeGWizard,
    WikiTreeInterface,
    wikitree_image_url,
)

PHOTO_URL = "https://www.wikitree.com/photo.php/1/1a/Baker-101.jpg"
IMAGE_BYTES = b"\xff\xd8\xff photo of Thomas"


def _profile() -> dict[str, Any]:
    return {
        "Id": 101,
        "Name": "Baker-101",
        "FirstName": "Thomas",
        "LastNameBirth": "Baker",
        "Gender": "Male",
        "BirthDate": "1753-03-10",
        "Photo": "Baker-101.jpg",
        "PhotoData": {
            "path": "/photo.php/1/1a/Baker-101.jpg",
            "url": "/photo.php/thumb/1/1a/Baker-101.jpg/75px-Baker-101.jpg",
            "file": "75px-Baker-101.jpg",
            "orig_width": "600",
            "orig_height": "800",
        },
        "Bio": "== Biography ==\nThomas was a miller.\n"
        "[[Image:Baker-101-1.jpg|thumb|right|Mill on the creek]]\n",
    }


def _fake_download(url: str, path: str, timeout: int = 60) -> bool:
    """Write a small image file, as WikiTreeInterface.download_image would."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as out:
        out.write(IMAGE_BYTES + url.encode("utf-8"))
    return True


class WikiTreeImageUrlTest(unittest.TestCase):
    """The full-size image address follows WikiTree's MediaWiki layout."""

    def test_documented_example(self) -> None:
        # WikiTree's getPhotos documentation lists the 300px thumbnail
        # /photo.php/thumb/f/f1/1860-_Clemens.jpg/300px-1860-_Clemens.jpg.
        self.assertEqual(
            wikitree_image_url("1860-_Clemens.jpg"),
            "https://www.wikitree.com/photo.php/f/f1/1860-_Clemens.jpg",
        )

    def test_spaces_and_first_letter(self) -> None:
        self.assertEqual(
            wikitree_image_url("mill on creek.jpg"),
            wikitree_image_url("Mill_on_creek.jpg"),
        )
        self.assertEqual(wikitree_image_url(""), "")


class WikiTreePhotoTest(unittest.TestCase):
    """Loading, downloading and reusing WikiTree photos."""

    def setUp(self) -> None:
        self.media_dir = tempfile.mkdtemp(prefix="wikitree-media-")
        self.db: DbWriteBase = make_database("sqlite")
        self.db.load(":memory:")
        self.db.set_mediapath(self.media_dir)
        with DbTxn("setup", self.db) as trans:
            birth = Event()
            birth.set_type(EventType(EventType.BIRTH))
            date = Date()
            date.set_yr_mon_day(1753, 3, 10)
            birth.set_date_object(date)
            self.db.add_event(birth, trans)
            self.target = Person()
            name = Name()
            name.set_first_name("Thomas")
            surname = Surname()
            surname.set_surname("Baker")
            name.add_surname(surname)
            self.target.set_primary_name(name)
            self.target.set_gender(Person.MALE)
            ref = EventRef()
            ref.ref = birth.handle
            self.target.add_event_ref(ref)
            self.target.set_birth_ref(ref)
            self.db.add_person(self.target, trans)
        self.client = Mock(spec=WikiTreeInterface)
        self.client.download_image.side_effect = _fake_download

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _load(self, download: bool = True) -> tuple[WikiTreeGWizard, Any, Person]:
        gw = WikiTreeGWizard(self.db)
        gw.run_step(
            "connect",
            query="Baker-101",
            people_data=[_profile()],
            client=self.client,
            download_media=download,
        )
        (person,) = gw.run_step("load")
        return gw, gw.context["source_db"], person

    def _merge(self, gw: WikiTreeGWizard, person: Person) -> None:
        resolutions = {"person_sources": "source"}
        for index in range(len(person.get_media_list())):
            resolutions["media:%d" % index] = "source"
        self.assertTrue(
            gw.run_step(
                "apply",
                source_person_handle=person.handle,
                target_person_handle=self.target.handle,
                resolutions=resolutions,
            )
        )

    def _tree_media(self) -> list[Any]:
        person = self.db.get_person_from_handle(self.target.handle)
        return [self.db.get_media_from_handle(r.ref) for r in person.get_media_list()]

    def test_load_full_size_photo_and_gallery(self) -> None:
        _gw, source_db, person = self._load()
        media = [
            source_db.get_media_from_handle(r.ref) for r in person.get_media_list()
        ]
        by_path = {m.get_path(): m for m in media}
        self.assertIn(PHOTO_URL, by_path)
        photo = by_path[PHOTO_URL]
        self.assertEqual(photo.get_description(), "Baker, Thomas - Photo")
        values = {str(a.get_type()): a.get_value() for a in photo.get_attribute_list()}
        self.assertEqual(values[WIKITREE_URL_ATTRIBUTE], PHOTO_URL)
        self.assertEqual(values["Dimensions"], "600x800")
        gallery = by_path[wikitree_image_url("Baker-101-1.jpg")]
        self.assertEqual(gallery.get_description(), "Baker, Thomas - Mill on the creek")

    def test_merge_downloads_under_media_fix_names(self) -> None:
        gw, _source_db, person = self._load()
        self._merge(gw, person)
        self.assertEqual(gw.context["media_download"]["downloaded"], 2)
        paths = sorted(m.get_path() for m in self._tree_media())
        ref_id = self.db.get_person_from_handle(self.target.handle).get_gramps_id()
        self.assertEqual(
            paths,
            [
                "%s_Baker_Thomas-Mill_on_the_creek-1753.jpg" % ref_id,
                "%s_Baker_Thomas-Photo-1753.jpg" % ref_id,
            ],
        )
        for media in self._tree_media():
            self.assertTrue(
                os.path.isfile(os.path.join(self.media_dir, media.get_path()))
            )
            self.assertTrue(media.get_checksum())
        self.assertFalse(
            os.path.exists(os.path.join(self.media_dir, WIKITREE_MEDIA_FOLDER))
        )

    def test_failed_download_keeps_web_address(self) -> None:
        self.client.download_image.side_effect = None
        self.client.download_image.return_value = False
        gw, _source_db, person = self._load()
        self._merge(gw, person)
        self.assertEqual(len(gw.context["media_download"]["failed"]), 2)
        self.assertIn(PHOTO_URL, [m.get_path() for m in self._tree_media()])

    def test_second_merge_reuses_the_photo(self) -> None:
        gw, _source_db, person = self._load()
        self._merge(gw, person)
        gw2, _source_db2, person2 = self._load()
        self._merge(gw2, person2)
        self.assertEqual(self.db.get_number_of_media(), 2)
        self.assertEqual(gw2.context["media_download"]["downloaded"], 0)

    def test_offline_profile_data_does_not_download(self) -> None:
        gw = WikiTreeGWizard(self.db)
        gw.run_step("connect", query="Baker-101", people_data=[_profile()])
        (person,) = gw.run_step("load")
        self._merge(gw, person)
        self.assertNotIn("media_download", gw.context)
        self.client.download_image.assert_not_called()


class DownloadImageTest(unittest.TestCase):
    """WikiTreeInterface.download_image saves only image replies."""

    def setUp(self) -> None:
        self.folder = tempfile.mkdtemp(prefix="wikitree-dl-")
        self.path = os.path.join(self.folder, "sub", "photo.jpg")

    def tearDown(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    def _reply(self, content_type: str, status: int = 200) -> Mock:
        reply = Mock()
        reply.status_code = status
        reply.headers = {"Content-Type": content_type}
        reply.content = b"data"
        return reply

    def test_image_is_saved(self) -> None:
        with patch("requests.get", return_value=self._reply("image/jpeg")):
            self.assertTrue(WikiTreeInterface().download_image(PHOTO_URL, self.path))
        with open(self.path, "rb") as saved:
            self.assertEqual(saved.read(), b"data")

    def test_web_page_is_refused(self) -> None:
        with patch("requests.get", return_value=self._reply("text/html")):
            self.assertFalse(WikiTreeInterface().download_image(PHOTO_URL, self.path))
        self.assertFalse(os.path.exists(self.path))

    def test_http_error_is_refused(self) -> None:
        with patch("requests.get", return_value=self._reply("image/jpeg", 404)):
            self.assertFalse(WikiTreeInterface().download_image(PHOTO_URL, self.path))


if __name__ == "__main__":
    unittest.main()
