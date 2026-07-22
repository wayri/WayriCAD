"""wxPython UI for routed trace RLC and impedance analysis."""

from __future__ import annotations

import csv
import os
from typing import Any, List, Optional

import pcbnew
import wx

from .measurement import PathMeasurement, TraceMeasurementEngine
from .help_utils import open_help
from .selection_utils import pads_on_net, select_items
from .guided_ui import add_workflow


class TraceImpedancePlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Trace RLC / Impedance Analyzer"
        self.category = "Analysis"
        self.description = "Measure routed net geometry and estimate RLC, impedance, vias, layers, and zones."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.5.0"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            TraceFrame(None, board).Show()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Trace RLC / Impedance Analyzer", wx.OK | wx.ICON_ERROR)


class TraceFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Trace RLC / Impedance Analyzer", size=(1120, 840), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.board = board
        self.engine = TraceMeasurementEngine(board)
        self.current: Optional[PathMeasurement] = None
        self.last_selection_signature = ()
        self.selection_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_selection_timer, self.selection_timer)
        self._build_ui()
        self._load_nets()
        self._load_stackup()
        self.selection_timer.Start(500)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(panel, root, "Trace RLC / Impedance Analyzer", "Choose a route and stackup context, preview measured geometry, then export the engineering estimate.", ("Configure path", "Review result", "Export"))
        config = wx.FlexGridSizer(0, 2, 6, 8)
        self.net = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.start = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.end = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.diff_net = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.frequency = wx.TextCtrl(panel, value="100")
        self.reference = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.auto_refresh = wx.CheckBox(panel, label="Auto-refresh from PCB selection")
        self.auto_refresh.SetValue(True)
        for label, control in (("Net:", self.net), ("Start pad:", self.start), ("End pad:", self.end), ("Differential mate (optional):", self.diff_net), ("Frequency (MHz):", self.frequency), ("Reference layer:", self.reference)):
            config.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL); config.Add(control, 1, wx.EXPAND)
        config.AddGrowableCol(1, 1); root.Add(config, 0, wx.EXPAND | wx.ALL, 10)
        self.net.Bind(wx.EVT_COMBOBOX, self._load_pads)
        self.measure_button = wx.Button(panel, label="Analyze Path")
        self.measure_button.Bind(wx.EVT_BUTTON, self.analyze)
        export = wx.Button(panel, label="Export CSV")
        export.Bind(wx.EVT_BUTTON, self.export_csv)
        select = wx.Button(panel, label="Select Net on PCB")
        select.Bind(wx.EVT_BUTTON, self.select_net)
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row = wx.BoxSizer(wx.HORIZONTAL); row.Add(self.measure_button, 0, wx.ALL, 5); row.Add(select, 0, wx.ALL, 5); row.Add(export, 0, wx.ALL, 5); row.Add(help_btn, 0, wx.ALL, 5)
        refresh_stackup = wx.Button(panel, label="Refresh Stackup")
        refresh_stackup.Bind(wx.EVT_BUTTON, self._load_stackup)
        row.Add(refresh_stackup, 0, wx.ALL, 5)
        row.Add(self.auto_refresh, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT)
        self.summary = wx.StaticText(panel, label="Select a net and optional start/end pads.")
        root.Add(self.summary, 0, wx.EXPAND | wx.ALL, 8)
        stackup_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Detected Board Stackup"), wx.VERTICAL)
        self.stackup_list = wx.ListCtrl(stackup_box.GetStaticBox(), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.stackup_list.SetMinSize((-1, 150))
        for index, label in enumerate(("Layer", "Type", "Copper mm", "Dielectric mm", "Er", "Material")):
            self.stackup_list.InsertColumn(index, label, width=150 if index in (0, 5) else 105)
        stackup_box.Add(self.stackup_list, 1, wx.EXPAND | wx.ALL, 3)
        root.Add(stackup_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.table = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.table.SetMinSize((-1, 190))
        for index, label in enumerate(("Metric", "Value")):
            self.table.InsertColumn(index, label, width=260 if index == 0 else 620)
        root.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.notes = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.notes.SetMinSize((-1, 100))
        root.Add(self.notes, 1, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(root)
        self.workflow.set_step(0, "Select a net, endpoints, frequency, and reference layer; then Analyze Path.")

    def _load_nets(self) -> None:
        names = self.engine.net_names()
        self.net.AppendItems(names); self.diff_net.Append("<none>"); self.diff_net.AppendItems(names)
        if names: self.net.SetSelection(0); self._load_pads(None)

    def _load_stackup(self, _event: Any = None) -> None:
        layers = self.engine.stackup_layers()
        names = [layer.name for layer in layers]
        self.reference.Clear()
        reference_names = [layer.name for layer in layers if layer.name.endswith(".Cu") or "copper" in layer.kind.lower() or layer.kind == "routed"]
        self.reference.AppendItems(reference_names)
        if reference_names:
            self.reference.SetSelection(0)
        self.stackup_list.DeleteAllItems()
        for layer in layers:
            index = self.stackup_list.InsertItem(self.stackup_list.GetItemCount(), layer.name)
            values = (layer.kind, f"{layer.thickness_mm:.4f}", f"{layer.dielectric_height_mm:.4f}", f"{layer.relative_permittivity:.4g}", layer.material)
            for column, value in enumerate(values, 1):
                self.stackup_list.SetItem(index, column, str(value))
        self.summary.SetLabel(f"Detected {len(layers)} stackup layers ({len(reference_names)} copper references). The selected reference is used in C/L/Z0 math.")

    def _load_pads(self, _event: Any) -> None:
        pads = self.engine.pads_for_net(self.net.GetValue())
        self.start.Clear(); self.end.Clear(); self.start.AppendItems(pads); self.end.AppendItems(pads)
        if pads: self.start.SetSelection(0); self.end.SetSelection(len(pads) - 1)

    def analyze(self, _event: Any) -> None:
        try:
            self.current = self.engine.measure(self.net.GetValue(), self.start.GetValue(), self.end.GetValue(), float(self.frequency.GetValue()), self.reference.GetValue())
            self._show(self.current)
            self.workflow.set_step(2, "Review route geometry and notes, cross-select the net, then export if appropriate.")
        except Exception as exc:
            wx.MessageBox(str(exc), "Trace analysis failed", wx.OK | wx.ICON_ERROR)

    def select_net(self, _event: Any) -> None:
        net_name = self.net.GetValue()
        targets = list(pads_on_net(self.board, net_name))
        targets.extend(item for item in getattr(self.board, "GetTracks", lambda: [])() if str(getattr(item, "GetNetname", lambda: "")()) == net_name)
        count = select_items(self.board, targets)
        self.summary.SetLabel(f"Selected {count} pads/tracks on {net_name} in PCB Editor.")

    def _show(self, result: PathMeasurement) -> None:
        self.table.DeleteAllItems()
        for key, value in result.as_dict().items():
            index = self.table.InsertItem(self.table.GetItemCount(), key); self.table.SetItem(index, 1, str(value))
        self.notes.SetValue("\n".join(result.notes))
        self.summary.SetLabel(f"{result.net_name}: {result.length_mm:.3f} mm | reference {result.reference_layer} | h={result.dielectric_height_mm:.4f} mm | Er={result.relative_permittivity:.3g} | {result.via_count} vias")
        if result.board_items:
            select_items(self.board, result.board_items + pads_on_net(self.board, result.net_name))

    def _selected_board_items(self) -> list[Any]:
        items = []
        for footprint in self.board.GetFootprints():
            items.extend(pad for pad in footprint.Pads() if bool(getattr(pad, "IsSelected", lambda: False)()))
        items.extend(item for item in getattr(self.board, "GetTracks", lambda: [])() if bool(getattr(item, "IsSelected", lambda: False)()))
        return items

    def on_selection_timer(self, _event: Any) -> None:
        if not self.auto_refresh.GetValue():
            return
        try:
            items = self._selected_board_items()
            signature = tuple(sorted(id(item) for item in items))
            if signature == self.last_selection_signature:
                return
            self.last_selection_signature = signature
            net_names = [str(getattr(item, "GetNetname", lambda: "")()) for item in items]
            net_name = next((name for name in net_names if name), "")
            if net_name and self.net.FindString(net_name) != wx.NOT_FOUND:
                self.net.SetValue(net_name)
                self._load_pads(None)
            selected_pads = []
            for footprint in self.board.GetFootprints():
                for pad in footprint.Pads():
                    if bool(getattr(pad, "IsSelected", lambda: False)()):
                        selected_pads.append(f"{footprint.GetReference()}.{pad.GetNumber()}")
            if selected_pads:
                self.start.SetValue(selected_pads[0])
                self.end.SetValue(selected_pads[-1])
            self.summary.SetLabel(f"PCB selection: {len(items)} routed items; net {net_name or 'none'}; {len(selected_pads)} endpoint pads.")
        except Exception:
            pass

    def on_close(self, event: Any) -> None:
        self.selection_timer.Stop()
        event.Skip()

    def export_csv(self, _event: Any) -> None:
        if not self.current:
            wx.MessageBox("Analyze a path first.", "KiWay", wx.OK | wx.ICON_INFORMATION); return
        with wx.FileDialog(self, "Export trace measurement", wildcard="CSV files (*.csv)|*.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            row = self.current.as_dict()
            with open(dialog.GetPath(), "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
            self.workflow.set_step(3, "Validate critical results with a field solver or measurement before release.")
