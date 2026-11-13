#
# Gramps - a GTK+/GNOME based genealogy program
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
"""
Central enforcement of the gtk-alternative-button-order setting.

When the setting is True (Windows), the affirmative button of a dialog is
moved to the front of its action area: [OK] [Cancel] instead of the GNOME
order [Cancel] [OK]. When it is False nothing is changed.

Uses only non-deprecated GTK 3 API (no get_action_area() or
set_alternative_button_order_from_array()).
"""

from gi.repository import Gtk

# Responses that mark the affirmative button, in priority order.
_PRIMARY = (
    Gtk.ResponseType.OK,
    Gtk.ResponseType.ACCEPT,
    Gtk.ResponseType.YES,
    Gtk.ResponseType.APPLY,
)


def alternative_order_enabled():
    """Return True when dialogs should use the Windows button order."""
    settings = Gtk.Settings.get_default()
    return bool(settings and settings.props.gtk_alternative_button_order)


def apply_button_order(dialog, order=None, help_last=False):
    """Reorder the action buttons of ``dialog`` for the Windows convention.

    :param order: optional explicit list of response ids, for dialogs that
                  use custom responses (e.g. MultiSelectDialog's 1/2/3).
    :param help_last: also move a Help button from the far left to the far
                      right ([OK] [Cancel] [Help]).

    Idempotent, and a no-op unless gtk-alternative-button-order is True.
    """
    if not isinstance(dialog, Gtk.Dialog) or not alternative_order_enabled():
        return
    if dialog.props.use_header_bar:
        return  # header-bar dialogs place their buttons by response type

    # Locate the action area through a button rather than the deprecated
    # Gtk.Dialog.get_action_area().
    if order is None:
        primary = None
        for response in _PRIMARY:
            primary = dialog.get_widget_for_response(response)
            if primary is not None:
                break
        if primary is None:
            return  # nothing affirmative to move
        area = primary.get_parent()
        area.reorder_child(primary, 0)
    else:
        buttons = [dialog.get_widget_for_response(r) for r in order]
        buttons = [b for b in buttons if b is not None]
        if not buttons:
            return
        area = buttons[0].get_parent()
        for pos, btn in enumerate(buttons):
            area.reorder_child(btn, pos)

    if help_last:
        help_btn = dialog.get_widget_for_response(Gtk.ResponseType.HELP)
        if help_btn is not None and isinstance(area, Gtk.ButtonBox):
            area.set_child_secondary(help_btn, False)
            area.reorder_child(help_btn, -1)


def apply_on_realize(dialog, order=None, help_last=False):
    """For dialogs built in Python: reorder when the dialog is first
    realized, i.e. after every add_button() call but before it is drawn."""
    if isinstance(dialog, Gtk.Dialog):
        dialog.connect(
            "realize", lambda d: apply_button_order(d, order, help_last)
        )


def apply_to_builder(builder):
    """For Glade files: buttons exist as soon as the file is loaded."""
    for obj in builder.get_objects():
        if isinstance(obj, Gtk.Dialog):
            apply_button_order(obj)
