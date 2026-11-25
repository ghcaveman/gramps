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
The National Archives Catalog (NARA) as a record source for the GWizard
Multi-Archive Record Scan.

Registered as a GENERAL plugin in category "GWizardRecordSource"; Gramps
calls ``load_on_reg`` at start-up and the Multi-Archive Record Scan (in GWizard File
Merge) lists NARA as a column group. Gramps imports this module at
start-up, so the NARA modules are only imported when they are used.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
import sys
from typing import Any
import re

# Helper to strip nicknames like "Fred" or (Buddy) from given names
_NICK_RE = re.compile(r'["\'].*?["\']|\(.*?\)')


def _clean_given_variants(given: str, middle: str) -> list[str]:
    variants = set()
    for raw in (given, f"{given} {middle}".strip()):
        cleaned = re.sub(r"\s+", " ", _NICK_RE.sub("", raw)).strip()
        if cleaned and not cleaned.lower().startswith(("unknown", "child", "baby")):
            variants.add(cleaned)
    # Also extract quoted nicknames as alternate given names (e.g., "Fred")
    for nick in re.findall(r'["\']([^"\']+)["\']', f"{given} {middle}"):
        if len(nick.strip()) > 1:
            variants.add(nick.strip())
    return sorted(variants)


def _is_range_folder(title: str, given_variants: list[str]) -> bool:
    """Return True if title is an alphabetical box range ('A THRU B') without the person's given name."""
    upper = title.upper()
    if " THRU " not in upper and not upper.startswith("NATURALIZATION INDEX"):
        return False
    return not any(
        tok.upper() in upper
        for g in given_variants
        for tok in g.split()
        if len(tok.strip(".")) > 2
    )


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

from gwizardnaraquerybuilder import build_nara_query, is_valid_nara_hit


def _record_query_to_ind(query: RecordQuery) -> dict[str, Any]:
    """Adapt a GWizard RecordQuery into the dict shape expected by gwizardnaraquerybuilder."""
    full_given = " ".join(part for part in (query.given, query.middle) if part).strip()
    birth_surname = query.surnames[0] if query.surnames else ""
    married_surnames = set(query.surnames[1:]) if len(query.surnames) > 1 else set()
    sex = {"male": "M", "female": "F"}.get(query.gender.casefold(), "")
    return {
        "names": (
            [f"{full_given} /{birth_surname}/"] if (full_given or birth_surname) else []
        ),
        "married_surnames": married_surnames,
        "sex": sex,
        "birth_year": query.birth_year,
        "death_year": query.death_year,
        "places": list(query.places),
        "tags": set(query.tags),
    }


# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizard_base import RecordQuery, score_record
from gramps.gen.gwizard.gwizard_filemerge_recordscan import (
    RecordSource,
    SourceMatch,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

NARA_URL = "https://catalog.archives.gov/id/%s"
# Years after a death that records (pensions, estates) are still searched.
RECORD_YEARS_AFTER_DEATH = 10


# ------------------------------------------------------------
#
# NaraSource
#
# ------------------------------------------------------------
class NaraSource(RecordSource):
    """Search the NARA catalog for records naming the people in the tree."""

    source_id = "nara"
    title = "NARA"
    min_interval = 1.0
    has_links = False
    # Records asked for per person; records whose best-named person scores
    # below min_score are dropped, which keeps the saved results small.
    search_limit = 20
    min_score = 50.0

    def __init__(self, client: Any = None) -> None:
        """Use ``client`` (a NaraCatalogInterface) or create one when needed."""
        self._client = client

    def client(self) -> Any:
        """Return the NARA catalog client."""
        if self._client is None:
            from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface

            self._client = NaraCatalogInterface()
        return self._client

    def available(self) -> tuple[bool, str]:
        """NARA needs an API key in NARA_API_KEY."""
        if self._client is None and not os.environ.get("NARA_API_KEY", "").strip():
            return False, _("Set the NARA_API_KEY environment variable to search NARA.")
        return True, ""

    @staticmethod
    def search_terms(query: RecordQuery) -> tuple[str, str, str]:
        """Return (keywords, first record year, last record year) for a person."""
        params = build_nara_query(_record_query_to_ind(query))
        if not params:
            return "", "", ""
        start = str(query.birth_year) if query.birth_year else ""
        end = (
            str(query.death_year + RECORD_YEARS_AFTER_DEATH) if query.death_year else ""
        )
        return params["q"], start, end

    def search(self, query: RecordQuery) -> list[SourceMatch]:
        """Search the catalog; each record is scored on its best-named person."""
        from gramps.gen.gwizard.gwizardnaramatch import best_match, record_candidate
        from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface

        ind = _record_query_to_ind(query)
        keywords, start, end = self.search_terms(query)
        if not keywords:
            return []
        client = self.client()
        response = client.search_records(
            query=keywords,
            rows=self.search_limit,
            start_year=start,
            end_year=end,
            level_of_description="item,fileUnit",
        )
        if response is None:
            raise RuntimeError(_("The NARA catalog search failed."))
        matches: list[SourceMatch] = []
        for hit in client.extract_hits(response):
            parsed = NaraCatalogInterface.parse_record(hit)
            title = str(parsed.get("title") or "")
            if not is_valid_nara_hit(title, ind):
                continue
            best = best_match(query, parsed)
            if best.candidate is None:
                continue
            candidate = record_candidate(best.candidate)
            if score_record(query, candidate).score < self.min_score:
                continue
            naid = str(parsed.get("naid") or "")
            display_title = title or naid
            if len(display_title) > 90:
                display_title = display_title[:87] + "..."
            matches.append(
                SourceMatch(
                    key=naid,
                    label=f"{display_title} [NAID {naid}]" if naid else display_title,
                    candidate=candidate,
                    url=NARA_URL % naid if naid else "",
                    data={"hit": hit},
                )
            )
        return matches

    def open_merge(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        match: SourceMatch,
        parent: Any = None,
    ) -> bool:
        """Open the NARA window on this record and review it for the person."""
        hit = match.data.get("hit")
        if not isinstance(hit, dict):
            from gramps.gui.dialog import ErrorDialog

            ErrorDialog(
                _("GWizard NARA Merge"),
                _("The saved result has no record details; scan this person again."),
                parent=parent,
            )
            return False
        from gramps.gui.gwizard.gwizardnaralauncher import open_nara_record

        return open_nara_record(
            uistate, dbstate, person_handle, hit, parent=parent, client=self.client()
        )

    def open_search(
        self, dbstate: Any, uistate: Any, person_handle: str, parent: Any = None
    ) -> bool:
        """Open the NARA search window with this person as the target."""
        from gramps.gui.gwizard.gwizardnaralauncher import NaraSearchDialog

        dialog = NaraSearchDialog(
            uistate=uistate,
            dbstate=dbstate,
            target_handle=person_handle,
            parent=parent,
            client=self._client,
        )
        try:
            dialog.run()
        finally:
            dialog.destroy()
        return True


def load_on_reg(dbstate: Any, uistate: Any, plugin: Any) -> list[RecordSource]:
    """Offer NARA to the GWizard Multi-Archive Record Scan."""
    return [NaraSource()]
