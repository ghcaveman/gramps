#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Grizard Merge Dialog
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
Modal merge dialog for Grizard.

Shows the current family tree on the left and the incoming GEDCOM tree on
the right, with a per-field arrow button (<=) between them for any
data that does not match exactly. Clicking Apply runs the gen-side
GedGrizard._apply for the collected field resolutions.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
from typing import Any

# -------------------------------------------------------------------------
#
# GTK/Gnome modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk
from gi.repository import GLib

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.lib import Person
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.display.name import displayer as name_displayer
from gramps.gen.grizard.gedcom import GedGrizard
from gramps.gen.fs.utils.attributes import get_fsftid

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)

_ = glocale.translation.gettext


# -------------------------------------------------------------------------
#
# GrizardMergeDialog
#
# -------------------------------------------------------------------------
class GrizardMergeDialog(Gtk.Dialog):
    """
    Modal dialog to review one source/target person pair and move
    fields between the two trees before committing to the database.
    """

    def __init__(
        self,
        dbstate: Any,
        grizard: GedGrizard,
        source_handle: str,
        target_handle: str,
        parent: Gtk.Window | None = None,
    ) -> None:
        """
        Build the modal merge dialog for one source/target person pair.

        :param dbstate: Active Gramps DB state manager (target tree).
        :param grizard: A GedGrizard whose connect/load steps already ran.
        :param source_handle: Handle of the person in the GEDCOM (source) DB.
        :param target_handle: Handle of the person in the target DB.
        :param parent: Parent window (translates to a modal dialog).
        """
        Gtk.Dialog.__init__(self, transient_for=parent, modal=True)
        self.set_title(_("Grizard Merge"))
        self.set_default_size(620, 850)
        self.set_border_width(6)

        self.grizard = grizard
        self.source_db = grizard.context.get("source_db")
        self.target_db = dbstate.db
        self.source_handle = source_handle
        self.target_handle = target_handle
        self.source_person = self.source_db.get_person_from_handle(source_handle)
        self.target_person = self.target_db.get_person_from_handle(target_handle)

        self._resolutions: dict[str, str] = {}

        box = self.get_content_area()
        self._people_row = self._build_people_row()
        box.pack_start(self._people_row, False, False, 0)
        self._fields_table = self._build_fields_table()
        box.pack_start(self._fields_table, True, True, 0)

        bar = self.get_action_area()
        btn_cancel = Gtk.Button(label=_("Cancel"))
        btn_cancel.connect("clicked", self.cb_cancel)
        bar.pack_start(btn_cancel, False, False, 0)
        btn_apply = Gtk.Button(label=_("Apply"))
        btn_apply.get_style_context().add_class("suggested-action")
        btn_apply.connect("clicked", self.cb_apply)
        bar.pack_start(btn_apply, False, False, 0)

        self.show_all()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_people_row(self) -> Gtk.Widget:
        """
        Build the top bar with the two person names and a single
        right-pointing arrow (data always flows GEDCOM -> Gramps).
        """
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        left = Gtk.Label(label=name_displayer.display(self.target_person))
        left.set_xalign(0.0)
        dash = Gtk.Label(label=_("\u2192"))
        dash.set_xalign(0.5)
        right = Gtk.Label(label=name_displayer.display(self.source_person))
        right.set_xalign(1.0)
        row.pack_start(left, True, True, 0)
        row.pack_start(dash, False, False, 0)
        row.pack_start(right, True, True, 0)
        return row

    def _build_fields_table(self) -> Gtk.Widget:
        """
        Build the scrollable grid of field rows with arrow buttons.
        """
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        scrolled.add(self._grid)
        self._row_index = 0
        self._populate_fields()
        return scrolled

    def _populate_fields(self) -> None:
        """
        Fill the grid with the four sections used by the GrizardCompare
        details panel (Individual Details, Family Relations, Children,
        Events & Other Records), each row showing the target value on the
        left and the source value on the right with an arrow between.
        """
        left = self.target_person
        right = self.source_person
        td = self.target_db
        sd = self.source_db
        grid = self._grid

        def header(text: str, xalign: float = 0.0) -> Gtk.Label:
            lab = Gtk.Label()
            lab.set_xalign(xalign)
            lab.set_markup("<b>%s</b>" % GLib.markup_escape_text(text))
            return lab

        # Column headers at the top (match the compare window panel titles).
        grid.attach(header(_("Current Family Tree")), 0, 0, 1, 1)
        grid.attach(Gtk.Label(label=""), 1, 0, 1, 1)
        grid.attach(header(_("Incoming GEDCOM Tree")), 2, 0, 1, 1)
        self._row_index = 1

        def section(title: str) -> None:
            """Add a bold section heading and a separator beneath it."""
            grid.attach(header(title, xalign=0.5), 0, self._row_index, 3, 1)
            self._row_index += 1
            grid.attach(
                Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
                0,
                self._row_index,
                3,
                1,
            )
            self._row_index += 1

        def add_row(
            key: str | None,
            label: str,
            left_val: Any,
            right_val: Any,
            is_nullable_identity: bool = False,
            show_label: bool = True,
        ) -> None:
            ls = "" if left_val is None else str(left_val)
            rs = "" if right_val is None else str(right_val)
            same = ls == rs
            if is_nullable_identity:
                same = bool(ls) == bool(rs)
            left_text = _("%s: %s") % (label, ls) if show_label else ls
            right_text = _("%s: %s") % (label, rs) if show_label else rs
            left_cell = Gtk.Label(label=left_text)
            left_cell.set_xalign(0.0)
            left_cell.set_line_wrap(True)
            right_cell = Gtk.Label(label=right_text)
            right_cell.set_xalign(1.0)
            right_cell.set_line_wrap(True)
            btn = None
            if key is not None:
                if is_nullable_identity:
                    if rs and not ls:
                        btn = self._make_arrow(key, label)
                elif not same and rs:
                    btn = self._make_arrow(key, label)
            gap = btn if btn is not None else Gtk.Label(label="")
            grid.attach(left_cell, 0, self._row_index, 1, 1)
            grid.attach(gap, 1, self._row_index, 1, 1)
            grid.attach(right_cell, 2, self._row_index, 1, 1)
            self._row_index += 1

        def event_groups(db: Any, person: Person) -> dict[str, list[tuple[str, str]]]:
            """
            Group a person's non-birth/death events by type string,
            returning a list of (event_handle, display_line) per type.
            """
            groups: dict[str, list[tuple[str, str]]] = {}
            for ref in person.get_event_ref_list():
                try:
                    event = db.get_event_from_handle(ref.ref)
                    if not event:
                        continue
                    etype = str(event.get_type())
                    if etype in ("_PPEXCLUDE", "_FSLINK", "Birth", "Death"):
                        continue
                    groups.setdefault(etype, []).append(
                        (event.handle, self._event_line_from(db, event))
                    )
                except Exception:
                    continue
            return groups

        def rel_items(db: Any, person: Person, role: str) -> list[Person]:
            if role == "spouse":
                return self._spouses(db, person)
            if role == "child":
                return self._children(db, person)
            return self._parents(db, person, role)

        genders = {
            Person.MALE: _("Male"),
            Person.FEMALE: _("Female"),
            Person.OTHER: _("Other"),
            Person.UNKNOWN: _("Unknown"),
        }

        # ---------- Individual Details ----------
        section(_("Individual Details"))
        add_row(
            "given_name",
            _("Given Name"),
            left.get_primary_name().first_name,
            right.get_primary_name().first_name,
        )
        left_surname = (
            left.get_primary_name().surname_list[0].surname
            if left.get_primary_name().surname_list
            else ""
        )
        right_surname = (
            right.get_primary_name().surname_list[0].surname
            if right.get_primary_name().surname_list
            else ""
        )
        add_row("surname", _("Surname"), left_surname, right_surname)
        add_row(
            "gender",
            _("Gender"),
            genders.get(left.get_gender(), _("Unknown")),
            genders.get(right.get_gender(), _("Unknown")),
        )
        l_b = self._event_for(td, left, "birth")
        r_b = self._event_for(sd, right, "birth")
        add_row(
            "birth_event",
            _("Birth"),
            self._event_display_from(l_b),
            self._event_display_from(r_b),
        )
        l_d = self._event_for(td, left, "death")
        r_d = self._event_for(sd, right, "death")
        add_row(
            "death_event",
            _("Death"),
            self._event_display_from(l_d),
            self._event_display_from(r_d),
        )
        add_row(
            "fsid",
            _("FamilySearch ID"),
            get_fsftid(left),
            get_fsftid(right),
            is_nullable_identity=True,
        )

        # ---------- Family Relations ----------
        section(_("Family Relations"))
        for role, title in (
            ("father", _("Father")),
            ("mother", _("Mother")),
            ("spouse", _("Spouse")),
        ):
            t_items = rel_items(td, left, role)
            s_items = rel_items(sd, right, role)
            count = max(len(t_items), len(s_items))
            for i in range(count):
                t_rel = t_items[i] if i < len(t_items) else None
                s_rel = s_items[i] if i < len(s_items) else None
                t_text = self._related_text(t_rel, td) if t_rel else ""
                s_text = self._related_text(s_rel, sd) if s_rel else ""
                key = (role + ":" + s_rel.handle) if s_rel else None
                add_row(key, title, t_text, s_text)

        # ---------- Children ----------
        section(_("Children"))
        t_items = rel_items(td, left, "child")
        s_items = rel_items(sd, right, "child")
        count = max(len(t_items), len(s_items))
        for i in range(count):
            t_rel = t_items[i] if i < len(t_items) else None
            s_rel = s_items[i] if i < len(s_items) else None
            t_text = self._related_text(t_rel, td) if t_rel else ""
            s_text = self._related_text(s_rel, sd) if s_rel else ""
            key = ("child:" + s_rel.handle) if s_rel else None
            add_row(key, "", t_text, s_text, show_label=False)

        # ---------- Events & Other Records ----------
        section(_("Events & Other Records"))
        left_groups = event_groups(td, left)
        right_groups = event_groups(sd, right)
        for etype in dict.fromkeys(list(left_groups) + list(right_groups)):
            t_items = left_groups.get(etype, [])
            s_items = right_groups.get(etype, [])
            count = max(len(t_items), len(s_items))
            for i in range(count):
                t_handle, t_line = t_items[i] if i < len(t_items) else (None, "")
                s_handle, s_line = s_items[i] if i < len(s_items) else (None, "")
                key = ("event:" + s_handle) if s_handle else None
                add_row(key, etype, t_line, s_line)

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    def _event_year(self, db: Any, person: Person, kind: str) -> str:
        """
        Return the year of the person's birth/death event, or ''.
        ``kind`` is 'birth' or 'death'.
        """
        try:
            _date, _place, handle = self._event_for(db, person, kind)
            if not handle:
                return ""
            event = db.get_event_from_handle(handle)
            if event:
                return str(event.get_date_object().get_year() or "")
        except Exception:
            pass
        return ""

    def _event_for(
        self, db: Any, person: Person, kind: str
    ) -> tuple[str, str | None, str | None]:
        """
        Return (date_display, place_name, event_handle) for the person's
        birth/death event, or ('', None, None). ``kind`` is 'birth' or
        'death'.
        """
        if kind == "birth":
            ref = person.get_birth_ref()
        else:
            ref = person.get_death_ref()
        if not ref:
            return "", None, None
        try:
            event = db.get_event_from_handle(ref.ref)
            if not event:
                return "", None, None
            date_str = glocale.date_displayer.display(event.get_date_object())
            place = ""
            ph = event.get_place_handle()
            if ph:
                place_obj = db.get_place_from_handle(ph)
                if place_obj:
                    place = place_obj.get_name().get_value()
            return date_str, place or None, event.handle
        except Exception:
            return "", None, None

    def _event_display_from(self, event: tuple[str, str | None, str | None]) -> str:
        """Format a birth/death event tuple for display."""
        date_str, place, _handle = event
        return ", ".join(p for p in (date_str, place or "") if p)

    def _event_line_from(self, db: Any, event: Any) -> str:
        """Return ``date, place`` for an event, trimming empty parts."""
        date_str = glocale.date_displayer.display(event.get_date_object())
        place = ""
        ph = event.get_place_handle()
        if ph:
            try:
                place_obj = db.get_place_from_handle(ph)
                if place_obj:
                    place = place_obj.get_name().get_value() or ""
            except Exception:
                pass
        return ", ".join(p for p in (date_str, place) if p)

    def _vitals_text(self, person: Person, db: Any) -> str:
        """
        Return the compact vital summary for a person in the form
        ``b.<year> (<birth place>) d.<year>``, or ''.
        """
        birth_year = self._event_year(db, person, "birth")
        death_year = self._event_year(db, person, "death")
        birth_place = ""
        try:
            _d, birth_place, _h = self._event_for(db, person, "birth")
        except Exception:
            pass
        birth_part = ""
        if birth_year:
            birth_part = "b. %s" % birth_year
            if birth_place:
                birth_part += " (%s)" % birth_place
        parts = [
            p for p in (birth_part, "d. %s" % death_year if death_year else "") if p
        ]
        return " ".join(parts)

    def _related_text(self, person: Person, db: Any) -> str:
        """
        Return ``<display name> (b.<year> ... d.<year>)`` for a related
        person, omitting the parenthetical when no vitals are known.
        """
        name = name_displayer.display(person)
        vitals = self._vitals_text(person, db)
        return "%s (%s)" % (name, vitals) if vitals else name

    def _parents(self, db: Any, person: Person, role: str) -> list[Person]:
        out = []
        seen = set()
        for fh in person.get_parent_family_handle_list():
            fam = db.get_family_from_handle(fh)
            if not fam:
                continue
            handle = (
                fam.get_father_handle() if role == "father" else fam.get_mother_handle()
            )
            if handle and handle not in seen:
                seen.add(handle)
                person_obj = db.get_person_from_handle(handle)
                if person_obj:
                    out.append(person_obj)
        return out

    def _spouses(self, db: Any, person: Person) -> list[Person]:
        out = []
        seen = set()
        for fh in person.get_family_handle_list():
            fam = db.get_family_from_handle(fh)
            if not fam:
                continue
            fh_ = fam.get_father_handle()
            mh = fam.get_mother_handle()
            handle = mh if fh_ == person.handle else fh_
            if handle and handle not in seen:
                seen.add(handle)
                person_obj = db.get_person_from_handle(handle)
                if person_obj:
                    out.append(person_obj)
        return out

    def _children(self, db: Any, person: Person) -> list[Person]:
        out = []
        seen = set()
        for fh in person.get_family_handle_list():
            fam = db.get_family_from_handle(fh)
            if not fam:
                continue
            for child_ref in fam.get_child_ref_list():
                handle = child_ref.ref
                if handle in seen:
                    continue
                seen.add(handle)
                child = db.get_person_from_handle(handle)
                if child:
                    out.append(child)
        return out

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def _make_arrow(self, key: str, label: str) -> Gtk.Button:
        """
        Build a left-pointing arrow button that moves the source value for
        this field into the current family tree when clicked.
        """
        btn = Gtk.Button(label=_("<="))
        btn.set_tooltip_text(_("Move %s to current family tree") % label)
        btn.connect("clicked", self.cb_field_clicked, key)
        return btn

    def cb_field_clicked(self, button: Gtk.Button, key: str) -> None:
        """
        Record the user's choice to take the source value for this field.
        """
        button.set_label(_("\u2713"))
        button.set_sensitive(False)
        self._resolutions[key] = "source"

    def cb_apply(self, _button: Gtk.Button) -> None:
        """
        Run the apply step for the collected resolutions and close.
        """
        try:
            self.grizard.run_step(
                "apply",
                source_person_handle=self.source_handle,
                target_person_handle=self.target_handle,
                resolutions=self._resolutions,
            )
        except Exception as e:  # pragma: no cover
            LOG.exception("Apply failed: %s", e)
        self.response(Gtk.ResponseType.OK)
        self.destroy()

    def cb_cancel(self, _button: Gtk.Button) -> None:
        """Close the dialog without applying anything."""
        self.response(Gtk.ResponseType.CANCEL)
        self.destroy()
