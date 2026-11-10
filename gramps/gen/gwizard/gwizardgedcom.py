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
GEDCOM implementation of the GWizard import framework.
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
from gramps.gen.db.utils import import_as_dict, make_database
from gramps.gen.config import config
from gramps.gen.plug import BasePluginManager
from gramps.gen.types import PersonHandle
from gramps.gen.user import User
from gramps.gen.lib import (
    Person,
    Event,
    EventRef,
    Place,
    Name,
    Family,
    ChildRef,
    Attribute,
    EventRoleType,
    EventType,
)
from gramps.gen.soundex import soundex
from gramps.gen.display.place import displayer as place_displayer
from gramps.gen.utils.id import create_id
from gramps.gen.const import GRAMPS_LOCALE as glocale

# -------------------------------------------------------------------------
#
# Local imports
#
# -------------------------------------------------------------------------
from .gwizard_base import (
    GWizardBase,
    GWizardCompareRow,
    CandidateMatcher,
    surname_prefix_text,
    surname_text,
    safe_get_event,
    safe_get_family,
    safe_get_person,
    safe_get_place,
    safe_get_source,
    vital_event_ref,
    SOURCE_AMBIGUOUS,
    SourceMatcher,
    normalize_source_text,
    source_signature,
)

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)

_ = glocale.translation.gettext


# ------------------------------------------------------------
#
# GedGWizard
#
# ------------------------------------------------------------
class GedGWizard(GWizardBase):
    """
    Concrete GWizard implementation for importing data from GEDCOM (.ged)
    and Gramps XML (.gramps, .xml) files.
    """

    # File extensions (without dot) treated as Gramps XML even though no
    # ``xml`` importer is registered. ``import_as_dict`` dispatches purely
    # on extension, so a bare ``.xml`` holding Gramps XML would otherwise
    # fail to load.
    GRAMPS_XML_EXTENSIONS = frozenset({"gramps", "xml"})

    # Minimum score for linking a relative (father, mother, spouse, child)
    # when the compare window has not already paired the person. Matches
    # the compare window's default so both agree on who is the same person.
    RELATIVE_MATCH_THRESHOLD = 0.7

    def __init__(self, db: DbWriteBase) -> None:
        """
        Initialize the GedGWizard.

        :param db: The target database to merge data into.
        """
        super().__init__(db)

    def _is_gramps_xml_file(self, path: str) -> bool:
        """
        Return True if the file looks like Gramps XML.

        Files with a ``.gramps`` extension are trusted by extension (the
        registered ``gramps`` importer only reads Gramps XML). Anything
        else is sniffed: the first bytes must contain a ``<database``
        element in the Gramps XML namespace.
        """
        extension = os.path.splitext(os.path.basename(path))[1][1:].lower()
        if extension == "gramps":
            return True
        try:
            with open(path, "rb") as handle:
                head = handle.read(4096)
        except OSError:
            return False
        if b"<database" not in head:
            return False
        return b"gramps-project.org/xml" in head

    def _load_gramps_xml(self, path: str, user: User) -> DbWriteBase | None:
        """
        Load Gramps XML from any extension into an in-memory database.

        Routes the registered ``gramps`` importer plugin at the file in
        place (no temp copy); only falls back to ``import_as_dict`` when
        the plugin manager has no importers registered (e.g. bare
        ``gen``-level unit contexts).
        """
        db = make_database("sqlite")
        db.load(":memory:")
        db.set_feature("skip-import-additions", True)
        db.set_prefixes(
            config.get("preferences.iprefix"),
            config.get("preferences.oprefix"),
            config.get("preferences.fprefix"),
            config.get("preferences.sprefix"),
            config.get("preferences.cprefix"),
            config.get("preferences.pprefix"),
            config.get("preferences.eprefix"),
            config.get("preferences.rprefix"),
            config.get("preferences.nprefix"),
            config.get("preferences.tprefix"),
            config.get("preferences.mprefix"),
        )
        pmgr = BasePluginManager.get_instance()
        for pdata in pmgr.get_reg_importers():
            if pdata.extension == "gramps":
                mod = pmgr.load_plugin(pdata)
                if not mod:
                    break
                import_function = getattr(mod, pdata.import_function)
                try:
                    results = import_function(db, path, user)
                except Exception:
                    LOG.exception("Failed to import Gramps XML file: %s", path)
                    db.close()
                    return None
                if results is None:
                    db.close()
                    return None
                return db
        # No importers registered: fall back to the standard dispatcher,
        # which returns None for unknown extensions.
        db.close()
        return import_as_dict(path, user)

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
        Load source data into an in-memory dictionary database for analysis.

        Supports GEDCOM (``.ged``) and Gramps XML (``.gramps``, plus a
        bare ``.xml`` holding Gramps XML, routed to the ``gramps``
        importer without any temp copy).

        :returns: A list of Person objects loaded from the file.
        :rtype: list[Person]
        """
        gedcom_path = self.context.get("gedcom_path")
        if not gedcom_path:
            raise ValueError("No GEDCOM path configured. Call connect step first.")

        user = User()
        source_db: DbWriteBase | None = None
        extension = os.path.splitext(os.path.basename(gedcom_path))[1][1:].lower()
        if extension in self.GRAMPS_XML_EXTENSIONS or self._is_gramps_xml_file(
            gedcom_path
        ):
            source_db = self._load_gramps_xml(gedcom_path, user)
        else:
            source_db = import_as_dict(gedcom_path, user)
        if not source_db:
            raise RuntimeError("Failed to import GEDCOM file.")

        self.context["source_db"] = source_db
        # Handles copied for an earlier file mean nothing for this one.
        self.context["handle_map"] = {}
        self.context.pop("place_index", None)

        people: list[Person] = []
        for handle in source_db.iter_person_handles():
            person = safe_get_person(source_db, handle)
            if person:
                people.append(person)

        return people

    def _match(self, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Find potential matching persons in the target database.

        :param source_person_handle: Handle of the person in the source database.
        :type source_person_handle: str
        :param threshold: Minimum matching score required to include a candidate.
        :type threshold: float
        :returns: List of target candidates with details.
        :rtype: list[dict[str, Any]]
        """
        source_person_handle = kwargs.get("source_person_handle")
        if not source_person_handle:
            raise ValueError("source_person_handle parameter is required.")
        try:
            threshold = float(kwargs.get("threshold", 0.5))
        except (TypeError, ValueError):
            threshold = 0.5

        source_db = self.context.get("source_db")
        if not source_db:
            raise ValueError("Source database is not loaded.")

        source_person = safe_get_person(source_db, source_person_handle)
        if not source_person:
            raise ValueError(
                f"Source person not found for handle: {source_person_handle}"
            )

        matcher = CandidateMatcher(self.db)
        matches = matcher.find_matches(
            source_person, threshold=threshold, source_db=source_db
        )

        candidates: list[dict[str, Any]] = []
        for target_handle, score in matches:
            try:
                target_person = safe_get_person(self.db, target_handle)
                if target_person:
                    name_str = glocale.translation.gettext(
                        target_person.get_primary_name().get_name()
                    )
                    # Use formatted birth year if available
                    birth_ref = vital_event_ref(self.db, target_person, "birth")
                    birth_yr = ""
                    if birth_ref:
                        birth_evt = safe_get_event(self.db, birth_ref.ref)
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

    def _compare(self, **kwargs: Any) -> list[GWizardCompareRow]:
        """
        Generate comparative side-by-side rows between a source person and target person.

        :param source_person_handle: Handle of the person in the source database.
        :type source_person_handle: str
        :param target_person_handle: Handle of the person in the target database.
        :type target_person_handle: PersonHandle
        :returns: List of comparison rows.
        :rtype: list[GWizardCompareRow]
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

        s_person = safe_get_person(source_db, source_person_handle)
        t_person = safe_get_person(self.db, target_person_handle)

        if not s_person or not t_person:
            raise ValueError("Source or target person record not found.")

        rows: list[GWizardCompareRow] = []

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
            GWizardCompareRow(
                status=get_status(s_given, t_given),
                field=_("Given Name"),
                source_val=s_given,
                target_val=t_given,
                field_type="given_name",
            )
        )

        # 2. Compare Surnames
        s_surname = surname_text(s_person.get_primary_name())
        t_surname = surname_text(t_person.get_primary_name())
        rows.append(
            GWizardCompareRow(
                status=get_status(s_surname, t_surname),
                field=_("Surname"),
                source_val=s_surname,
                target_val=t_surname,
                field_type="surname",
            )
        )

        # 2b. Compare Surname Prefixes (GEDCOM SPFX, e.g. "Vrow")
        s_prefix = surname_prefix_text(s_person.get_primary_name())
        t_prefix = surname_prefix_text(t_person.get_primary_name())
        rows.append(
            GWizardCompareRow(
                status=get_status(s_prefix, t_prefix),
                field=_("Surname Prefix"),
                source_val=s_prefix,
                target_val=t_prefix,
                field_type="surname_prefix",
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
            GWizardCompareRow(
                status=get_status(s_gender_str, t_gender_str),
                field=_("Gender"),
                source_val=s_gender_str,
                target_val=t_gender_str,
                field_type="gender",
            )
        )

        # Helper to extract event details for the primary event of a type.
        # The primary (birth_ref/death_ref, else first of that type) feeds
        # the mergeable top row; every other event of that type is listed
        # under Events & Other Records by the merge dialog.
        def get_event_details(
            db: DbWriteBase, person: Person, event_type_val: int
        ) -> tuple[str, str, str]:
            kind = "birth" if event_type_val == EventType.BIRTH else "death"
            try:
                primary = vital_event_ref(db, person, kind)
            except Exception:
                primary = None
            ordered_refs: list[Any] = []
            if primary is not None:
                ordered_refs.append(primary)
            try:
                for ref in person.get_event_ref_list():
                    if primary is None or ref.ref != primary.ref:
                        ordered_refs.append(ref)
            except Exception:
                pass
            for ref in ordered_refs:
                try:
                    event = safe_get_event(db, ref.ref)
                    if event and event.get_type() == event_type_val:
                        dt_str = glocale.date_displayer.display(event.get_date_object())
                        pl_handle = event.get_place_handle()
                        pl_title = ""
                        if pl_handle:
                            place = safe_get_place(db, pl_handle)
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
            GWizardCompareRow(
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
            GWizardCompareRow(
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

        # 6. Compare extra (non-primary) Birth and Death events.
        # These are the events beyond the primary record and are surfaced as
        # separate rows so the Diff list correctly flags a person when an
        # alternate vital event exists on either side.
        def get_event_details_for_event(
            db: DbWriteBase, event: Event
        ) -> tuple[str, str]:
            dt_str = glocale.date_displayer.display(event.get_date_object())
            place = ""
            ph = event.get_place_handle()
            if ph:
                place_obj = safe_get_place(db, ph)
                if place_obj:
                    place = place_obj.get_title()
            return dt_str, place

        def get_extra_events(
            db: DbWriteBase,
            person: Person,
            event_type_val: int,
            primary_handle: str | None,
        ) -> list[tuple[str, Event]]:
            extra: list[tuple[str, Event]] = []
            for ref in person.get_event_ref_list():
                try:
                    event = safe_get_event(db, ref.ref)
                    if not event:
                        continue
                    if event.get_type() != event_type_val:
                        continue
                    if ref.ref == primary_handle:
                        continue
                    extra.append((ref.ref, event))
                except Exception:
                    continue
            return extra

        # Extra Birth events
        s_birth_extra = get_extra_events(
            source_db, s_person, EventType.BIRTH, s_birth_h
        )
        t_birth_extra = get_extra_events(self.db, t_person, EventType.BIRTH, t_birth_h)
        for s_ref, s_ev in s_birth_extra:
            s_dt, s_pl = get_event_details_for_event(source_db, s_ev)
            s_val = f"{s_dt} ({s_pl})" if s_pl else s_dt
            rows.append(
                GWizardCompareRow(
                    status="source_only",
                    field=_("Birth"),
                    source_val=s_val,
                    target_val="",
                    source_date=s_dt,
                    target_date="",
                    field_type="birth_event",
                    extra_data={"source_handle": s_ref, "target_handle": ""},
                )
            )

        for t_ref, t_ev in t_birth_extra:
            t_dt, t_pl = get_event_details_for_event(self.db, t_ev)
            t_val = f"{t_dt} ({t_pl})" if t_pl else t_dt
            rows.append(
                GWizardCompareRow(
                    status="target_only",
                    field=_("Birth"),
                    source_val="",
                    target_val=t_val,
                    source_date="",
                    target_date=t_dt,
                    field_type="birth_event",
                    extra_data={"source_handle": "", "target_handle": t_ref},
                )
            )

        # Extra Death events
        s_death_extra = get_extra_events(
            source_db, s_person, EventType.DEATH, s_death_h
        )
        t_death_extra = get_extra_events(self.db, t_person, EventType.DEATH, t_death_h)
        for s_ref, s_ev in s_death_extra:
            s_dt, s_pl = get_event_details_for_event(source_db, s_ev)
            s_val = f"{s_dt} ({s_pl})" if s_pl else s_dt
            rows.append(
                GWizardCompareRow(
                    status="source_only",
                    field=_("Death"),
                    source_val=s_val,
                    target_val="",
                    source_date=s_dt,
                    target_date="",
                    field_type="death_event",
                    extra_data={"source_handle": s_ref, "target_handle": ""},
                )
            )

        for t_ref, t_ev in t_death_extra:
            t_dt, t_pl = get_event_details_for_event(self.db, t_ev)
            t_val = f"{t_dt} ({t_pl})" if t_pl else t_dt
            rows.append(
                GWizardCompareRow(
                    status="target_only",
                    field=_("Death"),
                    source_val="",
                    target_val=t_val,
                    source_date="",
                    target_date=t_dt,
                    field_type="death_event",
                    extra_data={"source_handle": "", "target_handle": t_ref},
                )
            )

        # 7. Compare generic (non-Birth/non-Death) events. These are the
        # "other" personal events (custom events and the like). They are
        # paired by identical description first, then any remaining events
        # are matched by ordinal position. This ensures a person who has a
        # different number of generic events on each side -- for example two
        # events in the GEDCOM file but three in the database -- is flagged
        # as a difference rather than being silently ignored.
        def generic_event_label(db: DbWriteBase, event: Event) -> str:
            """Return a short display value for a generic event."""
            desc = event.get_description() or ""
            dt_str = ""
            try:
                dt_str = glocale.date_displayer.display(event.get_date_object())
            except Exception:
                dt_str = ""
            label = desc or str(event.get_type())
            if dt_str:
                label = f"{label} ({dt_str})"
            return label

        def collect_generic_events(
            db: DbWriteBase, person: Person
        ) -> list[tuple[str, Event]]:
            """Return (handle, Event) pairs for non-Birth/Death events."""
            result: list[tuple[str, Event]] = []
            for ref in person.get_event_ref_list():
                try:
                    event = safe_get_event(db, ref.ref)
                except Exception:
                    continue
                if not event:
                    continue
                if event.get_type() in (EventType.BIRTH, EventType.DEATH):
                    continue
                result.append((ref.ref, event))
            return result

        def _norm(value: str) -> str:
            return value.strip().lower()

        s_generic = collect_generic_events(source_db, s_person)
        t_generic = collect_generic_events(self.db, t_person)

        # First pass: pair events whose display values are identical.
        matched_target_idx: set[int] = set()
        s_unmatched: list[tuple[str, str]] = []
        for s_ref, s_ev in s_generic:
            s_label = generic_event_label(source_db, s_ev)
            found: int | None = None
            for idx, (t_ref, t_ev) in enumerate(t_generic):
                if idx in matched_target_idx:
                    continue
                if _norm(generic_event_label(self.db, t_ev)) == _norm(s_label):
                    found = idx
                    break
            if found is None:
                s_unmatched.append((s_ref, s_label))
            else:
                matched_target_idx.add(found)
                t_ref, t_ev = t_generic[found]
                rows.append(
                    GWizardCompareRow(
                        status="match",
                        field=_("Event"),
                        source_val=s_label,
                        target_val=generic_event_label(self.db, t_ev),
                        field_type="event",
                        extra_data={"source_handle": s_ref, "target_handle": t_ref},
                    )
                )

        # Second pass: pair leftover source and target events by position.
        # Unequal counts therefore surface as differ/source_only/target_only.
        t_remaining: list[tuple[str, str]] = [
            (t_ref, generic_event_label(self.db, t_ev))
            for idx, (t_ref, t_ev) in enumerate(t_generic)
            if idx not in matched_target_idx
        ]
        pair_count = max(len(s_unmatched), len(t_remaining))
        for i in range(pair_count):
            s_ref = ""
            s_label = ""
            t_ref = ""
            t_label = ""
            if i < len(s_unmatched):
                s_ref, s_label = s_unmatched[i]
            if i < len(t_remaining):
                t_ref, t_label = t_remaining[i]
            rows.append(
                GWizardCompareRow(
                    status=get_status(s_label, t_label),
                    field=_("Event"),
                    source_val=s_label,
                    target_val=t_label,
                    field_type="event",
                    extra_data={"source_handle": s_ref, "target_handle": t_ref},
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

        s_person = safe_get_person(source_db, source_person_handle)
        if not s_person:
            raise ValueError("Source person not found.")

        source_matcher = SourceMatcher(self.db)

        def fresh_gramps_id(obj: Any, has_gramps_id: Any) -> None:
            """Clear a Gramps ID the target already uses so a new one is assigned."""
            if obj.gramps_id and has_gramps_id(obj.gramps_id):
                obj.set_gramps_id("")

        # ------------------------------------------------------------------
        # Copying the objects an incoming person refers to (notes, media,
        # repositories, sources, citations and places).
        #
        # ``handle_map`` records, per kind of object, which target handle
        # stands for each incoming handle. It lives in the session context,
        # so an object reached from several people or several merges is
        # copied once. A handle is never taken to mean "same object" just
        # because the target uses it too: a file exported from the same tree
        # can hold different content under a shared handle. An equal handle
        # is reused only when the content is equivalent; otherwise the copy
        # gets a fresh handle.
        # ------------------------------------------------------------------
        handle_map: dict[str, dict[str, str]] = self.context.setdefault(
            "handle_map", {}
        )

        def mapped_handle(kind: str, s_handle: str, exists: Any) -> str | None:
            """Return the target handle already chosen for ``s_handle``."""
            t_handle = handle_map.get(kind, {}).get(s_handle)
            if t_handle and exists(t_handle):
                return t_handle
            return None

        def remember(kind: str, s_handle: str, t_handle: str) -> str:
            """Record that ``s_handle`` is represented by ``t_handle``."""
            handle_map.setdefault(kind, {})[s_handle] = t_handle
            return t_handle

        def unused_handle(obj: Any, exists: Any) -> None:
            """Give ``obj`` a new handle when the target already uses its own."""
            if not obj.handle or exists(obj.handle):
                obj.set_handle(create_id())

        def copy_note_list(obj: Any, trans: Any) -> None:
            """Replace the notes of ``obj`` with copies in the target."""
            obj.set_note_list(
                [
                    handle
                    for handle in (
                        copy_note(note, trans) for note in obj.get_note_list()
                    )
                    if handle
                ]
            )

        def copy_media_refs(obj: Any, trans: Any) -> None:
            """Point the media references of ``obj`` at copies in the target."""
            kept = []
            for mref in obj.get_media_list():
                new_handle = copy_media(mref.get_reference_handle(), trans)
                if new_handle:
                    mref.set_reference_handle(new_handle)
                    kept.append(mref)
            obj.set_media_list(kept)

        def copy_citation_list(obj: Any, trans: Any) -> None:
            """Replace the citations of ``obj`` with copies in the target."""
            obj.set_citation_list(
                [
                    handle
                    for handle in (
                        copy_citation(citation, trans)
                        for citation in obj.get_citation_list()
                    )
                    if handle
                ]
            )

        def source_fields(source: Any) -> tuple[str, str, str]:
            """Return the fields that make two sources the same source."""
            return (
                normalize_source_text(source.get_title()),
                normalize_source_text(source.get_author()),
                normalize_source_text(source.get_publication_info()),
            )

        # Places are matched on their title, or on the displayed name when
        # the title is empty (it usually is for hierarchical places).
        def place_key(db: Any, place: Any) -> str:
            title = (place.get_title() or "").strip()
            if title:
                return title
            try:
                return place_displayer.display(db, place).strip()
            except Exception:  # pylint: disable=broad-except
                return place.get_name().get_value().strip()

        def place_index() -> dict[str, str]:
            """Return {place key: handle} for the target, built on first use."""
            index = self.context.get("place_index")
            if index is None:
                index = {}
                for t_place in self.db.iter_places():
                    key = place_key(self.db, t_place)
                    if key:
                        index.setdefault(key, t_place.handle)
                self.context["place_index"] = index
            return index

        def find_target_place(key: str) -> str | None:
            if not key:
                return None
            t_handle = place_index().get(key)
            if t_handle:
                t_place = safe_get_place(self.db, t_handle)
                if t_place is not None and place_key(self.db, t_place) == key:
                    return t_handle
            return None

        places_in_progress: set[str] = set()

        def get_or_create_place(s_pl_handle: str | None, trans: Any) -> str | None:
            if not s_pl_handle:
                return None
            hit = mapped_handle("place", s_pl_handle, self.db.has_place_handle)
            if hit:
                return hit
            if s_pl_handle in places_in_progress:
                return None  # the incoming places enclose each other in a loop
            places_in_progress.add(s_pl_handle)
            try:
                s_place = safe_get_place(source_db, s_pl_handle)
                if not s_place:
                    return None
                key = place_key(source_db, s_place)
                if key and self.db.has_place_handle(s_pl_handle):
                    t_place = safe_get_place(self.db, s_pl_handle)
                    if t_place is not None and place_key(self.db, t_place) == key:
                        return remember("place", s_pl_handle, s_pl_handle)
                found = find_target_place(key)
                if found:
                    return remember("place", s_pl_handle, found)

                new_place = copy.deepcopy(s_place)
                unused_handle(new_place, self.db.has_place_handle)
                copy_note_list(new_place, trans)
                copy_media_refs(new_place, trans)
                copy_citation_list(new_place, trans)
                enclosing = []
                for pref in new_place.get_placeref_list():
                    new_parent = get_or_create_place(pref.ref, trans)
                    if new_parent:
                        pref.ref = new_parent
                        enclosing.append(pref)
                new_place.set_placeref_list(enclosing)
                fresh_gramps_id(new_place, self.db.has_place_gramps_id)
                self.db.add_place(new_place, trans)
                new_key = place_key(self.db, new_place)
                if new_key:
                    place_index().setdefault(new_key, new_place.handle)
                return remember("place", s_pl_handle, new_place.handle)
            except Exception:
                LOG.warning(
                    "Could not copy %s from the incoming file; it was skipped",
                    "place",
                    exc_info=True,
                )
            finally:
                places_in_progress.discard(s_pl_handle)
            return None

        # Helper to copy note
        def copy_note(s_note_handle: str | None, trans: Any) -> str | None:
            if not s_note_handle:
                return None
            hit = mapped_handle("note", s_note_handle, self.db.has_note_handle)
            if hit:
                return hit
            try:
                s_note = source_db.get_note_from_handle(s_note_handle)
                if not s_note:
                    return None
                if self.db.has_note_handle(s_note_handle):
                    t_note = self.db.get_note_from_handle(s_note_handle)
                    if t_note.get_type() == s_note.get_type() and (
                        t_note.get() == s_note.get()
                    ):
                        return remember("note", s_note_handle, s_note_handle)
                new_note = copy.deepcopy(s_note)
                unused_handle(new_note, self.db.has_note_handle)
                fresh_gramps_id(new_note, self.db.has_note_gramps_id)
                self.db.add_note(new_note, trans)
                return remember("note", s_note_handle, new_note.handle)
            except Exception:
                LOG.warning(
                    "Could not copy %s from the incoming file; it was skipped",
                    "note",
                    exc_info=True,
                )
            return None

        # Helper to copy media
        def copy_media(s_media_handle: str | None, trans: Any) -> str | None:
            if not s_media_handle:
                return None
            hit = mapped_handle("media", s_media_handle, self.db.has_media_handle)
            if hit:
                return hit
            try:
                s_media = source_db.get_media_from_handle(s_media_handle)
                if not s_media:
                    return None
                if self.db.has_media_handle(s_media_handle):
                    t_media = self.db.get_media_from_handle(s_media_handle)
                    if t_media.get_path() == s_media.get_path():
                        return remember("media", s_media_handle, s_media_handle)
                new_media = copy.deepcopy(s_media)
                unused_handle(new_media, self.db.has_media_handle)
                copy_note_list(new_media, trans)
                copy_citation_list(new_media, trans)
                fresh_gramps_id(new_media, self.db.has_media_gramps_id)
                self.db.add_media(new_media, trans)
                return remember("media", s_media_handle, new_media.handle)
            except Exception:
                LOG.warning(
                    "Could not copy %s from the incoming file; it was skipped",
                    "media",
                    exc_info=True,
                )
            return None

        # Helper to copy repository
        def copy_repository(s_repo_handle: str | None, trans: Any) -> str | None:
            if not s_repo_handle:
                return None
            hit = mapped_handle("repo", s_repo_handle, self.db.has_repository_handle)
            if hit:
                return hit
            try:
                s_repo = source_db.get_repository_from_handle(s_repo_handle)
                if not s_repo:
                    return None
                if self.db.has_repository_handle(s_repo_handle):
                    t_repo = self.db.get_repository_from_handle(s_repo_handle)
                    if t_repo.get_name() == s_repo.get_name() and (
                        t_repo.get_type() == s_repo.get_type()
                    ):
                        return remember("repo", s_repo_handle, s_repo_handle)
                new_repo = copy.deepcopy(s_repo)
                unused_handle(new_repo, self.db.has_repository_handle)
                copy_note_list(new_repo, trans)
                fresh_gramps_id(new_repo, self.db.has_repository_gramps_id)
                self.db.add_repository(new_repo, trans)
                return remember("repo", s_repo_handle, new_repo.handle)
            except Exception:
                LOG.warning(
                    "Could not copy %s from the incoming file; it was skipped",
                    "repo",
                    exc_info=True,
                )
            return None

        # Helper to copy source
        def copy_source(s_source_handle: str | None, trans: Any) -> str | None:
            if not s_source_handle:
                return None
            hit = mapped_handle("source", s_source_handle, self.db.has_source_handle)
            if hit:
                return hit
            try:
                s_source = safe_get_source(source_db, s_source_handle)
                if not s_source:
                    return None
                if self.db.has_source_handle(s_source_handle):
                    t_source = safe_get_source(self.db, s_source_handle)
                    if t_source is not None and source_fields(
                        t_source
                    ) == source_fields(s_source):
                        return remember("source", s_source_handle, s_source_handle)
                existing_handle, status = source_matcher.find(s_source)
                if existing_handle:
                    LOG.info(
                        "Source %r matches existing source %s; reusing it",
                        s_source.get_title(),
                        existing_handle,
                    )
                    return remember("source", s_source_handle, existing_handle)
                if status == SOURCE_AMBIGUOUS:
                    LOG.warning(
                        "Source %r matches several sources in the family tree; "
                        "adding it as a new source",
                        s_source.get_title(),
                    )
                new_source = copy.deepcopy(s_source)
                unused_handle(new_source, self.db.has_source_handle)
                copy_note_list(new_source, trans)
                copy_media_refs(new_source, trans)
                kept_repos = []
                for rref in new_source.get_reporef_list():
                    new_rh = copy_repository(rref.get_reference_handle(), trans)
                    if new_rh:
                        rref.set_reference_handle(new_rh)
                        kept_repos.append(rref)
                new_source.set_reporef_list(kept_repos)

                fresh_gramps_id(new_source, self.db.has_source_gramps_id)
                self.db.add_source(new_source, trans)
                source_matcher.add(new_source)
                return remember("source", s_source_handle, new_source.handle)
            except Exception:
                LOG.warning(
                    "Could not copy %s from the incoming file; it was skipped",
                    "source",
                    exc_info=True,
                )
            return None

        # Helper to copy citation
        def copy_citation(s_citation_handle: str | None, trans: Any) -> str | None:
            if not s_citation_handle:
                return None
            hit = mapped_handle(
                "citation", s_citation_handle, self.db.has_citation_handle
            )
            if hit:
                return hit
            try:
                s_citation = source_db.get_citation_from_handle(s_citation_handle)
                if not s_citation:
                    return None
                if self.db.has_citation_handle(s_citation_handle):
                    s_sig = citation_signature(source_db, s_citation_handle)
                    if s_sig is not None and s_sig == citation_signature(
                        self.db, s_citation_handle
                    ):
                        return remember("citation", s_citation_handle, s_citation_handle)
                new_citation = copy.deepcopy(s_citation)
                unused_handle(new_citation, self.db.has_citation_handle)
                copy_note_list(new_citation, trans)
                copy_media_refs(new_citation, trans)
                new_sh = copy_source(new_citation.get_reference_handle(), trans)
                if not new_sh:
                    LOG.warning(
                        "Citation %s: its source could not be copied; skipped",
                        s_citation_handle,
                    )
                    return None
                new_citation.set_reference_handle(new_sh)
                fresh_gramps_id(new_citation, self.db.has_citation_gramps_id)
                self.db.add_citation(new_citation, trans)
                return remember("citation", s_citation_handle, new_citation.handle)
            except Exception:
                LOG.warning(
                    "Could not copy %s from the incoming file; it was skipped",
                    "citation",
                    exc_info=True,
                )
            return None

        # Helper to resolve references on an Event
        def resolve_references_for_event(new_event: Any, trans: Any) -> None:
            new_notes = []
            for nh in new_event.get_note_list():
                new_nh = copy_note(nh, trans)
                if new_nh:
                    new_notes.append(new_nh)
            new_event.set_note_list(new_notes)

            for mref in new_event.media_list:
                new_mh = copy_media(mref.get_reference_handle(), trans)
                if new_mh:
                    mref.set_reference_handle(new_mh)

            new_citations = []
            for ch in new_event.get_citation_list():
                new_ch = copy_citation(ch, trans)
                if new_ch:
                    new_citations.append(new_ch)
            new_event.set_citation_list(new_citations)

        # Helper to resolve references on a Person
        def resolve_references_for_person(new_person: Any, trans: Any) -> None:
            new_notes = []
            for nh in new_person.get_note_list():
                new_nh = copy_note(nh, trans)
                if new_nh:
                    new_notes.append(new_nh)
            new_person.set_note_list(new_notes)

            for mref in new_person.media_list:
                new_mh = copy_media(mref.get_reference_handle(), trans)
                if new_mh:
                    mref.set_reference_handle(new_mh)

            new_citations = []
            for ch in new_person.get_citation_list():
                new_ch = copy_citation(ch, trans)
                if new_ch:
                    new_citations.append(new_ch)
            new_person.set_citation_list(new_citations)

        # Helper to copy event
        def copy_event(s_evt_handle: str | None, trans: Any) -> str | None:
            if not s_evt_handle:
                return None
            try:
                s_event = safe_get_event(source_db, s_evt_handle)
                if not s_event:
                    return None

                new_event = copy.deepcopy(s_event)
                if new_event.handle and self.db.has_event_handle(new_event.handle):
                    new_event.set_handle(None)
                new_place = get_or_create_place(s_event.get_place_handle(), trans)
                new_event.set_place_handle(new_place)
                resolve_references_for_event(new_event, trans)
                fresh_gramps_id(new_event, self.db.has_event_gramps_id)
                self.db.add_event(new_event, trans)
                return new_event.handle
            except Exception:
                LOG.warning(
                    "Could not copy %s from the incoming file; it was skipped",
                    "event",
                    exc_info=True,
                )
            return None

        def citation_signature(db: Any, citation_handle: str) -> tuple[str, ...] | None:
            """
            Return a (source key, page) tuple for a citation.

            The source key is the matcher's (title, author, publication
            info) key, so two citations compare equal when they cite the
            same source and page even though their handles differ.
            Returns None when the citation cannot be read.
            """
            try:
                citation = db.get_citation_from_handle(citation_handle)
                if not citation:
                    return None
                source = safe_get_source(db, citation.get_reference_handle())
                ident = (source_signature(source) if source else None) or (
                    "handle",
                    "",
                    citation.get_reference_handle() or "",
                )
                return tuple(ident) + (normalize_source_text(citation.get_page()),)
            except Exception:
                LOG.warning(
                    "Could not read citation %s", citation_handle, exc_info=True
                )
                return None

        def copy_new_citations(owner: Any, s_owner: Any, trans: Any) -> None:
            """
            Add the incoming object's citations to ``owner``, skipping any
            that ``owner`` already has (same source title, author and page).
            """
            existing = {
                citation_signature(self.db, h) for h in owner.get_citation_list()
            }
            existing.discard(None)
            for s_handle in s_owner.get_citation_list():
                signature = citation_signature(source_db, s_handle)
                if signature is not None and signature in existing:
                    continue
                new_handle = copy_citation(s_handle, trans)
                if not new_handle:
                    LOG.warning("Citation %s could not be copied; skipped", s_handle)
                    continue
                owner.add_citation(new_handle)
                if signature is not None:
                    existing.add(signature)

        def remap_citations_notes(obj: Any) -> None:
            """Copy the citations and notes of ``obj`` into the target tree."""
            if hasattr(obj, "get_citation_list"):
                obj.set_citation_list(
                    [
                        handle
                        for handle in (
                            copy_citation(citation, trans)
                            for citation in obj.get_citation_list()
                        )
                        if handle
                    ]
                )
            if hasattr(obj, "get_note_list"):
                obj.set_note_list(
                    [
                        handle
                        for handle in (
                            copy_note(note, trans) for note in obj.get_note_list()
                        )
                        if handle
                    ]
                )

        def copy_event_ref(
            s_event_handle: str | None,
            t_event_handle: str,
            trans: Any,
            role: Any = None,
        ) -> EventRef:
            """
            Return an EventRef to the copied event ``t_event_handle``.

            The source person's reference to ``s_event_handle`` is copied
            so its role, privacy, attributes and notes survive. ``role``
            overrides the copied role (birth and death are always Primary).
            """
            new_ref = EventRef()
            for ref in s_person.get_event_ref_list():
                if ref.ref == s_event_handle:
                    new_ref = copy.deepcopy(ref)
                    break
            new_ref.ref = t_event_handle
            if role is not None:
                new_ref.set_role(role)
            remap_citations_notes(new_ref)
            for attribute in new_ref.get_attribute_list():
                remap_citations_notes(attribute)
            return new_ref

        with DbTxn(_("GWizard Data Merge"), self.db) as trans:
            if target_person_handle is None:
                # Add as entirely new person
                new_person = copy.deepcopy(s_person)
                if new_person.handle and self.db.has_person_handle(new_person.handle):
                    new_person.set_handle(None)
                if new_person.gramps_id and self.db.has_person_gramps_id(
                    new_person.gramps_id
                ):
                    new_person.set_gramps_id("")
                resolve_references_for_person(new_person, trans)

                birth_idx = new_person.birth_ref_index
                death_idx = new_person.death_ref_index
                new_event_refs: list[Any] = []
                new_birth_idx = new_death_idx = -1
                for idx, event_ref in enumerate(new_person.get_event_ref_list()):
                    target_event_handle = copy_event(event_ref.ref, trans)
                    if not target_event_handle:
                        continue
                    event_ref.ref = target_event_handle
                    remap_citations_notes(event_ref)
                    for attribute in event_ref.get_attribute_list():
                        remap_citations_notes(attribute)
                    if idx == birth_idx:
                        new_birth_idx = len(new_event_refs)
                    if idx == death_idx:
                        new_death_idx = len(new_event_refs)
                    new_event_refs.append(event_ref)
                new_person.set_event_ref_list(new_event_refs)
                new_person.birth_ref_index = new_birth_idx
                new_person.death_ref_index = new_death_idx

                for name in [
                    new_person.get_primary_name()
                ] + new_person.get_alternate_names():
                    remap_citations_notes(name)
                for attribute in new_person.get_attribute_list():
                    remap_citations_notes(attribute)
                for address in new_person.get_address_list():
                    remap_citations_notes(address)

                new_person.set_family_handle_list([])
                new_person.set_parent_family_handle_list([])
                new_person.set_person_ref_list([])
                new_person.set_lds_ord_list([])
                new_person.set_tag_list([])

                self.db.add_person(new_person, trans)
                LOG.info("Added new person: %s", new_person.handle)
            else:
                # Merge into existing target person
                t_person = safe_get_person(self.db, target_person_handle)
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

                # 2b. Surname Prefix (a GEDCOM SPFX value lives on the
                # Surname itself, so only the prefixes of the surnames
                # present on both sides are copied; the whole list is
                # already copied when the surname row was chosen)
                if (
                    resolutions.get("surname_prefix") == "source"
                    and resolutions.get("surname") != "source"
                ):
                    s_list = s_person.get_primary_name().surname_list
                    t_list = t_person.get_primary_name().surname_list
                    for idx, t_surn in enumerate(t_list):
                        if idx < len(s_list):
                            t_surn.set_prefix(s_list[idx].get_prefix())

                # 2c. Citations on the primary name and on the person
                if resolutions.get("name_sources") == "source":
                    copy_new_citations(
                        t_person.get_primary_name(), s_person.get_primary_name(), trans
                    )
                if resolutions.get("person_sources") == "source":
                    copy_new_citations(t_person, s_person, trans)

                # 3. Gender
                if resolutions.get("gender") == "source":
                    t_person.set_gender(s_person.get_gender())

                # Helper to extract the primary event handle to match comparison:
                # the birth_ref/death_ref when set, else the first event of
                # that type. Alternate births/deaths merge via "event:" keys.
                def get_source_event_handle(
                    person: Person, event_type_val: int
                ) -> str | None:
                    kind = "birth" if event_type_val == EventType.BIRTH else "death"
                    try:
                        primary = vital_event_ref(source_db, person, kind)
                    except Exception:
                        primary = None
                    if primary is not None:
                        return primary.ref
                    return None

                # 4. Birth Event
                if resolutions.get("birth_event") == "source":
                    s_birth_h = get_source_event_handle(s_person, EventType.BIRTH)
                    t_birth_h = copy_event(s_birth_h, trans)
                    if t_birth_h:
                        t_person.set_birth_ref(
                            copy_event_ref(
                                s_birth_h, t_birth_h, trans, EventRoleType.PRIMARY
                            )
                        )

                # 5. Death Event
                if resolutions.get("death_event") == "source":
                    s_death_h = get_source_event_handle(s_person, EventType.DEATH)
                    t_death_h = copy_event(s_death_h, trans)
                    if t_death_h:
                        t_person.set_death_ref(
                            copy_event_ref(
                                s_death_h, t_death_h, trans, EventRoleType.PRIMARY
                            )
                        )

                # Helpers for field-level items beyond the standard rows
                def best_target_person(s_handle: str) -> str | None:
                    """
                    Find the target person that best matches the source
                    person with the given handle.
                    """
                    # The compare window records its one-to-one pairing (and
                    # any "Not a Match" rejections as None); use it so a
                    # relative is linked to the person the user sees paired.
                    pair_map = self.context.get("pair_map") or {}
                    if s_handle in pair_map:
                        paired = pair_map[s_handle]
                        if paired and safe_get_person(self.db, paired) is not None:
                            return paired
                        return None
                    rel = safe_get_person(source_db, s_handle)
                    if not rel:
                        return None
                    matches = CandidateMatcher(self.db).find_matches(
                        rel,
                        threshold=self.RELATIVE_MATCH_THRESHOLD,
                        source_db=source_db,
                    )
                    if not matches:
                        return None
                    matches.sort(key=lambda m: m[1], reverse=True)
                    return matches[0][0]

                def ensure_parent_family(trans: Any) -> Family:
                    """
                    Return the target person's first parent family,
                    creating it (with the target person as child) if
                    needed.
                    """
                    for fh in t_person.get_parent_family_handle_list():
                        fam = safe_get_family(self.db, fh)
                        if fam:
                            return fam
                    fam = Family()
                    child_ref = ChildRef()
                    child_ref.ref = t_person.handle
                    fam.add_child_ref(child_ref)
                    self.db.add_family(fam, trans)
                    t_person.add_parent_family_handle(fam.handle)
                    return fam

                def source_fs_id() -> str:
                    """
                    Return the FamilySearch ID of the source person from
                    the _FSFTID attribute, falling back to the _FSLINK
                    event URL tail.
                    """
                    for attr in s_person.get_attribute_list():
                        try:
                            if str(attr.get_type()) == "_FSFTID":
                                return attr.get_value() or ""
                        except Exception:
                            continue
                    for ref in s_person.get_event_ref_list():
                        try:
                            event = safe_get_event(source_db, ref.ref)
                            if event and str(event.get_type()) == "_FSLINK":
                                desc = event.get_description() or ""
                                tail = desc.rstrip("/").split("/")[-1]
                                if tail and tail != "details":
                                    return tail
                        except Exception:
                            continue
                    return ""

                s_birth_h = get_source_event_handle(s_person, EventType.BIRTH)
                s_death_h = get_source_event_handle(s_person, EventType.DEATH)

                for key, res in resolutions.items():
                    if res != "source" or target_person_handle is None:
                        continue

                    # 6. Other events: key is "event:<source event handle>"
                    if key.startswith("event:"):
                        s_evt_h = key.split(":", 1)[1]
                        if s_evt_h in (s_birth_h, s_death_h):
                            continue
                        t_evt_h = copy_event(s_evt_h, trans)
                        if t_evt_h:
                            t_person.add_event_ref(
                                copy_event_ref(s_evt_h, t_evt_h, trans)
                            )
                        continue

                    # 7. FamilySearch ID
                    if key == "fsid":
                        fs_id = source_fs_id()
                        if fs_id:
                            attr = Attribute()
                            attr.set_type("_FSFTID")
                            attr.set_value(fs_id)
                            t_person.add_attribute(attr)
                        continue

                    # 8. Family relations: father/mother, keys are
                    # "<role>:<source person handle>"; relatives are
                    # linked through their best-matching target person.
                    if key.startswith(("father:", "mother:")):
                        role, s_handle = key.split(":", 1)
                        t_rel_h = best_target_person(s_handle)
                        if not t_rel_h:
                            LOG.warning("No target match for %s; skipped", key)
                            continue
                        if t_rel_h == t_person.handle:
                            LOG.warning("%s matches the person itself; skipped", key)
                            continue
                        fam = ensure_parent_family(trans)
                        if role == "father" and not fam.get_father_handle():
                            fam.set_father_handle(t_rel_h)
                        elif role == "mother" and not fam.get_mother_handle():
                            fam.set_mother_handle(t_rel_h)
                        else:
                            LOG.warning("%s slot occupied; skipped", key)
                            continue
                        self.db.commit_family(fam, trans)
                        # A parent must list the family too, or the two
                        # records disagree (Check and Repair would flag it).
                        t_parent = safe_get_person(self.db, t_rel_h)
                        if t_parent is not None:
                            t_parent.add_family_handle(fam.handle)
                            self.db.commit_person(t_parent, trans)
                        continue

                    # 9. Spouse, key is "spouse:<source person handle>".
                    if key.startswith("spouse:"):
                        s_handle = key.split(":", 1)[1]
                        t_rel_h = best_target_person(s_handle)
                        t_rel = safe_get_person(self.db, t_rel_h) if t_rel_h else None
                        if not t_rel:
                            LOG.warning("No target match for spouse; skipped")
                            continue
                        if t_rel_h == t_person.handle:
                            LOG.warning("Spouse matches the person itself; skipped")
                            continue
                        spouse_fam: Family | None = None
                        occupied = False
                        for fh in t_person.get_family_handle_list():
                            candidate = safe_get_family(self.db, fh)
                            if not candidate:
                                continue
                            father_h = candidate.get_father_handle()
                            mother_h = candidate.get_mother_handle()
                            if t_rel_h in (father_h, mother_h):
                                occupied = True
                                break
                            if t_person.handle in (father_h, mother_h) and (
                                father_h is None or mother_h is None
                            ):
                                spouse_fam = candidate
                                break
                        if occupied:
                            continue
                        if spouse_fam is None:
                            if t_person.get_gender() == Person.FEMALE:
                                spouse_fam = Family()
                                spouse_fam.set_mother_handle(t_person.handle)
                                spouse_fam.set_father_handle(t_rel_h)
                            else:
                                spouse_fam = Family()
                                spouse_fam.set_father_handle(t_person.handle)
                                spouse_fam.set_mother_handle(t_rel_h)
                            self.db.add_family(spouse_fam, trans)
                            t_person.add_family_handle(spouse_fam.handle)
                        elif spouse_fam.get_father_handle() is None:
                            spouse_fam.set_father_handle(t_rel_h)
                        else:
                            spouse_fam.set_mother_handle(t_rel_h)
                        self.db.commit_family(spouse_fam, trans)
                        t_rel.add_family_handle(spouse_fam.handle)
                        self.db.commit_person(t_rel, trans)
                        continue

                    # 10. Child, key is "child:<source person handle>".
                    if key.startswith("child:"):
                        s_handle = key.split(":", 1)[1]
                        t_rel_h = best_target_person(s_handle)
                        if not t_rel_h:
                            LOG.warning("No target match for child; skipped")
                            continue
                        if t_rel_h == t_person.handle:
                            LOG.warning("Child matches the person itself; skipped")
                            continue
                        child_fam: Family | None = None
                        already_child = False
                        for fh in t_person.get_family_handle_list():
                            candidate = safe_get_family(self.db, fh)
                            if not candidate or t_person.handle not in (
                                candidate.get_father_handle(),
                                candidate.get_mother_handle(),
                            ):
                                continue
                            if any(
                                ref.ref == t_rel_h
                                for ref in candidate.get_child_ref_list()
                            ):
                                already_child = True
                                break
                            if child_fam is None:
                                child_fam = candidate
                        if already_child:
                            LOG.info("Child %s is already in the tree; skipped", key)
                            continue
                        if child_fam is None:
                            child_fam = Family()
                            if t_person.get_gender() == Person.FEMALE:
                                child_fam.set_mother_handle(t_person.handle)
                            else:
                                child_fam.set_father_handle(t_person.handle)
                            self.db.add_family(child_fam, trans)
                            t_person.add_family_handle(child_fam.handle)
                        child_ref = ChildRef()
                        child_ref.ref = t_rel_h
                        child_fam.add_child_ref(child_ref)
                        self.db.commit_family(child_fam, trans)
                        t_rel = safe_get_person(self.db, t_rel_h)
                        if t_rel:
                            t_rel.add_parent_family_handle(child_fam.handle)
                            self.db.commit_person(t_rel, trans)
                        continue

                self.db.commit_person(t_person, trans)
                LOG.info("Merged changes into person: %s", t_person.handle)

        return True
