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
    NameType,
    Family,
    FamilyRelType,
    ChildRef,
    Attribute,
    EventRoleType,
    EventType,
)
from gramps.gen.soundex import soundex
from gramps.gen.display.place import displayer as place_displayer
from gramps.gen.utils.id import create_id
from gramps.gen.display.name import displayer as name_displayer
from gramps.gen.utils.db import get_birth_or_fallback
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
    compare_date_specificity,
    compare_place_specificity,
    is_empty_event,
    safe_get,
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
    name_covers,
    parent_age_problem,
    person_birth_year,
    relative_match_problem,
)
from .gwizard_filemerge_media import (
    TargetMediaIndex,
    file_checksum,
    find_file,
    is_url,
    mark_incoming,
    same_media,
    target_path,
)

# -------------------------------------------------------------------------
#
# Log
#
# -------------------------------------------------------------------------
LOG = logging.getLogger(__name__)

_ = glocale.translation.gettext


def format_link_preview(entries: list[dict[str, Any]]) -> str:
    """Return plain text for the preview that ``link_preview`` produces."""
    roles = {"father": _("father"), "mother": _("mother"), "child": _("child")}
    lines: list[str] = []
    for entry in entries:
        lines.append(entry["label"])
        for member in entry["members"]:
            if member["is_self"]:
                status = _("this person")
            elif member["in_tree"]:
                status = _("in your tree")
            else:
                status = _("not in your tree yet")
            lines.append(
                "    %s (%s): %s" % (member["name"], roles[member["role"]], status)
            )
        if not entry["will_link"]:
            lines.append("    " + _("Nothing to link yet."))
        lines.append("")
    return "\n".join(lines).rstrip()


def keep_replaced_name(person: Any, old_name: Any) -> bool:
    """
    After a merge changed a person's primary name, keep the name it had as
    an "Also Known As" alternate name, unless the new name (or an alternate
    name already there) holds everything the old one did.

    :returns: True when the old name was added.
    """
    new_name = person.get_primary_name()
    old_given = str(old_name.get_first_name() or "")
    old_surname = surname_text(old_name)
    if not (old_given or old_surname):
        return False
    for name in [new_name] + list(person.get_alternate_names()):
        if name_covers(str(name.get_first_name() or ""), old_given) and name_covers(
            surname_text(name), old_surname
        ):
            return False
    kept = copy.deepcopy(old_name)
    kept.set_type(NameType(NameType.AKA))
    person.add_alternate_name(kept)
    return True


def format_link_summary(
    summary: list[dict[str, str]], statuses: tuple[str, ...] = ("conflict",)
) -> str:
    """Return plain text for the entries of ``link_summary`` with ``statuses``."""
    return "\n".join(
        "%s: %s" % (entry["family"], entry["detail"])
        for entry in summary
        if entry["status"] in statuses
    )


# ------------------------------------------------------------
#
# GedGWizard
#
# ------------------------------------------------------------

# Person items that are compared one by one and only ever added, never
# replaced: alternate names, attributes, addresses and notes. The merge
# dialog keys them "<kind>:<index in the incoming person's list>".
EXTRA_KINDS = ("altname", "attribute", "address", "note", "url", "media", "lds")

# Notes the GEDCOM importer writes about itself ("Records not imported...")
# describe the import, not the person, so they are left out.
_IMPORT_NOTE_TYPE = "GEDCOM import"


def _norm_text(value: Any) -> str:
    """Return ``value`` as text with spaces collapsed and case folded."""
    return " ".join(str(value or "").split()).casefold()


def extra_label(kind: str) -> str:
    """Return the row label for a kind of item."""
    return {
        "altname": _("Also Known As"),
        "attribute": _("Attribute"),
        "address": _("Address"),
        "note": _("Note"),
        "url": _("Web Link"),
        "media": _("Media"),
        "lds": _("LDS Ordinance"),
    }[kind]


def extra_items(kind: str, person: Any, db: Any) -> list[tuple[int, Any]]:
    """
    Return (index, item) pairs for one kind of item of ``person``.

    The index is the item's place in the person's own list, which is what
    the merge dialog's keys refer to. The FamilySearch ID attribute has its
    own row, so it is left out of the attributes. Items with nothing to
    show (a note with no text, an attribute with no value, an address with
    every field blank...) are left out too.
    """
    return [
        (index, item)
        for index, item in _all_extra_items(kind, person, db)
        if not is_blank_extra_item(kind, item)
    ]


def is_blank_extra_item(kind: str, item: Any) -> bool:
    """
    Return True when an item has nothing to show or compare: every field
    but its type is blank. When in doubt the item counts as not blank.
    """
    try:
        if kind == "note":
            return not (item.get() or "").strip()
        if kind == "attribute":
            return not _norm_text(item.get_value())
        if kind == "url":
            return not (
                _norm_text(item.get_path()) or _norm_text(item.get_description())
            )
        if kind == "media":
            return not (
                _norm_text(item.get_path()) or _norm_text(item.get_description())
            )
        if kind == "lds":
            return (
                item.get_date_object().is_empty()
                and not _norm_text(item.get_temple())
                and not item.get_place_handle()
                and not item.get_family_handle()
                and not item.get_status()
            )
        if kind == "altname":
            # Everything but the name type is blank.
            return not any(
                (
                    _norm_text(item.get_first_name()),
                    any(
                        _norm_text(s.get_prefix()) or _norm_text(s.get_surname())
                        for s in item.get_surname_list()
                    ),
                    _norm_text(item.get_suffix()),
                    _norm_text(item.get_title()),
                    _norm_text(item.get_nick_name()),
                    _norm_text(item.get_call_name()),
                )
            )
        # Addresses: every field and the date are blank.
        return not any(extra_signature(kind, item))
    except Exception:  # pylint: disable=broad-except
        return False


def _all_extra_items(kind: str, person: Any, db: Any) -> list[tuple[int, Any]]:
    """Return every (index, item) pair of one kind, blank items included."""
    if kind == "altname":
        return list(enumerate(person.get_alternate_names()))
    if kind == "attribute":
        return [
            (index, attribute)
            for index, attribute in enumerate(person.get_attribute_list())
            if str(attribute.get_type()) != "_FSFTID"
        ]
    if kind == "address":
        return list(enumerate(person.get_address_list()))
    if kind == "url":
        return list(enumerate(person.get_url_list()))
    if kind == "lds":
        return list(enumerate(person.get_lds_ord_list()))
    if kind == "media":
        # The items are the Media objects; the index is the position of
        # the person's reference to the media.
        items = []
        for index, mref in enumerate(person.get_media_list()):
            media = safe_get(
                db, mref.get_reference_handle(), "get_media_from_handle", "media"
            )
            if media is not None:
                items.append((index, media))
        return items
    items = []
    for index, handle in enumerate(person.get_note_list()):
        try:
            note = db.get_note_from_handle(handle)
        except Exception:  # pylint: disable=broad-except
            continue
        if note is None or str(note.get_type()) == _IMPORT_NOTE_TYPE:
            continue
        items.append((index, note))
    return items


def extra_signature(kind: str, item: Any) -> tuple[Any, ...]:
    """Return what makes two items of the same kind the same item."""
    if kind == "altname":
        return (
            _norm_text(item.get_type()),
            _norm_text(item.get_first_name()),
            tuple(
                (_norm_text(s.get_prefix()), _norm_text(s.get_surname()))
                for s in item.get_surname_list()
            ),
            _norm_text(item.get_suffix()),
            _norm_text(item.get_title()),
            _norm_text(item.get_nick_name()),
            _norm_text(item.get_call_name()),
        )
    if kind == "attribute":
        return (_norm_text(item.get_type()), _norm_text(item.get_value()))
    if kind == "url":
        return (
            _norm_text(item.get_type()),
            _norm_text(item.get_path()).rstrip("/"),
            _norm_text(item.get_description()),
        )
    if kind == "address":
        return (
            _norm_text(glocale.date_displayer.display(item.get_date_object())),
            _norm_text(item.get_street()),
            _norm_text(item.get_locality()),
            _norm_text(item.get_city()),
            _norm_text(item.get_county()),
            _norm_text(item.get_state()),
            _norm_text(item.get_country()),
            _norm_text(item.get_postal_code()),
            _norm_text(item.get_phone()),
        )
    if kind == "media":
        return (_norm_text(item.get_path().replace("\\", "/")),)
    if kind == "lds":
        return (
            _norm_text(item.type2str()),
            _norm_text(glocale.date_displayer.display(item.get_date_object())),
            _norm_text(item.get_temple()),
            _norm_text(item.status2str()),
        )
    return (_norm_text(item.get_type()), _norm_text(item.get()))


def same_extra_item(kind: str, s_item: Any, s_db: Any, t_item: Any, t_db: Any) -> bool:
    """
    Return True when an incoming item and a tree item are the same item.

    Media is the same picture when the paths are written alike, point at
    the same file, or the files have the same checksum; everything else
    compares by :func:`extra_signature`.
    """
    if kind == "media":
        return same_media(s_item, s_db, t_item, t_db)
    return extra_signature(kind, s_item) == extra_signature(kind, t_item)


def extra_text(kind: str, item: Any, db: Any = None, fallback_db: Any = None) -> str:
    """
    Return a short one-line description of an item.

    For media, ``db`` (and ``fallback_db``, for incoming media exported
    from the tree itself) are used to say when the file cannot be found.
    """
    if kind == "altname":
        return "%s (%s)" % (name_displayer.display_name(item), item.get_type())
    if kind == "attribute":
        return "%s: %s" % (item.get_type(), item.get_value())
    if kind == "url":
        text = "%s: %s" % (item.get_type(), item.get_path())
        if item.get_description():
            text += " (%s)" % item.get_description()
        return text
    if kind == "address":
        parts = [
            item.get_street(),
            item.get_locality(),
            item.get_city(),
            item.get_county(),
            item.get_state(),
            item.get_postal_code(),
            item.get_country(),
        ]
        text = ", ".join(part for part in parts if part)
        date = glocale.date_displayer.display(item.get_date_object())
        return "%s (%s)" % (text, date) if date and text else text or date
    if kind == "media":
        text = item.get_path()
        if item.get_description():
            text += " (%s)" % item.get_description()
        path = item.get_path() or ""
        if (
            db is not None
            and not is_url(path)
            and find_file(db, path, fallback_db) is None
        ):
            text += " " + _("[file not found]")
        return text
    if kind == "lds":
        parts = [
            item.type2str(),
            glocale.date_displayer.display(item.get_date_object()),
            item.get_temple(),
        ]
        text = ", ".join(part for part in parts if part)
        status = item.status2str()
        return "%s (%s)" % (text, status) if status else text
    body = " ".join(item.get().split())
    if len(body) > 100:
        body = body[:100].rstrip() + "\u2026"
    return "%s: %s" % (item.get_type(), body)


def pair_extra_items(
    kind: str, s_person: Any, s_db: Any, t_person: Any, t_db: Any
) -> list[tuple[int | None, Any, int | None, Any]]:
    """
    Pair the incoming person's items of one kind with the tree person's.

    Returns (source index, source item, target index, target item) tuples:
    items with the same content first (in incoming order), then incoming
    items the tree person lacks, then items only the tree person has. The
    missing side of an unpaired item is None.
    """
    unused = list(extra_items(kind, t_person, t_db))
    paired = []
    source_only = []
    for s_index, s_item in extra_items(kind, s_person, s_db):
        for position, (t_index, t_item) in enumerate(unused):
            if same_extra_item(kind, s_item, s_db, t_item, t_db):
                del unused[position]
                paired.append((s_index, s_item, t_index, t_item))
                break
        else:
            source_only.append((s_index, s_item, None, None))
    return paired + source_only + [(None, None, i, item) for i, item in unused]


def event_signature(db: Any, handle: str) -> tuple[str, int, str] | None:
    """Return what makes two events the same event: type, date and text."""
    event = safe_get_event(db, handle)
    if event is None:
        return None
    return (
        str(event.get_type()),
        event.get_date_object().get_sort_value(),
        (event.get_description() or "").strip(),
    )


def family_summary(db: Any, family: Any) -> str:
    """
    Return a one-line description of a family: partners, type, events.

    Events are listed in date order, undated ones last; events with no
    date, place or description are left out.
    """
    names = []
    for handle in (family.get_father_handle(), family.get_mother_handle()):
        person = safe_get_person(db, handle) if handle else None
        if person is not None:
            names.append(name_displayer.display(person))
    details = []
    if family.get_relationship() != FamilyRelType.UNKNOWN:
        details.append(str(family.get_relationship()))
    # Events in date order (undated last), then by text, so both sides of
    # a comparison list them the same way; empty events are left out.
    events = []
    for ref in family.get_event_ref_list():
        event = safe_get_event(db, ref.ref)
        if event is None or is_empty_event(event, db):
            continue
        date = " ".join(glocale.date_displayer.display(event.get_date_object()).split())
        text = " ".join(("%s %s" % (event.get_type(), date)).split())
        sort_value = event.get_date_object().get_sort_value()
        events.append((sort_value == 0, sort_value, text.casefold(), text))
    details.extend(text for *_key, text in sorted(events))
    text = _(" and ").join(names) or _("(no partners)")
    return "%s: %s" % (text, "; ".join(details) if details else _("(no details)"))


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
        # This database only reads objects, so its ID prefixes hardly matter.
        # Older Gramps versions lack the tag prefix setting and take fewer
        # arguments, so use the defaults there instead of failing to load.
        try:
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
        except (AttributeError, TypeError):
            LOG.debug("ID prefixes not set: this Gramps version differs")
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

        # Media paths in the incoming file are read from where it came from.
        mark_incoming(source_db, gedcom_path)
        self.context["source_db"] = source_db
        # Handles copied for an earlier file mean nothing for this one.
        self.context["handle_map"] = {}
        self.context["person_map"] = {}
        self.context.pop("place_index", None)
        self.context.pop("media_index", None)

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

        # 2c. Compare nickname and call name. They are listed only when the
        # incoming person has one, so a value only the tree has is not a
        # difference to step to.
        for field_type, label, getter in (
            ("nickname", _("Nickname"), "get_nick_name"),
            ("call_name", _("Call Name"), "get_call_name"),
        ):
            s_value = getattr(s_person.get_primary_name(), getter)()
            t_value = getattr(t_person.get_primary_name(), getter)()
            if s_value:
                rows.append(
                    GWizardCompareRow(
                        status=get_status(s_value, t_value),
                        field=label,
                        source_val=s_value,
                        target_val=t_value,
                        field_type=field_type,
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
            """
            Return (handle, Event) pairs for non-Birth/Death events. Empty
            events (no date, place or description) are left out, as they
            are in the compare window and merge dialog.
            """
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
                if is_empty_event(event, db):
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

        # 8. Alternate names, attributes, addresses and notes. Items found
        # on both sides match and are not listed; the rest are source_only or
        # target_only rows so the Diff list flags the person.
        for kind in EXTRA_KINDS:
            for s_index, s_item, t_index, t_item in pair_extra_items(
                kind, s_person, source_db, t_person, self.db
            ):
                if s_item is not None and t_item is not None:
                    continue
                rows.append(
                    GWizardCompareRow(
                        status="source_only" if t_item is None else "target_only",
                        field=extra_label(kind),
                        source_val=(
                            extra_text(kind, s_item, source_db, self.db)
                            if s_item is not None
                            else ""
                        ),
                        target_val=(
                            extra_text(kind, t_item, self.db)
                            if t_item is not None
                            else ""
                        ),
                        field_type=kind,
                        extra_data={"source_index": s_index, "target_index": t_index},
                    )
                )

        # 9. Families the incoming person heads: a family the tree lacks, a
        # different relationship type, events or members the tree's family
        # lacks. Only what can be merged is listed.
        for entry in self.family_compare(s_person.handle, t_person.handle):
            if entry["differences"]:
                rows.append(
                    GWizardCompareRow(
                        status=(
                            "source_only" if entry["tf_handle"] is None else "differ"
                        ),
                        field=_("Family"),
                        source_val=entry["source_text"],
                        target_val=entry["target_text"],
                        field_type="family",
                        extra_data={"family_handle": entry["sf_handle"]},
                    )
                )

        return rows

    def target_person_for(self, s_handle: str) -> str | None:
        """
        Return the handle of the person in the tree that an incoming person
        stands for, or None. This is the person a merge links as a relative.
        """
        return self._best_target_person(s_handle)

    def _best_target_person(self, s_handle: str) -> str | None:
        """
        Return the handle of the person in the tree that an incoming person
        stands for, or None.

        People the merge has already added or merged come first, then the
        compare window's one-to-one pairing (where None means the user said
        "Not a Match"), then the closest name match.
        """
        source_db = self.context.get("source_db")
        if source_db is None:
            return None
        done = (self.context.get("person_map") or {}).get(s_handle)
        if done and safe_get_person(self.db, done) is not None:
            return done
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
        # A score can pass on a first name alone, so the best match is used
        # only when its surname and birth year also fit the relative. A
        # match refused only for its birth year is remembered, so the link
        # summary can say who it was and the user can link them by hand.
        refused: tuple[str, str] | None = None
        for handle, _score in matches:
            target = safe_get_person(self.db, handle)
            problem = relative_match_problem(rel, source_db, target, self.db)
            if not problem:
                return handle
            if problem == "birth_year" and refused is None:
                refused = (handle, problem)
        if refused is not None:
            self.context.setdefault("refused_matches", {})[s_handle] = refused[0]
        return None

    def _find_target_family(
        self,
        t_father: str | None,
        t_mother: str | None,
        t_children: list[str],
        has_father: bool,
        has_mother: bool,
    ) -> Family | None:
        """
        Return the family in the tree that best fits these people.

        Candidates are the families the parents already head and the
        families the children already belong to. A family is ruled out
        when a parent slot holds someone other than the person the
        incoming parent maps to (or, when that parent is not in the tree
        yet, anyone at all).
        """
        candidates: dict[str, Family] = {}

        def consider(handles: Any) -> None:
            for family_handle in handles:
                if family_handle not in candidates:
                    found = safe_get_family(self.db, family_handle)
                    if found is not None:
                        candidates[family_handle] = found

        for parent_handle in (t_father, t_mother):
            parent = safe_get_person(self.db, parent_handle) if parent_handle else None
            if parent is not None:
                consider(parent.get_family_handle_list())
        for child_handle in t_children:
            child = safe_get_person(self.db, child_handle)
            if child is not None:
                consider(child.get_parent_family_handle_list())

        best: Family | None = None
        best_score = 0
        for fam in candidates.values():
            father_h = fam.get_father_handle()
            mother_h = fam.get_mother_handle()
            if has_father and father_h and father_h != t_father:
                continue
            if has_mother and mother_h and mother_h != t_mother:
                continue
            score = 0
            if t_father and father_h == t_father:
                score += 2
            if t_mother and mother_h == t_mother:
                score += 2
            members = {ref.ref for ref in fam.get_child_ref_list()}
            score += sum(1 for handle in t_children if handle in members)
            if score > best_score:
                best, best_score = fam, score
        return best

    def family_compare(
        self, source_person_handle: str, target_person_handle: str | None
    ) -> list[dict[str, Any]]:
        """
        Compare each family the incoming person heads with its counterpart
        in the tree, for a person who is already paired with a tree person.

        Returns one entry per incoming family: ``sf_handle``, ``tf_handle``
        (None when the tree has no such family), ``source_text`` and
        ``target_text`` (one-line descriptions), ``differences`` (any of
        "family", "relationship", "events", "members"; empty when there is
        nothing to merge), ``actionable`` (False while the family has fewer
        than two members in the tree, so merging would do nothing) and
        ``event_handles`` (incoming events the tree's family lacks).
        """
        source_db = self.context.get("source_db")
        s_person = (
            safe_get_person(source_db, source_person_handle) if source_db else None
        )
        if s_person is None or not target_person_handle:
            return []

        def mapped(handle: str | None) -> str | None:
            if not handle:
                return None
            if handle == source_person_handle:
                return target_person_handle
            return self._best_target_person(handle)

        entries: list[dict[str, Any]] = []
        for sf_handle in s_person.get_family_handle_list():
            s_family = safe_get_family(source_db, sf_handle)
            if s_family is None:
                continue
            s_father = s_family.get_father_handle()
            s_mother = s_family.get_mother_handle()
            t_father = mapped(s_father)
            t_mother = mapped(s_mother)
            if t_father and t_father == t_mother:
                t_mother = None
            claimed = {handle for handle in (t_father, t_mother) if handle}
            t_children: list[str] = []
            for ref in s_family.get_child_ref_list():
                t_child = mapped(ref.ref)
                if t_child and t_child not in claimed:
                    t_children.append(t_child)
                    claimed.add(t_child)
            t_family = self._find_target_family(
                t_father, t_mother, t_children, bool(s_father), bool(s_mother)
            )

            differences: list[str] = []
            event_handles: list[str] = []
            known = (
                {event_signature(self.db, r.ref) for r in t_family.get_event_ref_list()}
                if t_family is not None
                else set()
            )
            for ref in s_family.get_event_ref_list():
                # An empty incoming event adds nothing to the tree's family.
                if is_empty_event(safe_get_event(source_db, ref.ref), source_db):
                    continue
                signature = event_signature(source_db, ref.ref)
                if signature is not None and signature not in known:
                    event_handles.append(ref.ref)
                    known.add(signature)
            if t_family is None:
                differences.append("family")
            else:
                relationship = s_family.get_relationship()
                if (
                    relationship != FamilyRelType.UNKNOWN
                    and relationship != t_family.get_relationship()
                ):
                    differences.append("relationship")
                if event_handles:
                    differences.append("events")
                children = {ref.ref for ref in t_family.get_child_ref_list()}
                if (
                    (t_father and t_family.get_father_handle() != t_father)
                    or (t_mother and t_family.get_mother_handle() != t_mother)
                    or any(handle not in children for handle in t_children)
                ):
                    differences.append("members")
            actionable = t_family is not None or len(claimed) >= 2
            entries.append(
                {
                    "sf_handle": sf_handle,
                    "tf_handle": t_family.handle if t_family is not None else None,
                    "source_text": family_summary(source_db, s_family),
                    "target_text": (
                        family_summary(self.db, t_family)
                        if t_family is not None
                        else ""
                    ),
                    "differences": differences if actionable else [],
                    "actionable": actionable,
                    "event_handles": event_handles,
                }
            )
        return entries

    def missing_relatives(self, source_person_handle: str) -> list[str]:
        """
        Return the handles of the incoming person's parents, spouses and
        children who have nobody in the tree: the people the
        ``add_missing_relatives`` option of the apply step would add.

        A relative whose name matched someone in the tree but was refused
        only for the birth year is not listed: they are not added.
        """
        source_db = self.context.get("source_db")
        s_person = (
            safe_get_person(source_db, source_person_handle) if source_db else None
        )
        if s_person is None:
            return []
        handles: list[str] = []
        for sf_handle in s_person.get_parent_family_handle_list():
            s_family = safe_get_family(source_db, sf_handle)
            if s_family is not None:
                handles += [s_family.get_father_handle(), s_family.get_mother_handle()]
        for sf_handle in s_person.get_family_handle_list():
            s_family = safe_get_family(source_db, sf_handle)
            if s_family is not None:
                handles += [s_family.get_father_handle(), s_family.get_mother_handle()]
                handles += [ref.ref for ref in s_family.get_child_ref_list()]
        missing: list[str] = []
        for handle in handles:
            if not handle or handle == source_person_handle or handle in missing:
                continue
            if self._best_target_person(handle) is not None:
                continue
            if handle in (self.context.get("refused_matches") or {}):
                continue
            missing.append(handle)
        return missing

    def link_preview(self, source_person_handle: str) -> list[dict[str, Any]]:
        """
        Describe, without changing anything, how the families of an
        incoming person would link into the tree if the person were added.

        Returns one entry per family: ``label``, ``will_link`` (some other
        member is already in the tree) and ``members``, each with ``role``,
        ``name``, ``in_tree`` and ``is_self``.
        """
        source_db = self.context.get("source_db")
        s_person = (
            safe_get_person(source_db, source_person_handle) if source_db else None
        )
        if s_person is None:
            return []
        entries: list[dict[str, Any]] = []
        family_handles = list(s_person.get_parent_family_handle_list()) + list(
            s_person.get_family_handle_list()
        )
        for sf_handle in family_handles:
            s_family = safe_get_family(source_db, sf_handle)
            if s_family is None:
                continue
            roles = [
                ("father", s_family.get_father_handle()),
                ("mother", s_family.get_mother_handle()),
            ] + [("child", ref.ref) for ref in s_family.get_child_ref_list()]
            members = []
            others_in_tree = 0
            for role, handle in roles:
                if not handle:
                    continue
                person = safe_get_person(source_db, handle)
                is_self = handle == source_person_handle
                in_tree = is_self or self._best_target_person(handle) is not None
                if in_tree and not is_self:
                    others_in_tree += 1
                members.append(
                    {
                        "role": role,
                        "name": name_displayer.display(person) if person else handle,
                        "in_tree": in_tree,
                        "is_self": is_self,
                    }
                )
            parents = [m["name"] for m in members if m["role"] != "child"]
            label = (
                _(" and ").join(parents)
                if parents
                else _("Family of %s") % ", ".join(m["name"] for m in members[:2])
            )
            entries.append(
                {"label": label, "will_link": others_in_tree > 0, "members": members}
            )
        return entries

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
        # Link a new person's families into the tree (on by default).
        link_families = bool(kwargs.get("link_families", True))
        # Add the incoming person's parents, spouses and children who are
        # not in the tree as new people, instead of leaving them out (off
        # by default). A relative who matches someone in the tree is linked
        # to that person as always, and nobody is added twice.
        add_missing_relatives = bool(kwargs.get("add_missing_relatives", False))
        # Who the merge has already added or merged, and what linking did.
        person_map: dict[str, str] = self.context.setdefault("person_map", {})
        link_summary: list[dict[str, str]] = []
        self.context["link_summary"] = link_summary
        self.context["refused_matches"] = {}
        # Tree handles of the relatives this apply added as new people.
        added_relatives: list[str] = []
        self.context["added_relatives"] = added_relatives
        best_target_person = self._best_target_person
        family_keys: list[str] = []

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

        def drop_tags(obj: Any) -> None:
            """
            Clear the tags of a copied object, as for a new person.

            Its tag handles belong to the incoming file (the importer can tag
            every object it reads) and mean nothing in the target.
            """
            obj.set_tag_list([])

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
            """
            Point the media references of ``obj`` at copies in the target.

            A reference whose media could not be copied is dropped rather
            than left pointing at a handle the target lacks. The citations
            and notes of each reference (and of its attributes) are copied too.
            """
            kept = []
            for mref in obj.get_media_list():
                new_handle = copy_media(mref.get_reference_handle(), trans)
                if not new_handle:
                    continue
                mref.set_reference_handle(new_handle)
                remap_citations_notes(mref)
                for attribute in mref.get_attribute_list():
                    remap_citations_notes(attribute)
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
                drop_tags(new_place)
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

        notes_by_text: dict[tuple[str, str], str] = {}
        notes_indexed: list[bool] = []

        def note_key(note: Any) -> tuple[str, str] | None:
            """Return a note's (type, text) key, or None for an empty note."""
            text = note.get().strip()
            return (str(note.get_type()), text) if text else None

        def note_index() -> dict[tuple[str, str], str]:
            """Return {(type, text): handle} for the tree's notes, built on first use."""
            if not notes_indexed:
                for handle in sorted(self.db.get_note_handles()):
                    try:
                        key = note_key(self.db.get_note_from_handle(handle))
                    except Exception:  # pylint: disable=broad-except
                        continue
                    if key and key not in notes_by_text:
                        notes_by_text[key] = handle
                notes_indexed.append(True)
            return notes_by_text

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
                if not s_note.get().strip():
                    return None  # an empty note is import debris, not data
                if self.db.has_note_handle(s_note_handle):
                    t_note = self.db.get_note_from_handle(s_note_handle)
                    if t_note.get_type() == s_note.get_type() and (
                        t_note.get() == s_note.get()
                    ):
                        return remember("note", s_note_handle, s_note_handle)
                # A note with the same type and text is already in the tree
                # (the same record merged again): it is shared, not copied.
                key = note_key(s_note)
                same = note_index().get(key) if key else None
                if same and self.db.has_note_handle(same):
                    return remember("note", s_note_handle, same)
                new_note = copy.deepcopy(s_note)
                unused_handle(new_note, self.db.has_note_handle)
                drop_tags(new_note)
                fresh_gramps_id(new_note, self.db.has_note_gramps_id)
                self.db.add_note(new_note, trans)
                if key:
                    note_index()[key] = new_note.handle
                return remember("note", s_note_handle, new_note.handle)
            except Exception:
                LOG.warning(
                    "Could not copy %s from the incoming file; it was skipped",
                    "note",
                    exc_info=True,
                )
            return None

        def media_index() -> TargetMediaIndex:
            """Return the index of the target's media, built on first use."""
            index = self.context.get("media_index")
            if index is None or index.db is not self.db:
                index = TargetMediaIndex(self.db)
                self.context["media_index"] = index
            return index

        # Media and citations can refer to each other (a citation's media
        # reference citing that citation). An object reached again while it
        # is being copied is left out rather than recursed into forever.
        copies_in_progress: set[tuple[str, str]] = set()

        # Helper to copy media
        def copy_media(s_media_handle: str | None, trans: Any) -> str | None:
            """
            Return the target media for an incoming one, copying it if needed.

            The incoming path is read from where the incoming file came from
            and recorded so it means the same file in the target (relative to
            the tree's base media path when the file is under it, otherwise
            in full). A picture the tree already has, by file, recorded path
            or checksum, is reused instead of added again. A file that cannot
            be found keeps its path as written.
            """
            if not s_media_handle:
                return None
            hit = mapped_handle("media", s_media_handle, self.db.has_media_handle)
            if hit:
                return hit
            if ("media", s_media_handle) in copies_in_progress:
                return None
            copies_in_progress.add(("media", s_media_handle))
            try:
                s_media = source_db.get_media_from_handle(s_media_handle)
                if not s_media:
                    return None
                s_path = s_media.get_path() or ""
                full = find_file(source_db, s_path, fallback_db=self.db)
                new_path = target_path(full, self.db) if full else s_path
                checksum = (s_media.get_checksum() or "").strip() or file_checksum(full)
                if self.db.has_media_handle(s_media_handle):
                    t_media = self.db.get_media_from_handle(s_media_handle)
                    if t_media.get_path() in (s_path, new_path):
                        return remember("media", s_media_handle, s_media_handle)
                found = media_index().find(full, checksum, new_path)
                if found:
                    LOG.info(
                        "Media %r is already in the family tree; reusing it", s_path
                    )
                    return remember("media", s_media_handle, found)
                new_media = copy.deepcopy(s_media)
                unused_handle(new_media, self.db.has_media_handle)
                drop_tags(new_media)
                new_media.set_path(new_path)
                if checksum:
                    new_media.set_checksum(checksum)
                if full is None and not is_url(s_path):
                    LOG.warning("Media file not found: %s", s_path)
                copy_note_list(new_media, trans)
                copy_citation_list(new_media, trans)
                fresh_gramps_id(new_media, self.db.has_media_gramps_id)
                self.db.add_media(new_media, trans)
                media_index().add(new_media)
                return remember("media", s_media_handle, new_media.handle)
            except Exception:
                LOG.warning(
                    "Could not copy %s from the incoming file; it was skipped",
                    "media",
                    exc_info=True,
                )
            finally:
                copies_in_progress.discard(("media", s_media_handle))
            return None

        def repository_index() -> dict[str, str]:
            """
            Return {normalized name: handle} for the tree's repositories,
            built on first use. A name more than one tree repository has is
            left out, so the merge never guesses between them.
            """
            index = self.context.get("repository_index")
            if index is None:
                index = {}
                shared: set[str] = set()
                for t_repo in self.db.iter_repositories():
                    key = normalize_source_text(t_repo.get_name())
                    if not key:
                        continue
                    if key in index:
                        shared.add(key)
                    index.setdefault(key, t_repo.handle)
                for key in shared:
                    del index[key]
                self.context["repository_index"] = index
            return index

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
                # A repository the tree already has under the same name
                # (National Archives, WikiTree, ...) is reused, not copied.
                same = repository_index().get(normalize_source_text(s_repo.get_name()))
                if same and self.db.has_repository_handle(same):
                    return remember("repo", s_repo_handle, same)
                new_repo = copy.deepcopy(s_repo)
                unused_handle(new_repo, self.db.has_repository_handle)
                drop_tags(new_repo)
                copy_note_list(new_repo, trans)
                fresh_gramps_id(new_repo, self.db.has_repository_gramps_id)
                self.db.add_repository(new_repo, trans)
                name_key = normalize_source_text(new_repo.get_name())
                if name_key:
                    repository_index().setdefault(name_key, new_repo.handle)
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
                drop_tags(new_source)
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

        def note_texts(db: Any, obj: Any) -> list[tuple[str, str]]:
            """Return the (type, text) of an object's notes, sorted."""
            texts = []
            for handle in obj.get_note_list():
                try:
                    note = db.get_note_from_handle(handle) if handle else None
                except Exception:  # pylint: disable=broad-except
                    note = None
                if note is not None:
                    texts.append((str(note.get_type()), note.get().strip()))
            return sorted(texts)

        def same_citation_in_tree(s_citation: Any, t_source_handle: str) -> str | None:
            """
            Return the tree citation the incoming ``s_citation`` repeats, if
            any: one of the same tree source with the same page and the
            same notes (type and text). A merge from the same record again
            (a WikiTree profile merged twice, say) then reuses the citation
            and its notes instead of adding copies.

            The citation's date is not compared: for a web record it is the
            date the record was read, which changes with every merge.
            """
            page = normalize_source_text(s_citation.get_page())
            wanted = note_texts(source_db, s_citation)
            try:
                backlinks = list(
                    self.db.find_backlink_handles(t_source_handle, ["Citation"])
                )
            except Exception:  # pylint: disable=broad-except
                return None
            for _class, handle in sorted(backlinks, key=lambda item: item[1]):
                try:
                    t_citation = self.db.get_citation_from_handle(handle)
                except Exception:  # pylint: disable=broad-except
                    continue
                if (
                    t_citation is not None
                    and normalize_source_text(t_citation.get_page()) == page
                    and note_texts(self.db, t_citation) == wanted
                ):
                    return handle
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
            if ("citation", s_citation_handle) in copies_in_progress:
                return None
            copies_in_progress.add(("citation", s_citation_handle))
            try:
                s_citation = source_db.get_citation_from_handle(s_citation_handle)
                if not s_citation:
                    return None
                if self.db.has_citation_handle(s_citation_handle):
                    s_sig = citation_signature(source_db, s_citation_handle)
                    if s_sig is not None and s_sig == citation_signature(
                        self.db, s_citation_handle
                    ):
                        return remember(
                            "citation", s_citation_handle, s_citation_handle
                        )
                new_citation = copy.deepcopy(s_citation)
                new_sh = copy_source(new_citation.get_reference_handle(), trans)
                if not new_sh:
                    LOG.warning(
                        "Citation %s: its source could not be copied; skipped",
                        s_citation_handle,
                    )
                    return None
                same = same_citation_in_tree(s_citation, new_sh)
                if same:
                    return remember("citation", s_citation_handle, same)
                unused_handle(new_citation, self.db.has_citation_handle)
                drop_tags(new_citation)
                copy_note_list(new_citation, trans)
                copy_media_refs(new_citation, trans)
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
            finally:
                copies_in_progress.discard(("citation", s_citation_handle))
            return None

        # Helper to resolve references on an Event
        def resolve_references_for_event(new_event: Any, trans: Any) -> None:
            new_notes = []
            for nh in new_event.get_note_list():
                new_nh = copy_note(nh, trans)
                if new_nh:
                    new_notes.append(new_nh)
            new_event.set_note_list(new_notes)

            copy_media_refs(new_event, trans)

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

            copy_media_refs(new_person, trans)

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
                drop_tags(new_event)
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

        def upgrade_tree_event(t_evt: Any, s_evt: Any, trans: Any) -> None:
            """
            Merge the incoming event ``s_evt`` into the tree's event
            ``t_evt`` without losing anything the tree event holds:

            - the date and the place are taken from the incoming event
              unless the tree's are more specific (an empty incoming date or
              place never clears the tree's);
            - the description is filled in only when the tree's is empty;
            - the incoming citations, notes and media are added, skipping
              any the event already has (a citation of the same source and
              page with the same notes, the same note text, the same
              picture), so merging the same record again adds nothing.

            Only for an event no one else in the tree refers to: changing a
            shared event would change it for the others too.
            """
            s_date = s_evt.get_date_object()
            t_date = t_evt.get_date_object()
            if s_date and not s_date.is_empty():
                if (
                    not t_date
                    or t_date.is_empty()
                    or compare_date_specificity(s_date, t_date) >= 0
                ):
                    t_evt.set_date_object(copy.deepcopy(s_date))
            s_place_handle = s_evt.get_place_handle()
            if s_place_handle:
                s_pl = safe_get_place(source_db, s_place_handle)
                t_pl = safe_get_place(self.db, t_evt.get_place_handle())
                if t_pl is None or (
                    compare_place_specificity(s_pl, t_pl, source_db, self.db) >= 0
                ):
                    new_place = get_or_create_place(s_place_handle, trans)
                    if new_place:
                        t_evt.set_place_handle(new_place)
            s_desc = (s_evt.get_description() or "").strip()
            if s_desc and not (t_evt.get_description() or "").strip():
                t_evt.set_description(s_desc)
            # A citation the tree already has (same source, page and notes)
            # is reused, and so already on the event; one with new notes or
            # a new page is added.
            for s_cit_h in s_evt.get_citation_list():
                t_cit_h = copy_citation(s_cit_h, trans)
                if t_cit_h and t_cit_h not in t_evt.get_citation_list():
                    t_evt.add_citation(t_cit_h)
            for s_note_h in s_evt.get_note_list():
                t_note_h = copy_note(s_note_h, trans)
                if t_note_h and t_note_h not in t_evt.get_note_list():
                    t_evt.add_note(t_note_h)
            incoming = copy.deepcopy(s_evt)
            copy_media_refs(incoming, trans)
            have_media = {mref.ref for mref in t_evt.get_media_list()}
            for mref in incoming.get_media_list():
                if mref.ref not in have_media:
                    t_evt.add_media_reference(mref)
                    have_media.add(mref.ref)
            self.db.commit_event(t_evt, trans)

        def event_shared(event_handle: str, person_handle: str) -> bool:
            """Return whether anyone but ``person_handle`` refers to the event."""
            try:
                backlinks = self.db.find_backlink_handles(event_handle)
                return any(handle != person_handle for _cls, handle in backlinks)
            except Exception:  # pylint: disable=broad-except
                return True

        def merge_into_copy(new_evt: Any, t_evt: Any, s_evt: Any) -> None:
            """
            Fill the copied incoming event ``new_evt``, which replaces the
            shared tree event ``t_evt`` for one person, with what the tree
            event holds: its date or place when more specific, its
            description when the incoming one is empty, and its own
            citations and notes.
            """
            s_date = s_evt.get_date_object()
            t_date = t_evt.get_date_object()
            if (
                t_date
                and not t_date.is_empty()
                and compare_date_specificity(s_date, t_date) < 0
            ):
                new_evt.set_date_object(copy.deepcopy(t_date))
            s_pl = safe_get_place(source_db, s_evt.get_place_handle())
            t_pl = safe_get_place(self.db, t_evt.get_place_handle())
            if t_evt.get_place_handle() and (
                s_pl is None
                or compare_place_specificity(s_pl, t_pl, source_db, self.db) < 0
            ):
                new_evt.set_place_handle(t_evt.get_place_handle())
            if not new_evt.get_description() and t_evt.get_description():
                new_evt.set_description(t_evt.get_description())
            for handle in t_evt.get_citation_list():
                if handle not in new_evt.get_citation_list():
                    new_evt.add_citation(handle)
            for handle in t_evt.get_note_list():
                if handle not in new_evt.get_note_list():
                    new_evt.add_note(handle)

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
            owner: Any = None,
        ) -> EventRef:
            """
            Return an EventRef to the copied event ``t_event_handle``.

            The source person's reference to ``s_event_handle`` is copied
            so its role, privacy, attributes and notes survive. ``role``
            overrides the copied role (birth and death are always Primary).
            ``owner`` is the incoming object holding the reference when it
            is not the person (a family, for its events).
            """
            new_ref = EventRef()
            for ref in (owner if owner is not None else s_person).get_event_ref_list():
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

        # ------------------------------------------------------------------
        # Linking families.
        #
        # ``reconcile_family`` makes the tree match one incoming family. It
        # finds the family in the tree that already holds some of the same
        # people (or creates one once at least two of them are in the tree),
        # then adds whoever is missing, writing both sides of each link. It
        # can run again at any time without adding anything twice, so the
        # order in which people arrive does not matter: a family fills in as
        # its members are added.
        # ------------------------------------------------------------------
        def source_name(handle: str) -> str:
            person = safe_get_person(source_db, handle)
            return name_displayer.display(person) if person else handle

        def target_name(handle: str) -> str:
            person = safe_get_person(self.db, handle)
            return name_displayer.display(person) if person else handle

        def family_label(s_family: Family) -> str:
            parents = [
                source_name(handle)
                for handle in (
                    s_family.get_father_handle(),
                    s_family.get_mother_handle(),
                )
                if handle
            ]
            if parents:
                return _(" and ").join(parents)
            children = [source_name(ref.ref) for ref in s_family.get_child_ref_list()]
            return _("Family of %s") % ", ".join(children[:2])

        def birth_sort(person: Any) -> int:
            """Return the sort value of a person's birth date (0 if none)."""
            try:
                event = get_birth_or_fallback(self.db, person)
                if event is not None:
                    return event.get_date_object().get_sort_value()
            except Exception:  # pylint: disable=broad-except
                pass
            return 0

        def insert_child_by_birth(fam: Family, child_ref: ChildRef, child: Any) -> None:
            """Put the child before the first sibling born after them."""
            refs = list(fam.get_child_ref_list())
            position = len(refs)
            new_sort = birth_sort(child)
            if new_sort:
                for index, ref in enumerate(refs):
                    other = safe_get_person(self.db, ref.ref)
                    if other is not None and birth_sort(other) > new_sort:
                        position = index
                        break
            refs.insert(position, child_ref)
            fam.set_child_ref_list(refs)

        find_target_family = self._find_target_family

        def reconcile_family(
            sf_handle: str, trans: Any, override: bool = False
        ) -> None:
            s_family = safe_get_family(source_db, sf_handle)
            if s_family is None:
                return
            s_father = s_family.get_father_handle()
            s_mother = s_family.get_mother_handle()
            t_father = best_target_person(s_father) if s_father else None
            t_mother = best_target_person(s_mother) if s_mother else None
            if t_father and t_father == t_mother:
                t_mother = None
            claimed = {handle for handle in (t_father, t_mother) if handle}
            t_children: list[tuple[ChildRef, str]] = []
            waiting: list[str] = []
            for handle, found in ((s_father, t_father), (s_mother, t_mother)):
                if handle and not found:
                    waiting.append(source_name(handle))
            for s_child_ref in s_family.get_child_ref_list():
                t_child = best_target_person(s_child_ref.ref)
                if t_child and t_child not in claimed:
                    t_children.append((s_child_ref, t_child))
                    claimed.add(t_child)
                elif not t_child:
                    waiting.append(source_name(s_child_ref.ref))

            label = family_label(s_family)

            # Name matches refused for their birth year: say who they were.
            refused_matches = self.context.get("refused_matches") or {}
            linked_children = {ref.ref for ref, _t in t_children}
            not_found = [
                handle
                for handle, found in ((s_father, t_father), (s_mother, t_mother))
                if handle and not found
            ] + [
                ref.ref
                for ref in s_family.get_child_ref_list()
                if ref.ref not in linked_children
            ]
            for s_rel in not_found:
                t_rel = refused_matches.get(s_rel)
                if not t_rel or t_rel in claimed:
                    continue
                s_year = person_birth_year(source_db, safe_get_person(source_db, s_rel))
                t_year = person_birth_year(self.db, safe_get_person(self.db, t_rel))
                link_summary.append(
                    {
                        "status": "conflict",
                        "family": label,
                        "detail": _(
                            "%(tree)s (born %(tyear)d) may be %(incoming)s "
                            "(born %(syear)d), but their birth years are "
                            "%(gap)d years apart; not linked"
                        )
                        % {
                            "tree": target_name(t_rel),
                            "tyear": t_year,
                            "incoming": source_name(s_rel),
                            "syear": s_year,
                            "gap": abs(s_year - t_year),
                        },
                    }
                )

            # A parent born too short or too long a time before a child is
            # not that child's parent, whoever the match says it is.
            age_conflicts: list[str] = []
            child_years = [
                (t_child, person_birth_year(self.db, safe_get_person(self.db, t_child)))
                for _ref, t_child in t_children
            ]
            for role in ("father", "mother"):
                t_parent = t_father if role == "father" else t_mother
                if not t_parent:
                    continue
                parent_year = person_birth_year(
                    self.db, safe_get_person(self.db, t_parent)
                )
                for t_child, child_year in child_years:
                    if parent_age_problem(parent_year, child_year):
                        age_conflicts.append(
                            _(
                                "%(parent)s (born %(pyear)d) cannot be a parent "
                                "of %(child)s (born %(cyear)d); not linked"
                            )
                            % {
                                "parent": target_name(t_parent),
                                "pyear": parent_year,
                                "child": target_name(t_child),
                                "cyear": child_year,
                            }
                        )
                        if role == "father":
                            t_father = None
                        else:
                            t_mother = None
                        break
            for text in age_conflicts:
                link_summary.append(
                    {"status": "conflict", "family": label, "detail": text}
                )
            claimed = {handle for handle in (t_father, t_mother) if handle}
            claimed.update(t_child for _ref, t_child in t_children)
            if len(claimed) < 2:
                # Nobody to link to yet; the family is built when more of
                # its members are in the tree.
                link_summary.append(
                    {"status": "waiting", "family": label, "detail": ", ".join(waiting)}
                )
                return

            fam = find_target_family(
                t_father,
                t_mother,
                [handle for _ref, handle in t_children],
                bool(s_father),
                bool(s_mother),
            )
            created = fam is None
            if fam is None:
                fam = Family()
                self.db.add_family(fam, trans)
            linked: list[str] = []
            conflicts: list[str] = []

            for role, t_handle in (("father", t_father), ("mother", t_mother)):
                if not t_handle:
                    continue
                current = (
                    fam.get_father_handle()
                    if role == "father"
                    else fam.get_mother_handle()
                )
                if current and current != t_handle:
                    conflicts.append(
                        _("%s: the family already has someone else in that place")
                        % target_name(t_handle)
                    )
                    continue
                if not current:
                    if role == "father":
                        fam.set_father_handle(t_handle)
                    else:
                        fam.set_mother_handle(t_handle)
                    linked.append(target_name(t_handle))
                parent = safe_get_person(self.db, t_handle)
                if (
                    parent is not None
                    and fam.handle not in parent.get_family_handle_list()
                ):
                    parent.add_family_handle(fam.handle)
                    self.db.commit_person(parent, trans)
                    if target_name(t_handle) not in linked:
                        linked.append(target_name(t_handle))

            members = {ref.ref for ref in fam.get_child_ref_list()}
            for s_child_ref, t_child in t_children:
                child = safe_get_person(self.db, t_child)
                if child is None:
                    continue
                parent_families = child.get_parent_family_handle_list()
                if parent_families and fam.handle not in parent_families:
                    conflicts.append(
                        _("%s already has other parents in the tree")
                        % target_name(t_child)
                    )
                    continue
                changed = False
                if t_child not in members:
                    new_ref = copy.deepcopy(s_child_ref)
                    new_ref.ref = t_child
                    remap_citations_notes(new_ref)
                    insert_child_by_birth(fam, new_ref, child)
                    members.add(t_child)
                    changed = True
                if fam.handle not in parent_families:
                    child.add_parent_family_handle(fam.handle)
                    self.db.commit_person(child, trans)
                    changed = True
                if changed:
                    linked.append(target_name(t_child))

            if created:
                extras = copy.deepcopy(s_family)
                copy_note_list(extras, trans)
                copy_citation_list(extras, trans)
                copy_media_refs(extras, trans)
                fam.set_note_list(extras.get_note_list())
                fam.set_citation_list(extras.get_citation_list())
                fam.set_media_list(extras.get_media_list())
                for attribute in extras.get_attribute_list():
                    remap_citations_notes(attribute)
                    fam.add_attribute(attribute)
                fam.set_privacy(s_family.get_privacy())
            else:
                copy_new_citations(fam, s_family, trans)
            if (
                created
                or fam.get_relationship() == FamilyRelType.UNKNOWN
                or (override and s_family.get_relationship() != FamilyRelType.UNKNOWN)
            ):
                fam.set_relationship(s_family.get_relationship())

            known = {
                event_signature(self.db, ref.ref) for ref in fam.get_event_ref_list()
            }
            for s_event_ref in s_family.get_event_ref_list():
                signature = event_signature(source_db, s_event_ref.ref)
                if signature is None or signature in known:
                    continue
                t_event = copy_event(s_event_ref.ref, trans)
                if t_event:
                    fam.add_event_ref(
                        copy_event_ref(s_event_ref.ref, t_event, trans, owner=s_family)
                    )
                    known.add(signature)
                    if _("family events") not in linked:
                        linked.append(_("family events"))
            self.db.commit_family(fam, trans)

            if created or linked:
                link_summary.append(
                    {
                        "status": "created" if created else "linked",
                        "family": label,
                        "detail": ", ".join(linked),
                    }
                )
            if waiting:
                link_summary.append(
                    {"status": "waiting", "family": label, "detail": ", ".join(waiting)}
                )
            for text in conflicts:
                link_summary.append(
                    {"status": "conflict", "family": label, "detail": text}
                )

        def link_families_for(s_person_obj: Person, trans: Any) -> None:
            """Link every family the incoming person belongs to."""
            family_handles = list(s_person_obj.get_parent_family_handle_list()) + list(
                s_person_obj.get_family_handle_list()
            )
            for sf_handle in family_handles:
                try:
                    reconcile_family(sf_handle, trans)
                except Exception:  # pylint: disable=broad-except
                    LOG.warning("Could not link family %s", sf_handle, exc_info=True)
                    link_summary.append(
                        {
                            "status": "conflict",
                            "family": sf_handle,
                            "detail": _("could not be linked (see the log)"),
                        }
                    )

        def copy_extra_item(
            kind: str, index: int, t_person_obj: Person, trans: Any
        ) -> None:
            """
            Add the incoming person's alternate name, attribute, address or
            note number ``index`` to the tree person, unless the tree person
            already has the same item.
            """
            wanted = dict(extra_items(kind, s_person, source_db)).get(index)
            if wanted is None:
                return
            if any(
                same_extra_item(kind, wanted, source_db, item, self.db)
                for _index, item in extra_items(kind, t_person_obj, self.db)
            ):
                return
            if kind == "note":
                new_handle = copy_note(s_person.get_note_list()[index], trans)
                if new_handle and new_handle not in t_person_obj.get_note_list():
                    t_person_obj.add_note(new_handle)
                return
            if kind == "media":
                s_ref = s_person.get_media_list()[index]
                new_handle = copy_media(s_ref.get_reference_handle(), trans)
                if new_handle:
                    new_ref = copy.deepcopy(s_ref)
                    new_ref.set_reference_handle(new_handle)
                    remap_citations_notes(new_ref)
                    for attribute in new_ref.get_attribute_list():
                        remap_citations_notes(attribute)
                    t_person_obj.add_media_reference(new_ref)
                return
            new_item = copy.deepcopy(wanted)
            remap_citations_notes(new_item)
            if kind == "lds":
                # An ordinance of a person's own; the sealing-to-parents
                # family is not carried over.
                new_item.set_place_handle(
                    get_or_create_place(new_item.get_place_handle(), trans) or ""
                )
                new_item.set_family_handle(None)
                t_person_obj.add_lds_ord(new_item)
            elif kind == "altname":
                t_person_obj.add_alternate_name(new_item)
            elif kind == "attribute":
                t_person_obj.add_attribute(new_item)
            elif kind == "url":
                t_person_obj.add_url(new_item)
            else:
                t_person_obj.add_address(new_item)

        def copy_new_person(s_obj: Person, trans: Any) -> str:
            """
            Add a copy of the incoming person ``s_obj`` to the tree: its
            events, names, attributes and the objects they refer to, but no
            family links (linking its families makes those).

            :returns: The new person's handle.
            """
            new_person = copy.deepcopy(s_obj)
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
            # Media references and their citations were copied by
            # resolve_references_for_person.
            for ordinance in new_person.get_lds_ord_list():
                remap_citations_notes(ordinance)
                ordinance.set_place_handle(
                    get_or_create_place(ordinance.get_place_handle(), trans) or ""
                )
                ordinance.set_family_handle(None)

            new_person.set_family_handle_list([])
            new_person.set_parent_family_handle_list([])
            new_person.set_person_ref_list([])
            new_person.set_tag_list([])

            self.db.add_person(new_person, trans)
            LOG.info("Added new person: %s", new_person.handle)
            return new_person.handle

        # ------------------------------------------------------------------
        # Adding relatives the tree lacks (``add_missing_relatives``).
        #
        # Only the incoming person's own parents, spouses and children are
        # added, never their relatives in turn. Someone the matcher refused
        # only for a birth year is not added either: they may well be the
        # tree's person, and the link summary names them so the user can
        # decide.
        # ------------------------------------------------------------------
        added_families: list[str] = []

        def source_family_with(s_obj: Person, s_rel: str) -> Family | None:
            """Return the incoming family that holds both people, if any."""
            for sf_handle in list(s_obj.get_parent_family_handle_list()) + list(
                s_obj.get_family_handle_list()
            ):
                s_family = safe_get_family(source_db, sf_handle)
                if s_family is None:
                    continue
                members = {
                    s_family.get_father_handle(),
                    s_family.get_mother_handle(),
                } | {ref.ref for ref in s_family.get_child_ref_list()}
                if s_rel in members:
                    return s_family
            return None

        def add_missing_relative(
            s_rel: str | None, role: str, s_obj: Person, trans: Any
        ) -> str | None:
            """
            Return the tree person for the relative ``s_rel`` of ``s_obj``,
            adding them as a new person when the tree has nobody for them.

            :param role: "parent", "spouse" or "child", from ``s_obj``'s
                point of view.
            :returns: The tree person's handle, or None when the relative is
                not in the tree and was not added.
            """
            if not s_rel or s_rel == s_obj.handle:
                return None
            found = best_target_person(s_rel)
            if found or not add_missing_relatives:
                return found
            if s_rel in (self.context.get("refused_matches") or {}):
                return None
            s_rel_obj = safe_get_person(source_db, s_rel)
            if s_rel_obj is None:
                return None
            s_family = source_family_with(s_obj, s_rel)
            label = family_label(s_family) if s_family else source_name(s_rel)
            rel_year = person_birth_year(source_db, s_rel_obj)
            own_year = person_birth_year(source_db, s_obj)
            if role == "parent":
                problem = parent_age_problem(rel_year, own_year)
            elif role == "child":
                problem = parent_age_problem(own_year, rel_year)
            else:
                problem = ""
            if problem:
                link_summary.append(
                    {
                        "status": "conflict",
                        "family": label,
                        "detail": _(
                            "%(name)s (born %(year)d) was not added: born too "
                            "far from %(other)s (born %(other_year)d) to be "
                            "their %(role)s"
                        )
                        % {
                            "name": source_name(s_rel),
                            "year": rel_year,
                            "other": source_name(s_obj.handle),
                            "other_year": own_year,
                            "role": _("parent") if role == "parent" else _("child"),
                        },
                    }
                )
                return None
            new_handle = copy_new_person(s_rel_obj, trans)
            person_map[s_rel] = new_handle
            added_relatives.append(new_handle)
            link_summary.append(
                {
                    "status": "added",
                    "family": label,
                    "detail": _("%s added as a new person") % source_name(s_rel),
                }
            )
            if s_family is not None and s_family.handle not in added_families:
                added_families.append(s_family.handle)
            return new_handle

        def add_missing_family_members(
            sf_handle: str, s_obj: Person, trans: Any
        ) -> None:
            """Add the missing spouse and children of a family ``s_obj`` heads."""
            s_family = safe_get_family(source_db, sf_handle)
            if s_family is None:
                return
            for handle in (s_family.get_father_handle(), s_family.get_mother_handle()):
                add_missing_relative(handle, "spouse", s_obj, trans)
            for ref in s_family.get_child_ref_list():
                add_missing_relative(ref.ref, "child", s_obj, trans)

        def add_missing_members(s_obj: Person, trans: Any) -> None:
            """Add the missing parents, spouses and children of ``s_obj``."""
            for sf_handle in s_obj.get_parent_family_handle_list():
                s_family = safe_get_family(source_db, sf_handle)
                if s_family is None:
                    continue
                for handle in (
                    s_family.get_father_handle(),
                    s_family.get_mother_handle(),
                ):
                    add_missing_relative(handle, "parent", s_obj, trans)
            for sf_handle in s_obj.get_family_handle_list():
                add_missing_family_members(sf_handle, s_obj, trans)

        with DbTxn(_("GWizard Data Merge"), self.db) as trans:
            if target_person_handle is None:
                # Add as entirely new person
                person_map[s_person.handle] = copy_new_person(s_person, trans)
                if link_families:
                    if add_missing_relatives:
                        add_missing_members(s_person, trans)
                    link_families_for(s_person, trans)
            else:
                # Merge into existing target person
                t_person = safe_get_person(self.db, target_person_handle)
                if not t_person:
                    return False

                # Apply choices. A merge never loses name detail: an incoming
                # given name or surname that the tree's already holds (the
                # same words, initials matching whole words) leaves it as it
                # is, and a name that is replaced is kept as an "Also Known
                # As" name.
                old_name = copy.deepcopy(t_person.get_primary_name())
                # 1. Given Name
                if resolutions.get("given_name") == "source":
                    s_given = str(s_person.get_primary_name().first_name or "").strip()
                    t_given = str(t_person.get_primary_name().first_name or "").strip()
                    if not name_covers(t_given, s_given):
                        t_person.get_primary_name().first_name = s_given

                # 2. Surname
                if resolutions.get("surname") == "source":
                    s_surname = surname_text(s_person.get_primary_name())
                    t_surname = surname_text(t_person.get_primary_name())
                    if not name_covers(t_surname, s_surname):
                        # Clear target surname list and copy source list
                        t_person.get_primary_name().surname_list = copy.deepcopy(
                            s_person.get_primary_name().surname_list
                        )
                keep_replaced_name(t_person, old_name)

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
                        # An empty incoming prefix does not clear the tree's.
                        if idx < len(s_list) and s_list[idx].get_prefix().strip():
                            t_surn.set_prefix(s_list[idx].get_prefix())

                # 2c. Nickname and call name (an empty incoming value keeps
                # the tree's: a merge never blanks a field)
                if resolutions.get("nickname") == "source":
                    s_nick = s_person.get_primary_name().get_nick_name().strip()
                    if s_nick:
                        t_person.get_primary_name().set_nick_name(s_nick)
                if resolutions.get("call_name") == "source":
                    s_call = s_person.get_primary_name().get_call_name().strip()
                    if s_call:
                        t_person.get_primary_name().set_call_name(s_call)

                # 2d. Citations on the primary name and on the person
                if resolutions.get("name_sources") == "source":
                    copy_new_citations(
                        t_person.get_primary_name(), s_person.get_primary_name(), trans
                    )
                if resolutions.get("person_sources") == "source":
                    copy_new_citations(t_person, s_person, trans)

                # 3. Gender (an incoming Unknown does not replace a known one)
                if resolutions.get("gender") == "source" and (
                    s_person.get_gender() != Person.UNKNOWN
                    or t_person.get_gender() == Person.UNKNOWN
                ):
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

                def merge_or_replace_vital_event(
                    event_type_val: int,
                    resolution_val: str,
                ) -> None:
                    s_evt_h = get_source_event_handle(s_person, event_type_val)
                    if not s_evt_h:
                        return
                    s_evt = safe_get_event(source_db, s_evt_h)
                    if not s_evt:
                        return

                    t_ref = (
                        t_person.get_birth_ref()
                        if event_type_val == EventType.BIRTH
                        else t_person.get_death_ref()
                    )
                    t_evt_h = t_ref.ref if t_ref else None
                    t_evt = safe_get_event(self.db, t_evt_h) if t_evt_h else None

                    if t_evt and resolution_val == "alternate":
                        # Add the incoming event as an alternate, keeping
                        # the tree's primary event as it is.
                        new_evt_h = copy_event(s_evt_h, trans)
                        if new_evt_h:
                            t_person.add_event_ref(
                                copy_event_ref(
                                    s_evt_h, new_evt_h, trans, EventRoleType.PRIMARY
                                )
                            )
                        return

                    if t_evt and not event_shared(t_evt.handle, t_person.handle):
                        # Merge into the tree's own event, so the person
                        # keeps one birth (or death) and nothing the tree
                        # event holds is lost; merging again changes
                        # nothing more.
                        upgrade_tree_event(t_evt, s_evt, trans)
                        return

                    if t_evt:
                        # The tree event is shared with someone else, so it
                        # is left as it is: this person gets a merged copy
                        # in its place.
                        new_evt_h = copy_event(s_evt_h, trans)
                        if not new_evt_h:
                            return
                        new_evt = safe_get_event(self.db, new_evt_h)
                        if new_evt is None:
                            return
                        merge_into_copy(new_evt, t_evt, s_evt)
                        self.db.commit_event(new_evt, trans)
                        new_ref = copy_event_ref(
                            s_evt_h, new_evt_h, trans, EventRoleType.PRIMARY
                        )
                        # Swap the reference where it stands, so the
                        # person's birth and death positions stay right.
                        refs = t_person.get_event_ref_list()
                        for index, ref in enumerate(refs):
                            if ref.ref == t_evt.handle:
                                refs[index] = new_ref
                                break
                        else:
                            refs.append(new_ref)
                        if event_type_val == EventType.BIRTH:
                            t_person.set_birth_ref(new_ref)
                        else:
                            t_person.set_death_ref(new_ref)
                        return

                    # No such event in the tree: add the incoming one.
                    new_evt_h = copy_event(s_evt_h, trans)
                    if not new_evt_h:
                        return
                    new_ref = copy_event_ref(
                        s_evt_h, new_evt_h, trans, EventRoleType.PRIMARY
                    )
                    if event_type_val == EventType.BIRTH:
                        t_person.set_birth_ref(new_ref)
                    else:
                        t_person.set_death_ref(new_ref)

                # 4. Birth Event
                res_birth = resolutions.get("birth_event")
                if res_birth in ("source", "alternate"):
                    merge_or_replace_vital_event(EventType.BIRTH, res_birth)

                # 5. Death Event
                res_death = resolutions.get("death_event")
                if res_death in ("source", "alternate"):
                    merge_or_replace_vital_event(EventType.DEATH, res_death)

                # Helpers for field-level items beyond the standard rows
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

                def event_key(db: Any, event: Any) -> tuple[str, int, str, str]:
                    """Return an event's type, date, date text and place."""
                    place = safe_get_place(db, event.get_place_handle())
                    return (
                        str(event.get_type()),
                        event.get_date_object().get_sort_value(),
                        str(event.get_date_object()),
                        place_key(db, place) if place is not None else "",
                    )

                def same_event_on_person(s_evt_h: str) -> str | None:
                    """
                    Return the tree person's event that is the incoming
                    event again (same type, date and place), if any.
                    """
                    s_evt = safe_get_event(source_db, s_evt_h)
                    if s_evt is None:
                        return None
                    wanted = event_key(source_db, s_evt)
                    for ref in t_person.get_event_ref_list():
                        t_evt = safe_get_event(self.db, ref.ref)
                        if t_evt is not None and event_key(self.db, t_evt) == wanted:
                            return t_evt.handle
                    return None

                for key, res in resolutions.items():
                    if res != "source" or target_person_handle is None:
                        continue

                    # 6. Other events: key is "event:<source event handle>"
                    if key.startswith("event:"):
                        s_evt_h = key.split(":", 1)[1]
                        if s_evt_h in (s_birth_h, s_death_h):
                            continue
                        same = same_event_on_person(s_evt_h)
                        if same:
                            # The person already has this event (the same
                            # record merged again): add its citations and
                            # notes there instead of a second copy.
                            s_evt = safe_get_event(source_db, s_evt_h)
                            t_evt = safe_get_event(self.db, same)
                            if s_evt is not None and t_evt is not None:
                                upgrade_tree_event(t_evt, s_evt, trans)
                            continue
                        t_evt_h = copy_event(s_evt_h, trans)
                        if t_evt_h:
                            t_person.add_event_ref(
                                copy_event_ref(s_evt_h, t_evt_h, trans)
                            )
                        continue

                    # Alternate names, attributes, addresses and notes: the key
                    # is "<kind>:<index in the incoming person's list>".
                    if key.startswith("family:"):
                        family_keys.append(key.partition(":")[2])
                        continue

                    kind, _separator, raw_index = key.partition(":")
                    if kind in EXTRA_KINDS and raw_index.isdigit():
                        copy_extra_item(kind, int(raw_index), t_person, trans)
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
                        t_rel_h = add_missing_relative(
                            s_handle, "parent", s_person, trans
                        )
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
                        t_rel_h = add_missing_relative(
                            s_handle, "spouse", s_person, trans
                        )
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
                        t_rel_h = add_missing_relative(
                            s_handle, "child", s_person, trans
                        )
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
                        insert_child_by_birth(
                            child_fam, child_ref, safe_get_person(self.db, t_rel_h)
                        )
                        self.db.commit_family(child_fam, trans)
                        t_rel = safe_get_person(self.db, t_rel_h)
                        if t_rel:
                            t_rel.add_parent_family_handle(child_fam.handle)
                            self.db.commit_person(t_rel, trans)
                        continue

                self.db.commit_person(t_person, trans)
                LOG.info("Merged changes into person: %s", t_person.handle)
                person_map[s_person.handle] = t_person.handle
                if resolutions.get("link_families") == "source":
                    if add_missing_relatives:
                        add_missing_members(s_person, trans)
                    link_families_for(s_person, trans)
                # Families chosen one by one in the merge dialog; the person
                # is saved first so the families see their current record.
                for sf_handle in family_keys:
                    if add_missing_relatives:
                        add_missing_family_members(sf_handle, s_person, trans)
                    try:
                        reconcile_family(sf_handle, trans, override=True)
                    except Exception:  # pylint: disable=broad-except
                        LOG.warning(
                            "Could not merge family %s", sf_handle, exc_info=True
                        )
                        link_summary.append(
                            {
                                "status": "conflict",
                                "family": sf_handle,
                                "detail": _("could not be merged (see the log)"),
                            }
                        )

            # Families of relatives added on their own (a parent or spouse
            # chosen in the merge dialog): link them in full, so the
            # family's events and the other members already in the tree
            # come along too.
            for sf_handle in added_families:
                if sf_handle in family_keys:
                    continue
                try:
                    reconcile_family(sf_handle, trans)
                except Exception:  # pylint: disable=broad-except
                    LOG.warning("Could not link family %s", sf_handle, exc_info=True)

        return True
