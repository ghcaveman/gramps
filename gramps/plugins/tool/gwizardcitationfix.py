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

"""Tools/Family Tree Processing/GWizard citation fix."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import difflib
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.dialog import ErrorDialog, OkDialog
from gramps.gui.managedwindow import ManagedWindow
from gramps.gui.plug import tool
from gramps.gui.utils import ProgressMeter
from gramps.plugins.tool.goldstandardrepos import GoldStandardRepositories

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

REPORT_FILENAME = "CitationFixReport.txt"
REPORT_TITLE = "Citation analysis file"
REPORT_LINE_WIDTH = 78


# ------------------------------------------------------------
#
# Golden repository names (pure logic, no GUI)
#
# ------------------------------------------------------------
def get_golden_repository_names() -> list[str]:
    """Return the gold-standard repository names used for merging."""
    return GoldStandardRepositories.get_names()


def get_golden_repo_display(name: str) -> str:
    """Return the dropdown label with description and URL for a golden name."""
    return GoldStandardRepositories.get_display_label(name)


def normalize_repo_name(name: str) -> str:
    """Return a normalized key used to compare repository names."""
    key = (name or "").lower().strip()
    key = key.replace("&", "and")
    key = re.sub(r"\bu\.?\s*s\.?\b", " ", key)
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def is_golden_repo_name(name: str, golden: list[str] | None = None) -> bool:
    """Return True when a name already matches a gold-standard name."""
    if golden is None:
        golden = get_golden_repository_names()
    wanted = normalize_repo_name(name)
    return any(normalize_repo_name(item) == wanted for item in golden)


def rank_golden_repo_matches(
    name: str, golden: list[str] | None = None, limit: int | None = 5
) -> list[str]:
    """Return golden names ranked closest to the given repository name.

    Pass ``limit=None`` to return every golden name in ranked order.
    """
    if golden is None:
        golden = get_golden_repository_names()
    if not name or not golden:
        return list(golden) if limit is None else list(golden[:limit])
    scored: list[tuple[float, str]] = []
    plain = normalize_repo_name(name)
    for candidate in golden:
        target = normalize_repo_name(candidate)
        ratio = difflib.SequenceMatcher(None, plain, target).ratio()
        # Small bonus for token overlap so abbreviations still rank well.
        overlap = len(set(plain.split()) & set(target.split()))
        scored.append((ratio + 0.05 * overlap, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    ranked = [candidate for _score, candidate in scored]
    return ranked if limit is None else ranked[:limit]


def build_repo_merge_rows(
    repo_names: list[str], golden: list[str] | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    """Build per-repository merge rows for the dialog model.

    Each row holds the original ``name``, the dropdown ``options``
    (the source's repository name first as the bypass entry, then every
    golden-list entry), the ``best_guess`` target (the closest golden
    name), and ``skip`` which is True when the name already matches a
    golden name.
    """
    if golden is None:
        golden = get_golden_repository_names()
    rows: list[dict[str, Any]] = []
    for name in repo_names:
        if is_golden_repo_name(name, golden):
            rows.append(
                {
                    "name": name,
                    "options": [name],
                    "best_guess": name,
                    "skip": True,
                }
            )
            continue
        matches = rank_golden_repo_matches(name, golden, limit=None)
        best = matches[0] if matches else name
        options = [name] + [item for item in golden if item != name]
        rows.append(
            {"name": name, "options": options, "best_guess": best, "skip": False}
        )
    return rows


def plan_repo_merges(
    choices: dict[str, str], golden: list[str] | None = None
) -> dict[str, list[str]]:
    """Group repository names by chosen target, skipping bypass picks."""
    if golden is None:
        golden = get_golden_repository_names()
    plan: dict[str, list[str]] = defaultdict(list)
    for original, target in choices.items():
        if not target or target == original:
            continue
        plan[target].append(original)
    return dict(plan)


# Repository key used for sources that have no repository reference.
UNATTACHED_REPO_KEY = "(no repository)"


def collect_sources_by_repo(db: Any) -> dict[str, list[str]]:
    """Return repository name mapped to sorted source titles referencing it.

    Sources with no repository reference are collected under the
    ``UNATTACHED_REPO_KEY`` key so they can be displayed and assigned.
    """
    handle_to_name: dict[str, str] = {}
    for repo in _safe_iter(db, "iter_repositories"):
        try:
            handle = str(repo.get_handle() or "")
            name = str(repo.get_name() or "")
            if handle and name:
                handle_to_name[handle] = name
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to read repository")

    sources_by_repo: dict[str, list[str]] = defaultdict(list)
    for source in _safe_iter(db, "iter_sources"):
        try:
            title = str(source.get_title() or "")
            refs = list(source.get_reporef_list())
            if not refs:
                sources_by_repo[UNATTACHED_REPO_KEY].append(title)
                continue
            for ref in refs:
                repo_name = handle_to_name.get(
                    str(ref.get_reference_handle() or ""), ""
                )
                if repo_name:
                    sources_by_repo[repo_name].append(title)
                else:
                    sources_by_repo[UNATTACHED_REPO_KEY].append(title)
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to read source")

    return {name: sorted(titles) for name, titles in sources_by_repo.items()}


# ------------------------------------------------------------
#
# Button specs
#
# ------------------------------------------------------------
def get_button_specs() -> list[tuple[str, str, bool]]:
    """Return the (key, label, sensitive) specs for the dialog buttons."""
    return [
        ("generate", str(_("Generate report")), True),
        ("view", str(_("View report")), False),
        ("fix_repositories", str(_("Fix Repositories")), True),
        ("fix_sources", str(_("Fix Sources")), True),
        ("fix_citations", str(_("Fix Citations")), True),
        ("fix_notes", str(_("Fix Notes")), True),
        ("auto_all", str(_("Auto (best guess all)")), True),
    ]


# ------------------------------------------------------------
#
# Report helpers (pure logic, no GUI)
#
# ------------------------------------------------------------
def get_report_stages() -> list[str]:
    """Return the staged status texts shown while generating the report."""
    return [
        str(_("Starting analysis")),
        str(_("Collecting citations")),
        str(_("Analyzing sources")),
        str(_("Writing report")),
        str(_("Report complete!")),
    ]


def get_report_path(base_dir: str | None = None) -> str:
    """Return the full path of the generated CitationFixReport.txt file."""
    if base_dir is None:
        from gramps.gen.const import USER_DATA

        base_dir = USER_DATA
    return os.path.join(base_dir, REPORT_FILENAME)


def report_exists(path: str | None = None) -> bool:
    """Return True when the CitationFixReport.txt file exists."""
    if path is None:
        path = get_report_path()
    return os.path.isfile(path)


# ------------------------------------------------------------
#
# Analysis helpers (pure logic, no GUI)
#
# ------------------------------------------------------------
_FILENAME_RE = re.compile(r"\.\w{2,5}$")
_BARE_URL_RE = re.compile(r"^\s*https?://\S+\s*$", re.IGNORECASE)
_GENERIC_SOURCE_HINTS = (
    "official civil vital records",
    "birth, death, and burial registries",
    "state and municipal government archives",
)
_NON_SOURCE_TITLES = ("facebook", "legacy.com", "familysearch.org")


def normalize_source_title(title: str) -> str:
    """Return a normalized key used to group near-duplicate sources."""
    key = (title or "").lower().strip()
    key = key.replace("&", "and")
    key = re.sub(r"\bu\.?\s*s\.?\b", " ", key)
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def _safe_iter(db: Any, name: str) -> list[Any]:
    """Return list(db.<name>()) or an empty list when unavailable."""
    try:
        method = getattr(db, name, None)
        if method is None:
            return []
        return list(method())
    except Exception:  # pylint: disable=broad-except
        LOG.exception("Failed to iterate %s", name)
        return []


def _safe_count(db: Any, name: str, fallback_iter: str) -> int:
    """Return db.<name>() with an iteration fallback."""
    try:
        method = getattr(db, name, None)
        if callable(method):
            return int(method())
    except Exception:  # pylint: disable=broad-except
        LOG.exception("Failed counting via %s", name)
    return len(_safe_iter(db, fallback_iter))


def _note_text(note: Any) -> str:
    """Return the plain text of a note."""
    try:
        styled = note.get_styledtext()
        if styled is not None:
            if hasattr(styled, "get_string"):
                return str(styled.get_string())
            return str(styled)
    except Exception:  # pylint: disable=broad-except
        pass
    try:
        return str(note.get() or "")
    except Exception:  # pylint: disable=broad-except
        return ""


def _person_has_citation(person: Any) -> bool:
    """Return True when a person carries any direct citation."""
    try:
        if person.get_citation_list():
            return True
        for name_list in person.get_all_citation_lists():
            if name_list:
                return True
    except Exception:  # pylint: disable=broad-except
        pass
    return False


def build_report_text(
    citation_count: int,
    timestamp: str,
    stages: list[str] | None = None,
    stats: dict[str, Any] | None = None,
) -> str:
    """Build the text content of the citation analysis report file."""
    if stages is None:
        stages = get_report_stages()
    title = str(_(REPORT_TITLE))
    padding = max(2, REPORT_LINE_WIDTH - len(title) - len(timestamp))
    lines = [
        f"{title}{' ' * padding}{timestamp}",
        "=" * REPORT_LINE_WIDTH,
        "",
        str(_("Citations in database: %d") % citation_count),
        "",
    ]
    if stats is not None:
        lines.append(format_analysis(stats))
    lines.append(str(_("Analysis stages:")))
    lines.extend(f"- {stage}" for stage in stages)
    lines.append("")
    return "\n".join(lines)


def collect_db_stats(db: Any) -> dict[str, Any]:
    """Scan repositories, sources, citations, notes and media."""
    people = _safe_iter(db, "iter_people")
    sources = _safe_iter(db, "iter_sources")
    citations = _safe_iter(db, "iter_citations")
    repos = _safe_iter(db, "iter_repositories")
    notes = _safe_iter(db, "iter_notes")
    media_objs = _safe_iter(db, "iter_media")
    events = _safe_iter(db, "iter_events")
    stats: dict[str, Any] = {
        "people": len(people) or _safe_count(db, "get_number_of_people", "iter_people"),
        "families": _safe_count(db, "get_number_of_families", "iter_families"),
        "sources": len(sources),
        "repositories": len(repos),
        "citations": len(citations),
        "notes": len(notes),
        "media": len(media_objs),
    }
    try:
        stats["people"] = int(db.get_number_of_people())
    except Exception:  # pylint: disable=broad-except
        pass
    cites_by_source: Counter[str] = Counter()
    no_page = 0
    no_date = 0
    for cit in citations:
        try:
            src_handle = cit.get_reference_handle()
        except Exception:  # pylint: disable=broad-except
            src_handle = None
        if src_handle:
            cites_by_source[str(src_handle)] += 1
        try:
            page = (cit.get_page() or "").strip()
        except Exception:  # pylint: disable=broad-except
            page = ""
        if not page:
            no_page += 1
        try:
            date_obj = cit.get_date_object()
            has_date = bool(date_obj and str(date_obj))
        except Exception:  # pylint: disable=broad-except
            has_date = False
        if not has_date:
            no_date += 1
    stats["citations_no_page"] = no_page
    stats["citations_no_date"] = no_date
    stats["cites_by_source"] = dict(cites_by_source)
    source_rows: list[dict[str, Any]] = []
    norm_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tree_handles: set[str] = set()
    for src in sources:
        try:
            title = str(src.get_title() or "")
        except Exception:  # pylint: disable=broad-except
            title = ""
        try:
            author = str(src.get_author() or "")
        except Exception:  # pylint: disable=broad-except
            author = ""
        try:
            gid = str(src.get_gramps_id() or "")
        except Exception:  # pylint: disable=broad-except
            gid = ""
        try:
            handle = str(src.get_handle() or "")
        except Exception:  # pylint: disable=broad-except
            handle = ""
        try:
            repo_refs = list(src.get_reporef_list())
        except Exception:  # pylint: disable=broad-except
            repo_refs = []
        row = {
            "title": title,
            "author": author,
            "gramps_id": gid,
            "handle": handle,
            "repo_count": len(repo_refs),
            "citations": cites_by_source.get(str(handle), 0),
        }
        source_rows.append(row)
        key = normalize_source_title(title)
        if key:
            norm_groups[key].append(row)
        lowered = title.lower()
        if "familysearch" in lowered and "family tree" in lowered:
            tree_handles.add(str(handle))
    stats["source_rows"] = source_rows
    stats["orphan_sources"] = [r for r in source_rows if r["citations"] == 0]
    stats["sources_no_repo"] = [r for r in source_rows if r["repo_count"] == 0]
    stats["near_duplicates"] = [g for g in norm_groups.values() if len(g) > 1]
    stats["tree_citations"] = sum(cites_by_source.get(h, 0) for h in tree_handles)
    conf_high_tree = 0
    for cit in citations:
        try:
            handle = str(cit.get_reference_handle() or "")
            if handle in tree_handles and int(cit.get_confidence_level()) >= 3:
                conf_high_tree += 1
        except Exception:  # pylint: disable=broad-except
            continue
    stats["tree_conf_high"] = conf_high_tree
    repo_rows: list[dict[str, Any]] = []
    for repo in repos:
        try:
            name = str(repo.get_name() or "")
        except Exception:  # pylint: disable=broad-except
            name = ""
        try:
            gid = str(repo.get_gramps_id() or "")
        except Exception:  # pylint: disable=broad-except
            gid = ""
        repo_rows.append({"name": name, "gramps_id": gid})
    stats["repo_rows"] = repo_rows
    stats["people_unsourced"] = sum(1 for p in people if not _person_has_citation(p))
    bare_url = 0
    debris: list[dict[str, Any]] = []
    text_counter: Counter[str] = Counter()
    unreferenced = 0
    long_notes: list[dict[str, Any]] = []
    for note in notes:
        text = _note_text(note)
        text_counter[text.strip()[:200]] += 1
        if _BARE_URL_RE.match(text):
            bare_url += 1
        lowered = text.lower()
        try:
            gid = str(note.get_gramps_id() or "")
        except Exception:  # pylint: disable=broad-except
            gid = ""
        low_stripped = text.strip().lower()
        if "records not imported into repo" in lowered or low_stripped.startswith(
            "birth type:"
        ):
            debris.append({"gramps_id": gid, "preview": text.strip()[:100]})
        if len(text) > 500:
            long_notes.append({"gramps_id": gid, "length": len(text)})
            long_notes[-1]["preview"] = text.strip()[:120]
        if hasattr(db, "find_backlink_handles"):
            try:
                if not list(db.find_backlink_handles(note.get_handle())):
                    unreferenced += 1
            except Exception:  # pylint: disable=broad-except
                pass
    stats["notes_bare_url"] = bare_url
    stats["notes_debris"] = debris
    stats["notes_unreferenced"] = unreferenced
    dup = sum(1 for key, count in text_counter.items() if count > 1 and key)
    stats["notes_duplicated"] = dup
    stats["notes_long"] = sorted(long_notes, key=lambda r: r["length"], reverse=True)[
        :5
    ]
    abs_paths: list[str] = []
    base_counter: Counter[str] = Counter()
    cites_with_media = 0
    for media in media_objs:
        try:
            path = str(media.get_path() or "")
        except Exception:  # pylint: disable=broad-except
            path = ""
        if path and (os.path.isabs(path) or re.match(r"^[a-zA-Z]:\\", path)):
            abs_paths.append(path)
        base = os.path.basename(path).lower() if path else ""
        if base:
            base_counter[base] += 1
    for cit in citations:
        try:
            if cit.get_media_list():
                cites_with_media += 1
        except Exception:  # pylint: disable=broad-except
            continue
    stats["media_absolute"] = abs_paths[:10]
    stats["media_absolute_count"] = len(abs_paths)
    stats["media_dup_basenames"] = {k: v for k, v in base_counter.items() if v > 1}
    stats["citations_with_media"] = cites_with_media
    custom_counter: Counter[str] = Counter()
    for event in events:
        try:
            etype = event.get_type()
            label = etype.xml_str() if hasattr(etype, "xml_str") else str(etype)
        except Exception:  # pylint: disable=broad-except
            continue
        if label.startswith("_"):
            custom_counter[label] += 1
    stats["custom_events"] = dict(custom_counter)
    stats["custom_events_total"] = sum(custom_counter.values())
    return stats


def format_analysis(stats: dict[str, Any]) -> str:
    """Format the collected stats as the report body."""
    get = stats.get
    lines: list[str] = []
    lines.append(
        str(
            _(
                "Database totals: %d people, %d families, %d sources, "
                "%d repositories, %d citations, %d notes, %d media."
            )
            % (
                get("people", 0),
                get("families", 0),
                get("sources", 0),
                get("repositories", 0),
                get("citations", 0),
                get("notes", 0),
                get("media", 0),
            )
        )
    )
    lines.append("")
    lines.append(str(_("Where it matches best practice")))
    lines.append(
        str(
            _(
                "Most sources are collection-level with specifics in "
                "citations (the Evidence Explained 'split' approach). "
                "Orphan sources: %d."
            )
            % len(get("orphan_sources", []))
        )
    )
    lines.append("")
    lines.append(str(_("Where it falls short")))
    lines.append(
        str(
            _("Sources without a repository: %d of %d.")
            % (len(get("sources_no_repo", [])), get("sources", 0))
        )
    )
    for row in get("repo_rows", []):
        lines.append(
            "- %s (%s)"
            % (row.get("name") or _("Unnamed repository"), row.get("gramps_id") or "?")
        )
    lines.append(
        str(
            _("Citations with no Volume/Page: %d of %d.")
            % (get("citations_no_page", 0), get("citations", 0))
        )
    )
    if get("tree_citations"):
        lines.append(
            str(
                _(
                    "FamilySearch Family Tree citations: %d, rated "
                    "confidence 3+: %d. A user-edited tree is "
                    "derivative/secondary, so lower the confidence."
                )
                % (get("tree_citations", 0), get("tree_conf_high", 0))
            )
        )
    lines.append(
        str(
            _("People with no directly-attached source: %d of %d.")
            % (get("people_unsourced", 0), get("people", 0))
        )
    )
    dupes = get("near_duplicates", [])
    lines.append(str(_("Near-duplicate source groups: %d.") % len(dupes)))
    for group in dupes[:7]:
        joined = "; ".join(
            "%s '%s'" % (r.get("gramps_id"), r.get("title")) for r in group[:4]
        )
        lines.append("  - " + joined)
    for row in get("non_source_like", [])[:10]:
        lines.append(
            str(
                _("Not really a source: %s '%s' (%d citations).")
                % (row.get("gramps_id"), row.get("title"), row.get("citations"))
            )
        )
    for row in get("generic_sources", [])[:10]:
        lines.append(
            str(
                _("Generic source: %s '%s' by '%s'.")
                % (row.get("gramps_id"), row.get("title"), row.get("author"))
            )
        )
    lines.append(
        str(
            _("Notes that are bare URLs: %d of %d; unreferenced: %d; duplicated: %d.")
            % (
                get("notes_bare_url", 0),
                get("notes", 0),
                get("notes_unreferenced", 0),
                get("notes_duplicated", 0),
            )
        )
    )
    for row in get("notes_debris", [])[:10]:
        lines.append(
            str(
                _("Import debris note %s: %s")
                % (row.get("gramps_id"), row.get("preview"))
            )
        )
    for row in get("notes_long", [])[:5]:
        lines.append(
            str(
                _("Long narrative note %s (%d chars): %s...")
                % (row.get("gramps_id"), row.get("length"), row.get("preview"))
            )
        )
    lines.append(
        str(
            _("Media with absolute paths: %d of %d. Citations with images: %d.")
            % (
                get("media_absolute_count", 0),
                get("media", 0),
                get("citations_with_media", 0),
            )
        )
    )
    for base, count in list(get("media_dup_basenames", {}).items())[:5]:
        lines.append(str(_("Media filename imported %dx: %s") % (count, base)))
    if get("custom_events_total"):
        lines.append(
            str(_("Custom leftover events: %d.") % get("custom_events_total", 0))
        )
    lines.append("")
    lines.append(str(_("Suggested order of fixes:")))
    lines.append(str(_("1. Merge the duplicate sources.")))
    lines.append(
        str(_("2. Clean up the FamilySearch Tree source and lower the confidence."))
    )
    lines.append(
        str(_("3. Add Ancestry and FamilySearch as repositories and link the sources."))
    )
    lines.append(str(_("4. Delete the import-log notes.")))
    lines.append(
        str(_("5. Add page/entry details to census and death-record citations."))
    )
    lines.append("")
    return "\n".join(lines)


def parse_report_header(text: str) -> tuple[str, str]:
    """Split the first report line into (title, timestamp) parts."""
    first = text.splitlines()[0] if text else ""
    chunks = first.rsplit(None, 2)
    if len(chunks) >= 3 and len(chunks[-2]) == 10 and len(chunks[-1]) == 8:
        timestamp = f"{chunks[-2]} {chunks[-1]}"
        title = first[: len(first) - len(timestamp)].rstrip()
        return (title, timestamp)
    return (first.strip(), "")


# ------------------------------------------------------------
#
# GWizardCitationFixProgressMeter
#
# ------------------------------------------------------------
class GWizardCitationFixProgressMeter(ProgressMeter):
    """Wait/hourglass progress dialog for the citation fix report flow."""

    def __init__(self, parent: Any = None) -> None:
        """Initialize the meter in activity mode like the GWizard flow."""
        ProgressMeter.__init__(
            self,
            str(_("Loading Citation Fix")),
            str(_("Starting analysis...")),
            parent=parent,
        )
        self.set_pass(
            str(_("Starting analysis...")),
            mode=ProgressMeter.MODE_ACTIVITY,
        )

    def show_stage(self, text: str) -> None:
        """Update the header text and pulse the meter for a stage."""
        self.set_header(text)
        self.step()


# ------------------------------------------------------------
#
# Fix layer specs
#
# ------------------------------------------------------------
def get_fix_layer_specs() -> list[tuple[str, str, str]]:
    """Return (layer, title, description) specs for the fix dialogs."""
    return [
        (
            "repositories",
            str(_("Fix Repositories")),
            str(_("Create missing repositories and link orphan sources.")),
        ),
        (
            "sources",
            str(_("Fix Sources")),
            str(_("Merge near-duplicates and quarantine non-sources.")),
        ),
        (
            "citations",
            str(_("Fix Citations")),
            str(_("Clean FamilySearch Tree PAGE/DATE and confidence.")),
        ),
        (
            "notes",
            str(_("Fix Notes")),
            str(_("Remove import debris and convert bare-URL notes.")),
        ),
    ]


def get_fix_layer_titles() -> dict[str, str]:
    """Return a mapping of layer key to dialog title."""
    return {layer: title for layer, title, _desc in get_fix_layer_specs()}


def get_fix_description(layer: str) -> str:
    """Return the description text for a fix layer."""
    for spec_layer, _title, desc in get_fix_layer_specs():
        if spec_layer == layer:
            return desc
    return layer


# ------------------------------------------------------------
#
# GWizardCitationFixOptions
#
# ------------------------------------------------------------
class GWizardCitationFixOptions(tool.ToolOptions):
    """Defines options and provides handling interface."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        """Initialize the options."""
        tool.ToolOptions.__init__(self, name, person_id)
        self.options_dict = {}
        self.options_help = {}


# ------------------------------------------------------------
#
# GWizardCitationFix
#
# ------------------------------------------------------------
class GWizardCitationFix(tool.Tool, ManagedWindow):
    """Show the GWizard citation fix dialog."""

    def __init__(
        self,
        dbstate: Any,
        user: Any,
        options_class: Any,
        name: str,
        callback: Any = None,
    ) -> None:
        """Initialize the tool and open the modal dialog."""
        uistate = user.uistate
        tool.Tool.__init__(self, dbstate, options_class, name)
        ManagedWindow.__init__(self, uistate, [], self.__class__, modal=True)
        self.dbstate = dbstate
        self.report_path: str | None = None
        self.report_datetime: str | None = None
        self._build_window(uistate)
        self.update_view_button()
        self.show()

    def _build_window(self, uistate: Any) -> None:
        """Build the modal dialog layout."""
        dialog = Gtk.Dialog(
            title=str(_("GWizard citation fix")),
            transient_for=uistate.window,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        dialog.connect("response", self.cb_close)
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.add(vbox)
        specs = get_button_specs()
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        top_row.set_homogeneous(True)
        vbox.pack_start(top_row, False, False, 0)
        self.buttons: dict[str, Gtk.Button] = {}
        for key, label, sensitive in specs[:2]:
            button = Gtk.Button(label=label)
            button.set_sensitive(sensitive)
            button.set_hexpand(True)
            button.connect("clicked", self.cb_button, key)
            top_row.pack_start(button, True, True, 0)
            self.buttons[key] = button
        for key, label, sensitive in specs[2:]:
            button = Gtk.Button(label=label)
            button.set_sensitive(sensitive)
            button.set_hexpand(True)
            button.connect("clicked", self.cb_button, key)
            vbox.pack_start(button, False, False, 0)
            self.buttons[key] = button
        self.set_window(dialog, None, str(_("GWizard citation fix")))
        self.setup_configs("interface.gwizardcitationfix", 420, 260)
        dialog.show_all()

    def build_menu_names(self, obj: Any) -> tuple[str, str]:
        """Return the menu labels for the managed window."""
        return (_("GWizard citation fix"), " ")

    def cb_close(self, dialog: Gtk.Dialog, response: int) -> None:
        """Close the dialog."""
        self.close()

    def cb_button(self, button: Gtk.Button, key: str) -> None:
        """Dispatch dialog button clicks."""
        if key == "generate":
            self.cb_generate_report()
        elif key == "view":
            self.cb_view_report()
        elif key == "fix_repositories":
            self.cb_fix_layer("repositories")
        elif key == "fix_sources":
            self.cb_fix_layer("sources")
        elif key == "fix_citations":
            self.cb_fix_layer("citations")
        elif key == "fix_notes":
            self.cb_fix_layer("notes")
        elif key == "auto_all":
            self.cb_auto_all()
        else:
            LOG.debug("Unknown button pressed: %s", key)

    def cb_fix_layer(self, layer: str) -> None:
        """Open the fix dialog for one GEDCOM layer."""
        titles = get_fix_layer_titles()
        title = titles.get(layer, layer)
        self.show_fix_dialog(layer, title)

    def show_fix_dialog(self, layer: str, title: str) -> None:
        """Show a per-layer dialog with an Auto best-guess button."""
        if layer == "repositories":
            self.show_repo_merge_dialog()
            return
        if layer == "sources":
            self.show_source_fix_dialog()
            return
        if layer == "citations":
            self.show_citation_fix_dialog()
            return
        dialog = Gtk.Dialog(
            title=title,
            transient_for=self.window,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        dialog.connect("response", lambda dlg, resp: dlg.destroy())
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        label = Gtk.Label(label=self.get_fix_description(layer))
        label.set_line_wrap(True)
        label.set_halign(Gtk.Align.START)
        content.add(label)
        auto_button = Gtk.Button(label=str(_("Auto (best guess)")))
        auto_button.connect("clicked", self.cb_fix_auto, layer)
        content.add(auto_button)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def show_repo_merge_dialog(self) -> None:
        """Open the standalone merge-repositories dialog."""
        from gramps.plugins.tool.repomergedialog import RepoMergeDialog

        titles = get_fix_layer_titles()
        dialog = RepoMergeDialog(
            title=titles.get("repositories", "repositories"),
            dbstate=self.dbstate,
            transient_for=self.window,
        )
        dialog.show_dialog()

    def show_citation_fix_dialog(self) -> None:
        """Open the standalone citation-fix dialog."""
        from gramps.plugins.tool.citationsfixdialog import CitationFixDialog

        title = get_fix_layer_titles().get("citations", "citations")
        dialog = CitationFixDialog(
            title=title,
            dbstate=self.dbstate,
            description=self.get_fix_description("citations"),
            transient_for=self.window,
        )
        dialog.show_dialog()

    def show_source_fix_dialog(self) -> None:
        """Open the standalone source-record fix dialog."""
        from gramps.plugins.tool.sourcesfixdialog import SourceFixDialog

        title = get_fix_layer_titles().get("sources", "sources")
        dialog = SourceFixDialog(
            title=title,
            dbstate=self.dbstate,
            description=self.get_fix_description("sources"),
            transient_for=self.window,
        )
        dialog.show_dialog()

    def get_fix_description(self, layer: str) -> str:
        """Return the description text for a fix layer."""
        return get_fix_description(layer)

    def cb_repo_auto(self) -> None:
        """Apply best-guess golden merges for all non-golden repositories."""
        from gramps.plugins.tool.repomergedialog import RepoMergeDialog

        dialog = RepoMergeDialog(
            title="",
            dbstate=self.dbstate,
            transient_for=self.window,
        )
        dialog.run_auto(parent=self.window)
        dialog.destroy()

    def cb_fix_auto(self, button: Gtk.Button, layer: str) -> None:
        """Run the best-guess auto fix for one layer (preview-first)."""
        if layer == "repositories":
            self.cb_repo_auto()
            return
        try:
            stats = collect_db_stats(self.dbstate.db)
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to analyze database for %s", layer)
            stats = None
        summary = self.summarize_auto_fix(layer, stats)
        OkDialog(
            str(_("Auto fix preview: %s") % layer),
            summary,
            parent=self.window,
        )

    def summarize_auto_fix(self, layer: str, stats: dict[str, Any] | None) -> str:
        """Return a preview summary of what auto fix would do."""
        if not stats:
            return str(_("No analysis available. Generate a report first."))
        if layer == "repositories":
            count = len(stats.get("sources_no_repo", []))
            return str(_("Best guess would link %d sources to repositories.") % count)
        if layer == "sources":
            count = len(stats.get("near_duplicates", []))
            return str(_("Best guess would merge %d duplicate groups.") % count)
        if layer == "citations":
            count = int(stats.get("tree_citations", 0))
            return str(
                _("Best guess would clean %d FamilySearch Tree citations.") % count
            )
        if layer == "notes":
            count = len(stats.get("notes_debris", []))
            return str(_("Best guess would remove %d debris notes.") % count)
        return str(_("Unknown layer: %s") % layer)

    def cb_auto_all(self) -> None:
        """Run best-guess auto fixes across all layers in order."""
        try:
            stats = collect_db_stats(self.dbstate.db)
        except Exception:  # pylint: disable=broad-except
            LOG.exception("Failed to analyze database for auto all")
            stats = None
        parts = [
            self.summarize_auto_fix(layer, stats)
            for layer, _t, _d in get_fix_layer_specs()
        ]
        OkDialog(
            str(_("Auto fix preview (all layers)")),
            "\n".join(parts),
            parent=self.window,
        )

    def update_view_button(self) -> None:
        """Enable View report only when the report file exists."""
        button = self.buttons.get("view")
        if button is None:
            return
        path = self.report_path or get_report_path()
        button.set_sensitive(report_exists(path))

    def _pump_events(self) -> None:
        """Let pending GTK events run so the meter stays responsive."""
        while Gtk.events_pending():
            Gtk.main_iteration()

    def cb_generate_report(self) -> None:
        """Generate the CitationFixReport.txt file with staged progress."""
        stages = get_report_stages()
        meter = GWizardCitationFixProgressMeter(parent=self.window)
        citation_count = 0
        stats: dict[str, Any] | None = None
        try:
            for stage in stages:
                meter.show_stage(stage)
                self._pump_events()
                if stage == stages[1]:
                    try:
                        stats = collect_db_stats(self.dbstate.db)
                        citation_count = int(stats.get("citations", 0))
                    except Exception:  # pylint: disable=broad-except
                        LOG.exception("Failed to analyze database")
                        stats = None
                        citation_count = 0
                if stage == stages[2] and stats is None:
                    try:
                        stats = collect_db_stats(self.dbstate.db)
                        citation_count = int(stats.get("citations", 0))
                    except Exception:  # pylint: disable=broad-except
                        LOG.exception("Failed to analyze database")
                        stats = None
                if stage == stages[-2]:
                    self.report_datetime = datetime.now().strftime("%Y-%m-%d %H:%M")
                    text = build_report_text(
                        citation_count, self.report_datetime, stages, stats
                    )
                    self.report_path = get_report_path()
                    try:
                        os.makedirs(os.path.dirname(self.report_path), exist_ok=True)
                        with open(self.report_path, "w", encoding="utf-8") as handle:
                            handle.write(text)
                    except OSError as error:
                        LOG.error("Failed to write citation report: %s", error)
                        ErrorDialog(
                            str(_("Report Failed")),
                            str(error),
                            parent=self.window,
                        )
                        self.report_path = None
                        return
        finally:
            meter.close()
        if self.report_path:
            self.update_view_button()
            OkDialog(
                str(_("Report generated")),
                str(_("Wrote %s") % self.report_path),
                parent=self.window,
            )
            self.cb_view_report()

    def cb_view_report(self) -> None:
        """Open the generated CitationFixReport.txt in a report window."""
        path = self.report_path or get_report_path()
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            OkDialog(
                str(_("No report yet")),
                str(_("Please choose Generate report first.")),
                parent=self.window,
            )
            return
        title, timestamp = parse_report_header(text)
        if not timestamp and self.report_datetime:
            timestamp = self.report_datetime
        dialog = Gtk.Dialog(
            title=str(_("GWizard citation fix report")),
            transient_for=self.window,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        dialog.connect("response", lambda dlg, resp: dlg.destroy())
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_label = Gtk.Label()
        title_label.set_markup('<span size="larger" weight="bold">%s</span>' % title)
        title_label.set_halign(Gtk.Align.START)
        title_label.set_hexpand(True)
        header.pack_start(title_label, True, True, 0)
        date_label = Gtk.Label()
        date_label.set_markup('<span size="smaller">%s</span>' % timestamp)
        date_label.set_halign(Gtk.Align.END)
        header.pack_start(date_label, False, False, 0)
        content.add(header)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(300)
        scrolled.set_min_content_width(1080)
        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_wrap_mode(Gtk.WrapMode.WORD)
        textview.set_vexpand(True)
        textview.set_hexpand(True)
        textview.get_buffer().set_text(text)
        scrolled.add(textview)
        content.pack_start(scrolled, True, True, 0)
        scrolled.set_vexpand(True)
        dialog.show_all()
        dialog.run()
        dialog.destroy()
