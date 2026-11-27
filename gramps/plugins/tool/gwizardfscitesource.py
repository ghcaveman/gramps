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
What the FamilySearch record source knows about citations, for the GWizard
Citation Improvement Scan (see gramps/gen/gwizard/gwizard_filemerge_citationscan.py,
in gwizard_filemerge).

Registered as a GENERAL plugin in category "GWizardCitationSource".
FamilySearch has two kinds of page a citation can point at:

* a Family Tree person (ID like "KWCB-QZP"): the page of a citation of the
  "FamilySearch Family Tree" source the FamilySearch Merge creates, or a
  familysearch.org/tree/person/... address. These are the record source's
  keys: such a citation is flagged as citing a family tree (unless its
  source title already says so), the image and page checks meant for
  record citations are waived, and the person opens in the FamilySearch
  merge window.
* a historical record (familysearch.org/ark:/61903/1:1:...): a real
  record. A citation of one without an image is flagged, since
  FamilySearch often has the image.
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
from gramps.gen.gwizard.gwizard_base import RecordCandidate
from gramps.gen.gwizard.gwizard_filemerge_citationscan import (
    NO_MEDIA,
    PAGE_FRAGMENT,
    PAGE_SOURCE_TEXT,
    PART_RECORD,
    PART_SOURCE,
    RECORD_NO_MEDIA,
    SOURCE_TREE,
    CitationSource,
    Issue,
    citation_source_title,
    citation_text,
    is_tree_source_title,
    make_issue,
)
from gramps.gen.gwizard.gwizard_filemerge_recordscan import SourceMatch
from gramps.gen.gwizard.gwizardfsprovenance import SOURCE_TITLE
from gramps.gen.lib import Citation

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

# A Family Tree person ID: 4 + 3-4 letters/digits, with at least one letter
# (so "1900-1910" is not taken for one).
_PERSON_ID = r"(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{4}-[A-Z0-9]{3,4}"
_BARE_ID_RE = re.compile(rf"^\s*({_PERSON_ID})\s*$", re.IGNORECASE)
_TREE_URL_RE = re.compile(
    rf"familysearch\.org/(?:tree/person/(?:details/|about/|memories/)?|"
    rf"platform/tree/persons/|ark:/61903/4:1:)({_PERSON_ID})\b",
    re.IGNORECASE,
)
# A historical record: ark:/61903/1:1:XXXX-XXXX (3:1: for an image).
_RECORD_ARK_RE = re.compile(
    r"familysearch\.org/ark:/61903/1:1:([A-Z0-9]{4}-[A-Z0-9]{3,5})\b",
    re.IGNORECASE,
)
# Checks meant for record citations, not for a citation of a tree person.
WAIVED = frozenset({NO_MEDIA, PAGE_FRAGMENT, PAGE_SOURCE_TEXT})


def tree_person_ids(db: Any, citation: Citation) -> list[str]:
    """
    Return the Family Tree person IDs a citation cites: its page when it
    cites the "FamilySearch Family Tree" source, and any tree person
    address in its page, notes or attributes.
    """
    found: list[str] = []

    def add(value: str) -> None:
        value = value.upper()
        if value not in found:
            found.append(value)

    if citation_source_title(db, citation).strip() == SOURCE_TITLE:
        bare = _BARE_ID_RE.match(str(citation.get_page() or ""))
        if bare:
            add(bare.group(1))
    for match in _TREE_URL_RE.finditer(citation_text(db, citation)):
        add(match.group(1))
    return found


def record_arks(db: Any, citation: Citation) -> list[str]:
    """Return the FamilySearch historical record IDs a citation points at."""
    found: list[str] = []
    for match in _RECORD_ARK_RE.finditer(citation_text(db, citation)):
        ark = match.group(1).upper()
        if ark not in found:
            found.append(ark)
    return found


# ------------------------------------------------------------
#
# FamilySearchCitationSource
#
# ------------------------------------------------------------
class FamilySearchCitationSource(CitationSource):
    """FamilySearch's side of the Citation Improvement Scan."""

    source_id = "familysearch"

    def record_keys(self, db: Any, citation: Citation) -> list[str]:
        """Return the Family Tree person IDs the citation cites."""
        return tree_person_ids(db, citation)

    def extra_issues(self, db: Any, citation: Citation, keys: list[str]) -> list[Issue]:
        """
        A tree person is a family tree (unless the source title already
        says so); a historical record without an image may have one.
        """
        issues: list[Issue] = []
        if keys and not is_tree_source_title(citation_source_title(db, citation)):
            issues.append(
                make_issue(
                    SOURCE_TREE,
                    PART_SOURCE,
                    _(
                        "Cites FamilySearch Family Tree person %s, a family "
                        "tree; look for the records it is based on."
                    )
                    % ", ".join(keys),
                )
            )
        arks = record_arks(db, citation)
        if arks and not citation.get_media_list():
            issues.append(
                make_issue(
                    RECORD_NO_MEDIA,
                    PART_RECORD,
                    _(
                        "No image is attached; FamilySearch record %s may have "
                        "an image to download."
                    )
                    % ", ".join(arks),
                )
            )
        return issues

    def waived_issues(self, db: Any, citation: Citation, keys: list[str]) -> set[str]:
        """
        A tree-person citation needs no image, and its page is an ID; a
        citation that also names a historical record keeps the image check.
        """
        if not keys:
            return set()
        if record_arks(db, citation):
            return set(WAIVED - {NO_MEDIA})
        return set(WAIVED)

    def open_record(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        key: str,
        parent: Any = None,
    ) -> bool:
        """Open the cited tree person in the FamilySearch merge window."""
        if not person_handle:
            from gramps.gui.dialog import ErrorDialog

            ErrorDialog(
                _("GWizard FamilySearch Merge"),
                _("This citation is not attached to a person."),
                parent=parent,
            )
            return False
        from gramps.plugins.tool.gwizardfssource import FamilySearchSource

        match = SourceMatch(key=key, label=key, candidate=RecordCandidate())
        return FamilySearchSource().open_merge(
            dbstate, uistate, person_handle, match, parent=parent
        )


def load_on_reg(dbstate: Any, uistate: Any, plugin: Any) -> list[CitationSource]:
    """Offer FamilySearch's citation checks to the GWizard Citation Improvement Scan."""
    return [FamilySearchCitationSource()]
