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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Unit tests for the NARA attach review window (gwizardnaraattachdialog.py).

GTK is replaced by mocks, and the image list by a small list-backed store,
so the window's selection and attach logic run without a display. The
record is the real naturalization response in the engine's test data.
"""

# ------------------------------------------------------------
#
# Python modules
#
# ------------------------------------------------------------
from __future__ import annotations
import json
import os
import shutil
import importlib
import sys
import tempfile
import unittest
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, Mock, patch


# -------------------------------------------------------------------------
#
# GTK stubbing for headless test environments
#
# -------------------------------------------------------------------------
class DummyDialog:
    """Stand-in for Gtk.Dialog."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._content_area = MagicMock()
        self.buttons: dict[int, Any] = {}

    def get_content_area(self) -> Any:
        return self._content_area

    def set_title(self, title: str) -> None:
        self.title = title

    def set_default_size(self, width: int, height: int) -> None:
        pass

    def set_resizable(self, resizable: bool) -> None:
        pass

    def set_border_width(self, width: int) -> None:
        pass

    def add_button(self, text: str, response: int) -> Any:
        button = MagicMock()
        self.buttons[response] = button
        return button

    def show_all(self) -> None:
        pass


class FakeListStore:
    """A list-backed stand-in for Gtk.ListStore (iters are row numbers),
    used only while a test opens the window."""

    def __init__(self, *types: Any) -> None:
        self.rows: list[list[Any]] = []

    def append(self, row: list[Any]) -> int:
        self.rows.append(list(row))
        return len(self.rows) - 1

    def get_iter_first(self) -> int | None:
        return 0 if self.rows else None

    def iter_next(self, tree_iter: int) -> int | None:
        return tree_iter + 1 if tree_iter + 1 < len(self.rows) else None

    def get_iter(self, path: str) -> int:
        return int(path)

    def get_value(self, tree_iter: int, column: int) -> Any:
        return self.rows[tree_iter][column]

    def set_value(self, tree_iter: int, column: int, value: Any) -> None:
        self.rows[tree_iter][column] = value


# Fresh stand-ins, put in sys.modules only while this module's tests run.
_STUB_MODULES: dict[str, Any] = {}
_gi: Any = MagicMock()
_gi_repo: Any = MagicMock()
_glib: Any = MagicMock()
_glib.markup_escape_text = lambda s: str(s)
_gi_repo.GLib = _glib
_gtk: Any = MagicMock()
_gtk.Dialog = DummyDialog
for _name in (
    "Label",
    "Button",
    "Box",
    "Frame",
    "Paned",
    "TreeView",
    "TreeViewColumn",
    "CellRendererText",
    "CellRendererToggle",
    "ScrolledWindow",
    "CheckButton",
    "LinkButton",
):
    getattr(_gtk, _name).side_effect = lambda *a, **k: MagicMock()
_gtk.ResponseType.OK = 1
_gtk.ResponseType.CANCEL = 2
_gtk.events_pending.return_value = False
_gi_repo.Gtk = _gtk
for _module in ("Gdk", "Pango"):
    _stub = MagicMock()
    _STUB_MODULES[f"gi.repository.{_module}"] = _stub
    setattr(_gi_repo, _module, _stub)

_gi.repository = _gi_repo
_STUB_MODULES.update(
    {
        "gi": _gi,
        "gi.repository": _gi_repo,
        "gi.repository.GLib": _glib,
        "gi.repository.Gtk": _gtk,
    }
)


def _uses_gtk(name: str) -> bool:
    """
    True for modules that must be imported again under the stand-ins.

    Test modules stay put: unittest finds a module's tearDownModule through
    sys.modules, and they do not use GTK themselves.
    """
    if ".test." in name or name.endswith(".test"):
        return False
    return (
        name in ("gi", "gramps.gui")
        or name.startswith("gi.")
        or name.startswith("gramps.gui.")
    )


_SAVED_MODULES: dict[str, Any] = {}


def setUpModule() -> None:  # pylint: disable=invalid-name
    """
    Import the window under this module's own GTK stand-ins.

    Never reuse real GTK, or a stub another test module put in sys.modules:
    changing it there leaks into other tests (a real GLib whose
    markup_escape_text no longer escapes, for one). Modules that use GTK
    (gi and gramps.gui.*) are set aside and imported afresh, so neither the
    stand-ins nor anything imported with them is seen by other test
    modules; tearDownModule puts the originals back.
    """
    _SAVED_MODULES.clear()
    _SAVED_MODULES.update(sys.modules)
    for name in [name for name in sys.modules if _uses_gtk(name)]:
        del sys.modules[name]
    sys.modules.update(_STUB_MODULES)

    module = importlib.import_module("gramps.gui.gwizard.gwizardnaraattachdialog")
    globals().update({name: getattr(module, name) for name in _IMPORTED_NAMES})


def tearDownModule() -> None:  # pylint: disable=invalid-name
    """Put back the modules setUpModule set aside."""
    sys.modules.clear()
    sys.modules.update(_SAVED_MODULES)
    # Importing afresh re-pointed package attributes (gramps.gui, ...) at
    # the fresh modules; point them back at the originals.
    for name, module in _SAVED_MODULES.items():
        parent, _sep, child = name.rpartition(".")
        if parent and _uses_gtk(name) and parent in _SAVED_MODULES:
            try:
                setattr(_SAVED_MODULES[parent], child, module)
            except (AttributeError, TypeError):
                pass
    _SAVED_MODULES.clear()


# ------------------------------------------------------------
#
# Gramps modules
#
# ------------------------------------------------------------
from gramps.gen.db import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.gwizard.gwizardnaramerge import (
    IMAGE_IN_TREE,
    IMAGE_LINKED,
    IMAGE_NEW,
    ImageStatus,
    NaraCatalogInterface,
    NaraRecordAttacher,
    RecordReview,
)
from gramps.gen.lib import Name, Person, Surname

# Imported by setUpModule, under this module's GTK stand-ins.
if TYPE_CHECKING:
    from gramps.gui.gwizard.gwizardnaraattachdialog import (
        COL_SELECTED,
        NaraAttachDialog,
        COL_MENTIONS,
        COL_NUMBER,
        COL_PROBABLY,
        citation_text,
        has_work,
        page_description,
        person_names,
        selection_summary,
        status_text,
    )

_IMPORTED_NAMES = (
    "COL_SELECTED",
    "NaraAttachDialog",
    "COL_MENTIONS",
    "COL_NUMBER",
    "COL_PROBABLY",
    "citation_text",
    "has_work",
    "page_description",
    "person_names",
    "selection_summary",
    "status_text",
)


def _load_parsed() -> dict[str, Any]:
    """Return the parsed real naturalization record (two images)."""
    sample = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "gen",
        "gwizard",
        "test",
        "data",
        "nara_record_naturalization.json",
    )
    with open(sample, encoding="utf-8") as handle:
        hits = NaraCatalogInterface.extract_hits(json.load(handle))
    return NaraCatalogInterface.parse_record(hits[0])


class _FakeReply:
    """A requests-style reply with fixed content."""

    status_code = 200

    def iter_content(self, chunk_size: int = 65536):
        yield b"jpegdata"


# ------------------------------------------------------------
#
# Tests
#
# ------------------------------------------------------------
class TestReviewText(unittest.TestCase):
    """Test the window's text helpers."""

    def _review(self, statuses: list[str], **kwargs: Any) -> RecordReview:
        images = [
            ImageStatus(
                index=i,
                object_id=str(i),
                filename=f"{i}.jpg",
                size=1_000_000,
                url=f"https://example.com/{i}.jpg",
                mime_type="image/jpeg",
                status=status,
            )
            for i, status in enumerate(statuses)
        ]
        return RecordReview(images=images, **kwargs)

    def test_status_text(self) -> None:
        """Verify each image status has its own label."""
        self.assertEqual(status_text(IMAGE_NEW), "New")
        self.assertEqual(status_text(IMAGE_LINKED), "Already attached")
        self.assertIn("will be linked", status_text(IMAGE_IN_TREE))

    def test_citation_text(self) -> None:
        """Verify the citation line follows the record's state."""
        self.assertIn("new", citation_text(RecordReview()))
        self.assertIn(
            "already in your tree", citation_text(RecordReview(citation_handle="c1"))
        )
        self.assertIn(
            "already attached",
            citation_text(RecordReview(citation_handle="c1", citation_on_person=True)),
        )

    def test_selection_summary(self) -> None:
        """Verify the summary counts new, relinked and attached images."""
        review = self._review([IMAGE_NEW, IMAGE_NEW, IMAGE_IN_TREE, IMAGE_LINKED])
        text = selection_summary(review, {0, 2})
        self.assertIn("1 new images selected (977 KB)", text)
        self.assertIn("1 images already in your tree will be linked", text)
        self.assertIn("1 images are already attached", text)

    def test_has_work(self) -> None:
        """Verify Attach is only useful when something would change."""
        done = self._review([IMAGE_LINKED], citation_on_person=True)
        self.assertFalse(has_work(done, {0}))
        partial = self._review([IMAGE_NEW, IMAGE_LINKED], citation_on_person=True)
        self.assertFalse(has_work(partial, set()))
        self.assertTrue(has_work(partial, {0}))
        self.assertTrue(has_work(self._review([]), set()))


class _ReviewWindowBase(unittest.TestCase):
    """A real record, an in-memory tree and a helper to open the window."""

    def setUp(self) -> None:
        """Set up a tree with one person, a media folder and the record."""
        self.media_dir = tempfile.mkdtemp(prefix="nara-review-")
        self.db = make_database("sqlite")
        self.db.load(":memory:")
        self.db.set_mediapath(self.media_dir)
        person = Person()
        name = Name()
        name.set_first_name("Lyman Angus")
        surname = Surname()
        surname.set_surname("MacDonald")
        name.add_surname(surname)
        person.set_primary_name(name)
        with DbTxn("Add person", self.db) as trans:
            self.person_handle = self.db.add_person(person, trans)
        self.parsed = _load_parsed()
        self.session = Mock()
        self.session.get.return_value = _FakeReply()
        self.dbstate = Mock()
        self.dbstate.db = self.db

    def tearDown(self) -> None:
        """Close the tree and remove the media folder."""
        self.db.close()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _dialog(self, client: Any = None) -> NaraAttachDialog:
        """Open the window with a list-backed image store."""
        attacher = NaraRecordAttacher(self.db, session=self.session)
        with patch.object(_gtk, "ListStore", FakeListStore):
            return NaraAttachDialog(
                None,
                self.dbstate,
                Mock(),
                self.person_handle,
                self.parsed,
                attacher,
                client=client,
            )

    def _text_client(self) -> Any:
        """Return a catalog client whose page text names Lyman MacDonald."""
        ids = [item["object_id"] for item in self.parsed["digital_objects"]]
        client = Mock()
        client.fetch_record_text.return_value = {
            ids[0]: "Box 31981 Cert. 47795 of Lyman MacDonald",
            ids[1]: "",
        }
        return client


class TestNaraAttachDialog(_ReviewWindowBase):
    """Test the review window's selection, attach and preview."""

    def test_new_images_start_checked(self) -> None:
        """Verify every new image starts checked and Attach is enabled."""
        dialog = self._dialog()
        self.assertEqual(dialog.selected_indexes(), {0, 1})
        dialog.btn_attach.set_sensitive.assert_called_with(True)
        self.assertIn(
            "2 new images selected", dialog.summary_label.set_text.call_args[0][0]
        )

    def test_select_buttons_and_toggle(self) -> None:
        """Verify Select None, a single toggle and Select All."""
        dialog = self._dialog()
        dialog.cb_select_none()
        self.assertEqual(dialog.selected_indexes(), set())
        dialog.cb_image_toggled(None, "1")
        self.assertEqual(dialog.selected_indexes(), {1})
        dialog.cb_select_all()
        self.assertEqual(dialog.selected_indexes(), {0, 1})

    def test_attach_only_checked_images(self) -> None:
        """Verify Attach downloads and adds only the checked images."""
        dialog = self._dialog()
        dialog.download_check.get_active.return_value = True
        dialog.cb_select_none()
        dialog.cb_image_toggled(None, "0")
        with patch("gramps.gui.utils.ProgressMeter") as meter_cls:
            meter_cls.return_value.get_cancelled.return_value = False
            result = dialog.run_attach()

        assert result is not None
        self.assertEqual(result.downloaded, 1)
        self.assertEqual(result.media_added, 1)
        self.assertEqual(self.session.get.call_count, 1)
        meter_cls.return_value.close.assert_called_once()

    def test_attached_images_cannot_be_checked_again(self) -> None:
        """Verify a second review shows attached images as not selectable."""
        first = self._dialog()
        first.download_check.get_active.return_value = False
        first.run_attach()

        dialog = self._dialog()
        self.assertEqual(dialog.selected_indexes(), set())
        rows = dialog.image_store.rows
        self.assertEqual([row[COL_SELECTED] for row in rows], [False, False])
        dialog.cb_image_toggled(None, "0")
        self.assertEqual(dialog.selected_indexes(), set())
        dialog.btn_attach.set_sensitive.assert_called_with(False)

    def test_run_attach_reports_failure(self) -> None:
        """Verify an attach error is shown and nothing is returned."""
        dialog = self._dialog()
        dialog.download_check.get_active.return_value = False
        with patch.object(dialog.attacher, "attach", side_effect=RuntimeError("boom")):
            self.assertIsNone(dialog.run_attach())
        self.assertIn(
            "Could not attach the NARA record: boom",
            dialog.summary_label.set_text.call_args[0][0],
        )

    def test_preview_downloads_one_image(self) -> None:
        """Verify Preview downloads just the highlighted image and opens it."""
        dialog = self._dialog()
        model = dialog.image_store
        dialog.image_view.get_selection().get_selected.return_value = (model, 1)
        with patch("gramps.gui.utils.open_file_with_default_application") as open_file:
            dialog.cb_preview()
        self.assertEqual(self.session.get.call_count, 1)
        opened = open_file.call_args[0][0]
        self.assertTrue(opened.endswith("2481.jpg"), opened)
        self.assertTrue(os.path.isfile(opened))

    def test_preview_without_highlight_asks_for_one(self) -> None:
        """Verify Preview asks for a highlighted image first."""
        dialog = self._dialog()
        dialog.image_view.get_selection().get_selected.return_value = (None, None)
        dialog.cb_preview()
        self.session.get.assert_not_called()
        self.assertIn(
            "Highlight an image", dialog.summary_label.set_text.call_args[0][0]
        )


class TestReviewPageText(_ReviewWindowBase):
    """Test page types, mentions and text in the review window."""

    def test_pages_classified_from_fetched_text(self) -> None:
        """Verify one fetch fills the Page, Probably and Mentions columns."""
        client = self._text_client()
        dialog = self._dialog(client)

        client.fetch_record_text.assert_called_once_with("90361620")
        rows = dialog.image_store.rows
        self.assertEqual([row[COL_NUMBER] for row in rows], [1, 2])
        self.assertEqual(rows[0][COL_PROBABLY], "Cover or jacket")
        self.assertEqual(rows[0][COL_MENTIONS], "Lyman, MacDonald")
        self.assertEqual(rows[1][COL_PROBABLY], "No text")
        self.assertIn("one API call", dialog.text_status)
        self.assertIn("1 of 2 pages have text", dialog.text_status)
        dialog.note_check.set_active.assert_called_with(True)

    def test_page_text_panel(self) -> None:
        """Verify the highlighted page's text is shown."""
        dialog = self._dialog(self._text_client())
        dialog.image_view.get_selection().get_selected.return_value = (
            dialog.image_store,
            0,
        )
        dialog.cb_cursor_changed()
        dialog.page_text_view.get_buffer().set_text.assert_called_with(
            "Box 31981 Cert. 47795 of Lyman MacDonald"
        )
        self.assertEqual(dialog.page_text(1), "NARA has no text for this page.")

    def test_without_client_pages_are_not_classified(self) -> None:
        """Verify the window works without page text."""
        dialog = self._dialog(None)
        self.assertEqual(dialog.pages, {})
        self.assertIn("not available", dialog.text_status)
        self.assertEqual(dialog.image_store.rows[0][COL_PROBABLY], "")
        dialog.note_check.set_sensitive.assert_called_with(False)

    def test_failed_text_fetch(self) -> None:
        """Verify a failed fetch is reported and the window still opens."""
        client = Mock()
        client.fetch_record_text.return_value = None
        dialog = self._dialog(client)
        self.assertEqual(dialog.pages, {})
        self.assertIn("did not return it", dialog.text_status)

    def test_attach_passes_descriptions_and_notes(self) -> None:
        """Verify Attach sends page descriptions and, if checked, the texts."""
        dialog = self._dialog(self._text_client())
        dialog.download_check.get_active.return_value = False
        dialog.note_check.get_active.return_value = True
        with patch.object(dialog.attacher, "attach") as attach:
            dialog.run_attach()
        kwargs = attach.call_args.kwargs
        self.assertEqual(
            kwargs["descriptions"][0],
            "MacDonald, Lyman Angus - 1942, page 1: Cover or jacket",
        )
        self.assertEqual(
            kwargs["descriptions"][1], "MacDonald, Lyman Angus - 1942, page 2"
        )
        self.assertIn("Lyman MacDonald", kwargs["page_texts"][0])

        dialog.note_check.get_active.return_value = False
        with patch.object(dialog.attacher, "attach") as attach:
            dialog.run_attach()
        self.assertEqual(attach.call_args.kwargs["page_texts"], {})

    def test_person_names_include_alternate_surnames(self) -> None:
        """Verify given names, surname and married surname are looked for."""
        person = self.db.get_person_from_handle(self.person_handle)
        alt = Name()
        alt_surname = Surname()
        alt_surname.set_surname("Smith")
        alt.add_surname(alt_surname)
        person.add_alternate_name(alt)
        self.assertEqual(person_names(person), ["Lyman", "Angus", "MacDonald", "Smith"])
        self.assertEqual(person_names(None), [])

    def test_page_description_without_label(self) -> None:
        """Verify unidentified pages get just the page number."""
        self.assertEqual(page_description("T", None), "")


if __name__ == "__main__":
    unittest.main()
