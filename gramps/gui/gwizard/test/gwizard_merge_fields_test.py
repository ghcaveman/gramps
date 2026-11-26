#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  GWizard Merge Field Tests
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
Tests for the field rows built by the GWizard merge dialog.

These cover the surname rows, where a GEDCOM surname prefix (``SPFX``)
and additional surnames must not be mistaken for a match.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import unittest
from unittest.mock import Mock, patch

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except (ImportError, ValueError):
    import html
    import sys
    import types
    from unittest.mock import MagicMock

    class _DummyBase:
        pass

    class _DummyClass:
        FILL = 0
        START = 0
        END = 0
        CENTER = 0

        def __init__(self, *args, **kwargs):
            self._name = ""

        def __call__(self, *args, **kwargs):
            return self

        def __getattr__(self, name):
            return self

        def __int__(self):
            return 0

        def __mro_entries__(self, bases):
            return (type(f"_DummyBase_{id(self)}", (), {}),)

        def set_name(self, name):
            self._name = name

        def get_name(self):
            return self._name

        def add_pattern(self, pattern):
            pass

    class _GtkModule(types.ModuleType):
        def __getattr__(self, name):
            return _DummyClass()

    _gtk = _GtkModule("gi.repository.Gtk")
    _glib = MagicMock()
    _glib.MAJOR_VERSION = 2
    _glib.MINOR_VERSION = 80
    _glib.MICRO_VERSION = 0
    _glib.markup_escape_text = html.escape

    _repo = types.ModuleType("gi.repository")
    _repo_attrs = vars(_repo)
    _repo_attrs.update(
        {
            "Gtk": _gtk,
            "GLib": _glib,
            "Gio": MagicMock(),
            "Gdk": _DummyClass(),
            "Pango": MagicMock(),
            "PangoCairo": MagicMock(),
            "GObject": _DummyClass(),
            "GdkPixbuf": MagicMock(),
        }
    )

    _gi = types.ModuleType("gi")
    vars(_gi).update({"repository": _repo, "require_version": lambda *args: None})

    sys.modules["gi"] = _gi
    sys.modules["gi.repository"] = _repo
    sys.modules["gi.repository.Gtk"] = _gtk
    sys.modules["gi.repository.GLib"] = _glib
    sys.modules["gi.repository.Gio"] = _repo_attrs["Gio"]
    sys.modules["gi.repository.Gdk"] = _repo_attrs["Gdk"]
    sys.modules["gi.repository.Pango"] = _repo_attrs["Pango"]
    sys.modules["gi.repository.PangoCairo"] = _repo_attrs["PangoCairo"]
    sys.modules["gi.repository.GObject"] = _repo_attrs["GObject"]
    sys.modules["gi.repository.GdkPixbuf"] = _repo_attrs["GdkPixbuf"]

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.lib import Date, EventRef, Name, Person, Surname
from gramps.gen.gwizard.gwizard_base import surname_prefix_text, surname_text
from gramps.gui.gwizard.gwizardmergedialog import (
    citation_sources_summary,
    field_values_differ,
    person_events_by_type,
)


def _person(first: str, surnames: list[tuple[str, str]]) -> Person:
    """
    Build a person with one primary name from (surname, prefix) pairs.

    :param first: The given name.
    :param surnames: Sequence of ``(surname, prefix)`` tuples.
    :returns: The constructed person.
    :rtype: Person
    """
    name = Name()
    name.first_name = first
    for surname, prefix in surnames:
        surn = Surname()
        surn.set_surname(surname)
        surn.set_prefix(prefix)
        name.add_surname(surn)
    person = Person()
    person.set_primary_name(name)
    return person


def _mock_event(
    handle: str, event_type: str, date: Date | None = None, description: str = ""
) -> Mock:
    """Build a mock event with the fields used by merge dialog comparisons."""
    return Mock(
        handle=handle,
        get_type=Mock(return_value=event_type),
        get_date_object=Mock(return_value=date or Date()),
        get_place_handle=Mock(return_value=None),
        get_description=Mock(return_value=description),
        get_citation_list=Mock(return_value=[]),
    )


class GWizardMergeFieldRowsTest(unittest.TestCase):
    """Field row values for names that differ only by prefix or extra surname."""

    def test_surname_prefix_difference_is_flagged(self) -> None:
        """
        A SPFX-only difference must mark the Surname Prefix row as different.
        """
        source = _person("Anna", [("Hansdotter", "")])
        target = _person("Anna", [("Hansdotter", "Vrow")])
        self.assertFalse(
            field_values_differ(
                surname_text(source.get_primary_name()),
                surname_text(target.get_primary_name()),
            )
        )
        self.assertTrue(
            field_values_differ(
                surname_prefix_text(source.get_primary_name()),
                surname_prefix_text(target.get_primary_name()),
            )
        )
        self.assertEqual(surname_prefix_text(source.get_primary_name()), "")
        self.assertEqual(surname_prefix_text(target.get_primary_name()), "Vrow")

    def test_additional_surname_is_flagged(self) -> None:
        """
        An extra surname on the target must mark the Surname row as different.
        """
        source = _person("Anna", [("Hansdotter", "")])
        target = _person("Anna", [("Hansdotter", "Vrow"), ("Smith", "")])
        self.assertTrue(
            field_values_differ(
                surname_text(source.get_primary_name()),
                surname_text(target.get_primary_name()),
            )
        )
        self.assertEqual(surname_text(source.get_primary_name()), "Hansdotter")
        self.assertEqual(surname_text(target.get_primary_name()), "Hansdotter Smith")

    def test_shared_prefix_is_not_flagged(self) -> None:
        """
        Equal prefixes and surnames must not be reported as a difference.
        """
        source = _person("Anna", [("Hansdotter", "Vrow")])
        target = _person("Anna", [("Hansdotter", "Vrow")])
        self.assertFalse(
            field_values_differ(
                surname_prefix_text(source.get_primary_name()),
                surname_prefix_text(target.get_primary_name()),
            )
        )

    def test_empty_source_prefix_still_differs_from_target(self) -> None:
        """
        An empty source value compares as different from a populated target.
        """
        self.assertTrue(field_values_differ("", "Vrow"))
        self.assertFalse(field_values_differ(None, ""))
        self.assertFalse(field_values_differ("Vrow", "Vrow"))


class GWizardCitationSummaryTest(unittest.TestCase):
    """Citation summaries shown with values in the merge dialog."""

    def test_summary_includes_source_title_and_citation_page(self) -> None:
        citation = Mock()
        citation.get_reference_handle.return_value = "source-handle"
        citation.get_page.return_value = "42"
        citation.get_note_list.return_value = []
        source = Mock()
        source.get_title.return_value = "1840 Census"
        source.get_author.return_value = ""
        source.gramps_id = "S0001"
        db = Mock()
        db.get_citation_from_handle.return_value = citation
        db.get_source_from_handle.return_value = source
        obj = Mock()
        obj.get_citation_list.return_value = ["citation-handle"]

        self.assertEqual(citation_sources_summary(db, obj), "1840 Census (page 42)")

    def test_summary_is_empty_without_citations(self) -> None:
        obj = Mock()
        obj.get_citation_list.return_value = []

        self.assertEqual(citation_sources_summary(Mock(), obj), "")

    def test_summary_includes_distinct_author(self) -> None:
        citation = Mock()
        citation.get_reference_handle.return_value = "source-handle"
        citation.get_page.return_value = "42"
        citation.get_note_list.return_value = []
        source = Mock()
        source.get_title.return_value = "1850 Census"
        source.get_author.return_value = "Bureau of the Census"
        source.get_reporef_list.return_value = []
        source.gramps_id = "S0001"
        db = Mock()
        db.get_citation_from_handle.return_value = citation
        db.get_source_from_handle.return_value = source
        obj = Mock()
        obj.get_citation_list.return_value = ["citation-handle"]

        self.assertEqual(
            citation_sources_summary(db, obj),
            "Bureau of the Census, 1850 Census (page 42)",
        )

    def test_summary_omits_duplicate_author(self) -> None:
        citation = Mock()
        citation.get_reference_handle.return_value = "source-handle"
        citation.get_page.return_value = "42"
        citation.get_note_list.return_value = []
        source = Mock()
        source.get_title.return_value = "Ancestry.com Family Tree"
        source.get_author.return_value = "Ancestry.com"
        source.get_reporef_list.return_value = []
        source.gramps_id = "S0001"
        db = Mock()
        db.get_citation_from_handle.return_value = citation
        db.get_source_from_handle.return_value = source
        obj = Mock()
        obj.get_citation_list.return_value = ["citation-handle"]

        self.assertEqual(
            citation_sources_summary(db, obj),
            "Ancestry.com Family Tree (page 42)",
        )

    def test_summary_includes_repository_provenance(self) -> None:
        citation = Mock()
        citation.get_reference_handle.return_value = "source-handle"
        citation.get_page.return_value = "42"
        citation.get_note_list.return_value = []
        repo_ref = Mock(ref="repo-handle")
        source = Mock()
        source.get_title.return_value = "1840 Census"
        source.get_author.return_value = ""
        source.get_reporef_list.return_value = [repo_ref]
        source.gramps_id = "S0001"
        repo = Mock()
        repo.get_name.return_value = "National Archives and Records Administration"
        db = Mock()
        db.get_citation_from_handle.return_value = citation
        db.get_source_from_handle.return_value = source
        db.get_repository_from_handle.return_value = repo
        obj = Mock()
        obj.get_citation_list.return_value = ["citation-handle"]

        self.assertEqual(
            citation_sources_summary(db, obj),
            "1840 Census (page 42) via National Archives and Records Administration",
        )

    def test_summary_combines_author_title_page_and_repository(self) -> None:
        citation = Mock()
        citation.get_reference_handle.return_value = "source-handle"
        citation.get_page.return_value = "ED 51-508, p. 3B"
        citation.get_note_list.return_value = []
        repo_ref = Mock(ref="repo-handle")
        source = Mock()
        source.get_title.return_value = "Population Schedule"
        source.get_author.return_value = "Bureau of the Census"
        source.get_reporef_list.return_value = [repo_ref]
        source.gramps_id = "S0001"
        repo = Mock()
        repo.get_name.return_value = "NARA"
        db = Mock()
        db.get_citation_from_handle.return_value = citation
        db.get_source_from_handle.return_value = source
        db.get_repository_from_handle.return_value = repo
        obj = Mock()
        obj.get_citation_list.return_value = ["citation-handle"]

        self.assertEqual(
            citation_sources_summary(db, obj),
            "Bureau of the Census, Population Schedule (page ED 51-508, p. 3B) via NARA",
        )


class GWizardEventGroupingTest(unittest.TestCase):
    """Events listed in the merge dialog match the compare window's set."""

    def test_includes_vital_and_other_events_but_excludes_internal_markers(
        self,
    ) -> None:
        event_types = {
            "birth": "Birth",
            "death": "Death",
            "occupation": "Occupation",
            "exclude": "_PPEXCLUDE",
            "fslink": "_FSLINK",
        }
        events = {}
        refs = []
        for handle, event_type in event_types.items():
            event = Mock()
            event.handle = handle
            event.get_type.return_value = event_type
            events[handle] = event
            refs.append(Mock(ref=handle))

        db = Mock()
        db.get_event_from_handle.side_effect = events.__getitem__
        person = Mock()
        person.get_event_ref_list.return_value = refs

        self.assertEqual(
            person_events_by_type(db, person),
            {"Birth": ["birth"], "Death": ["death"], "Occupation": ["occupation"]},
        )

    def test_compare_event_lines_sorted_alphabetically(self) -> None:
        from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow

        window = Mock(spec=GWizardCompareWindow)
        window._format_event_line = lambda event, db: str(event.get_type())

        event_types = ["Residence", "Birth", "Occupation", "Census"]
        events = {}
        refs = []
        for etype in event_types:
            event = Mock()
            event.handle = etype.lower()
            event.get_type.return_value = etype
            events[event.handle] = event
            refs.append(Mock(ref=event.handle))

        db = Mock()
        db.get_event_from_handle.side_effect = events.__getitem__
        person = Mock()
        person.get_event_ref_list.return_value = refs

        lines = GWizardCompareWindow._event_lines(window, person, db)
        self.assertEqual(lines, ["Birth", "Census", "Occupation", "Residence"])

    def test_merge_dialog_events_sorted_alphabetically(self) -> None:
        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        dialog = Mock(spec=GWizardMergeDialog)
        dialog.source_person = Person()
        dialog.target_person = Person()
        dialog.source_db = Mock()
        dialog.target_db = Mock()
        dialog.gwizard = Mock(context={})
        dialog._grid = Mock()
        dialog._value_column_size_group = Mock()
        dialog._resolutions = {}
        dialog._mergeable_count = 0
        dialog._format_diff_line = lambda label, a, b, show_label, is_left: a
        dialog._event_for = lambda db, person, kind: ("", None, None)
        dialog._event_display_from = lambda event: ""
        dialog._related_text = lambda rel, db: ""
        dialog._spouses = lambda db, person: []
        dialog._parents = lambda db, person, role: []
        dialog._children = lambda db, person: []
        dialog._sorted_relatives = lambda db, persons: persons

        # Events need some data: empty events are not listed.
        s_events = {
            "s_res": _mock_event("s_res", "Residence", description="Farm"),
            "s_cen": _mock_event("s_cen", "Census", description="1900"),
        }
        t_events = {
            "t_cen": _mock_event("t_cen", "Census", description="1900"),
            "t_res": _mock_event("t_res", "Residence", description="Farm"),
        }
        dialog.source_db.get_event_from_handle.side_effect = s_events.get
        dialog.target_db.get_event_from_handle.side_effect = t_events.get
        dialog.source_db.get_dbname.return_value = "db"
        dialog.target_db.get_dbname.return_value = "db"
        dialog._event_line_from = lambda db, ev: ev.handle if ev else ""

        ref_s1 = EventRef()
        ref_s1.ref = "s_res"
        dialog.source_person.add_event_ref(ref_s1)
        ref_s2 = EventRef()
        ref_s2.ref = "s_cen"
        dialog.source_person.add_event_ref(ref_s2)

        ref_t1 = EventRef()
        ref_t1.ref = "t_cen"
        dialog.target_person.add_event_ref(ref_t1)
        ref_t2 = EventRef()
        ref_t2.ref = "t_res"
        dialog.target_person.add_event_ref(ref_t2)

        recorded_labels = []

        def record_diff_line(label, a, b, show_label, is_left):
            if is_left and label in ("Census", "Residence"):
                recorded_labels.append(label)
            return a

        dialog._format_diff_line = record_diff_line

        from gramps.gui.gwizard import gwizardmergedialog

        with (
            patch.object(gwizardmergedialog.Gtk, "Label", return_value=Mock()),
            patch.object(gwizardmergedialog.Gtk, "Separator", return_value=Mock()),
            patch.object(gwizardmergedialog, "create_diff_cell", return_value=Mock()),
        ):
            GWizardMergeDialog._populate_fields(dialog)
        self.assertEqual(recorded_labels, ["Census", "Residence"])

    def test_cancelled_merge_does_not_rebuild_the_compare_window(self) -> None:
        """
        Closing the merge dialog without merging leaves the compare
        window's lists alone; a completed merge rebuilds them.
        """
        from types import SimpleNamespace
        from unittest.mock import patch

        from gramps.gui.gwizard import gwizardcompare, gwizardmergedialog
        from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow

        # Fixed response codes, so the test runs with or without real GTK.
        codes = SimpleNamespace(OK=-5, CANCEL=-6, DELETE_EVENT=-4)
        for response, rebuilt in (
            (codes.CANCEL, False),
            (codes.DELETE_EVENT, False),
            (codes.OK, True),
        ):
            window = Mock()
            window._get_selected_pair.return_value = ("s1", "t1")
            dialog = Mock()
            dialog.run.return_value = response
            with (
                patch.object(
                    gwizardmergedialog, "GWizardMergeDialog", return_value=dialog
                ),
                patch.object(gwizardcompare.Gtk, "ResponseType", codes),
            ):
                GWizardCompareWindow.cb_merge_dialog(window, Mock())
            dialog.destroy.assert_called_once_with()
            window.present.assert_called_once_with()
            self.assertEqual(window.select_category.called, rebuilt, response)

    def test_prev_next_places_both_panels_without_sync_interference(
        self,
    ) -> None:
        """
        While Prev/Next places both panels, selection mirroring and scroll
        syncing are held off, and both rows are revealed afterwards.
        """
        from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow

        window = Mock()
        window.diff_list = [{"source_handle": "s1", "target_handle": "t1"}]
        window.diff_index = 0
        window.left_panel = {"name": "left"}
        window.right_panel = {"name": "right"}
        flags_during_select = []

        def select(panel: dict, handle: str) -> bool:
            flags_during_select.append(
                (
                    handle,
                    window._syncing,
                    window._syncing_selection,
                    window._suppress_scroll_sync,
                )
            )
            return True

        window._select_handle.side_effect = select

        GWizardCompareWindow._highlight_diff(window)

        self.assertEqual(
            flags_during_select, [("s1", True, True, True), ("t1", True, True, True)]
        )
        self.assertFalse(window._syncing)
        self.assertFalse(window._syncing_selection)
        window._cancel_pending_scroll_sync.assert_called_with()
        window._schedule_reveal.assert_called_once_with()

    def test_scroll_sync_is_ignored_while_suppressed(self) -> None:
        """Scroll events caused by Prev/Next do not schedule a scroll sync."""
        from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow

        for callback in (
            GWizardCompareWindow.cb_left_vscroll_changed,
            GWizardCompareWindow.cb_right_vscroll_changed,
            GWizardCompareWindow.cb_left_hscroll_changed,
            GWizardCompareWindow.cb_right_hscroll_changed,
        ):
            for suppressed in (True, False):
                window = Mock(_syncing_scroll=False, _suppress_scroll_sync=suppressed)
                callback(window, Mock())
                self.assertEqual(
                    window._schedule_scroll_sync.called, not suppressed, callback
                )

    def test_reveal_centres_rows_then_allows_scroll_sync(self) -> None:
        """
        After layout, both panels' rows are scrolled into view, centred,
        and scroll syncing is allowed again.
        """
        from unittest.mock import patch

        from gramps.gui.gwizard import gwizardcompare
        from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow

        window = Mock(_reveal_idle_id=None, _suppress_scroll_sync=True)
        window.left_panel = {"tree": Mock(), "reveal_path": "0:3"}
        window.right_panel = {"tree": Mock(), "reveal_path": None}
        with patch.object(
            gwizardcompare.GLib,
            "idle_add",
            side_effect=lambda func, **_kwargs: func(),
        ):
            GWizardCompareWindow._schedule_reveal(window)

        window.left_panel["tree"].scroll_to_cell.assert_called_once_with(
            "0:3", None, True, 0.5, 0.0
        )
        window.right_panel["tree"].scroll_to_cell.assert_not_called()
        self.assertFalse(window._suppress_scroll_sync)
        window._cancel_pending_scroll_sync.assert_called_with()

    def test_counterpart_lookup_uses_the_panel_side(self) -> None:
        """
        A handle present in both databases is looked up on the side it was
        selected on, not guessed from the incoming file's index.
        """
        from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow

        window = Mock()
        window.source_index = {"h1": "Ann Doe"}
        window._pair_map = {"h1": "t9"}
        window._pair_map_rev = {"h1": "s5"}
        window.diff_list = []

        lookup = GWizardCompareWindow._get_counterpart
        self.assertEqual(lookup(window, "h1", from_source=True), "t9")
        self.assertEqual(lookup(window, "h1", from_source=False), "s5")
        # Without a side, the old guess (the source index) still applies.
        self.assertEqual(lookup(window, "h1"), "t9")

    def test_relatives_sorted_by_name_then_birth_year(self) -> None:
        """
        Relatives come out in one order whatever order a tree stores them
        in: by name, then birth year, undated last.
        """
        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        people = {
            "zed": (_person("Zed", [("Doe", "")]), "1890"),
            "ann_late": (_person("Ann", [("Doe", "")]), "1905"),
            "ann_undated": (_person("Ann", [("Doe", "")]), ""),
            "ann_early": (_person("Ann", [("Doe", "")]), "1899"),
        }
        years = {id(person): year for person, year in people.values()}
        dialog = Mock(spec=GWizardMergeDialog)
        dialog._event_year = lambda db, person, kind: years[id(person)]

        ordered = GWizardMergeDialog._sorted_relatives(
            dialog, Mock(), [person for person, _year in people.values()]
        )

        self.assertEqual(
            [years[id(person)] for person in ordered], ["1899", "1905", "", "1890"]
        )

    def test_merge_dialog_aligns_events_with_different_date_quality(self) -> None:
        from gramps.gui.gwizard.gwizardmergedialog import GWizardMergeDialog

        dialog = Mock(spec=GWizardMergeDialog)
        dialog.source_person = Person()
        dialog.target_person = Person()
        dialog.source_db = Mock()
        dialog.target_db = Mock()
        dialog.gwizard = Mock(context={})
        dialog._grid = Mock()
        dialog._value_column_size_group = Mock()
        dialog._resolutions = {}
        dialog._mergeable_count = 0
        dialog._event_for = lambda db, person, kind: (
            ("", None, "s_birth")
            if db is dialog.source_db and kind == "birth"
            else (
                ("", None, "t_birth")
                if db is dialog.target_db and kind == "birth"
                else ("", None, None)
            )
        )
        dialog._event_display_from = lambda event: ""
        dialog._related_text = lambda rel, db: ""
        dialog._spouses = lambda db, person: []
        dialog._parents = lambda db, person, role: []
        dialog._children = lambda db, person: []
        dialog._sorted_relatives = lambda db, persons: persons

        def date(
            day: int = 0,
            month: int = 0,
            year: int = 0,
            quality: int = Date.QUAL_NONE,
        ) -> Date:
            """Build an optional Gregorian date for an event."""
            event_date = Date()
            if year:
                event_date.set(
                    quality,
                    Date.MOD_NONE,
                    Date.CAL_GREGORIAN,
                    (day, month, year, False),
                )
            return event_date

        s_events = {
            "s_birth": _mock_event("s_birth", "Birth", date(2, 10, 1864)),
            "s_empty": _mock_event("s_empty", "Birth"),
        }
        t_events = {
            "t_empty": _mock_event("t_empty", "Birth"),
            "t_birth": _mock_event(
                "t_birth",
                "Birth",
                date(2, 10, 1864, Date.QUAL_ESTIMATED),
            ),
        }
        event_lines = {
            "s_birth": "1864-10-02 Luderup",
            "s_empty": "",
            "t_birth": "estimated 1864-10-02 Luderup",
            "t_empty": "",
        }

        dialog.source_db.get_event_from_handle.side_effect = s_events.get
        dialog.target_db.get_event_from_handle.side_effect = t_events.get
        dialog.source_db.get_dbname.return_value = "db"
        dialog.target_db.get_dbname.return_value = "db"
        dialog._event_line_from = lambda db, ev: (
            event_lines.get(ev.handle, "") if ev else ""
        )

        # Source and target have different event order and date quality.
        ref_s1 = EventRef()
        ref_s1.ref = "s_birth"
        dialog.source_person.add_event_ref(ref_s1)
        ref_s2 = EventRef()
        ref_s2.ref = "s_empty"
        dialog.source_person.add_event_ref(ref_s2)

        ref_t1 = EventRef()
        ref_t1.ref = "t_empty"
        dialog.target_person.add_event_ref(ref_t1)
        ref_t2 = EventRef()
        ref_t2.ref = "t_birth"
        dialog.target_person.add_event_ref(ref_t2)

        rendered_events = []
        birth_rows_seen = 0
        arrow_keys = []
        dialog._make_arrow.side_effect = lambda key, label: arrow_keys.append(key)

        def record_diff_line(label, a, b, show_label, is_left):
            nonlocal birth_rows_seen
            if is_left and label == "Birth":
                birth_rows_seen += 1
                if birth_rows_seen > 1:
                    rendered_events.append((a, b))
            return a

        dialog._format_diff_line = record_diff_line

        from gramps.gui.gwizard import gwizardmergedialog

        with (
            patch.object(gwizardmergedialog.Gtk, "Label", return_value=Mock()),
            patch.object(gwizardmergedialog.Gtk, "Separator", return_value=Mock()),
            patch.object(gwizardmergedialog, "create_diff_cell", return_value=Mock()),
        ):
            GWizardMergeDialog._populate_fields(dialog)
        # The empty Birth events on both sides are not listed at all.
        self.assertEqual(
            rendered_events,
            [("1864-10-02 Luderup", "estimated 1864-10-02 Luderup")],
        )
        self.assertIn("birth_event", arrow_keys)
        self.assertNotIn("event:s_empty", arrow_keys)

    def test_empty_events_are_not_listed(self) -> None:
        """
        Events with no date, place or description are left out of both
        the merge dialog's grouping and the compare window's lines.
        """
        from gramps.gui.gwizard.gwizardcompare import GWizardCompareWindow

        dated = Date()
        dated.set(
            Date.QUAL_NONE, Date.MOD_NONE, Date.CAL_GREGORIAN, (0, 0, 1900, False)
        )
        text_only = Date()
        text_only.set_as_text("about the war")
        described = _mock_event("described", "Burial")
        described.get_description.return_value = "Old churchyard"
        placed = _mock_event("placed", "Census")
        placed.get_place_handle.return_value = "P0001"
        events = {
            "empty": _mock_event("empty", "Birth"),
            "blank_desc": _mock_event("blank_desc", "Death"),
            "dated": _mock_event("dated", "Birth", dated),
            "text_only": _mock_event("text_only", "Residence", text_only),
            "described": described,
            "placed": placed,
        }
        events["blank_desc"].get_description.return_value = "  \n "
        db = Mock()
        db.get_event_from_handle.side_effect = events.__getitem__
        person = Mock()
        person.get_event_ref_list.return_value = [Mock(ref=h) for h in events]

        self.assertEqual(
            person_events_by_type(db, person),
            {
                "Birth": ["dated"],
                "Residence": ["text_only"],
                "Burial": ["described"],
                "Census": ["placed"],
            },
        )

        window = Mock(spec=GWizardCompareWindow)
        window._format_event_line = lambda event, db: event.handle
        self.assertEqual(
            GWizardCompareWindow._event_lines(window, person, db),
            ["dated", "described", "placed", "text_only"],
        )


if __name__ == "__main__":
    unittest.main()
