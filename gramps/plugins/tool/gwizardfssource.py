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
FamilySearch as a record source for the GWizard Multi-Archive Record Scan.

Registered as a GENERAL plugin in category 'GWizardRecordSource'; Gramps
calls load_on_reg at start-up and the Multi-Archive Record Scan lists
FamilySearch as an available archive column.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import re
from typing import Any

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizard_base import (
    RecordCandidate,
    RecordQuery,
    year_range,
)
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    RecordSource,
    SourceMatch,
)
from gramps.gen.gwizard.gwizardfamilysearch import (
    FamilySearchInterface,
    extract_familysearch_id,
    get_familysearch_id,
)
from gramps.gen.gwizard.gwizardfsprovenance import profile_url

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(\d{4})\b")


# ------------------------------------------------------------
#
# Matching & Candidate conversion
#
# ------------------------------------------------------------
def _extract_years_from_life(
    life_str: str,
) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """
    Extract birth and death year ranges from a lifespan string.

    :param life_str: E.g. "1809 - 1865", "1809-", or "1900".
    :returns: Tuple of (birth_years, death_years).
    """
    if not life_str:
        return None, None

    tokens = [t.strip() for t in life_str.split("-")]
    birth_years = None
    death_years = None

    if tokens:
        m1 = _YEAR_RE.search(tokens[0])
        if m1:
            try:
                y = int(m1.group(1))
                birth_years = year_range(y)
            except (ValueError, TypeError):
                pass

    if len(tokens) > 1:
        m2 = _YEAR_RE.search(tokens[1])
        if m2:
            try:
                y = int(m2.group(1))
                death_years = year_range(y)
            except (ValueError, TypeError):
                pass

    return birth_years, death_years


def candidate_from_fs_result(res: dict[str, Any]) -> RecordCandidate:
    """
    Convert a FamilySearch search result into a RecordCandidate for scoring.

    :param res: FamilySearch search result dictionary.
    :returns: RecordCandidate instance.
    :rtype: RecordCandidate
    """
    name_str = str(res.get("name") or "").strip()
    given = ""
    surnames: list[str] = []

    if name_str:
        tokens = name_str.split()
        if len(tokens) == 1:
            given = tokens[0]
        elif len(tokens) > 1:
            given = " ".join(tokens[:-1])
            surnames.append(tokens[-1])

    life_str = str(res.get("life") or "")
    birth_years, death_years = _extract_years_from_life(life_str)

    return RecordCandidate(
        given=given,
        surnames=surnames,
        birth_years=birth_years,
        death_years=death_years,
    )


# ------------------------------------------------------------
#
# FamilySearchSource
#
# ------------------------------------------------------------
class FamilySearchSource(RecordSource):
    """Search FamilySearch profiles for people in the Family Tree."""

    source_id = "familysearch"
    title = "FamilySearch"
    min_interval = 0.5
    has_links = True
    search_limit = 20
    date_spread = 2

    def __init__(self, client: Any = None) -> None:
        """Initialize with an optional FamilySearchInterface client."""
        self._client = client

    def client(self) -> FamilySearchInterface:
        """Return the FamilySearch API client."""
        if self._client is None:
            self._client = FamilySearchInterface()
        return self._client

    def available(self) -> tuple[bool, str]:
        """FamilySearch is available when configured."""
        return True, ""

    def linked_key(self, db: Any, person: Any) -> str:
        """Return the FamilySearch ID stored on the person, if any."""
        return get_familysearch_id(person)

    def search(self, query: RecordQuery) -> list[SourceMatch]:
        """
        Search FamilySearch for candidates matching the query.

        :param query: RecordQuery from the Multi-Archive Record Scan.
        :returns: List of SourceMatch candidates.
        """
        surname = query.surnames[0] if query.surnames else ""
        birth = str(query.birth_year) if query.birth_year else ""

        results = self.client().search_person(
            first_name=query.given,
            last_name=surname,
            birth_date=birth,
            limit=self.search_limit,
        )

        matches: dict[str, SourceMatch] = {}
        for res in results:
            fid = res.get("fsid")
            if not fid:
                continue
            match = self.to_match(res)
            matches.setdefault(match.key, match)

        return list(matches.values())

    def lookup(self, key: str) -> SourceMatch | None:
        """Return the profile the person is linked to."""
        clean_key = extract_familysearch_id(key) or key.strip().upper()
        if not clean_key:
            return None
        return SourceMatch(
            key=clean_key,
            label=f"{clean_key} [{clean_key}]",
            candidate=RecordCandidate(),
            url=profile_url(clean_key),
        )

    @staticmethod
    def to_match(res: dict[str, Any]) -> SourceMatch:
        """Return a FamilySearch result dict as a SourceMatch."""
        fid = str(res.get("fsid") or "").strip().upper()
        name = str(res.get("name") or fid).strip()
        life = str(res.get("life") or "").strip()
        span_str = f" ({life})" if life else ""
        label = f"{name}{span_str} [{fid}]"

        return SourceMatch(
            key=fid,
            label=label,
            candidate=candidate_from_fs_result(res),
            url=profile_url(fid) if fid else "",
        )

    def open_merge(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        match: SourceMatch,
        parent: Any = None,
    ) -> bool:
        """Open the FamilySearch merge dialog."""
        from gramps.gui.gwizard.gwizardfslauncher import merge_familysearch_person

        merged, message = merge_familysearch_person(
            dbstate,
            match.key,
            person_handle,
            parent=parent,
            client=self.client(),
        )
        if not merged and message:
            try:
                from gramps.gui.dialog import ErrorDialog

                ErrorDialog(_("GWizard FamilySearch Merge"), message, parent=parent)
            except Exception:
                LOG.error("%s: %s", _("GWizard FamilySearch Merge"), message)
        return merged

    def open_search(
        self, dbstate: Any, uistate: Any, person_handle: str, parent: Any = None
    ) -> bool:
        """Open the FamilySearch search dialog for this person."""
        from gramps.gui.gwizard.gwizardfslauncher import FamilySearchSearchDialog

        dialog = FamilySearchSearchDialog(
            uistate=uistate,
            dbstate=dbstate,
            target_handle=person_handle,
            parent=parent,
            client=self.client(),
        )
        try:
            dialog.run()
        finally:
            dialog.destroy()
        return True


def load_on_reg(dbstate: Any, uistate: Any, plugin: Any) -> list[RecordSource]:
    """Register FamilySearch into the GWizard Multi-Archive Record Scan."""
    return [FamilySearchSource()]
