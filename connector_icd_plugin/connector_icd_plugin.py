"""Export connector pin/net tables for ICD reviews."""

from __future__ import annotations

import csv
import os
from typing import Any, Dict, List

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import footprint, select_items
from .guided_ui import add_workflow


def connector_rows(board: Any) -> List[Dict[str, str]]:
    rows = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        value = fp.GetValue()
        if not (ref.upper().startswith(("J", "P", "CN")) or "CONN" in value.upper() or "HEADER" in value.upper()):
            continue
        for pad in fp.Pads():
            net = pad.GetNetname() if hasattr(pad, "GetNetname") else ""
            rows.append({"Connector": ref, "Part": value, "Pin": str(pad.GetNumber()), "Net": net, "Type": str(pad.GetAttribute())})
    return rows


class ConnectorICDPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Connector ICD Builder"
        self.category = "Documentation"
        self.description = "Export connector pin and net tables for interface control documents."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.4.1"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            ConnectorFrame(None, board).Show()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Connector ICD Builder", wx.OK | wx.ICON_ERROR)


class ConnectorFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Connector ICD Builder", size=(850, 560))
        self.board = board
        self.rows: List[Dict[str, str]] = []
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(
            panel, root, "Connector ICD Builder",
            "Load connector pins, verify them against the PCB, then export the reviewed table.",
            ("Load", "Review on PCB", "Export"),
        )
        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.select_row)
        for index, label in enumerate(("Connector", "Part", "Pin", "Net", "Type")):
            self.list.InsertColumn(index, label, width=160 if index < 2 else 130)
        root.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        export = wx.Button(panel, label="Export CSV")
        export.Bind(wx.EVT_BUTTON, self.export_csv)
        refresh = wx.Button(panel, label="Refresh Preview")
        refresh.Bind(wx.EVT_BUTTON, self.refresh)
        select = wx.Button(panel, label="Select on PCB")
        select.Bind(wx.EVT_BUTTON, self.select_row)
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row.Add(refresh, 0, wx.ALL, 5); row.Add(select, 0, wx.ALL, 5); row.Add(export, 0, wx.ALL, 5); row.Add(help_btn, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT)
        self.status = wx.StaticText(panel, label="Loading connector pins...")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(root)
        self.refresh(None)
        self.Centre()

    def refresh(self, _event: Any) -> None:
        self.rows = connector_rows(self.board)
        self.list.DeleteAllItems()
        for row in self.rows:
            index = self.list.InsertItem(self.list.GetItemCount(), row["Connector"])
            for col, key in enumerate(("Part", "Pin", "Net", "Type"), 1): self.list.SetItem(index, col, row[key])
        self.status.SetLabel(f"Preview contains {len(self.rows)} connector pins.")
        self.workflow.set_step(1 if self.rows else 0, "Select representative rows on the PCB before exporting." if self.rows else "Check connector references/values, then Refresh.")

    def export_csv(self, _event: Any) -> None:
        with wx.FileDialog(self, "Export connector ICD", wildcard="CSV files (*.csv)|*.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            with open(dialog.GetPath(), "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Connector", "Part", "Pin", "Net", "Type"]); writer.writeheader(); writer.writerows(self.rows)
        wx.MessageBox(f"Exported {len(self.rows)} connector pins.", "KiWay", wx.OK | wx.ICON_INFORMATION)
        self.workflow.set_step(3, "Open the CSV and complete the ICD review/sign-off.")

    def select_row(self, event: Any) -> None:
        index = event.GetIndex() if hasattr(event, "GetIndex") else self.list.GetFirstSelected()
        if index < 0 or index >= len(self.rows):
            wx.MessageBox("Select a connector-pin row first.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        row = self.rows[index]
        owner = footprint(self.board, row["Connector"])
        pads = [pad for pad in owner.Pads() if str(pad.GetNumber()) == row["Pin"]] if owner else []
        select_items(self.board, pads or [owner])
        self.status.SetLabel(f"Selected {row['Connector']} pin {row['Pin']} on the PCB.")
        self.workflow.set_step(2, "Continue spot-checking rows or export the reviewed connector table.")
