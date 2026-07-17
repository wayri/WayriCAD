"""Board-level net quality checks with CSV export."""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from typing import Any, Dict, List

import pcbnew
import wx


def find_issues(board: Any) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    refs = defaultdict(list)
    nets = defaultdict(list)
    for fp in board.GetFootprints():
        refs[fp.GetReference()].append(fp.GetValue())
        for pad in fp.Pads():
            net = pad.GetNetname() if hasattr(pad, "GetNetname") else ""
            if net: nets[net].append(f"{fp.GetReference()}.{pad.GetNumber()}")
            else: issues.append({"Severity": "warning", "Kind": "unconnected-pad", "Object": f"{fp.GetReference()}.{pad.GetNumber()}", "Details": "Pad has no net assignment"})
    for ref, values in refs.items():
        if len(values) > 1: issues.append({"Severity": "error", "Kind": "duplicate-reference", "Object": ref, "Details": ", ".join(values)})
    for net, pads in nets.items():
        if len(pads) == 1: issues.append({"Severity": "warning", "Kind": "single-pad-net", "Object": net, "Details": pads[0]})
        if net.lower() in {"", "net-(none)", "unconnected-(none)"}: issues.append({"Severity": "warning", "Kind": "suspicious-net-name", "Object": net, "Details": "Review generated or unnamed net"})
    return issues


class NetHygienePlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Net Hygiene"
        self.category = "Inspection"
        self.description = "Find common PCB net and reference quality issues."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.2.0"

    def Run(self) -> None: NetHygieneFrame(None, pcbnew.GetBoard()).Show()


class NetHygieneFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Net Hygiene", size=(900, 560))
        self.board = board; self.issues: List[Dict[str, str]] = []
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        for idx, label in enumerate(("Severity", "Kind", "Object", "Details")): self.list.InsertColumn(idx, label, width=180 if idx != 3 else 360)
        root.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Scan", self.scan), ("Export CSV", self.export_csv)):
            button = wx.Button(panel, label=label); button.Bind(wx.EVT_BUTTON, handler); row.Add(button, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT); panel.SetSizer(root); self.scan(None); self.Centre()

    def scan(self, _event: Any) -> None:
        self.issues = find_issues(self.board); self.list.DeleteAllItems()
        for issue in self.issues:
            i = self.list.InsertItem(self.list.GetItemCount(), issue["Severity"])
            for col, key in enumerate(("Kind", "Object", "Details"), 1): self.list.SetItem(i, col, issue[key])

    def export_csv(self, _event: Any) -> None:
        with wx.FileDialog(self, "Export net hygiene report", wildcard="CSV files (*.csv)|*.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            with open(dialog.GetPath(), "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Severity", "Kind", "Object", "Details"]); writer.writeheader(); writer.writerows(self.issues)
