"""Advanced wxPython dashboard for KiWay Extract Pins."""

from __future__ import annotations

import os
import fnmatch
from typing import Any, Dict, List, Optional

import wx
import wx.html

try:
    import pcbnew
except ImportError:  # pragma: no cover - only outside KiCad
    pcbnew = None

# Do not import matplotlib during KiCad plugin discovery.  Some matplotlib/
# wxPython combinations load native backends that can terminate KiCad before
# the ActionPlugin window is shown.  SVG exports remain dependency-free.
FigureCanvas = None
Figure = None

try:
    import markdown
except ImportError:  # pragma: no cover - optional dependency
    markdown = None

from .core.doc_generator import DocGenerator
from .core.layout_assistant import LayoutAssistant
from .core.schematic_graph import SchematicGraphParser, SheetDefinition
from .core.test_point_extractor import TestPointExtractor
from .core.board_extract import extract_board_pin_rows, protocol_color
from .core.data_extractor import DataExtractor
from .core.signal_flow import SignalFlowAnalyzer
from .core.diagram_generator import SVGDiagramGenerator
from .core.formatters import CSVFormatter, MarkdownFormatter
from .core.cross_linker import (
    CrossProjectLinker,
    ImportedPinDocument,
    PinDocumentImporter,
    parse_link_rules,
)
from .help_utils import open_help
from .selection_utils import footprint, select_items
from .guided_ui import add_workflow


class PluginUI(wx.Frame):
    """Main KiWay dashboard for graph extraction, visualization, and docs."""

    def __init__(self, parent: Any = None, board: Any = None) -> None:
        super().__init__(
            parent,
            title="KiWay Extract Pins - Interface Dashboard",
            size=(1180, 760),
            style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER,
        )
        self.board = board if board is not None else (pcbnew.GetBoard() if pcbnew else None)
        self.parser: Optional[SchematicGraphParser] = None
        self.interfaces: Dict[str, Dict[str, Any]] = {}
        self.tm_tc_rows: List[Dict[str, Any]] = []
        self.tp_rows: List[Dict[str, Any]] = []
        self.connector_rows: List[Dict[str, Any]] = []
        self.peripheral_rows: List[Dict[str, Any]] = []
        self.board_rows: List[Dict[str, Any]] = []
        self.signal_flow_rows: List[Dict[str, Any]] = []
        self.selected_component_refs: List[str] = []
        self.component_export_data: Dict[str, Any] = {}
        self.cross_documents: List[ImportedPinDocument] = []
        self.cross_links: List[Dict[str, str]] = []
        self.current_markdown = ""
        self.docgen = DocGenerator()
        self.extractor = DataExtractor(self.board) if self.board else None
        self.signal_analyzer = SignalFlowAnalyzer(self.extractor) if self.extractor else None
        self.diagram_generator = SVGDiagramGenerator()

        self._build_ui()
        self.on_refresh_component_selection(None)
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(
            panel, root, "Extract Pins and Build ICD",
            "Choose project inputs, generate a complete report preview, then review tables and export the approved artifacts.",
            ("Configure", "Preview and review", "Export"),
        )

        config = wx.StaticBoxSizer(wx.StaticBox(panel, label="Project"), wx.VERTICAL)
        self.schematic_dir = wx.TextCtrl(panel)
        browse_btn = wx.Button(panel, label="Browse")
        browse_btn.Bind(wx.EVT_BUTTON, self.on_browse_dir)
        self.board_sequence = wx.TextCtrl(panel)
        self.board_sequence.SetToolTip("Comma-separated board order, e.g. DEMO_CTRL, DEMO_SENSOR, DEMO_POWER, DEMO_IO")
        self.pass_field = wx.TextCtrl(panel)
        self.pass_field.SetValue("NetTie_Path")
        analyze_btn = wx.Button(panel, label="Analyze & Preview")
        analyze_btn.Bind(wx.EVT_BUTTON, self.on_analyze)
        analyze_btn.SetDefault()

        source_row = wx.BoxSizer(wx.HORIZONTAL)
        source_row.Add(wx.StaticText(panel, label="Netlist directory:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        source_row.Add(self.schematic_dir, 1, wx.EXPAND | wx.ALL, 4)
        source_row.Add(browse_btn, 0, wx.ALL, 4)
        config.Add(source_row, 0, wx.EXPAND)
        options_row = wx.BoxSizer(wx.HORIZONTAL)
        options_row.Add(wx.StaticText(panel, label="Board order:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        options_row.Add(self.board_sequence, 1, wx.EXPAND | wx.ALL, 4)
        options_row.Add(wx.StaticText(panel, label="Pass field:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        options_row.Add(self.pass_field, 0, wx.ALL, 4)
        options_row.Add(analyze_btn, 0, wx.ALL, 4)
        config.Add(options_row, 0, wx.EXPAND)
        root.Add(config, 0, wx.EXPAND | wx.ALL, 6)

        self.filter_pane = wx.CollapsiblePane(panel, label="Filters and advanced options")
        filter_panel = self.filter_pane.GetPane()
        filters = wx.WrapSizer(wx.HORIZONTAL)
        self.reference_filter = wx.TextCtrl(filter_panel, value="", size=(110, -1))
        self.value_filter = wx.TextCtrl(filter_panel, value="", size=(110, -1))
        self.net_filter = wx.TextCtrl(filter_panel, value="", size=(130, -1))
        self.property_filter = wx.TextCtrl(filter_panel, value="", size=(140, -1))
        self.include_power = wx.CheckBox(filter_panel, label="Power nets")
        self.include_power.SetValue(True)
        self.selected_only = wx.CheckBox(filter_panel, label="Selected only")
        for label, control in (("Refs (*,?):", self.reference_filter), ("Values:", self.value_filter), ("Nets:", self.net_filter), ("Property / value:", self.property_filter)):
            filters.Add(wx.StaticText(filter_panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
            filters.Add(control, 1, wx.EXPAND | wx.ALL, 3)
        filters.Add(self.include_power, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        filters.Add(self.selected_only, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        filter_btn = wx.Button(filter_panel, label="Apply")
        filter_btn.Bind(wx.EVT_BUTTON, self.on_apply_filters)
        filters.Add(filter_btn, 0, wx.ALL, 4)
        self.consolidate_tm_tc = wx.CheckBox(filter_panel, label="Consolidate TM/TC by net")
        self.consolidate_tm_tc.SetValue(True)
        self.consolidate_tm_tc.SetToolTip("Combine repeated connector, passive, and IC pin entries into one row per labeled net.")
        self.tm_tc_selected_only = wx.CheckBox(filter_panel, label="TM/TC from selected components")
        self.tm_tc_selected_only.SetToolTip("Limit TM/TC rows to footprints currently selected in PCB Editor.")
        filters.Add(self.consolidate_tm_tc, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        filters.Add(self.tm_tc_selected_only, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        filter_panel.SetSizer(filters)
        self.filter_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, lambda _event: panel.Layout())
        root.Add(self.filter_pane, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        self.notebook = wx.Choicebook(panel)
        self.interface_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.interface_list.InsertColumn(0, "Interface", width=120)
        self.interface_list.InsertColumn(1, "Nets", width=70)
        self.interface_list.InsertColumn(2, "Source", width=90)
        self.interface_list.InsertColumn(3, "Destination", width=100)
        self.interface_list.InsertColumn(4, "TM/TC", width=100)
        self.interface_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_interface_selected)
        self.notebook.AddPage(self.interface_list, "Interfaces")

        self.tp_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT)
        for idx, label in enumerate(["TP", "Sheet", "Net", "Resolved IC", "IC Sheet", "Function", "IC Pin", "Type"]):
            self.tp_list.InsertColumn(idx, label, width=120)
        self.notebook.AddPage(self.tp_list, "Test Points")

        self.tm_tc_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT)
        for idx, label in enumerate(["Type", "Source", "Destination", "Interface", "Signal", "Net", "Sheet", "Ref", "Pin", "Count"]):
            self.tm_tc_list.InsertColumn(idx, label, width=110)
        self.notebook.AddPage(self.tm_tc_list, "TM/TC")
        self.pin_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for idx, label in enumerate(["Reference", "Pad", "Net", "Type", "Power", "Protocol", "Value", "Properties"]):
            self.pin_list.InsertColumn(idx, label, width=125 if idx != 7 else 260)
        self.pin_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_pin_selected)
        self.pin_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_pin_selected)
        self.notebook.AddPage(self.pin_list, "Board Pins")

        sheet_panel = wx.Panel(self.notebook)
        sheet_root = wx.BoxSizer(wx.VERTICAL)
        sheet_splitter = wx.SplitterWindow(sheet_panel)
        sheet_rules_panel = wx.Panel(sheet_splitter)
        sheet_rules_sizer = wx.BoxSizer(wx.VERTICAL)
        self.sheet_definitions = wx.TextCtrl(
            sheet_rules_panel,
            style=wx.TE_MULTILINE | wx.TE_DONTWRAP,
        )
        self.sheet_definitions.SetToolTip(
            "One rule per line: Display Name | /hierarchical/path/* | reference wildcard. "
            "Path and reference may be *; examples: Power | /Power/* | * or Control | * | U*."
        )
        sheet_rules_sizer.Add(self.sheet_definitions, 1, wx.EXPAND | wx.ALL, 4)
        validate_sheets = wx.Button(sheet_rules_panel, label="Validate Rules")
        validate_sheets.Bind(wx.EVT_BUTTON, self.on_validate_sheet_definitions)
        sheet_rules_sizer.Add(validate_sheets, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
        sheet_rules_panel.SetSizer(sheet_rules_sizer)

        sheet_preview_panel = wx.Panel(sheet_splitter)
        sheet_preview_sizer = wx.BoxSizer(wx.VERTICAL)
        self.sheet_list = wx.ListCtrl(sheet_preview_panel, style=wx.LC_REPORT)
        for idx, label in enumerate(["Sheet", "Native Path", "Components", "References"]):
            self.sheet_list.InsertColumn(idx, label, width=120 if idx < 3 else 280)
        sheet_preview_sizer.Add(self.sheet_list, 1, wx.EXPAND | wx.ALL, 4)
        sheet_preview_panel.SetSizer(sheet_preview_sizer)
        sheet_splitter.SplitVertically(sheet_rules_panel, sheet_preview_panel, 330)
        sheet_root.Add(sheet_splitter, 1, wx.EXPAND)
        sheet_panel.SetSizer(sheet_root)
        self.notebook.AddPage(sheet_panel, "Sheet Definitions")

        cross_panel = wx.Panel(self.notebook)
        cross_root = wx.BoxSizer(wx.VERTICAL)
        cross_controls = wx.WrapSizer(wx.HORIZONTAL)
        cross_controls.Add(wx.StaticText(cross_panel, label="Project / board:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.cross_project_name = wx.TextCtrl(cross_panel, value="", size=(150, -1))
        self.cross_project_name.SetToolTip("Optional project name for a single imported document or the current PCB.")
        cross_controls.Add(self.cross_project_name, 0, wx.ALL, 4)
        for label, handler in (
            ("Import Pin Docs", self.on_import_pin_docs),
            ("Add Current PCB", self.on_add_current_cross_document),
            ("Clear", self.on_clear_cross_documents),
        ):
            button = wx.Button(cross_panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            cross_controls.Add(button, 0, wx.ALL, 4)
        self.cross_exact_match = wx.CheckBox(cross_panel, label="Exact labels")
        self.cross_exact_match.SetValue(True)
        self.cross_normalized_match = wx.CheckBox(cross_panel, label="Normalized labels")
        self.cross_normalized_match.SetValue(True)
        self.cross_include_power = wx.CheckBox(cross_panel, label="Include power")
        cross_controls.Add(self.cross_exact_match, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        cross_controls.Add(self.cross_normalized_match, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        cross_controls.Add(self.cross_include_power, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        build_links = wx.Button(cross_panel, label="Build Cross-Links")
        build_links.Bind(wx.EVT_BUTTON, self.on_build_cross_links)
        cross_controls.Add(build_links, 0, wx.ALL, 4)
        cross_root.Add(cross_controls, 0, wx.EXPAND)

        self.cross_document_list = wx.ListCtrl(cross_panel, style=wx.LC_REPORT)
        self.cross_document_list.SetMinSize((-1, 105))
        for idx, label in enumerate(["Project", "Document", "Endpoints"]):
            self.cross_document_list.InsertColumn(idx, label, width=150 if idx != 1 else 390)
        cross_root.Add(self.cross_document_list, 0, wx.EXPAND | wx.ALL, 4)

        cross_rules_box = wx.StaticBoxSizer(wx.StaticBox(cross_panel, label="Link Rules"), wx.VERTICAL)
        self.cross_rules = wx.TextCtrl(cross_panel, size=(-1, 72), style=wx.TE_MULTILINE | wx.TE_DONTWRAP)
        self.cross_rules.SetToolTip(
            "One rule per line: Name | wildcard/regex | source pattern | destination pattern. "
            "Wildcard captures (* and ?) or regex capture groups must contain the same signal text. "
            "Use || as the field delimiter when a regex contains | alternation."
        )
        cross_rules_box.Add(self.cross_rules, 1, wx.EXPAND | wx.ALL, 4)
        cross_root.Add(cross_rules_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        self.cross_link_list = wx.ListCtrl(cross_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        cross_columns = [
            "Source", "Source Pin", "Source Label", "Destination", "Destination Pin",
            "Destination Label", "Signal", "Method", "Rule", "Confidence", "Status",
        ]
        for idx, label in enumerate(cross_columns):
            self.cross_link_list.InsertColumn(idx, label, width=130 if idx not in {2, 5} else 190)
        cross_root.Add(self.cross_link_list, 1, wx.EXPAND | wx.ALL, 4)
        cross_exports = wx.WrapSizer(wx.HORIZONTAL)
        for label, handler in (
            ("Export Tracker CSV", self.on_export_cross_csv),
            ("Export Tracker Markdown", self.on_export_cross_markdown),
            ("Export Harness SVG", self.on_export_cross_svg),
        ):
            button = wx.Button(cross_panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            cross_exports.Add(button, 0, wx.ALL, 4)
        cross_root.Add(cross_exports, 0, wx.ALIGN_RIGHT)
        cross_panel.SetSizer(cross_root)
        self.notebook.AddPage(cross_panel, "Cross-Link")

        component_panel = wx.Panel(self.notebook)
        component_root = wx.BoxSizer(wx.VERTICAL)
        component_controls = wx.StaticBoxSizer(wx.StaticBox(component_panel, label="Connector / Component Selection"), wx.HORIZONTAL)
        component_controls.Add(wx.StaticText(component_panel, label="Reference pattern:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.component_pattern = wx.TextCtrl(component_panel, value="J*", size=(130, -1))
        self.component_pattern.SetToolTip("Use * and ? wildcards, for example J*, U1, or TP*")
        component_controls.Add(self.component_pattern, 1, wx.EXPAND | wx.ALL, 4)
        select_refresh = wx.Button(component_panel, label="Use PCB Selection")
        select_refresh.Bind(wx.EVT_BUTTON, self.on_refresh_component_selection)
        component_controls.Add(select_refresh, 0, wx.ALL, 4)
        preview_components = wx.Button(component_panel, label="Preview")
        preview_components.Bind(wx.EVT_BUTTON, self.on_component_preview)
        component_controls.Add(preview_components, 0, wx.ALL, 4)
        component_root.Add(component_controls, 0, wx.EXPAND | wx.ALL, 4)
        self.component_list = wx.ListCtrl(component_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.component_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_component_selected)
        self.component_list.InsertColumn(0, "Reference", width=120)
        self.component_list.InsertColumn(1, "Value", width=220)
        self.component_list.InsertColumn(2, "Pins", width=80)
        component_root.Add(self.component_list, 1, wx.EXPAND | wx.ALL, 4)
        self.component_preview = wx.TextCtrl(component_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        component_root.Add(self.component_preview, 1, wx.EXPAND | wx.ALL, 4)
        component_buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Export Selected", self.on_export_selected_components), ("Export Pattern", self.on_export_pattern_components)):
            button = wx.Button(component_panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            component_buttons.Add(button, 0, wx.ALL, 4)
        component_root.Add(component_buttons, 0, wx.ALIGN_RIGHT)
        component_panel.SetSizer(component_root)
        self.notebook.AddPage(component_panel, "Component Export")

        flow_panel = wx.Panel(self.notebook)
        flow_root = wx.BoxSizer(wx.VERTICAL)
        flow_controls = wx.StaticBoxSizer(wx.StaticBox(flow_panel, label="Flow Selection"), wx.HORIZONTAL)
        flow_controls.Add(wx.StaticText(flow_panel, label="Sources:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.flow_source_filter = wx.TextCtrl(flow_panel, value="J*,U*", size=(110, -1))
        self.flow_source_filter.SetToolTip("Comma-separated wildcard references, for example J*, U1")
        flow_controls.Add(self.flow_source_filter, 0, wx.ALL, 4)
        flow_controls.Add(wx.StaticText(flow_panel, label="Destinations:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.flow_destination_filter = wx.TextCtrl(flow_panel, value="U*,J*", size=(110, -1))
        self.flow_destination_filter.SetToolTip("Comma-separated wildcard references, for example U*, J2")
        flow_controls.Add(self.flow_destination_filter, 0, wx.ALL, 4)
        self.flow_include_intermediates = wx.CheckBox(flow_panel, label="Show pass-through parts")
        self.flow_include_intermediates.SetValue(True)
        flow_controls.Add(self.flow_include_intermediates, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.flow_include_power = wx.CheckBox(flow_panel, label="Include power")
        flow_controls.Add(self.flow_include_power, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        flow_preview_btn = wx.Button(flow_panel, label="Preview Flow")
        flow_preview_btn.Bind(wx.EVT_BUTTON, self.on_flow_preview)
        flow_controls.Add(flow_preview_btn, 0, wx.ALL, 4)
        flow_root.Add(flow_controls, 0, wx.EXPAND | wx.ALL, 4)
        self.flow_preview = wx.TextCtrl(flow_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        flow_root.Add(self.flow_preview, 1, wx.EXPAND | wx.ALL, 4)
        flow_panel.SetSizer(flow_root)
        self.notebook.AddPage(flow_panel, "Signal Flow")
        report_panel = wx.Panel(self.notebook)
        report_sizer = wx.BoxSizer(wx.VERTICAL)
        self.html_preview = wx.html.HtmlWindow(report_panel, style=wx.html.HW_SCROLLBAR_AUTO)
        report_sizer.Add(self.html_preview, 1, wx.EXPAND | wx.ALL, 4)
        report_panel.SetSizer(report_sizer)
        self.notebook.AddPage(report_panel, "Report Preview")
        self.html_preview.SetPage(self.docgen.render_html("# No preview yet\n\nChoose project inputs, then click **Analyze & Preview**." , for_preview=True))
        root.Add(self.notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        group_btn = wx.Button(panel, label="Create PCB Group")
        group_btn.Bind(wx.EVT_BUTTON, self.on_create_group)
        highlight_btn = wx.Button(panel, label="Highlight Net")
        highlight_btn.Bind(wx.EVT_BUTTON, self.on_highlight_net)
        clear_highlight_btn = wx.Button(panel, label="Clear")
        clear_highlight_btn.Bind(wx.EVT_BUTTON, self.on_clear_highlight)
        export_btn = wx.Button(panel, label="Export...")
        export_btn.Bind(wx.EVT_BUTTON, self.on_export_menu)
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        for btn in (group_btn, highlight_btn, clear_highlight_btn, export_btn, help_btn):
            button_row.Add(btn, 0, wx.ALL, 4)
        button_row.AddStretchSpacer(1)
        root.Add(button_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self.figure = None
        self.canvas = None

        self.status = wx.StaticText(panel, label="Ready.")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(root)
        self.workflow.set_step(0, "Choose an optional netlist directory and board order, then Analyze & Preview.")

    def on_browse_dir(self, _event: Any) -> None:
        with wx.DirDialog(self, "Select directory containing KiCad XML netlists") as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.schematic_dir.SetValue(dlg.GetPath())

    def on_import_pin_docs(self, _event: Any) -> None:
        wildcard = "Pin documents (*.csv;*.md;*.markdown)|*.csv;*.md;*.markdown|All files (*.*)|*.*"
        with wx.FileDialog(
            self,
            "Import KiWay or compatible pin documents",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            paths = dialog.GetPaths()
        importer = PinDocumentImporter()
        configured_project = self.cross_project_name.GetValue().strip()
        imported: List[ImportedPinDocument] = []
        try:
            for path in paths:
                project = configured_project if len(paths) == 1 else os.path.splitext(os.path.basename(path))[0]
                document = importer.load(path, project_name=project)
                if not document.endpoints:
                    raise ValueError(f"No recognizable pin endpoints were found in {path}.")
                imported.append(document)
        except Exception as exc:
            wx.MessageBox(str(exc), "Pin document import failed", wx.OK | wx.ICON_ERROR)
            return
        self.cross_documents.extend(imported)
        self.cross_links = []
        self._populate_cross_documents()
        self._populate_cross_links()
        self._rebuild_current_markdown()
        self._update_preview()
        self.status.SetLabel(
            f"Imported {len(imported)} pin documents with "
            f"{sum(len(document.endpoints) for document in imported)} endpoints."
        )

    def on_add_current_cross_document(self, _event: Any) -> None:
        if not self.board:
            wx.MessageBox("Open a PCB before adding the current board.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        project = self.cross_project_name.GetValue().strip()
        board_path = str(getattr(self.board, "GetFileName", lambda: "")() or "")
        if not project:
            project = os.path.splitext(os.path.basename(board_path))[0] or "Current PCB"
        rows = extract_board_pin_rows(self.board, include_power=True)
        if self.parser:
            for row in rows:
                sheet = self.parser.get_component_sheet(str(row.get("Reference", "")))
                row["Sheet"] = sheet["name"]
                row["Sheet Path"] = sheet["path"]
        importer = PinDocumentImporter()
        endpoints = importer.endpoints_from_rows(rows, project, board_path or "Current PCB")
        self.cross_documents = [
            document for document in self.cross_documents
            if document.path != (board_path or "Current PCB")
        ]
        self.cross_documents.append(
            ImportedPinDocument(project=project, path=board_path or "Current PCB", endpoints=endpoints)
        )
        self.cross_links = []
        self._populate_cross_documents()
        self._populate_cross_links()
        self._rebuild_current_markdown()
        self._update_preview()
        self.status.SetLabel(f"Added current PCB as {project} with {len(endpoints)} pin endpoints.")

    def on_clear_cross_documents(self, _event: Any) -> None:
        self.cross_documents = []
        self.cross_links = []
        self._populate_cross_documents()
        self._populate_cross_links()
        self._rebuild_current_markdown()
        self._update_preview()
        self.status.SetLabel("Cleared imported cross-link documents.")

    def on_build_cross_links(self, _event: Any) -> None:
        if len(self.cross_documents) < 2:
            wx.MessageBox(
                "Import at least two pin documents, or import one document and add the current PCB.",
                "KiWay",
                wx.OK | wx.ICON_INFORMATION,
            )
            return
        try:
            rules = parse_link_rules(self.cross_rules.GetValue())
            linker = CrossProjectLinker(self.cross_documents)
            self.cross_links = linker.link(
                rules=rules,
                exact_match=self.cross_exact_match.GetValue(),
                normalized_match=self.cross_normalized_match.GetValue(),
                include_power=self.cross_include_power.GetValue(),
            )
        except Exception as exc:
            wx.MessageBox(str(exc), "Cross-link generation failed", wx.OK | wx.ICON_ERROR)
            return
        self._populate_cross_links()
        self._rebuild_current_markdown()
        self._update_preview()
        unmatched = len(
            linker.unmatched(
                self.cross_links,
                include_power=self.cross_include_power.GetValue(),
            )
        )
        self.status.SetLabel(
            f"Generated {len(self.cross_links)} cross-project links; "
            f"{unmatched} endpoints remain unmatched."
        )

    def _populate_cross_documents(self) -> None:
        self.cross_document_list.DeleteAllItems()
        for document in self.cross_documents:
            index = self.cross_document_list.InsertItem(
                self.cross_document_list.GetItemCount(), document.project
            )
            self.cross_document_list.SetItem(index, 1, document.path)
            self.cross_document_list.SetItem(index, 2, str(len(document.endpoints)))

    def _populate_cross_links(self) -> None:
        self.cross_link_list.DeleteAllItems()
        keys = [
            "Source Endpoint",
            "Source Pin",
            "Source Net/Label",
            "Destination Endpoint",
            "Destination Pin",
            "Destination Net/Label",
            "Signal Key",
            "Match Method",
            "Rule",
            "Confidence",
            "Status",
        ]
        for row in self.cross_links:
            index = self.cross_link_list.InsertItem(
                self.cross_link_list.GetItemCount(), str(row.get(keys[0], ""))
            )
            for column, key in enumerate(keys[1:], start=1):
                self.cross_link_list.SetItem(index, column, str(row.get(key, "")))

    def _ensure_cross_links(self) -> bool:
        if not self.cross_links:
            self.on_build_cross_links(None)
        return bool(self.cross_links)

    def on_export_cross_csv(self, _event: Any) -> None:
        if not self._ensure_cross_links():
            return
        with wx.FileDialog(
            self,
            "Export cross-project tracker",
            wildcard="CSV files (*.csv)|*.csv",
            defaultFile="kiway_cross_project_tracker.csv",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.docgen.export_csv(self.cross_links, dialog.GetPath())
                self.status.SetLabel(f"Exported {dialog.GetPath()}.")

    def on_export_cross_markdown(self, _event: Any) -> None:
        if not self._ensure_cross_links():
            return
        linker = CrossProjectLinker(self.cross_documents)
        unmatched_rows = [
            {
                "Project": endpoint.project,
                "Board": endpoint.board,
                "Sheet": endpoint.sheet,
                "Reference": endpoint.reference,
                "Pin": endpoint.pin,
                "Net/Label": endpoint.net_name or endpoint.label,
                "Source File": endpoint.source_file,
            }
            for endpoint in linker.unmatched(
                self.cross_links,
                include_power=self.cross_include_power.GetValue(),
            )
        ]
        lines = ["# KiWay Cross-Project Pin Tracker", ""]
        lines.extend(self.docgen._table_section("Resolved Cross-Links", self.cross_links))
        lines.extend(self.docgen._table_section("Unmatched Endpoints", unmatched_rows))
        markdown_text = "\n".join(lines)
        with wx.FileDialog(
            self,
            "Export cross-project tracker",
            wildcard="Markdown files (*.md)|*.md",
            defaultFile="kiway_cross_project_tracker.md",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.docgen.export_markdown(markdown_text, dialog.GetPath())
                self.status.SetLabel(f"Exported {dialog.GetPath()}.")

    def on_export_cross_svg(self, _event: Any) -> None:
        if not self._ensure_cross_links():
            return
        svg = CrossProjectLinker(self.cross_documents).harness_svg(self.cross_links)
        with wx.FileDialog(
            self,
            "Export cross-project harness",
            wildcard="SVG files (*.svg)|*.svg",
            defaultFile="kiway_cross_project_harness.svg",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                with open(dialog.GetPath(), "w", encoding="utf-8") as handle:
                    handle.write(svg)
                self.status.SetLabel(f"Exported {dialog.GetPath()}.")

    def _parse_sheet_definitions(self) -> List[SheetDefinition]:
        definitions: List[SheetDefinition] = []
        for line_number, raw_line in enumerate(self.sheet_definitions.GetValue().splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if not parts[0]:
                raise ValueError(f"Sheet rule line {line_number} is missing a display name.")
            if len(parts) > 3:
                raise ValueError(f"Sheet rule line {line_number} has more than three fields.")
            definitions.append(
                SheetDefinition(
                    name=parts[0],
                    path_pattern=parts[1] if len(parts) > 1 and parts[1] else "*",
                    reference_pattern=parts[2] if len(parts) > 2 and parts[2] else "*",
                )
            )
        return definitions

    def on_validate_sheet_definitions(self, _event: Any) -> None:
        try:
            definitions = self._parse_sheet_definitions()
        except ValueError as exc:
            wx.MessageBox(str(exc), "Invalid sheet definition", wx.OK | wx.ICON_ERROR)
            return
        self.status.SetLabel(f"Validated {len(definitions)} sheet definition rules.")

    def on_analyze(self, _event: Any) -> None:
        try:
            board_order = [b.strip() for b in self.board_sequence.GetValue().split(",") if b.strip()]
            schematic_paths = [self.schematic_dir.GetValue()] if self.schematic_dir.GetValue() else []
            self.parser = SchematicGraphParser(
                board=self.board,
                schematic_paths=schematic_paths,
                board_sequence=board_order,
                pass_through_field=self.pass_field.GetValue() or "NetTie_Path",
                sheet_definitions=self._parse_sheet_definitions(),
            )
            self.parser.build()
            self.interfaces = self.parser.group_interfaces()
            tp_extractor = TestPointExtractor(self.parser)
            self.tp_rows = tp_extractor.as_rows()
            selected_refs = [footprint.GetReference() for footprint in self._selected_footprints()] if self.tm_tc_selected_only.GetValue() else None
            self.tm_tc_rows = self.docgen.make_tm_tc_rows(
                self.parser,
                selected_refs=selected_refs,
                consolidate=self.consolidate_tm_tc.GetValue(),
            )
            self.connector_rows = self.docgen.connector_rows_from_parser(self.parser)
            self.peripheral_rows = self.docgen.peripheral_rows_from_parser(self.parser)
            if self.board:
                self.extractor = DataExtractor(self.board)
                self.signal_analyzer = SignalFlowAnalyzer(self.extractor)
            self._rebuild_current_markdown()
            self._refresh_board_rows()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay analysis failed", wx.OK | wx.ICON_ERROR)
            return

        self._populate_tables()
        self._draw_interfaces()
        self._update_preview()
        self.notebook.SetSelection(self.notebook.GetPageCount() - 1)
        self.status.SetLabel(
            f"Analyzed {len(self.interfaces)} interfaces, {len(self.tp_rows)} test points, "
            f"{len(self.tm_tc_rows)} TM/TC rows."
        )
        self.workflow.set_step(2, "Review Report Preview, then inspect detailed views and cross-select uncertain PCB rows before export.")

    def _refresh_board_rows(self) -> None:
        self.board_rows = extract_board_pin_rows(
            self.board,
            reference_filter=self.reference_filter.GetValue(),
            value_filter=self.value_filter.GetValue(),
            net_filter=self.net_filter.GetValue(),
            property_filter=self.property_filter.GetValue(),
            include_power=self.include_power.GetValue(),
            selected_only=self.selected_only.GetValue(),
        )
        self.pin_list.DeleteAllItems()
        for row in self.board_rows:
            index = self.pin_list.InsertItem(self.pin_list.GetItemCount(), row["Reference"])
            values = [row["Pad"], row["Net Name"], row["Net Type"], row["Power Net"], row["Protocol"], row["Value"], row["Properties"]]
            for column, value in enumerate(values, 1):
                self.pin_list.SetItem(index, column, str(value))
            self.pin_list.SetItemBackgroundColour(index, protocol_color(row["Protocol"], row["Net Type"]))
            self.pin_list.SetItemTextColour(index, wx.Colour(24, 31, 38))

    def on_apply_filters(self, _event: Any) -> None:
        try:
            self._refresh_board_rows()
            self.status.SetLabel(f"Showing {len(self.board_rows)} filtered board pin rows.")
        except Exception as exc:
            wx.MessageBox(str(exc), "Filter failed", wx.OK | wx.ICON_ERROR)

    def on_export_menu(self, _event: Any) -> None:
        menu = wx.Menu()
        actions = (
            ("Report as Markdown...", self.on_export_markdown),
            ("Report as HTML...", self.on_export_html),
            ("Combined tables as CSV...", self.on_export_csv),
            (None, None),
            ("Signal flow as SVG...", self.on_export_flow_svg),
            ("Interface blocks as SVG...", self.on_export_interface_svg),
            ("Signal flow as CSV...", self.on_export_flow_csv),
        )
        for label, handler in actions:
            if label is None:
                menu.AppendSeparator()
                continue
            item_id = int(wx.NewIdRef())
            menu.Append(item_id, label)
            self.Bind(wx.EVT_MENU, handler, id=item_id)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_pin_selected(self, event: Any) -> None:
        row_index = event.GetIndex()
        if row_index < 0 or row_index >= len(self.board_rows):
            return
        row = self.board_rows[row_index]
        net_name = row.get("Net Name", "")
        owner = footprint(self.board, row.get("Reference", ""))
        pads = [pad for pad in owner.Pads() if str(pad.GetNumber()) == str(row.get("Pad", ""))] if owner else []
        select_items(self.board, pads or [owner])
        self._highlight_net_name(net_name)

    def on_component_selected(self, event: Any) -> None:
        reference = self.component_list.GetItemText(event.GetIndex())
        select_items(self.board, [footprint(self.board, reference)])
        self.status.SetLabel(f"Selected {reference} on the PCB.")

    def on_highlight_net(self, _event: Any) -> None:
        selected = self.pin_list.GetFirstSelected()
        if selected >= 0:
            self._highlight_net_name(self.board_rows[selected].get("Net Name", ""))
            return
        iface = self.interface_list.GetFirstSelected()
        if iface >= 0:
            nets = self.interfaces.get(self.interface_list.GetItemText(iface), {}).get("nets", [])
            if nets:
                self._highlight_net_name(nets[0])

    def _highlight_net_name(self, net_name: str) -> None:
        if not self.board or not net_name:
            return
        try:
            net = self.board.FindNet(net_name) if hasattr(self.board, "FindNet") else None
            if net is not None and hasattr(self.board, "SetHighLightNet"):
                self.board.SetHighLightNet(net.GetNetCode())
            elif hasattr(self.board, "HighlightNet"):
                self.board.HighlightNet(net_name)
            if pcbnew and hasattr(pcbnew, "Refresh"):
                pcbnew.Refresh()
            self.status.SetLabel(f"Highlighted net {net_name}.")
        except Exception as exc:
            self.status.SetLabel(f"Could not highlight {net_name}: {exc}")

    def on_clear_highlight(self, _event: Any) -> None:
        if self.board and hasattr(self.board, "SetHighLightNet"):
            self.board.SetHighLightNet(-1)
        if pcbnew and hasattr(pcbnew, "Refresh"):
            pcbnew.Refresh()
        self.status.SetLabel("Net highlighting cleared.")

    def on_interface_selected(self, event: Any) -> None:
        self._draw_interfaces(selected=self.interface_list.GetItemText(event.GetIndex()))

    def on_create_group(self, _event: Any) -> None:
        selected = self.interface_list.GetFirstSelected()
        if selected < 0:
            wx.MessageBox("Select an interface first.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        name = self.interface_list.GetItemText(selected)
        try:
            LayoutAssistant(self.board).create_interface_group(self.interfaces[name])
        except Exception as exc:
            wx.MessageBox(str(exc), "Create PCB group failed", wx.OK | wx.ICON_ERROR)
            return
        self.status.SetLabel(f"Created PCB group for {name}.")

    def on_export_markdown(self, _event: Any) -> None:
        self._export_file("Markdown files (*.md)|*.md", "kiway_icd.md", self.docgen.export_markdown)

    def on_export_html(self, _event: Any) -> None:
        self._export_file("HTML files (*.html)|*.html", "kiway_icd.html", self.docgen.export_html)

    def on_export_csv(self, _event: Any) -> None:
        rows = self.tm_tc_rows + self.tp_rows + self.connector_rows
        with wx.FileDialog(self, "Export CSV", wildcard="CSV files (*.csv)|*.csv", defaultFile="kiway_tables.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.docgen.export_csv(rows, dlg.GetPath())
                self.status.SetLabel(f"Exported {dlg.GetPath()}.")
                self.workflow.set_step(3, "Open the exported artifact and complete its engineering review/sign-off.")

    def _selected_footprints(self) -> List[Any]:
        if not self.board:
            return []
        return [footprint for footprint in self.board.GetFootprints() if getattr(footprint, "IsSelected", lambda: False)()]

    def on_refresh_component_selection(self, _event: Any) -> None:
        footprints = sorted(self._selected_footprints(), key=lambda item: DataExtractor.natural_sort_key(item.GetReference()))
        self.selected_component_refs = [str(item.GetReference()) for item in footprints]
        self.component_list.DeleteAllItems()
        for footprint in footprints:
            index = self.component_list.InsertItem(self.component_list.GetItemCount(), str(footprint.GetReference()))
            self.component_list.SetItem(index, 1, str(footprint.GetValue()))
            self.component_list.SetItem(index, 2, str(len(list(footprint.Pads()))))
        self.status.SetLabel(f"Loaded {len(footprints)} selected components.")

    def _component_data(self, footprints: List[Any]) -> Dict[str, Any]:
        if not self.extractor:
            return {}
        data = self.extractor.extract_footprint_data(
            footprints,
            ignore_unconnected=False,
            ignore_power_nets=False,
            sort_pins_by_net_type=True,
        )
        if self.parser:
            for reference, component in data.items():
                sheet = self.parser.get_component_sheet(reference)
                properties = component.setdefault("general_properties", {})
                properties["Sheet"] = sheet["name"]
                properties["Sheet Path"] = sheet["path"]
        return data

    def _component_targets(self, use_selection: bool) -> List[Any]:
        if use_selection:
            refs = set(self.selected_component_refs)
            return [footprint for footprint in (self.board.GetFootprints() if self.board else []) if footprint.GetReference() in refs]
        return self._matching_footprints(self.component_pattern.GetValue())

    def on_component_preview(self, _event: Any) -> None:
        use_selection = bool(self.selected_component_refs)
        footprints = self._component_targets(use_selection)
        self.component_export_data = self._component_data(footprints)
        lines = [f"Components: {len(self.component_export_data)}", ""]
        if not self.component_export_data:
            lines.append("No components found. Select footprints on the PCB or enter a reference pattern.")
        else:
            for reference, data in self.component_export_data.items():
                props = data.get("general_properties", {})
                lines.append(f"{reference} | {props.get('Value', '')} | {len(data.get('pins', []))} pins")
                for pin in data.get("pins", [])[:12]:
                    lines.append(f"  {pin.get('Pad Name/Number', '')}: {pin.get('Net Name', '')} [{pin.get('Net Type', '')}]")
        self.component_preview.SetValue("\n".join(lines))
        self.status.SetLabel(f"Previewed {len(self.component_export_data)} components.")

    def _export_component_data(self, use_selection: bool) -> None:
        footprints = self._component_targets(use_selection)
        data = self._component_data(footprints)
        if not data:
            wx.MessageBox("No components matched the selection or pattern.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        with wx.FileDialog(self, "Export component pins", wildcard="CSV files (*.csv)|*.csv|Markdown files (*.md)|*.md", defaultFile="kiway_components.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
            if path.lower().endswith(".md"):
                content = MarkdownFormatter().format_component_data(data)
            else:
                content = CSVFormatter().format_component_data(data)
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
        self.status.SetLabel(f"Exported {len(data)} components to {path}.")

    def on_export_selected_components(self, _event: Any) -> None:
        self._export_component_data(True)

    def on_export_pattern_components(self, _event: Any) -> None:
        self._export_component_data(False)

    def _matching_footprints(self, pattern_text: str) -> List[str]:
        if not self.board:
            return []
        patterns = [item.strip().upper() for item in pattern_text.split(",") if item.strip()]
        if not patterns:
            return []
        refs = []
        for footprint in self.board.GetFootprints():
            reference = str(footprint.GetReference())
            if any(fnmatch.fnmatchcase(reference.upper(), pattern) for pattern in patterns):
                refs.append(reference)
        return sorted(refs, key=DataExtractor.natural_sort_key)

    def on_flow_preview(self, _event: Any) -> None:
        if not self.signal_analyzer:
            wx.MessageBox("Open a PCB with footprints before calculating signal flow.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        source_refs = self._matching_footprints(self.flow_source_filter.GetValue())
        destination_refs = self._matching_footprints(self.flow_destination_filter.GetValue())
        self.signal_flow_rows = self.signal_analyzer.generate_rich_source_destination_table(
            source_refs,
            destination_refs,
            include_intermediates=self.flow_include_intermediates.GetValue(),
            include_power=self.flow_include_power.GetValue(),
        )
        lines = [
            f"Sources: {', '.join(source_refs) or 'none'}",
            f"Destinations: {', '.join(destination_refs) or 'none'}",
            f"Paths: {len(self.signal_flow_rows)}",
            "",
        ]
        if not self.signal_flow_rows:
            lines.append("No complete paths matched. Check wildcard filters and net names.")
        else:
            for row in self.signal_flow_rows:
                lines.append(
                    f"{row.get('Source Reference')}:{row.get('Source Pin')} -> "
                    f"{row.get('Destination Reference')}:{row.get('Destination Pin')} | "
                    f"{row.get('Net Name')} | {row.get('Protocol') or 'signal'} | "
                    f"{row.get('Path')}"
                )
        self.flow_preview.SetValue("\n".join(lines))
        self._rebuild_current_markdown()
        self._update_preview()
        self.status.SetLabel(f"Prepared {len(self.signal_flow_rows)} signal-flow paths.")

    def _rebuild_current_markdown(self) -> None:
        self.current_markdown = self.docgen.build_markdown(
            tm_tc_rows=self.tm_tc_rows,
            test_point_rows=self.tp_rows,
            interface_maps=self.interfaces,
            connector_rows=self.connector_rows,
            peripheral_rows=self.peripheral_rows,
            flow_rows=self.signal_flow_rows,
            cross_link_rows=self.cross_links,
        )

    def _ensure_flow_rows(self) -> bool:
        if not self.signal_flow_rows:
            self.on_flow_preview(None)
        return bool(self.signal_flow_rows)

    def on_export_flow_csv(self, _event: Any) -> None:
        if not self._ensure_flow_rows():
            return
        with wx.FileDialog(self, "Export Signal Flow CSV", wildcard="CSV files (*.csv)|*.csv", defaultFile="kiway_signal_flow.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.docgen.export_csv(self.signal_flow_rows, dlg.GetPath())
                self.status.SetLabel(f"Exported {dlg.GetPath()}.")

    def on_export_flow_svg(self, _event: Any) -> None:
        if not self._ensure_flow_rows():
            return
        svg = self.diagram_generator.generate_rich_signal_flow_diagram(
            self.signal_flow_rows,
            title="KiWay Signal Flow: Sources to Destinations",
        )
        with wx.FileDialog(self, "Export Signal Flow SVG", wildcard="SVG files (*.svg)|*.svg", defaultFile="kiway_signal_flow.svg", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                with open(dlg.GetPath(), "w", encoding="utf-8") as handle:
                    handle.write(svg)
                self.status.SetLabel(f"Exported {dlg.GetPath()}.")

    def on_export_interface_svg(self, _event: Any) -> None:
        if not self.interfaces:
            wx.MessageBox("Run Analyze before exporting the interface block diagram.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        svg = self.diagram_generator.generate_interface_block_diagram(self.interfaces)
        with wx.FileDialog(self, "Export Interface Block SVG", wildcard="SVG files (*.svg)|*.svg", defaultFile="kiway_interface_blocks.svg", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                with open(dlg.GetPath(), "w", encoding="utf-8") as handle:
                    handle.write(svg)
                self.status.SetLabel(f"Exported {dlg.GetPath()}.")

    def _export_file(self, wildcard: str, default_file: str, exporter: Any) -> None:
        if not self.current_markdown:
            wx.MessageBox("Run Analyze before exporting.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        with wx.FileDialog(self, "Export", wildcard=wildcard, defaultFile=default_file, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                exporter(self.current_markdown, dlg.GetPath())
                self.status.SetLabel(f"Exported {dlg.GetPath()}.")
                self.workflow.set_step(3, "Open the exported artifact and complete its engineering review/sign-off.")

    def _populate_tables(self) -> None:
        self.interface_list.DeleteAllItems()
        for iface in sorted(self.interfaces.values(), key=lambda i: i.get("name", "")):
            idx = self.interface_list.InsertItem(self.interface_list.GetItemCount(), iface.get("name", ""))
            self.interface_list.SetItem(idx, 1, str(len(iface.get("nets", []))))
            self.interface_list.SetItem(idx, 2, iface.get("source_board", ""))
            self.interface_list.SetItem(idx, 3, iface.get("destination_board", ""))
            self.interface_list.SetItem(idx, 4, ", ".join(iface.get("tm_tc_types", [])))

        self.tp_list.DeleteAllItems()
        for row in self.tp_rows:
            idx = self.tp_list.InsertItem(self.tp_list.GetItemCount(), str(row.get("TP Reference", "")))
            for col, key in enumerate(
                ["TP Sheet", "Net Name", "Resolved IC", "Resolved IC Sheet", "Resolved IC Function", "IC Pin", "TM/TC Type"],
                start=1,
            ):
                self.tp_list.SetItem(idx, col, str(row.get(key, "")))

        self.tm_tc_list.DeleteAllItems()
        keys = ["Type", "Source Board", "Destination Board", "Interface", "Signal", "Net Name", "Sheet", "Reference", "Pin", "Pin Count"]
        for row in self.tm_tc_rows:
            idx = self.tm_tc_list.InsertItem(self.tm_tc_list.GetItemCount(), str(row.get(keys[0], "")))
            for col, key in enumerate(keys[1:], start=1):
                self.tm_tc_list.SetItem(idx, col, str(row.get(key, "")))

        self.sheet_list.DeleteAllItems()
        if self.parser:
            for row in self.parser.sheet_summary():
                idx = self.sheet_list.InsertItem(self.sheet_list.GetItemCount(), str(row["Sheet"]))
                for col, key in enumerate(["Path", "Components", "References"], start=1):
                    self.sheet_list.SetItem(idx, col, str(row[key]))

    def _draw_interfaces(self, selected: str = "") -> None:
        if not self.figure or not self.canvas:
            return
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.axis("off")
        names = sorted(self.interfaces.keys())
        if selected and selected in names:
            names = [selected]
        if not names:
            ax.text(0.5, 0.5, "Run Analyze to build interface map", ha="center", va="center")
        else:
            for idx, name in enumerate(names[:12]):
                iface = self.interfaces[name]
                y = 1.0 - (idx + 1) / (min(len(names), 12) + 1)
                src = iface.get("source_board") or "Board/MCU"
                dst = iface.get("destination_board") or "Peripheral"
                ax.text(0.05, y, src, bbox={"boxstyle": "round,pad=0.3", "fc": "#e8f1fb", "ec": "#618db5"})
                ax.text(0.78, y, dst, bbox={"boxstyle": "round,pad=0.3", "fc": "#f4efe5", "ec": "#a47f3e"})
                ax.annotate(
                    f"{name} ({len(iface.get('nets', []))} nets)",
                    xy=(0.76, y + 0.01),
                    xytext=(0.25, y + 0.01),
                    arrowprops={"arrowstyle": "->", "color": "#435466"},
                    va="center",
                )
        self.canvas.draw()

    def _update_preview(self) -> None:
        self.html_preview.SetPage(self.docgen.render_html(self.current_markdown, for_preview=True))
