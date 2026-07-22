"""Board-level net quality checks with CSV export."""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from typing import Any, Dict, List

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import footprint, pads_on_net, select_items
from .guided_ui import add_workflow


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
        self.version = "0.4.1"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            NetHygieneFrame(None, board).Show()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Net Hygiene", wx.OK | wx.ICON_ERROR)


class NetHygieneFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Net Hygiene", size=(900, 560))
        self.board = board; self.issues: List[Dict[str, str]] = []
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(panel, root, "Net Hygiene", "Scan the board, inspect each finding in context, then export the reviewed issue list.", ("Scan", "Inspect", "Export"))
        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.select_issue)
        for idx, label in enumerate(("Severity", "Kind", "Object", "Details")): self.list.InsertColumn(idx, label, width=180 if idx != 3 else 360)
        root.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Scan Preview", self.scan), ("Export CSV", self.export_csv)):
            button = wx.Button(panel, label=label); button.Bind(wx.EVT_BUTTON, handler); row.Add(button, 0, wx.ALL, 5)
        select = wx.Button(panel, label="Select on PCB")
        select.Bind(wx.EVT_BUTTON, self.select_issue)
        row.Add(select, 0, wx.ALL, 5)
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row.Add(help_btn, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT)
        self.status = wx.StaticText(panel, label="Scanning board...")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(root); self.scan(None); self.Centre()

    def scan(self, _event: Any) -> None:
        self.issues = find_issues(self.board); self.list.DeleteAllItems()
        for issue in self.issues:
            i = self.list.InsertItem(self.list.GetItemCount(), issue["Severity"])
            for col, key in enumerate(("Kind", "Object", "Details"), 1): self.list.SetItem(i, col, issue[key])
        self.status.SetLabel(f"Preview contains {len(self.issues)} findings. Double-click a row to inspect it on the PCB.")
        self.workflow.set_step(1, "Inspect findings on the PCB and decide which are defects versus documented exceptions.")

    def export_csv(self, _event: Any) -> None:
        with wx.FileDialog(self, "Export net hygiene report", wildcard="CSV files (*.csv)|*.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            with open(dialog.GetPath(), "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Severity", "Kind", "Object", "Details"]); writer.writeheader(); writer.writerows(self.issues)
        self.workflow.set_step(3, "Attach the CSV to the design review and resolve or document each finding.")

    def select_issue(self, event: Any) -> None:
        index = event.GetIndex() if hasattr(event, "GetIndex") else self.list.GetFirstSelected()
        if index < 0 or index >= len(self.issues):
            wx.MessageBox("Select an issue row first.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        value = self.issues[index]["Object"]
        if "." in value:
            ref, pad_number = value.split(".", 1)
            owner = footprint(self.board, ref)
            targets = [pad for pad in owner.Pads() if str(pad.GetNumber()) == pad_number] if owner else []
        else:
            targets = pads_on_net(self.board, value) or [footprint(self.board, value)]
        select_items(self.board, targets)
        self.status.SetLabel(f"Selected {value} on the PCB.")
        self.workflow.set_step(2, "Continue inspecting findings or export the reviewed list.")
