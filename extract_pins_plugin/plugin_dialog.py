# plugin_dialog.py 
"""
EXTRACT PINS PLUGIN

@author - Wayri (Yawar)
@version - 1.1.0
@date - 1-07-2025


ALLOWS USER TO EXTRACT ALL THE NET NAMES IN MARKDOWN OR CSV FORMAT FROM CONNECTORS LIKE J1, J2 ETC, OR USER SELECTIONS OR ANY COMPONENT
THE CONTROLS ALLOW FOR DEFINING CUSTOM TYPES OF CONNECTORS USING "CONNECTOR-TYPE" AND THEN USING SELECTION FILTER

THE EXPORTED DATA CAN BE VIEWED USING A MARKDOWN VIEWER

THIS PLUGIN IS PROVIDED AS IS WITHOUT ANY GUARANTEE OR WARRANTY.
"""

import wx
import pcbnew
import csv
from io import StringIO
import random
import os
import webbrowser
import re

class PluginDialog(wx.Dialog):
    """
    A non-modal wxPython dialog for the KiCad pin extraction plugin.
    Allows interaction with KiCad while the dialog is open.
    """

    def __init__(self, parent, initial_selected_footprints):
        """
        Initializes the dialog window.

        Args:
            parent: The parent wx.Window (can be None for a top-level dialog,
                    or pcbnew.GetBoard().GetParentWindow() for more strict parenting).
            initial_selected_footprints: A list of pcbnew.FOOTPRINT objects selected initially.
        """
        # --- Adjusted initial size for much more compact layout ---
        super(PluginDialog, self).__init__(parent, title="KiCad Pin Extractor", size=(750, 480)) # Significantly smaller
        print("DEBUG: PluginDialog __init__ called.")

        self.board = pcbnew.GetBoard()
        self.all_board_footprints = self.board.GetFootprints()

        self.all_values = sorted(list(set(fp.GetValue() for fp in self.all_board_footprints if fp.GetValue())))
        
        all_nets = set()
        all_connector_types = set()
        for fp in self.all_board_footprints:
            for pad in fp.Pads():
                net = pad.GetNet()
                if net:
                    all_nets.add(net.GetNetname())
            
            connector_type_val = self._get_footprint_property_safe(fp, "connector-type")
            if connector_type_val:
                all_connector_types.add(connector_type_val.strip())

        self.all_net_names = sorted(list(all_nets))
        self.all_connector_types = sorted(list(all_connector_types))

        self.current_display_footprints = []

        self.InitUI()

        self._update_footprint_list_display(initial_selected_footprints)

        self.Centre()
        self.Show()
        self.Bind(wx.EVT_CLOSE, self.OnClose)

    def InitUI(self):
        panel = wx.Panel(self)
        main_vbox = wx.BoxSizer(wx.VERTICAL)

        top_hbox = wx.BoxSizer(wx.HORIZONTAL)

        list_panel = wx.Panel(panel)
        list_vbox = wx.BoxSizer(wx.VERTICAL)

        list_vbox.Add(wx.StaticText(list_panel, label="Selected Components:"), 0, wx.ALL | wx.EXPAND, 2) # Reduced padding
        # --- Reduced height for ListCtrl ---
        self.footprint_list_ctrl = wx.ListCtrl(list_panel, size=(-1, 120), style=wx.LC_REPORT | wx.LC_NO_HEADER) 
        self.footprint_list_ctrl.InsertColumn(0, "Reference")
        self.footprint_list_ctrl.SetColumnWidth(0, 150)
        self.footprint_list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnListItemSelected)

        list_vbox.Add(self.footprint_list_ctrl, 0, wx.ALL | wx.EXPAND, 2) # Proportion 0, fixed height
        
        selection_control_hbox = wx.BoxSizer(wx.HORIZONTAL)

        self.multi_select_checkbox = wx.CheckBox(list_panel, label="Multi-select from PCB")
        self.multi_select_checkbox.SetToolTip("If checked, 'Refresh Selection' adds to list instead of replacing.")
        selection_control_hbox.Add(self.multi_select_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2) # Reduced padding

        refresh_button = wx.Button(list_panel, label="Refresh Selection from PCB")
        refresh_button.Bind(wx.EVT_BUTTON, self.OnRefreshSelection)
        selection_control_hbox.Add(refresh_button, 0, wx.ALL, 2) # Reduced padding

        remove_button = wx.Button(list_panel, label="Remove Selected from List")
        remove_button.Bind(wx.EVT_BUTTON, self.OnRemoveSelectedFromList)
        selection_control_hbox.Add(remove_button, 0, wx.ALL, 2) # Reduced padding

        list_vbox.Add(selection_control_hbox, 0, wx.EXPAND | wx.ALL, 2) # Reduced padding

        list_panel.SetSizer(list_vbox)
        top_hbox.Add(list_panel, 1, wx.EXPAND | wx.ALL, 2) # Proportion 1 for list panel

        details_panel = wx.Panel(panel)
        details_vbox = wx.BoxSizer(wx.VERTICAL)
        details_vbox.Add(wx.StaticText(details_panel, label="Selected Component Details:"), 0, wx.ALL | wx.EXPAND, 2) # Reduced padding
        # --- Reduced height for TextCtrl ---
        self.details_text_ctrl = wx.TextCtrl(details_panel, size=(-1, 120), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL) 
        details_vbox.Add(self.details_text_ctrl, 0, wx.ALL | wx.EXPAND, 2) # Proportion 0, fixed height
        details_panel.SetSizer(details_vbox)
        top_hbox.Add(details_panel, 1, wx.EXPAND | wx.ALL, 2) # Proportion 1 for details panel
        main_vbox.Add(top_hbox, 0, wx.EXPAND | wx.ALL, 2) # Proportion 0 for top_hbox, fixed height

        middle_hbox = wx.BoxSizer(wx.HORIZONTAL)

        filters_panel = wx.StaticBoxSizer(wx.StaticBox(panel, label="Filters (Apply to 'J's & 'Connectors' Exports)"),
                                           wx.VERTICAL)
        grid_filters = wx.GridSizer(3, 2, 2, 2) # Reduced gaps

        grid_filters.Add(wx.StaticText(filters_panel.GetStaticBox(), label="Value Filter (wildcard *):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.value_filter_ctrl = wx.ComboBox(filters_panel.GetStaticBox(), size=(120, -1), choices=self.all_values, style=wx.CB_DROPDOWN) # Reduced width
        grid_filters.Add(self.value_filter_ctrl, 0, wx.EXPAND)

        grid_filters.Add(wx.StaticText(filters_panel.GetStaticBox(), label="Net Name Filter (comma-sep, wildcard *):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.net_name_filter_ctrl = wx.ComboBox(filters_panel.GetStaticBox(), size=(120, -1), choices=self.all_net_names, style=wx.CB_DROPDOWN) # Reduced width
        grid_filters.Add(self.net_name_filter_ctrl, 0, wx.EXPAND)

        grid_filters.Add(wx.StaticText(filters_panel.GetStaticBox(), label="Connector Type Filter (comma-sep, wildcard *):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.connector_type_filter_ctrl = wx.ComboBox(filters_panel.GetStaticBox(), size=(120, -1), choices=self.all_connector_types, style=wx.CB_DROPDOWN) # Reduced width
        grid_filters.Add(self.connector_type_filter_ctrl, 0, wx.EXPAND)

        filters_panel.Add(grid_filters, 1, wx.EXPAND | wx.ALL, 2) # Reduced padding
        middle_hbox.Add(filters_panel, 1, wx.EXPAND | wx.ALL, 2) # Proportion 1 for filters panel

        options_panel = wx.StaticBoxSizer(wx.StaticBox(panel, label="Output Options"), wx.VERTICAL)

        self.highlight_nets_markdown_checkbox = wx.CheckBox(options_panel.GetStaticBox(), label="Highlight Same Nets in Markdown Output")
        options_panel.Add(self.highlight_nets_markdown_checkbox, 0, wx.ALL, 2) # Reduced padding

        self.sort_by_reference_checkbox = wx.CheckBox(options_panel.GetStaticBox(), label="Sort Components by Reference (A-Z)")
        options_panel.Add(self.sort_by_reference_checkbox, 0, wx.ALL, 2) # Reduced padding

        self.ignore_unconnected_pins_checkbox = wx.CheckBox(options_panel.GetStaticBox(), label="Ignore 'Unconnected' Pins (CSV)")
        self.ignore_unconnected_pins_checkbox.SetToolTip("If checked, pins with 'unconnected' net name are excluded from CSV.")
        options_panel.Add(self.ignore_unconnected_pins_checkbox, 0, wx.ALL, 2) # Reduced padding

        self.ignore_free_pins_checkbox = wx.CheckBox(options_panel.GetStaticBox(), label="Ignore Free Pins (CSV)")
        self.ignore_free_pins_checkbox.SetToolTip("If checked, pins with no assigned net are excluded from CSV.")
        options_panel.Add(self.ignore_free_pins_checkbox, 0, wx.ALL, 2) # Reduced padding

        self.output_column_checkboxes = {}
        column_checkbox_data = {
            "General Properties": ["Reference", "Value", "Footprint Name", "Description", "Layer", "Position", "Rotation",
                                   "Connector Type"],
            "Pin Details": ["Pad Name/Number", "Net Name"]
        }

        options_panel.Add(wx.StaticText(options_panel.GetStaticBox(), label="Select Output Columns:"), 0, wx.ALL, 2) # Reduced padding

        column_checkbox_hbox = wx.BoxSizer(wx.HORIZONTAL)
        
        for category, columns in column_checkbox_data.items():
            col_vbox = wx.BoxSizer(wx.VERTICAL)
            col_vbox.Add(wx.StaticText(options_panel.GetStaticBox(), label=f"{category}"), 0, wx.ALL, 1) # Reduced padding
            for col_name in columns:
                cb = wx.CheckBox(options_panel.GetStaticBox(), label=f"Include {col_name}")
                cb.SetValue(True)
                self.output_column_checkboxes[col_name] = cb
                col_vbox.Add(cb, 0, wx.ALL, 1) # Reduced padding
            column_checkbox_hbox.Add(col_vbox, 1, wx.EXPAND | wx.ALL, 2) # Proportion 1 for each column group
        
        options_panel.Add(column_checkbox_hbox, 1, wx.EXPAND | wx.ALL, 2) # Proportion 1 for column checkboxes
        middle_hbox.Add(options_panel, 1, wx.EXPAND | wx.ALL, 2) # Proportion 1 for options panel
        main_vbox.Add(middle_hbox, 1, wx.EXPAND | wx.ALL, 2) # Proportion 1 for middle_hbox


        progress_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.status_text = wx.StaticText(panel, label="Ready.")
        progress_sizer.Add(self.status_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
        self.progress_bar = wx.Gauge(panel, range=100, size=(150, 15), style=wx.GA_HORIZONTAL)
        self.progress_bar.Hide()
        progress_sizer.Add(self.progress_bar, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
        main_vbox.Add(progress_sizer, 0, wx.EXPAND | wx.ALL, 2)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.export_selected_button = wx.Button(panel, label="Export Selected")
        self.export_selected_button.Bind(wx.EVT_BUTTON, self.OnExportSelected)
        self.export_selected_button.Enable(False)
        button_sizer.Add(self.export_selected_button, 0, wx.ALL, 2)

        export_js_button = wx.Button(panel, label="Export 'J's")
        export_js_button.Bind(wx.EVT_BUTTON, self.OnExportJs)
        button_sizer.Add(export_js_button, 0, wx.ALL, 2)

        export_connectors_by_type_button = wx.Button(panel, label="Export Connectors (by Type)")
        export_connectors_by_type_button.Bind(wx.EVT_BUTTON, self.OnExportConnectorsByType)
        button_sizer.Add(export_connectors_by_type_button, 0, wx.ALL, 2)

        extract_unique_nets_button = wx.Button(panel, label="Extract Unique Connector Nets")
        extract_unique_nets_button.Bind(wx.EVT_BUTTON, self.OnExtractUniqueNets)
        button_sizer.Add(extract_unique_nets_button, 0, wx.ALL, 2)

        help_button = wx.Button(panel, label="Help")
        help_button.Bind(wx.EVT_BUTTON, self.OnHelp)
        button_sizer.Add(help_button, 0, wx.ALL, 2)

        cancel_button = wx.Button(panel, label="Close")
        cancel_button.Bind(wx.EVT_BUTTON, self.OnCancel)
        button_sizer.Add(cancel_button, 0, wx.ALL, 2)

        main_vbox.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 2)

        panel.SetSizer(main_vbox)
        main_vbox.Fit(self) # Let wx.Fit() make final adjustments based on contents

    def OnHelp(self, event):
        print("DEBUG: Help button clicked. Opening HTML Help.")
        
        plugin_dir = os.path.dirname(__file__)
        help_file_path = os.path.join(plugin_dir, "help_doc.html")
        
        if os.path.exists(help_file_path):
            try:
                webbrowser.open_new_tab(f"file:///{help_file_path}")
                print(f"DEBUG: Opened help file: {help_file_path}")
            except Exception as e:
                wx.MessageBox(f"Could not open help file in browser.\nError: {e}", "Error Opening Help", wx.OK | wx.ICON_ERROR)
                print(f"ERROR: Failed to open help file: {e}")
        else:
            wx.MessageBox(f"Help file not found: {help_file_path}", "Help File Missing", wx.OK | wx.ICON_ERROR)
            print(f"ERROR: Help file not found: {help_file_path}")

    def OnClose(self, event):
        print("DEBUG: Main Dialog OnClose event fired. Destroying dialog.")
        self.Destroy()

    def _update_footprint_list_display(self, footprints_list):
        self.footprint_list_ctrl.ClearAll()
        self.footprint_list_ctrl.InsertColumn(0, "Reference")
        self.footprint_list_ctrl.SetColumnWidth(0, 150)
        self.current_display_footprints = footprints_list

        for i, fp in enumerate(self.current_display_footprints):
            self.footprint_list_ctrl.InsertItem(i, fp.GetReference())
        
        self.details_text_ctrl.SetValue("")

        self.export_selected_button.Enable(bool(footprints_list))


    def OnRefreshSelection(self, event):
        """
        Event handler for the 'Refresh Selection from PCB' button.
        Gets the current selection from the KiCad PCB editor and updates the dialog's list.
        Applies 'multi' behavior if checkbox is selected.
        """
        print("DEBUG: OnRefreshSelection method called.")
        
        newly_selected_from_pcb = [f for f in self.board.GetFootprints() if f.IsSelected()]
        
        if self.multi_select_checkbox.IsChecked():
            print("DEBUG: Multi-select mode enabled. Merging selections.")
            existing_footprints_dict = {fp.GetReference(): fp for fp in self.current_display_footprints}
            
            for fp in newly_selected_from_pcb:
                existing_footprints_dict[fp.GetReference()] = fp
            
            merged_footprints_list = sorted(existing_footprints_dict.values(), key=lambda f: self._natural_sort_key(f.GetReference()))
            
            self._update_footprint_list_display(merged_footprints_list)
            wx.MessageBox(f"Merged selection. Added {len(newly_selected_from_pcb)} new items. Total: {len(merged_footprints_list)}.", 
                          "Selection Merged", wx.OK | wx.ICON_INFORMATION)
        else:
            print("DEBUG: Single-select mode. Replacing selections.")
            self._update_footprint_list_display(newly_selected_from_pcb)
            wx.MessageBox(f"Refreshed selection. Found {len(newly_selected_from_pcb)} selected components.", 
                          "Selection Refreshed", wx.OK | wx.ICON_INFORMATION)

    def OnListItemSelected(self, event):
        selected_index = event.GetIndex()
        if selected_index == wx.NOT_FOUND:
            self.details_text_ctrl.SetValue("")
            return

        selected_fp = self.current_display_footprints[selected_index]
        print(f"DEBUG: List item selected: {selected_fp.GetReference()}")

        props = self._get_footprint_properties_for_display(selected_fp)

        details_text = ""
        for prop_name, prop_value in props.items():
            details_text += f"{prop_name}: {prop_value}\n"

        self.details_text_ctrl.SetValue(details_text.strip())

    def OnRemoveSelectedFromList(self, event):
        """
        Event handler for the 'Remove Selected from List' button.
        Removes currently selected items from the dialog's ListCtrl and internal list.
        """
        print("DEBUG: OnRemoveSelectedFromList called.")
        items_to_remove_indices = []
        
        idx = self.footprint_list_ctrl.GetFirstSelected()
        while idx != wx.NOT_FOUND:
            items_to_remove_indices.append(idx)
            idx = self.footprint_list_ctrl.GetNextSelected(idx)
        
        if not items_to_remove_indices:
            wx.MessageBox("No items selected in the list to remove.", "No Selection", wx.OK | wx.ICON_INFORMATION)
            return

        new_current_display_footprints = []
        removed_count = 0
        for i in range(len(self.current_display_footprints)):
            if i not in items_to_remove_indices:
                new_current_display_footprints.append(self.current_display_footprints[i])
            else:
                removed_count += 1
        
        print(f"DEBUG: Removed {removed_count} items from the list.")
        self._update_footprint_list_display(new_current_display_footprints)
        wx.MessageBox(f"Removed {removed_count} item(s) from the list.", "Items Removed", wx.OK | wx.ICON_INFORMATION)

    def _natural_sort_key(self, text):
        """
        Helper for natural sorting (e.g., J1, J2, J10 instead of J1, J10, J2).
        """
        return [int(s) if s.isdigit() else s.lower() for s in re.split('([0-9]+)', text)]


    def _get_footprint_property_safe(self, footprint, prop_name):
        """
        Safely retrieves the value of a property from a footprint,
        by iterating its fields. Returns None if property not found.
        """
        for field in footprint.GetFields():
            if field.GetName() == prop_name:
                return field.GetText()
        return None

    def _get_footprint_properties_for_display(self, fp):
        properties = {}
        properties["Reference"] = fp.GetReference()
        properties["Value"] = fp.GetValue()

        footprint_id = fp.GetFPID()
        properties["Footprint Name"] = str(footprint_id)

        description = fp.GetLibDescription()
        properties["Description"] = description if description and description != "No description" else "N/A"

        properties["Layer"] = fp.GetLayerName()
        pos = fp.GetPosition()
        properties["Position (X, Y)"] = f"({pos.x / 1000000.0:.2f}mm, {pos.y / 1000000.0:.2f}mm)"
        rot = fp.GetOrientation()
        properties["Rotation"] = f"{rot.AsDegrees():.1f}°"

        connector_type_val = self._get_footprint_property_safe(fp, "connector-type")
        if connector_type_val is not None:
            properties["Connector Type"] = connector_type_val.strip()
        else:
            properties["Connector Type"] = "N/A (No 'connector-type' property)"

        return properties


    def OnExportSelected(self, event):
        print("DEBUG: OnExportSelected method called.")
        initial_footprints = list(self.current_display_footprints)
        self._process_and_export(initial_footprints, "selected_data.md", "selected_data.csv", "selected components")

    def OnExportJs(self, event):
        print("DEBUG: OnExportJs method called.")
        initial_footprints = list(self.all_board_footprints)
        # Apply wildcard matching for 'J*' references
        filtered_footprints = [f for f in initial_footprints if re.fullmatch(self._convert_wildcard_to_regex("J*"), f.GetReference().upper())]
        self._process_and_export(filtered_footprints, "js_components.md", "js_components.csv", "'J' components")

    def OnExportConnectorsByType(self, event):
        print("DEBUG: OnExportConnectorsByType method called.")
        initial_footprints = list(self.all_board_footprints)

        connector_type_filter_raw = self.connector_type_filter_ctrl.GetValue().strip()
        
        if not connector_type_filter_raw:
            wx.MessageBox("Please enter connector types (e.g., 'harness,backplane', or 'conn*') in the filter field.",
                          "Filter Required", wx.OK | wx.ICON_INFORMATION)
            return

        # Split by comma and convert each part to a regex pattern
        connector_type_patterns = [self._convert_wildcard_to_regex(t.strip().lower()) for t in connector_type_filter_raw.split(',') if t.strip()]

        filtered_footprints = []
        for fp in initial_footprints:
            fp_connector_type_val = self._get_footprint_property_safe(fp, "connector-type")
            if fp_connector_type_val is not None:
                fp_connector_type_val_lower = fp_connector_type_val.lower().strip()
                # Check if the footprint's connector type matches any of the patterns
                if any(re.fullmatch(pattern, fp_connector_type_val_lower) for pattern in connector_type_patterns):
                    filtered_footprints.append(fp)

        self._process_and_export(filtered_footprints, "connectors_by_type.md", "connectors_by_type.csv",
                                 "connectors by type")

    def OnExtractUniqueNets(self, event):
        print("DEBUG: OnExtractUniqueNets method called.")
        
        connectors_to_process = []
        if self.current_display_footprints:
            print("DEBUG: Extracting unique nets from currently displayed footprints.")
            connectors_to_process = list(self.current_display_footprints)
        else:
            print("DEBUG: No footprints displayed. Extracting unique nets from all 'connector-type' footprints on board.")
            for fp in self.all_board_footprints:
                if self._get_footprint_property_safe(fp, "connector-type") is not None:
                    connectors_to_process.append(fp)

        if not connectors_to_process:
            wx.MessageBox("No connectors found in current selection or on board with 'connector-type' property.", "No Connectors", wx.OK | wx.ICON_INFORMATION)
            return

        # Apply general text filters (Value, Net Name) to the connectors
        # Note: The net_name_filter_text is used here to filter the *footprints*
        # based on whether *any* of their pins match the filter.
        # The actual filtering of the *unique nets list* will happen after collection.
        filtered_connectors = self._apply_text_filters(connectors_to_process)

        if not filtered_connectors:
            wx.MessageBox("No connectors found after applying general text filters.", "No Unique Nets", wx.OK | wx.ICON_INFORMATION)
            return

        self.status_text.SetLabel(f"Extracting unique nets from {len(filtered_connectors)} connectors...")
        self.progress_bar.Show()
        self.progress_bar.SetValue(0)
        wx.Yield()

        unique_nets = set()
        total_pads_scanned = 0
        for i, fp in enumerate(filtered_connectors):
            self.progress_bar.SetValue(int((i / len(filtered_connectors)) * 50))
            wx.Yield()
            for pad in fp.Pads():
                total_pads_scanned += 1
                net = pad.GetNet()
                if net:
                    net_name = net.GetNetname()
                    
                    is_connected = bool(net)
                    current_net_name = net_name # Use net_name directly
                    is_unconnected_literal = (current_net_name.lower() == "unconnected")

                    skip_net = False
                    if self.ignore_unconnected_pins_checkbox.IsChecked() and is_unconnected_literal:
                        skip_net = True
                    if self.ignore_free_pins_checkbox.IsChecked() and not is_connected:
                        skip_net = True

                    if not skip_net:
                        unique_nets.add(net_name)

        # Apply wildcard filter to the collected unique nets
        net_name_filter_text = self.net_name_filter_ctrl.GetValue().strip()
        if net_name_filter_text:
            print(f"DEBUG: Applying wildcard filter '{net_name_filter_text}' to unique nets.")
            unique_nets = self._filter_nets_by_wildcard(unique_nets, net_name_filter_text)
            if not unique_nets:
                wx.MessageBox(f"No unique nets found matching '{net_name_filter_text}' after filtering.", "No Matching Unique Nets", wx.OK | wx.ICON_INFORMATION)
                self.status_text.SetLabel("No matching unique nets found.")
                self.progress_bar.Hide()
                return


        if not unique_nets:
            wx.MessageBox("No unique nets found on the selected/filtered connectors.", "No Unique Nets", wx.OK | wx.ICON_INFORMATION)
            self.status_text.SetLabel("No unique nets found.")
            self.progress_bar.Hide()
            return

        sorted_unique_nets = sorted(list(unique_nets), key=self._natural_sort_key)
        
        self.status_text.SetLabel(f"Generating unique nets CSV for {len(sorted_unique_nets)} nets...")
        self.progress_bar.SetValue(75)
        wx.Yield()

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Unique Net Name"])
        for net_name in sorted_unique_nets:
            writer.writerow([net_name])
        csv_content = output.getvalue()

        self.status_text.SetLabel("Showing save dialog...")
        self.progress_bar.Hide()
        wx.Yield()

        self.save_file_dialog(csv_content, "CSV Files (*.csv)|*.csv", "Save Unique Connector Nets", "unique_connector_nets.csv")

        self.status_text.SetLabel("Done.")
        self.progress_bar.SetValue(100)
        self.progress_bar.Hide()
        print(f"DEBUG: Unique nets extraction complete. Total unique nets: {len(sorted_unique_nets)}")

    def OnCancel(self, event):
        print("DEBUG: Close button clicked. Closing dialog.")
        self.Close()

    def _process_and_export(self, initial_footprints_list, default_md_name, default_csv_name, export_type_desc):
        """
        Consolidates filtering, extraction, generation, and saving for all export types.
        """
        self.status_text.SetLabel(f"Applying filters for {export_type_desc}...")
        self.progress_bar.Show()
        self.progress_bar.SetValue(0)
        self.progress_bar.SetRange(100)
        wx.Yield()

        filtered_footprints = self._apply_text_filters(initial_footprints_list)

        self.status_text.SetLabel(f"Extracting data for {len(filtered_footprints)} components...")
        self.progress_bar.SetValue(25)
        wx.Yield()

        extracted_data_by_footprint = self.extract_data(
            filtered_footprints,
            ignore_unconnected_pins_for_csv=self.ignore_unconnected_pins_checkbox.IsChecked(),
            ignore_free_pins_for_csv=self.ignore_free_pins_checkbox.IsChecked()
        )
        print(f"DEBUG: _process_and_export: extract_data completed. Found {len(extracted_data_by_footprint)} components.")

        if not extracted_data_by_footprint:
            wx.MessageBox(f"No pins found in the {export_type_desc} after filtering to export.", "No Pin Data",
                          wx.OK | wx.ICON_INFORMATION)
            self.status_text.SetLabel("No data found.")
            self.progress_bar.Hide()
            return

        if self.sort_by_reference_checkbox.IsChecked():
            print("DEBUG: Sorting components by reference for output.")
            sorted_refs = sorted(extracted_data_by_footprint.keys(),
                                 key=lambda k: self._natural_sort_key(extracted_data_by_footprint[k]['general_properties']['Reference']))
            ordered_extracted_data = {ref: extracted_data_by_footprint[ref] for ref in sorted_refs}
            extracted_data_by_footprint = ordered_extracted_data
        else:
            print("DEBUG: Outputting components in processed order.")

        apply_markdown_highlight = self.highlight_nets_markdown_checkbox.IsChecked()
        selected_columns = self._get_selected_columns()

        self.status_text.SetLabel("Generating Markdown content...")
        self.progress_bar.SetValue(50)
        wx.Yield()
        markdown_content = self.generate_markdown(extracted_data_by_footprint, apply_markdown_highlight,
                                                  selected_columns)

        self.status_text.SetLabel("Generating CSV content...")
        self.progress_bar.SetValue(75)
        wx.Yield()
        
        csv_content = ""
        try:
            csv_content = self.generate_csv(extracted_data_by_footprint, selected_columns)
            print(f"DEBUG: CSV content generated. Length: {len(csv_content)} bytes.")
        except Exception as e:
            print(f"ERROR: Exception during CSV generation: {e}")
            import traceback
            traceback.print_exc()
            wx.MessageBox(f"An error occurred during CSV generation:\n{e}", "CSV Generation Error", wx.OK | wx.ICON_ERROR)
            self.status_text.SetLabel("Error during CSV generation.")
            self.progress_bar.Hide()
            return

        self.status_text.SetLabel("Showing save dialogs...")
        self.progress_bar.Hide()
        wx.Yield()

        self.save_file_dialog(markdown_content, "Markdown Files (*.md)|*.md", "Save Pin Data (Markdown)",
                              default_md_name)
        self.save_file_dialog(csv_content, "CSV Files (*.csv)|*.csv", "Save Pin Data (CSV)", default_csv_name)

        self.status_text.SetLabel("Done.")
        self.progress_bar.SetValue(100)
        self.progress_bar.Hide()
        print("DEBUG: _perform_export: Export complete.")

    def _convert_wildcard_to_regex(self, pattern):
        """
        Converts a wildcard pattern (e.g., 'J*') into a regex pattern.
        Escapes special regex characters and replaces '*' with '.*'.
        """
        # Escape all special regex characters first
        escaped_pattern = re.escape(pattern)
        # Then replace the escaped '*' with '.*'
        regex_pattern = escaped_pattern.replace(r'\*', '.*')
        return regex_pattern

    def _filter_nets_by_wildcard(self, net_names_set, wildcard_pattern_string):
        """
        Filters a set of net names based on one or more comma-separated wildcard patterns.
        Returns a new set containing only matching net names.
        """
        if not wildcard_pattern_string:
            return net_names_set # No filter applied

        # Split the input string by comma and generate a list of regex patterns
        patterns = [self._convert_wildcard_to_regex(p.strip().lower()) for p in wildcard_pattern_string.split(',') if p.strip()]
        
        if not patterns: # If splitting results in an empty list (e.g., input was just ", ,")
            return net_names_set

        filtered_nets = set()
        for net_name in net_names_set:
            net_name_lower = net_name.lower()
            # Check if the net_name matches any of the provided patterns
            if any(re.fullmatch(pattern, net_name_lower) for pattern in patterns):
                filtered_nets.add(net_name)
        return filtered_nets

    def _apply_text_filters(self, footprints_list):
        """
        Applies Value and Net Name filters to a list of footprints, supporting wildcards.
        Returns a new filtered list.
        """
        filtered = list(footprints_list)

        value_filter_text = self.value_filter_ctrl.GetValue().strip()
        # Note: net_name_filter_text is used here for filtering footprints by pins,
        # and also later in OnExtractUniqueNets for filtering the final set of unique nets.
        net_name_filter_text = self.net_name_filter_ctrl.GetValue().strip()

        # Apply Value filter with wildcard support
        if value_filter_text:
            value_regex = self._convert_wildcard_to_regex(value_filter_text.lower())
            filtered = [fp for fp in filtered if re.fullmatch(value_regex, fp.GetValue().lower())]
            print(f"DEBUG: Applied Value filter '{value_filter_text}'. Found {len(filtered)} FPs.")

        # Apply Net Name filter (for footprints with *any* matching pin) with wildcard support
        # This filter is applied to the footprints themselves, not the final unique nets list yet.
        if net_name_filter_text:
            # For footprint-level filtering, we want to check if *any* of the comma-separated patterns match
            net_name_patterns_for_footprint_filter = [self._convert_wildcard_to_regex(p.strip().lower()) for p in net_name_filter_text.split(',') if p.strip()]
            
            if net_name_patterns_for_footprint_filter: # Only apply if there are valid patterns
                filtered_by_net = []
                for fp in filtered:
                    for pad in fp.Pads():
                        net = pad.GetNet()
                        if net:
                            net_name_lower = net.GetNetname().lower()
                            if any(re.fullmatch(pattern, net_name_lower) for pattern in net_name_patterns_for_footprint_filter):
                                filtered_by_net.append(fp)
                                break # Found a matching net for this footprint, move to next footprint
                filtered = filtered_by_net
                print(f"DEBUG: Applied Net Name filter (footprint-level) '{net_name_filter_text}'. Found {len(filtered)} FPs.")

        return filtered

    def _get_selected_columns(self):
        """
        Returns a list of column names that are checked by the user for output.
        """
        selected_cols = []
        # Adjusted all_possible_columns after removing Footprint Name from GUI/filters
        all_possible_columns = [
            "Reference", "Value", "Description", "Layer",
            "Position", "Rotation", "Connector Type",
            "Pad Name/Number", "Net Name", "Pins (Aggregated)" # Added aggregated pins for CSV
        ]

        for col_name in all_possible_columns:
            cb = self.output_column_checkboxes.get(col_name)
            if cb and cb.IsChecked():
                selected_cols.append(col_name)
        return selected_cols

    # extract_data now accepts pin filter flags
    def extract_data(self, footprints_to_process, ignore_unconnected_pins_for_csv=False, ignore_free_pins_for_csv=False):
        """
        Extracts relevant properties and pin details from the provided list of footprints.
        Applies pin filtering for CSV based on ignore_unconnected_pins_for_csv and ignore_free_pins_for_csv flags.
        Returns a dictionary organized by footprint reference designator.
        """
        extracted_data_by_footprint = {}
        total_footprints = len(footprints_to_process)
        for i, footprint in enumerate(footprints_to_process):
            if total_footprints > 0:
                self.progress_bar.SetValue(25 + int((i / total_footprints) * 25))
                wx.Yield()

            footprint_ref = footprint.GetReference()
            footprint_value = footprint.GetValue()

            footprint_id = footprint.GetFPID()
            footprint_full_name = str(footprint_id) # Still extract for internal use/details panel

            footprint_description = footprint.GetLibDescription()

            footprint_layer = footprint.GetLayerName()
            footprint_pos = footprint.GetPosition()
            footprint_rot = footprint.GetOrientation()

            connector_type_val = self._get_footprint_property_safe(footprint, "connector-type")
            if connector_type_val is None:
                connector_type_val = ""

            general_properties = {
                "Reference": footprint_ref,
                "Value": footprint_value,
                "Footprint Name": footprint_full_name, # Still included here for internal use/details
                "Description": footprint_description if footprint_description and footprint_description != "No description" else "N/A",
                "Layer": footprint_layer,
                "Position": f"({footprint_pos.x / 1000000.0:.2f}mm, {footprint_pos.y / 1000000.0:.2f}mm)",
                "Rotation": f"{footprint_rot.AsDegrees():.1f}°",
                "Connector Type": connector_type_val
            }

            pin_data_unfiltered = [] # This list holds all pins, used for Markdown
            filtered_pins_for_csv = [] # This list holds pins after CSV-specific filters
            # aggregated_pins_str is REMOVED from here, as it's built in generate_csv now

            for pad in footprint.Pads():
                pad_name = pad.GetPadName()
                net_name = ""
                net = pad.GetNet()
                
                is_connected = bool(net) # True if net object exists
                current_net_name = net.GetNetname() if is_connected else ""
                is_unconnected_literal = (current_net_name.lower() == "unconnected") # Check for literal "unconnected" string

                # Always add to unfiltered list for Markdown
                pin_data_unfiltered.append({
                    "Pad Name/Number": pad_name,
                    "Net Name": current_net_name
                })

                # Apply pin filters for CSV only
                skip_pin_for_csv = False
                if ignore_unconnected_pins_for_csv and is_unconnected_literal:
                    skip_pin_for_csv = True
                if ignore_free_pins_for_csv and not is_connected: # Only skip if it's truly free (no net)
                    skip_pin_for_csv = True

                if not skip_pin_for_csv:
                    filtered_pins_for_csv.append({
                        "Pad Name/Number": pad_name,
                        "Net Name": current_net_name
                    })
            
            extracted_data_by_footprint[footprint_ref] = {
                "general_properties": general_properties,
                "pin_data": pin_data_unfiltered, # Unfiltered list for Markdown output
                "filtered_pins_for_csv": filtered_pins_for_csv, # Filtered list for CSV
                # "aggregated_pins_str" is REMOVED from here
            }
        return extracted_data_by_footprint

    def generate_markdown(self, data_by_footprint, apply_highlight=False, selected_columns=None):
        markdown = "# Extracted Component Pin Data\n\n"

        if selected_columns is None:
            selected_columns = self._get_selected_columns()

        html_color_palette = [
            "#FF0000", "#008000", "#0000FF", "#FFA500", "#800080", "#00FFFF", "#FFC0CB", "#00FF7F", "#8B4513",
            "#A52A2A", "#6A5ACD", "#D2691E", "#4682B4", "#BDB76B", "#FFD700"
        ]
        net_colors_map = {}
        color_index = 0

        for ref, component_data in data_by_footprint.items():
            general_props = component_data["general_properties"]
            pin_data = component_data["pin_data"] # Markdown uses the unfiltered pin_data

            markdown += f"## Component: {ref}\n\n"

            general_headers_to_include = [col for col in selected_columns if col in general_props]
            if general_headers_to_include:
                markdown += "### General Properties\n\n"
                markdown += "| " + " | ".join(general_headers_to_include) + " |\n"
                markdown += "|:" + "---------|:---------".join([""] * len(general_headers_to_include)) + "|\n"

                row_values = []
                for header in general_headers_to_include:
                    if header == "Position":
                        row_values.append(general_props.get("Position (X, Y)", "N/A"))
                    elif header == "Rotation":
                        row_values.append(general_props.get("Rotation", "N/A"))
                    else: # This covers Reference, Value, Description, Layer, Connector Type, Footprint Name
                        row_values.append(str(general_props.get(header, "N/A")))
                markdown += "| " + " | ".join(row_values) + " |\n"
                markdown += "\n"

            pin_headers_to_include = [col for col in selected_columns if col in ["Pad Name/Number", "Net Name"]]
            if pin_data and pin_headers_to_include:
                markdown += "### Pin Details\n\n"
                markdown += "| " + " | ".join(pin_headers_to_include) + " |\n"
                markdown += "|:" + "----------------|:---------".join([""] * len(pin_headers_to_include)) + "|\n"

                for pin_row in pin_data:
                    row_values = []
                    for header in pin_headers_to_include:
                        val = pin_row.get(header, "N/A")
                        if header == "Net Name" and apply_highlight and val != "N/A" and val != "":
                            if val not in net_colors_map:
                                net_colors_map[val] = html_color_palette[color_index % len(html_color_palette)]
                                color_index += 1

                            display_val = f'<span style="color: {net_colors_map[val]};">{val}</span>'
                        else:
                            display_val = val

                        row_values.append(display_val)
                    markdown += "| " + " | ".join(row_values) + " |\n"
                markdown += "\n"
            elif pin_data and not pin_headers_to_include:
                markdown += "Pin details available but no pin columns selected.\n\n"
            else:
                markdown += "No pins found for this component.\n\n"

        return markdown

    def generate_csv(self, data_by_footprint, selected_columns=None):
        output = StringIO()
        writer = csv.writer(output)

        # Map display name to internal storage key for general properties
        general_prop_cols_map = {
            "Reference": "Reference", "Value": "Value", "Footprint Name": "Footprint Name",
            "Description": "Description", "Layer": "Layer",
            "Position": "Position (X, Y)", "Rotation": "Rotation",
            "Connector Type": "Connector Type"
        }
        
        # Fixed headers for the pin rows (as requested)
        pin_row_headers = ["Connector Name", "Pin Number", "Net Name"]

        for ref, component_data in data_by_footprint.items():
            general_props = component_data["general_properties"]
            filtered_pins_for_csv = component_data["filtered_pins_for_csv"] # Use the filtered pins

            # --- Write Connector Properties Section ---
            general_headers_to_include = [col for col in selected_columns if col in general_prop_cols_map]
            
            # Only write general properties section if general properties are selected OR if there are pins to list
            if general_headers_to_include or filtered_pins_for_csv:
                writer.writerow([f"Component: {ref}"]) # Section header for the component
                
                if general_headers_to_include: # Only write properties if columns are selected
                    # Write general properties as key-value pairs
                    for col_display_name in general_headers_to_include:
                        col_storage_name = general_prop_cols_map[col_display_name]
                        value = general_props.get(col_storage_name, "")
                        writer.writerow([col_display_name, value])
                # No blank row needed here as per request

            # --- Write Pin Details Section ---
            # Only write pin section if pin details are selected for output AND there are filtered pins
            if filtered_pins_for_csv and (("Pad Name/Number" in selected_columns) or ("Net Name" in selected_columns)):
                writer.writerow(pin_row_headers) # Write pin headers
                for pin_row in filtered_pins_for_csv:
                    # Ensure columns match the pin_row_headers order and content
                    row_data = [
                        general_props.get("Reference", ""), # Connector Name (Reference)
                        pin_row.get("Pad Name/Number", ""), # Pin Number
                        pin_row.get("Net Name", "") # Net Name
                    ]
                    writer.writerow(row_data)
                # No blank row needed here as per request

        return output.getvalue()

    def save_file_dialog(self, content, wildcard, title, default_filename):
        with wx.FileDialog(
                None,
                title,
                wildcard=wildcard,
                defaultFile=default_filename,
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as file_dialog:
            if file_dialog.ShowModal() == wx.ID_CANCEL:
                return

            pathname = file_dialog.GetPath()
            try:
                with open(pathname, 'w', encoding='utf-8') as f:
                    f.write(content)
                wx.MessageBox(f"File saved successfully to:\n{pathname}", "Success", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Error saving file:\n{e}", "Error", wx.OK | wx.ICON_ERROR)

