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
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Guess what each page of a NARA record is, from the text NARA's catalog
machine-read from the scan (its "extracted text").

The text is rough, especially for handwriting, but printed form headings
come through well, and those headings say what a page is: a claim brief, a
declaration, an affidavit, a deposition, an Adjutant General's service
report, and so on. The rules below were drawn from a real Civil War widow's
pension file; every label is a guess, shown as "probably".
"""

# ------------------------------------------------------------
#
# Python modules
#
# ------------------------------------------------------------
from __future__ import annotations
import re
from dataclasses import dataclass, field

# ------------------------------------------------------------
#
# Gramps modules
#
# ------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale

_ = glocale.translation.sgettext

# The page number at the end of a NARA file name, as in
# "WC47795-SMITH-John-A_M_00003.jpg".
_PAGE_NUMBER = re.compile(r"[_-](\d{3,})\.\w+$")

# Text shorter than this is treated as a cover, envelope or stray mark.
SHORT_TEXT = 90

# (label, patterns) in order: the first rule with a matching pattern wins.
# Patterns are regular expressions matched case-insensitively against the
# page text with runs of whitespace collapsed to single spaces. They allow
# for common OCR slips where that was seen in real pages.
PAGE_RULES: list[tuple[str, list[str]]] = [
    (_("Claim brief"), [r"\bbrief in the case\b", r"\bbrief\b.{0,80}\bclaim for\b"]),
    (_("Special examiner's report index"), [r"\bi ?ndex to special\b"]),
    (
        _("Examiner's interview certificate"),
        [r"certify that i have personally (?:interviewed|in)"],
    ),
    (_("Fee contract"), [r"\bfee contract\b", r"\bnotice to claimant\b"]),
    (_("Deposition"), [r"\bdeposition\b"]),
    (
        _("Special examiner's report"),
        [r"\bspecial exam", r"\bspecial examination\b"],
    ),
    (_("Marriage record"), [r"united in marriage", r"proof of marriage"]),
    (_("Death record"), [r"certificate of death", r"\bdeath certificate\b"]),
    (
        _("Declaration"),
        [r"\bdeclaration\b.{0,60}\bpension\b", r"\bclaim for .{0,20}pension\b"],
    ),
    (
        _("Service report"),
        [r"adjutant general", r"\brecord and pension office\b", r"surgeon general"],
    ),
    (_("Medical examination"), [r"surgeon'?s certificate", r"examining surgeon"]),
    (
        _("Affidavit"),
        [
            r"personally appeared",
            r"\baffidavit\b",
            r"(?:sworn|subscribed) (?:to )?(?:and subscribed )?before me",
        ],
    ),
    (_("Pension claim form"), [r"widow'?s pension", r"\bact of (?:june|july) \d"]),
    (
        _("Letter"),
        [
            r"\bi have the honou?r\b",
            r"\bcommissioner of pensions\b",
            r"\battorney at (?:law|caw|yaw)\b",
            r"\blaw office\b",
        ],
    ),
    # Pension forms were printed by the Department of the Interior, but so
    # are National Park Service, Land Office and Indian Affairs records: the
    # department only counts with a pension nearby.
    (
        _("Pension Bureau form"),
        [
            r"bureau of pensions",
            r"department of the interior\b.{0,300}\bpensions?\b",
            r"\bpensions?\b.{0,300}\bdepartment of the interior",
        ],
    ),
]

_COMPILED = [
    (label, [re.compile(pattern, re.IGNORECASE) for pattern in patterns])
    for label, patterns in PAGE_RULES
]

COVER = _("Cover or jacket")
LITTLE_TEXT = _("Little text (endorsement, envelope or blank)")
CONTINUATION = _("Continued page")
UNKNOWN = _("Not identified")
NO_TEXT = _("No text")

# Labels a following page that starts "Page ..." continues.
_CONTINUES = (
    _("Deposition"),
    _("Examiner's interview certificate"),
    _("Affidavit"),
    CONTINUATION,
)


@dataclass
class PageInfo:
    """What one page probably is."""

    page: int
    label: str
    snippet: str
    text: str = ""
    mentions: list[str] = field(default_factory=list)


def page_number(filename: str, index: int) -> int:
    """
    Return NARA's page number from an image file name, or index + 1 when
    the name has none (as in "2480.jpg", where 2480 is a frame number).
    """
    match = _PAGE_NUMBER.search(filename or "")
    return int(match.group(1)) if match else index + 1


def _flatten(text: str) -> str:
    """Collapse whitespace so patterns can span the page's line breaks."""
    return re.sub(r"\s+", " ", text or "").strip()


def snippet(text: str, lines: int = 3, width: int = 120) -> str:
    """Return the first few non-empty lines of a page's text."""
    found = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return " / ".join(found[:lines])[:width]


def classify_page(text: str, previous: str = "") -> str:
    """
    Return the probable kind of page for its extracted text.

    :param text: The page's extracted text ('' when NARA has none).
    :param previous: The label of the page before, so a page that starts
        "Page 2" after a deposition is shown as its continuation.
    """
    flat = _flatten(text)
    if not flat:
        return NO_TEXT
    if re.match(r"page\b", flat, re.IGNORECASE) and previous in _CONTINUES:
        return CONTINUATION
    for label, patterns in _COMPILED:
        if any(pattern.search(flat) for pattern in patterns):
            return label
    if len(flat) < SHORT_TEXT:
        if re.search(r"\bbox\b", flat, re.IGNORECASE) and re.search(r"\d{3,}", flat):
            return COVER
        return LITTLE_TEXT
    return UNKNOWN


def name_mentions(text: str, names: list[str]) -> list[str]:
    """
    Return which of the given names appear in the text as whole words,
    ignoring case. Names shorter than three letters are skipped.
    """
    flat = _flatten(text).casefold()
    found = []
    for name in names:
        name = (name or "").strip()
        if len(name) < 3:
            continue
        if re.search(rf"\b{re.escape(name.casefold())}\b", flat):
            found.append(name)
    return found


def classify_pages(
    filenames: list[str], texts: list[str], names: list[str] | None = None
) -> list[PageInfo]:
    """
    Classify every page of a record.

    :param filenames: Each image's file name, in order.
    :param texts: Each image's extracted text, in the same order.
    :param names: Names to look for (such as the person's given names,
        surname and married name).
    :returns: One PageInfo per image.
    """
    pages: list[PageInfo] = []
    previous = ""
    for index, (filename, text) in enumerate(zip(filenames, texts)):
        label = classify_page(text, previous)
        pages.append(
            PageInfo(
                page=page_number(filename, index),
                label=label,
                snippet=snippet(text),
                text=text or "",
                mentions=name_mentions(text, names or []),
            )
        )
        previous = label
    return pages
