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

"""Step 1 dialog: review and unpack conflated source titles into repositories and source titles."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
from typing import Any

# -------------------------------------------------------------------------
#
# GTK modules
#
# -------------------------------------------------------------------------
from gi.repository import Gtk, Pango

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.dialog import ErrorDialog, OkDialog
from gramps.gen.db import DbTxn
from gramps.gen.lib import RepoRef
from gramps.plugins.tool.gwizardcitationrepairengine import (
    GWizardCitationRepairEngine,
)
from gramps.plugins.tool.gwizardcitationshared import normalize_repo_name

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)


def _unpacked_abbreviation(
    current_abbrev: str, old_title: str, new_title: str, repo_name: str
) -> str | None:
    """Return a replacement abbreviation after a source title was unpacked.

    The abbreviation usually starts out as a copy of the conflated title
    (e.g. "Newspapers.com Obituary Index"), so it keeps the repository text
    that was just moved out. Return the new abbreviation, or None when the
    existing value should be left alone (a deliberate custom abbreviation).
    """
    abbrev = (current_abbrev or "").strip()
    old = (old_title or "").strip()
    new = (new_title or "").strip()
    repo = (repo_name or "").strip()
    if not new:
        return None
    if not abbrev:
        return None
    if abbrev.casefold() == old.casefold():
        return new if abbrev != new else None
    if repo and abbrev.casefold().startswith(repo.casefold()):
        rest = abbrev[len(repo) :].lstrip(" -:;,")
        if rest and rest != abbrev:
            return rest
    return None


# ------------------------------------------------------------
#
# UnpackSourcesDialog
#
# ------------------------------------------------------------
class UnpackSourcesDialog(Gtk.Dialog):
    """Review and unpack conflated sources into repositories, source titles, and publication info."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        description: str | None = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Unpack Conflated Source"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.engine = GWizardCitationRepairEngine()
        raw_plan = self.engine.plan_unpack_conflated_sources(dbstate.db)
        self.plan: list[dict[str, Any]] = []
        for item in raw_plan:
            hint_parts = []
            repo_name = item.get("repo_name", "")
            if repo_name:
                hint_parts.append(_("Extract repository '%s'") % repo_name)
            new_title = item.get("new_title", "")
            if new_title:
                hint_parts.append(_("Source title to '%s'") % new_title)
                hint_parts.append(_("Abbreviation updated to match, if it copied the old title"))
            moved = item.get("moved_text", "")
            if moved:
                hint_parts.append(
                    _("Move citation detail '%s' to publication info") % moved
                )
            item["hint_text"] = "\n".join(hint_parts)
            self.plan.append(item)

        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1060, 520)

        # Action buttons in dialog action area (always visible at bottom)
        n_hints = len(self.plan)
        self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(n_hints > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)
        info = Gtk.Label(
            label=description
            or str(
                _(
                    "Review conflated sources that combine repository, source, and citation data into a single title. "
                    "Press 'Accept hints' to populate the target columns, edit any values as needed, then press 'Apply'."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not self.plan:
            done = Gtk.Label(label=str(_("No conflated source titles found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(_("Total conflated sources found: %d") % len(self.plan))
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        # Header row above the scrolled grid
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(6)
        header_grid.set_row_spacing(0)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        src_head = Gtk.Label()
        src_head.set_markup("<b>%s</b>" % str(_("Source")))
        src_head.set_halign(Gtk.Align.START)
        src_head.set_hexpand(False)

        repo_head = Gtk.Label()
        repo_head.set_markup("<b>%s</b>" % str(_("Repository")))
        repo_head.set_halign(Gtk.Align.START)
        repo_head.set_hexpand(False)

        title_head = Gtk.Label()
        title_head.set_markup("<b>%s</b>" % str(_("Source Title")))
        title_head.set_halign(Gtk.Align.START)
        title_head.set_hexpand(False)

        pub_head = Gtk.Label()
        pub_head.set_markup("<b>%s</b>" % str(_("Publication Info")))
        pub_head.set_halign(Gtk.Align.START)
        pub_head.set_hexpand(False)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(src_head, 0, 0, 1, 1)
        header_grid.attach(repo_head, 1, 0, 1, 1)
        header_grid.attach(title_head, 2, 0, 1, 1)
        header_grid.attach(pub_head, 3, 0, 1, 1)
        header_grid.attach(hint_head, 4, 0, 1, 1)
        content.add(header_grid)

        # SizeGroups to ensure each header matches the data column width
        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(5)
        ]
        self.column_sizegroups[0].add_widget(src_head)
        self.column_sizegroups[1].add_widget(repo_head)
        self.column_sizegroups[2].add_widget(title_head)
        self.column_sizegroups[3].add_widget(pub_head)
        self.column_sizegroups[4].add_widget(hint_head)

        content.pack_start(self.build_rows(self.plan), True, True, 0)

        hint_footer = Gtk.Label(
            label=str(
                _(
                    "Citation-style text (page, volume, memorial ID...) taken out "
                    "of a title is preserved in the source's publication information."
                )
            )
        )
        hint_footer.set_line_wrap(True)
        hint_footer.set_halign(Gtk.Align.START)
        # Widen the hint footer so the explanatory text has roughly twice the
        # vertical room it previously had.
        hint_footer.set_size_request(-1, 45)
        content.pack_start(hint_footer, False, False, 0)

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        """Build the data grid for reviewing and editing unpacked sources."""
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            # Column 0: Source name & ID
            display_title = "%s (%s)" % (
                entry.get("old_title", ""),
                entry.get("gramps_id", ""),
            )
            src_label = Gtk.Label(label=display_title)
            src_label.set_halign(Gtk.Align.START)
            src_label.set_xalign(0.0)
            src_label.set_line_wrap(True)
            src_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            src_label.set_size_request(240, -1)
            src_label.set_max_width_chars(32)
            grid.attach(src_label, 0, row_index, 1, 1)

            # Column 1: Target Repository entry (empty by default)
            repo_entry = Gtk.Entry()
            repo_entry.set_width_chars(18)
            repo_entry.set_text("")
            grid.attach(repo_entry, 1, row_index, 1, 1)

            # Column 2: Target Source Title entry (empty by default)
            title_entry = Gtk.Entry()
            # Source titles can be long enough that horizontal scrolling is
            # undesirable, so give the field extra room (was 24 chars).
            title_entry.set_width_chars(48)
            title_entry.set_text("")
            grid.attach(title_entry, 2, row_index, 1, 1)

            # Column 3: Target Publication Info entry (empty by default)
            moved_entry = Gtk.Entry()
            moved_entry.set_width_chars(18)
            moved_entry.set_text("")
            grid.attach(moved_entry, 3, row_index, 1, 1)

            # Column 4: Hint label
            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(220, -1)
            hint_label.set_max_width_chars(30)
            grid.attach(hint_label, 4, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(src_label)
                self.column_sizegroups[1].add_widget(repo_entry)
                self.column_sizegroups[2].add_widget(title_entry)
                self.column_sizegroups[3].add_widget(moved_entry)
                self.column_sizegroups[4].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "repo_entry": repo_entry,
                    "title_entry": title_entry,
                    "moved_entry": moved_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(300)
        # Keep the scrollable area at the new, narrower content width so the
        # dialog does not leave dead space on the right.
        scrolled.set_min_content_width(950)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def build_buttons(self) -> Gtk.Box:
        """Return the action button row with Accept hints and Apply."""
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_homogeneous(True)
        n_hints = len(self.row_targets)
        accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        accept_button.set_sensitive(n_hints > 0)
        apply_button = Gtk.Button(label=str(_("Apply")))
        accept_button.connect("clicked", self.cb_accept_hints)
        apply_button.connect("clicked", self.cb_apply)
        buttons.pack_start(accept_button, True, True, 0)
        buttons.pack_start(apply_button, True, True, 0)
        return buttons

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        """Populate suggested values into target columns."""
        populated_count = 0
        for target in self.row_targets:
            item = target["entry"]
            repo_name = item.get("repo_name", "")
            new_title = item.get("new_title", "")
            moved_text = item.get("moved_text", "")

            changed = False
            if repo_name and not target["repo_entry"].get_text():
                target["repo_entry"].set_text(repo_name)
                changed = True
            if new_title and not target["title_entry"].get_text():
                target["title_entry"].set_text(new_title)
                changed = True
            if moved_text and not target["moved_entry"].get_text():
                target["moved_entry"].set_text(moved_text)
                changed = True

            if changed:
                populated_count += 1

        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Populated suggested data into target columns for %d sources. "
                    "Review or edit them, then press Apply."
                )
            )
            % populated_count,
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        """Apply target column data directly into source and repository records."""
        repo_map: dict[str, str] = {}
        for repo in self.dbstate.db.iter_repositories():
            key = normalize_repo_name(str(repo.get_name() or ""))
            if key:
                repo_map.setdefault(key, repo.get_handle())

        applied_count = 0
        abbrev_count = 0
        with DbTxn(_("Unpack Conflated Source"), self.dbstate.db) as trans:
            for target in self.row_targets:
                item = target["entry"]
                repo_name = target["repo_entry"].get_text().strip()
                new_title = target["title_entry"].get_text().strip()
                moved_text = target["moved_entry"].get_text().strip()

                if not repo_name and not new_title and not moved_text:
                    continue

                handle = item.get("handle")
                try:
                    source = self.dbstate.db.get_source_from_handle(handle)
                except Exception:
                    source = None
                if source is None:
                    continue

                # 1. Repository
                if repo_name:
                    key = normalize_repo_name(repo_name)
                    repo_handle = repo_map.get(key)
                    if not repo_handle:
                        repo_handle = self.engine._create_repository(
                            self.dbstate.db, repo_name, trans
                        )
                        repo_map[key] = repo_handle
                    linked = any(
                        ref.get_reference_handle() == repo_handle
                        for ref in source.get_reporef_list()
                    )
                    if not linked:
                        repo_ref = RepoRef()
                        repo_ref.set_reference_handle(repo_handle)
                        source.add_repo_reference(repo_ref)

                # 2. Source Title (and the abbreviation that copied it)
                if new_title:
                    old_title = str(source.get_title() or "")
                    new_abbrev = _unpacked_abbreviation(
                        str(source.get_abbreviation() or ""),
                        old_title,
                        new_title,
                        repo_name,
                    )
                    source.set_title(new_title)
                    if new_abbrev is not None:
                        source.set_abbreviation(new_abbrev)
                        abbrev_count += 1

                # 3. Moved publication info
                if moved_text:
                    pubinfo = str(source.get_publication_info() or "").strip()
                    source.set_publication_info(
                        "%s; %s" % (pubinfo, moved_text) if pubinfo else moved_text
                    )

                self.dbstate.db.commit_source(source, trans)
                applied_count += 1

        if applied_count == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(
                    _(
                        "No target values entered. Press 'Accept hints' or type "
                        "values into the target columns first."
                    )
                ),
                parent=self,
            )
            return

        OkDialog(
            str(_("Field Unpacking Complete")),
            str(_("Unpacked %d conflated sources (%d abbreviations updated)."))
            % (applied_count, abbrev_count),
            parent=self,
        )

    def show_dialog(self) -> None:
        """Display the modal dialog until user explicitly closes it."""
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
