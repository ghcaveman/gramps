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

"""Tests for the GWizard citation fix tool button layout."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import os
import types
import unittest


# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
def get_button_specs_from_source() -> list[tuple[str, str, bool]]:
    """Parse the button specs without importing Gtk/Gramps."""
    import ast

    tool_path = os.path.join(os.path.dirname(__file__), "..", "gwizardcitationfix.py")
    with open(tool_path, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_button_specs":
            returned = node.body[-1]
            assert isinstance(returned, ast.Return)
            assert isinstance(returned.value, ast.List)
            specs: list[tuple[str, str, bool]] = []
            for elt in returned.value.elts:
                assert isinstance(elt, ast.Tuple)
                key = ast.literal_eval(elt.elts[0])
                sensitive = ast.literal_eval(elt.elts[2])
                label_src = ast.get_source_segment(source, elt.elts[1]) or ""
                specs.append((key, label_src, sensitive))
            return specs
    raise AssertionError("get_button_specs not found")


def get_button_specs() -> list[tuple[str, str, bool]]:
    """Return button specs parsed from the tool source."""
    return get_button_specs_from_source()


# ------------------------------------------------------------
#
# GWizardCitationFixButtonTest
#
# ------------------------------------------------------------
class GWizardCitationFixButtonTest(unittest.TestCase):
    """Check the dialog exposes seven buttons with the right layout."""

    def test_seven_buttons(self) -> None:
        """There are seven button specs."""
        self.assertEqual(len(get_button_specs()), 7)

    def test_top_buttons_side_by_side(self) -> None:
        """First two specs are the side-by-side report buttons."""
        specs = get_button_specs()
        self.assertEqual(specs[0][0], "generate")
        self.assertIn("Generate report", specs[0][1])
        self.assertEqual(specs[1][0], "view")
        self.assertIn("View report", specs[1][1])

    def test_fix_layer_buttons(self) -> None:
        """Four per-layer fix buttons follow the report buttons."""
        specs = get_button_specs()
        keys = [key for key, _label, _sens in specs[2:6]]
        self.assertEqual(
            keys,
            ["fix_repositories", "fix_sources", "fix_citations", "fix_notes"],
        )
        labels = [label for _key, label, _sens in specs[2:6]]
        for expected in (
            "Fix Repositories",
            "Fix Sources",
            "Fix Citations",
            "Fix Notes",
        ):
            self.assertTrue(
                any(expected in label for label in labels),
                f"missing fix button: {expected}",
            )

    def test_master_auto_button(self) -> None:
        """A master Auto best-guess button closes the dialog."""
        specs = get_button_specs()
        self.assertEqual(specs[6][0], "auto_all")
        self.assertIn("Auto", specs[6][1])

    def test_view_starts_disabled(self) -> None:
        """View report is insensitive until a report file exists."""
        specs = dict((key, sensitive) for key, _label, sensitive in get_button_specs())
        self.assertTrue(specs["generate"])
        self.assertFalse(specs["view"])

    def test_view_enabling_wired(self) -> None:
        """Dialog checks for the file on load and after Generate."""
        source = read_tool_source()
        self.assertIn("def report_exists", source)
        self.assertIn("def update_view_button", source)
        self.assertIn("self.update_view_button()", source)
        self.assertIn("report_exists(path)", source)


# ------------------------------------------------------------
#
# Source helpers for GUI-free assertions
#
# ------------------------------------------------------------
def read_tool_source() -> str:
    """Return the raw tool source text."""
    tool_path = os.path.join(os.path.dirname(__file__), "..", "gwizardcitationfix.py")
    with open(tool_path, encoding="utf-8") as handle:
        return handle.read()


# ------------------------------------------------------------
#
# GWizardCitationFixReportTest
#
# ------------------------------------------------------------
class GWizardCitationFixReportTest(unittest.TestCase):
    """Check the staged meter and report file wiring in the source."""

    def test_progress_meter_named_like_gwizard(self) -> None:
        """A GWizardCitationFixProgressMeter wraps the GWizard pattern."""
        source = read_tool_source()
        self.assertIn("class GWizardCitationFixProgressMeter(ProgressMeter)", source)
        self.assertIn("MODE_ACTIVITY", source)
        self.assertIn('str(_("Loading Citation Fix"))', source)

    def test_stages_start_and_finish(self) -> None:
        """Stages begin with Starting analysis and end with Report complete!."""
        source = read_tool_source()
        self.assertIn('str(_("Starting analysis"))', source)
        self.assertIn('str(_("Report complete!"))', source)
        self.assertIn("def show_stage", source)

    def test_report_file_and_header_layout(self) -> None:
        """Generate writes CitationFixReport.txt; View parses title/date."""
        source = read_tool_source()
        self.assertIn('REPORT_FILENAME = "CitationFixReport.txt"', source)
        self.assertIn('REPORT_TITLE = "Citation analysis file"', source)
        self.assertIn('size="smaller"', source)
        self.assertIn("def parse_report_header", source)
        self.assertIn("with open(self.report_path", source)
        self.assertIn("with open(path, encoding=", source)


# ------------------------------------------------------------
#
# GWizardCitationFixAnalysisTest
#
# ------------------------------------------------------------
class GWizardCitationFixAnalysisTest(unittest.TestCase):
    """Check the repository/source/citation analysis wiring in the source."""

    def test_analysis_helpers_exist(self) -> None:
        """Collector, formatter and title normalizer are defined."""
        source = read_tool_source()
        self.assertIn("def normalize_source_title", source)
        self.assertIn("def collect_db_stats", source)
        self.assertIn("def format_analysis", source)

    def test_report_covers_example_findings(self) -> None:
        """Report covers totals, repos, page gaps, dupes, notes, media."""
        source = read_tool_source()
        self.assertIn("Database totals:", source)
        self.assertIn("Sources without a repository", source)
        self.assertIn("Citations with no Volume/Page", source)
        self.assertIn("FamilySearch Family Tree citations", source)
        self.assertIn("Near-duplicate source groups", source)
        self.assertIn("bare URLs", source)
        self.assertIn("absolute paths", source)
        self.assertIn("Suggested order of fixes", source)

    def test_generate_passes_live_stats(self) -> None:
        """Generate collects db stats and passes them to the builder."""
        source = read_tool_source()
        self.assertIn("collect_db_stats(self.dbstate.db)", source)
        self.assertIn("stats: dict[str, Any] | None = None", source)
        self.assertIn("stages, stats", source)

    def test_title_normalizer_groups_us_variants(self) -> None:
        """U.S. and punctuation variants normalize to the same key."""
        first = "Philadelphia, Pennsylvania, U.S., Death Certificates Index"
        second = "Philadelphia Pennsylvania Death Certificates Index"
        norm = normalize_for_test(first)
        self.assertEqual(norm, normalize_for_test(second))
        self.assertNotIn("u s", norm)


def normalize_for_test(title: str) -> str:
    """Mirror normalize_source_title without importing Gtk/Gramps."""
    import re

    key = (title or "").lower().strip()
    key = key.replace("&", "and")
    key = re.sub(r"\bu\.?\s*s\.?\b", " ", key)
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


# ------------------------------------------------------------
#
# GWizardCitationFixLayerTest
#
# ------------------------------------------------------------
class GWizardCitationFixLayerTest(unittest.TestCase):
    """Check the per-layer fix dialogs and Auto buttons."""

    def test_fix_layer_specs(self) -> None:
        """Four layer specs exist: repositories, sources, citations, notes."""
        source = read_tool_source()
        self.assertIn("def get_fix_layer_specs", source)
        self.assertIn("def get_fix_layer_titles", source)
        for layer in ("repositories", "sources", "citations", "notes"):
            self.assertIn(f'"{layer}"', source)

    def test_fix_dialog_has_auto_button(self) -> None:
        """Each layer dialog offers an Auto best-guess button."""
        source = read_tool_source()
        self.assertIn("def show_fix_dialog", source)
        self.assertIn("def cb_fix_layer", source)
        self.assertIn("def cb_fix_auto", source)
        self.assertIn("def summarize_auto_fix", source)
        self.assertIn("Auto (best guess)", source)

    def test_master_auto_runs_all_layers(self) -> None:
        """Master Auto iterates all layers in order."""
        source = read_tool_source()
        self.assertIn("def cb_auto_all", source)
        self.assertIn("get_fix_layer_specs()", source)
        self.assertIn("Auto fix preview (all layers)", source)


# ------------------------------------------------------------
#
# GWizardCitationFixRepoMergeTest
#
# ------------------------------------------------------------
class GWizardCitationFixRepoMergeTest(unittest.TestCase):
    """Check the golden-name repository merge model."""

    def _load_logic(self) -> dict[str, object]:
        """Load pure repo-merge helpers without importing Gtk/Gramps."""
        import ast
        import os
        import sys

        source = read_tool_source()
        tree = ast.parse(source)
        wanted = {
            "collect_sources_by_repo",
            "get_golden_repository_names",
            "normalize_repo_name",
            "is_golden_repo_name",
            "rank_golden_repo_matches",
            "build_repo_merge_rows",
            "plan_repo_merges",
        }
        module = ast.Module(
            body=[
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in wanted
            ],
            type_ignores=[],
        )
        tool_dir = os.path.join(os.path.dirname(__file__), "..")
        sys.path.insert(0, os.path.abspath(tool_dir))
        try:
            from goldstandardrepos import GoldStandardRepositories
        finally:
            sys.path.pop(0)
        namespace: dict[str, object] = {"re": __import__("re")}
        namespace["difflib"] = __import__("difflib")
        namespace["defaultdict"] = __import__("collections").defaultdict
        namespace["_"] = lambda text: text

        def _safe_iter(db, name):
            try:
                method = getattr(db, name, None)
                if method is None:
                    return []
                return list(method())
            except Exception:
                return []

        namespace["_safe_iter"] = _safe_iter
        namespace["GoldStandardRepositories"] = GoldStandardRepositories
        namespace["_QUARANTINE_REPO_NAME"] = "Quarantine"
        exec(compile(module, "<repo_merge>", "exec"), namespace)  # noqa: S102
        return namespace

    def test_golden_names_exist(self) -> None:
        """Golden list contains well-known repositories."""
        logic = self._load_logic()
        names = logic["get_golden_repository_names"]()
        self.assertIn("Ancestry.com", names)
        self.assertIn("FamilySearch", names)
        self.assertGreaterEqual(len(names), 20)

    def test_golden_match_is_skipped(self) -> None:
        """A golden name on the left is skipped entirely."""
        logic = self._load_logic()
        rows = logic["build_repo_merge_rows"](["FamilySearch", "family junk"])
        by_name = {row["name"]: row for row in rows}
        self.assertTrue(by_name["FamilySearch"]["skip"])
        self.assertFalse(by_name["family junk"]["skip"])

    def test_bypass_entry_is_first_option(self) -> None:
        """Dropdown lists the original name first as the bypass entry."""
        logic = self._load_logic()
        rows = logic["build_repo_merge_rows"](["family junk"])
        self.assertEqual(rows[0]["options"][0], "family junk")
        self.assertIn(rows[0]["best_guess"], rows[0]["options"][1:])

    def test_closest_golden_ranks_first(self) -> None:
        """Closest golden names rank ahead of unrelated ones."""
        logic = self._load_logic()
        matches = logic["rank_golden_repo_matches"]("familysearch films")
        self.assertEqual(matches[0], "FamilySearch")

    def test_plan_skips_bypass_choices(self) -> None:
        """Bypass (same-name) picks produce no merge work."""
        logic = self._load_logic()
        plan = logic["plan_repo_merges"](
            {"a": "a", "b": "FamilySearch", "c": "FamilySearch"}
        )
        self.assertEqual(plan, {"FamilySearch": ["b", "c"]})

    def test_collect_sources_by_repo(self) -> None:
        """Sources map to their referencing repositories via RepoRef."""
        logic = self._load_logic()
        collect = logic["collect_sources_by_repo"]

        class FakeRepoRef:
            def __init__(self, handle):
                self._handle = handle

            def get_reference_handle(self):
                return self._handle

        class FakeSource:
            def __init__(self, title, repo_handles):
                self._title = title
                self._repo_handles = repo_handles

            def get_title(self):
                return self._title

            def get_reporef_list(self):
                return [FakeRepoRef(h) for h in self._repo_handles]

        class FakeRepo:
            def __init__(self, handle, name):
                self._handle = handle
                self._name = name

            def get_handle(self):
                return self._handle

            def get_name(self):
                return self._name

        class FakeDb:
            def __init__(self):
                self._repos = [
                    FakeRepo("r1", "FamilySearch"),
                    FakeRepo("r2", "Ancestry.com"),
                    FakeRepo("r3", "Empty Repo"),
                ]
                self._sources = [
                    FakeSource("1880 Census", ["r1"]),
                    FakeSource("1900 Census", ["r1"]),
                    FakeSource("Birth Records", ["r2"]),
                    FakeSource("Orphan Source", []),
                ]

            def iter_repositories(self):
                return iter(self._repos)

            def iter_sources(self):
                return iter(self._sources)

        result = collect(FakeDb())
        self.assertEqual(result["FamilySearch"], ["1880 Census", "1900 Census"])
        self.assertEqual(result["Ancestry.com"], ["Birth Records"])
        self.assertNotIn("Empty Repo", result)
        self.assertNotIn("Orphan Source", [s for srcs in result.values() for s in srcs])

    def test_dialog_wiring_exists(self) -> None:
        """Merge dialog lives in its own RepoMergeDialog class."""
        import ast
        import os

        source = read_tool_source()
        self.assertIn("def show_repo_merge_dialog", source)
        self.assertIn("RepoMergeDialog", source)
        self.assertIn("def cb_repo_auto", source)
        path = os.path.join(os.path.dirname(__file__), "..", "repomergedialog.py")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        tree = ast.parse(content)
        found = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "RepoMergeDialog"
        ]
        self.assertTrue(found)
        for token in (
            "def build_header",
            "def build_rows",
            "def build_buttons",
            "def get_choices",
            "def apply_merges",
            "def run_auto",
            "def show_dialog",
            "def cb_set_best",
            "def cb_apply",
            "def collect_repo_names",
            "def find_repository_by_name",
        ):
            self.assertIn(token, content)

    def test_gold_catalog_has_details(self) -> None:
        """Gold catalog exposes detail helpers for the dropdown."""
        import ast
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "goldstandardrepos.py")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        tree = ast.parse(content)
        found = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and node.name == "GoldStandardRepositories"
        ]
        self.assertTrue(found)
        self.assertIn("get_display_label", content)
        self.assertIn("GENEALOGY_REPOSITORIES", content)


# ------------------------------------------------------------
#
# GWizardCitationFixSourceFixTest
#
# ------------------------------------------------------------
class GWizardCitationFixSourceFixTest(unittest.TestCase):
    """Check the source-record fix model."""

    def _load_logic(self) -> dict[str, object]:
        """Load pure source-fix helpers without importing Gtk/Gramps."""
        import ast
        import os
        import sys

        source_path = os.path.join(
            os.path.dirname(__file__), "..", "sourcesfixdialog.py"
        )
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        wanted = {
            "build_source_fix_rows",
            "plan_source_fixes",
            "_source_display",
            "_dedupe_handles",
            "_pick_keeper",
        }
        module = ast.Module(
            body=[
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in wanted
            ],
            type_ignores=[],
        )
        tool_dir = os.path.join(os.path.dirname(__file__), "..")
        sys.path.insert(0, os.path.abspath(tool_dir))
        try:
            from goldstandardrepos import GoldStandardRepositories  # noqa: F401
        finally:
            sys.path.pop(0)
        namespace: dict[str, object] = {"re": __import__("re")}
        namespace["defaultdict"] = __import__("collections").defaultdict
        namespace["_"] = lambda text: text
        namespace["GoldStandardRepositories"] = GoldStandardRepositories
        namespace["_QUARANTINE_REPO_NAME"] = "Quarantine"
        exec(compile(module, "<source_fix>", "exec"), namespace)  # noqa: S102
        return namespace

    def test_source_fix_rows_build(self) -> None:
        """Duplicate groups merge and clean sources stay out of quarantine."""
        logic = self._load_logic()
        build = logic["build_source_fix_rows"]

        stats = {
            "source_rows": [
                {
                    "handle": "h1",
                    "title": "Smith, John",
                    "author": "A",
                    "gramps_id": "g1",
                    "repo_count": 0,
                    "citations": 0,
                },
                {
                    "handle": "h2",
                    "title": "Smith, John ",
                    "author": "A",
                    "gramps_id": "g2",
                    "repo_count": 0,
                    "citations": 0,
                },
                {
                    "handle": "h3",
                    "title": "Jones, Mary",
                    "author": "",
                    "gramps_id": "g3",
                    "repo_count": 1,
                    "citations": 3,
                },
                {
                    "handle": "h4",
                    "title": "Unattributed",
                    "author": "",
                    "gramps_id": "g4",
                    "repo_count": 0,
                    "citations": 0,
                },
            ],
            "near_duplicates": [
                [
                    {
                        "title": "Smith, John",
                        "author": "A",
                        "gramps_id": "g1",
                        "handle": "h1",
                        "repo_count": 0,
                        "citations": 0,
                    },
                    {
                        "title": "Smith, John ",
                        "author": "A",
                        "gramps_id": "g2",
                        "handle": "h2",
                        "repo_count": 0,
                        "citations": 0,
                    },
                ],
            ],
        }
        rows = build(stats)
        merge = [r for r in rows if r["problem"] == "merge"]
        quars = [r for r in rows if r["problem"] == "quarantine"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(merge), 1)
        self.assertEqual(merge[0]["keeper_handle"], "h1")
        self.assertEqual(merge[0]["discard_handles"], ["h2"])
        self.assertEqual({r["quarantine_handle"] for r in quars}, {"h4"})
        rec = quars[0]
        self.assertEqual(rec["best_guess"], "Quarantine new repository")
        self.assertEqual(rec["options"], ["Quarantine new repository"])
        self.assertFalse(any(r["quarantine_handle"] == "h3" for r in quars))

    def test_plan_source_fixes(self) -> None:
        """Plan splits merge and quarantine actions without touching DB."""
        logic = self._load_logic()
        plan = logic["plan_source_fixes"]

        rows = [
            {
                "problem": "merge",
                "keeper_handle": "k",
                "discard_handles": ["d1", "d2"],
                "skip": False,
            },
            {
                "problem": "quarantine",
                "quarantine_handle": "q",
                "skip": False,
            },
            {"skip": True, "problem": "merge", "keeper_handle": "x"},
        ]
        result = plan(rows)
        self.assertEqual(
            result["merge"], [{"keeper_handle": "k", "discard_handles": ["d1", "d2"]}]
        )
        self.assertEqual(
            result["quarantine"],
            [{"source_handle": "q", "target_repo_name": "Quarantine"}],
        )

    def test_no_problem_stats_yields_no_plan(self) -> None:
        """A clean database yields no fix rows and an empty plan."""
        logic = self._load_logic()
        build = logic["build_source_fix_rows"]
        plan = logic["plan_source_fixes"]

        stats = {
            "source_rows": [
                {
                    "handle": "h1",
                    "title": "Jones, Mary",
                    "author": "",
                    "gramps_id": "g1",
                    "repo_count": 1,
                    "citations": 3,
                },
            ],
            "near_duplicates": [],
        }
        self.assertEqual(build(stats), [])
        self.assertEqual(plan([]), {"merge": [], "quarantine": []})

    def test_dialog_wiring_and_file_exist(self) -> None:
        """SourceFixDialog class and module exist and mirror the repo dialog."""
        import os

        path = os.path.join(os.path.dirname(__file__), "..", "sourcesfixdialog.py")
        self.assertTrue(os.path.exists(path), "sourcesfixdialog.py not found")
        import ast

        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        tree = ast.parse(content)
        found = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "SourceFixDialog"
        ]
        self.assertTrue(found, "SourceFixDialog class missing")
        for token in (
            "def build_header",
            "def build_rows",
            "def build_buttons",
            "def run_auto",
            "def show_dialog",
            "def cb_set_best",
            "def cb_apply",
        ):
            self.assertIn(token, content, "missing %r" % token)


# ------------------------------------------------------------
#
# GWizardCitationFixCitationFixTest
#
# ------------------------------------------------------------
class GWizardCitationFixCitationFixTest(unittest.TestCase):
    """Check the citation-fix dialog model and auto-clean behavior."""

    def _load_logic(self) -> dict[str, object]:
        """Load pure citation-fix helpers without importing Gtk/Gramps."""
        import ast

        source_path = os.path.join(
            os.path.dirname(__file__), "..", "citationsfixdialog.py"
        )
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        wanted = {
            "build_citation_fix_rows",
            "plan_citation_fixes",
            "apply_citation_fixes",
            "_tree_source_handles",
        }
        module = ast.Module(
            body=[
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in wanted
            ],
            type_ignores=[],
        )
        namespace: dict[str, object] = {"re": __import__("re")}
        namespace["defaultdict"] = __import__("collections").defaultdict
        namespace["_"] = lambda text: text
        namespace["DbTxn"] = object
        namespace["Gtk"] = object
        namespace["OkDialog"] = object
        namespace["PROBLEM_NO_PAGE"] = "no_page"
        namespace["PROBLEM_NO_DATE"] = "no_date"
        namespace["PROBLEM_TREE_CONFIDENCE"] = "tree_confidence"
        exec(compile(module, "<citation_fix>", "exec"), namespace)  # noqa: S102
        return namespace

    def _sample_statistics(self) -> dict[str, object]:
        return {
            "citations_no_page": 5,
            "citations_no_date": 3,
            "tree_conf_high": 7,
        }

    def test_citation_fix_rows_build(self) -> None:
        """Rows cover missing page, missing date, and over-confident tree."""
        logic = self._load_logic()
        build = logic["build_citation_fix_rows"]

        rows = build(self._sample_statistics())
        self.assertEqual(len(rows), 3)
        problems = {r["problem"] for r in rows}
        self.assertIn("no_page", problems)
        self.assertIn("no_date", problems)
        self.assertIn("tree_confidence", problems)

        tree = [r for r in rows if r["problem"] == "tree_confidence"][0]
        self.assertEqual(
            tree["display"], "Lower confidence of 7 FamilySearch Tree citations"
        )
        self.assertEqual(tree["best_guess"], "Lower to Confidence 1")

    def test_plan_citation_fixes(self) -> None:
        """Plan groups selected actions per problem type."""
        logic = self._load_logic()
        plan = logic["plan_citation_fixes"]

        rows = [
            {
                "skip": False,
                "problem": "tree_confidence",
                "best_guess": "Lower to Confidence 1",
            },
            {
                "skip": True,
                "problem": "tree_confidence",
                "best_guess": "Lower to Confidence 2",
            },
        ]
        result = plan(rows)
        self.assertEqual(result["tree_confidence"], ["Lower to Confidence 1"])

    def test_apply_lowers_tree_confidence(self) -> None:
        """Auto-clean lowers confidence for in-tree citations rated 3+."""
        logic = self._load_logic()
        apply_fixes = logic["apply_citation_fixes"]

        class FakeCitation:
            def __init__(self, handle, confidence):
                self._handle = handle
                self._confidence = confidence

            def get_reference_handle(self):
                return self._handle

            def get_confidence_level(self):
                return self._confidence

            def set_confidence_level(self, level):
                self._confidence = level

        class FakeDb:
            def __init__(self, citations):
                self._citations = citations

            def iter_sources(self):
                class Src:
                    def __init__(self, handle):
                        self._handle = handle

                    def get_handle(self):
                        return self._handle

                    def get_title(self):
                        return "FamilySearch Family Tree"

                return [Src("tree1"), Src("tree2")]

            def iter_citations(self):
                return iter(self._citations)

            def get_undodb(self):
                return []

            def transaction_begin(self, transaction):
                return None

            def transaction_commit(self, transaction):
                return None

            def transaction_abort(self, transaction):
                return None

            def commit_citation(self, citation, trans=None, change_time=None):
                return True

        citations = [
            FakeCitation("tree1", 4),
            FakeCitation("tree2", 3),
            FakeCitation("tree3", 2),
            FakeCitation("other1", 4),
        ]
        dbstate = types.SimpleNamespace(db=FakeDb(citations))
        result = apply_fixes(dbstate, {"tree_confidence": ["Lower to Confidence 1"]})

        self.assertEqual(result["tree_confidence_lowered"], 2)
        self.assertEqual(citations[0]._confidence, 1)
        self.assertEqual(citations[1]._confidence, 1)
        self.assertEqual(citations[2]._confidence, 2)
        self.assertEqual(citations[3]._confidence, 4)

    def test_dialog_wiring_and_file_exist(self) -> None:
        """CitationFixDialog class and module exist and mirror the repo dialog."""
        import ast

        path = os.path.join(os.path.dirname(__file__), "..", "citationsfixdialog.py")
        self.assertTrue(os.path.exists(path), "citationsfixdialog.py not found")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        tree = ast.parse(content)
        found = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "CitationFixDialog"
        ]
        self.assertTrue(found, "CitationFixDialog class missing")
        for token in (
            "def build_header",
            "def build_rows",
            "def build_buttons",
            "def run_auto",
            "def show_dialog",
            "def cb_set_best",
            "def cb_apply",
        ):
            self.assertIn(token, content, "missing %r" % token)


if __name__ == "__main__":
    unittest.main()
