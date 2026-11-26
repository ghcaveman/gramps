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
WikiTree as a record source for the GWizard Multi-Archive Record Scan.

Registered as a GENERAL plugin in category "GWizardRecordSource"; Gramps
calls ``load_on_reg`` at start-up and the Multi-Archive Record Scan (in GWizard File
Merge) lists WikiTree as a column group. Gramps imports this module at
start-up, so the WikiTree modules are only imported when they are used.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import importlib.util
import logging
import os
import sys
from typing import Any

# As a standalone addon the sibling modules live in the addon directory, and
# the shared GWizard modules in the GWizard File Merge addon next to it;
# Gramps removes the addon directory from sys.path after import.
_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
for _path in (
    os.path.join(os.path.dirname(_ADDON_DIR), "GWizardFileMerge"),
    _ADDON_DIR,
):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizard_base import RecordQuery
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    RecordSource,
    SourceMatch,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

WIKITREE_URL = "https://www.wikitree.com/wiki/%s"
# Profile fields asked for in searches: everything matching and the result
# labels use. Without a field list WikiTree leaves some out (MiddleName).
SEARCH_FIELDS = (
    "Id,Name,FirstName,MiddleName,MiddleInitial,RealName,ColloquialName,"
    "Nicknames,LastNameAtBirth,LastNameBirth,LastNameCurrent,LastNameOther,"
    "LongName,ShortName,Gender,BirthDate,DeathDate,BirthDateDecade,"
    "DeathDateDecade,BirthLocation,DeathLocation"
)


# ------------------------------------------------------------
#
# WikiTreeSource
#
# ------------------------------------------------------------
class WikiTreeSource(RecordSource):
    """Search WikiTree profiles for the people in the Family Tree."""

    source_id = "wikitree"
    title = "WikiTree"
    min_interval = 1.0
    has_links = True
    # Profiles asked for per person, and the birth-year spread allowed.
    search_limit = 20
    date_spread = 2

    def __init__(self, client: Any = None) -> None:
        """Use ``client`` (a WikiTreeInterface) or create one when needed."""
        self._client = client

    def client(self) -> Any:
        """Return the WikiTree API client."""
        if self._client is None:
            from gramps.gen.gwizard.gwizardwikitree import WikiTreeInterface

            self._client = WikiTreeInterface()
        return self._client

    def available(self) -> tuple[bool, str]:
        """WikiTree needs the requests package."""
        if importlib.util.find_spec("requests") is None:
            return False, _("The Python package 'requests' is not installed.")
        return True, ""

    def linked_key(self, db: Any, person: Any) -> str:
        """Return the WikiTree ID stored on the person, if any."""
        from gramps.gen.gwizard.gwizardwikitree import get_wikitree_id

        return get_wikitree_id(person)

    def search(self, query: RecordQuery) -> list[SourceMatch]:
        """
        Progressive search cascade for RecordQuery (worker-thread safe):
        1. Given (+ middle) + birth surname + birth year (±2) + gender
        2. Given alone + birth surname + birth year (±2) (if middle name missed)
        3. Alternate surnames (married name, collapsed particles like Dilauro)
           or inline nicknames (Mamie, King, Buzz) with birth year
        4. Dateless fallback (first + birth surname) only when birth year is
           missing or Tiers 1-3 returned zero hits.
        """
        from gramps.gen.gwizard.gwizardwikitreenorm import build_search_plan

        plan = build_search_plan(query)
        if plan.skip:
            return []

        profiles: list[dict[str, Any]] = []
        primary_surname = plan.surnames[0]
        full_given = f"{plan.given} {plan.middle}".strip() if plan.middle else plan.given

        def _run(
            fn: str,
            ln: str,
            birth_yr: int | None = None,
            spread: int = 0,
            last_name_match: str = "all",
        ) -> list[dict[str, Any]]:
            kwargs: dict[str, Any] = {
                "first_name": fn,
                "last_name": ln,
                "birth_date": str(birth_yr) if birth_yr else "",
                "date_spread": spread if birth_yr else 0,
                "limit": self.search_limit,
                "raise_errors": True,
                "fields": SEARCH_FIELDS,
                "lastNameMatch": last_name_match,
            }
            if plan.gender:
                kwargs["Gender"] = plan.gender
            return self.client().search_person(**kwargs)

        # Tier 1 & 2: Birth year search (full given first, then first name alone)
        if plan.birth_year:
            for fn in dict.fromkeys([full_given, plan.given]):
                found = _run(
                    fn,
                    primary_surname,
                    birth_yr=plan.birth_year,
                    spread=plan.date_spread,
                )
                if found:
                    profiles.extend(found)
                    break

        # Tier 3: Alternate surnames (married names / particle variants) & nicknames
        if not profiles:
            for alt_ln in plan.surnames[1:]:
                profiles.extend(
                    _run(
                        plan.given,
                        alt_ln,
                        birth_yr=plan.birth_year,
                        spread=plan.date_spread,
                    )
                )
            for nick in plan.nicknames:
                if nick.casefold() != plan.given.casefold():
                    profiles.extend(
                        _run(
                            nick,
                            primary_surname,
                            birth_yr=plan.birth_year,
                            spread=plan.date_spread,
                        )
                    )

        # Tier 4: Dateless fallback ONLY when birth_year is absent or Tiers 1-3 found 0
        if not profiles:
            profiles.extend(_run(plan.given, primary_surname))

        matches: dict[str, SourceMatch] = {}
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("Name"):
                match = self.to_match(profile)
                matches.setdefault(match.key, match)
        return list(matches.values())
    
    def lookup(self, key: str) -> SourceMatch | None:
        """Return the profile the person is linked to."""
        profile = self.client().get_person(key, raise_errors=True)
        return self.to_match(profile) if profile else None

    @staticmethod
    def to_match(profile: dict[str, Any]) -> SourceMatch:
        """Return a WikiTree profile as a SourceMatch."""
        from gramps.gen.gwizard.gwizardwikitreematch import candidate_from_profile

        key = str(profile.get("Name") or profile.get("Id") or "")
        name = str(
            profile.get("LongName")
            or profile.get("ShortName")
            or " ".join(
                str(profile.get(k) or "")
                for k in ("FirstName", "MiddleName", "LastNameAtBirth")
                if profile.get(k)
            )
        ).strip()
        years = []
        for date_key, decade_key in (
            ("BirthDate", "BirthDateDecade"),
            ("DeathDate", "DeathDateDecade"),
        ):
            date = str(profile.get(date_key) or "")[:4]
            if date.isdigit() and int(date) > 0:
                years.append(date)
            else:
                years.append(str(profile.get(decade_key) or ""))
        span = "–".join(years) if any(years) else ""
        label = f"{name} ({span})" if span else name
        return SourceMatch(
            key=key,
            label=f"{label} [{key}]" if key else label,
            candidate=candidate_from_profile(profile),
            url=WIKITREE_URL % key if key else "",
        )

    def open_merge(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        match: SourceMatch,
        parent: Any = None,
    ) -> bool:
        """Load the profile and open the WikiTree merge window."""
        from gramps.gui.gwizard.gwizardwikitreelauncher import merge_wikitree_profile

        merged, message = merge_wikitree_profile(
            dbstate,
            match.key,
            person_handle,
            parent=parent,
            client=self.client(),
        )
        if not merged and message:
            from gramps.gui.dialog import ErrorDialog

            ErrorDialog(_("GWizard WikiTree Merge"), message, parent=parent)
        return merged

    def open_search(
        self, dbstate: Any, uistate: Any, person_handle: str, parent: Any = None
    ) -> bool:
        """Open the WikiTree search window with this person as the target."""
        from gramps.gui.gwizard.gwizardwikitreelauncher import WikiTreeSearchDialog

        dialog = WikiTreeSearchDialog(
            uistate=uistate,
            dbstate=dbstate,
            target_handle=person_handle,
            parent=parent,
        )
        try:
            dialog.run()
        finally:
            dialog.destroy()
        return True


def load_on_reg(dbstate: Any, uistate: Any, plugin: Any) -> list[RecordSource]:
    """Offer WikiTree to the GWizard Multi-Archive Record Scan."""
    return [WikiTreeSource()]
