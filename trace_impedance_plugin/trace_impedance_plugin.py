"""wxPython UI for routed trace RLC and impedance analysis."""

from __future__ import annotations

import csv
import os
from typing import Any, List, Optional

import pcbnew
import wx

from .measurement import PathMeasurement, TraceMeasurementEngine
from .help_utils import open_help


class TraceImpedancePlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Trace RLC / Impedance Analyzer"
        self.category = "Analysis"
        self.description = "Measure routed net geometry and estimate RLC, impedance, vias, layers, and zones."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.3.0"

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
        super().__init__(parent, title="KiWay Trace RLC / Impedance Analyzer", size=(980, 680))
        self.board = board
        self.engine = TraceMeasurementEngine(board)
        self.current: Optional[PathMeasurement] = None
        self._build_ui()
        self._load_nets()
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        config = wx.FlexGridSizer(0, 2, 6, 8)
        self.net = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.start = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.end = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.diff_net = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.frequency = wx.TextCtrl(panel, value="100")
        self.reference = wx.ComboBox(panel, choices=["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"], style=wx.CB_READONLY)
        self.reference.SetSelection(0)
        for label, control in (("Net:", self.net), ("Start pad:", self.start), ("End pad:", self.end), ("Differential mate (optional):", self.diff_net), ("Frequency (MHz):", self.frequency), ("Reference layer:", self.reference)):
            config.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL); config.Add(control, 1, wx.EXPAND)
        config.AddGrowableCol(1, 1); root.Add(config, 0, wx.EXPAND | wx.ALL, 10)
        self.net.Bind(wx.EVT_COMBOBOX, self._load_pads)
        self.measure_button = wx.Button(panel, label="Analyze Path")
        self.measure_button.Bind(wx.EVT_BUTTON, self.analyze)
        export = wx.Button(panel, label="Export CSV")
        export.Bind(wx.EVT_BUTTON, self.export_csv)
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row = wx.BoxSizer(wx.HORIZONTAL); row.Add(self.measure_button, 0, wx.ALL, 5); row.Add(export, 0, wx.ALL, 5); row.Add(help_btn, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT)
        self.summary = wx.StaticText(panel, label="Select a net and optional start/end pads.")
        root.Add(self.summary, 0, wx.EXPAND | wx.ALL, 8)
        self.table = wx.ListCtrl(panel, style=wx.LC_REPORT)
        for index, label in enumerate(("Metric", "Value")):
            self.table.InsertColumn(index, label, width=260 if index == 0 else 620)
        root.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.notes = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        root.Add(self.notes, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(root)

    def _load_nets(self) -> None:
        names = self.engine.net_names()
        self.net.AppendItems(names); self.diff_net.Append("<none>"); self.diff_net.AppendItems(names)
        if names: self.net.SetSelection(0); self._load_pads(None)

    def _load_pads(self, _event: Any) -> None:
        pads = self.engine.pads_for_net(self.net.GetValue())
        self.start.Clear(); self.end.Clear(); self.start.AppendItems(pads); self.end.AppendItems(pads)
        if pads: self.start.SetSelection(0); self.end.SetSelection(len(pads) - 1)

    def analyze(self, _event: Any) -> None:
        try:
            self.current = self.engine.measure(self.net.GetValue(), self.start.GetValue(), self.end.GetValue(), float(self.frequency.GetValue()), self.reference.GetValue())
            self._show(self.current)
        except Exception as exc:
            wx.MessageBox(str(exc), "Trace analysis failed", wx.OK | wx.ICON_ERROR)

    def _show(self, result: PathMeasurement) -> None:
        self.table.DeleteAllItems()
        for key, value in result.as_dict().items():
            index = self.table.InsertItem(self.table.GetItemCount(), key); self.table.SetItem(index, 1, str(value))
        self.notes.SetValue("\n".join(result.notes))
        self.summary.SetLabel(f"{result.net_name}: {result.length_mm:.3f} mm, {result.via_count} vias, {result.layer_changes} layer changes, {result.zone_count} zones")

    def export_csv(self, _event: Any) -> None:
        if not self.current:
            wx.MessageBox("Analyze a path first.", "KiWay", wx.OK | wx.ICON_INFORMATION); return
        with wx.FileDialog(self, "Export trace measurement", wildcard="CSV files (*.csv)|*.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            row = self.current.as_dict()
            with open(dialog.GetPath(), "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
