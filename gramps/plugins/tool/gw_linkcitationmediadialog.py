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
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
try:
    from gi.repository import Gtk, Pango
except (ImportError, AttributeError):
    from unittest.mock import MagicMock

    class _FakeDialog:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    Gtk = MagicMock()  # type: ignore[assignment]
    Gtk.Dialog = _FakeDialog  # type: ignore[assignment]
    Pango = MagicMock()  # type: ignore[assignment]

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.db import DbTxn
from gramps.gen.utils.file import media_path_full
from gramps.gen.utils.thumbnails import get_thumbnail_image
from gramps.gui.dialog import OkDialog
from gramps.plugins.tool.gwizard_common import reports_apply_errors
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
# Data builder
#
# -------------------------------------------------------------------------
def build_link_citation_media_rows(
    db: Any, stats: dict[str, int] | None = None
) -> list[dict[str, Any]]:
    """Scan the database and build candidate rows for media-to-citation linking.

    Only locked media is offered. The lock is set in Media Fix once a file
    has been checked, so media is fixed before it is linked to a citation,
    and a user can lock media over several sessions and run this step again.
    A candidate whose citation already has the media is left out.

    :param db: The database.
    :param stats: Optional dict that receives ``unlocked_media``, the number
        of different media files left out because they are not locked yet.
    :returns: The candidate rows, safe matches first.
    """
    if stats is not None:
        stats["unlocked_media"] = 0
    if not db:
        return []

    candidates: list[dict[str, Any]] = []
    candidates.extend(find_promotable_gallery_media(db))
    candidates.extend(find_unpackable_source_media(db))
    candidates.extend(find_orphan_media_matches(db))

    unlocked: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item in candidates:
        m_id = item["media_identity"]
        c_id = item["citation_identity"]
        compat = item["compatibility"]
        action = item["action"]
        if not m_id.is_locked:
            unlocked.add(str(item["media_handle"]))
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
                "is_locked": m_id.is_locked,
            }
        )

    if stats is not None:
        stats["unlocked_media"] = len(unlocked)
    # Sort: safe first, then review, then conflict
    order = {"safe": 0, "ambiguous": 1, "conflict": 2}
    rows.sort(key=lambda r: (order.get(r["status"], 3), -r["score"]))
    return rows


def unlocked_media_message(count: int) -> str:
    """Return the note shown when media was left out because it is unlocked.

    :param count: Number of media files that are not locked yet.
    :returns: The message, or an empty string when ``count`` is 0.
    """
    if not count:
        return ""
    return ngettext(
        "{number_of} media file was left out because it is not locked yet. "
        "Check it in Media Fix and lock it, then run this step again.",
        "{number_of} media files were left out because they are not locked "
        "yet. Check them in Media Fix and lock them, then run this step again.",
        count,
    ).format(number_of=count)


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


def auto_link_citation_media(db: Any, stats: dict[str, int] | None = None) -> int:
    """Headless auto-linker for 'Accept all hints'.

    Applies only safe (🟢) candidates with zero conflicts in one transaction.
    Only locked media is used; see :func:`build_link_citation_media_rows`
    for ``stats``.
    """
    if not db:
        if stats is not None:
            stats["unlocked_media"] = 0
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
        self.stats: dict[str, int] = {"unlocked_media": 0}
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

        unlocked_text = unlocked_media_message(self.stats["unlocked_media"])
        if unlocked_text:
            unlocked_label = Gtk.Label(label=unlocked_text)
            unlocked_label.set_line_wrap(True)
            unlocked_label.set_halign(Gtk.Align.START)
            content.pack_start(unlocked_label, False, False, 0)

        if not self.rows:
            done = Gtk.Label(
                label=str(
                    _(
                        "No candidate media links found. All citations and media attachments are well-aligned."
                    )
                )
            )
            done.set_halign(Gtk.Align.START)
            content.add(done)
            self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
            return

        stat_label = Gtk.Label(
            label=str(
                _(
                    "Found %d candidate media links: %d Safe 🟢, %d Review 🟡, %d Conflict 🔴"
                )
            )
            % (len(self.rows), n_safe, n_review, n_conf)
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
        self.accept_button = Gtk.Button(label=str(_("Accept safe hints (%d)")) % n_safe)
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
        box.set_min_content_width(380)
        box.set_border_width(6)

        title = Gtk.Label()
        title.set_markup("<b>" + str(_("Link Inspector")) + "</b>")
        title.set_halign(Gtk.Align.START)
        box.pack_start(title, False, False, 0)

        # Thumbnail image display
        self.preview_image = Gtk.Image()
        self.preview_image.set_min_content_height(140)
        self.preview_image.set_min_content_width(200)
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

        # Score markup
        score_color = (
            "#2E8B57"
            if compat.status == "safe"
            else ("#B8860B" if compat.status == "ambiguous" else "#B22222")
        )
        self.preview_score.set_markup(
            f"<b>Compatibility Score:</b> <span foreground='{score_color}'><b>{compat.score}/100 ({row['status_display']})</b></span>"
        )

        lines = []
        lines.append(f"<b>Candidate Media:</b> {m_id.filename}")
        lines.append(f"• Path: {m_id.path}")
        lines.append(
            f"• Detected Category: {m_id.category.title() if m_id.category else '(none)'}"
        )
        lines.append(f"• Year: {m_id.year or '(none)'}")
        if m_id.sheet_page:
            lines.append(f"• Sheet/Page: {m_id.sheet_page}")
        if m_id.surname:
            lines.append(f"• Surname: {m_id.surname.title()} {m_id.given.title()}")

        lines.append("")
        lines.append("<b>Target Citation:</b>")
        lines.append(f"• Source: {c_id.source_title or '(no title)'}")
        lines.append(f"• Volume/Page: {c_id.page or '(none)'}")
        lines.append(f"• Citation Year: {c_id.year or '(none)'}")
        if c_id.surnames:
            lines.append(
                f"• Associated Surnames: {', '.join(s.title() for s in c_id.surnames)}"
            )

        if compat.reasons:
            lines.append("")
            lines.append("<b>Matching Factors:</b>")
            for r in compat.reasons:
                lines.append(f"  ✓ {r}")

        if compat.conflicts:
            lines.append("")
            lines.append("<span foreground='#B22222'><b>Conflict Warnings:</b></span>")
            for conf in compat.conflicts:
                lines.append(f"  <span foreground='#B22222'>⚠ {conf}</span>")

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
        msg_parts = [str(_("Linked %d media object(s) to citations.")) % linked]
        if detached:
            msg_parts.append(
                str(_("Detached %d document scan(s) from owners.")) % detached
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
