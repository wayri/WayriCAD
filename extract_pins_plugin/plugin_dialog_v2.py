# plugin_dialog_v2.py 
"""
KiWay Pin Extractor modeless workspace

@author - Wayri (Yawar)
@version - 2.0.0
@date - 2025

Enhanced GUI with:
- Signal flow analysis
- IC signal chart generation
- SVG diagram export
- Power net grouping
- Improved filtering

THIS PLUGIN IS PROVIDED AS IS WITHOUT ANY GUARANTEE OR WARRANTY.
"""

import wx
import pcbnew
import csv
from io import StringIO
import os
import webbrowser
import re

try:
    import wx.html2 as wxhtml2
except ImportError:
    wxhtml2 = None

# Import core modules
try:
    from .core.data_extractor import DataExtractor
    from .core.signal_flow import SignalFlowAnalyzer
    from .core.formatters import get_formatter, MarkdownFormatter, CSVFormatter
    from .core.diagram_generator import SVGDiagramGenerator
except ImportError:
    # Fallback for direct execution
    from core.data_extractor import DataExtractor
    from core.signal_flow import SignalFlowAnalyzer
    from core.formatters import get_formatter, MarkdownFormatter, CSVFormatter
    from core.diagram_generator import SVGDiagramGenerator


class PluginDialogV2(wx.Frame):
    """
    Focused wxPython workspace for selection, extraction, and visualization.
    """

    def __init__(self, parent, initial_selected_footprints):
        super(PluginDialogV2, self).__init__(
            parent,
            title="KiWay Pin Extractor",
            size=(1120, 760),
            style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER,
        )
        
        self.board = pcbnew.GetBoard()
        self.extractor = DataExtractor(self.board)
        self.analyzer = SignalFlowAnalyzer(self.extractor)
        self.diagram_gen = SVGDiagramGenerator()
        
        self.current_display_footprints = []
        self.preview_footprints = []
        self.preview_data = {}
        self.preview_rows = []
        self.current_diagram_svg = ""
        self.all_refs = sorted([fp.GetReference() for fp in self.extractor.footprints], 
                               key=DataExtractor.natural_sort_key)
        self.all_ics = [r for r in self.all_refs if r.startswith('U')]
        
        # Auto-refresh timer for detecting new selections
        self.auto_refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnAutoRefreshTimer, self.auto_refresh_timer)
        self.last_known_selection = set()  # Track what we've already added
        
        self.InitUI()
        self._update_footprint_list_display(initial_selected_footprints)
        self.auto_refresh_timer.Start(500)
        
        # Initialize last known selection with initial footprints
        self.last_known_selection = {fp.GetReference() for fp in initial_selected_footprints}
        
        self.Centre()
        self.Bind(wx.EVT_CLOSE, self.OnClose)

    def InitUI(self):
        """Initialize the user interface with notebook tabs."""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Create notebook for tabs
        self.notebook = wx.Notebook(panel)
        
        # Keep the original extraction workflow first and separate visualization tasks.
        self.extract_panel = self._create_extract_tab()
        self.notebook.AddPage(self.extract_panel, "1  Extract Pins")
        
        # Tab 2: Signal Flow
        self.signal_flow_panel = self._create_signal_flow_tab()
        self.notebook.AddPage(self.signal_flow_panel, "2  Signal Flow")
        
        # Tab 3: IC Signal Chart
        self.ic_chart_panel = self._create_ic_chart_tab()
        self.notebook.AddPage(self.ic_chart_panel, "3  IC Signal Chart")
        
        # Tab 4: Diagrams
        self.diagram_panel = self._create_diagram_tab()
        self.notebook.AddPage(self.diagram_panel, "4  Block Diagrams")
        
        main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        
        # Status bar
        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.status_text = wx.StaticText(panel, label="Ready.")
        status_sizer.Add(self.status_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        self.progress_bar = wx.Gauge(panel, range=100, size=(200, 20))
        self.progress_bar.Hide()
        status_sizer.Add(self.progress_bar, 0, wx.ALL, 5)
        
        main_sizer.Add(status_sizer, 0, wx.EXPAND | wx.ALL, 2)
        
        # Bottom buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, self.OnHelp)
        button_sizer.Add(help_btn, 0, wx.ALL, 5)
        
        button_sizer.AddStretchSpacer()
        
        close_btn = wx.Button(panel, label="Close")
        close_btn.Bind(wx.EVT_BUTTON, self.OnClose)
        button_sizer.Add(close_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        panel.SetSizer(main_sizer)

    def _create_extract_tab(self):
        """Create the selection-aware extraction workspace."""
        panel = wx.Panel(self.notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(
            panel,
            label="Select components on the PCB, enter wildcard filters, or combine both. "
                  "Preview the exact pin rows before exporting.",
        )
        sizer.Add(intro, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        source_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="1. Choose components"), wx.VERTICAL)
        source_row = wx.BoxSizer(wx.HORIZONTAL)
        self.source_mode = wx.RadioBox(
            panel,
            label="Use",
            choices=("PCB selection", "Wildcard filters", "Selection + filters"),
            majorDimension=3,
            style=wx.RA_SPECIFY_COLS,
        )
        self.source_mode.SetSelection(2)
        self.source_mode.SetToolTip("Combined mode exports the union of the live PCB selection and wildcard matches.")
        source_row.Add(self.source_mode, 0, wx.RIGHT, 10)

        selection_box = wx.BoxSizer(wx.VERTICAL)
        live_row = wx.BoxSizer(wx.HORIZONTAL)
        self.auto_refresh_cb = wx.CheckBox(panel, label="Follow PCB selection")
        self.auto_refresh_cb.SetValue(True)
        self.auto_refresh_cb.SetToolTip("Keep this window open and click footprints in PCB Editor to add them here.")
        self.auto_refresh_cb.Bind(wx.EVT_CHECKBOX, self.OnAutoRefreshToggle)
        live_row.Add(self.auto_refresh_cb, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.auto_status = wx.StaticText(panel, label="Live")
        self.auto_status.SetForegroundColour(wx.Colour(31, 122, 78))
        live_row.Add(self.auto_status, 0, wx.ALIGN_CENTER_VERTICAL)
        selection_box.Add(live_row, 0, wx.BOTTOM, 4)

        selection_buttons = wx.BoxSizer(wx.HORIZONTAL)
        refresh_btn = wx.Button(panel, label="Refresh from PCB")
        refresh_btn.Bind(wx.EVT_BUTTON, self.OnRefreshSelection)
        selection_buttons.Add(refresh_btn, 0, wx.RIGHT, 6)
        remove_btn = wx.Button(panel, label="Remove")
        remove_btn.Bind(wx.EVT_BUTTON, self.OnRemoveSelectedFromList)
        selection_buttons.Add(remove_btn, 0, wx.RIGHT, 6)
        clear_btn = wx.Button(panel, label="Clear")
        clear_btn.Bind(wx.EVT_BUTTON, self.OnClearList)
        selection_buttons.Add(clear_btn, 0)
        selection_box.Add(selection_buttons, 0)
        source_row.Add(selection_box, 1, wx.ALIGN_CENTER_VERTICAL)
        source_box.Add(source_row, 0, wx.EXPAND | wx.ALL, 6)

        content_row = wx.BoxSizer(wx.HORIZONTAL)
        selected_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Selection basket"), wx.VERTICAL)
        self.footprint_list_ctrl = wx.ListCtrl(panel, size=(310, 145), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.footprint_list_ctrl.InsertColumn(0, "Reference", width=90)
        self.footprint_list_ctrl.InsertColumn(1, "Value", width=190)
        self.footprint_list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnListItemSelected)
        selected_box.Add(self.footprint_list_ctrl, 1, wx.EXPAND | wx.ALL, 4)
        self.details_text = wx.TextCtrl(panel, size=(-1, 58), style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.details_text.SetHint("Select a basket row to inspect and locate it on the PCB.")
        selected_box.Add(self.details_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        content_row.Add(selected_box, 1, wx.EXPAND | wx.RIGHT, 8)

        filter_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Wildcard filters (* and ?)"), wx.VERTICAL)
        grid = wx.FlexGridSizer(3, 2, 5, 8)
        grid.AddGrowableCol(1)
        grid.Add(wx.StaticText(panel, label="References"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.ref_filter = wx.TextCtrl(panel)
        self.ref_filter.SetValue("J*")
        self.ref_filter.SetToolTip("Comma-separated patterns, for example J*, U1, U2, P?.")
        grid.Add(self.ref_filter, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label="Net names"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.net_filter_ctrl = wx.ComboBox(panel, choices=sorted(self.extractor.all_nets)[:100])
        self.net_filter_ctrl.SetToolTip("Optional. Comma-separated wildcard patterns, for example CAN_*, 28V*.")
        grid.Add(self.net_filter_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label="Component value"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.value_filter_ctrl = wx.ComboBox(panel, choices=sorted(set(fp.GetValue() for fp in self.extractor.footprints)))
        self.value_filter_ctrl.SetToolTip("Optional wildcard filter for component values.")
        grid.Add(self.value_filter_ctrl, 1, wx.EXPAND)
        filter_box.Add(grid, 1, wx.EXPAND | wx.ALL, 5)
        preset = wx.Button(panel, label="Use connector preset (J*)")
        preset.Bind(wx.EVT_BUTTON, self.OnConnectorPreset)
        filter_box.Add(preset, 0, wx.LEFT | wx.BOTTOM, 5)
        content_row.Add(filter_box, 1, wx.EXPAND)
        source_box.Add(content_row, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer.Add(source_box, 0, wx.EXPAND | wx.ALL, 8)

        preview_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="2. Review extracted pins"), wx.VERTICAL)
        options_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ignore_unconnected_cb = wx.CheckBox(panel, label="Hide unconnected")
        self.ignore_power_cb = wx.CheckBox(panel, label="Hide power and ground")
        self.sort_by_type_cb = wx.CheckBox(panel, label="Group by net type")
        self.highlight_nets_cb = wx.CheckBox(panel, label="Highlight nets in Markdown")
        for control in (self.ignore_unconnected_cb, self.ignore_power_cb, self.sort_by_type_cb, self.highlight_nets_cb):
            options_sizer.Add(control, 0, wx.RIGHT, 14)
        options_sizer.AddStretchSpacer()
        preview_button = wx.Button(panel, label="Preview Extraction")
        preview_button.Bind(wx.EVT_BUTTON, self.OnPreviewExtraction)
        options_sizer.Add(preview_button, 0)
        preview_box.Add(options_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.pin_preview = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("Reference", 90), ("Value", 170), ("Pad", 70), ("Net", 270), ("Type", 90))):
            self.pin_preview.InsertColumn(index, label, width=width)
        self.pin_preview.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnPreviewRowActivated)
        preview_box.Add(self.pin_preview, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        self.preview_summary = wx.StaticText(panel, label="No preview yet. The PCB has not been changed.")
        preview_box.Add(self.preview_summary, 0, wx.ALL, 5)
        sizer.Add(preview_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        export_sizer = wx.BoxSizer(wx.HORIZONTAL)
        export_sizer.Add(wx.StaticText(panel, label="3. Export the reviewed rows"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.export_selected_btn = wx.Button(panel, label="Export Preview...")
        self.export_selected_btn.Bind(wx.EVT_BUTTON, self.OnExportPreview)
        self.export_selected_btn.Enable(False)
        export_sizer.Add(self.export_selected_btn, 0, wx.RIGHT, 6)
        export_nets_btn = wx.Button(panel, label="Export Unique Nets...")
        export_nets_btn.Bind(wx.EVT_BUTTON, self.OnExtractUniqueNets)
        export_sizer.Add(export_nets_btn, 0)
        sizer.Add(export_sizer, 0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(sizer)
        return panel

    def _create_signal_flow_tab(self):
        """Create the Signal Flow tab."""
        panel = wx.Panel(self.notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Source/Destination selection
        sel_sizer = wx.FlexGridSizer(2, 4, 5, 10)
        sel_sizer.AddGrowableCol(1)
        sel_sizer.AddGrowableCol(3)
        
        sel_sizer.Add(wx.StaticText(panel, label="Source:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.source_pattern = wx.TextCtrl(panel, value="J*")
        self.source_pattern.SetToolTip("Source components (wildcards: * ?)")
        sel_sizer.Add(self.source_pattern, 1, wx.EXPAND)
        
        sel_sizer.Add(wx.StaticText(panel, label="Destination:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.dest_pattern = wx.TextCtrl(panel, value="U*")
        self.dest_pattern.SetToolTip("Destination components (wildcards: * ?)")
        sel_sizer.Add(self.dest_pattern, 1, wx.EXPAND)
        
        sizer.Add(sel_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Options
        opt_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.sf_include_intermediates = wx.CheckBox(panel, label="Include Intermediates")
        opt_sizer.Add(self.sf_include_intermediates, 0, wx.ALL, 5)
        
        self.sf_include_power = wx.CheckBox(panel, label="Include Power Nets")
        opt_sizer.Add(self.sf_include_power, 0, wx.ALL, 5)
        
        sizer.Add(opt_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Preview area
        preview_sizer = wx.StaticBoxSizer(wx.StaticBox(panel, label="Preview"), wx.VERTICAL)
        self.sf_preview = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("Source", 110), ("Pin", 70), ("Net", 260), ("Destination", 120), ("Pin", 70), ("Type", 90))):
            self.sf_preview.InsertColumn(index, label, width=width)
        preview_sizer.Add(self.sf_preview, 1, wx.EXPAND | wx.ALL, 2)
        sizer.Add(preview_sizer, 1, wx.EXPAND | wx.ALL, 5)
        
        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        preview_btn = wx.Button(panel, label="Preview")
        preview_btn.Bind(wx.EVT_BUTTON, self.OnSignalFlowPreview)
        btn_sizer.Add(preview_btn, 0, wx.ALL, 5)
        
        export_csv_btn = wx.Button(panel, label="Export CSV")
        export_csv_btn.Bind(wx.EVT_BUTTON, lambda e: self.OnSignalFlowExport('csv'))
        btn_sizer.Add(export_csv_btn, 0, wx.ALL, 5)
        
        export_md_btn = wx.Button(panel, label="Export Markdown")
        export_md_btn.Bind(wx.EVT_BUTTON, lambda e: self.OnSignalFlowExport('md'))
        btn_sizer.Add(export_md_btn, 0, wx.ALL, 5)
        
        export_svg_btn = wx.Button(panel, label="Export SVG Diagram")
        export_svg_btn.Bind(wx.EVT_BUTTON, lambda e: self.OnSignalFlowExport('svg'))
        btn_sizer.Add(export_svg_btn, 0, wx.ALL, 5)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        
        panel.SetSizer(sizer)
        return panel

    def _create_ic_chart_tab(self):
        """Create the IC Signal Chart tab."""
        panel = wx.Panel(self.notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # IC selection
        sel_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sel_sizer.Add(wx.StaticText(panel, label="Select IC:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        self.ic_combo = wx.ComboBox(panel, choices=self.all_ics, style=wx.CB_DROPDOWN)
        if self.all_ics:
            self.ic_combo.SetValue(self.all_ics[0])
        sel_sizer.Add(self.ic_combo, 1, wx.ALL, 5)
        
        self.ic_include_power = wx.CheckBox(panel, label="Include Power Nets")
        sel_sizer.Add(self.ic_include_power, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        sizer.Add(sel_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Preview
        preview_sizer = wx.StaticBoxSizer(wx.StaticBox(panel, label="IC Pin Connections"), wx.VERTICAL)
        self.ic_preview = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("IC Pin", 90), ("Net", 260), ("Destination", 130), ("Dest Pin", 90), ("Type", 90))):
            self.ic_preview.InsertColumn(index, label, width=width)
        preview_sizer.Add(self.ic_preview, 1, wx.EXPAND | wx.ALL, 2)
        sizer.Add(preview_sizer, 1, wx.EXPAND | wx.ALL, 5)
        
        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        preview_btn = wx.Button(panel, label="Preview")
        preview_btn.Bind(wx.EVT_BUTTON, self.OnICChartPreview)
        btn_sizer.Add(preview_btn, 0, wx.ALL, 5)
        
        export_csv_btn = wx.Button(panel, label="Export CSV")
        export_csv_btn.Bind(wx.EVT_BUTTON, lambda e: self.OnICChartExport('csv'))
        btn_sizer.Add(export_csv_btn, 0, wx.ALL, 5)
        
        export_md_btn = wx.Button(panel, label="Export Markdown")
        export_md_btn.Bind(wx.EVT_BUTTON, lambda e: self.OnICChartExport('md'))
        btn_sizer.Add(export_md_btn, 0, wx.ALL, 5)
        
        export_svg_btn = wx.Button(panel, label="Export SVG Chart")
        export_svg_btn.Bind(wx.EVT_BUTTON, lambda e: self.OnICChartExport('svg'))
        btn_sizer.Add(export_svg_btn, 0, wx.ALL, 5)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        
        panel.SetSizer(sizer)
        return panel

    def _create_diagram_tab(self):
        """Create an embedded visual block-diagram workspace."""
        panel = wx.Panel(self.notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        controls = wx.StaticBoxSizer(wx.StaticBox(panel, label="Diagram scope"), wx.VERTICAL)
        scope_row = wx.BoxSizer(wx.HORIZONTAL)
        scope_row.Add(wx.StaticText(panel, label="Components"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.diagram_refs = wx.TextCtrl(panel, value="J*,U*")
        self.diagram_refs.SetToolTip("Comma-separated references or wildcards. Leave blank to use the extraction preview.")
        scope_row.Add(self.diagram_refs, 1, wx.RIGHT, 12)
        self.diagram_mode = wx.RadioBox(
            panel,
            label="Connections",
            choices=("Combined", "Signals only", "Power only"),
            majorDimension=3,
            style=wx.RA_SPECIFY_COLS,
        )
        scope_row.Add(self.diagram_mode, 0)
        controls.Add(scope_row, 0, wx.EXPAND | wx.ALL, 6)

        action_row = wx.BoxSizer(wx.HORIZONTAL)
        refresh = wx.Button(panel, label="Refresh Visual Preview")
        refresh.Bind(wx.EVT_BUTTON, self.OnDiagramPreview)
        action_row.Add(refresh, 0, wx.RIGHT, 6)
        use_extract = wx.Button(panel, label="Use Extraction Preview")
        use_extract.Bind(wx.EVT_BUTTON, self.OnUseExtractionForDiagram)
        action_row.Add(use_extract, 0, wx.RIGHT, 6)
        self.export_diagram_btn = wx.Button(panel, label="Export This SVG...")
        self.export_diagram_btn.Enable(False)
        self.export_diagram_btn.Bind(wx.EVT_BUTTON, self.OnExportDiagramPreview)
        action_row.Add(self.export_diagram_btn, 0)
        controls.Add(action_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        sizer.Add(controls, 0, wx.EXPAND | wx.ALL, 8)

        preview_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Visual preview"), wx.VERTICAL)
        if wxhtml2 is not None:
            self.diagram_preview = wxhtml2.WebView.New(panel)
            self.diagram_preview_is_web = True
        else:
            self.diagram_preview = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
            self.diagram_preview_is_web = False
        preview_box.Add(self.diagram_preview, 1, wx.EXPAND | wx.ALL, 4)
        self.diagram_summary = wx.StaticText(panel, label="Choose components and refresh the preview. No PCB objects are changed.")
        preview_box.Add(self.diagram_summary, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(preview_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        return panel

    # ==================== Event Handlers ====================
    
    def OnClose(self, event):
        # Stop timer before closing
        if self.auto_refresh_timer.IsRunning():
            self.auto_refresh_timer.Stop()
        self.Destroy()

    def OnHelp(self, event):
        plugin_dir = os.path.dirname(__file__)
        help_file = os.path.join(plugin_dir, "help.html")
        if os.path.exists(help_file):
            webbrowser.open_new_tab(f"file:///{help_file}")
        else:
            wx.MessageBox("Help file not found.", "Error", wx.OK | wx.ICON_ERROR)

    def OnAutoRefreshToggle(self, event):
        """Toggle auto-refresh timer on/off."""
        if self.auto_refresh_cb.IsChecked():
            # Start timer - check every 500ms
            self.auto_refresh_timer.Start(500)
            self.auto_status.SetLabel("(Active)")
            self.status_text.SetLabel("Auto-refresh enabled. Click components on PCB to add them.")
        else:
            self.auto_refresh_timer.Stop()
            self.auto_status.SetLabel("")
            self.status_text.SetLabel("Auto-refresh disabled.")

    def OnAutoRefreshTimer(self, event):
        """Timer callback - check for newly selected components."""
        try:
            # Get currently selected footprints from PCB
            currently_selected = {fp.GetReference(): fp 
                                  for fp in self.board.GetFootprints() if fp.IsSelected()}
            
            # Find new selections (not already in our list)
            existing_refs = {fp.GetReference() for fp in self.current_display_footprints}
            new_refs = set(currently_selected.keys()) - existing_refs
            
            if new_refs:
                # Add new components to list
                new_footprints = [currently_selected[ref] for ref in new_refs]
                all_footprints = list(self.current_display_footprints) + new_footprints
                
                # Sort and update
                all_footprints.sort(key=lambda fp: DataExtractor.natural_sort_key(fp.GetReference()))
                self._update_footprint_list_display(all_footprints)
                
                # Update status
                added_str = ", ".join(sorted(new_refs, key=DataExtractor.natural_sort_key))
                self.status_text.SetLabel(f"Added: {added_str}")
                
        except Exception as e:
            # Silently handle errors during auto-refresh
            pass

    def OnClearList(self, event):
        """Clear the component list."""
        self.current_display_footprints = []
        self._update_footprint_list_display([])
        self.last_known_selection = set()
        self.status_text.SetLabel("List cleared.")

    def _update_footprint_list_display(self, footprints_list):
        self.footprint_list_ctrl.DeleteAllItems()
        self.current_display_footprints = list(footprints_list)
        
        for i, fp in enumerate(self.current_display_footprints):
            self.footprint_list_ctrl.InsertItem(i, fp.GetReference())
            self.footprint_list_ctrl.SetItem(i, 1, fp.GetValue())
        
        self.details_text.SetValue("")

    def OnRefreshSelection(self, event):
        newly_selected = [f for f in self.board.GetFootprints() if f.IsSelected()]
        self._update_footprint_list_display(newly_selected)
        self.status_text.SetLabel(f"Found {len(self.current_display_footprints)} components.")

    def OnListItemSelected(self, event):
        idx = event.GetIndex()
        if idx < 0 or idx >= len(self.current_display_footprints):
            return
        
        fp = self.current_display_footprints[idx]
        pos = fp.GetPosition()
        rot = fp.GetOrientation()
        
        details = f"Reference: {fp.GetReference()}\n"
        details += f"Value: {fp.GetValue()}\n"
        details += f"Footprint: {fp.GetFPID()}\n"
        details += f"Layer: {fp.GetLayerName()}\n"
        details += f"Position: ({pos.x/1e6:.2f}mm, {pos.y/1e6:.2f}mm)\n"
        details += f"Rotation: {rot.AsDegrees():.1f}°\n"
        
        conn_type = self.extractor.get_footprint_property(fp, "connector-type")
        if conn_type:
            details += f"Connector Type: {conn_type}\n"
        
        details += f"\nPins: {len(list(fp.Pads()))}"
        self.details_text.SetValue(details)

        try:
            fp.SetSelected()
            pcbnew.Refresh()
            self.status_text.SetLabel(f"Selected {fp.GetReference()} on the PCB.")
        except Exception:
            pass

    def OnConnectorPreset(self, event):
        self.ref_filter.SetValue("J*")
        self.source_mode.SetSelection(1)
        self.OnPreviewExtraction(event)

    def _resolve_extract_scope(self):
        selected = {fp.GetReference(): fp for fp in self.current_display_footprints}
        pattern = self.ref_filter.GetValue().strip()
        matched = {
            fp.GetReference(): fp for fp in self._get_footprints_by_pattern(pattern)
        } if pattern else {}
        mode = self.source_mode.GetSelection()
        if mode == 0:
            footprints = selected
        elif mode == 1:
            footprints = matched
        else:
            footprints = dict(selected)
            footprints.update(matched)
        return sorted(footprints.values(), key=lambda fp: DataExtractor.natural_sort_key(fp.GetReference()))

    def OnPreviewExtraction(self, event):
        footprints = self._resolve_extract_scope()
        self.pin_preview.DeleteAllItems()
        self.preview_rows = []
        self.preview_footprints = footprints
        self.preview_data = self.extractor.extract_footprint_data(
            footprints,
            ignore_unconnected=self.ignore_unconnected_cb.IsChecked(),
            ignore_power_nets=self.ignore_power_cb.IsChecked(),
            value_filter=self.value_filter_ctrl.GetValue().strip() or None,
            net_filter=self.net_filter_ctrl.GetValue().strip() or None,
            sort_pins_by_net_type=self.sort_by_type_cb.IsChecked(),
        )
        for ref, component in self.preview_data.items():
            value = component.get("general_properties", {}).get("Value", "")
            for pin in component.get("pins", []):
                row = {
                    "Reference": ref,
                    "Value": value,
                    "Pad": pin.get("Pad Name/Number", ""),
                    "Net": pin.get("Net Name", ""),
                    "Type": pin.get("Net Type", ""),
                }
                self.preview_rows.append(row)
                index = self.pin_preview.InsertItem(self.pin_preview.GetItemCount(), row["Reference"])
                for column, key in enumerate(("Value", "Pad", "Net", "Type"), 1):
                    self.pin_preview.SetItem(index, column, str(row[key]))
        count = len(self.preview_rows)
        self.export_selected_btn.Enable(count > 0)
        self.preview_summary.SetLabel(
            f"Preview: {count} pin rows from {len(self.preview_data)} components. "
            "Double-click a row to select its footprint and highlight its net on the PCB."
            if count else
            "No rows match this scope. Adjust the source or filters and preview again."
        )
        self.status_text.SetLabel(f"Previewed {count} pin rows; the PCB was not changed.")

    def OnPreviewRowActivated(self, event):
        index = event.GetIndex()
        if index < 0 or index >= len(self.preview_rows):
            return
        row = self.preview_rows[index]
        footprint = self.extractor.get_footprint_by_reference(row["Reference"])
        try:
            for fp in self.board.GetFootprints():
                fp.ClearSelected()
            if footprint is not None:
                footprint.SetSelected()
            net = row.get("Net", "")
            if net and hasattr(self.board, "SetHighLightNet"):
                net_info = self.board.FindNet(net)
                if net_info:
                    self.board.SetHighLightNet(net_info.GetNetCode())
            pcbnew.Refresh()
            self.status_text.SetLabel(f"PCB selection: {row['Reference']} pad {row['Pad']} on {row['Net'] or 'no net'}.")
        except Exception as exc:
            self.status_text.SetLabel(f"Could not update PCB selection: {exc}")

    def OnExportPreview(self, event):
        if not self.preview_data:
            wx.MessageBox("Create a preview first.", "Preview required", wx.OK | wx.ICON_INFORMATION)
            return
        choices = ("CSV (.csv)", "Markdown (.md)")
        with wx.SingleChoiceDialog(self, "Choose an export format for the reviewed rows.", "Export Preview", choices) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            if dialog.GetSelection() == 0:
                content = CSVFormatter().format_component_data(self.preview_data)
                self._save_file(content, "CSV", "kiway_pin_preview.csv")
            else:
                content = MarkdownFormatter(highlight_nets=self.highlight_nets_cb.IsChecked()).format_component_data(self.preview_data)
                self._save_file(content, "Markdown", "kiway_pin_preview.md")

    def OnRemoveSelectedFromList(self, event):
        idx = self.footprint_list_ctrl.GetFirstSelected()
        if idx != wx.NOT_FOUND and idx < len(self.current_display_footprints):
            del self.current_display_footprints[idx]
            self._update_footprint_list_display(self.current_display_footprints)

    def _get_footprints_by_pattern(self, pattern: str):
        """Get footprints matching pattern(s)."""
        patterns = [p.strip() for p in pattern.split(',') if p.strip()]
        result = []
        for p in patterns:
            result.extend(self.extractor.get_footprints_by_reference_pattern(p))
        # Remove duplicates
        seen = set()
        unique = []
        for fp in result:
            ref = fp.GetReference()
            if ref not in seen:
                seen.add(ref)
                unique.append(fp)
        return unique

    def OnExportSelected(self, event):
        if not self.current_display_footprints:
            wx.MessageBox("No components selected.", "Info", wx.OK)
            return
        self._export_footprints(self.current_display_footprints, "selected")

    def OnExportJs(self, event):
        footprints = self._get_footprints_by_pattern("J*")
        if not footprints:
            wx.MessageBox("No 'J*' components found.", "Info", wx.OK)
            return
        self._export_footprints(footprints, "connectors")

    def OnExportByPattern(self, event):
        pattern = self.ref_filter.GetValue().strip()
        if not pattern:
            wx.MessageBox("Enter a reference pattern.", "Info", wx.OK)
            return
        
        footprints = self._get_footprints_by_pattern(pattern)
        if not footprints:
            wx.MessageBox(f"No components matching '{pattern}'.", "Info", wx.OK)
            return
        self._export_footprints(footprints, pattern.replace('*', '').replace('?', ''))

    def _export_footprints(self, footprints, name_prefix):
        """Export footprint data to CSV and Markdown."""
        self.status_text.SetLabel("Extracting data...")
        self.progress_bar.Show()
        self.progress_bar.SetValue(25)
        wx.Yield()
        
        data = self.extractor.extract_footprint_data(
            footprints,
            ignore_unconnected=self.ignore_unconnected_cb.IsChecked(),
            ignore_power_nets=self.ignore_power_cb.IsChecked(),
            value_filter=self.value_filter_ctrl.GetValue().strip() or None,
            net_filter=self.net_filter_ctrl.GetValue().strip() or None,
            sort_pins_by_net_type=self.sort_by_type_cb.IsChecked()
        )
        
        if not data:
            wx.MessageBox("No data found after filtering.", "Info", wx.OK)
            self.progress_bar.Hide()
            return
        
        self.progress_bar.SetValue(50)
        wx.Yield()
        
        # Generate CSV
        csv_formatter = CSVFormatter()
        csv_content = csv_formatter.format_component_data(data)
        
        self.progress_bar.SetValue(75)
        wx.Yield()
        
        # Generate Markdown
        md_formatter = MarkdownFormatter(highlight_nets=self.highlight_nets_cb.IsChecked())
        md_content = md_formatter.format_component_data(data)
        
        self.progress_bar.Hide()
        
        # Save files
        self._save_file(csv_content, "CSV", f"{name_prefix}_pins.csv")
        self._save_file(md_content, "Markdown", f"{name_prefix}_pins.md")
        
        self.status_text.SetLabel("Export complete.")

    def OnExtractUniqueNets(self, event):
        footprints = list(self.preview_footprints) or self._resolve_extract_scope()
        
        if not footprints:
            wx.MessageBox("No components are in the current extraction scope.", "Info", wx.OK)
            return
        
        nets = self.extractor.extract_unique_nets(
            footprints,
            ignore_power_nets=self.ignore_power_cb.IsChecked(),
            net_filter=self.net_filter_ctrl.GetValue().strip() or None,
            sort_by_type=self.sort_by_type_cb.IsChecked()
        )
        
        if not nets:
            wx.MessageBox("No nets found.", "Info", wx.OK)
            return
        
        csv_content = "Net Name\n" + "\n".join(nets)
        self._save_file(csv_content, "CSV", "unique_nets.csv")

    # Signal Flow handlers
    def OnSignalFlowPreview(self, event):
        src_pattern = self.source_pattern.GetValue().strip()
        dst_pattern = self.dest_pattern.GetValue().strip()
        
        if not src_pattern or not dst_pattern:
            wx.MessageBox("Enter source and destination patterns.", "Info", wx.OK)
            return
        
        sources = [fp.GetReference() for fp in self._get_footprints_by_pattern(src_pattern)]
        dests = [fp.GetReference() for fp in self._get_footprints_by_pattern(dst_pattern)]
        
        if not sources or not dests:
            wx.MessageBox("No matching components found.", "Info", wx.OK)
            return
        
        data = self.analyzer.generate_source_destination_table(
            sources, dests, 
            include_intermediates=self.sf_include_intermediates.IsChecked()
        )
        if not self.sf_include_power.IsChecked():
            data = [row for row in data if self.extractor.classify_net(row.get("Net Name", "")) == "signal"]
        
        self.sf_preview.DeleteAllItems()
        if not data:
            self.status_text.SetLabel("No matching connections found between source and destination.")
            return
        for entry in data:
            net_type = self.extractor.classify_net(entry.get("Net Name", ""))
            index = self.sf_preview.InsertItem(self.sf_preview.GetItemCount(), str(entry.get("Source Reference", "")))
            values = (entry.get("Source Pin", ""), entry.get("Net Name", ""), entry.get("Destination Reference", ""), entry.get("Destination Pin", ""), net_type)
            for column, value in enumerate(values, 1):
                self.sf_preview.SetItem(index, column, str(value))
        self.status_text.SetLabel(f"Previewed {len(data)} source-to-destination connections.")

    def OnSignalFlowExport(self, format_type):
        src_pattern = self.source_pattern.GetValue().strip()
        dst_pattern = self.dest_pattern.GetValue().strip()
        
        sources = [fp.GetReference() for fp in self._get_footprints_by_pattern(src_pattern)]
        dests = [fp.GetReference() for fp in self._get_footprints_by_pattern(dst_pattern)]
        
        data = self.analyzer.generate_source_destination_table(
            sources, dests,
            include_intermediates=self.sf_include_intermediates.IsChecked()
        )
        if not self.sf_include_power.IsChecked():
            data = [row for row in data if self.extractor.classify_net(row.get("Net Name", "")) == "signal"]
        
        if not data:
            wx.MessageBox("No data to export.", "Info", wx.OK)
            return
        
        if format_type == 'svg':
            content = self.diagram_gen.generate_signal_flow_diagram(
                data, title=f"Signal Flow: {src_pattern} → {dst_pattern}"
            )
            self._save_file(content, "SVG", "signal_flow.svg")
        else:
            formatter = get_formatter(format_type)
            content = formatter.format_signal_flow(data)
            ext = 'md' if format_type == 'md' else format_type
            self._save_file(content, format_type.upper(), f"signal_flow.{ext}")

    # IC Chart handlers
    def OnICChartPreview(self, event):
        ic_ref = self.ic_combo.GetValue().strip()
        if not ic_ref:
            wx.MessageBox("Select an IC.", "Info", wx.OK)
            return
        
        data = self.analyzer.generate_ic_signal_chart(
            ic_ref,
            include_power_nets=self.ic_include_power.IsChecked()
        )
        
        self.ic_preview.DeleteAllItems()
        if not data:
            self.status_text.SetLabel(f"No connection rows found for {ic_ref}.")
            return
        for entry in data:
            index = self.ic_preview.InsertItem(self.ic_preview.GetItemCount(), str(entry.get("IC Pin", "")))
            values = (entry.get("Net Name", ""), entry.get("Destination Reference", ""), entry.get("Destination Pin", ""), "power" if entry.get("Is Power Net") == "Yes" else "signal")
            for column, value in enumerate(values, 1):
                self.ic_preview.SetItem(index, column, str(value))
        self.status_text.SetLabel(f"Previewed {len(data)} connections for {ic_ref}.")

    def OnICChartExport(self, format_type):
        ic_ref = self.ic_combo.GetValue().strip()
        if not ic_ref:
            return
        
        data = self.analyzer.generate_ic_signal_chart(
            ic_ref,
            include_power_nets=self.ic_include_power.IsChecked()
        )
        
        if not data:
            wx.MessageBox("No data to export.", "Info", wx.OK)
            return
        
        if format_type == 'svg':
            ic_fp = self.extractor.get_footprint_by_reference(ic_ref)
            ic_value = ic_fp.GetValue() if ic_fp else ""
            content = self.diagram_gen.generate_ic_signal_chart(
                ic_ref, ic_value, data
            )
            self._save_file(content, "SVG", f"{ic_ref}_chart.svg")
        else:
            formatter = get_formatter(format_type)
            content = formatter.format_signal_flow(data)
            ext = 'md' if format_type == 'md' else format_type
            self._save_file(content, format_type.upper(), f"{ic_ref}_chart.{ext}")

    # Diagram handlers
    def OnUseExtractionForDiagram(self, event):
        refs = list(self.preview_data)
        if not refs:
            wx.MessageBox("Create an extraction preview first.", "Preview required", wx.OK | wx.ICON_INFORMATION)
            return
        self.diagram_refs.SetValue(",".join(refs))
        self.OnDiagramPreview(event)

    def _diagram_flow_rows(self, refs):
        if len(refs) == 1:
            rows = self.analyzer.generate_ic_signal_chart(refs[0], include_power_nets=True)
            return [{
                "Source Reference": refs[0],
                "Source Pin": row.get("IC Pin", ""),
                "Net Name": row.get("Net Name", ""),
                "Destination Reference": row.get("Destination Reference", ""),
                "Destination Value": row.get("Destination Value", ""),
                "Destination Pin": row.get("Destination Pin", ""),
                "Is Power Net": row.get("Is Power Net", "No"),
            } for row in rows]

        rows = self.analyzer.generate_source_destination_table(refs, refs)
        if not rows:
            rows = []
            for ref in refs:
                for row in self.analyzer.generate_ic_signal_chart(ref, include_power_nets=True):
                    rows.append({
                        "Source Reference": ref,
                        "Source Pin": row.get("IC Pin", ""),
                        "Net Name": row.get("Net Name", ""),
                        "Destination Reference": row.get("Destination Reference", ""),
                        "Destination Value": row.get("Destination Value", ""),
                        "Destination Pin": row.get("Destination Pin", ""),
                        "Is Power Net": row.get("Is Power Net", "No"),
                    })
        return rows

    def OnDiagramPreview(self, event):
        patterns = self.diagram_refs.GetValue().strip()
        footprints = self._get_footprints_by_pattern(patterns) if patterns else list(self.preview_footprints)
        refs = [fp.GetReference() for fp in footprints]
        if not refs:
            wx.MessageBox("Select components or enter reference patterns first.", "No diagram scope", wx.OK | wx.ICON_INFORMATION)
            return

        rows = self._diagram_flow_rows(refs)
        mode = self.diagram_mode.GetSelection()
        filtered = []
        for row in rows:
            is_power = self.extractor.classify_net(row.get("Net Name", "")) != "signal"
            row["Is Power Net"] = "Yes" if is_power else "No"
            if mode == 1 and is_power:
                continue
            if mode == 2 and not is_power:
                continue
            filtered.append(row)

        labels = ("Combined power and signal", "Signal", "Power and ground")
        self.current_diagram_svg = self.diagram_gen.generate_signal_flow_diagram(
            filtered,
            title=f"{labels[mode]} connections: {', '.join(refs[:6])}{'...' if len(refs) > 6 else ''}",
        )
        if self.diagram_preview_is_web:
            html = (
                "<!doctype html><meta charset='utf-8'><style>"
                "html,body{margin:0;background:#15191f;height:100%;overflow:auto}"
                "svg{display:block;max-width:100%;height:auto;margin:0 auto}"
                "</style>" + self.current_diagram_svg
            )
            self.diagram_preview.SetPage(html, "")
        else:
            self.diagram_preview.SetValue(
                f"Visual web preview is unavailable in this KiCad Python build.\n\n"
                f"{len(filtered)} connections are ready for SVG export."
            )
        self.export_diagram_btn.Enable(bool(filtered))
        self.diagram_summary.SetLabel(
            f"Preview: {len(filtered)} connections across {len(refs)} components. "
            "The displayed SVG is exactly what Export This SVG writes."
        )
        self.status_text.SetLabel(f"Rendered {len(filtered)} diagram connections in the plugin window.")

    def OnExportDiagramPreview(self, event):
        if not self.current_diagram_svg:
            wx.MessageBox("Refresh the visual preview first.", "Preview required", wx.OK | wx.ICON_INFORMATION)
            return
        self._save_file(self.current_diagram_svg, "SVG", "kiway_block_diagram.svg")

    def _save_file(self, content, format_name, default_name):
        """Show save dialog and write file."""
        wildcard = f"{format_name} files (*.{default_name.split('.')[-1]})|*.{default_name.split('.')[-1]}"
        
        with wx.FileDialog(
            self, f"Save {format_name}",
            wildcard=wildcard,
            defaultFile=default_name,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            
            path = dlg.GetPath()
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                wx.MessageBox(f"Saved: {path}", "Success", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Error: {e}", "Error", wx.OK | wx.ICON_ERROR)
