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
What the WikiTree record source knows about citations, for the GWizard
Multi-Archive Citation Scan (see gramps/gen/gwizard/gwizard_filemerge_citationscan.py,
in gwizard_filemerge).

Registered as a GENERAL plugin in category "GWizardCitationSource". It
finds the WikiTree profile a citation cites: the page of a citation of the
"WikiTree" source the WikiTree Merge creates (the bare profile ID), or a
wikitree.com/wiki/ profile address in any citation's page, notes or
attributes. A WikiTree profile is a family tree, not a record, so such a
citation is flagged to look for the records behind it, and the image and
page checks meant for record citations are waived. A cited profile opens
in the WikiTree merge window.
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
    PART_SOURCE,
    SOURCE_TREE,
    CitationSource,
    Issue,
    citation_source_title,
    citation_text,
    make_issue,
)
from gramps.gen.gwizard.gwizard_filemerge_recordscan import SourceMatch
from gramps.gen.lib import Citation
from gramps.plugins.tool.gwizardwikitreeprovenance import (
    SOURCE_TITLE,
    normalize_profile_id,
)

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

_URL_RE = re.compile(r"wikitree\.com/wiki/([^\s/?#\"'<>)\]]+)", re.IGNORECASE)
# Checks meant for record citations, not for a citation of a profile.
WAIVED = frozenset({NO_MEDIA, PAGE_FRAGMENT, PAGE_SOURCE_TEXT})


def profile_ids(db: Any, citation: Citation) -> list[str]:
    """
    Return the WikiTree profile IDs a citation cites: its page when it
    cites the "WikiTree" source, and any profile address in its page,
    notes or attributes.
    """
    found: list[str] = []

    def add(value: str) -> None:
        try:
            profile_id = normalize_profile_id(value)
        except ValueError:
            return
        if profile_id not in found:
            found.append(profile_id)

    if citation_source_title(db, citation).strip() == SOURCE_TITLE:
        add(str(citation.get_page() or ""))
    for match in _URL_RE.finditer(citation_text(db, citation)):
        add(match.group(1))
    return found


# ------------------------------------------------------------
#
# WikiTreeCitationSource
#
# ------------------------------------------------------------
class WikiTreeCitationSource(CitationSource):
    """WikiTree's side of the Multi-Archive Citation Scan."""

    source_id = "wikitree"

    def record_keys(self, db: Any, citation: Citation) -> list[str]:
        """Return the WikiTree profile IDs the citation cites."""
        return profile_ids(db, citation)

    def extra_issues(self, db: Any, citation: Citation, keys: list[str]) -> list[Issue]:
        """A WikiTree profile is a family tree: look for its records."""
        if not keys:
            return []
        return [
            make_issue(
                SOURCE_TREE,
                PART_SOURCE,
                _(
                    "Cites WikiTree profile %s, a family tree; look for the "
                    "records it is based on."
                )
                % ", ".join(keys),
            )
        ]

    def waived_issues(self, db: Any, citation: Citation, keys: list[str]) -> set[str]:
        """A profile citation needs no image, and its page is an ID."""
        return set(WAIVED) if keys else set()

    def open_record(
        self,
        dbstate: Any,
        uistate: Any,
        person_handle: str,
        key: str,
        parent: Any = None,
    ) -> bool:
        """Open the cited profile in the WikiTree merge window."""
        if not person_handle:
            from gramps.gui.dialog import ErrorDialog

            ErrorDialog(
                _("GWizard WikiTree Merge"),
                _("This citation is not attached to a person."),
                parent=parent,
            )
            return False
        from gramps.plugins.tool.gwizardwikitreesource import WikiTreeSource

        match = SourceMatch(key=key, label=key, candidate=RecordCandidate())
        return WikiTreeSource().open_merge(
            dbstate, uistate, person_handle, match, parent=parent
        )


def load_on_reg(dbstate: Any, uistate: Any, plugin: Any) -> list[CitationSource]:
    """Offer WikiTree's citation checks to the GWizard Multi-Archive Citation Scan."""
    return [WikiTreeCitationSource()]
