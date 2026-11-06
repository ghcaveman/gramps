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
from gramps.plugins.tool.goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardcitationreport import GWizardCitationReport
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
def get_button_specs() -> list[tuple[str, str, bool]]:
    """Return the (key, label, sensitive) specs for the dialog buttons."""
    return [
        ("generate", str(_("Generate report")), True),
        ("view", str(_("View report")), False),
        ("unpack_sources", str(_("Unpack Conflated Source")), True),
        ("consolidate_repositories", str(_("Repository Consolidate")), True),
        ("fix_repositories", str(_("Fix Repositories")), True),
        ("fix_sources", str(_("Fix Sources")), True),
        ("unpack_citations", str(_("Unpack Conflated Citation")), True),
        ("fix_citations", str(_("Fix Citations")), True),
        ("citation_attributes", str(_("Citation Attributes")), True),
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
            str(_("Clean Tree PAGE/DATE and confidence.")),
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
        self.update_view_button()
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

        for key, label, sensitive in specs[2:-1]:
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
        self.close()

    def cb_button(self, button: Gtk.Button, key: str) -> None:
        """Dispatch dialog button clicks."""
        if key == "generate":
            self.cb_generate_report()
        elif key == "view":
            self.cb_view_report()
        elif key == "unpack_sources":
            self.cb_fix_layer("unpack_sources")  # Route the new button click
        elif key == "consolidate_repositories":
            from gramps.plugins.tool.repoconsolidatedialog import RepoConsolidateDialog

            RepoConsolidateDialog(self.dbstate, transient_for=self.window).run()
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
        elif key == "fix_notes":
            self.cb_fix_layer("notes")
        elif key == "auto_all":
            self.cb_auto_all()

    def cb_fix_layer(self, layer: str) -> None:
        titles = get_fix_layer_titles()
        self.show_fix_dialog(layer, titles.get(layer, layer))

    def show_fix_dialog(self, layer: str, title: str) -> None:
        if layer == "unpack_sources":
            from gramps.plugins.tool.unpacksourcesdialog import UnpackSourcesDialog

            UnpackSourcesDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("unpack_sources"),
                transient_for=self.window,
            ).show_dialog()
            self.update_view_button()
            return
        if layer == "repositories":
            from gramps.plugins.tool.repomergedialog import RepoMergeDialog

            RepoMergeDialog(
                title=title, dbstate=self.dbstate, transient_for=self.window
            ).show_dialog()
            return
        if layer == "sources":
            from gramps.plugins.tool.sourcesfixdialog import SourceFixDialog

            SourceFixDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("sources"),
                transient_for=self.window,
            ).show_dialog()
            return
        if layer == "unpack_citations":
            from gramps.plugins.tool.unpackcitationsdialog import UnpackCitationsDialog

            UnpackCitationsDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("unpack_citations"),
                transient_for=self.window,
            ).show_dialog()
            self.update_view_button()
            return
        if layer == "citations":
            try:
                from gramps.plugins.tool.citationsfixdialog import CitationFixDialog
            except ImportError:
                LOG.warning("citationsfixdialog not available; using auto fix")
            else:
                CitationFixDialog(
                    title=title,
                    dbstate=self.dbstate,
                    description=get_fix_description("citations"),
                    transient_for=self.window,
                ).show_dialog()
                return
        if layer == "citation_attributes":
            from gramps.plugins.tool.citationattributesdialog import (
                CitationAttributesDialog,
            )

            CitationAttributesDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("citation_attributes"),
                transient_for=self.window,
            ).show_dialog()
            self.update_view_button()
            return
        if layer == "notes":
            from gramps.plugins.tool.notesfixdialog import NotesFixDialog

            NotesFixDialog(
                title=title,
                dbstate=self.dbstate,
                description=get_fix_description("notes"),
                transient_for=self.window,
            ).show_dialog()
            self.update_view_button()
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
        """Run the best-guess auto fix for one layer without a review dialog."""
        engine = GWizardCitationRepairEngine()
        actions = {
            "unpack_sources": (
                engine.unpack_conflated_sources,
                str(_("Field Unpacking Complete")),
                str(_("Unpacked %d source titles into repository and source fields.")),
            ),
            "repositories": (
                engine.consolidate_duplicate_repositories,
                str(_("Repository Consolidate Complete")),
                str(_("Merged %d matching repository records.")),
            ),
            "sources": (
                engine.consolidate_duplicate_sources,
                str(_("Source Cleanup Complete")),
                str(_("Merged %d duplicate source records.")),
            ),
            "citations": (
                engine.clean_and_rate_citations,
                str(_("Citation Refinement Complete")),
                str(_("Adjusted confidence ratings or page text on %d citations.")),
            ),
            "notes": (
                engine.purge_import_debris_notes,
                str(_("Note Cleanup Complete")),
                str(_("Permanently removed %d import debris notes.")),
            ),
        }
        action = actions.get(layer)
        if action is None:
            return
        func, title, message = action
        try:
            count = func(self.dbstate.db)
        except Exception as error:  # pylint: disable=broad-except
            LOG.exception("Auto fix failed for layer %s", layer)
            ErrorDialog(str(_("Fix failed")), str(error), parent=self.window)
            return
        OkDialog(title, message % count, parent=self.window)
        self.update_view_button()

    def cb_auto_all(self) -> None:
        """Run best-guess auto fixes across all cleanup layers in order."""
        confirm = QuestionDialog2(
            str(_("Run all fixes?")),
            str(
                _(
                    "This applies every best-guess fix without review: unpack "
                    "source titles, merge duplicate repositories and sources, "
                    "clean citations, and permanently delete import debris "
                    "notes. Each step can be undone with Edit > Undo."
                )
            ),
            str(_("_Run all")),
            str(_("_Cancel")),
            parent=self.window,
        )
        if not confirm.run():
            return
        engine = GWizardCitationRepairEngine()
        db = self.dbstate.db
        steps = [
            (
                str(_("Unpacked %d mixed source titles.")),
                engine.unpack_conflated_sources,
            ),
            (
                str(_("Merged %d duplicate repository records.")),
                engine.consolidate_duplicate_repositories,
            ),
            (
                str(_("Merged %d duplicate source records.")),
                engine.consolidate_duplicate_sources,
            ),
            (str(_("Refined %d citations.")), engine.clean_and_rate_citations),
            (
                str(_("Purged %d import debris notes.")),
                engine.purge_import_debris_notes,
            ),
        ]
        lines = []
        for number, (message, func) in enumerate(steps, 1):
            try:
                lines.append("%d. %s" % (number, message % func(db)))
            except Exception as error:  # pylint: disable=broad-except
                LOG.exception("Auto step %d failed", number)
                lines.append("%d. %s" % (number, str(_("FAILED: %s")) % error))
        OkDialog(
            str(_("Global Macro Pipeline Complete")),
            str(_("The automated best-guess pipeline results:"))
            + "\n\n"
            + "\n".join(lines),
            parent=self.window,
        )
        self.update_view_button()

    def update_view_button(self) -> None:
        """Enable View report only when the report file exists."""
        button = self.buttons.get("view")
        if button is not None:
            button.set_sensitive(report_exists(self.report_path or get_report_path()))

    def _pump_events(self) -> None:
        """Let pending GTK events run so the meter stays responsive."""
        while Gtk.events_pending():
            Gtk.main_iteration()

    def cb_generate_report(self) -> None:
        """Generate the CitationFixReport.txt with modular engine metrics."""
        stages = get_report_stages()
        meter = GWizardCitationFixProgressMeter(parent=self.window)
        engine = GWizardCitationReport()

        try:
            meter.show_stage(stages[0])
            self._pump_events()
            stats = engine.collect_db_stats(self.dbstate.db)

            meter.show_stage(stages[3])
            self._pump_events()
            self.report_datetime = datetime.now().strftime("%Y-%m-%d %H:%M")
            report_body = engine.format_analysis(stats)

            text = (
                f"{_(REPORT_TITLE)}\t\t\t{self.report_datetime}\n"
                + ("=" * REPORT_LINE_WIDTH)
                + "\n\n"
                + report_body
            )
            self.report_path = get_report_path()

            os.makedirs(os.path.dirname(self.report_path), exist_ok=True)
            with open(self.report_path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as error:
            LOG.error("Failed to write citation report: %s", error)
            ErrorDialog(str(_("Report Failed")), str(error), parent=self.window)
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
            return

        title, timestamp = parse_report_header(text)
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

        dialog.show_all()
        dialog.run()
        dialog.destroy()
