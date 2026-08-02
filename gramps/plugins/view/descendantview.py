#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  The Gramps project
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

# -------------------------------------------------------------------------
#
# Standard Python modules
#
# -------------------------------------------------------------------------
import logging

# -------------------------------------------------------------------------
#
# GTK/Gnome modules
#
# -------------------------------------------------------------------------
from gi.repository import Gdk
from gi.repository import Gtk

# -------------------------------------------------------------------------
#
# Gramps modules
#
# -------------------------------------------------------------------------
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.const import CUSTOM_FILTERS, URL_MANUAL_PAGE, URL_WIKISTRING
from gramps.gen.errors import WindowActiveError
from gramps.gen.lib import ChildRef, Family
from gramps.gen.display.name import displayer as name_displayer
from gramps.gen.utils.db import find_children, find_parents, find_witnessed_people
from gramps.gen.utils.libformatting import FormattingHelper
from gramps.gui.display import display_url
from gramps.gui.dialog import RunDatabaseRepair
from gramps.gui.editors import EditFamily, EditPerson, FilterEditor
from gramps.gui.utils import is_right_click
from gramps.gui.views.bookmarks import PersonBookmarks
from gramps.gui.views.navigationview import NavigationView
from gramps.plugins.view.pedigreeview import PersonBoxWidgetCairo

_ = glocale.translation.sgettext

LOG = logging.getLogger(__name__)

WIKI_PAGE = URL_WIKISTRING + URL_MANUAL_PAGE + "_-_Categories#Descendant_View"


#------------------------------------------------------------
#
# ParentOutboundLine
#
#------------------------------------------------------------
class ParentOutboundLine(Gtk.DrawingArea):
    """
    Draws a vertical coupling backbone on the right side to join couples
    together, extending a single horizontal connector stub cleanly outward
    to the LEFT.
    """

    def __init__(self, num_spouses: int = 0) -> None:
        Gtk.DrawingArea.__init__(self)
        self.num_spouses = num_spouses
        self.set_size_request(20, -1)
        self.connect("draw", self.draw_line)

    def draw_line(self, widget: Gtk.DrawingArea, context) -> bool:
        alloc = self.get_allocation()
        context.set_source_rgb(0.0, 0.0, 0.0)
        context.set_line_width(2)

        mid_y = alloc.height / 2
        right_edge = alloc.width

        # The top primary person box center always maps to 24px
        person1_center_y = 24

        if self.num_spouses > 0:
            spouse_center_y = alloc.height - 24

            # Draw horizontal lines poking into both the person and the spouse
            context.move_to(right_edge, person1_center_y)
            context.line_to(right_edge / 2, person1_center_y)

            context.move_to(right_edge, spouse_center_y)
            context.line_to(right_edge / 2, spouse_center_y)

            # Draw the vertical coupling backbone joining them
            context.move_to(right_edge / 2, person1_center_y)
            context.line_to(right_edge / 2, spouse_center_y)

            # Outbound lineage delivery line centered perfectly on the branch
            context.move_to(right_edge / 2, mid_y)
            context.line_to(0, mid_y)
        else:
            # Single individual connector line layout
            context.move_to(right_edge, mid_y)
            context.line_to(0, mid_y)

        context.stroke()
        return False


#------------------------------------------------------------
#
# ChildInboundLine
#
#------------------------------------------------------------
class ChildInboundLine(Gtk.DrawingArea):
    """
    Draws seamless, unbroken vertical tracking rails from the first sibling's
    horizontal line down to the last sibling's horizontal line.
    """

    def __init__(
        self, is_first_child: bool, is_last_child: bool, has_spouse: bool = False
    ) -> None:
        Gtk.DrawingArea.__init__(self)
        self.is_first_child = is_first_child
        self.is_last_child = is_last_child
        self.has_spouse = has_spouse
        self.set_size_request(20, -1)
        self.connect("draw", self.draw_lines)

    def draw_lines(self, widget: Gtk.DrawingArea, context) -> bool:
        alloc = self.get_allocation()
        context.set_source_rgb(0.0, 0.0, 0.0)
        context.set_line_width(2)

        spine_x = alloc.width

        # Calculate target Y center based on whether the sibling box
        # contains a spouse
        target_y = 24 if self.has_spouse else (alloc.height / 2)

        # 1. Horizontal connector pin running into the right side of the
        #    child box
        context.move_to(spine_x, target_y)
        context.line_to(0, target_y)

        # 2. Continuous vertical sibling tracking rails (edge to edge)
        if not self.is_first_child:
            context.move_to(spine_x, target_y)
            context.line_to(spine_x, 0)

        if not self.is_last_child:
            context.move_to(spine_x, target_y)
            context.line_to(spine_x, alloc.height)

        context.stroke()
        return False


#------------------------------------------------------------
#
# DescendantView
#
#------------------------------------------------------------
class DescendantView(NavigationView):
    """
    A view that displays descendants branching from right (root) to left
    (descendants), grouping spouses side-by-side inside family cells with
    zero line breaking gaps.
    """

    CONFIGSETTINGS = (
        ("interface.descrtl-tree-size", 4),
        ("interface.descrtl-show-images", True),
        ("interface.descrtl-show-tags", False),
    )

    FLEUR_CURSOR = Gdk.Cursor.new_for_display(
        Gdk.Display.get_default(), Gdk.CursorType.FLEUR
    )

    additional_ui = [
        """
      <placeholder id="CommonGo">
      <section>
        <item>
          <attribute name="action">win.Back</attribute>
          <attribute name="label" translatable="yes">_Back</attribute>
        </item>
        <item>
          <attribute name="action">win.Forward</attribute>
          <attribute name="label" translatable="yes">_Forward</attribute>
        </item>
      </section>
      <section>
        <item>
          <attribute name="action">win.HomePerson</attribute>
          <attribute name="label" translatable="yes">_Home</attribute>
        </item>
      </section>
      </placeholder>
""",
        """
      <section id="AddEditBook">
        <item>
          <attribute name="action">win.AddBook</attribute>
          <attribute name="label" translatable="yes">_Add Bookmark</attribute>
        </item>
        <item>
          <attribute name="action">win.EditBook</attribute>
          <attribute name="label" translatable="no">%s...</attribute>
        </item>
      </section>
"""
        % _("Organize Bookmarks"),
        """
        <placeholder id='otheredit'>
        <item>
          <attribute name="action">win.FilterEdit</attribute>
          <attribute name="label" translatable="yes">"""
        """Person Filter Editor</attribute>
        </item>
        </placeholder>
""",
        """
    <placeholder id='CommonNavigation'>
    <child groups='RO'>
      <object class="GtkToolButton">
        <property name="icon-name">go-previous</property>
        <property name="action-name">win.Back</property>
        <property name="tooltip_text" translatable="yes">"""
        """Go to the previous object in the history</property>
        <property name="label" translatable="yes">_Back</property>
        <property name="use-underline">True</property>
      </object>
      <packing>
        <property name="homogeneous">False</property>
      </packing>
    </child>
    <child groups='RO'>
      <object class="GtkToolButton">
        <property name="icon-name">go-next</property>
        <property name="action-name">win.Forward</property>
        <property name="tooltip_text" translatable="yes">"""
        """Go to the next object in the history</property>
        <property name="label" translatable="yes">_Forward</property>
        <property name="use-underline">True</property>
      </object>
      <packing>
        <property name="homogeneous">False</property>
      </packing>
    </child>
    <child groups='RO'>
      <object class="GtkToolButton">
        <property name="icon-name">go-home</property>
        <property name="action-name">win.HomePerson</property>
        <property name="tooltip_text" translatable="yes">"""
        """Go to the home person</property>
        <property name="label" translatable="yes">_Home</property>
        <property name="use-underline">True</property>
      </object>
      <packing>
        <property name="homogeneous">False</property>
      </packing>
    </child>
    </placeholder>
    """,
    ]

    def __init__(self, pdata, dbstate, uistate, nav_group: int = 0) -> None:
        NavigationView.__init__(
            self,
            _("Descendant RTL"),
            pdata,
            dbstate,
            uistate,
            PersonBookmarks,
            nav_group,
        )
        self.dbstate = dbstate
        self.uistate = uistate
        self.dbstate.connect("database-changed", self.change_db)
        uistate.connect("nameformat-changed", self.refresh_view)
        uistate.connect("font-changed", self.refresh_view)
        self.format_helper = FormattingHelper(self.dbstate, self.uistate)
        self.tree_depth = self._config.get("interface.descrtl-tree-size")
        self.show_images = self._config.get("interface.descrtl-show-images")
        self.show_tags = self._config.get("interface.descrtl-show-tags")
        self.scrolledwindow = None
        self.table = None
        self.additional_uis.append(self.additional_ui)
        # Variables for drag-scroll
        self._last_x = 0
        self._last_y = 0
        self._in_move = False

    def define_actions(self) -> None:
        """Build the action group information for navigation shortcuts."""
        NavigationView.define_actions(self)
        self._add_action("FilterEdit", self.cb_filter_editor)
        self._add_action("F2", self.kb_goto_home, "F2")
        self._add_action("PRIMARY-J", self.jump, "<PRIMARY>J")

    def cb_filter_editor(self, *obj) -> None:
        """Display the person filter editor."""
        try:
            FilterEditor("Person", CUSTOM_FILTERS, self.dbstate, self.uistate)
        except WindowActiveError:
            return

    def kb_goto_home(self, *obj) -> None:
        """Goto home person from keyboard."""
        self.cb_home(None)

    def get_handle_from_gramps_id(self, gid: str):
        """Return the handle of the specified person."""
        obj = self.dbstate.db.get_person_from_gramps_id(gid)
        if obj:
            return obj.get_handle()
        return None

    def get_stock(self) -> str:
        """Return the category stock icon."""
        return "gramps-pedigree"

    def get_viewtype_stock(self) -> str:
        """Return the view type stock icon."""
        return "gramps-pedigree"

    def navigation_type(self) -> str:
        """Return the navigation type."""
        return "Person"

    def can_configure(self) -> bool:
        """Allow configuration of the view."""
        return True

    def on_delete(self) -> None:
        """Save config on shutdown."""
        self._config.save()
        NavigationView.on_delete(self)

    def on_help_clicked(self, dummy) -> None:
        """Display the relevant portion of Gramps manual."""
        display_url(WIKI_PAGE)

    def _connect_db_signals(self) -> None:
        """Connect database signals."""
        self._add_db_signal("person-add", self.refresh_view)
        self._add_db_signal("person-update", self.refresh_view)
        self._add_db_signal("person-delete", self.refresh_view)
        self._add_db_signal("person-rebuild", self.refresh_view)
        self._add_db_signal("family-update", self.refresh_view)
        self._add_db_signal("family-add", self.refresh_view)
        self._add_db_signal("family-delete", self.refresh_view)
        self._add_db_signal("family-rebuild", self.refresh_view)
        self._add_db_signal("event-update", self.refresh_view)

    def build_widget(self):
        """Build the interface and return a Gtk.Container."""
        self.scrolledwindow = Gtk.ScrolledWindow()
        self.scrolledwindow.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )
        self.scrolledwindow.add_events(Gdk.EventMask.SCROLL_MASK)
        event_box = Gtk.EventBox()
        event_box.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
        )
        event_box.connect("button-press-event", self.cb_bg_button_press)
        event_box.connect("button-release-event", self.cb_bg_button_release)
        event_box.connect("motion-notify-event", self.cb_bg_motion_notify_event)
        self.scrolledwindow.add(event_box)

        self.table = Gtk.Grid()
        self.table.set_direction(Gtk.TextDirection.LTR)
        event_box.add(self.table)
        event_box.get_parent().set_shadow_type(Gtk.ShadowType.NONE)
        self.table.set_row_spacing(0)
        self.table.set_column_spacing(0)
        return self.scrolledwindow

    def change_page(self) -> None:
        """Called when the page changes."""
        NavigationView.change_page(self)
        self.uistate.clear_filter_results()
        if self.dirty:
            self.build_tree()

    def change_db(self, db) -> None:
        """Handle database change callback."""
        self._change_db(db)
        if self.active:
            self.bookmarks.redraw()
        self.build_tree()

    def refresh_view(self, dummy=None) -> None:
        """Refresh the view when data changes."""
        self.format_helper.clear_cache()
        self.dirty = True
        if self.active:
            self.build_tree()

    def goto_handle(self, handle=None) -> None:
        """Rebuild the tree with the given person handle as root."""
        self.dirty = True
        if handle:
            person = self.dbstate.db.get_person_from_handle(handle)
            if person:
                self.build_tree()
            else:
                return
        else:
            self.build_tree()
        self.uistate.modify_statusbar(self.dbstate)

    def cb_childmenu_changed(self, obj, person_handle) -> bool:
        """Callback for pulldown menu selection."""
        self.change_active(person_handle)
        return True

    def cb_on_show_child_menu(self, obj, person_handle) -> int:
        """Show a popup menu of children for the given person."""
        from html import escape

        person = self.dbstate.db.get_person_from_handle(person_handle)
        if person:
            childlist = find_children(self.dbstate.db, person)
            if len(childlist) == 1:
                child = self.dbstate.db.get_person_from_handle(childlist[0])
                if child:
                    self.change_active(childlist[0])
            elif len(childlist) > 1:
                self.my_menu = Gtk.Menu()
                self.my_menu.set_reserve_toggle_size(False)
                for child_handle in childlist:
                    child = self.dbstate.db.get_person_from_handle(child_handle)
                    cname = escape(name_displayer.display(child))
                    if find_children(self.dbstate.db, child):
                        label = Gtk.Label(label="<b><i>%s</i></b>" % cname)
                    else:
                        label = Gtk.Label(label=cname)
                    label.set_use_markup(True)
                    label.show()
                    label.set_halign(Gtk.Align.START)
                    menuitem = Gtk.MenuItem()
                    menuitem.add(label)
                    self.my_menu.append(menuitem)
                    menuitem.connect(
                        "activate", self.cb_childmenu_changed, child_handle
                    )
                    menuitem.show()
                self.my_menu.popup_at_pointer(None)
            return 1
        return 0

    def cb_on_show_parent_menu(self, obj, person_handle) -> int:
        """Show a popup menu of parents for the given person."""
        from html import escape

        person = self.dbstate.db.get_person_from_handle(person_handle)
        if person:
            parentlist = find_parents(self.dbstate.db, person)
            if len(parentlist) == 1:
                parent = self.dbstate.db.get_person_from_handle(parentlist[0])
                if parent:
                    self.change_active(parentlist[0])
            elif len(parentlist) > 1:
                self.my_menu = Gtk.Menu()
                self.my_menu.set_reserve_toggle_size(False)
                for parent_handle in parentlist:
                    parent = self.dbstate.db.get_person_from_handle(parent_handle)
                    if not parent:
                        continue
                    pname = escape(name_displayer.display(parent))
                    if find_parents(self.dbstate.db, parent):
                        label = Gtk.Label(label="<b><i>%s</i></b>" % pname)
                    else:
                        label = Gtk.Label(label=pname)
                    label.set_use_markup(True)
                    label.show()
                    label.set_halign(Gtk.Align.START)
                    menuitem = Gtk.MenuItem()
                    menuitem.add(label)
                    self.my_menu.append(menuitem)
                    menuitem.connect(
                        "activate", self.cb_childmenu_changed, parent_handle
                    )
                    menuitem.show()
                self.my_menu.popup_at_pointer(None)
            return 1
        return 0

    def build_tree(self) -> None:
        """Build the descendant tree from the active person."""
        try:
            active_handle = self.get_active()
            if not active_handle:
                return

            if self.table is None:
                return

            for child in self.table.get_children():
                child.destroy()

            person = self.dbstate.db.get_person_from_handle(active_handle)
            if person:
                population_map: dict[int, list] = {}
                self.map_descendants(
                    person,
                    current_depth=0,
                    max_depth=self.tree_depth,
                    generation_dict=population_map,
                )
                self.render_rtl_grid(population_map)
            self.dirty = False
        except AttributeError as msg:
            RunDatabaseRepair(str(msg), parent=self.uistate.window)

    def map_descendants(
        self,
        person,
        current_depth: int,
        max_depth: int,
        generation_dict: dict,
        next_row: int = 0,
    ) -> int:
        """Recursively map descendants into a generation dictionary."""
        if current_depth >= max_depth or not person:
            return next_row

        if current_depth not in generation_dict:
            generation_dict[current_depth] = []

        spouses = []
        for family_handle in person.get_family_handle_list():
            family = self.dbstate.db.get_family_from_handle(family_handle)
            if family:
                orig_father = family.get_father_handle()
                orig_mother = family.get_mother_handle()
                spouse_handle = None
                if person.handle == orig_father and orig_mother:
                    spouse_handle = orig_mother
                elif person.handle == orig_mother and orig_father:
                    spouse_handle = orig_father
                if spouse_handle:
                    spouse_obj = self.dbstate.db.get_person_from_handle(
                        spouse_handle
                    )
                    if spouse_obj and spouse_obj not in spouses:
                        spouses.append(spouse_obj)

        current_node_row = next_row
        # Layout: [row, person, spouses, is_first, is_last]
        node_payload = [current_node_row, person, spouses, True, True]
        generation_dict[current_depth].append(node_payload)

        child_start_row = next_row
        child_nodes_in_family = []

        for family_handle in person.get_family_handle_list():
            family = self.dbstate.db.get_family_from_handle(family_handle)
            if family:
                valid_children = []
                for child_ref in family.get_child_ref_list():
                    child_person = self.dbstate.db.get_person_from_handle(
                        child_ref.ref
                    )
                    if child_person:
                        valid_children.append(child_person)

                for idx, child_person in enumerate(valid_children):
                    if idx > 0 or len(child_nodes_in_family) > 0:
                        next_row += 2

                    target_gen = current_depth + 1
                    if target_gen not in generation_dict:
                        generation_dict[target_gen] = []
                    target_list_idx = len(generation_dict[target_gen])

                    next_row = self.map_descendants(
                        child_person,
                        current_depth + 1,
                        max_depth,
                        generation_dict,
                        next_row,
                    )

                    is_first_sibling = (
                        idx == 0 and len(child_nodes_in_family) == 0
                    )
                    child_nodes_in_family.append(
                        (target_gen, target_list_idx, is_first_sibling)
                    )

        if child_nodes_in_family:
            for t_gen, t_idx, _t_first in child_nodes_in_family:
                generation_dict[t_gen][t_idx][3] = False
                generation_dict[t_gen][t_idx][4] = False

            first_gen, first_idx, _ = child_nodes_in_family[0]
            generation_dict[first_gen][first_idx][3] = True

            last_gen, last_idx, _ = child_nodes_in_family[-1]
            generation_dict[last_gen][last_idx][4] = True

            center_row = (child_start_row + next_row) // 2
            node_payload[0] = center_row

        return next_row

    def render_rtl_grid(self, population_map: dict) -> None:
        """Render the descendant tree into the GTK grid."""
        if not population_map:
            return

        max_seen_depth = max(population_map.keys())
        size_groups_by_column: dict[int, Gtk.SizeGroup] = {}
        # Offset columns by 1 to reserve column 0 for child nav buttons
        col_offset = 1

        # Step 1: Render all Person and Spouse boxes to establish columns
        for depth_level, people_nodes in population_map.items():
            grid_column = (max_seen_depth - depth_level) * 3 + col_offset

            if grid_column not in size_groups_by_column:
                size_groups_by_column[grid_column] = Gtk.SizeGroup(
                    mode=Gtk.SizeGroupMode.HORIZONTAL
                )
            column_size_group = size_groups_by_column[grid_column]

            for grid_row, person, spouses, _is_first, _is_last in people_nodes:
                family_container = Gtk.Box(
                    orientation=Gtk.Orientation.VERTICAL, spacing=2
                )
                family_container.set_margin_top(6)
                family_container.set_margin_bottom(6)

                is_alive = not person.get_death_ref()
                primary_box = PersonBoxWidgetCairo(
                    view=self,
                    format_helper=self.format_helper,
                    dbstate=self.dbstate,
                    person=person,
                    alive=is_alive,
                    maxlines=3,
                    image=self.show_images,
                    tags=self.show_tags,
                )
                family_container.pack_start(primary_box, False, False, 0)
                column_size_group.add_widget(primary_box)

                # Connect button-press for context menu and double-click edit
                fam_h = None
                for family_handle in person.get_family_handle_list():
                    fam = self.dbstate.db.get_family_from_handle(family_handle)
                    if fam:
                        fam_h = family_handle
                        break
                primary_box.connect(
                    "button-press-event",
                    self.cb_person_button_press,
                    person.get_handle(),
                    fam_h,
                )

                for spouse in spouses:
                    spouse_alive = not spouse.get_death_ref()
                    spouse_box = PersonBoxWidgetCairo(
                        view=self,
                        format_helper=self.format_helper,
                        dbstate=self.dbstate,
                        person=spouse,
                        alive=spouse_alive,
                        maxlines=3,
                        image=self.show_images,
                        tags=self.show_tags,
                    )
                    spouse_box.set_margin_top(10)
                    family_container.pack_start(spouse_box, False, False, 0)
                    column_size_group.add_widget(spouse_box)

                    # Connect button-press for spouse context menu
                    sp_fam_h = None
                    for family_handle in person.get_family_handle_list():
                        fam = self.dbstate.db.get_family_from_handle(
                            family_handle
                        )
                        if fam and (
                            fam.get_father_handle() == spouse.get_handle()
                            or fam.get_mother_handle() == spouse.get_handle()
                        ):
                            sp_fam_h = family_handle
                            break
                    spouse_box.connect(
                        "button-press-event",
                        self.cb_person_button_press,
                        spouse.get_handle(),
                        sp_fam_h,
                    )

                self.table.attach(
                    family_container, grid_column, grid_row, 1, 1
                )

                if depth_level < max_seen_depth:
                    outbound_stub = ParentOutboundLine(
                        num_spouses=len(spouses)
                    )
                    outbound_stub.set_vexpand(True)
                    outbound_stub.set_valign(Gtk.Align.FILL)
                    self.table.attach(
                        outbound_stub, grid_column - 1, grid_row, 1, 1
                    )

        # Step 2: Render continuous, gap-free vertical lines for siblings
        for depth_level in range(1, max_seen_depth + 1):
            grid_column = (max_seen_depth - depth_level) * 3 + col_offset
            current_generation_nodes = population_map[depth_level]

            sibling_groups = []
            current_group = []

            for node in current_generation_nodes:
                current_group.append(node)
                if node[4]:
                    sibling_groups.append(list(current_group))
                    current_group = []

            for group in sibling_groups:
                if not group:
                    continue

                start_row = group[0][0]
                end_row = group[-1][0]
                people_rows_map = {node[0]: node for node in group}

                for current_row in range(start_row, end_row + 1):
                    if current_row in people_rows_map:
                        node_data = people_rows_map[current_row]
                        is_first = node_data[3]
                        is_last = node_data[4]
                        has_spouse = len(node_data[2]) > 0

                        inbound_line = ChildInboundLine(
                            is_first_child=is_first,
                            is_last_child=is_last,
                            has_spouse=has_spouse,
                        )
                    else:
                        inbound_line = ChildInboundLine(
                            is_first_child=False,
                            is_last_child=False,
                            has_spouse=False,
                        )

                        def draw_plain_vertical(widget, context) -> bool:
                            alloc = widget.get_allocation()
                            context.set_source_rgb(0.0, 0.0, 0.0)
                            context.set_line_width(2)
                            context.move_to(alloc.width, 0)
                            context.line_to(alloc.width, alloc.height)
                            context.stroke()
                            return False

                        inbound_line.disconnect_by_func(inbound_line.draw_lines)
                        inbound_line.connect("draw", draw_plain_vertical)

                    inbound_line.set_vexpand(True)
                    inbound_line.set_valign(Gtk.Align.FILL)
                    self.table.attach(
                        inbound_line, grid_column + 1, current_row, 1, 1
                    )

        # Step 3: Add navigation arrow buttons
        active_handle = self.get_active()
        if active_handle:
            person = self.dbstate.db.get_person_from_handle(active_handle)
            if person:
                # Add parent navigation arrow on the right side of root.
                # Uses popup menu when multiple parents exist.  The button
                # box mirrors the family cell layout so each person/spouse
                # gets its own horizontally-aligned button.
                root_node = population_map[0][0]
                root_row = root_node[0]
                root_spouses = root_node[2]

                parent_button_box = Gtk.Box(
                    orientation=Gtk.Orientation.VERTICAL, spacing=2
                )
                parent_button_box.set_margin_top(6)
                parent_button_box.set_margin_bottom(6)

                # Primary person's parents
                parentlist = find_parents(self.dbstate.db, person)
                if parentlist:
                    button = Gtk.Button.new_from_icon_name(
                        "go-next-symbolic", Gtk.IconSize.BUTTON
                    )
                    button.set_size_request(24, 24)
                    button.connect(
                        "clicked",
                        self.cb_on_show_parent_menu,
                        active_handle,
                    )
                    button.set_tooltip_text(_("Jump to parent..."))
                    button.set_halign(Gtk.Align.CENTER)
                    button.set_valign(Gtk.Align.CENTER)
                    parent_button_box.pack_start(button, False, False, 0)

                # Spouses' parents
                for idx, spouse in enumerate(root_spouses):
                    spouse_parentlist = find_parents(
                        self.dbstate.db, spouse
                    )
                    if not spouse_parentlist:
                        continue
                    button = Gtk.Button.new_from_icon_name(
                        "go-next-symbolic", Gtk.IconSize.BUTTON
                    )
                    button.set_size_request(24, 24)
                    button.connect(
                        "clicked",
                        self.cb_on_show_parent_menu,
                        spouse.get_handle(),
                    )
                    button.set_tooltip_text(_("Jump to parent..."))
                    button.set_halign(Gtk.Align.CENTER)
                    button.set_valign(Gtk.Align.CENTER)
                    button.set_margin_top(10)
                    parent_button_box.pack_start(button, False, False, 0)

                if len(parent_button_box.get_children()) > 0:
                    self.table.attach(
                        parent_button_box,
                        (max_seen_depth * 3) + col_offset + 1,
                        root_row,
                        1,
                        1,
                    )

        # Add child navigation arrows on the left side of deepest persons.
        # Uses popup menu when multiple children exist.  The button column
        # mirrors the family cell layout so each person/spouse gets its own
        # horizontally-aligned button.
        deepest_nodes = population_map.get(max_seen_depth, [])
        for grid_row, person, spouses, _is_first, _is_last in deepest_nodes:
            # Button box matching the family container layout: one button
            # for the primary person and one for each spouse.
            button_box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=2
            )
            button_box.set_margin_top(6)
            button_box.set_margin_bottom(6)

            persons_handles = [person.get_handle()] + [
                spouse.get_handle() for spouse in spouses
            ]

            for idx, handle in enumerate(persons_handles):
                # Skip spouses without children
                if idx > 0:
                    person_obj = self.dbstate.db.get_person_from_handle(handle)
                    if not person_obj:
                        continue
                    childlist = find_children(self.dbstate.db, person_obj)
                else:
                    childlist = find_children(self.dbstate.db, person)

                if not childlist:
                    continue

                button = Gtk.Button.new_from_icon_name(
                    "go-previous-symbolic", Gtk.IconSize.BUTTON
                )
                button.set_size_request(24, 24)
                button.connect(
                    "clicked",
                    self.cb_on_show_child_menu,
                    handle,
                )
                button.set_tooltip_text(_("Jump to child..."))
                button.set_halign(Gtk.Align.CENTER)
                button.set_valign(Gtk.Align.CENTER)
                if idx > 0:
                    button.set_margin_top(10)
                button_box.pack_start(button, False, False, 0)

            if len(button_box.get_children()) > 0:
                self.table.attach(button_box, 0, grid_row, 1, 1)

        # Add a spacer in column 0 to ensure the column has visible width
        # even when no child navigation buttons are present.
        spacer = Gtk.Label()
        spacer.set_size_request(24, 1)
        self.table.attach(spacer, 0, 0, 1, 1)

        self.table.show_all()

    ####################################################################
    # Context menu and navigation
    ####################################################################
    def cb_home(self, menuitem) -> None:
        """Change root person to default person for database."""
        defperson = self.dbstate.db.get_default_person()
        if defperson:
            self.change_active(defperson.get_handle())

    def cb_set_home(self, menuitem, handle) -> None:
        """Set the root person to current person for database."""
        active = self.uistate.get_active("Person")
        if active:
            self.dbstate.db.set_default_person_handle(handle)
        self.cb_home(None)

    def cb_edit_person(self, obj, person_handle) -> bool:
        """Open edit person window for person_handle."""
        person = self.dbstate.db.get_person_from_handle(person_handle)
        if person:
            try:
                EditPerson(self.dbstate, self.uistate, [], person)
            except WindowActiveError:
                return True
            return True
        return False

    def cb_edit_family(self, obj, family_handle) -> bool:
        """Open edit family window for family_handle."""
        family = self.dbstate.db.get_family_from_handle(family_handle)
        if family:
            try:
                EditFamily(self.dbstate, self.uistate, [], family)
            except WindowActiveError:
                return True
            return True
        return False

    def cb_add_parents(self, obj, person_handle, family_handle) -> None:
        """Edit not full family."""
        if family_handle:
            family = self.dbstate.db.get_family_from_handle(family_handle)
        else:
            family = Family()
            childref = ChildRef()
            childref.set_reference_handle(person_handle)
            family.add_child_ref(childref)
        try:
            EditFamily(self.dbstate, self.uistate, [], family)
        except WindowActiveError:
            return

    def cb_copy_person_to_clipboard(self, obj, person_handle) -> bool:
        """Copy person data to clipboard."""
        person = self.dbstate.db.get_person_from_handle(person_handle)
        if person:
            clipboard = Gtk.Clipboard.get_for_display(
                Gdk.Display.get_default(), Gdk.SELECTION_CLIPBOARD
            )
            clipboard.set_text(
                self.format_helper.format_person(person, 11), -1
            )
            return True
        return False

    def cb_copy_family_to_clipboard(self, obj, family_handle) -> bool:
        """Copy family data to clipboard."""
        family = self.dbstate.db.get_family_from_handle(family_handle)
        if family:
            clipboard = Gtk.Clipboard.get_for_display(
                Gdk.Display.get_default(), Gdk.SELECTION_CLIPBOARD
            )
            clipboard.set_text(
                self.format_helper.format_relation(family, 11), -1
            )
            return True
        return False

    def cb_person_button_press(
        self, obj, event, person_handle, family_handle
    ) -> bool:
        """Handle button press on person box."""
        if is_right_click(event):
            self.cb_build_full_nav_menu(obj, event, person_handle, family_handle)
            return True
        elif event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS and event.button == 1:
            self.cb_edit_person(obj, person_handle)
            return True
        return True

    def cb_bg_button_press(self, widget, event) -> bool:
        """Enter scroll mode or show option menu on background press."""
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            widget.get_window().set_cursor(self.FLEUR_CURSOR)
            self._last_x = event.x
            self._last_y = event.y
            self._in_move = True
            return True
        elif is_right_click(event):
            self.cb_on_show_option_menu(widget, event)
            return True
        return False

    def cb_bg_button_release(self, widget, event) -> bool:
        """Exit scroll mode on button release."""
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_RELEASE:
            self.cb_bg_motion_notify_event(widget, event)
            widget.get_window().set_cursor(None)
            self._in_move = False
            return True
        return False

    def cb_bg_motion_notify_event(self, widget, event) -> bool:
        """Handle drag-scroll motion."""
        if self._in_move and (
            event.type == Gdk.EventType.MOTION_NOTIFY
            or event.type == Gdk.EventType.BUTTON_RELEASE
        ):
            window = widget.get_parent()
            hadjustment = window.get_hadjustment()
            vadjustment = window.get_vadjustment()
            self.update_scrollbar_positions(
                vadjustment,
                vadjustment.get_value() - (event.y - self._last_y),
            )
            self.update_scrollbar_positions(
                hadjustment,
                hadjustment.get_value() - (event.x - self._last_x),
            )
            return True
        return False

    def update_scrollbar_positions(self, adjustment, value) -> bool:
        """Control value then try setup in scrollbar."""
        if value > (adjustment.get_upper() - adjustment.get_page_size()):
            adjustment.set_value(
                adjustment.get_upper() - adjustment.get_page_size()
            )
        else:
            adjustment.set_value(value)
        return True

    def cb_on_show_option_menu(self, obj, event, data=None) -> bool:
        """Right click option menu on background."""
        self.menu = Gtk.Menu()
        self.menu.set_reserve_toggle_size(False)
        self.add_nav_portion_to_menu(self.menu, None)
        self.add_settings_to_menu(self.menu)
        self.menu.popup_at_pointer(event)
        return True

    def add_nav_portion_to_menu(self, menu, person_handle) -> None:
        """Add history-navigation portion to the context menu."""
        hobj = self.uistate.get_history(
            self.navigation_type(), self.navigation_group()
        )
        home_sensitivity = True
        if not self.dbstate.db.get_default_person():
            home_sensitivity = False
        entries = [
            (_("Pre_vious"), self.back_clicked, not hobj.at_front()),
            (_("_Next"), self.fwd_clicked, not hobj.at_end()),
            (_("_Home"), self.cb_home, home_sensitivity),
        ]

        for label, callback, sensitivity in entries:
            item = Gtk.MenuItem.new_with_mnemonic(label)
            item.set_sensitive(sensitivity)
            if callback:
                item.connect("activate", callback)
            item.show()
            menu.append(item)
        item = Gtk.MenuItem.new_with_mnemonic(_("Set _Home Person"))
        item.connect("activate", self.cb_set_home, person_handle)
        if person_handle is None:
            item.set_sensitive(False)
        item.show()
        menu.append(item)

    def add_settings_to_menu(self, menu) -> None:
        """Add settings to the context menu."""
        item = Gtk.SeparatorMenuItem()
        item.show()
        menu.append(item)

        item = Gtk.MenuItem(label=_("About Descendant View"))
        item.connect("activate", self.on_help_clicked)
        item.show()
        menu.append(item)

    def cb_build_full_nav_menu(
        self, obj, event, person_handle, family_handle
    ) -> int:
        """Build the full context menu for a person."""
        from html import escape

        self.menu = Gtk.Menu()
        self.menu.set_reserve_toggle_size(False)

        person = self.dbstate.db.get_person_from_handle(person_handle)
        if not person:
            return 0

        go_item = Gtk.MenuItem(label=name_displayer.display(person))
        go_item.connect("activate", self.cb_childmenu_changed, person_handle)
        go_item.show()
        self.menu.append(go_item)

        edit_item = Gtk.MenuItem.new_with_mnemonic(_("_Edit"))
        edit_item.connect("activate", self.cb_edit_person, person_handle)
        edit_item.show()
        self.menu.append(edit_item)

        clipboard_item = Gtk.MenuItem.new_with_mnemonic(_("_Copy"))
        clipboard_item.connect(
            "activate", self.cb_copy_person_to_clipboard, person_handle
        )
        clipboard_item.show()
        self.menu.append(clipboard_item)

        # Go over spouses and build their menu
        item = Gtk.MenuItem(label=_("Spouses"))
        fam_list = person.get_family_handle_list()
        no_spouses = 1
        for fam_id in fam_list:
            family = self.dbstate.db.get_family_from_handle(fam_id)
            if family.get_father_handle() == person.get_handle():
                sp_id = family.get_mother_handle()
            else:
                sp_id = family.get_father_handle()
            spouse = None
            if sp_id:
                spouse = self.dbstate.db.get_person_from_handle(sp_id)
            if not spouse:
                continue

            if no_spouses:
                no_spouses = 0
                item.set_submenu(Gtk.Menu())
                sp_menu = item.get_submenu()
                sp_menu.set_reserve_toggle_size(False)

            sp_item = Gtk.MenuItem(label=name_displayer.display(spouse))
            sp_item.connect("activate", self.cb_childmenu_changed, sp_id)
            sp_item.show()
            sp_menu.append(sp_item)

        if no_spouses:
            item.set_sensitive(0)
        item.show()
        self.menu.append(item)

        # Go over siblings and build their menu
        item = Gtk.MenuItem(label=_("Siblings"))
        pfam_list = person.get_parent_family_handle_list()
        no_siblings = 1
        for pfam in pfam_list:
            fam = self.dbstate.db.get_family_from_handle(pfam)
            sib_list = fam.get_child_ref_list()
            for sib_ref in sib_list:
                sib_id = sib_ref.ref
                if sib_id == person.get_handle():
                    continue
                sib = self.dbstate.db.get_person_from_handle(sib_id)
                if not sib:
                    continue

                if no_siblings:
                    no_siblings = 0
                    item.set_submenu(Gtk.Menu())
                    sib_menu = item.get_submenu()
                    sib_menu.set_reserve_toggle_size(False)

                if find_children(self.dbstate.db, sib):
                    label = Gtk.Label(
                        label="<b><i>%s</i></b>"
                        % escape(name_displayer.display(sib))
                    )
                else:
                    label = Gtk.Label(
                        label=escape(name_displayer.display(sib))
                    )

                sib_item = Gtk.MenuItem()
                label.set_use_markup(True)
                label.show()
                label.set_halign(Gtk.Align.START)
                sib_item.add(label)
                sib_item.connect("activate", self.cb_childmenu_changed, sib_id)
                sib_item.show()
                sib_menu.append(sib_item)

        if no_siblings:
            item.set_sensitive(0)
        item.show()
        self.menu.append(item)

        # Go over children and build their menu
        item = Gtk.MenuItem(label=_("Children"))
        no_children = 1
        childlist = find_children(self.dbstate.db, person)
        for child_handle in childlist:
            child = self.dbstate.db.get_person_from_handle(child_handle)
            if not child:
                continue

            if no_children:
                no_children = 0
                item.set_submenu(Gtk.Menu())
                child_menu = item.get_submenu()
                child_menu.set_reserve_toggle_size(False)

            if find_children(self.dbstate.db, child):
                label = Gtk.Label(
                    label="<b><i>%s</i></b>"
                    % escape(name_displayer.display(child))
                )
            else:
                label = Gtk.Label(
                    label=escape(name_displayer.display(child))
                )

            child_item = Gtk.MenuItem()
            label.set_use_markup(True)
            label.show()
            label.set_halign(Gtk.Align.START)
            child_item.add(label)
            child_item.connect(
                "activate", self.cb_childmenu_changed, child_handle
            )
            child_item.show()
            child_menu.append(child_item)

        if no_children:
            item.set_sensitive(0)
        item.show()
        self.menu.append(item)

        # Go over parents and build their menu
        item = Gtk.MenuItem(label=_("Parents"))
        no_parents = 1
        par_list = find_parents(self.dbstate.db, person)
        for par_id in par_list:
            par = None
            if par_id:
                par = self.dbstate.db.get_person_from_handle(par_id)
            if not par:
                continue

            if no_parents:
                no_parents = 0
                item.set_submenu(Gtk.Menu())
                par_menu = item.get_submenu()
                par_menu.set_reserve_toggle_size(False)

            if find_parents(self.dbstate.db, par):
                label = Gtk.Label(
                    label="<b><i>%s</i></b>"
                    % escape(name_displayer.display(par))
                )
            else:
                label = Gtk.Label(
                    label=escape(name_displayer.display(par))
                )

            par_item = Gtk.MenuItem()
            label.set_use_markup(True)
            label.show()
            label.set_halign(Gtk.Align.START)
            par_item.add(label)
            par_item.connect("activate", self.cb_childmenu_changed, par_id)
            par_item.show()
            par_menu.append(par_item)

        if no_parents:
            item.set_sensitive(0)
        item.show()
        self.menu.append(item)

        # Go over related (witnessed) people
        item = Gtk.MenuItem(label=_("Related"))
        no_related = 1
        for p_id in find_witnessed_people(self.dbstate.db, person):
            per = self.dbstate.db.get_person_from_handle(p_id)
            if not per:
                continue

            if no_related:
                no_related = 0
                item.set_submenu(Gtk.Menu())
                per_menu = item.get_submenu()
                per_menu.set_reserve_toggle_size(False)

            label = Gtk.Label(label=escape(name_displayer.display(per)))

            per_item = Gtk.MenuItem()
            label.set_use_markup(True)
            label.show()
            label.set_halign(Gtk.Align.START)
            per_item.add(label)
            per_item.connect("activate", self.cb_childmenu_changed, p_id)
            per_item.show()
            per_menu.append(per_item)

        if no_related:
            item.set_sensitive(0)
        item.show()
        self.menu.append(item)

        # Add separator line
        item = Gtk.SeparatorMenuItem()
        item.show()
        self.menu.append(item)

        # Add history-based navigation
        self.add_nav_portion_to_menu(self.menu, person_handle)
        self.add_settings_to_menu(self.menu)
        self.menu.popup_at_pointer(event)
        return 1

    ####################################################################
    # Configuration
    ####################################################################
    def config_connect(self) -> None:
        """Connect to config changes."""
        self._config.connect(
            "interface.descrtl-show-images", self.cb_update_show_images
        )
        self._config.connect(
            "interface.descrtl-show-tags", self.cb_update_show_tags
        )
        self._config.connect(
            "interface.descrtl-tree-size", self.cb_update_tree_size
        )

    def cb_update_show_tags(self, client, cnxn_id, entry, data) -> None:
        """Called when tags setting changes."""
        self.show_tags = entry == "True"
        self.build_tree()

    def cb_update_show_images(self, client, cnxn_id, entry, data) -> None:
        """Called when images setting changes."""
        self.show_images = entry == "True"
        self.build_tree()

    def cb_update_tree_size(self, client, cnxn_id, entry, data) -> None:
        """Called when tree size setting changes."""
        self.tree_depth = int(entry)
        self.build_tree()

    def _get_configure_page_funcs(self) -> list:
        """Return config page functions."""
        return [self.config_panel]

    def config_panel(self, configdialog):
        """Build the configuration dialog widget."""
        grid = Gtk.Grid()
        grid.set_border_width(12)
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)

        configdialog.add_checkbox(
            grid, _("Show images"), 0, "interface.descrtl-show-images"
        )
        configdialog.add_checkbox(
            grid, _("Show tags"), 1, "interface.descrtl-show-tags"
        )
        configdialog.add_slider(
            grid, _("Tree size"), 2, "interface.descrtl-tree-size", (2, 9)
        )

        return _("Layout"), grid