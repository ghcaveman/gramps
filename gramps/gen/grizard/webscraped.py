#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  The Gramps Project
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
Grizard implementation for importing and merging web scraped or search data.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import copy
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.db.base import DbWriteBase
from gramps.gen.db.txn import DbTxn
from gramps.gen.db.utils import make_database
from gramps.gen.types import PersonHandle
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.lib import (
    Person,
    Name,
    Event,
    EventRef,
    EventType,
    EventRoleType,
    Place,
    Citation,
    Source,
    Note,
    Surname,
)

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .grizard import GrizardBase

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)


# ------------------------------------------------------------
#
# WebScrapedGrizard
#
# ------------------------------------------------------------
class WebScrapedGrizard(GrizardBase):
    """
    Concrete Grizard implementation for importing data from raw search/scraped dicts.
    """

    def __init__(self, db: DbWriteBase) -> None:
        """
        Initialize WebScrapedGrizard.

        :param db: The target database to merge data into.
        """
        super().__init__(db)

    def _connect(self, **kwargs: Any) -> bool:
        """
        Configure connection details by supplying scraped search results.

        :param scraped_results: List of dictionaries of scraped records.
        :type scraped_results: list[dict[str, Any]]
        :returns: True if results list is provided.
        :rtype: bool
        """
        scraped_results = kwargs.get("scraped_results")
        if scraped_results is None:
            LOG.error("No scraped_results provided.")
            return False

        self.context["scraped_results"] = scraped_results
        return True

    def _load(self, **kwargs: Any) -> list[Person]:
        """
        Build an in-memory SQLite database populated with the scraped results.

        :returns: A list of Person objects loaded from the scraped data.
        :rtype: list[Person]
        """
        scraped_results = self.context.get("scraped_results")
        if scraped_results is None:
            raise ValueError(
                "No scraped_results found in context. Call connect step first."
            )

        # Create temporary in-memory database
        source_db = make_database("sqlite")
        source_db.load(":memory:")
        self.context["source_db"] = source_db

        people: list[Person] = []

        with DbTxn(_("Populate Web Scraped Grizard"), source_db) as trans:
            for item in scraped_results:
                person = Person()

                # Primary name
                name = Name()
                name.first_name = item.get("first_name", "")

                surn = Surname()
                surn.surname = item.get("last_name", "")
                name.add_surname(surn)
                person.set_primary_name(name)

                # Gender
                gender_str = item.get("gender", "U")
                person.set_gender(Person.Gender.from_str(gender_str))

                # Note reference
                notes_list = item.get("notes", [])
                for note_text in notes_list:
                    note = Note()
                    note.set(note_text)
                    source_db.add_note(note, trans)
                    person.add_note_handle(note.handle)

                # Citations & Sources
                citation_list = item.get("citations", [])
                for cit_item in citation_list:
                    # Create parent Source if specified
                    src_title = cit_item.get("source_title")
                    src_handle = None
                    if src_title:
                        # Check if source with same title already exists in in-memory db
                        for sh in source_db.iter_source_handles():
                            s = source_db.get_source_from_handle(sh)
                            if s and s.title == src_title:
                                src_handle = sh
                                break

                        if not src_handle:
                            source_obj = Source()
                            source_obj.title = src_title
                            source_db.add_source(source_obj, trans)
                            src_handle = source_obj.handle

                    citation_obj = Citation()
                    citation_obj.set_reference_handle(src_handle)
                    citation_obj.page = cit_item.get("page", "")

                    cit_note = cit_item.get("citation_note")
                    if cit_note:
                        note = Note()
                        note.set(cit_note)
                        source_db.add_note(note, trans)
                        citation_obj.add_note_handle(note.handle)

                    source_db.add_citation(citation_obj, trans)
                    person.add_citation_handle(citation_obj.handle)

                # Events: Birth & Death
                for evt_type_name, key_prefix in [
                    ("birth", "birth"),
                    ("death", "death"),
                ]:
                    evt_date = item.get(f"{key_prefix}_date")
                    evt_place = item.get(f"{key_prefix}_place")

                    if evt_date or evt_place:
                        event = Event()
                        event.type.set(
                            EventType.BIRTH
                            if evt_type_name == "birth"
                            else EventType.DEATH
                        )

                        if evt_date:
                            event.date_val.set_as_text(evt_date)

                        if evt_place:
                            # Create Place object
                            place = Place()
                            place.title = evt_place
                            source_db.add_place(place, trans)
                            event.set_place_handle(place.handle)

                        source_db.add_event(event, trans)

                        ref = EventRef()
                        ref.ref = event.handle
                        ref.set_role(EventRoleType.PRIMARY)
                        person.add_event_ref(ref)

                source_db.add_person(person, trans)
                people.append(person)

        return people

    def _match(self, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Match scraped results to target database candidates.
        """
        source_person_handle = kwargs.get("source_person_handle")
        if not source_person_handle:
            raise ValueError("source_person_handle parameter is required.")

        source_db = self.context.get("source_db")
        if not source_db:
            raise ValueError("Source database is not loaded.")

        source_person = source_db.get_person_from_handle(source_person_handle)
        if not source_person:
            raise ValueError(f"Source person not found: {source_person_handle}")

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
                    birth_ref = target_person.get_birth_ref()
                    birth_yr = ""
                    if birth_ref:
                        birth_evt = self.db.get_event_from_handle(birth_ref.ref)
                        if birth_evt:
                            birth_yr = str(birth_evt.get_date_object().get_year() or "")

                    candidates.append(
                        {
                            "handle": target_handle,
                            "display": name_str,
                            "birth_year": birth_yr,
                            "score": f"{int(score * 100)}%",
                        }
                    )
            except Exception:
                pass

        return candidates
