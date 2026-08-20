#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Devin
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
GEDCOM implementation of the Grizard import framework.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import copy
import logging
import os
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import import_as_dict
from gramps.gen.types import PersonHandle
from gramps.gen.user import User
from gramps.gen.lib import (
    Person,
    Event,
    EventRef,
    Place,
    Name,
    EventRoleType,
    EventType,
)
from gramps.gen.soundex import soundex
from gramps.gen.const import GRAMPS_LOCALE as glocale

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .grizard import GrizardBase, GrizardCompareRow, CandidateMatcher

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)

_ = glocale.translation.gettext


# ------------------------------------------------------------
#
# GedGrizard
#
# ------------------------------------------------------------
class GedGrizard(GrizardBase):
    """
    Concrete Grizard implementation for importing data from GEDCOM (.ged) files.
    """

    def __init__(self, db: DbWriteBase) -> None:
        """
        Initialize the GedGrizard.

        :param db: The target database to merge data into.
        """
        super().__init__(db)

    def _connect(self, **kwargs: Any) -> bool:
        """
        Configure connection details by supplying a path to a GEDCOM file.

        :param gedcom_path: Path to the GEDCOM file.
        :type gedcom_path: str
        :returns: True if path is valid and file exists.
        :rtype: bool
        """
        gedcom_path = kwargs.get("gedcom_path", "")
        if not gedcom_path or not os.path.isfile(gedcom_path):
            LOG.error("Invalid GEDCOM path: %s", gedcom_path)
            return False

        self.context["gedcom_path"] = gedcom_path
        return True

    def _load(self, **kwargs: Any) -> list[Person]:
        """
        Load GEDCOM data into an in-memory dictionary database for analysis.

        :returns: A list of Person objects loaded from the file.
        :rtype: list[Person]
        """
        gedcom_path = self.context.get("gedcom_path")
        if not gedcom_path:
            raise ValueError("No GEDCOM path configured. Call connect step first.")

        user = User()
        source_db = import_as_dict(gedcom_path, user)
        if not source_db:
            raise RuntimeError("Failed to import GEDCOM file.")

        self.context["source_db"] = source_db

        people: list[Person] = []
        for handle in source_db.iter_person_handles():
            person = source_db.get_person_from_handle(handle)
            if person:
                people.append(person)

        return people

    def _match(self, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Find potential matching persons in the target database.

        :param source_person_handle: Handle of the person in the source database.
        :type source_person_handle: str
        :returns: List of target candidates with details.
        :rtype: list[dict[str, Any]]
        """
        source_person_handle = kwargs.get("source_person_handle")
        if not source_person_handle:
            raise ValueError("source_person_handle parameter is required.")

        source_db = self.context.get("source_db")
        if not source_db:
            raise ValueError("Source database is not loaded.")

        source_person = source_db.get_person_from_handle(source_person_handle)
        if not source_person:
            raise ValueError(
                f"Source person not found for handle: {source_person_handle}"
            )

        matcher = CandidateMatcher(self.db)
        matches = matcher.find_matches(source_person, threshold=0.5)

        candidates: list[dict[str, Any]] = []
        for target_handle, score in matches:
            try:
                target_person = self.db.get_person_from_handle(target_handle)
                if target_person:
                    name_str = glocale.translation.gettext(
                        target_person.get_primary_name().get_name()
                    )
                    # Use formatted birth year if available
                    birth_ref = target_person.get_birth_ref()
                    birth_yr = ""
                    if birth_ref:
                        birth_evt = self.db.get_event_from_handle(birth_ref.ref)
                        if birth_evt:
                            birth_yr = str(birth_evt.get_date_object().get_year() or "")

                    candidates.append(
                        {
                            "handle": target_handle,
                            "score": score,
                            "name": name_str,
                            "birth_year": birth_yr,
                        }
                    )
            except Exception:
                continue

        return candidates

    def _compare(self, **kwargs: Any) -> list[GrizardCompareRow]:
        """
        Generate comparative side-by-side rows between a source person and target person.

        :param source_person_handle: Handle of the person in the source database.
        :type source_person_handle: str
        :param target_person_handle: Handle of the person in the target database.
        :type target_person_handle: PersonHandle
        :returns: List of comparison rows.
        :rtype: list[GrizardCompareRow]
        """
        source_person_handle = kwargs.get("source_person_handle")
        target_person_handle = kwargs.get("target_person_handle")

        if not source_person_handle or not target_person_handle:
            raise ValueError(
                "Both source_person_handle and target_person_handle are required."
            )

        source_db = self.context.get("source_db")
        if not source_db:
            raise ValueError("Source database is not loaded.")

        s_person = source_db.get_person_from_handle(source_person_handle)
        t_person = self.db.get_person_from_handle(target_person_handle)

        if not s_person or not t_person:
            raise ValueError("Source or target person record not found.")

        rows: list[GrizardCompareRow] = []

        # Helper for statuses
        def get_status(s_val: str, t_val: str) -> str:
            if not s_val and not t_val:
                return "match"
            if s_val and not t_val:
                return "source_only"
            if t_val and not s_val:
                return "target_only"
            if s_val.strip().lower() == t_val.strip().lower():
                return "match"
            return "differ"

        # 1. Compare Given Name
        s_given = s_person.get_primary_name().first_name
        t_given = t_person.get_primary_name().first_name
        rows.append(
            GrizardCompareRow(
                status=get_status(s_given, t_given),
                field=_("Given Name"),
                source_val=s_given,
                target_val=t_given,
                field_type="given_name",
            )
        )

        # 2. Compare Surnames
        matcher = CandidateMatcher(self.db)
        s_surname = matcher.get_surnames(s_person.get_primary_name())
        t_surname = matcher.get_surnames(t_person.get_primary_name())
        rows.append(
            GrizardCompareRow(
                status=get_status(s_surname, t_surname),
                field=_("Surname"),
                source_val=s_surname,
                target_val=t_surname,
                field_type="surname",
            )
        )

        # 3. Compare Gender
        def format_gender(gender_val: int) -> str:
            genders = {
                Person.MALE: _("Male"),
                Person.FEMALE: _("Female"),
                Person.OTHER: _("Other"),
                Person.UNKNOWN: _("Unknown"),
            }
            return genders.get(gender_val, _("Unknown"))

        s_gender_str = format_gender(s_person.get_gender())
        t_gender_str = format_gender(t_person.get_gender())
        rows.append(
            GrizardCompareRow(
                status=get_status(s_gender_str, t_gender_str),
                field=_("Gender"),
                source_val=s_gender_str,
                target_val=t_gender_str,
                field_type="gender",
            )
        )

        # Helper to extract event details
        def get_event_details(
            db: DbWriteBase, person: Person, event_type_val: int
        ) -> tuple[str, str, str]:
            for ref in person.get_event_ref_list():
                try:
                    event = db.get_event_from_handle(ref.ref)
                    if event and event.get_type() == event_type_val:
                        dt_str = glocale.date_displayer.display(event.get_date_object())
                        pl_handle = event.get_place_handle()
                        pl_title = ""
                        if pl_handle:
                            place = db.get_place_from_handle(pl_handle)
                            if place:
                                pl_title = place.get_title()
                        return dt_str, pl_title, event.handle
                except Exception:
                    continue
            return "", "", ""

        # 4. Compare Birth Event
        s_birth_dt, s_birth_pl, s_birth_h = get_event_details(
            source_db, s_person, EventType.BIRTH
        )
        t_birth_dt, t_birth_pl, t_birth_h = get_event_details(
            self.db, t_person, EventType.BIRTH
        )

        s_birth_val = f"{s_birth_dt} ({s_birth_pl})" if s_birth_pl else s_birth_dt
        t_birth_val = f"{t_birth_dt} ({t_birth_pl})" if t_birth_pl else t_birth_dt

        rows.append(
            GrizardCompareRow(
                status=get_status(s_birth_val, t_birth_val),
                field=_("Birth"),
                source_val=s_birth_val,
                target_val=t_birth_val,
                source_date=s_birth_dt,
                target_date=t_birth_dt,
                field_type="birth_event",
                extra_data={"source_handle": s_birth_h, "target_handle": t_birth_h},
            )
        )

        # 5. Compare Death Event
        s_death_dt, s_death_pl, s_death_h = get_event_details(
            source_db, s_person, EventType.DEATH
        )
        t_death_dt, t_death_pl, t_death_h = get_event_details(
            self.db, t_person, EventType.DEATH
        )

        s_death_val = f"{s_death_dt} ({s_death_pl})" if s_death_pl else s_death_dt
        t_death_val = f"{t_death_dt} ({t_death_pl})" if t_death_pl else t_death_dt

        rows.append(
            GrizardCompareRow(
                status=get_status(s_death_val, t_death_val),
                field=_("Death"),
                source_val=s_death_val,
                target_val=t_death_val,
                source_date=s_death_dt,
                target_date=t_death_dt,
                field_type="death_event",
                extra_data={"source_handle": s_death_h, "target_handle": t_death_h},
            )
        )

        return rows

    def _apply(self, **kwargs: Any) -> bool:
        """
        Apply resolutions by updating an existing person or adding as a new person in target db.

        :param source_person_handle: Handle of the person in the source database.
        :type source_person_handle: str
        :param target_person_handle: Handle of the person in target db, or None to add new.
        :type target_person_handle: PersonHandle | None
        :param resolutions: Dictionary of field resolutions (e.g. {'birth_event': 'source'}).
        :type resolutions: dict[str, str]
        :returns: True if successfully applied and committed.
        :rtype: bool
        """
        source_person_handle = kwargs.get("source_person_handle")
        target_person_handle = kwargs.get("target_person_handle")
        resolutions = kwargs.get("resolutions", {})

        if not source_person_handle:
            raise ValueError("source_person_handle is required.")

        source_db = self.context.get("source_db")
        if not source_db:
            raise ValueError("Source database is not loaded.")

        s_person = source_db.get_person_from_handle(source_person_handle)
        if not s_person:
            raise ValueError("Source person not found.")

        # Helper to get/create place
        def get_or_create_place(s_pl_handle: str | None, trans: Any) -> str | None:
            if not s_pl_handle:
                return None
            try:
                s_place = source_db.get_place_from_handle(s_pl_handle)
                if not s_place:
                    return None

                # Check if place with same title already exists in target
                title = s_place.get_title()
                for h in self.db.iter_place_handles():
                    t_pl = self.db.get_place_from_handle(h)
                    if t_pl and t_pl.get_title() == title:
                        return h

                new_place = copy.deepcopy(s_place)
                self.db.add_place(new_place, trans)
                return new_place.handle
            except Exception:
                pass
            return None

        # Helper to copy event
        def copy_event(s_evt_handle: str | None, trans: Any) -> str | None:
            if not s_evt_handle:
                return None
            try:
                s_event = source_db.get_event_from_handle(s_evt_handle)
                if not s_event:
                    return None

                new_event = copy.deepcopy(s_event)
                new_place = get_or_create_place(s_event.get_place_handle(), trans)
                new_event.set_place_handle(new_place)
                self.db.add_event(new_event, trans)
                return new_event.handle
            except Exception:
                pass
            return None

        with DbTxn(_("Grizard GEDCOM Merge"), self.db) as trans:
            if target_person_handle is None:
                # Add as entirely new person
                new_person = copy.deepcopy(s_person)
                # Copy birth event if exists
                s_birth_ref = s_person.get_birth_ref()
                if s_birth_ref:
                    t_birth_h = copy_event(s_birth_ref.ref, trans)
                    if t_birth_h:
                        new_birth_ref = EventRef()
                        new_birth_ref.ref = t_birth_h
                        new_birth_ref.set_role(EventRoleType.PRIMARY)
                        # We must clear the existing event ref list and set the correct birth ref
                        # In Gramps, birth/death references reside in event_ref_list.
                        # set_birth_ref internally manages the ref.
                        new_person.set_birth_ref(new_birth_ref)

                s_death_ref = s_person.get_death_ref()
                if s_death_ref:
                    t_death_h = copy_event(s_death_ref.ref, trans)
                    if t_death_h:
                        new_death_ref = EventRef()
                        new_death_ref.ref = t_death_h
                        new_death_ref.set_role(EventRoleType.PRIMARY)
                        new_person.set_death_ref(new_death_ref)

                self.db.add_person(new_person, trans)
                LOG.info("Added new person: %s", new_person.handle)
            else:
                # Merge into existing target person
                t_person = self.db.get_person_from_handle(target_person_handle)
                if not t_person:
                    return False

                # Apply choices
                # 1. Given Name
                if resolutions.get("given_name") == "source":
                    t_person.get_primary_name().first_name = (
                        s_person.get_primary_name().first_name
                    )

                # 2. Surname
                if resolutions.get("surname") == "source":
                    # Clear target surname list and copy source list
                    t_person.get_primary_name().surname_list = copy.deepcopy(
                        s_person.get_primary_name().surname_list
                    )

                # 3. Gender
                if resolutions.get("gender") == "source":
                    t_person.set_gender(s_person.get_gender())

                # Helper to extract event details to match comparison
                def get_source_event_handle(
                    person: Person, event_type_val: int
                ) -> str | None:
                    for ref in person.get_event_ref_list():
                        try:
                            event = source_db.get_event_from_handle(ref.ref)
                            if event and event.get_type() == event_type_val:
                                return event.handle
                        except Exception:
                            continue
                    return None

                # 4. Birth Event
                if resolutions.get("birth_event") == "source":
                    s_birth_h = get_source_event_handle(s_person, EventType.BIRTH)
                    t_birth_h = copy_event(s_birth_h, trans)
                    if t_birth_h:
                        new_birth_ref = EventRef()
                        new_birth_ref.ref = t_birth_h
                        new_birth_ref.set_role(EventRoleType.PRIMARY)
                        t_person.set_birth_ref(new_birth_ref)

                # 5. Death Event
                if resolutions.get("death_event") == "source":
                    s_death_h = get_source_event_handle(s_person, EventType.DEATH)
                    t_death_h = copy_event(s_death_h, trans)
                    if t_death_h:
                        new_death_ref = EventRef()
                        new_death_ref.ref = t_death_h
                        new_death_ref.set_role(EventRoleType.PRIMARY)
                        t_person.set_death_ref(new_death_ref)

                self.db.commit_person(t_person, trans)
                LOG.info("Merged changes into person: %s", t_person.handle)

        return True
