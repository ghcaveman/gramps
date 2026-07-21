# -*- python -*-
# -*- coding: utf-8 -*-
#
# File: descendantview.py
# Purpose: Descendant right-to-left view with self-aligning sibling connection brackets.

import math
from gi.repository import Gtk, Gdk

# Gramps Modules
from gramps.gen.lib import Family
from gramps.gui.views.navigationview import NavigationView
from gramps.gen.utils.libformatting import FormattingHelper
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gui.views.bookmarks import PersonBookmarks

# Localized layout string context
_ = glocale.translation.sgettext

# Re-use the custom box drawing classes from pedigreeview
from gramps.plugins.view.pedigreeview import PersonBoxWidgetCairo


class ParentOutboundLine(Gtk.DrawingArea):
    """
    Draws a vertical coupling backbone on the right side to join couples together,
    extending a single horizontal connector stub cleanly outward to the LEFT.
    """
    def __init__(self, num_spouses=0):
        Gtk.DrawingArea.__init__(self)
        self.num_spouses = num_spouses
        self.set_size_request(20, -1)
        self.connect("draw", self.draw_line)

    def draw_line(self, widget, context):
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


class ChildInboundLine(Gtk.DrawingArea):
    """
    Draws seamless, unbroken vertical tracking rails from the first sibling's 
    horizontal line down to the last sibling's horizontal line.
    """
    def __init__(self, is_first_child, is_last_child, has_spouse=False):
        Gtk.DrawingArea.__init__(self)
        self.is_first_child = is_first_child
        self.is_last_child = is_last_child
        self.has_spouse = has_spouse
        self.set_size_request(20, -1)
        self.connect("draw", self.draw_lines)

    def draw_lines(self, widget, context):
        alloc = self.get_allocation()
        context.set_source_rgb(0.0, 0.0, 0.0)
        context.set_line_width(2)
        
        spine_x = alloc.width
        
        # Calculate target Y center based on whether the sibling box contains a spouse
        target_y = 24 if self.has_spouse else (alloc.height / 2)

        # 1. Horizontal connector pin running into the right side of the child box
        context.move_to(spine_x, target_y)
        context.line_to(0, target_y)

        # 2. Continuous vertical sibling tracking rails (drawn from edge to edge)
        if not self.is_first_child:
            context.move_to(spine_x, target_y)
            context.line_to(spine_x, 0)
            
        if not self.is_last_child:
            context.move_to(spine_x, target_y)
            context.line_to(spine_x, alloc.height)

        context.stroke()
        return False


class DescendantView(NavigationView):
    """
    A view that displays descendants branching from right (root) to left (descendants),
    grouping spouses side-by-side inside family cells with zero line breaking gaps.
    """
    CONFIGSETTINGS = (
        ("interface.descrtl-tree-size", 4),
        ("interface.descrtl-show-images", True),
        ("interface.descrtl-show-tags", False),
    )

    def __init__(self, pdata, dbstate, uistate, nav_group=0):
        NavigationView.__init__(
            self, _("Descendant RTL"), pdata, dbstate, uistate, PersonBookmarks, nav_group
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

    def get_stock(self):
        return "gramps-pedigree"

    def navigation_type(self):
        return "Person"

    def build_widget(self):
        self.scrolledwindow = Gtk.ScrolledWindow()
        self.scrolledwindow.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.table = Gtk.Grid()
        self.table.set_direction(Gtk.TextDirection.LTR)
        self.scrolledwindow.add(self.table)
        self.table.set_row_spacing(0) # Zero out row spacing to completely resolve visual breaks
        self.table.set_column_spacing(0)
        return self.scrolledwindow

    def change_db(self, db):
        self._change_db(db)
        self.build_tree()

    def refresh_view(self, dummy=None):
        self.dirty = True
        self.build_tree()

    def goto_handle(self, handle=None):
        self.dirty = True
        self.build_tree()
        self.uistate.modify_statusbar(self.dbstate)

    def build_tree(self):
        active_handle = self.get_active()
        if not active_handle:
            return

        for child in self.table.get_children():
            child.destroy()

        person = self.dbstate.db.get_person_from_handle(active_handle)
        if person:
            population_map = {}
            self.map_descendants(person, current_depth=0, max_depth=self.tree_depth, generation_dict=population_map)
            self.render_rtl_grid(population_map)

    def map_descendants(self, person, current_depth, max_depth, generation_dict, next_row=0):
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
                    spouse_obj = self.dbstate.db.get_person_from_handle(spouse_handle)
                    if spouse_obj and spouse_obj not in spouses:
                        spouses.append(spouse_obj)

        current_node_row = next_row
        node_payload = [current_node_row, person, spouses, True, True] # Layout: [row, person, spouses, is_first, is_last]
        generation_dict[current_depth].append(node_payload)

        child_start_row = next_row
        child_nodes_in_family = []
        
        for family_handle in person.get_family_handle_list():
            family = self.dbstate.db.get_family_from_handle(family_handle)
            if family:
                valid_children = []
                for child_ref in family.get_child_ref_list():
                    child_person = self.dbstate.db.get_person_from_handle(child_ref.ref)
                    if child_person:
                        valid_children.append(child_person)
                
                total_children = len(valid_children)
                for idx, child_person in enumerate(valid_children):
                    if idx > 0 or len(child_nodes_in_family) > 0:
                        next_row += 2 # Clean padding rows between distinct sibling elements
                        
                    target_gen = current_depth + 1
                    if target_gen not in generation_dict:
                        generation_dict[target_gen] = []
                    target_list_idx = len(generation_dict[target_gen])
                    
                    next_row = self.map_descendants(
                        child_person, current_depth + 1, max_depth, generation_dict, next_row
                    )
                    
                    is_first_sibling = (idx == 0 and len(child_nodes_in_family) == 0)
                    child_nodes_in_family.append((target_gen, target_list_idx, is_first_sibling))

        # --- FIXED PAYLOAD INDEX ASSIGNMENTS ---
        if child_nodes_in_family:
            # 1. Reset all children in this specific family group to False by default
            for t_gen, t_idx, t_first in child_nodes_in_family:
                generation_dict[t_gen][t_idx][3] = False # is_first_child index
                generation_dict[t_gen][t_idx][4] = False # is_last_child index
            
            # 2. Explicitly flag the first child box in this family
            first_gen, first_idx, _ = child_nodes_in_family[0]
            generation_dict[first_gen][first_idx][3] = True
            
            # 3. Explicitly flag the last child box in this family
            last_gen, last_idx, _ = child_nodes_in_family[-1]
            generation_dict[last_gen][last_idx][4] = True
        # ----------------------------------------

            center_row = (child_start_row + next_row) // 2
            node_payload[0] = center_row

        return next_row

    def render_rtl_grid(self, population_map):
        if not population_map:
            return

        max_seen_depth = max(population_map.keys())
        size_groups_by_column = {}

        # Step 1: Render all Person and Spouse boxes to establish layout columns
        for depth_level, people_nodes in population_map.items():
            grid_column = (max_seen_depth - depth_level) * 3

            if grid_column not in size_groups_by_column:
                size_groups_by_column[grid_column] = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
            column_size_group = size_groups_by_column[grid_column]

            for grid_row, person, spouses, is_first_child, is_last_child in people_nodes:
                family_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                family_container.set_margin_top(6)
                family_container.set_margin_bottom(6)

                is_alive = not person.get_death_ref()
                primary_box = PersonBoxWidgetCairo(
                    view=self, format_helper=self.format_helper, dbstate=self.dbstate,
                    person=person, alive=is_alive, maxlines=3, image=self.show_images, tags=self.show_tags
                )
                family_container.pack_start(primary_box, False, False, 0)
                column_size_group.add_widget(primary_box)

                for spouse in spouses:
                    spouse_alive = not spouse.get_death_ref()
                    spouse_box = PersonBoxWidgetCairo(
                        view=self, format_helper=self.format_helper, dbstate=self.dbstate,
                        person=spouse, alive=spouse_alive, maxlines=3, image=self.show_images, tags=self.show_tags
                    )
                    spouse_box.set_margin_top(10)
                    family_container.pack_start(spouse_box, False, False, 0)
                    column_size_group.add_widget(spouse_box)

                # Attach the family container to the middle grid column
                self.table.attach(family_container, grid_column, grid_row, 1, 1)

                if depth_level < max_seen_depth:
                    outbound_stub = ParentOutboundLine(num_spouses=len(spouses))
                    outbound_stub.set_vexpand(True)
                    outbound_stub.set_valign(Gtk.Align.FILL)
                    self.table.attach(outbound_stub, grid_column - 1, grid_row, 1, 1)

        # Step 2: Render continuous, gap-free vertical lines for every sibling group
        for depth_level in range(1, max_seen_depth + 1):
            grid_column = (max_seen_depth - depth_level) * 3
            current_generation_nodes = population_map[depth_level]
            
            # Group nodes into their specific family groups
            sibling_groups = []
            current_group = []
            
            for node in current_generation_nodes:
                current_group.append(node)
                if node[4]: # If 'is_last_child' flag is true, close the group boundary
                    sibling_groups.append(list(current_group))
                    current_group = []

            for group in sibling_groups:
                if not group:
                    continue
                
                # Identify the boundary row range for this specific family group
                start_row = group[0][0]
                end_row = group[-1][0]
                
                # Make a quick lookup map of people rows within this family
                people_rows_map = {node[0]: node for node in group}

                # --- THE GAP-CLOSING COLUMN LOOP ---
                # Loop through EVERY single row coordinate from the first child to the last child.
                # This guarantees that empty rows caused by grandchild expansions are filled with lines.
                for current_row in range(start_row, end_row + 1):
                    
                    if current_row in people_rows_map:
                        # If a person exists on this row, render a line with a horizontal connector
                        node_data = people_rows_map[current_row]
                        is_first = node_data[3]
                        is_last = node_data[4]
                        has_spouse = len(node_data[2]) > 0
                        
                        inbound_line = ChildInboundLine(
                            is_first_child=is_first,
                            is_last_child=is_last,
                            has_spouse=has_spouse
                        )
                    else:
                        # If this row is empty space (pushed apart by grandchildren),
                        # render a plain vertical line to act as a seamless bridge
                        inbound_line = ChildInboundLine(
                            is_first_child=False,
                            is_last_child=False,
                            has_spouse=False
                        )
                        # Hide the horizontal connector line so it doesn't poke into empty space
                        # (We can force target_y out of bounds or draw a straight line)
                        inbound_line.has_spouse = False
                        
                        # Override drawing method to only draw a straight vertical line through the gap
                        def draw_plain_vertical(widget, context):
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
                    
                    # Attach the line widget to fill the column cell completely
                    self.table.attach(inbound_line, grid_column + 1, current_row, 1, 1)

        self.table.show_all()
        