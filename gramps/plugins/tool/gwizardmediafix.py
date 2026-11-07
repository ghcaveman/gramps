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

"""GWizard Media Fix tool: Find missing media, consolidate media locations, and apply filename standards."""

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
from __future__ import annotations
import logging
import os
import re
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
from gramps.gen.config import config
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.dialog import OkDialog
from gramps.gen.db import DbTxn
from gramps.gen.utils.file import media_path_full, relative_path, media_path
from gramps.gen.utils.db import get_birth_or_fallback, get_death_or_fallback
from gramps.gui.plug import tool
from gramps.gui.managedwindow import ManagedWindow

_ = glocale.translation.sgettext
LOG = logging.getLogger(__name__)

CONFIG_TEMPLATE_KEY = "preferences.gwizardmediafix-filename-template"
DEFAULT_FILENAME_TEMPLATE = "{ref_id}_{surname}_{given}-{doc_type}-{year}.{ext}"
config.register(CONFIG_TEMPLATE_KEY, DEFAULT_FILENAME_TEMPLATE)

FILENAME_PRESETS: list[tuple[str, str]] = [
    (
        "{ref_id}_{surname}_{given}-{doc_type}-{year}.{ext}",
        _(
            "Reference ID + Community Standard ({ref_id}_{surname}_{given}-{doc_type}-{year})"
        ),
    ),
    (
        "{surname}_{given}-{doc_type}-{year}.{ext}",
        _("Community Standard ({surname}_{given}-{doc_type}-{year})"),
    ),
    (
        "{ref_id}_{doc_type}-{year}.{ext}",
        _("Reference ID + Document Type ({ref_id}_{doc_type}-{year})"),
    ),
    (
        "{id}_{doc_type}-{year}.{ext}",
        _("Media ID + Document Type ({id}_{doc_type}-{year})"),
    ),
    (
        "{id}_{orig}.{ext}",
        _("Media ID + Original Name ({id}_{orig})"),
    ),
    (
        "{orig}.{ext}",
        _("Sanitized Original Name ({orig})"),
    ),
]


# ------------------------------------------------------------
#
# Helper utilities for media analysis
#
# ------------------------------------------------------------
def clean_token(val: Any) -> str:
    """Sanitize an individual token value to contain only alphanumeric characters, underscores, and hyphens."""
    if not val:
        return ""
    s = re.sub(r"[\s_]*-+[\s_]*", "-", str(val))
    clean = re.sub(r"[^\w\-]+", "_", s)
    clean = re.sub(r"_+", "_", clean)
    clean = re.sub(r"[-_]*-[_\s-]*", "-", clean)
    clean = re.sub(r"-+", "-", clean)
    return clean.strip("_-")


def get_person_year(db: Any, person: Any) -> str:
    """Extract a representative year for a person (birth, death, or first dated event)."""
    if not person or not db:
        return ""
    try:
        birth = get_birth_or_fallback(db, person)
        if birth and birth.get_date_object() and birth.get_date_object().get_year() > 0:
            return str(birth.get_date_object().get_year())
        death = get_death_or_fallback(db, person)
        if death and death.get_date_object() and death.get_date_object().get_year() > 0:
            return str(death.get_date_object().get_year())
    except Exception:
        pass
    if hasattr(person, "get_event_ref_list"):
        for eref in person.get_event_ref_list():
            if hasattr(eref, "ref") and eref.ref:
                try:
                    evt = db.get_event_from_handle(eref.ref)
                    if (
                        evt
                        and evt.get_date_object()
                        and evt.get_date_object().get_year() > 0
                    ):
                        return str(evt.get_date_object().get_year())
                except Exception:
                    continue
    return ""


def resolve_media_reference_context(db: Any, media: Any) -> dict[str, str]:
    """Resolve context tokens (surname, given, doc_type, year, ref_id) for a media object."""
    context: dict[str, str] = {
        "id": str(media.get_gramps_id() or "") if media else "",
        "desc": str(media.get_description() or "") if media else "",
        "orig": "",
        "ext": "",
        "ref_id": str(media.get_gramps_id() or "") if media else "",
        "surname": "",
        "given": "",
        "doc_type": "",
        "year": "",
    }

    if media:
        raw_path = str(media.get_path() or "")
        if raw_path:
            _, basename = os.path.split(raw_path)
            name, ext = os.path.splitext(basename)
            context["orig"] = name
            context["ext"] = ext.lstrip(".").lower()

        if hasattr(media, "get_date_object"):
            d_obj = media.get_date_object()
            if d_obj and hasattr(d_obj, "get_year") and d_obj.get_year() > 0:
                context["year"] = str(d_obj.get_year())

    if not db or not media or not hasattr(db, "find_backlink_handles"):
        context["doc_type"] = context["desc"] or "media"
        return context

    media_handle = media.get_handle()
    if not media_handle:
        context["doc_type"] = context["desc"] or "media"
        return context

    backlinks = list(db.find_backlink_handles(media_handle))

    # Priority 1: Person backlink
    for cname, handle in backlinks:
        if cname == "Person":
            person = db.get_person_from_handle(handle)
            if person:
                context["ref_id"] = str(person.get_gramps_id() or context["ref_id"])
                pname = person.get_primary_name()
                if pname:
                    context["surname"] = str(pname.get_surname() or "")
                    context["given"] = str(pname.get_first_name() or "")
                context["doc_type"] = context["desc"] or "Photo"
                if not context["year"]:
                    context["year"] = get_person_year(db, person)
                return context

    # Priority 2: Event backlink
    for cname, handle in backlinks:
        if cname == "Event":
            event = db.get_event_from_handle(handle)
            if event:
                event_gid = str(event.get_gramps_id() or "")
                context["doc_type"] = context["desc"] or str(
                    event.get_type() or "Event"
                )
                e_date = event.get_date_object()
                if e_date and hasattr(e_date, "get_year") and e_date.get_year() > 0:
                    context["year"] = str(e_date.get_year())

                # Find participant in event
                e_backlinks = list(
                    db.find_backlink_handles(
                        handle, include_classes=["Person", "Family"]
                    )
                )
                for ecname, ehandle in e_backlinks:
                    if ecname == "Person":
                        person = db.get_person_from_handle(ehandle)
                        if person:
                            context["ref_id"] = str(person.get_gramps_id() or event_gid)
                            pname = person.get_primary_name()
                            if pname:
                                context["surname"] = str(pname.get_surname() or "")
                                context["given"] = str(pname.get_first_name() or "")
                            break
                    elif ecname == "Family" and not context["surname"]:
                        family = db.get_family_from_handle(ehandle)
                        if family:
                            context["ref_id"] = str(family.get_gramps_id() or event_gid)
                            f_handle = (
                                family.get_father_handle()
                                if hasattr(family, "get_father_handle")
                                else None
                            )
                            father = (
                                db.get_person_from_handle(f_handle)
                                if f_handle
                                else None
                            )
                            if father and father.get_primary_name():
                                context["surname"] = str(
                                    father.get_primary_name().get_surname() or ""
                                )
                if not context["ref_id"] or context["ref_id"] == context["id"]:
                    context["ref_id"] = event_gid
                return context

    # Priority 3: Family backlink
    for cname, handle in backlinks:
        if cname == "Family":
            family = db.get_family_from_handle(handle)
            if family:
                context["ref_id"] = str(family.get_gramps_id() or context["ref_id"])
                context["doc_type"] = context["desc"] or "Family"
                f_handle = (
                    family.get_father_handle()
                    if hasattr(family, "get_father_handle")
                    else None
                )
                father = db.get_person_from_handle(f_handle) if f_handle else None
                if father and father.get_primary_name():
                    context["surname"] = str(
                        father.get_primary_name().get_surname() or ""
                    )
                return context

    # Priority 4: Citation / Source backlink
    for cname, handle in backlinks:
        if cname == "Citation":
            cit = db.get_citation_from_handle(handle)
            if cit:
                context["ref_id"] = str(cit.get_gramps_id() or context["ref_id"])
                context["doc_type"] = context["desc"] or str(
                    cit.get_page() or "Citation"
                )
                s_handle = (
                    cit.get_reference_handle()
                    if hasattr(cit, "get_reference_handle")
                    else None
                )
                src = db.get_source_from_handle(s_handle) if s_handle else None
                if src and src.get_title():
                    context["doc_type"] = str(src.get_title())
                return context
        elif cname == "Source":
            src = db.get_source_from_handle(handle)
            if src:
                context["ref_id"] = str(src.get_gramps_id() or context["ref_id"])
                context["doc_type"] = context["desc"] or str(
                    src.get_title() or "Source"
                )
                return context

    if not context["doc_type"]:
        context["doc_type"] = context["desc"] or "media"
    return context


def format_standard_filename(
    template: str, context: dict[str, str], max_stem_len: int = 85
) -> str:
    """Format and sanitize a filename using template tokens and context."""
    ext = clean_token(context.get("ext", "jpg")).lower()
    if not ext:
        ext = "jpg"

    safe_context = {k: clean_token(v) for k, v in context.items() if k != "ext"}
    safe_context["ext"] = ext

    try:
        rendered = template.format(**safe_context)
    except (KeyError, ValueError, IndexError):
        rendered = f"{safe_context.get('ref_id', '')}_{safe_context.get('orig', 'media')}.{ext}"

    if "." in rendered:
        base, _ = rendered.rsplit(".", 1)
    else:
        base = rendered

    base = re.sub(r"[\s_]*-+[\s_]*", "-", base)
    base = re.sub(r"[^\w\-]+", "_", base)
    base = re.sub(r"_+", "_", base)
    base = re.sub(r"[-_]*-[_\s-]*", "-", base)
    base = re.sub(r"-+", "-", base)
    base = base.strip("_-")

    if not base:
        base = safe_context.get("orig") or safe_context.get("id") or "media"
        base = clean_token(base) or "media"

    if len(base) > max_stem_len:
        base = base[:max_stem_len].rstrip("_-")

    return f"{base}.{ext}"


def sanitize_standard_filename(
    path: str,
    db: Any = None,
    media: Any = None,
    template: str | None = None,
) -> str:
    """Return a sanitized standard filename adhering to platform-safe naming templates."""
    dirname, basename = os.path.split(path)
    name, ext = os.path.splitext(basename)
    ext_clean = ext.lstrip(".").lower()

    if db is not None and media is not None:
        tmpl = template or config.get(CONFIG_TEMPLATE_KEY) or DEFAULT_FILENAME_TEMPLATE
        ctx = resolve_media_reference_context(db, media)
        ctx["orig"] = name
        ctx["ext"] = ext_clean
        standard_basename = format_standard_filename(tmpl, ctx)
    else:
        tmpl = template or "{orig}.{ext}"
        ctx = {"orig": name, "ext": ext_clean, "id": "media", "ref_id": "media"}
        standard_basename = format_standard_filename(tmpl, ctx)

    return os.path.join(dirname, standard_basename) if dirname else standard_basename


# ------------------------------------------------------------
#
# FindMissingMediaDialog
#
# ------------------------------------------------------------
class FindMissingMediaDialog(Gtk.Dialog):
    """Review media records where the file is missing from disk."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Find Missing Media"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.rows: list[dict[str, Any]] = []
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1200, 480)

        # Scan database for missing media files
        base_dir = media_path(dbstate.db) if dbstate and dbstate.db else ""
        for media in dbstate.db.iter_media():
            m_handle = str(media.get_handle() or "")
            m_gid = str(media.get_gramps_id() or "")
            desc = str(media.get_description() or "")
            raw_path = str(media.get_path() or "")

            try:
                full_path = media_path_full(dbstate.db, raw_path)
            except Exception:
                full_path = raw_path

            if not os.path.exists(full_path):
                # Check if file exists in base media directory
                basename = os.path.basename(raw_path)
                sug_path = ""
                hint = _("File not found on disk")
                if base_dir and os.path.exists(os.path.join(base_dir, basename)):
                    sug_path = basename
                    hint = _("Found in media directory: suggest '%s'") % basename

                self.rows.append(
                    {
                        "handle": m_handle,
                        "gramps_id": m_gid,
                        "desc": desc,
                        "raw_path": raw_path,
                        "full_path": full_path,
                        "suggested_path": sug_path,
                        "hint_text": hint,
                    }
                )

        n_hints = sum(1 for r in self.rows if r.get("suggested_path"))
        self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(len(self.rows) > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        info = Gtk.Label(
            label=str(
                _(
                    "Review media records whose files are missing on disk. "
                    "Type the updated path or click 'Accept hints' if found in the media directory, then press 'Apply'."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not self.rows:
            done = Gtk.Label(label=str(_("No missing media files found.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(_("Total missing media records found: %d") % len(self.rows))
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        # Header grid
        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(6)
        header_grid.set_row_spacing(0)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        media_head = Gtk.Label()
        media_head.set_markup("<b>%s</b>" % str(_("Media")))
        media_head.set_halign(Gtk.Align.START)

        path_head = Gtk.Label()
        path_head.set_markup("<b>%s</b>" % str(_("Current Path")))
        path_head.set_halign(Gtk.Align.START)

        new_path_head = Gtk.Label()
        new_path_head.set_markup("<b>%s</b>" % str(_("New Path")))
        new_path_head.set_halign(Gtk.Align.START)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(media_head, 0, 0, 1, 1)
        header_grid.attach(path_head, 1, 0, 1, 1)
        header_grid.attach(new_path_head, 2, 0, 1, 1)
        header_grid.attach(hint_head, 3, 0, 1, 1)
        content.add(header_grid)

        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(4)
        ]
        self.column_sizegroups[0].add_widget(media_head)
        self.column_sizegroups[1].add_widget(path_head)
        self.column_sizegroups[2].add_widget(new_path_head)
        self.column_sizegroups[3].add_widget(hint_head)

        content.pack_start(self.build_rows(self.rows), True, True, 0)

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            # Column 0: Media description & ID
            m_text = "%s (%s)" % (
                entry.get("desc") or _("(unnamed)"),
                entry.get("gramps_id", ""),
            )
            media_label = Gtk.Label(label=m_text)
            media_label.set_halign(Gtk.Align.START)
            media_label.set_xalign(0.0)
            media_label.set_line_wrap(True)
            media_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            media_label.set_size_request(200, -1)
            media_label.set_max_width_chars(26)
            grid.attach(media_label, 0, row_index, 1, 1)

            # Column 1: Current Path
            curr_label = Gtk.Label(label=entry.get("raw_path", ""))
            curr_label.set_halign(Gtk.Align.START)
            curr_label.set_xalign(0.0)
            curr_label.set_line_wrap(True)
            curr_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            curr_label.set_size_request(240, -1)
            curr_label.set_max_width_chars(32)
            grid.attach(curr_label, 1, row_index, 1, 1)

            # Column 2: New Path entry
            path_entry = Gtk.Entry()
            path_entry.set_width_chars(28)
            path_entry.set_text("")
            grid.attach(path_entry, 2, row_index, 1, 1)

            # Column 3: Hint label
            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(220, -1)
            hint_label.set_max_width_chars(28)
            grid.attach(hint_label, 3, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(media_label)
                self.column_sizegroups[1].add_widget(curr_label)
                self.column_sizegroups[2].add_widget(path_entry)
                self.column_sizegroups[3].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "path_entry": path_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(280)
        scrolled.set_min_content_width(960)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        count = 0
        for target in self.row_targets:
            sug = target["entry"].get("suggested_path", "")
            if sug and not target["path_entry"].get_text():
                target["path_entry"].set_text(sug)
                count += 1
        OkDialog(
            str(_("Hints accepted")),
            str(
                _("Populated paths for %d media records. Review and press Apply.")
                % count
            ),
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        applied = 0
        with DbTxn(_("Update Missing Media Paths"), self.dbstate.db) as trans:
            for target in self.row_targets:
                new_path = target["path_entry"].get_text().strip()
                if not new_path:
                    continue
                h = target["entry"].get("handle")
                try:
                    media = self.dbstate.db.get_media_from_handle(h)
                except Exception:
                    media = None
                if media is not None:
                    media.set_path(new_path)
                    self.dbstate.db.commit_media(media, trans)
                    applied += 1

        if applied == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(_("No paths entered. Press 'Accept hints' or enter paths first.")),
                parent=self,
            )
            return

        OkDialog(
            str(_("Media Paths Updated")),
            str(_("Updated %d media file paths in the database.") % applied),
            parent=self,
        )

    def show_dialog(self) -> None:
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


# ------------------------------------------------------------
#
# ConsolidateMediaLocationDialog
#
# ------------------------------------------------------------
class ConsolidateMediaLocationDialog(Gtk.Dialog):
    """Review and consolidate absolute/scattered media paths into relative media directory paths."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Consolidate Media Location"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.rows: list[dict[str, Any]] = []
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1200, 480)

        base_dir = media_path(dbstate.db) if dbstate and dbstate.db else ""
        for media in dbstate.db.iter_media():
            m_handle = str(media.get_handle() or "")
            m_gid = str(media.get_gramps_id() or "")
            desc = str(media.get_description() or "")
            raw_path = str(media.get_path() or "")

            is_abs = os.path.isabs(raw_path)
            sug_path = ""
            hint = ""

            if is_abs and base_dir:
                try:
                    rel = relative_path(raw_path, base_dir)
                    if not os.path.isabs(rel) and not rel.startswith(".."):
                        sug_path = rel
                        hint = _("Absolute path: convert to relative '%s'") % rel
                    else:
                        hint = _("Absolute path outside base media directory")
                except Exception:
                    hint = _("Absolute path")
            elif not is_abs and ("\\" in raw_path or "/" in raw_path):
                # Standardize path separators
                std = raw_path.replace("\\", "/")
                if std != raw_path:
                    sug_path = std
                    hint = _("Standardize path separators")

            if sug_path or hint:
                self.rows.append(
                    {
                        "handle": m_handle,
                        "gramps_id": m_gid,
                        "desc": desc,
                        "raw_path": raw_path,
                        "suggested_path": sug_path,
                        "hint_text": hint,
                    }
                )

        n_hints = sum(1 for r in self.rows if r.get("suggested_path"))
        self.accept_button = Gtk.Button(label=str(_("Accept hints (%d)")) % n_hints)
        self.accept_button.set_sensitive(n_hints > 0)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(len(self.rows) > 0)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        info = Gtk.Label(
            label=str(
                _(
                    "Review media records with hardcoded absolute or non-standard paths. "
                    "Press 'Accept hints' to convert them to relative paths within your media directory, then press 'Apply'."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        if not self.rows:
            done = Gtk.Label(label=str(_("All media paths are already consolidated.")))
            done.set_halign(Gtk.Align.START)
            content.add(done)
            return

        count_label = Gtk.Label(
            label=str(_("Total unconsolidated media paths: %d") % len(self.rows))
        )
        count_label.set_halign(Gtk.Align.START)
        content.add(count_label)

        header_grid = Gtk.Grid()
        header_grid.set_column_spacing(6)
        header_grid.set_row_spacing(0)
        header_grid.set_hexpand(True)
        header_grid.set_vexpand(False)

        media_head = Gtk.Label()
        media_head.set_markup("<b>%s</b>" % str(_("Media")))
        media_head.set_halign(Gtk.Align.START)

        path_head = Gtk.Label()
        path_head.set_markup("<b>%s</b>" % str(_("Current Path")))
        path_head.set_halign(Gtk.Align.START)

        new_path_head = Gtk.Label()
        new_path_head.set_markup("<b>%s</b>" % str(_("Consolidated Path")))
        new_path_head.set_halign(Gtk.Align.START)

        hint_head = Gtk.Label()
        hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
        hint_head.set_halign(Gtk.Align.START)
        hint_head.set_hexpand(True)

        header_grid.attach(media_head, 0, 0, 1, 1)
        header_grid.attach(path_head, 1, 0, 1, 1)
        header_grid.attach(new_path_head, 2, 0, 1, 1)
        header_grid.attach(hint_head, 3, 0, 1, 1)
        content.add(header_grid)

        self.column_sizegroups = [
            Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(4)
        ]
        self.column_sizegroups[0].add_widget(media_head)
        self.column_sizegroups[1].add_widget(path_head)
        self.column_sizegroups[2].add_widget(new_path_head)
        self.column_sizegroups[3].add_widget(hint_head)

        content.pack_start(self.build_rows(self.rows), True, True, 0)

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            m_text = "%s (%s)" % (
                entry.get("desc") or _("(unnamed)"),
                entry.get("gramps_id", ""),
            )
            media_label = Gtk.Label(label=m_text)
            media_label.set_halign(Gtk.Align.START)
            media_label.set_xalign(0.0)
            media_label.set_line_wrap(True)
            media_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            media_label.set_size_request(200, -1)
            media_label.set_max_width_chars(26)
            grid.attach(media_label, 0, row_index, 1, 1)

            curr_label = Gtk.Label(label=entry.get("raw_path", ""))
            curr_label.set_halign(Gtk.Align.START)
            curr_label.set_xalign(0.0)
            curr_label.set_line_wrap(True)
            curr_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            curr_label.set_size_request(240, -1)
            curr_label.set_max_width_chars(32)
            grid.attach(curr_label, 1, row_index, 1, 1)

            path_entry = Gtk.Entry()
            path_entry.set_width_chars(28)
            path_entry.set_text("")
            grid.attach(path_entry, 2, row_index, 1, 1)

            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(220, -1)
            hint_label.set_max_width_chars(28)
            grid.attach(hint_label, 3, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(media_label)
                self.column_sizegroups[1].add_widget(curr_label)
                self.column_sizegroups[2].add_widget(path_entry)
                self.column_sizegroups[3].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "path_entry": path_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(280)
        scrolled.set_min_content_width(960)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        count = 0
        for target in self.row_targets:
            sug = target["entry"].get("suggested_path", "")
            if sug and not target["path_entry"].get_text():
                target["path_entry"].set_text(sug)
                count += 1
        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Populated consolidated paths for %d media records. Review and press Apply."
                )
                % count
            ),
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        applied = 0
        with DbTxn(_("Consolidate Media Locations"), self.dbstate.db) as trans:
            for target in self.row_targets:
                new_path = target["path_entry"].get_text().strip()
                if not new_path:
                    continue
                h = target["entry"].get("handle")
                try:
                    media = self.dbstate.db.get_media_from_handle(h)
                except Exception:
                    media = None
                if media is not None:
                    media.set_path(new_path)
                    self.dbstate.db.commit_media(media, trans)
                    applied += 1

        if applied == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(_("No paths entered. Press 'Accept hints' or enter paths first.")),
                parent=self,
            )
            return

        OkDialog(
            str(_("Media Locations Consolidated")),
            str(_("Consolidated %d media file paths in the database.") % applied),
            parent=self,
        )

    def show_dialog(self) -> None:
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


# ------------------------------------------------------------
#
# ApplyFilenameStandardsDialog
#
# ------------------------------------------------------------
class ApplyFilenameStandardsDialog(Gtk.Dialog):
    """Review and apply standard naming conventions to media filenames."""

    def __init__(
        self,
        title: str | None = None,
        dbstate: Any = None,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        dialog_title = title or str(_("Apply Filename Standards"))
        super().__init__(
            title=dialog_title,
            transient_for=transient_for,
            modal=True,
            destroy_with_parent=True,
        )
        self.dbstate = dbstate
        self.rows: list[dict[str, Any]] = []
        self.row_targets: list[dict[str, Any]] = []
        self.set_default_size(1200, 520)

        self.accept_button = Gtk.Button(label=str(_("Accept hints (0)")))
        self.accept_button.set_sensitive(False)
        self.accept_button.connect("clicked", self.cb_accept_hints)
        self.add_action_widget(self.accept_button, Gtk.ResponseType.NONE)

        self.apply_button = Gtk.Button(label=str(_("Apply")))
        self.apply_button.set_sensitive(False)
        self.apply_button.connect("clicked", self.cb_apply)
        self.add_action_widget(self.apply_button, Gtk.ResponseType.NONE)

        self.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        info = Gtk.Label(
            label=str(
                _(
                    "Review media filenames with irregular characters, spaces, or uppercase extensions. "
                    "Select a standard naming template, press 'Accept hints', then press 'Apply'."
                )
            )
        )
        info.set_line_wrap(True)
        info.set_halign(Gtk.Align.START)
        content.add(info)

        # Template selection row
        tmpl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tmpl_box.set_hexpand(True)

        tmpl_label = Gtk.Label(label=str(_("Naming Template:")))
        tmpl_label.set_halign(Gtk.Align.START)
        tmpl_box.pack_start(tmpl_label, False, False, 0)

        self.tmpl_combo = Gtk.ComboBoxText.new_with_entry()
        self.tmpl_combo.set_hexpand(True)
        for tmpl_str, tmpl_desc in FILENAME_PRESETS:
            self.tmpl_combo.append_text(tmpl_desc)

        curr_tmpl = config.get(CONFIG_TEMPLATE_KEY) or DEFAULT_FILENAME_TEMPLATE
        entry = self.tmpl_combo.get_child()
        if hasattr(entry, "set_text"):
            entry.set_text(curr_tmpl)
            if hasattr(entry, "connect"):
                entry.connect("activate", self.cb_template_entry_activated)

        self.tmpl_combo.connect("changed", self.cb_template_changed)
        tmpl_box.pack_start(self.tmpl_combo, True, True, 0)
        content.add(tmpl_box)

        self.count_label = Gtk.Label(label="")
        self.count_label.set_halign(Gtk.Align.START)
        content.add(self.count_label)

        self.rows_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.rows_container.set_hexpand(True)
        self.rows_container.set_vexpand(True)
        content.pack_start(self.rows_container, True, True, 0)

        self.refresh_rows(curr_tmpl)

    def cb_template_changed(self, combo: Gtk.ComboBoxText) -> None:
        idx = combo.get_active()
        if 0 <= idx < len(FILENAME_PRESETS):
            tmpl_str = FILENAME_PRESETS[idx][0]
            entry = combo.get_child()
            if hasattr(entry, "set_text"):
                entry.set_text(tmpl_str)
            self.apply_template(tmpl_str)
        else:
            entry = combo.get_child()
            if hasattr(entry, "get_text"):
                tmpl_str = entry.get_text().strip()
                if tmpl_str:
                    self.apply_template(tmpl_str)

    def cb_template_entry_activated(self, entry: Gtk.Entry) -> None:
        tmpl_str = entry.get_text().strip()
        if tmpl_str:
            self.apply_template(tmpl_str)

    def apply_template(self, tmpl_str: str) -> None:
        config.set(CONFIG_TEMPLATE_KEY, tmpl_str)
        self.refresh_rows(tmpl_str)

    def refresh_rows(self, template: str) -> None:
        self.rows.clear()
        self.row_targets.clear()

        if self.dbstate and self.dbstate.db:
            for media in self.dbstate.db.iter_media():
                m_handle = str(media.get_handle() or "")
                m_gid = str(media.get_gramps_id() or "")
                desc = str(media.get_description() or "")
                raw_path = str(media.get_path() or "")

                if not raw_path:
                    continue

                std_path = sanitize_standard_filename(
                    raw_path, db=self.dbstate.db, media=media, template=template
                )
                if std_path != raw_path:
                    self.rows.append(
                        {
                            "handle": m_handle,
                            "gramps_id": m_gid,
                            "desc": desc,
                            "raw_path": raw_path,
                            "suggested_path": std_path,
                            "hint_text": _("Standardize filename to '%s'")
                            % os.path.basename(std_path),
                        }
                    )

        n_hints = len(self.rows)
        self.accept_button.set_label(str(_("Accept hints (%d)")) % n_hints)
        self.accept_button.set_sensitive(n_hints > 0)
        self.apply_button.set_sensitive(n_hints > 0)
        self.count_label.set_text(
            str(_("Total non-standard media filenames: %d") % n_hints)
        )

        for child in self.rows_container.get_children():
            self.rows_container.remove(child)

        if not self.rows:
            done = Gtk.Label(
                label=str(_("All media filenames already meet the selected standards."))
            )
            done.set_halign(Gtk.Align.START)
            self.rows_container.pack_start(done, False, False, 0)
        else:
            header_grid = Gtk.Grid()
            header_grid.set_column_spacing(6)
            header_grid.set_row_spacing(0)
            header_grid.set_hexpand(True)
            header_grid.set_vexpand(False)

            media_head = Gtk.Label()
            media_head.set_markup("<b>%s</b>" % str(_("Media")))
            media_head.set_halign(Gtk.Align.START)

            curr_head = Gtk.Label()
            curr_head.set_markup("<b>%s</b>" % str(_("Current Filename")))
            curr_head.set_halign(Gtk.Align.START)

            std_head = Gtk.Label()
            std_head.set_markup("<b>%s</b>" % str(_("Standard Filename")))
            std_head.set_halign(Gtk.Align.START)

            hint_head = Gtk.Label()
            hint_head.set_markup("<b>%s</b>" % str(_("Hint")))
            hint_head.set_halign(Gtk.Align.START)
            hint_head.set_hexpand(True)

            header_grid.attach(media_head, 0, 0, 1, 1)
            header_grid.attach(curr_head, 1, 0, 1, 1)
            header_grid.attach(std_head, 2, 0, 1, 1)
            header_grid.attach(hint_head, 3, 0, 1, 1)
            self.rows_container.pack_start(header_grid, False, False, 0)

            self.column_sizegroups = [
                Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for _ in range(4)
            ]
            self.column_sizegroups[0].add_widget(media_head)
            self.column_sizegroups[1].add_widget(curr_head)
            self.column_sizegroups[2].add_widget(std_head)
            self.column_sizegroups[3].add_widget(hint_head)

            self.rows_container.pack_start(self.build_rows(self.rows), True, True, 0)

        self.rows_container.show_all()

    def build_rows(self, entries: list[dict[str, Any]]) -> Gtk.ScrolledWindow:
        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        row_index = 0
        for entry in entries:
            m_text = "%s (%s)" % (
                entry.get("desc") or _("(unnamed)"),
                entry.get("gramps_id", ""),
            )
            media_label = Gtk.Label(label=m_text)
            media_label.set_halign(Gtk.Align.START)
            media_label.set_xalign(0.0)
            media_label.set_line_wrap(True)
            media_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            media_label.set_size_request(200, -1)
            media_label.set_max_width_chars(26)
            grid.attach(media_label, 0, row_index, 1, 1)

            curr_label = Gtk.Label(label=entry.get("raw_path", ""))
            curr_label.set_halign(Gtk.Align.START)
            curr_label.set_xalign(0.0)
            curr_label.set_line_wrap(True)
            curr_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            curr_label.set_size_request(240, -1)
            curr_label.set_max_width_chars(32)
            grid.attach(curr_label, 1, row_index, 1, 1)

            std_entry = Gtk.Entry()
            std_entry.set_width_chars(28)
            std_entry.set_text("")
            grid.attach(std_entry, 2, row_index, 1, 1)

            hint_label = Gtk.Label(label=entry.get("hint_text", ""))
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_xalign(0.0)
            hint_label.set_line_wrap(True)
            hint_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            hint_label.set_size_request(220, -1)
            hint_label.set_max_width_chars(28)
            grid.attach(hint_label, 3, row_index, 1, 1)

            if row_index == 0 and hasattr(self, "column_sizegroups"):
                self.column_sizegroups[0].add_widget(media_label)
                self.column_sizegroups[1].add_widget(curr_label)
                self.column_sizegroups[2].add_widget(std_entry)
                self.column_sizegroups[3].add_widget(hint_label)

            self.row_targets.append(
                {
                    "entry": entry,
                    "std_entry": std_entry,
                    "hint_label": hint_label,
                }
            )
            row_index += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(280)
        scrolled.set_min_content_width(960)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(grid)
        return scrolled

    def cb_accept_hints(self, _button: Gtk.Button) -> None:
        count = 0
        for target in self.row_targets:
            sug = target["entry"].get("suggested_path", "")
            if sug and not target["std_entry"].get_text():
                target["std_entry"].set_text(sug)
                count += 1
        OkDialog(
            str(_("Hints accepted")),
            str(
                _(
                    "Populated standard filenames for %d media records. Review and press Apply."
                )
                % count
            ),
            parent=self,
        )

    def cb_apply(self, _button: Gtk.Button) -> None:
        applied = 0
        with DbTxn(_("Apply Filename Standards"), self.dbstate.db) as trans:
            for target in self.row_targets:
                new_path = target["std_entry"].get_text().strip()
                if not new_path:
                    continue
                h = target["entry"].get("handle")
                try:
                    media = self.dbstate.db.get_media_from_handle(h)
                except Exception:
                    media = None
                if media is not None:
                    media.set_path(new_path)
                    self.dbstate.db.commit_media(media, trans)
                    applied += 1

        if applied == 0:
            OkDialog(
                str(_("Nothing to apply")),
                str(
                    _(
                        "No filenames entered. Press 'Accept hints' or enter filenames first."
                    )
                ),
                parent=self,
            )
            return

        OkDialog(
            str(_("Filename Standards Applied")),
            str(_("Updated %d media filenames in the database.") % applied),
            parent=self,
        )

    def show_dialog(self) -> None:
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


def generate_media_fix_report(db: Any) -> str:
    """Scan all media objects in database, check existence with os.path.exists(), and return formatted report."""
    base_dir = media_path(db) if db else ""
    curr_tmpl = config.get(CONFIG_TEMPLATE_KEY) or DEFAULT_FILENAME_TEMPLATE
    total = 0
    found = 0
    missing = 0
    absolute_paths = 0
    non_standard = 0

    missing_list: list[tuple[str, str, str]] = []
    abs_list: list[tuple[str, str, str]] = []
    non_std_list: list[tuple[str, str, str, str]] = []

    for media in db.iter_media():
        total += 1
        m_gid = str(media.get_gramps_id() or "")
        desc = str(media.get_description() or "")

        # Inspect file path(s) using media.get_path() or media.get_file_list() if available
        if hasattr(media, "get_file_list"):
            raw_paths = media.get_file_list() or []
            if not raw_paths:
                raw_paths = [str(media.get_path() or "")]
        else:
            raw_paths = [str(media.get_path() or "")]

        for raw_path in raw_paths:
            # Check existence on filesystem
            try:
                full_path = media_path_full(db, raw_path)
            except Exception:
                full_path = raw_path

            if os.path.exists(full_path):
                found += 1
            else:
                missing += 1
                missing_list.append((m_gid, desc, raw_path))

            # Check absolute path
            if os.path.isabs(raw_path):
                absolute_paths += 1
                abs_list.append((m_gid, desc, raw_path))

            # Check filename standards
            if raw_path:
                std_path = sanitize_standard_filename(
                    raw_path, db=db, media=media, template=curr_tmpl
                )
                if std_path != raw_path:
                    non_standard += 1
                    non_std_list.append((m_gid, desc, raw_path, std_path))

    lines: list[str] = [
        "=" * 72,
        "GWIZARD MEDIA FIX REPORT",
        "=" * 72,
        "",
        "SUMMARY METRICS:",
        f"  Total media records:       {total}",
        f"  Files found on disk:       {found}",
        f"  Files missing on disk:     {missing}",
        f"  Absolute file paths:       {absolute_paths}",
        f"  Non-standard filenames:    {non_standard}",
        f"  Naming template:           {curr_tmpl}",
        f"  Base media directory:      {base_dir if base_dir else '(none configured)'}",
        "",
    ]

    if missing_list:
        lines.append("-" * 72)
        lines.append(f"MISSING FILES ({len(missing_list)} items):")
        lines.append("-" * 72)
        for gid, desc, path in missing_list:
            lines.append(f"  [{gid}] {desc}")
            lines.append(f"    Path: {path}")
        lines.append("")

    if abs_list:
        lines.append("-" * 72)
        lines.append(f"ABSOLUTE PATHS ({len(abs_list)} items):")
        lines.append("-" * 72)
        for gid, desc, path in abs_list:
            lines.append(f"  [{gid}] {desc}")
            lines.append(f"    Path: {path}")
        lines.append("")

    if non_std_list:
        lines.append("-" * 72)
        lines.append(f"NON-STANDARD FILENAMES ({len(non_std_list)} items):")
        lines.append("-" * 72)
        for gid, desc, path, std_p in non_std_list:
            lines.append(f"  [{gid}] {desc}")
            lines.append(f"    Current:  {path}")
            lines.append(f"    Standard: {std_p}")
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------
#
# GWizardMediaFix Window Controller
#
# ------------------------------------------------------------
class GWizardMediaFixOptions(tool.ToolOptions):
    """Tool options for GWizard Media Fix."""

    def __init__(self, name: str, person_id: str | None = None) -> None:
        super().__init__(name, person_id)


class GWizardMediaFix(tool.Tool, ManagedWindow):
    """Top-level GWizard Media Fix tool window."""

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
        self._build_window(uistate)
        self.show()

    def _build_window(self, uistate: Any) -> None:
        dialog = Gtk.Dialog(
            title=str(_("GWizard Media Fix")),
            transient_for=uistate.window,
            modal=True,
            destroy_with_parent=True,
        )
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(8)

        desc = Gtk.Label(
            label=str(
                _(
                    "Comprehensive utility to inspect media files across your database, find missing files, "
                    "consolidate storage locations into relative paths, and enforce standardized filename formats."
                )
            )
        )
        desc.set_line_wrap(True)
        desc.set_halign(Gtk.Align.START)
        content.add(desc)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.pack_start(vbox, True, True, 0)

        specs = [
            ("generate", str(_("Generate report"))),
            ("find_missing", str(_("Find missing media"))),
            ("consolidate_location", str(_("Consolidate media location"))),
            ("apply_standards", str(_("Apply filename standards"))),
        ]

        self.buttons: dict[str, Gtk.Button] = {}
        for key, label in specs:
            button = Gtk.Button(label=label)
            button.set_hexpand(True)
            button.connect("clicked", self.cb_button, key)
            vbox.pack_start(button, False, False, 0)
            self.buttons[key] = button

        dialog.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        dialog.connect("response", self.cb_close)

        self.set_window(dialog, None, str(_("GWizard Media Fix")))
        self.setup_configs("interface.gwizardmediafix", 440, 280)
        dialog.show_all()

    def cb_close(self, dialog: Gtk.Dialog, response: int) -> None:
        self.close()

    def cb_generate_report(self) -> None:
        """Prompt file chooser for GWizardMediaFixReport.txt and write generated report."""
        chooser = Gtk.FileChooserDialog(
            title=str(_("Save Media Fix Report")),
            transient_for=self.window,
            action=Gtk.FileChooserAction.SAVE,
        )
        chooser.add_buttons(
            str(_("_Cancel")),
            Gtk.ResponseType.CANCEL,
            str(_("_Save")),
            Gtk.ResponseType.OK,
        )
        chooser.set_current_name("GWizardMediaFixReport.txt")

        base_dir = (
            media_path(self.dbstate.db) if self.dbstate and self.dbstate.db else ""
        )
        if base_dir and os.path.isdir(base_dir):
            chooser.set_current_folder(base_dir)

        status = chooser.run()
        target_path = chooser.get_filename() if status == Gtk.ResponseType.OK else None
        chooser.destroy()

        if not target_path:
            return

        report_text = generate_media_fix_report(self.dbstate.db)
        try:
            with open(target_path, "w", encoding="utf-8") as handle:
                handle.write(report_text)
            self.report_path = target_path
            OkDialog(
                str(_("Report Generated")),
                str(_("Report written to %s.") % target_path),
                parent=self.window,
            )
            self.cb_view_report()
        except OSError as err:
            LOG.error("Failed to write report: %s", err)

    def cb_view_report(self) -> None:
        """Open generated report in viewer dialog."""
        if not self.report_path or not os.path.exists(self.report_path):
            return

        try:
            with open(self.report_path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            return

        dialog = Gtk.Dialog(
            title=str(_("GWizard Media Fix Report")),
            transient_for=self.window,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button(str(_("_Close")), Gtk.ResponseType.CLOSE)
        dialog.connect("response", lambda dlg, resp: dlg.destroy())
        dialog.set_default_size(800, 500)

        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_wrap_mode(Gtk.WrapMode.WORD)
        textview.get_buffer().set_text(text)
        scrolled.add(textview)

        content.pack_start(scrolled, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def cb_button(self, button: Gtk.Button, key: str) -> None:
        if key == "generate":
            self.cb_generate_report()
        elif key == "find_missing":
            dlg = FindMissingMediaDialog(
                title=str(_("Find Missing Media")),
                dbstate=self.dbstate,
                transient_for=self.window,
            )
            dlg.show_dialog()
        elif key == "consolidate_location":
            dlg = ConsolidateMediaLocationDialog(
                title=str(_("Consolidate Media Location")),
                dbstate=self.dbstate,
                transient_for=self.window,
            )
            dlg.show_dialog()
        elif key == "apply_standards":
            dlg = ApplyFilenameStandardsDialog(
                title=str(_("Apply Filename Standards")),
                dbstate=self.dbstate,
                transient_for=self.window,
            )
            dlg.show_dialog()
