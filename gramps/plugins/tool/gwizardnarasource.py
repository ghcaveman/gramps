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
Record Scan.

Registered as a GENERAL plugin in category "GWizardRecordSource"; Gramps
calls ``load_on_reg`` at start-up and the Record Scan (in GWizard File
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
        """
        Return (keywords, first record year, last record year) for a person:
        the first given name and birth surname, records from the birth year
        to some years after the death.
        """
        surname = query.surnames[0] if query.surnames else ""
        keywords = " ".join(part for part in (query.given, surname) if part)
        start = str(query.birth_year) if query.birth_year else ""
        end = (
            str(query.death_year + RECORD_YEARS_AFTER_DEATH) if query.death_year else ""
        )
        return keywords, start, end

    def search(self, query: RecordQuery) -> list[SourceMatch]:
        """Search the catalog; each record is scored on its best-named person."""
        from gramps.gen.gwizard.gwizardnaramatch import best_match, record_candidate
        from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface

        keywords, start, end = self.search_terms(query)
        if not keywords:
            return []
        client = self.client()
        response = client.search_records(
            query=keywords, rows=self.search_limit, start_year=start, end_year=end
        )
        if response is None:
            raise RuntimeError(_("The NARA catalog search failed."))
        matches: list[SourceMatch] = []
        for hit in client.extract_hits(response):
            parsed = NaraCatalogInterface.parse_record(hit)
            best = best_match(query, parsed)
            if best.candidate is None:
                continue
            candidate = record_candidate(best.candidate)
            if score_record(query, candidate).score < self.min_score:
                continue
            naid = str(parsed.get("naid") or "")
            title = str(parsed.get("title") or naid)
            if len(title) > 90:
                title = title[:87] + "..."
            matches.append(
                SourceMatch(
                    key=naid,
                    label=f"{title} [NAID {naid}]" if naid else title,
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
    """Offer NARA to the GWizard Record Scan."""
    return [NaraSource()]
