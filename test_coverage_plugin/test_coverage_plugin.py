"""Test-point coverage report for board nets."""

from __future__ import annotations

import csv
import os
from typing import Any, Dict, List

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import pads_on_net, select_items
from .guided_ui import add_workflow


def coverage_rows(board: Any) -> List[Dict[str, str]]:
    testpoints = []
    covered = set()
    for fp in board.GetFootprints():
        ref = fp.GetReference(); value = fp.GetValue()
        is_tp = ref.upper().startswith("TP") or "TESTPOINT" in value.upper()
        for pad in fp.Pads():
            net = pad.GetNetname() if hasattr(pad, "GetNetname") else ""
            if is_tp and net: testpoints.append((ref, net)); covered.add(net)
    nets = set()
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            net = pad.GetNetname() if hasattr(pad, "GetNetname") else ""
            if net: nets.add(net)
    rows = []
    for net in sorted(nets):
        points = [ref for ref, point_net in testpoints if point_net == net]
        rows.append({"Net": net, "Test Points": ", ".join(points), "Status": "Covered" if points else "Missing", "Count": str(len(points))})
    return rows


class TestCoveragePlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Test Coverage Planner"
        self.category = "Inspection"
        self.description = "Report board-net coverage by test points."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.4.0"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            TestCoverageFrame(None, board).Show()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Test Coverage Planner", wx.OK | wx.ICON_ERROR)


class TestCoverageFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Test Coverage Planner", size=(820, 560))
        self.board = board; self.rows: List[Dict[str, str]] = []
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(panel, root, "Test Coverage Planner", "Scan named nets, inspect missing access on the PCB, then export the fixture-planning table.", ("Scan", "Inspect gaps", "Export"))
        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.select_net)
        for idx, label in enumerate(("Net", "Test Points", "Status", "Count")): self.list.InsertColumn(idx, label, width=270 if idx < 2 else 120)
        root.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Scan Preview", self.scan), ("Export CSV", self.export_csv)):
            button = wx.Button(panel, label=label); button.Bind(wx.EVT_BUTTON, handler); row.Add(button, 0, wx.ALL, 5)
        select = wx.Button(panel, label="Select Net on PCB")
        select.Bind(wx.EVT_BUTTON, self.select_net)
        row.Add(select, 0, wx.ALL, 5)
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row.Add(help_btn, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT)
        self.status = wx.StaticText(panel, label="Scanning named nets...")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(root); self.scan(None); self.Centre()

    def scan(self, _event: Any) -> None:
        self.rows = coverage_rows(self.board); self.list.DeleteAllItems()
        for row in self.rows:
            i = self.list.InsertItem(self.list.GetItemCount(), row["Net"])
            for col, key in enumerate(("Test Points", "Status", "Count"), 1): self.list.SetItem(i, col, row[key])
        missing = sum(row["Status"] == "Missing" for row in self.rows)
        self.status.SetLabel(f"Preview: {len(self.rows)} nets, {missing} missing test-point access.")
        self.workflow.set_step(1, "Inspect Missing rows on the PCB and document intentional exclusions.")

    def export_csv(self, _event: Any) -> None:
        with wx.FileDialog(self, "Export test coverage", wildcard="CSV files (*.csv)|*.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            with open(dialog.GetPath(), "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Net", "Test Points", "Status", "Count"]); writer.writeheader(); writer.writerows(self.rows)
        self.workflow.set_step(3, "Review physical probe access and use the CSV for fixture planning.")

    def select_net(self, event: Any) -> None:
        index = event.GetIndex() if hasattr(event, "GetIndex") else self.list.GetFirstSelected()
        if index < 0 or index >= len(self.rows):
            wx.MessageBox("Select a net row first.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        select_items(self.board, pads_on_net(self.board, self.rows[index]["Net"]))
        self.status.SetLabel(f"Selected net {self.rows[index]['Net']} on the PCB.")
        self.workflow.set_step(2, "Continue reviewing missing nets or export the coverage table.")
