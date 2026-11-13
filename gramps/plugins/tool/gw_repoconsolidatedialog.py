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

"""Repository consolidate dialog for the GWizard citation fix tool."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import difflib
import logging
from collections import defaultdict
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gdk, Gtk, Pango

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db import DbTxn
from gramps.gen.lib import Note, NoteType
from gramps.gui.dialog import ErrorDialog, OkDialog
from gramps.plugins.tool.gw_goldstandardrepos import GoldStandardRepositories
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardcitationshared import normalize_repo_name
from gramps.plugins.tool.gwizardcitationfix import rank_golden_repo_matches

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


def _strip_the(text: str) -> str:
    """Return text lower-cased with a leading 'the ' removed."""
    low = " ".join((text or "").split()).casefold()
    return low[4:] if low.startswith("the ") else low


def classify_repo_street(repo_name: str, street: str) -> tuple[str, str]:
    """Decide what to do with a repository address street line.

    :returns: ``(action, detail)`` where action is ``"keep"`` (a real
        address), ``"drop"`` (it only repeats the repository name) or
        ``"move"`` (it is the name followed by extra text, returned as
        *detail*, which belongs in a note rather than an address).
    """
    street = " ".join((street or "").split())
    if not street:
        return "keep", ""
    name_key = _strip_the(repo_name)
    street_key = _strip_the(street)
    if not name_key:
        return "keep", ""
    if street_key == name_key:
        return "drop", ""
    if street_key.startswith(name_key):
        base = street[4:] if street.casefold().startswith("the ") else street
        name_base = (
            " ".join(repo_name.split())[4:]
            if " ".join(repo_name.split()).casefold().startswith("the ")
            else " ".join(repo_name.split())
        )
        remainder = base[len(name_base) :].strip(" \t-:;,")
        remainder = remainder.strip("()[] ").strip()
        if remainder:
            return "move", remainder
        return "drop", ""
    return "keep", ""


def _find_or_create_golden(
    db: Any,
    golden_name: str,
    engine: GWizardCitationRepairEngine | None,
    trans: Any,
) -> tuple[str | None, bool]:
    """Return ``(handle, created)`` for a golden repository.

    The repository is created inside ``trans`` when it does not exist, so
    creating it and merging into it are one undo step.
    """
    for repo in db.iter_repositories():
        if repo and repo.get_name() == golden_name:
            return str(repo.get_handle()), False
    repair_engine = engine or GWizardCitationRepairEngine()
    try:
        return repair_engine._create_repository(db, golden_name, trans), True
    except Exception:  # pylint: disable=broad-except
        LOG.exception("Failed to create golden repository %s", golden_name)
        return None, False


def _tidy_keeper_address(
    db: Any, keeper_handle: str, trans: Any = None
) -> tuple[int, int]:
    """Clean address lines on the surviving repository.

    Joins ``trans`` when given, otherwise makes its own transaction.

    :returns: ``(removed, moved)`` counts.
    """
    if trans is None:
        with DbTxn(_("Tidy repository address"), db) as new_trans:
            return _tidy_keeper_address(db, keeper_handle, new_trans)
    repo = db.get_repository_from_handle(keeper_handle)
    if repo is None:
        return 0, 0
    name = repo.get_name() or ""
    removed = moved = 0
    kept = []
    details: list[str] = []
    for addr in repo.get_address_list():
        action, detail = classify_repo_street(name, addr.get_street())
        if action == "keep":
            kept.append(addr)
            continue
        if action == "move":
            details.append(detail)
        addr.set_street("")
        others = (
            addr.get_locality(),
            addr.get_city(),
            addr.get_county(),
            addr.get_state(),
            addr.get_country(),
            addr.get_postal_code(),
            addr.get_phone(),
        )
        if any((value or "").strip() for value in others):
            kept.append(addr)
        else:
            removed += 1
    try:
        repo.set_address_list(kept)
        for detail in details:
            text = str(_("Place detail from address: %s")) % detail
            if any(
                (db.get_note_from_handle(n_handle) is not None)
                and db.get_note_from_handle(n_handle).get() == text
                for n_handle in repo.get_note_list()
            ):
                continue
            note = Note()
            note.set(text)
            note.set_type(NoteType.REPO)
            note_handle = db.add_note(note, trans)
            repo.add_note(note_handle)
            moved += 1
        db.commit_repository(repo, trans)
    except Exception:  # pylint: disable=broad-except
        LOG.exception("Failed to tidy address for repository %s", name)
        return 0, 0
    return removed, moved


def _resolve_chain(handle: str, targets: dict[str, str]) -> str:
    """Follow merge targets to the final keeper, stopping at any cycle."""
    seen = {handle}
    current = handle
    while current in targets:
        current = targets[current]
        if current in seen:
            return handle
        seen.add(current)
    return current


def apply_repo_consolidations(
    db: Any,
    changes: list[tuple[str, str]],
    engine: GWizardCitationRepairEngine | None = None,
    trans: Any = None,
    tidy_handles: list[str] | None = None,
) -> dict[str, Any]:
    """Merge repositories and tidy their addresses in one transaction.

    ``changes`` is a list of ``(discard_handle, target)`` where target is a
    repository handle or ``GOLDEN:<name>`` (the golden repository is created
    when missing). Targets that are themselves merged away are followed to
    the final keeper. ``tidy_handles`` are repositories whose address should
    be cleaned in place without a merge. This is the one implementation used
    by the dialog's Apply button, its ``run_auto`` and Accept all hints.

    :returns: dict with ``merged``, ``created``, ``removed``, ``moved`` counts
        and an ``errors`` list.
    """
    if trans is None:
        with DbTxn(_("Consolidate Repositories"), db) as new_trans:
            return apply_repo_consolidations(
                db, changes, engine, new_trans, tidy_handles
            )
    repair_engine = engine or GWizardCitationRepairEngine()
    result: dict[str, Any] = {
        "merged": 0,
        "created": 0,
        "removed": 0,
        "moved": 0,
        "errors": [],
    }
    golden_cache: dict[str, str] = {}
    targets: dict[str, str] = {}
    for discard_handle, target_val in changes:
        if not target_val:
            continue
        if target_val.startswith("GOLDEN:"):
            golden_name = target_val[7:]
            keeper_handle = golden_cache.get(golden_name)
            if keeper_handle is None:
                keeper_handle, created = _find_or_create_golden(
                    db, golden_name, repair_engine, trans
                )
                if keeper_handle is None:
                    result["errors"].append(
                        str(_("Could not create golden repository '%s'.")) % golden_name
                    )
                    continue
                golden_cache[golden_name] = keeper_handle
                if created:
                    result["created"] += 1
        else:
            keeper_handle = target_val
        if keeper_handle != discard_handle:
            targets[discard_handle] = keeper_handle

    keepers: list[str] = []
    for discard_handle in targets:
        keeper_handle = _resolve_chain(discard_handle, targets)
        if keeper_handle == discard_handle:
            continue
        try:
            if repair_engine.merge_repositories(
                db, keeper_handle, discard_handle, trans
            ):
                result["merged"] += 1
                if keeper_handle not in keepers:
                    keepers.append(keeper_handle)
            else:
                result["errors"].append(
                    str(_("Failed to merge %s into %s."))
                    % (discard_handle, keeper_handle)
                )
        except Exception as err:  # pylint: disable=broad-except
            LOG.exception("Merge failed for %s -> %s", discard_handle, keeper_handle)
            result["errors"].append(str(err))

    for handle in keepers + [h for h in (tidy_handles or []) if h not in keepers]:
        removed, moved = _tidy_keeper_address(db, handle, trans)
        result["removed"] += removed
        result["moved"] += moved

    try:
        repair_engine.apply_gold_standard_details(db, trans)
    except Exception:  # pylint: disable=broad-except
        LOG.exception("Failed to apply gold standard details")
    return result


def auto_consolidate_repositories(
    db: Any, engine: GWizardCitationRepairEngine | None = None
) -> dict[str, Any]:
    """Accept every hint and apply it, as the Repository Consolidate dialog does.

    Also cleans the address of repositories that have an address problem
    but no merge target. Returns the dict from ``apply_repo_consolidations``.
    """
    rows = build_repo_consolidate_rows(db)
    changes = [
        (row["handle"], row["hint_target"]) for row in rows if row["hint_target"]
    ]
    tidy = [
        row["handle"]
        for row in rows
        if not row["hint_target"] and row["problem"] == "address"
    ]
    return apply_repo_consolidations(db, changes, engine, tidy_handles=tidy)


def build_repo_consolidate_rows(db: Any) -> list[dict[str, Any]]:
    """Build per-repository consolidation rows from database."""
    if db is None:
        return []

    repos: list[dict[str, Any]] = []
    golden_names = GoldStandardRepositories.get_names()
    golden_set = set(golden_names)

    existing_golden_handles: dict[str, str] = {}
    handle_list = (
        list(db.iter_repository_handles())
        if hasattr(db, "iter_repository_handles")
        else list(db.get_repository_handles())
    )

    for handle in handle_list:
        repo = db.get_repository_from_handle(handle)
        if repo is None:
            continue
        name = str(repo.get_name() or "").strip()
        gid = str(repo.get_gramps_id() or "")
        sources: list[str] = []
        if hasattr(db, "find_backlink_handles"):
            try:
                for item in db.find_backlink_handles(handle, ["Source"]):
                    s_h = item[1] if isinstance(item, (tuple, list)) else item
                    sources.append(str(s_h))
            except Exception:
                sources = []

        source_titles: list[str] = []
        for s_h in sources[:3]:
            s_obj = db.get_source_from_handle(s_h)
            if s_obj and s_obj.get_title():
                source_titles.append(str(s_obj.get_title()).strip())

        if len(sources) == 0:
            summary = str(_("No sources"))
        elif source_titles:
            sample = ", ".join(source_titles[:2])
            summary = f"{len(sources)} sources: {sample}"
        else:
            summary = f"{len(sources)} sources"

        is_golden = name in golden_set
        if is_golden:
            existing_golden_handles[name] = handle

        addr_issue = False
        for addr in repo.get_address_list():
            act, _det = classify_repo_street(name, addr.get_street())
            if act in ("drop", "move"):
                addr_issue = True
                break

        repos.append(
            {
                "handle": handle,
                "name": name,
                "gramps_id": gid,
                "display": f"{name} ({gid})" if gid else (name or _("(unnamed)")),
                "source_count": len(sources),
                "sources_summary": summary,
                "norm_name": normalize_repo_name(name),
                "is_golden": is_golden,
                "addr_issue": addr_issue,
            }
        )

    # Group duplicate repositories by normalized name or similarity
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in repos:
        if r["norm_name"]:
            groups[r["norm_name"]].append(r)

    merged_groups: list[list[dict[str, Any]]] = []
    handled_handles: set[str] = set()

    for _norm_key, members in groups.items():
        if len(members) >= 2:
            merged_groups.append(members)
            for m in members:
                handled_handles.add(m["handle"])

    remaining = [r for r in repos if r["handle"] not in handled_handles]
    used_in_fuzzy: set[str] = set()
    for i, r1 in enumerate(remaining):
        if r1["handle"] in used_in_fuzzy:
            continue
        cluster = [r1]
        for j in range(i + 1, len(remaining)):
            r2 = remaining[j]
            if r2["handle"] in used_in_fuzzy:
                continue
            k1 = r1["norm_name"]
            k2 = r2["norm_name"]
            if not k1 or not k2:
                continue
            if (
                k1 in k2
                or k2 in k1
                or difflib.SequenceMatcher(None, k1, k2).ratio() >= 0.75
            ):
                cluster.append(r2)
                used_in_fuzzy.add(r2["handle"])
        if len(cluster) >= 2:
            merged_groups.append(cluster)
            used_in_fuzzy.add(r1["handle"])
            for m in cluster:
                handled_handles.add(m["handle"])

    rows: list[dict[str, Any]] = []

    for group in merged_groups:
        group.sort(
            key=lambda r: (
                not r["is_golden"],
                -r["source_count"],
                r["gramps_id"],
            )
        )
        keeper = group[0]
        keeper_disp = keeper["display"]

        for member in group:
            m_handle = member["handle"]
            m_disp = member["display"]
            is_keeper = m_handle == keeper["handle"]

            options = [(m_disp, m_handle)]
            for other in group:
                if other["handle"] != m_handle:
                    options.append((other["display"], other["handle"]))
            for other_repo in repos:
                if other_repo["handle"] != m_handle and other_repo not in group:
                    options.append((other_repo["display"], other_repo["handle"]))
            for g_name in golden_names:
                g_val = existing_golden_handles.get(g_name, f"GOLDEN:{g_name}")
                if g_val != m_handle and all(opt[1] != g_val for opt in options):
                    disp_label = GoldStandardRepositories.get_display_label(g_name)
                    options.append((disp_label, g_val))

            if is_keeper:
                hint_target = ""
                hint_reason = ""
                hint_display = ""
            else:
                hint_target = keeper["handle"]
                if keeper["is_golden"]:
                    hint_reason = str(_("Matches gold standard"))
                elif keeper["source_count"] > member["source_count"]:
                    hint_reason = (
                        str(_("Keeper has %d sources")) % keeper["source_count"]
                    )
                else:
                    hint_reason = str(_("Preferred keeper"))
                hint_display = f"{keeper_disp}\n({hint_reason})"

            rows.append(
                {
                    "handle": m_handle,
                    "name": member["name"],
                    "gramps_id": member["gramps_id"],
                    "display": m_disp,
                    "sources_summary": member["sources_summary"],
                    "options": options,
                    "hint_target": hint_target,
                    "hint_reason": hint_reason,
                    "hint_display": hint_display,
                    "is_keeper": is_keeper,
                    "problem": "duplicate",
                }
            )

    for member in repos:
        if member["handle"] in handled_handles:
            continue
        m_handle = member["handle"]
        m_name = member["name"]
        m_disp = member["display"]

        hint_target = ""
        hint_reason = ""
        hint_display = ""

        if not member["is_golden"]:
            ranked = rank_golden_repo_matches(m_name, golden_names, limit=1)
            best_golden = ranked[0] if ranked else None
            if best_golden:
                norm_m = member["norm_name"]
                norm_g = normalize_repo_name(best_golden)
                ratio = difflib.SequenceMatcher(None, norm_m, norm_g).ratio()
                if norm_m in norm_g or norm_g in norm_m or ratio >= 0.6:
                    if best_golden in existing_golden_handles:
                        target_h = existing_golden_handles[best_golden]
                        if target_h != m_handle:
                            hint_target = target_h
                            hint_reason = str(_("Merge into existing %s")) % best_golden
                            target_disp = next(
                                (
                                    r["display"]
                                    for r in repos
                                    if r["handle"] == target_h
                                ),
                                best_golden,
                            )
                            hint_display = f"{target_disp}\n({hint_reason})"
                    else:
                        hint_target = f"GOLDEN:{best_golden}"
                        hint_reason = str(_("Gold-standard match"))
                        hint_display = f"{best_golden}\n({hint_reason})"

        if hint_target or member["addr_issue"]:
            options = [(m_disp, m_handle)]
            for other_repo in repos:
                if other_repo["handle"] != m_handle:
                    options.append((other_repo["display"], other_repo["handle"]))
            for g_name in golden_names:
                g_val = existing_golden_handles.get(g_name, f"GOLDEN:{g_name}")
                if g_val != m_handle and all(opt[1] != g_val for opt in options):
                    disp_label = GoldStandardRepositories.get_display_label(g_name)
                    options.append((disp_label, g_val))

            rows.append(
                {
                    "handle": m_handle,
                    "name": m_name,
                    "gramps_id": member["gramps_id"],
                    "display": m_disp,
                    "sources_summary": member["sources_summary"],
                    "options": options,
                    "hint_target": hint_target,
                    "hint_reason": hint_reason,
                    "hint_display": hint_display,
                    "is_keeper": False,
                    "problem": "golden_match" if hint_target else "address",
                }
            )

    rows.sort(key=lambda r: (not bool(r["hint_target"]), r["name"].lower()))
    return rows


# ------------------------------------------------------------
#
# RepoConsolidateDialog
#
# ------------------------------------------------------------
class RepoConsolidateDialog(Gtk.Dialog):
    """Review and consolidate repository records in a grid dialog."""

    def __init__(
        self,
        dbstate: Any,
        title: str | None = None,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        """Build the repository consolidate dialog."""
        dlg_title = title if title is not None else str(_("Repository Consolidate"))
        super().__init__(
            title=dlg_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.engine = GWizardCitationRepairEngine()
        self.combos: list[tuple[str, Gtk.ComboBox, str]] = []
        self.row_combos: list[tuple[dict[str, Any], Gtk.ComboBox]] = []
        self.set_default_size(1480, 520)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        rows = build_repo_consolidate_rows(self.dbstate.db)
        n_repos = len(rows)

        count_label = Gtk.Label()
        count_label.set_markup(
            "<b>%s</b>" % str(_("Problem repositories (%d total)") % n_repos)
        )
        count_label.set_halign(Gtk.Align.START)
        count_label.set_hexpand(True)
        content.add(count_label)

        info = Gtk.Label(
            label=(
                description
                if description is not None
                else _(
                    "Merge duplicate repositories into a single repository, "
                    "standardize repository names against gold standards, and "
                    "tidy address details."
                )
            ),
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not rows:
            done = Gtk.Label(
                label=str(_("No repository consolidation problems found."))
            )
            done.set_halign(Gtk.Align.START)
            content.add(done)
            self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
            return

        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(0)
        header_grid.set_row_spacing(0)
        header_grid.set_column_homogeneous(True)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)
        header_grid.get_style_context().add_class("merge-grid")

        repo_head = Gtk.Label()
        repo_head.set_markup("<b>%s</b>" % str(_("Repository")))
        repo_head.set_halign(Gtk.Align.START)
        repo_head.set_hexpand(True)

        source_head = Gtk.Label()
        source_head.set_markup("<b>%s</b>" % str(_("Sources")))
        source_head.set_halign(Gtk.Align.START)
        source_head.set_hexpand(True)

        mid_head = Gtk.Label()
        mid_head.set_markup("<b>%s</b>" % str(_("Consolidate into (target)")))
        mid_head.set_halign(Gtk.Align.START)
        mid_head.set_hexpand(True)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        for head in (repo_head, source_head, mid_head, hint_head):
            head.get_style_context().add_class("merge-cell")
        header_grid.attach(repo_head, 0, 0, 1, 1)
        header_grid.attach(source_head, 1, 0, 1, 1)
        header_grid.attach(mid_head, 2, 0, 1, 1)
        header_grid.attach(hint_head, 3, 0, 1, 1)
        content.add(header_grid)

        content.pack_start(self.build_rows(rows), True, True, 0)

        hint = Gtk.Label(
            label=str(
                _(
                    "Merging combines duplicate repositories into one and updates "
                    "all referencing sources; gold-standard targets add official "
                    "repository type and web address."
                )
            )
        )
        hint.set_line_wrap(True)
        hint.set_halign(Gtk.Align.START)
        content.add(hint)

        n_hints = sum(1 for row, _combo in self.row_combos if row.get("hint_target"))
        self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(len(rows) > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

    def _install_grid_css(self) -> None:
        """Install CSS that draws borders around every grid cell."""
        if getattr(self, "_grid_css_installed", False):
            return
        css = b"""
        .merge-grid {
            border: 1px solid #555555;
            margin: 0;
        }
        .merge-cell {
            border: none;
            margin: 0;
            padding: 2px;
        }
        """
        screen = Gdk.Screen.get_default()
        if screen is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._grid_css_installed = True

    def _make_combo(self, row: dict[str, Any]) -> Gtk.ComboBox:
        """Create a target dropdown for a repository row."""
        store = Gtk.ListStore(str, str)
        for opt_label, opt_val in row.get("options", []):
            store.append([opt_label, opt_val])

        combo = Gtk.ComboBox.new_with_model(store)
        combo.set_hexpand(False)
        combo.set_size_request(240, -1)
        renderer = Gtk.CellRendererText()
        renderer.set_property("wrap-mode", 2)
        renderer.set_property("width-chars", 40)
        renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        combo.pack_start(renderer, True)
        combo.add_attribute(renderer, "text", 0)
        combo.set_active(0)
        combo._user_target = row["handle"]
        combo.connect("changed", self._on_combo_changed)
        return combo

    def _on_combo_changed(self, combo: Gtk.ComboBox) -> None:
        """Record the user's current selection on the combo object itself."""
        iter_ = combo.get_active_iter()
        if iter_ is not None:
            model = combo.get_model()
            combo._user_target = str(model.get_value(iter_, 1) or "")
        else:
            combo._user_target = ""

    def build_rows(self, rows: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build the data grid inside a scrolled window."""
        self._install_grid_css()
        grid = Gtk.Grid()
        grid.set_column_spacing(0)
        grid.set_row_spacing(0)
        grid.set_column_homogeneous(True)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        grid.get_style_context().add_class("merge-grid")

        row_index = 0
        for row in rows:
            repo_label = Gtk.Label(label=row["display"])
            repo_label.set_halign(Gtk.Align.START)
            repo_label.set_line_wrap(True)
            repo_label.set_max_width_chars(35)
            repo_label.get_style_context().add_class("merge-cell")
            grid.attach(repo_label, 0, row_index, 1, 1)

            src_label = Gtk.Label(label=row.get("sources_summary", ""))
            src_label.set_halign(Gtk.Align.START)
            src_label.set_line_wrap(True)
            src_label.set_max_width_chars(50)
            src_label.get_style_context().add_class("merge-cell")
            grid.attach(src_label, 1, row_index, 1, 1)

            combo = self._make_combo(row)
            combo.get_style_context().add_class("merge-cell")
            grid.attach(combo, 2, row_index, 1, 1)

            hint_text = row.get("hint_display", "")
            hint_label = Gtk.Label(label=hint_text)
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_line_wrap(True)
            hint_label.set_max_width_chars(40)
            hint_label.get_style_context().add_class("merge-cell")
            grid.attach(hint_label, 3, row_index, 1, 1)

            self.combos.append((row["handle"], combo, str(row.get("hint_target", ""))))
            self.row_combos.append((row, combo))
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(330)
        scrolled.set_min_content_width(1330)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def get_choice(self, combo: Gtk.ComboBox, fallback: str) -> str:
        """Return the target handle/value behind a dropdown row."""
        user_target = getattr(combo, "_user_target", None)
        if user_target:
            return user_target
        active = combo.get_active()
        if active < 0:
            return fallback
        model = combo.get_model()
        return str(model[active][1] or fallback)

    def get_choices(self) -> dict[str, str]:
        """Return mapping of repository handle to chosen target value."""
        return {
            row["handle"]: self.get_choice(combo, row["handle"])
            for row, combo in self.row_combos
        }

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        """Set each unchanged drop-down to its hint target."""
        accepted = 0
        for row, combo in self.row_combos:
            target = row.get("hint_target")
            if not target:
                continue
            original = row["handle"]
            if self.get_choice(combo, original) != original:
                continue
            for index, model_row in enumerate(combo.get_model()):
                if str(model_row[1]) == target:
                    combo.set_active(index)
                    combo._user_target = target
                    accepted += 1
                    break
        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Set %d drop-downs to the suggested repository. Review "
                    "them, change any that look wrong, then press Apply."
                )
            )
            % accepted,
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply chosen repository consolidations."""
        changes: list[tuple[str, str]] = []
        for row, combo in self.row_combos:
            chosen = self.get_choice(combo, row["handle"])
            if chosen and chosen != row["handle"]:
                changes.append((row["handle"], chosen))

        if not changes:
            OkDialog(
                str(_("Nothing to consolidate")),
                str(
                    _(
                        "Every drop-down is still on its first entry. Pick a "
                        "target in one or more rows, then press Apply."
                    )
                ),
                parent=self,
            )
            return

        result = apply_repo_consolidations(self.dbstate.db, changes, self.engine)
        self._show_result(result, str(_("Repositories Consolidated")))

    def _show_result(self, result: dict[str, Any], ok_title: str) -> None:
        """Summarize an ``apply_repo_consolidations`` result."""
        summary_parts = []
        if result["merged"] > 0:
            summary_parts.append(
                str(_("Consolidated %d repositories.")) % result["merged"]
            )
        if result["created"] > 0:
            summary_parts.append(
                str(_("Created %d gold-standard repositories.")) % result["created"]
            )
        if result["removed"] > 0:
            summary_parts.append(
                str(_("Removed %d redundant address lines.")) % result["removed"]
            )
        if result["moved"] > 0:
            summary_parts.append(
                str(_("Moved %d place details into notes.")) % result["moved"]
            )
        msg = (
            " ".join(summary_parts)
            if summary_parts
            else str(_("Consolidation complete."))
        )
        if result["errors"]:
            ErrorDialog(
                str(_("Consolidate warnings")),
                msg + "\n\n" + "\n".join(result["errors"]),
                parent=self,
            )
        else:
            OkDialog(ok_title, msg, parent=self)

    def run_auto(self, parent: Gtk.Window | None = None) -> None:
        """Accept all hints and apply them (same code as Accept all hints)."""
        owner = parent or self.get_transient_for()
        result = auto_consolidate_repositories(self.dbstate.db, self.engine)
        message = str(_("Consolidated %d repositories.")) % result["merged"]
        if result["errors"]:
            ErrorDialog(
                str(_("Auto fix: repositories")),
                message + "\n\n" + "\n".join(result["errors"]),
                parent=owner,
            )
            return
        OkDialog(str(_("Auto fix: repositories")), message, parent=owner)

    def show_dialog(self) -> None:
        """Show and run the modal dialog until user explicitly closes it."""
        self.show_all()
        while True:
            resp = self.run()
            if resp in (
                Gtk.ResponseType.CLOSE,
                Gtk.ResponseType.CANCEL,
                Gtk.ResponseType.DELETE_EVENT,
            ):
                break
        self.destroy()
