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
WikiTree as a record source for the GWizard Record Scan.

Registered as a GENERAL plugin in category "GWizardRecordSource"; Gramps
calls ``load_on_reg`` at start-up and the Record Scan (in GWizard File
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
    "Id,Name,FirstName,MiddleName,MiddleInitial,RealName,LastNameAtBirth,"
    "LastNameCurrent,LastNameOther,LongName,ShortName,Gender,BirthDate,"
    "DeathDate,BirthDateDecade,DeathDateDecade"
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
        Search WikiTree for a person; the results of up to two searches are
        combined:

        * by given names, birth surname and birth year (within
          ``date_spread`` years), when the birth year is known. A person
          with a middle name is searched with it ("Thomas Lee"), and again
          with the first name alone when that finds nothing.
        * by first name and birth surname only, so a profile whose birth
          year differs (or is missing) is still found. It scores well at
          g/s and lower at g/s/b.
        """
        profiles: list[dict[str, Any]] = []
        if query.birth_year:
            first_names = [query.given]
            if query.given and query.middle:
                first_names.insert(0, f"{query.given} {query.middle}")
            for first_name in first_names:
                found = self._search(query, first_name, with_birth=True)
                if found:
                    profiles.extend(found)
                    break
        profiles.extend(self._search(query, query.given, with_birth=False))
        matches: dict[str, SourceMatch] = {}
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("Name"):
                match = self.to_match(profile)
                matches.setdefault(match.key, match)
        return list(matches.values())

    def _search(
        self, query: RecordQuery, first_name: str, with_birth: bool
    ) -> list[dict[str, Any]]:
        """One searchPerson request, with or without the birth year."""
        surname = query.surnames[0] if query.surnames else ""
        birth = str(query.birth_year) if with_birth and query.birth_year else ""
        return self.client().search_person(
            first_name=first_name,
            last_name=surname,
            birth_date=birth,
            date_spread=self.date_spread if birth else 0,
            limit=self.search_limit,
            raise_errors=True,
            fields=SEARCH_FIELDS,
        )

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
    """Offer WikiTree to the GWizard Record Scan."""
    return [WikiTreeSource()]
