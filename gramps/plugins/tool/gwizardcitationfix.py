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
from collections import defaultdict
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
from gramps.gui.dialog import ErrorDialog, OkDialog, QuestionDialog2
from gramps.gui.managedwindow import ManagedWindow
from gramps.gui.plug import tool
from gramps.gui.utils import ProgressMeter
from gramps.plugins.tool.gw_goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizard_common import SelectableLabel
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardcitationreport import GWizardCitationReport
from gramps.plugins.tool.gwizardcitationshared import (
    build_family_titles,
    build_title_repo_index,
    suggest_repository,
)
from gramps.plugins.tool.gwizardcitationshared import (
    normalize_repo_name as _shared_normalize,
)

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
    return _shared_normalize(name)


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


def infer_repository_name(source_title: str, golden: list[str] | None = None) -> str:
    """Infer a repository name from a source title.

    A golden name is selected only when its normalized or compact form is
    present in the title. If no golden name is identifiable, return the
    source title so the information is preserved for later review.
    """
    title = source_title.strip()
    if golden is None:
        golden = get_golden_repository_names()
    normalized_title = normalize_repo_name(title)
    compact_title = normalized_title.replace(" ", "")
    for candidate in golden:
        normalized_candidate = normalize_repo_name(candidate)
        if not normalized_candidate:
            continue
        aliases = [normalized_candidate]
        aliases.extend(
            normalize_repo_name(alias)
            for alias in re.findall(r"\(([^)]+)\)", candidate)
        )
        entry = GoldStandardRepositories.get_by_name(candidate)
        if entry is not None:
            url = entry.get("url", "")
            host = url.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.")
            aliases.append(normalize_repo_name(host))
        for alias in aliases:
            compact_alias = alias.replace(" ", "")
            if alias and (alias in normalized_title or compact_alias in compact_title):
                return candidate
    return title


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
#
# No-review ("accept all hints") runner, shared by every caller
#
# ------------------------------------------------------------
AUTO_STEP_LAYERS = (
    "unpack_sources",
    "consolidate_repositories",
    "repositories",
    "sources",
    "unpack_citations",
    "citations",
    "citation_attributes",
    "notes",
)


def get_auto_step_titles() -> dict[str, str]:
    """Return the display name of every step Accept all hints runs."""
    titles = get_fix_layer_titles()
    titles["consolidate_repositories"] = str(_("Repository Consolidate"))
    return titles


def run_auto_layer(layer: str, db: Any) -> str:
    """Accept all hints for one step and return a one-line result.

    Every step calls the same headless function its dialog uses to apply
    changes, inside one DbTxn, so the step is one Edit > Undo. Errors are
    raised to the caller instead of being swallowed.
    """
    if layer == "unpack_sources":
        count = GWizardCitationRepairEngine().unpack_conflated_sources(db)
        return str(_("Unpacked %d mixed source titles.")) % count
    if layer == "consolidate_repositories":
        from gramps.plugins.tool.gw_repoconsolidatedialog import (
            auto_consolidate_repositories,
        )

        result = auto_consolidate_repositories(db)
        text = str(_("Merged %d duplicate repository records")) % result["merged"]
        extras = []
        if result["created"]:
            extras.append(
                str(_("created %d gold-standard repositories")) % result["created"]
            )
        if result["removed"]:
            extras.append(
                str(_("removed %d repeated address lines")) % result["removed"]
            )
        if result["moved"]:
            extras.append(str(_("moved %d place details into notes")) % result["moved"])
        if extras:
            text += " (%s)" % ", ".join(extras)
        if result["errors"]:
            text += ". " + " ".join(result["errors"])
        return text + "."
    if layer == "repositories":
        changed, created = auto_assign_source_repositories(
            GWizardCitationRepairEngine(), db
        )
        text = str(_("Set the repository of %d sources")) % changed
        if created:
            text += str(_(" (%d new repositories created)")) % created
        return text + "."
    if layer == "sources":
        from gramps.plugins.tool.gw_sourcesfixdialog import auto_fix_sources

        merged, quarantined, trimmed = auto_fix_sources(db)
        return str(_("Merged %d duplicate sources, quarantined %d, trimmed %d.")) % (
            merged,
            quarantined,
            trimmed,
        )
    if layer == "unpack_citations":
        from gramps.plugins.tool.gw_unpackcitationsdialog import auto_unpack_citations

        return str(_("Unpacked %d conflated citations.")) % auto_unpack_citations(db)
    if layer == "citations":
        from gramps.plugins.tool.gw_citationsfixdialog import auto_fix_citations

        return str(_("Refined %d citations.")) % auto_fix_citations(db)
    if layer == "citation_attributes":
        from gramps.plugins.tool.gw_citationattributesdialog import (
            auto_citation_attributes,
        )

        return str(_("Updated attributes on %d citations.")) % auto_citation_attributes(
            db
        )
    if layer == "notes":
        from gramps.plugins.tool.gw_notesfixdialog import auto_fix_notes

        return str(_("Fixed or removed %d notes.")) % auto_fix_notes(db)
    raise ValueError("Unknown step: %s" % layer)


def find_items_needing_review(db: Any) -> list[str]:
    """Return one line per step that still has items a person must decide.

    Runs after the automatic steps, so any row a step's builder still
    returns is something its hints could not resolve. A check that fails is
    reported as such rather than silently skipped.
    """
    engine = GWizardCitationRepairEngine()
    items: list[str] = []

    def add(label: str, count: int, why: str) -> None:
        if count:
            items.append("  • %s (%d): %s" % (label, count, why))

    def failed(label: str, error: Exception) -> None:
        LOG.exception("Review check failed for %s", label)
        items.append(
            "  • %s: %s" % (label, str(_("could not be checked (%s).")) % error)
        )

    label = str(_("Unpack Conflated Source"))
    try:
        add(
            label,
            len(engine.plan_unpack_conflated_sources(db)),
            str(
                _(
                    "source titles with complex or ambiguous mixed text need manual review."
                )
            ),
        )
    except Exception as error:  # pylint: disable=broad-except
        failed(label, error)

    label = str(_("Repository Consolidate"))
    try:
        from gramps.plugins.tool.gw_repoconsolidatedialog import (
            build_repo_consolidate_rows,
        )

        add(
            label,
            len(build_repo_consolidate_rows(db)),
            str(_("repositories still have ambiguous matches or address problems.")),
        )
    except Exception as error:  # pylint: disable=broad-except
        failed(label, error)

    label = str(_("Fix Repositories"))
    try:
        orphan_count = 0
        for src in db.iter_sources():
            refs = src.get_reporef_list()
            if not refs:
                orphan_count += 1
            else:
                for ref in refs:
                    repo = db.get_repository_from_handle(ref.get_reference_handle())
                    if (
                        repo
                        and str(repo.get_name() or "").strip().lower() == "quarantine"
                    ):
                        orphan_count += 1
                        break
        add(
            label,
            orphan_count,
            str(_("sources could not be linked to any known repository.")),
        )
    except Exception as error:  # pylint: disable=broad-except
        failed(label, error)

    label = str(_("Fix Sources"))
    try:
        from gramps.plugins.tool.gw_sourcesfixdialog import build_source_fix_rows
        from gramps.plugins.tool.gwizardcitationreport import collect_db_stats

        add(
            label,
            len(build_source_fix_rows(collect_db_stats(db), db)),
            str(_("sources still need a decision (duplicates or non-sources).")),
        )
    except Exception as error:  # pylint: disable=broad-except
        failed(label, error)

    label = str(_("Unpack Conflated Citation"))
    try:
        from gramps.plugins.tool.gw_unpackcitationsdialog import (
            plan_unpack_conflated_citations,
        )

        add(
            label,
            len(plan_unpack_conflated_citations(db)),
            str(_("citations still have text that could not be separated.")),
        )
    except Exception as error:  # pylint: disable=broad-except
        failed(label, error)

    label = str(_("Citation Attributes"))
    try:
        from gramps.plugins.tool.gw_citationattributesdialog import (
            build_citation_attribute_rows,
        )

        add(
            label,
            len(
                [
                    row
                    for row in build_citation_attribute_rows(db)
                    if not row.get("has_all")
                    and not row.get("suggested_src_type")
                    and not row.get("suggested_info_type")
                    and not row.get("suggested_ev_type")
                    and not row.get("suggested_quay")
                ]
            ),
            str(
                _(
                    "citations have no characteristic keywords (e.g. census, certificate) to infer attributes from."
                )
            ),
        )
    except Exception as error:  # pylint: disable=broad-except
        failed(label, error)

    label = str(_("Fix Notes"))
    try:
        from gramps.plugins.tool.gw_notesfixdialog import build_note_fix_rows

        add(
            label,
            len(build_note_fix_rows(db)),
            str(_("notes still need manual cleanup.")),
        )
    except Exception as error:  # pylint: disable=broad-except
        failed(label, error)
    return items


# ------------------------------------------------------------
def build_repo_fix_changes(db: Any) -> list[dict[str, str]]:
    """Return the repository change the Fix Repositories hints suggest per source.

    One entry per source/repository pair that has a hint, using the same
    suggestions the Fix Repositories dialog shows in its Hint column. Each
    entry is ``{"source_handle", "old_repo_handle", "target_name"}`` for
    ``GWizardCitationRepairEngine.reassign_source_repositories``.
    """
    golden = GoldStandardRepositories.get_names()
    names = {
        str(repo.get_handle()): str(repo.get_name() or "")
        for repo in db.iter_repositories()
    }
    rows: list[dict[str, str]] = []
    for source in db.iter_sources():
        handle = str(source.get_handle() or "")
        title = str(source.get_title() or "")
        refs = [
            str(ref.get_reference_handle() or "") for ref in source.get_reporef_list()
        ]
        for ref_handle in refs or [""]:
            name = names.get(ref_handle, "")
            rows.append(
                {
                    "source_handle": handle,
                    "title": title,
                    "repo_handle": ref_handle if name else "",
                    "repo_name": name,
                }
            )
    index = build_title_repo_index([row for row in rows if row["repo_handle"]])
    family = build_family_titles([row["title"] for row in rows])
    changes: list[dict[str, str]] = []
    for row in rows:
        suggestion = suggest_repository(
            row["title"],
            row["source_handle"],
            row["repo_name"],
            index,
            golden,
            family,
        )
        if suggestion:
            changes.append(
                {
                    "source_handle": row["source_handle"],
                    "old_repo_handle": row["repo_handle"],
                    "target_name": suggestion[0],
                }
            )
    return changes


def auto_assign_source_repositories(
    engine: Any, db: Any, trans: Any = None
) -> tuple[int, int]:
    """Accept every Fix Repositories hint and apply it in one transaction.

    This is the single no-review implementation shared by the dialog's
    ``run_auto``, the per-step Auto button and Accept all hints. Returns
    ``(sources changed, repositories created)``.
    """
    return engine.reassign_source_repositories(db, build_repo_fix_changes(db), trans)


def get_button_specs() -> list[tuple[str, str, bool]]:
    """Return the (key, label, sensitive) specs for the dialog buttons."""
    return [
        ("generate", str(_("Generate report")), True),
        ("unpack_sources", str(_("Unpack Conflated Source")), True),
        ("consolidate_repositories", str(_("Repository Consolidate")), True),
        ("fix_repositories", str(_("Fix Repositories")), True),
        ("fix_sources", str(_("Fix Sources")), True),
        ("unpack_citations", str(_("Unpack Conflated Citation")), True),
        ("fix_citations", str(_("Fix Citations")), True),
        ("citation_attributes", str(_("Citation Attributes")), True),
        ("link_citation_media", str(_("Link Citation Media")), True),
        ("fix_notes", str(_("Fix Notes")), True),
        ("auto_all", str(_("Accept all hints")), True),
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


def parse_report_header(text: str) -> tuple[str, str]:
    """Split the first report line into (title, timestamp) parts."""
    first = text.splitlines()[0] if text else ""
    chunks = first.rsplit(None, 2)
    if len(chunks) >= 3 and len(chunks[-2]) == 10 and len(chunks[-1]) == 8:
        timestamp = f"{chunks[-2]} {chunks[-1]}"
        title = first[: len(first) - len(timestamp)].rstrip()
        return (title, timestamp)
    return (first.strip(), "")


def _safe_iter(db: Any, name: str) -> list[Any]:
    """Return list(db.<name>()) or an empty list when unavailable."""
    try:
        method = getattr(db, name, None)
        if method is None:
            return []
        return list(method())
    except Exception:
        LOG.exception("Failed to iterate %s", name)
        return []


# ------------------------------------------------------------
#
# GWizardCitationFixProgressMeter
#
# ------------------------------------------------------------
class GWizardCitationFixProgressMeter(ProgressMeter):
    """Wait/hourglass progress dialog for the citation fix report flow."""

    def __init__(self, parent: Any = None) -> None:
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
            "unpack_sources",
            str(_("Unpack Conflated Source")),
            str(
                _(
                    "Parse mixed text headers, extract repository entries, and prepare fields for deduplication."
                )
            ),
        ),
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
            "unpack_citations",
            str(_("Unpack Conflated Citation")),
            str(
                _(
                    "Extract dates and URLs mixed into volume/page strings or notes, and unpack citation fields."
                )
            ),
        ),
        (
            "citations",
            str(_("Fix Citations")),
            str(_("Clean tree page/date and confidence.")),
        ),
        (
            "citation_attributes",
            str(_("Citation Attributes")),
            str(
                _(
                    "Assign Genealogical Proof Standard (GPS) quality attributes and confidence ratings to citations."
                )
            ),
        ),
        (
            "link_citation_media",
            str(_("Link Citation Media")),
            str(
                _(
                    "Discover and link documentary media from galleries, sources, or orphan files to citations."
                )
            ),
        ),
        (
            "notes",
            str(_("Fix Notes")),
            str(_("Remove import debris and convert bare-URL notes.")),
        ),
    ]


def get_fix_layer_titles() -> dict[str, str]:
    return {layer: title for layer, title, _desc in get_fix_layer_specs()}


def get_fix_description(layer: str) -> str:
    for spec_layer, _title, desc in get_fix_layer_specs():
        if spec_layer == layer:
            return desc
    return layer


class GWizardCitationFixOptions(tool.ToolOptions):
    def __init__(self, name: str, person_id: str | None = None) -> None:
        tool.ToolOptions.__init__(self, name, person_id)
        self.options_dict = {}
        self.options_help = {}


# ------------------------------------------------------------
#
# GWizardCitationFix Window Controller
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
        uistate = user.uistate
        tool.Tool.__init__(self, dbstate, options_class, name)
        ManagedWindow.__init__(self, uistate, [], self.__class__, modal=True)
        self.dbstate = dbstate
        self.report_path: str | None = None
        self.report_datetime: str | None = None
        self._build_window(uistate)
        self.show()

    def _build_window(self, uistate: Any) -> None:
        dialog = Gtk.Dialog(
            title=str(_("GWizard citation fix")),
            transient_for=uistate.window,
            modal=True,
            destroy_with_parent=True,
        )
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.add(vbox)

        specs = get_button_specs()
        self.buttons: dict[str, Gtk.Button] = {}
        for key, label, sensitive in specs[:-1]:
            button = Gtk.Button(label=label)
            button.set_sensitive(sensitive)
            button.set_hexpand(True)
            button.connect("clicked", self.cb_button, key)
            vbox.pack_start(button, False, False, 0)
            self.buttons[key] = button

        # Action area buttons (Accept all hints placed to the left of Close)
        auto_all_btn = Gtk.Button(label=str(_("Accept all hints")))
        auto_all_btn.connect("clicked", self.cb_button, "auto_all")
        dialog.add_action_widget(auto_all_btn, Gtk.ResponseType.NONE)
        self.buttons["auto_all"] = auto_all_btn
        dialog.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        dialog.connect("response", self.cb_close)

        self.set_window(dialog, None, str(_("GWizard citation fix")))
        self.setup_configs("interface.gwizardcitationfix", 420, 260)
        dialog.show_all()

    def build_menu_names(self, obj: Any) -> tuple[str, str]:
        return (_("GWizard citation fix"), " ")

    def cb_close(self, dialog: Gtk.Dialog, response: int) -> None:
        # Only close the managed window on a close-type response.  Other
        # responses (e.g. propagated from transient child dialogs such as the
        # "Accept all hints" confirmation) must not close the parent dialog.
        if response == Gtk.ResponseType.CLOSE:
            self.close()

    def cb_button(self, button: Gtk.Button, key: str) -> None:
        """Dispatch dialog button clicks."""
        if key == "generate":
            self.cb_generate_report()
        elif key == "unpack_sources":
            self.cb_fix_layer("unpack_sources")  # Route the new button click
        elif key == "consolidate_repositories":
            from gramps.plugins.tool.gw_repoconsolidatedialog import (
                RepoConsolidateDialog,
            )

            RepoConsolidateDialog(self.dbstate, transient_for=self.window).show_dialog()
        elif key == "fix_repositories":
            self.cb_fix_layer("repositories")
        elif key == "fix_sources":
            self.cb_fix_layer("sources")
        elif key == "unpack_citations":
            self.cb_fix_layer("unpack_citations")
        elif key == "fix_citations":
            self.cb_fix_layer("citations")
        elif key == "citation_attributes":
            self.cb_fix_layer("citation_attributes")
        elif key == "link_citation_media":
            self.cb_fix_layer("link_citation_media")
        elif key == "fix_notes":
            self.cb_fix_layer("notes")
        elif key == "auto_all":
            self.cb_auto_all()

    def cb_fix_layer(self, layer: str) -> None:
        titles = get_fix_layer_titles()
        self.show_fix_dialog(layer, titles.get(layer, layer))

    def show_fix_dialog(self, layer: str, title: str) -> None:
        if layer == "unpack_sources":
            from gramps.plugins.tool.gw_unpacksourcesdialog import UnpackSourcesDialog

            UnpackSourcesDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("unpack_sources"),
                transient_for=self.window,
            ).show_dialog()
            return
        if layer == "repositories":
            from gramps.plugins.tool.gw_repomergedialog import RepoMergeDialog

            RepoMergeDialog(
                title=title, dbstate=self.dbstate, transient_for=self.window
            ).show_dialog()
            return
        if layer == "sources":
            from gramps.plugins.tool.gw_sourcesfixdialog import SourceFixDialog

            SourceFixDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("sources"),
                transient_for=self.window,
            ).show_dialog()
            return
        if layer == "unpack_citations":
            from gramps.plugins.tool.gw_unpackcitationsdialog import (
                UnpackCitationsDialog,
            )

            UnpackCitationsDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("unpack_citations"),
                transient_for=self.window,
            ).show_dialog()
            return
        if layer == "citations":
            try:
                from gramps.plugins.tool.gw_citationsfixdialog import CitationFixDialog
            except ImportError:
                LOG.warning("gw_citationsfixdialog not available; using auto fix")
            else:
                CitationFixDialog(
                    title=title,
                    dbstate=self.dbstate,
                    description=get_fix_description("citations"),
                    transient_for=self.window,
                ).show_dialog()
                return
        if layer == "citation_attributes":
            from gramps.plugins.tool.gw_citationattributesdialog import (
                CitationAttributesDialog,
            )

            CitationAttributesDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("citation_attributes"),
                transient_for=self.window,
            ).show_dialog()
            return
        if layer == "link_citation_media":
            from gramps.plugins.tool.gw_linkcitationmediadialog import (
                GWLinkCitationMediaDialog,
            )

            GWLinkCitationMediaDialog(
                title=title,
                dbstate=self.dbstate,
                transient_for=self.window,
            ).show_dialog()
            return
        if layer == "notes":
            from gramps.plugins.tool.gw_notesfixdialog import NotesFixDialog

            NotesFixDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("notes"),
                transient_for=self.window,
            ).show_dialog()
            return

        dialog = Gtk.Dialog(
            title=title, transient_for=self.window, modal=True, destroy_with_parent=True
        )
        dialog.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        dialog.connect("response", lambda dlg, resp: dlg.destroy())
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        label = Gtk.Label(label=get_fix_description(layer))
        label.set_line_wrap(True)
        label.set_halign(Gtk.Align.START)
        content.add(label)
        auto_button = Gtk.Button(label=str(_("Auto (best guess)")))
        auto_button.connect("clicked", self.cb_fix_auto, layer)
        content.add(auto_button)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def cb_fix_auto(self, button: Gtk.Button, layer: str) -> None:
        """Run the no-review fix for one layer (same code as Accept all hints)."""
        if layer not in AUTO_STEP_LAYERS:
            return
        title = get_auto_step_titles().get(layer, layer)
        try:
            message = run_auto_layer(layer, self.dbstate.db)
        except Exception as error:  # pylint: disable=broad-except
            LOG.exception("Auto fix failed for layer %s", layer)
            ErrorDialog(str(_("Fix failed")), str(error), parent=self.window)
            return
        OkDialog(title, message, parent=self.window)

    def cb_auto_all(self) -> None:
        """Run best-guess auto fixes across all cleanup layers in order."""
        confirm = QuestionDialog2(
            str(_("Accept all hints")),
            str(
                _(
                    "This accepts all hints and applies them without review. Each step "
                    "uses the same code as its own dialog's Accept hints and Apply:\n\n"
                    "1. Unpack Conflated Source: unpack source titles, parse mixed text headers, extract repository entries, and separate publication info.\n"
                    "2. Repository Consolidate: merge duplicate repositories into gold-standard ones and clean repeated address lines.\n"
                    "3. Fix Repositories: link sources to best-guess repositories and create missing repository entries.\n"
                    "4. Fix Sources: merge near-duplicates (differing author or publication text is kept in a note), trim whitespace, and quarantine non-sources such as image file names.\n"
                    "5. Unpack Conflated Citation: extract dates and URLs from volume/page fields, without duplicating notes.\n"
                    "6. Fix Citations: lower the confidence of user-tree citations and fill in volume/page and date from the hints.\n"
                    "7. Citation Attributes: assign Genealogical Proof Standard attributes (Source Type, Information Type, Evidence Type) and QUAY confidence.\n"
                    "8. Fix Notes: delete import debris and empty notes, trim whitespace, and remove notes that only repeat a web address already in the citation page.\n\n"
                    "Each step is one transaction: Edit > Undo reverses one step at a time (up to 8 undos)."
                )
            ),
            str(_("_Accept all")),
            str(_("_Cancel")),
            parent=self.window,
        )
        if not confirm.run():
            return
        db = self.dbstate.db
        titles = get_auto_step_titles()
        lines = []
        for number, layer in enumerate(AUTO_STEP_LAYERS, 1):
            try:
                message = run_auto_layer(layer, db)
            except Exception as error:  # pylint: disable=broad-except
                LOG.exception("Auto step %d (%s) failed", number, layer)
                message = str(_("FAILED: %s")) % error
            lines.append("  %d. %s: %s" % (number, titles[layer], message))

        manual_items = find_items_needing_review(db)

        report_sections = [
            str(_("AUTOMATED CHANGES PERFORMED:")),
            *lines,
            "",
        ]

        if manual_items:
            report_sections.append(str(_("CHANGES REQUIRING HUMAN INTERVENTION:")))
            report_sections.extend(manual_items)
        else:
            report_sections.append(
                str(
                    _(
                        "No human intervention required. All cleanup layers are fully resolved."
                    )
                )
            )

        report_dialog = Gtk.Dialog(
            title=str(_("Accept All Hints Complete")),
            transient_for=self.window,
            modal=True,
            destroy_with_parent=True,
        )
        report_dialog.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        content = report_dialog.get_content_area()
        report_text = "\n".join(report_sections)
        label = SelectableLabel(label=report_text)
        content.add(label)
        report_dialog.show_all()
        report_dialog.run()
        report_dialog.destroy()

    def update_view_button(self) -> None:
        """Kept for backward compatibility if called; view button is removed."""
        button = self.buttons.get("view")
        if button is not None:
            button.set_sensitive(report_exists(self.report_path or get_report_path()))

    def _pump_events(self) -> None:
        """Let pending GTK events run so the meter stays responsive."""
        while Gtk.events_pending():
            Gtk.main_iteration()

    def cb_generate_report(self) -> None:
        """Prompt file chooser for CitationFixReport.txt and write generated report."""
        chooser = Gtk.FileChooserDialog(
            title=str(_("Save Citation Fix Report")),
            transient_for=self.window,
            action=Gtk.FileChooserAction.SAVE,
        )
        chooser.set_default_size(600, 400)
        chooser.add_buttons(
            str(_("_Cancel")),
            Gtk.ResponseType.CANCEL,
            str(_("_Save")),
            Gtk.ResponseType.OK,
        )
        chooser.set_current_name(REPORT_FILENAME)

        from gramps.gen.const import USER_DATA

        base_dir = (
            os.path.dirname(self.report_path)
            if self.report_path and os.path.isdir(os.path.dirname(self.report_path))
            else USER_DATA
        )
        if base_dir and os.path.isdir(base_dir):
            chooser.set_current_folder(base_dir)

        status = chooser.run()
        target_path = chooser.get_filename() if status == Gtk.ResponseType.OK else None
        chooser.destroy()

        if not target_path:
            return

        stages = get_report_stages()
        meter = GWizardCitationFixProgressMeter(parent=self.window)
        engine = GWizardCitationReport()

        try:
            meter.show_stage(stages[0])
            self._pump_events()
            stats = engine.collect_db_stats(self.dbstate.db)

            meter.show_stage(stages[3])
            self._pump_events()
            self.report_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            report_body = engine.format_analysis(stats)

            text = (
                f"{_(REPORT_TITLE)}\t\t\t{self.report_datetime}\n"
                + ("=" * REPORT_LINE_WIDTH)
                + "\n\n"
                + report_body
            )

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as handle:
                handle.write(text)
            self.report_path = target_path
            OkDialog(
                str(_("Report Generated")),
                str(_("Report written to %s.") % target_path),
                parent=self.window,
            )
            self.cb_view_report()
        except OSError as error:
            LOG.error("Failed to write citation report: %s", error)
            ErrorDialog(str(_("Report Failed")), str(error), parent=self.window)
        finally:
            meter.close()

    def cb_view_report(self) -> None:
        """Open the generated CitationFixReport.txt in a report window."""
        path = self.report_path or get_report_path()
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            return

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

        dialog.show_all()
        dialog.run()
        dialog.destroy()
