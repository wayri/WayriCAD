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
import re
from urllib.parse import unquote

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
    from .core.power_tree import PowerTreeAnalyzer, generate_power_tree_svg
    from .help_utils import open_help
except ImportError:
    # Fallback for direct execution
    from core.data_extractor import DataExtractor
    from core.signal_flow import SignalFlowAnalyzer
    from core.formatters import get_formatter, MarkdownFormatter, CSVFormatter
    from core.diagram_generator import SVGDiagramGenerator
    from core.power_tree import PowerTreeAnalyzer, generate_power_tree_svg
    from help_utils import open_help


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
        self.sf_rows = []
        self.ic_rows = []
        self.current_diagram_svg = ""
        self.current_ic_svg = ""
        self.power_tree_result = {"nodes": [], "edges": [], "issues": [], "roots": []}
        self.current_power_tree_svg = ""
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

        self.power_tree_panel = self._create_power_tree_tab()
        self.notebook.AddPage(self.power_tree_panel, "5  Power Tree & Net Rules")
        
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

        net_action_sizer = wx.BoxSizer(wx.HORIZONTAL)
        net_action_sizer.Add(wx.StaticText(panel, label="PCB net:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.net_action_combo = wx.ComboBox(
            panel,
            choices=sorted(self.extractor.all_nets, key=DataExtractor.natural_sort_key),
            style=wx.CB_DROPDOWN,
        )
        self.net_action_combo.SetToolTip("Choose any board net to highlight or select its routed copper.")
        net_action_sizer.Add(self.net_action_combo, 1, wx.RIGHT, 6)
        highlight_net_btn = wx.Button(panel, label="Highlight Net")
        highlight_net_btn.Bind(wx.EVT_BUTTON, self.OnHighlightChosenNet)
        net_action_sizer.Add(highlight_net_btn, 0, wx.RIGHT, 6)
        select_net_btn = wx.Button(panel, label="Select Copper")
        select_net_btn.Bind(wx.EVT_BUTTON, self.OnSelectChosenNet)
        net_action_sizer.Add(select_net_btn, 0, wx.RIGHT, 6)
        clear_net_btn = wx.Button(panel, label="Clear Highlight")
        clear_net_btn.Bind(wx.EVT_BUTTON, self.OnClearNetHighlight)
        net_action_sizer.Add(clear_net_btn, 0)
        preview_box.Add(net_action_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

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

        self.sf_consolidate = wx.CheckBox(panel, label="Consolidate repeated routes")
        self.sf_consolidate.SetValue(True)
        self.sf_consolidate.SetToolTip("Group many pad-to-pad rows into one source/net/destination route with pin lists.")
        opt_sizer.Add(self.sf_consolidate, 0, wx.ALL, 5)
        
        sizer.Add(opt_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Preview area
        preview_sizer = wx.StaticBoxSizer(wx.StaticBox(panel, label="Preview"), wx.VERTICAL)
        self.sf_preview = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((
            ("From", 120), ("Pins", 100), ("Net", 190), ("Class", 85),
            ("Protocol", 80), ("Via", 180), ("To", 120), ("Pins", 100),
            ("Path", 240), ("Links", 65),
        )):
            self.sf_preview.InsertColumn(index, label, width=width)
        self.sf_preview.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnSignalFlowRowActivated)
        preview_sizer.Add(self.sf_preview, 1, wx.EXPAND | wx.ALL, 2)
        self.sf_summary = wx.StaticText(panel, label="Preview a route to see explicit source, intermediate, and destination context.")
        preview_sizer.Add(self.sf_summary, 0, wx.EXPAND | wx.ALL, 4)
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
        
        # Table and visual chart are generated from the same rows.
        preview_sizer = wx.StaticBoxSizer(wx.StaticBox(panel, label="IC Pin Connections and Flow Chart"), wx.VERTICAL)
        ic_content = wx.BoxSizer(wx.HORIZONTAL)
        self.ic_preview = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((
            ("IC Pin", 80), ("Net", 180), ("Class", 80), ("Protocol", 75),
            ("Destination", 110), ("Dest Pin", 80), ("Destination Value", 160),
        )):
            self.ic_preview.InsertColumn(index, label, width=width)
        self.ic_preview.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnICChartRowActivated)
        ic_content.Add(self.ic_preview, 1, wx.EXPAND | wx.ALL, 2)
        if wxhtml2 is not None:
            self.ic_visual_preview = wxhtml2.WebView.New(panel)
            self.ic_visual_is_web = True
        else:
            self.ic_visual_preview = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
            self.ic_visual_is_web = False
        ic_content.Add(self.ic_visual_preview, 1, wx.EXPAND | wx.ALL, 2)
        preview_sizer.Add(ic_content, 1, wx.EXPAND)
        self.ic_summary = wx.StaticText(panel, label="Preview an IC to generate both the table and visual flow chart.")
        preview_sizer.Add(self.ic_summary, 0, wx.EXPAND | wx.ALL, 4)
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
            label="Diagram type",
            choices=("System map", "Signal flow", "Power flow"),
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
            self.diagram_preview.Bind(wxhtml2.EVT_WEBVIEW_NAVIGATING, self.OnDiagramNavigation)
        else:
            self.diagram_preview = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
            self.diagram_preview_is_web = False
        preview_box.Add(self.diagram_preview, 1, wx.EXPAND | wx.ALL, 4)
        self.diagram_summary = wx.StaticText(panel, label="Choose components and refresh the preview. No PCB objects are changed.")
        preview_box.Add(self.diagram_summary, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(preview_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        return panel

    def _create_power_tree_tab(self):
        """Create shared net rules and automatic power-tree workspace."""
        panel = wx.Panel(self.notebook)
        root = wx.BoxSizer(wx.VERTICAL)

        rules = wx.StaticBoxSizer(wx.StaticBox(panel, label="Shared Net Classification Rules"), wx.VERTICAL)
        grid = wx.FlexGridSizer(4, 2, 5, 8)
        grid.AddGrowableCol(1)
        rule_rows = (
            ("Power patterns", "power_patterns_ctrl", self.extractor.power_net_patterns),
            ("Supply patterns", "supply_patterns_ctrl", self.extractor.supply_net_patterns),
            ("Ground patterns", "ground_patterns_ctrl", self.extractor.ground_net_patterns),
            ("Force-signal patterns", "signal_patterns_ctrl", self.extractor.signal_net_patterns),
        )
        for label, attribute, values in rule_rows:
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control = wx.TextCtrl(panel, value=", ".join(values))
            control.SetToolTip("Comma, semicolon, or newline-separated wildcards. * and ? are supported.")
            setattr(self, attribute, control)
            grid.Add(control, 1, wx.EXPAND)
        rules.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        rule_actions = wx.BoxSizer(wx.HORIZONTAL)
        apply_rules = wx.Button(panel, label="Apply Rules")
        apply_rules.Bind(wx.EVT_BUTTON, self.OnApplyNetRules)
        rule_actions.Add(apply_rules, 0, wx.RIGHT, 6)
        build_tree = wx.Button(panel, label="Build Power Tree")
        build_tree.Bind(wx.EVT_BUTTON, self.OnBuildPowerTree)
        rule_actions.Add(build_tree, 0, wx.RIGHT, 6)
        self.export_power_tree_svg = wx.Button(panel, label="Export Tree SVG...")
        self.export_power_tree_svg.Enable(False)
        self.export_power_tree_svg.Bind(wx.EVT_BUTTON, self.OnExportPowerTreeSvg)
        rule_actions.Add(self.export_power_tree_svg, 0, wx.RIGHT, 6)
        self.export_power_tree_csv = wx.Button(panel, label="Export Tree CSV...")
        self.export_power_tree_csv.Enable(False)
        self.export_power_tree_csv.Bind(wx.EVT_BUTTON, self.OnExportPowerTreeCsv)
        rule_actions.Add(self.export_power_tree_csv, 0)
        rules.Add(rule_actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        root.Add(rules, 0, wx.EXPAND | wx.ALL, 8)

        splitter = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
        left = wx.Panel(splitter)
        right = wx.Panel(splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        result_tabs = wx.Notebook(left)
        self.power_net_list = wx.ListCtrl(result_tabs, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("Net", 190), ("Class", 85), ("Pads", 65), ("Voltage", 80))):
            self.power_net_list.InsertColumn(index, label, width=width)
        self.power_net_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnPowerNetRowActivated)
        result_tabs.AddPage(self.power_net_list, "Classified Nets")
        self.power_edge_list = wx.ListCtrl(result_tabs, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("From Rail", 150), ("Via", 80), ("Function", 105), ("To Rail", 150), ("Confidence", 105))):
            self.power_edge_list.InsertColumn(index, label, width=width)
        result_tabs.AddPage(self.power_edge_list, "Power Paths")
        self.power_issue_list = wx.ListCtrl(result_tabs, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("Severity", 75), ("Check", 150), ("Item", 90), ("Detail", 360))):
            self.power_issue_list.InsertColumn(index, label, width=width)
        result_tabs.AddPage(self.power_issue_list, "Checks")
        left_sizer.Add(result_tabs, 1, wx.EXPAND)
        left.SetSizer(left_sizer)

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        if wxhtml2 is not None:
            self.power_tree_preview = wxhtml2.WebView.New(right)
            self.power_tree_preview_is_web = True
        else:
            self.power_tree_preview = wx.TextCtrl(right, style=wx.TE_MULTILINE | wx.TE_READONLY)
            self.power_tree_preview_is_web = False
        right_sizer.Add(self.power_tree_preview, 1, wx.EXPAND)
        self.power_tree_summary = wx.StaticText(right, label="Apply classification rules, then build the inferred rail topology.")
        right_sizer.Add(self.power_tree_summary, 0, wx.EXPAND | wx.ALL, 5)
        right.SetSizer(right_sizer)
        splitter.SplitVertically(left, right, 545)
        splitter.SetMinimumPaneSize(280)
        root.Add(splitter, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(root)
        self._populate_net_classification_table()
        return panel

    # ==================== Event Handlers ====================
    
    def OnClose(self, event):
        # Stop timer before closing
        if self.auto_refresh_timer.IsRunning():
            self.auto_refresh_timer.Stop()
        self.Destroy()

    def OnHelp(self, event):
        open_help(self, "help.html")

    def _find_net_code(self, net_name):
        if not net_name:
            return None
        try:
            net_info = self.board.FindNet(net_name)
            if net_info is not None:
                if hasattr(net_info, "GetNetCode"):
                    return int(net_info.GetNetCode())
                if isinstance(net_info, int):
                    return net_info
        except Exception:
            pass
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                try:
                    net = pad.GetNet()
                    if net and str(net.GetNetname()) == net_name:
                        if hasattr(pad, "GetNetCode"):
                            return int(pad.GetNetCode())
                        return int(net.GetNetCode())
                except Exception:
                    continue
        for item in getattr(self.board, "GetTracks", lambda: [])():
            try:
                if str(item.GetNetname()) == net_name:
                    return int(item.GetNetCode())
            except Exception:
                continue
        return None

    def _highlight_net(self, net_name):
        code = self._find_net_code(net_name)
        if code is None:
            self.status_text.SetLabel(f"Net not found on the PCB: {net_name}")
            return False
        highlighted = False
        for method_name in ("SetHighLightNet", "SetHighlightNet", "HighlightNet"):
            method = getattr(self.board, method_name, None)
            if not callable(method):
                continue
            try:
                method(code)
                highlighted = True
                break
            except Exception:
                continue
        pcbnew.Refresh()
        if highlighted:
            self.net_action_combo.SetValue(net_name)
            self.status_text.SetLabel(f"Highlighted {net_name} (net code {code}) in PCB Editor.")
            return True
        self.status_text.SetLabel(f"KiCad did not expose a compatible net highlight method for {net_name}.")
        return False

    def _select_net_copper(self, net_name):
        code = self._find_net_code(net_name)
        if code is None:
            self.status_text.SetLabel(f"Net not found on the PCB: {net_name}")
            return 0
        selected = 0
        collections = [list(getattr(self.board, "GetTracks", lambda: [])())]
        try:
            collections.append(list(self.board.Zones()))
        except Exception:
            try:
                collections.append(list(self.board.GetZones()))
            except Exception:
                pass
        for collection in collections:
            for item in collection:
                try:
                    if hasattr(item, "ClearSelected"):
                        item.ClearSelected()
                    if int(item.GetNetCode()) == code and hasattr(item, "SetSelected"):
                        item.SetSelected()
                        selected += 1
                except Exception:
                    continue
        pcbnew.Refresh()
        self.net_action_combo.SetValue(net_name)
        self.status_text.SetLabel(f"Selected {selected} routed copper items on {net_name}.")
        return selected

    def OnHighlightChosenNet(self, event):
        net_name = self.net_action_combo.GetValue().strip()
        if net_name:
            self._highlight_net(net_name)

    def OnSelectChosenNet(self, event):
        net_name = self.net_action_combo.GetValue().strip()
        if net_name:
            self._select_net_copper(net_name)

    def OnClearNetHighlight(self, event):
        cleared = False
        for method_name in ("SetHighLightNet", "SetHighlightNet"):
            method = getattr(self.board, method_name, None)
            if callable(method):
                try:
                    method(-1)
                    cleared = True
                    break
                except Exception:
                    continue
        pcbnew.Refresh()
        self.status_text.SetLabel("Cleared PCB net highlight." if cleared else "No compatible highlight-clear method was available.")

    def OnApplyNetRules(self, event):
        self.extractor.configure_net_patterns(
            power_net_patterns=DataExtractor.parse_pattern_text(self.power_patterns_ctrl.GetValue()),
            signal_net_patterns=DataExtractor.parse_pattern_text(self.signal_patterns_ctrl.GetValue()),
            ground_net_patterns=DataExtractor.parse_pattern_text(self.ground_patterns_ctrl.GetValue()),
            supply_net_patterns=DataExtractor.parse_pattern_text(self.supply_patterns_ctrl.GetValue()),
        )
        self._populate_net_classification_table()
        self.power_tree_result = {"nodes": [], "edges": [], "issues": [], "roots": []}
        self.current_power_tree_svg = ""
        self.export_power_tree_svg.Enable(False)
        self.export_power_tree_csv.Enable(False)
        self.status_text.SetLabel("Applied shared net rules to extraction, signal flow, IC charts, diagrams, and power-tree analysis.")

    def _populate_net_classification_table(self):
        if not hasattr(self, "power_net_list"):
            return
        self.power_net_list.DeleteAllItems()
        pad_map = self.extractor.get_net_to_pads_map()
        for net_name in sorted(self.extractor.all_nets, key=DataExtractor.natural_sort_key):
            net_type = self.extractor.classify_net(net_name)
            voltage = PowerTreeAnalyzer.parse_voltage(net_name)
            index = self.power_net_list.InsertItem(self.power_net_list.GetItemCount(), str(net_name))
            self.power_net_list.SetItem(index, 1, net_type)
            self.power_net_list.SetItem(index, 2, str(len(pad_map.get(net_name, []))))
            self.power_net_list.SetItem(index, 3, f"{voltage:g} V" if voltage is not None else "")
            colors = {"ground": "#d9e1e8", "supply": "#ffe0a6", "power": "#ffd0c7", "signal": "#ffffff"}
            self.power_net_list.SetItemBackgroundColour(index, colors.get(net_type, "#ffffff"))
            self.power_net_list.SetItemTextColour(index, "#202124")

    def OnPowerNetRowActivated(self, event):
        net_name = self.power_net_list.GetItemText(event.GetIndex())
        self.net_action_combo.SetValue(net_name)
        self._highlight_net(net_name)

    def OnBuildPowerTree(self, event):
        self.OnApplyNetRules(event)
        self.power_tree_result = PowerTreeAnalyzer(self.extractor).analyze()
        self.current_power_tree_svg = generate_power_tree_svg(self.power_tree_result)
        self.power_edge_list.DeleteAllItems()
        for edge in self.power_tree_result["edges"]:
            index = self.power_edge_list.InsertItem(self.power_edge_list.GetItemCount(), str(edge["Source Net"]))
            for column, key in enumerate(("Component", "Function", "Destination Net", "Confidence"), 1):
                self.power_edge_list.SetItem(index, column, str(edge.get(key, "")))
        self.power_issue_list.DeleteAllItems()
        severity_colors = {"Error": "#ffc7c7", "Warning": "#ffe4b5", "Info": "#d9ecf5"}
        for issue in self.power_tree_result["issues"]:
            index = self.power_issue_list.InsertItem(self.power_issue_list.GetItemCount(), str(issue["Severity"]))
            for column, key in enumerate(("Category", "Item", "Detail"), 1):
                self.power_issue_list.SetItem(index, column, str(issue.get(key, "")))
            self.power_issue_list.SetItemBackgroundColour(index, severity_colors.get(issue["Severity"], "#ffffff"))
            self.power_issue_list.SetItemTextColour(index, "#202124")
        if self.power_tree_preview_is_web:
            self.power_tree_preview.SetPage(self._svg_html(self.current_power_tree_svg), "")
        else:
            self.power_tree_preview.SetValue(
                f"Power tree visual preview requires wx.html2.\n\n"
                f"{len(self.power_tree_result['nodes'])} rails, {len(self.power_tree_result['edges'])} paths, "
                f"{len(self.power_tree_result['issues'])} findings are ready for export."
            )
        self.export_power_tree_svg.Enable(True)
        self.export_power_tree_csv.Enable(True)
        self.power_tree_summary.SetLabel(
            f"{len(self.power_tree_result['nodes'])} rails | {len(self.power_tree_result['edges'])} conversion/filter paths | "
            f"{len(self.power_tree_result['issues'])} findings | roots: {', '.join(self.power_tree_result['roots']) or 'none'}"
        )
        self.status_text.SetLabel("Built the inferred PCB power tree and completed topology checks.")

    @staticmethod
    def _svg_html(svg):
        return (
            "<!doctype html><meta charset='utf-8'><style>"
            "html,body{margin:0;background:#15191d;height:100%;overflow:auto}"
            "svg{display:block;min-width:900px;width:100%;height:auto;margin:0 auto}"
            "</style>" + svg
        )

    @staticmethod
    def _interactive_svg_html(svg):
        """Wrap an SVG in a picture-like pan/zoom viewport."""
        return """<!doctype html><meta charset="utf-8"><style>
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#15191d;color:#eef2f6;font:13px Segoe UI,sans-serif}
#toolbar{position:fixed;z-index:5;right:12px;top:10px;display:flex;gap:4px;padding:5px;background:#202630;border:1px solid #657080;border-radius:5px;box-shadow:0 2px 8px #0008}
#toolbar button{width:38px;height:30px;border:1px solid #6f7b89;background:#303844;color:#fff;border-radius:3px;font-size:15px;cursor:pointer}
#toolbar button.fit{width:48px;font-size:12px}#toolbar button:hover{background:#435064}
#stage{position:absolute;inset:0;overflow:auto;cursor:grab;user-select:none;padding:8px;box-sizing:border-box}
#stage.dragging{cursor:grabbing}#host{transform-origin:0 0;width:max-content;height:max-content}svg{display:block;max-width:none;height:auto}
</style><div id="toolbar"><button title="Zoom out" onclick="zoomBy(0.8)">-</button><button title="Zoom in" onclick="zoomBy(1.25)">+</button><button class="fit" title="Fit diagram" onclick="fitView()">Fit</button><button class="fit" title="Actual size" onclick="setScale(1)">100%</button></div><div id="stage"><div id="host">""" + svg + """</div></div><script>
const stage=document.getElementById('stage'),host=document.getElementById('host'),svg=host.querySelector('svg');
const vb=(svg.getAttribute('viewBox')||'0 0 1200 800').split(/\\s+/).map(Number);const baseW=vb[2],baseH=vb[3];let scale=1,drag=false,lastX=0,lastY=0;
function setScale(next,cx=stage.clientWidth/2,cy=stage.clientHeight/2){next=Math.max(.15,Math.min(6,next));const wx=(stage.scrollLeft+cx)/scale,wy=(stage.scrollTop+cy)/scale;scale=next;svg.style.width=(baseW*scale)+'px';svg.style.height=(baseH*scale)+'px';stage.scrollLeft=wx*scale-cx;stage.scrollTop=wy*scale-cy}
function zoomBy(f){setScale(scale*f)}function fitView(){setScale(Math.min((stage.clientWidth-24)/baseW,(stage.clientHeight-24)/baseH,1),0,0);stage.scrollLeft=0;stage.scrollTop=0}
stage.addEventListener('wheel',e=>{e.preventDefault();const r=stage.getBoundingClientRect();setScale(scale*(e.deltaY<0?1.12:.89),e.clientX-r.left,e.clientY-r.top)},{passive:false});
stage.addEventListener('mousedown',e=>{if(e.target.closest('.net-row'))return;drag=true;lastX=e.clientX;lastY=e.clientY;stage.classList.add('dragging')});
window.addEventListener('mousemove',e=>{if(!drag)return;stage.scrollLeft-=e.clientX-lastX;stage.scrollTop-=e.clientY-lastY;lastX=e.clientX;lastY=e.clientY});
window.addEventListener('mouseup',()=>{drag=false;stage.classList.remove('dragging')});
stage.addEventListener('dblclick',e=>{if(!e.target.closest('.net-row'))fitView()});
document.querySelectorAll('.net-row').forEach(row=>row.addEventListener('click',()=>{const net=row.dataset.net;if(net)location.href='kiway://net/'+encodeURIComponent(net)}));
setTimeout(fitView,50);
</script>"""

    def OnDiagramNavigation(self, event):
        url = event.GetURL()
        prefix = "kiway://net/"
        if not url.startswith(prefix):
            return
        event.Veto()
        net_name = unquote(url[len(prefix):]).strip("/")
        if net_name:
            self.net_action_combo.SetValue(net_name)
            self._highlight_net(net_name)

    def OnExportPowerTreeSvg(self, event):
        if self.current_power_tree_svg:
            self._save_file(self.current_power_tree_svg, "SVG", "kiway_power_tree.svg")

    def OnExportPowerTreeCsv(self, event):
        if not self.power_tree_result.get("nodes"):
            return
        rows = []
        for edge in self.power_tree_result["edges"]:
            rows.append({"Record Type": "Power Path", **edge})
        for issue in self.power_tree_result["issues"]:
            rows.append({"Record Type": "Issue", **issue})
        headers = []
        for row in rows:
            for key in row:
                if key not in headers:
                    headers.append(key)
        stream = StringIO()
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        self._save_file(stream.getvalue(), "CSV", "kiway_power_tree.csv")

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
                if hasattr(fp, "ClearSelected"):
                    fp.ClearSelected()
            if footprint is not None:
                footprint.SetSelected()
            net = row.get("Net", "")
            if net:
                self.net_action_combo.SetValue(net)
                self._highlight_net(net)
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
    def _signal_flow_rows(self):
        src_pattern = self.source_pattern.GetValue().strip()
        dst_pattern = self.dest_pattern.GetValue().strip()
        sources = [fp.GetReference() for fp in self._get_footprints_by_pattern(src_pattern)]
        destinations = [fp.GetReference() for fp in self._get_footprints_by_pattern(dst_pattern)]
        if not sources or not destinations:
            return [], sources, destinations
        kwargs = {
            "include_intermediates": self.sf_include_intermediates.IsChecked(),
            "include_power": self.sf_include_power.IsChecked(),
        }
        if self.sf_consolidate.IsChecked():
            rows = self.analyzer.summarize_source_destination_table(sources, destinations, **kwargs)
        else:
            rows = self.analyzer.generate_rich_source_destination_table(sources, destinations, **kwargs)
            for row in rows:
                row["Connection Count"] = 1
                row["Source Endpoint"] = f'{row.get("Source Reference", "")}.{row.get("Source Pin", "")}'
                row["Destination Endpoint"] = f'{row.get("Destination Reference", "")}.{row.get("Destination Pin", "")}'
        return rows, sources, destinations

    def OnSignalFlowPreview(self, event):
        src_pattern = self.source_pattern.GetValue().strip()
        dst_pattern = self.dest_pattern.GetValue().strip()
        
        if not src_pattern or not dst_pattern:
            wx.MessageBox("Enter source and destination patterns.", "Info", wx.OK)
            return
        
        data, sources, destinations = self._signal_flow_rows()
        if not sources or not destinations:
            wx.MessageBox("No matching components found.", "Info", wx.OK)
            return
        self.sf_rows = data
        self.sf_preview.DeleteAllItems()
        if not data:
            self.sf_summary.SetLabel("No complete source-to-destination routes matched the current scope and net rules.")
            self.status_text.SetLabel("No matching connections found between source and destination.")
            return
        for entry in data:
            source_label = str(entry.get("Source Reference", ""))
            if entry.get("Source Value"):
                source_label += f' | {entry.get("Source Value")}'
            destination_label = str(entry.get("Destination Reference", ""))
            if entry.get("Destination Value"):
                destination_label += f' | {entry.get("Destination Value")}'
            index = self.sf_preview.InsertItem(self.sf_preview.GetItemCount(), source_label)
            values = (
                entry.get("Source Pin", ""), entry.get("Net Name", ""),
                entry.get("Net Type", ""), entry.get("Protocol", ""),
                entry.get("Intermediates", ""), destination_label,
                entry.get("Destination Pin", ""), entry.get("Path", ""),
                entry.get("Connection Count", 1),
            )
            for column, value in enumerate(values, 1):
                self.sf_preview.SetItem(index, column, str(value))
        unique_nets = {row.get("Net Name", "") for row in data}
        power_routes = sum(1 for row in data if row.get("Net Type") != "signal")
        self.sf_summary.SetLabel(
            f"{len(data)} routes across {len(unique_nets)} nets; {power_routes} power/ground routes. "
            "Double-click a route to highlight its net in PCB Editor."
        )
        self.status_text.SetLabel(f"Previewed {len(data)} explicit source-to-destination routes.")

    def OnSignalFlowRowActivated(self, event):
        index = event.GetIndex()
        if 0 <= index < len(self.sf_rows):
            net_name = str(self.sf_rows[index].get("Net Name", ""))
            self.net_action_combo.SetValue(net_name)
            self._highlight_net(net_name)

    def OnSignalFlowExport(self, format_type):
        src_pattern = self.source_pattern.GetValue().strip()
        dst_pattern = self.dest_pattern.GetValue().strip()
        
        data, _sources, _destinations = self._signal_flow_rows()
        
        if not data:
            wx.MessageBox("No data to export.", "Info", wx.OK)
            return
        
        if format_type == 'svg':
            content = self.diagram_gen.generate_rich_signal_flow_diagram(
                data, title=f"Signal Flow: {src_pattern} to {dst_pattern}"
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
        
        self.ic_rows = data
        self.ic_preview.DeleteAllItems()
        if not data:
            self.ic_summary.SetLabel(f"No connection rows found for {ic_ref} with the current power-net option.")
            self.status_text.SetLabel(f"No connection rows found for {ic_ref}.")
            return
        for entry in data:
            index = self.ic_preview.InsertItem(self.ic_preview.GetItemCount(), str(entry.get("IC Pin", "")))
            values = (
                entry.get("Net Name", ""), entry.get("Net Type", ""),
                entry.get("Protocol", ""), entry.get("Destination Reference", ""),
                entry.get("Destination Pin", ""), entry.get("Destination Value", ""),
            )
            for column, value in enumerate(values, 1):
                self.ic_preview.SetItem(index, column, str(value))
        ic_fp = self.extractor.get_footprint_by_reference(ic_ref)
        ic_value = ic_fp.GetValue() if ic_fp else ""
        self.current_ic_svg = self.diagram_gen.generate_ic_signal_chart(ic_ref, ic_value, data)
        if self.ic_visual_is_web:
            self.ic_visual_preview.SetPage(self._svg_html(self.current_ic_svg), "")
        else:
            self.ic_visual_preview.SetValue(
                f"Visual preview requires wx.html2.\n\n{len(data)} IC connection rows are ready for SVG export."
            )
        unique_nets = {row.get("Net Name", "") for row in data}
        destinations = {row.get("Destination Reference", "") for row in data if row.get("Destination Reference") != "N/C"}
        self.ic_summary.SetLabel(
            f"{ic_ref}: {len(unique_nets)} nets to {len(destinations)} destination components. "
            "Double-click a row to highlight the net."
        )
        self.status_text.SetLabel(f"Generated the table and visual flow chart for {ic_ref}.")

    def OnICChartRowActivated(self, event):
        index = event.GetIndex()
        if 0 <= index < len(self.ic_rows):
            net_name = str(self.ic_rows[index].get("Net Name", ""))
            self.net_action_combo.SetValue(net_name)
            self._highlight_net(net_name)

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
            net_type = self.extractor.classify_net(row.get("Net Name", ""))
            is_power = net_type != "signal"
            row["Net Type"] = net_type
            row["Is Power Net"] = "Yes" if is_power else "No"
            if mode == 1 and is_power:
                continue
            if mode == 2 and not is_power:
                continue
            filtered.append(row)

        scope_label = f"{', '.join(refs[:6])}{'...' if len(refs) > 6 else ''}"
        if mode == 2:
            self.power_tree_result = PowerTreeAnalyzer(self.extractor).analyze()
            self.current_diagram_svg = generate_power_tree_svg(
                self.power_tree_result,
                title="Board Power Flow",
            )
            diagram_detail = (
                f"board-level {len(self.power_tree_result['nodes'])} rails, "
                f"{len(self.power_tree_result['edges'])} directed conversion/filter paths, and "
                f"{len(self.power_tree_result['issues'])} findings"
            )
        else:
            labels = ("System Connectivity", "Signal Topology")
            self.current_diagram_svg = self.diagram_gen.generate_signal_flow_diagram(
                filtered,
                title=f"{labels[mode]}: {scope_label}",
            )
            unique_nets = {row.get("Net Name", "") for row in filtered if row.get("Net Name", "")}
            diagram_detail = f"{len(unique_nets)} unique net lanes across {len(refs)} components"
        if self.diagram_preview_is_web:
            self.diagram_preview.SetPage(self._interactive_svg_html(self.current_diagram_svg), "")
        else:
            self.diagram_preview.SetValue(
                f"Visual web preview is unavailable in this KiCad Python build.\n\n"
                f"{len(filtered)} connections are ready for SVG export."
            )
        self.export_diagram_btn.Enable(bool(self.current_diagram_svg))
        self.diagram_summary.SetLabel(
            f"Preview: {diagram_detail}. Mouse wheel zooms; drag empty space to pan; click a net lane to highlight it."
        )
        self.status_text.SetLabel(f"Rendered interactive {self.diagram_mode.GetStringSelection().lower()} in the plugin window.")

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
