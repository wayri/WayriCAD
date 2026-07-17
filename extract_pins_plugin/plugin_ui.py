"""Advanced wxPython dashboard for KiWay Extract Pins."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import wx
import wx.html

try:
    import pcbnew
except ImportError:  # pragma: no cover - only outside KiCad
    pcbnew = None

try:
    from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
    from matplotlib.figure import Figure
except ImportError:  # pragma: no cover - optional dependency
    FigureCanvas = None
    Figure = None

try:
    import markdown
except ImportError:  # pragma: no cover - optional dependency
    markdown = None

from .core.doc_generator import DocGenerator
from .core.layout_assistant import LayoutAssistant
from .core.schematic_graph import SchematicGraphParser
from .core.test_point_extractor import TestPointExtractor
from .core.board_extract import extract_board_pin_rows, protocol_color


class PluginUI(wx.Frame):
    """Main KiWay dashboard for graph extraction, visualization, and docs."""

    def __init__(self, parent: Any = None, board: Any = None) -> None:
        super().__init__(
            parent,
            title="KiWay Extract Pins - Interface Dashboard",
            size=(1180, 760),
            style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER,
        )
        self.board = board or (pcbnew.GetBoard() if pcbnew else None)
        self.parser: Optional[SchematicGraphParser] = None
        self.interfaces: Dict[str, Dict[str, Any]] = {}
        self.tm_tc_rows: List[Dict[str, Any]] = []
        self.tp_rows: List[Dict[str, Any]] = []
        self.connector_rows: List[Dict[str, Any]] = []
        self.peripheral_rows: List[Dict[str, Any]] = []
        self.board_rows: List[Dict[str, Any]] = []
        self.current_markdown = ""
        self.docgen = DocGenerator()

        self._build_ui()
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        config = wx.StaticBoxSizer(wx.StaticBox(panel, label="Project Inputs"), wx.HORIZONTAL)
        self.schematic_dir = wx.TextCtrl(panel)
        browse_btn = wx.Button(panel, label="Browse")
        browse_btn.Bind(wx.EVT_BUTTON, self.on_browse_dir)
        self.board_sequence = wx.TextCtrl(panel)
        self.board_sequence.SetToolTip("Comma-separated board order, e.g. DEMO_CTRL, DEMO_SENSOR, DEMO_POWER, DEMO_IO")
        self.pass_field = wx.TextCtrl(panel)
        self.pass_field.SetValue("NetTie_Path")
        analyze_btn = wx.Button(panel, label="Analyze")
        analyze_btn.Bind(wx.EVT_BUTTON, self.on_analyze)

        config.Add(wx.StaticText(panel, label="Schematic/netlist directory:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        config.Add(self.schematic_dir, 1, wx.EXPAND | wx.ALL, 4)
        config.Add(browse_btn, 0, wx.ALL, 4)
        config.Add(wx.StaticText(panel, label="Board order:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        config.Add(self.board_sequence, 1, wx.EXPAND | wx.ALL, 4)
        config.Add(wx.StaticText(panel, label="Pass field:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        config.Add(self.pass_field, 0, wx.ALL, 4)
        config.Add(analyze_btn, 0, wx.ALL, 4)
        root.Add(config, 0, wx.EXPAND | wx.ALL, 6)

        filters = wx.StaticBoxSizer(wx.StaticBox(panel, label="Board Pin Filters"), wx.HORIZONTAL)
        self.reference_filter = wx.TextCtrl(panel, value="", size=(90, -1))
        self.value_filter = wx.TextCtrl(panel, value="", size=(90, -1))
        self.net_filter = wx.TextCtrl(panel, value="", size=(110, -1))
        self.property_filter = wx.TextCtrl(panel, value="", size=(120, -1))
        self.include_power = wx.CheckBox(panel, label="Power nets")
        self.include_power.SetValue(True)
        self.selected_only = wx.CheckBox(panel, label="Selected only")
        for label, control in (("Refs (*,?):", self.reference_filter), ("Values:", self.value_filter), ("Nets:", self.net_filter), ("Property / value:", self.property_filter)):
            filters.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
            filters.Add(control, 1, wx.EXPAND | wx.ALL, 3)
        filters.Add(self.include_power, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        filters.Add(self.selected_only, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        filter_btn = wx.Button(panel, label="Apply Filters")
        filter_btn.Bind(wx.EVT_BUTTON, self.on_apply_filters)
        filters.Add(filter_btn, 0, wx.ALL, 4)
        root.Add(filters, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        splitter = wx.SplitterWindow(panel)
        left = wx.Panel(splitter)
        right = wx.Panel(splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        self.notebook = wx.Notebook(left)
        self.interface_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.interface_list.InsertColumn(0, "Interface", width=120)
        self.interface_list.InsertColumn(1, "Nets", width=70)
        self.interface_list.InsertColumn(2, "Source", width=90)
        self.interface_list.InsertColumn(3, "Destination", width=100)
        self.interface_list.InsertColumn(4, "TM/TC", width=100)
        self.interface_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_interface_selected)
        self.notebook.AddPage(self.interface_list, "Interfaces")

        self.tp_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT)
        for idx, label in enumerate(["TP", "Net", "Resolved IC", "Function", "IC Pin", "Type"]):
            self.tp_list.InsertColumn(idx, label, width=120)
        self.notebook.AddPage(self.tp_list, "Test Points")

        self.tm_tc_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT)
        for idx, label in enumerate(["Type", "Source", "Destination", "Interface", "Signal", "Net", "Ref", "Pin"]):
            self.tm_tc_list.InsertColumn(idx, label, width=110)
        self.notebook.AddPage(self.tm_tc_list, "TM/TC")
        self.pin_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for idx, label in enumerate(["Reference", "Pad", "Net", "Type", "Power", "Protocol", "Value", "Properties"]):
            self.pin_list.InsertColumn(idx, label, width=125 if idx != 7 else 260)
        self.pin_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_pin_selected)
        self.notebook.AddPage(self.pin_list, "Board Pins")
        left_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 4)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        group_btn = wx.Button(left, label="Create PCB Group")
        group_btn.Bind(wx.EVT_BUTTON, self.on_create_group)
        export_md_btn = wx.Button(left, label="Export Markdown")
        export_md_btn.Bind(wx.EVT_BUTTON, self.on_export_markdown)
        export_html_btn = wx.Button(left, label="Export HTML")
        export_html_btn.Bind(wx.EVT_BUTTON, self.on_export_html)
        export_csv_btn = wx.Button(left, label="Export CSV")
        export_csv_btn.Bind(wx.EVT_BUTTON, self.on_export_csv)
        highlight_btn = wx.Button(left, label="Highlight Net")
        highlight_btn.Bind(wx.EVT_BUTTON, self.on_highlight_net)
        clear_highlight_btn = wx.Button(left, label="Clear Highlight")
        clear_highlight_btn.Bind(wx.EVT_BUTTON, self.on_clear_highlight)
        for btn in (group_btn, export_md_btn, export_html_btn, export_csv_btn, highlight_btn, clear_highlight_btn):
            button_row.Add(btn, 0, wx.ALL, 4)
        left_sizer.Add(button_row, 0, wx.EXPAND)
        left.SetSizer(left_sizer)

        if FigureCanvas and Figure:
            self.figure = Figure(figsize=(5, 3))
            self.canvas = FigureCanvas(right, -1, self.figure)
            right_sizer.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 4)
        else:
            self.figure = None
            self.canvas = None
            right_sizer.Add(wx.StaticText(right, label="Install matplotlib in KiCad Python to enable the visualizer."), 0, wx.ALL, 8)

        self.html_preview = wx.html.HtmlWindow(right, style=wx.html.HW_SCROLLBAR_AUTO)
        right_sizer.Add(self.html_preview, 1, wx.EXPAND | wx.ALL, 4)
        right.SetSizer(right_sizer)

        splitter.SplitVertically(left, right, 560)
        root.Add(splitter, 1, wx.EXPAND | wx.ALL, 6)

        self.status = wx.StaticText(panel, label="Ready.")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(root)

    def on_browse_dir(self, _event: Any) -> None:
        with wx.DirDialog(self, "Select directory containing KiCad XML netlists") as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.schematic_dir.SetValue(dlg.GetPath())

    def on_analyze(self, _event: Any) -> None:
        try:
            board_order = [b.strip() for b in self.board_sequence.GetValue().split(",") if b.strip()]
            schematic_paths = [self.schematic_dir.GetValue()] if self.schematic_dir.GetValue() else []
            self.parser = SchematicGraphParser(
                board=self.board,
                schematic_paths=schematic_paths,
                board_sequence=board_order,
                pass_through_field=self.pass_field.GetValue() or "NetTie_Path",
            )
            self.parser.build()
            self.interfaces = self.parser.group_interfaces()
            tp_extractor = TestPointExtractor(self.parser)
            self.tp_rows = tp_extractor.as_rows()
            self.tm_tc_rows = self.docgen.make_tm_tc_rows(self.parser)
            self.connector_rows = self.docgen.connector_rows_from_parser(self.parser)
            self.peripheral_rows = self.docgen.peripheral_rows_from_parser(self.parser)
            self.current_markdown = self.docgen.build_markdown(
                tm_tc_rows=self.tm_tc_rows,
                test_point_rows=self.tp_rows,
                interface_maps=self.interfaces,
                connector_rows=self.connector_rows,
                peripheral_rows=self.peripheral_rows,
            )
            self._refresh_board_rows()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay analysis failed", wx.OK | wx.ICON_ERROR)
            return

        self._populate_tables()
        self._draw_interfaces()
        self._update_preview()
        self.status.SetLabel(
            f"Analyzed {len(self.interfaces)} interfaces, {len(self.tp_rows)} test points, "
            f"{len(self.tm_tc_rows)} TM/TC rows."
        )

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

    def on_apply_filters(self, _event: Any) -> None:
        try:
            self._refresh_board_rows()
            self.status.SetLabel(f"Showing {len(self.board_rows)} filtered board pin rows.")
        except Exception as exc:
            wx.MessageBox(str(exc), "Filter failed", wx.OK | wx.ICON_ERROR)

    def on_pin_selected(self, event: Any) -> None:
        row_index = event.GetIndex()
        if row_index < 0 or row_index >= len(self.board_rows):
            return
        net_name = self.board_rows[row_index].get("Net Name", "")
        self._highlight_net_name(net_name)

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

    def _export_file(self, wildcard: str, default_file: str, exporter: Any) -> None:
        if not self.current_markdown:
            wx.MessageBox("Run Analyze before exporting.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        with wx.FileDialog(self, "Export", wildcard=wildcard, defaultFile=default_file, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                exporter(self.current_markdown, dlg.GetPath())
                self.status.SetLabel(f"Exported {dlg.GetPath()}.")

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
            for col, key in enumerate(["Net Name", "Resolved IC", "Resolved IC Function", "IC Pin", "TM/TC Type"], start=1):
                self.tp_list.SetItem(idx, col, str(row.get(key, "")))

        self.tm_tc_list.DeleteAllItems()
        keys = ["Type", "Source Board", "Destination Board", "Interface", "Signal", "Net Name", "Reference", "Pin"]
        for row in self.tm_tc_rows:
            idx = self.tm_tc_list.InsertItem(self.tm_tc_list.GetItemCount(), str(row.get(keys[0], "")))
            for col, key in enumerate(keys[1:], start=1):
                self.tm_tc_list.SetItem(idx, col, str(row.get(key, "")))

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
        if markdown:
            html_text = markdown.markdown(self.current_markdown, extensions=["tables"])
        else:
            html_text = self.docgen._basic_markdown_to_html(self.current_markdown)
        self.html_preview.SetPage(html_text)
