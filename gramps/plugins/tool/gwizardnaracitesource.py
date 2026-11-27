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
What the NARA record source knows about citations, for the GWizard Multi-Archive
Citation Scan (see gramps/gen/gwizard/gwizard_filemerge_citationscan.py,
in gwizard_filemerge).

Registered as a GENERAL plugin in category "GWizardCitationSource". It
reads the NAID attribute the NARA Merge puts on its citations, flags a
NARA citation without images, judges how well a NARA record fits a
citation (title, series and date range), and opens a cited record in the
NARA window to bring in its images.
"""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
import re
import sys
from typing import Any

# As a standalone addon the sibling modules live in the addon directory and
# the shared GWizard modules (the scan engine included) in the GWizard File
# Merge addon; Gramps removes the addon directory from sys.path after import.
_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
for _name in ("GWizardFileMerge", ""):
    _path = os.path.join(os.path.dirname(_ADDON_DIR), _name) if _name else _ADDON_DIR
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.gwizard.gwizard_filemerge_recordscan import SourceMatch
from gramps.gen.lib import Citation
from gramps.gen.gwizard.gwizard_filemerge_citationscan import (
    PART_RECORD,
    RECORD_NO_MEDIA,
    CitationItem,
    CitationSource,
    Issue,
    make_issue,
    text_relevance,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# The NARA Merge's citation attribute (gwizardnaramerge.NAID_ATTRIBUTE);
# repeated here so Gramps start-up does not import the NARA client.
NAID_ATTRIBUTE = "NAID"
_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20[0-4]\d)\b")


# ------------------------------------------------------------
#
# NaraCitationSource
#
# ------------------------------------------------------------
class NaraCitationSource(CitationSource):
    """NARA's side of the Multi-Archive Citation Scan."""

    source_id = "nara"

    def __init__(self, client: Any = None) -> None:
        """Use ``client`` (a NaraCatalogInterface) or create one when needed."""
        self._client = client

    def client(self) -> Any:
        """Return the NARA catalog client."""
        if self._client is None:
            from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface

            self._client = NaraCatalogInterface()
        return self._client

    def record_keys(self, db: Any, citation: Citation) -> list[str]:
        """Return the NAIDs on the citation's NAID attributes."""
        keys: list[str] = []
        for attribute in citation.get_attribute_list():
            if str(attribute.get_type()) == NAID_ATTRIBUTE:
                naid = str(attribute.get_value() or "").strip()
                if naid and naid not in keys:
                    keys.append(naid)
        return keys

    def extra_issues(self, db: Any, citation: Citation, keys: list[str]) -> list[Issue]:
        """A NARA citation with no image: NARA may have the images."""
        if keys and not citation.get_media_list():
            return [
                make_issue(
                    RECORD_NO_MEDIA,
                    PART_RECORD,
                    _(
                        "No image is attached; NARA record %s may have images "
                        "to download."
                    )
                    % ", ".join(keys),
                )
            ]
        return []

    def relevance(self, item: CitationItem, match: SourceMatch) -> float:
        """
        Judge a NARA record by its title, series and description, and by
        whether the citation's year is within its date range.
        """
        hit = match.data.get("hit") if isinstance(match.data, dict) else None
        if not isinstance(hit, dict):
            return text_relevance(item, match.label)
        from gramps.gen.gwizard.gwizardnaramerge import NaraCatalogInterface

        try:
            parsed = NaraCatalogInterface.parse_record(hit)
        except Exception:
            return text_relevance(item, match.label)
        text = " ".join(
            str(parsed.get(key) or "")
            for key in ("title", "series_title", "scope_note", "material_type")
        )
        years = [int(y) for y in _YEAR_RE.findall(str(parsed.get("date_str") or ""))]
        return text_relevance(item, text, years)

    def open_record(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        key: str,
        parent: Any = None,
    ) -> bool:
        """
        Fetch a cited record by its NAID (one NARA query) and open it in
        the NARA window for the person, to add the images not yet in the
        tree.
        """
        from gramps.gui.dialog import ErrorDialog

        if not person_handle:
            ErrorDialog(
                _("GWizard NARA Merge"),
                _("This citation is not attached to a person."),
                parent=parent,
            )
            return False
        hit = self.client().fetch_record(key)
        if hit is None:
            ErrorDialog(
                _("GWizard NARA Merge"),
                _("NARA record %s could not be fetched.") % key,
                parent=parent,
            )
            return False
        from gramps.gui.gwizard.gwizardnaralauncher import open_nara_record

        return open_nara_record(
            uistate, dbstate, person_handle, hit, parent=parent, client=self.client()
        )


def load_on_reg(dbstate: Any, uistate: Any, plugin: Any) -> list[CitationSource]:
    """Offer NARA's citation checks to the GWizard Multi-Archive Citation Scan."""
    return [NaraCitationSource()]
