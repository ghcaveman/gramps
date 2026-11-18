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

"""Tests for the media preview pane in GWizard Media Fix.

Find missing media and Fix media references show the focused row's file,
with the region of each media reference outlined.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
# These tests draw on real images, so the real PyGObject is loaded before
# the fakes are installed (they then replace only the widget classes).
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf

from gramps.plugins.tool.test import gwizard_gtk_fakes as fakes

Gtk = fakes.install()

from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.lib import Event, EventRef, Media, MediaRef, Name, Person, Surname
from gramps.plugins.tool import gw_mediapreview as mp
from gramps.plugins.tool import gwizardmediafix as mf
from gramps.plugins.tool.gw_fixmediareferencesdialog import FixMediaReferencesDialog


def setUpModule() -> None:
    """Install the GTK fakes for this module's tests."""
    fakes.install()


def tearDownModule() -> None:
    """Restore the real GTK classes for other test modules."""
    fakes.uninstall()


class _DbState:
    """Minimal stand-in for Gramps' DbState."""

    def __init__(self, db: object) -> None:
        self.db = db


def make_image(path: str, width: int = 120, height: int = 90) -> str:
    """Write a plain white PNG and return its path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    pixbuf.fill(0xFFFFFFFF)
    pixbuf.savev(path, "png", [], [])
    return path


def pixel(pixbuf: Any, x: int, y: int) -> tuple[int, int, int]:
    """Return the RGB value of one pixel."""
    data = pixbuf.get_pixels()
    offset = y * pixbuf.get_rowstride() + x * pixbuf.get_n_channels()
    return tuple(data[offset : offset + 3])  # type: ignore[return-value]


# ------------------------------------------------------------
#
# _PreviewDbTest
#
# ------------------------------------------------------------
class _PreviewDbTest(unittest.TestCase):
    """In-memory database and a media base folder."""

    def setUp(self) -> None:
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.dbstate = _DbState(self.db)
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "MediaBase")
        os.makedirs(self.base)
        self.db.set_mediapath(self.base)
        # Gramps writes thumbnails to its cache folder: use a fresh one.
        thumbs = os.path.join(self.tmp, "thumb")
        for size in ("normal", "large"):
            os.makedirs(os.path.join(thumbs, size))
        for name, size in (("THUMB_NORMAL", "normal"), ("THUMB_LARGE", "large")):
            patcher = patch(
                "gramps.gen.utils.thumbnails." + name, os.path.join(thumbs, size)
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_media(self, path: str, desc: str = "") -> str:
        """Add a media record and return its handle."""
        with DbTxn("add media", self.db) as trans:
            media = Media()
            media.set_path(path)
            media.set_description(desc)
            return self.db.add_media(media, trans)

    def add_person(
        self, surname: str, given: str, refs: list[tuple[str, Any]]
    ) -> Person:
        """Add a person referencing media records, each with a region or None."""
        with DbTxn("add person", self.db) as trans:
            person = Person()
            name = Name()
            name.set_first_name(given)
            surname_obj = Surname()
            surname_obj.set_surname(surname)
            name.add_surname(surname_obj)
            person.set_primary_name(name)
            for handle, rect in refs:
                ref = MediaRef()
                ref.set_reference_handle(handle)
                ref.set_rectangle(rect)
                person.add_media_reference(ref)
            self.db.add_person(person, trans)
        return person

    def add_event(self, desc: str, media_handle: str) -> Event:
        """Add an event that uses a whole media file."""
        with DbTxn("add event", self.db) as trans:
            event = Event()
            event.set_description(desc)
            ref = MediaRef()
            ref.set_reference_handle(media_handle)
            event.add_media_reference(ref)
            self.db.add_event(event, trans)
        return event


# ------------------------------------------------------------
#
# RegionHelperTest
#
# ------------------------------------------------------------
class RegionHelperTest(_PreviewDbTest):
    """Regions, labels, numbering, legend and outline drawing."""

    def test_region_of(self) -> None:
        """No region, an empty one or the full frame all mean the whole image."""
        self.assertIsNone(mp.region_of(None))
        self.assertIsNone(mp.region_of((0, 0, 100, 100)))
        self.assertIsNone(mp.region_of((0, 0, 0, 0)))
        self.assertIsNone(mp.region_of((50, 10, 20, 40)))  # x2 < x1
        self.assertIsNone(mp.region_of(("a", 1, 2, 3)))
        self.assertEqual(mp.region_of((10, 20, 30, 40)), (10, 20, 30, 40))
        self.assertEqual(mp.region_of((-5, 0, 120, 50)), (0, 0, 100, 50))

    def test_media_reference_regions(self) -> None:
        """Every reference to the record is listed with its region and owner."""
        handle = self.add_media("family.jpg")
        other = self.add_media("other.jpg")
        person = self.add_person(
            "Smith", "John", [(handle, (10, 10, 40, 60)), (other, (1, 1, 5, 5))]
        )
        self.add_event("Wedding", handle)
        regions = mp.media_reference_regions(self.db, handle)
        self.assertEqual(len(regions), 2)
        by_rect = {r["rect"]: r["label"] for r in regions}
        self.assertIn(person.gramps_id, by_rect[(10, 10, 40, 60)])
        self.assertIn("Smith", by_rect[(10, 10, 40, 60)])
        self.assertIn("Wedding", by_rect[None])
        prefixed = mp.media_reference_regions(self.db, handle, "[O0007]")
        self.assertTrue(all(r["label"].startswith("[O0007]: ") for r in prefixed))
        self.assertEqual(mp.media_reference_regions(self.db, ""), [])

    def test_number_regions_colors(self) -> None:
        """Colours follow the reference, or the media record when asked."""
        regions = [{"rect": None, "record": 0}, {"rect": None, "record": 0}]
        regions.append({"rect": None, "record": 1})
        by_ref = mp.number_regions(regions)
        self.assertEqual([r["number"] for r in by_ref], [1, 2, 3])
        self.assertEqual(len({r["color"] for r in by_ref}), 3)
        by_record = mp.number_regions(regions, "record")
        self.assertEqual(by_record[0]["color"], by_record[1]["color"])
        self.assertNotEqual(by_record[0]["color"], by_record[2]["color"])

    def test_legend_escapes_and_limits(self) -> None:
        """The legend escapes labels and counts what it leaves out."""
        regions = mp.number_regions(
            [{"label": "A & <B>", "rect": (1, 1, 9, 9)}]
            + [{"label": "x", "rect": None}] * (mp.MAX_LEGEND + 2)
        )
        text = mp.legend_markup(regions)
        self.assertIn("A &amp; &lt;B&gt;", text)
        self.assertIn("region", text)
        self.assertIn("whole image", text)
        self.assertEqual(text.count("■"), mp.MAX_LEGEND)
        self.assertIn("3 more references", text)

    def test_outline_regions_draws_on_a_copy(self) -> None:
        """A region's border is drawn in its colour; whole images are left alone."""
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 200, 100)
        pixbuf.fill(0xFFFFFFFF)
        regions = mp.number_regions([{"label": "a", "rect": (20, 50, 60, 90)}])
        drawn = mp.outline_regions(pixbuf, regions)
        self.assertIsNot(drawn, pixbuf)
        self.assertEqual((drawn.get_width(), drawn.get_height()), (200, 100))
        self.assertEqual(pixel(pixbuf, 80, 89), (255, 255, 255))  # original kept
        red, green, blue = pixel(drawn, 80, 89)  # on the bottom edge
        self.assertGreater(red, 150)
        self.assertLess(green, 100)
        self.assertEqual(pixel(drawn, 80, 70), (255, 255, 255))  # inside: clear
        whole = mp.number_regions([{"label": "b", "rect": None}])
        self.assertIs(mp.outline_regions(pixbuf, whole), pixbuf)


# ------------------------------------------------------------
#
# PaneTest
#
# ------------------------------------------------------------
class PaneTest(_PreviewDbTest):
    """The pane itself."""

    def test_missing_file_shows_message(self) -> None:
        """A file that does not exist shows the caption and no image."""
        pane = mp.MediaPreviewPane()
        pane.show_file(os.path.join(self.tmp, "none.jpg"), "not here")
        self.assertEqual(pane.shown["full_path"], "")
        self.assertEqual(pane.shown["caption"], "not here")
        pane.image.set_from_icon_name.assert_called()

    def test_double_click_opens_file(self) -> None:
        """A double-click opens the shown file in the default viewer."""
        path = make_image(os.path.join(self.base, "a.png"))
        pane = mp.MediaPreviewPane(uistate="UI")
        pane.show_file(path, "caption")
        opener = MagicMock()
        fake_utils = MagicMock(open_file_with_default_application=opener)
        event = MagicMock(type=Gdk.EventType.DOUBLE_BUTTON_PRESS, button=1)
        with patch.dict(sys.modules, {"gramps.gui.utils": fake_utils}):
            self.assertTrue(pane.cb_button_press(None, event))
        opener.assert_called_once_with(path, "UI")
        single = MagicMock(type=Gdk.EventType.BUTTON_PRESS, button=1)
        self.assertFalse(pane.cb_button_press(None, single))


# ------------------------------------------------------------
#
# FindMissingPreviewTest
#
# ------------------------------------------------------------
class FindMissingPreviewTest(_PreviewDbTest):
    """Find missing media previews the focused row's file."""

    def dialog(self) -> mf.FindMissingMediaDialog:
        """Open the dialog on the test tree."""
        return mf.FindMissingMediaDialog(dbstate=self.dbstate)

    def target(self, dlg: mf.FindMissingMediaDialog, handle: str) -> dict[str, Any]:
        """Return the dialog row for a media handle."""
        return next(t for t in dlg.row_targets if t["entry"]["handle"] == handle)

    def focus(self, dlg: Any, target: dict[str, Any]) -> None:
        """Move the focus into one of the row's widgets, as a click would."""
        widget = next(w for w, t in dlg._focus_rows.items() if t is target)
        dlg.cb_row_focus(None, widget)

    def test_suggestion_previewed_with_regions(self) -> None:
        """The first row opens showing its suggested file and its people."""
        found = make_image(os.path.join(self.base, "people", "IMG_1.png"))
        handle = self.add_media("C:/Old/IMG_1.png", "Family group")
        self.add_person("Smith", "John", [(handle, (10, 10, 50, 50))])
        dlg = self.dialog()
        shown = dlg.preview.shown
        self.assertEqual(shown["full_path"], found)
        self.assertIn("suggested (same file name)", shown["caption"])
        self.assertEqual(len(shown["regions"]), 1)
        self.assertEqual(shown["regions"][0]["rect"], (10, 10, 50, 50))
        self.assertIn("Smith", shown["regions"][0]["label"])
        # The image shown is Gramps' large thumbnail with the region outlined:
        # the box runs from 10% to 50% across and down.
        pixbuf = dlg.preview.image.set_from_pixbuf.call_args[0][0]
        width, height = pixbuf.get_width(), pixbuf.get_height()
        self.assertEqual((width, height), (180, 135))
        self.assertNotEqual(pixel(pixbuf, 18, height * 30 // 100), (255, 255, 255))
        self.assertEqual(
            pixel(pixbuf, width * 30 // 100, height * 30 // 100), (255, 255, 255)
        )
        self.assertEqual(
            pixel(pixbuf, width * 80 // 100, height * 80 // 100), (255, 255, 255)
        )

    def test_focus_moves_preview(self) -> None:
        """Focusing another row shows that row's file."""
        make_image(os.path.join(self.base, "a.png"))
        second = make_image(os.path.join(self.base, "b.png"))
        h_a = self.add_media("C:/Old/a.png")
        h_b = self.add_media("C:/Old/b.png")
        dlg = self.dialog()
        self.focus(dlg, self.target(dlg, h_b))
        self.assertIs(dlg.preview_target, self.target(dlg, h_b))
        self.assertEqual(dlg.preview.shown["full_path"], second)
        self.focus(dlg, self.target(dlg, h_a))
        self.assertTrue(dlg.preview.shown["full_path"].endswith("a.png"))
        dlg.cb_row_focus(None, None)  # focus left the table: keep the preview
        self.assertTrue(dlg.preview.shown["full_path"].endswith("a.png"))

    def test_entered_path_wins_and_updates(self) -> None:
        """Typing a path updates the preview of the focused row only."""
        typed = make_image(os.path.join(self.base, "typed.png"))
        h_a = self.add_media("C:/Old/one.png")
        h_b = self.add_media("C:/Old/two.png")
        dlg = self.dialog()
        row_a, row_b = self.target(dlg, h_a), self.target(dlg, h_b)
        self.focus(dlg, row_a)
        self.assertIn("no file chosen yet", dlg.preview.shown["caption"])
        row_a["path_entry"].set_text("typed.png")
        self.assertEqual(dlg.preview.shown["full_path"], typed)
        self.assertIn("new path", dlg.preview.shown["caption"])
        row_b["path_entry"].set_text("typed.png")  # not the shown row
        self.assertIs(dlg.preview_target, row_a)
        row_a["path_entry"].set_text("nothing/here.png")
        self.assertIn("is not a file", dlg.preview.shown["caption"])

    def test_preview_error_does_not_break_dialog(self) -> None:
        """If a preview fails, the pane says so and the dialog carries on."""
        self.add_media("C:/Old/x.png")
        with patch.object(
            mf.FindMissingMediaDialog, "update_preview", side_effect=OSError("boom")
        ):
            dlg = self.dialog()
        self.assertIn("No preview available", dlg.preview.shown["caption"])


# ------------------------------------------------------------
#
# FixReferencesPreviewTest
#
# ------------------------------------------------------------
class FixReferencesPreviewTest(_PreviewDbTest):
    """Fix media references previews what a merge would combine."""

    def test_duplicate_group_colours_each_record(self) -> None:
        """Each record's references get that record's colour."""
        path = make_image(os.path.join(self.base, "shared.png"))
        h_1 = self.add_media("shared.png", "first")
        h_2 = self.add_media("shared.png", "second")
        self.add_person("Smith", "John", [(h_1, (5, 5, 30, 40))])
        self.add_person("Smith", "Mary", [(h_2, (50, 5, 80, 40))])
        self.add_event("Census", h_2)
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        shown = dlg.preview.shown
        self.assertEqual(
            os.path.normcase(os.path.normpath(shown["full_path"])),
            os.path.normcase(os.path.normpath(path)),
        )
        self.assertEqual(len(shown["regions"]), 3)
        colors: dict[str, set[str]] = {}
        for region in shown["regions"]:
            gid = region["label"].split(":")[0]
            colors.setdefault(gid, set()).add(region["color"])
        self.assertEqual(len(colors), 2)  # two media records
        self.assertTrue(all(len(c) == 1 for c in colors.values()))
        self.assertNotEqual(*[next(iter(c)) for c in colors.values()])
        keeper = dlg.row_targets[0]["group"]["keeper"]["gramps_id"]
        self.assertIn("all 3 references on [%s]" % keeper, shown["caption"])

    def test_unreferenced_record_caption(self) -> None:
        """An unreferenced record says it has no references."""
        make_image(os.path.join(self.base, "lonely.png"))
        self.add_media("lonely.png")
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        self.assertIn("has no references", dlg.preview.shown["caption"])
        self.assertEqual(dlg.preview.shown["regions"], [])

    def test_missing_shared_file_noted(self) -> None:
        """A shared file that cannot be found is said so in the caption."""
        h_1 = self.add_media("gone.png")
        h_2 = self.add_media("gone.png")
        self.add_person("Smith", "John", [(h_1, None), (h_2, None)])
        dlg = FixMediaReferencesDialog(dbstate=self.dbstate)
        self.assertIn("cannot be found", dlg.preview.shown["caption"])
        self.assertEqual(len(dlg.preview.shown["regions"]), 2)


fakes.uninstall()

if __name__ == "__main__":
    unittest.main()
