#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026       Kevin White <gocaveman@gmail.com>
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

"""Dialog for reviewing, auditing, and linking media to citations in Gramps."""

from __future__ import annotations

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import logging
import os
import re
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
from gramps.gen.db import DbReadBase, DbTxn, DbWriteBase
from gramps.gen.utils.file import media_path_full
from gramps.gen.utils.thumbnails import get_thumbnail_image
from gramps.gui.dialog import OkDialog
from gramps.plugins.tool.gwizard_common import (
    clean_path,
    escape_markup,
    full_media_path,
    is_absolute_path,
    path_key,
    reports_apply_errors,
)
from gramps.plugins.tool.gwizardcitationmediaengine import (
    apply_link_media_to_citation,
    apply_promote_media_to_citation,
    apply_unpack_source_media,
    find_orphan_media_matches,
    find_promotable_gallery_media,
    find_unpackable_source_media,
)

_ = glocale.translation.sgettext
ngettext = glocale.translation.ngettext
LOG = logging.getLogger(__name__)


# -------------------------------------------------------------------------
#
# Media Fix rules check
#
# -------------------------------------------------------------------------
def _file_unreadable(path: str) -> bool:
    """Return True if the file, or a folder above it, cannot be read.

    Uses Media Fix's own permission check when it can be imported.
    """
    try:
        from gramps.plugins.tool.gwizardmediafix import check_path_permission
    except Exception:  # Media Fix not importable: fall back to os.access
        return os.path.exists(path) and not os.access(path, os.R_OK)
    denied, _where = check_path_permission(path)
    return denied


def build_media_path_index(db: DbReadBase) -> dict[str, list[str]]:
    """Map each media file on disk to the Gramps IDs of the records using it.

    :param db: The database.
    :returns: ``path_key(full path) -> [media Gramps IDs]``.
    """
    index: dict[str, list[str]] = {}
    for media in db.iter_media():
        raw = clean_path(str(media.get_path() or ""))
        if raw:
            key = path_key(full_media_path(db, raw))
            index.setdefault(key, []).append(str(media.get_gramps_id() or ""))
    return index


def media_fix_problems(
    db: DbReadBase, media: Any, path_index: dict[str, list[str]] | None = None
) -> list[str]:
    """Return the Media Fix rules a media record does not follow yet.

    The rules are the ones Media Fix's steps enforce: a base media path is
    set, the stored path is relative and inside it (Consolidate media
    location), the file can be found and read (Find missing media), and no
    other media record points at the same file (Fix media references).
    The filename template is not a rule, because Media Fix lets the user keep
    the original names.

    :param db: The database.
    :param media: The media record.
    :param path_index: Result of :func:`build_media_path_index` (built on
        demand when omitted).
    :returns: One short description per broken rule; empty when it passes.
    """
    problems: list[str] = []
    try:
        base_set = bool((db.get_mediapath() or "").strip())
    except Exception:
        base_set = False
    if not base_set:
        problems.append(str(_("no base media path is set")))

    raw = clean_path(str(media.get_path() or ""))
    if not raw:
        problems.append(str(_("no file path")))
        return problems
    if is_absolute_path(raw):
        problems.append(str(_("absolute path (run 'Consolidate media location')")))
    elif ".." in re.split(r"[\\/]+", raw):
        problems.append(
            str(_("outside the base media path (run 'Consolidate media " "location')"))
        )

    full = full_media_path(db, raw)
    if not os.path.exists(full):
        if _file_unreadable(full):
            problems.append(str(_("file cannot be read (permission denied)")))
        else:
            problems.append(str(_("file not found (run 'Find missing media')")))
    elif _file_unreadable(full):
        problems.append(str(_("file cannot be read (permission denied)")))

    if path_index is None:
        path_index = build_media_path_index(db)
    gid = str(media.get_gramps_id() or "")
    others = [g for g in path_index.get(path_key(full), []) if g != gid]
    if others:
        problems.append(
            str(_("same file as {media_ids} (run 'Fix media references')")).format(
                media_ids=", ".join(others)
            )
        )
    return problems


# -------------------------------------------------------------------------
#
# Data builder
#
# -------------------------------------------------------------------------
def build_link_citation_media_rows(
    db: DbReadBase, stats: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Scan the database and build candidate rows for media-to-citation linking.

    Media is only offered once it follows the Media Fix rules (see
    :func:`media_fix_problems`), so media is fixed before it is linked to a
    citation.  Media that would have been offered but breaks a rule is
    reported instead, with the rules it breaks.  A candidate whose citation
    already has the media is left out.

    :param db: The database.
    :param stats: Optional dict that receives ``media_problems``: one entry
        per media record left out, as a dict with ``gramps_id``, ``desc``,
        ``path`` and ``problems`` (list of strings), sorted by Gramps ID.
    :returns: The candidate rows, safe matches first.
    """
    if stats is not None:
        stats["media_problems"] = []
    if not db:
        return []

    candidates: list[dict[str, Any]] = []
    candidates.extend(find_promotable_gallery_media(db))
    candidates.extend(find_unpackable_source_media(db))
    candidates.extend(find_orphan_media_matches(db))

    path_index = build_media_path_index(db) if candidates else {}
    checked: dict[str, list[str]] = {}
    failed: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for item in candidates:
        m_id = item["media_identity"]
        c_id = item["citation_identity"]
        compat = item["compatibility"]
        action = item["action"]
        m_handle = str(item["media_handle"])
        if m_handle not in checked:
            media_obj = db.get_media_from_handle(m_handle)
            checked[m_handle] = (
                media_fix_problems(db, media_obj, path_index)
                if media_obj is not None
                else [str(_("media record not found"))]
            )
        if checked[m_handle]:
            failed[m_handle] = {
                "gramps_id": m_id.gramps_id,
                "desc": m_id.desc,
                "path": m_id.path,
                "problems": checked[m_handle],
            }
            continue
        if str(item["media_handle"]) in c_id.media_handles:
            continue

        # Action display label
        if action == "promote_from_person":
            action_label = str(_("Promote from Person gallery"))
            default_action = "link"
        elif action == "promote_from_event":
            action_label = str(_("Promote from Event gallery"))
            default_action = "link"
        elif action == "unpack_from_source":
            action_label = str(_("Unpack from Source"))
            default_action = "link"
        elif action == "link_orphan":
            action_label = str(_("Link unreferenced media"))
            default_action = "link"
        else:
            action_label = action
            default_action = "link"

        # If conflict, default action should be skip
        if compat.status == "conflict":
            default_action = "skip"

        # Status icon & text
        if compat.status == "safe":
            status_display = "🟢 " + str(_("Safe"))
        elif compat.status == "ambiguous":
            status_display = "🟡 " + str(_("Review"))
        else:
            status_display = "🔴 " + str(_("Conflict"))

        # Citation display string
        cit_parts = []
        if c_id.source_title:
            cit_parts.append(c_id.source_title)
        if c_id.page:
            cit_parts.append(c_id.page)
        cit_display = " | ".join(cit_parts) if cit_parts else str(_("(empty citation)"))
        if c_id.gramps_id:
            cit_display += f" [{c_id.gramps_id}]"

        # Media display string
        media_display = m_id.filename or os.path.basename(m_id.path) or "Media"
        if m_id.gramps_id:
            media_display += f" [{m_id.gramps_id}]"

        # Full path for thumbnail
        full_path = ""
        try:
            full_path = media_path_full(db, m_id.path)
        except Exception:
            full_path = m_id.path

        # Available options for this item
        options = [
            (str(_("Link to Citation")), "link"),
            (str(_("Skip / Ignore")), "skip"),
        ]
        # Detach is offered when the media hangs off a gallery or source
        if action in (
            "promote_from_person",
            "promote_from_event",
            "unpack_from_source",
        ):
            options.insert(1, (str(_("Link & Detach from Owner")), "link_detach"))

        rows.append(
            {
                "status": compat.status,
                "status_display": status_display,
                "score": compat.score,
                "action": action,
                "action_display": action_label,
                "media_handle": item["media_handle"],
                "citation_handle": item["citation_handle"],
                "owner_handle": item.get("owner_handle", ""),
                "owner_type": item.get("owner_type", ""),
                "owner_display": item.get("owner_display", ""),
                "media_identity": m_id,
                "citation_identity": c_id,
                "compatibility": compat,
                "cit_display": cit_display,
                "media_display": media_display,
                "full_path": full_path,
                "options": options,
                "hint_target": default_action,
                "chosen_action": default_action,
            }
        )

    if stats is not None:
        stats["media_problems"] = sorted(
            failed.values(), key=lambda p: str(p["gramps_id"])
        )
    # Sort: safe first, then review, then conflict
    order = {"safe": 0, "ambiguous": 1, "conflict": 2}
    rows.sort(key=lambda r: (order.get(r["status"], 3), -r["score"]))
    return rows


def media_problems_message(problems: list[dict[str, Any]], limit: int = 10) -> str:
    """Return the note listing media left out because it breaks Media Fix rules.

    :param problems: ``stats["media_problems"]`` from
        :func:`build_link_citation_media_rows`.
    :param limit: Most records to list by name.
    :returns: The message, or an empty string when there are no problems.
    """
    if not problems:
        return ""
    lines = [
        ngettext(
            "{number_of} media file was left out because it does not follow "
            "the Media Fix rules yet. Fix it in Media Fix, then run this step "
            "again:",
            "{number_of} media files were left out because they do not follow "
            "the Media Fix rules yet. Fix them in Media Fix, then run this "
            "step again:",
            len(problems),
        ).format(number_of=len(problems))
    ]
    for prob in problems[:limit]:
        lines.append(
            "  • [{media_id}] {desc}: {problems}".format(
                media_id=prob["gramps_id"],
                desc=prob["desc"] or os.path.basename(prob["path"]),
                problems="; ".join(prob["problems"]),
            )
        )
    if len(problems) > limit:
        lines.append(
            "  " + _("... and {number_of} more").format(number_of=len(problems) - limit)
        )
    return "\n".join(lines)


# -------------------------------------------------------------------------
#
# Mutation applier
#
# -------------------------------------------------------------------------
def apply_citation_media_fixes(
    dbstate: Any, plan: list[dict[str, Any]]
) -> tuple[int, int]:
    """Apply the chosen media linking actions in one database transaction.

    Returns:
        (linked_count, detached_count)
    """
    if not dbstate or not dbstate.db or not plan:
        return 0, 0

    db = dbstate.db
    linked = 0
    detached = 0

    with DbTxn(_("Link Media to Citations"), db) as trans:
        for item in plan:
            chosen = item.get("chosen_action", "skip")
            if chosen == "skip":
                continue

            action = item.get("action", "")
            c_h = item.get("citation_handle", "")
            m_h = item.get("media_handle", "")
            detach = chosen == "link_detach"

            success = False
            if action in ("promote_from_person", "promote_from_event"):
                success = apply_promote_media_to_citation(
                    db,
                    trans,
                    citation_handle=c_h,
                    media_handle=m_h,
                    detach_from_owner=detach,
                    owner_type=item.get("owner_type", ""),
                    owner_handle=item.get("owner_handle", ""),
                )
                if success and detach:
                    detached += 1
            elif action == "unpack_from_source":
                success = apply_unpack_source_media(
                    db,
                    trans,
                    source_handle=item.get("owner_handle", ""),
                    citation_handle=c_h,
                    media_handle=m_h,
                    detach_from_source=detach,
                )
                if success and detach:
                    detached += 1
            elif action == "link_orphan":
                success = apply_link_media_to_citation(db, trans, c_h, m_h)

            if success:
                linked += 1

    return linked, detached


def auto_link_citation_media(
    db: DbWriteBase, stats: dict[str, Any] | None = None
) -> int:
    """Headless auto-linker for 'Accept all hints'.

    Applies only safe (🟢) candidates with zero conflicts in one transaction.
    Only media that follows the Media Fix rules is used; see
    :func:`build_link_citation_media_rows` for ``stats``.
    """
    if not db:
        if stats is not None:
            stats["media_problems"] = []
        return 0

    rows = build_link_citation_media_rows(db, stats)
    safe_plan = [
        r
        for r in rows
        if r.get("status") == "safe"
        and r.get("compatibility")
        and not r["compatibility"].conflicts
    ]
    if not safe_plan:
        return 0

    for r in safe_plan:
        r["chosen_action"] = "link"

    class _FakeDbState:
        def __init__(self, database: Any) -> None:
            self.db = database

    linked, _detached = apply_citation_media_fixes(_FakeDbState(db), safe_plan)
    return linked


# -------------------------------------------------------------------------
#
# Dialog Controller
#
# -------------------------------------------------------------------------
class GWLinkCitationMediaDialog(Gtk.Dialog):
    """Review and link candidate media files to citations."""

    def __init__(
        self,
        title: str = "",
        dbstate: Any = None,
        transient_for: Any = None,
    ) -> None:
        dialog_title = title or str(_("Link Citation Media"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.stats: dict[str, Any] = {"media_problems": []}
        self.rows = (
            build_link_citation_media_rows(dbstate.db, self.stats)
            if dbstate and dbstate.db
            else []
        )
        self.row_combos: list[tuple[dict[str, Any], Gtk.ComboBoxText]] = []
        self.preview_image: Gtk.Image | None = None
        self.preview_text: Gtk.Label | None = None
        self.preview_score: Gtk.Label | None = None

        self.set_default_size(1250, 560)

        # Header summary counts
        n_safe = sum(1 for r in self.rows if r["status"] == "safe")
        n_review = sum(1 for r in self.rows if r["status"] == "ambiguous")
        n_conf = sum(1 for r in self.rows if r["status"] == "conflict")

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(8)

        problems_text = media_problems_message(self.stats["media_problems"])
        if problems_text:
            problems_label = Gtk.Label(label=problems_text)
            problems_label.set_line_wrap(True)
            problems_label.set_selectable(True)
            problems_label.set_halign(Gtk.Align.START)
            content.pack_start(problems_label, False, False, 0)

        if not self.rows:
            if problems_text:
                done_text = _("No other candidate media links found.")
            else:
                done_text = _(
                    "No candidate media links found. All citations and media "
                    "attachments are well-aligned."
                )
            done = Gtk.Label(label=str(done_text))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
            return

        stat_label = Gtk.Label(
            label=ngettext(
                "Found {number_of} candidate media link: {safe} Safe 🟢, {review} "
                "Review 🟡, {conflict} Conflict 🔴",
                "Found {number_of} candidate media links: {safe} Safe 🟢, {review} "
                "Review 🟡, {conflict} Conflict 🔴",
                len(self.rows),
            ).format(
                number_of=len(self.rows), safe=n_safe, review=n_review, conflict=n_conf
            )
        )
        stat_label.set_halign(Gtk.Align.START)
        content.pack_start(stat_label, False, False, 0)

        # Main horizontal split: Table on Left, Inspector on Right
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(820)
        paned.set_hexpand(True)
        paned.set_vexpand(True)
        content.pack_start(paned, True, True, 0)

        # Left pane: Data grid in scrolled window
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_box.set_hexpand(True)
        left_box.set_vexpand(True)

        scrolled_left = self._build_data_grid(self.rows)
        left_box.pack_start(scrolled_left, True, True, 0)
        paned.pack1(left_box, resize=True, shrink=False)

        # Right pane: Inspector preview
        right_box = self._build_inspector_pane()
        paned.pack2(right_box, resize=False, shrink=False)

        # Action area buttons
        self.accept_button = Gtk.Button(
            label=_("Accept safe hints ({number_of})").format(number_of=n_safe)
        )
        self.accept_button.set_sensitive(n_safe > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(len(self.rows) > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        # Show first row in inspector by default
        if self.rows:
            self._update_inspector(self.rows[0])

    def _build_data_grid(self, rows: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build the data table grid for candidate links."""
        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        # Header labels
        headers = [
            str(_("Status")),
            str(_("Citation")),
            str(_("Candidate Media")),
            str(_("Action")),
            str(_("Choice")),
            "",
        ]
        for col_idx, head in enumerate(headers):
            lbl = Gtk.Label()
            lbl.set_markup(f"<b>{head}</b>")
            lbl.set_halign(Gtk.Align.START)
            grid.attach(lbl, col_idx, 0, 1, 1)

        row_index = 1
        for row in rows:
            # Col 0: Status
            status_lbl = Gtk.Label(label=row["status_display"])
            status_lbl.set_halign(Gtk.Align.START)
            grid.attach(status_lbl, 0, row_index, 1, 1)

            # Col 1: Citation
            cit_lbl = Gtk.Label(label=row["cit_display"])
            cit_lbl.set_halign(Gtk.Align.START)
            cit_lbl.set_line_wrap(True)
            cit_lbl.set_max_width_chars(32)
            grid.attach(cit_lbl, 1, row_index, 1, 1)

            # Col 2: Media
            media_lbl = Gtk.Label(label=row["media_display"])
            media_lbl.set_halign(Gtk.Align.START)
            media_lbl.set_line_wrap(True)
            media_lbl.set_max_width_chars(28)
            grid.attach(media_lbl, 2, row_index, 1, 1)

            # Col 3: Proposed Action
            act_lbl = Gtk.Label(label=row["action_display"])
            act_lbl.set_halign(Gtk.Align.START)
            grid.attach(act_lbl, 3, row_index, 1, 1)

            # Col 4: Choice Dropdown
            combo = Gtk.ComboBoxText()
            chosen_key = row.get("chosen_action", "link")
            active_idx = 0
            for opt_idx, (opt_label, opt_val) in enumerate(row["options"]):
                combo.append(opt_val, opt_label)
                if opt_val == chosen_key:
                    active_idx = opt_idx
            combo.set_active(active_idx)
            combo.connect("changed", lambda cb, r=row: self.cb_combo_changed(cb, r))
            grid.attach(combo, 4, row_index, 1, 1)
            self.row_combos.append((row, combo))

            # Col 5: Inspect button
            inspect_btn = Gtk.Button(label=str(_("Inspect")))
            inspect_btn.connect("clicked", lambda _b, r=row: self._update_inspector(r))
            grid.attach(inspect_btn, 5, row_index, 1, 1)

            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(350)
        scrolled.set_min_content_width(780)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def _build_inspector_pane(self) -> Gtk.Box:
        """Build the inspector pane showing thumbnail and compatibility details."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(380, -1)  # Gtk.Box has no set_min_content_width
        box.set_border_width(6)

        title = Gtk.Label()
        title.set_markup("<b>" + str(_("Link Inspector")) + "</b>")
        title.set_halign(Gtk.Align.START)
        box.pack_start(title, False, False, 0)

        # Thumbnail image display
        self.preview_image = Gtk.Image()
        self.preview_image.set_size_request(200, 140)
        box.pack_start(self.preview_image, False, False, 0)

        # Score badge
        self.preview_score = Gtk.Label()
        self.preview_score.set_halign(Gtk.Align.START)
        box.pack_start(self.preview_score, False, False, 0)

        # Scrolled details text
        scrolled_text = Gtk.ScrolledWindow()
        scrolled_text.set_min_content_height(220)
        scrolled_text.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.preview_text = Gtk.Label()
        self.preview_text.set_halign(Gtk.Align.START)
        self.preview_text.set_valign(Gtk.Align.START)
        self.preview_text.set_line_wrap(True)
        self.preview_text.set_max_width_chars(45)
        scrolled_text.add(self.preview_text)
        box.pack_start(scrolled_text, True, True, 0)

        return box

    def _update_inspector(self, row: dict[str, Any]) -> None:
        """Update the inspector panel with the selected row's metadata and thumbnail."""
        if not self.preview_text or not self.preview_score:
            return

        m_id = row["media_identity"]
        c_id = row["citation_identity"]
        compat = row["compatibility"]

        # Load thumbnail
        if (
            self.preview_image
            and hasattr(self.preview_image, "set_from_pixbuf")
            and row.get("full_path")
        ):
            try:
                pixbuf = get_thumbnail_image(row["full_path"])
                if pixbuf:
                    self.preview_image.set_from_pixbuf(pixbuf)
                else:
                    self.preview_image.clear()
            except Exception:
                self.preview_image.clear()

        # Score markup. Every value from the database is escaped, so a "&"
        # or "<" in a file name or source title cannot break the markup.
        score_color = (
            "#2E8B57"
            if compat.status == "safe"
            else ("#B8860B" if compat.status == "ambiguous" else "#B22222")
        )
        self.preview_score.set_markup(
            "<b>{label}</b> <span foreground='{color}'><b>{score}/100 "
            "({status})</b></span>".format(
                label=escape_markup(_("Compatibility score:")),
                color=score_color,
                score=compat.score,
                status=escape_markup(row["status_display"]),
            )
        )

        none = _("(none)")

        def heading(text: str) -> str:
            return "<b>%s</b>" % escape_markup(text)

        def item(label: str, value: Any) -> str:
            return "• %s %s" % (escape_markup(label), escape_markup(value or none))

        lines = [
            "%s %s" % (heading(_("Candidate media:")), escape_markup(m_id.filename)),
            item(_("Path:"), m_id.path),
            item(_("Detected category:"), m_id.category.title()),
            item(_("Year:"), m_id.year),
        ]
        if m_id.sheet_page:
            lines.append(item(_("Sheet/Page:"), m_id.sheet_page))
        if m_id.surname:
            lines.append(
                item(_("Surname:"), f"{m_id.surname.title()} {m_id.given.title()}")
            )

        lines += [
            "",
            heading(_("Target citation:")),
            item(_("Source:"), c_id.source_title or _("(no title)")),
            item(_("Volume/Page:"), c_id.page),
            item(_("Citation year:"), c_id.year),
        ]
        if c_id.surnames:
            lines.append(
                item(
                    _("Associated surnames:"),
                    ", ".join(name.title() for name in c_id.surnames),
                )
            )

        if compat.reasons:
            lines += ["", heading(_("Matching factors:"))]
            lines += ["  ✓ %s" % escape_markup(reason) for reason in compat.reasons]

        if compat.conflicts:
            lines += [
                "",
                "<span foreground='#B22222'>%s</span>"
                % heading(_("Conflict warnings:")),
            ]
            lines += [
                "  <span foreground='#B22222'>⚠ %s</span>" % escape_markup(conflict)
                for conflict in compat.conflicts
            ]

        self.preview_text.set_markup("\n".join(lines))

    def cb_combo_changed(self, combo: Gtk.ComboBoxText, row: dict[str, Any]) -> None:
        """Handle choice selection dropdown changed."""
        val = combo.get_active_id() or "skip"
        row["chosen_action"] = val

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        """Select safe default choices for all rows."""
        for row, combo in self.row_combos:
            if row["status"] == "safe":
                combo.set_active_id("link")
                row["chosen_action"] = "link"

    @reports_apply_errors
    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply chosen actions and close dialog with report."""
        linked, detached = apply_citation_media_fixes(self.dbstate, self.rows)
        msg_parts = [
            ngettext(
                "Linked {number_of} media object to citations.",
                "Linked {number_of} media objects to citations.",
                linked,
            ).format(number_of=linked)
        ]
        if detached:
            msg_parts.append(
                ngettext(
                    "Detached {number_of} document scan from its owner.",
                    "Detached {number_of} document scans from their owners.",
                    detached,
                ).format(number_of=detached)
            )
        OkDialog(
            str(_("Media Linking Complete")),
            "\n".join(msg_parts),
            parent=self,
        )
        self.response(Gtk.ResponseType.OK)
        self.destroy()

    def show_dialog(self) -> None:
        """Show dialog and clean up on completion."""
        self.show_all()
        self.run()
        self.destroy()
