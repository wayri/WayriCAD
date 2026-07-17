"""Conservative radial fanout generator for selected/all SMD pads."""

from __future__ import annotations

import math
import os
from typing import Any, List, Tuple

import pcbnew
import wx

from .help_utils import open_help


def _coord(value: Any) -> float:
    return float(value) / 1_000_000.0 if hasattr(value, "__float__") else float(value)


class FanoutGeneratorPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Fanout Generator"
        self.category = "Routing"
        self.description = "Generate conservative radial fanout tracks from SMD pads."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.4.0"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            FanoutFrame(None, board).Show()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Fanout Generator", wx.OK | wx.ICON_ERROR)


class FanoutFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Fanout Generator", size=(620, 420))
        self.board = board
        self.preview_items: List[Any] = []
        self.undo_stack: List[List[Any]] = []
        self.redo_stack: List[List[Any]] = []
        self._build_ui()
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 6, 8)
        self.ref = wx.TextCtrl(panel, value="")
        self.width = wx.TextCtrl(panel, value="0.20")
        self.length = wx.TextCtrl(panel, value="1.50")
        self.clearance = wx.TextCtrl(panel, value="0.30")
        self.pattern = wx.ComboBox(panel, choices=["Radial", "BGA/LGA Grid Escape", "Perimeter Escape"], style=wx.CB_READONLY)
        self.pattern.SetSelection(0)
        self.escape_layer = wx.ComboBox(panel, choices=["Pad layer", "F.Cu", "B.Cu"], style=wx.CB_READONLY)
        self.escape_layer.SetSelection(0)
        self.add_vias = wx.CheckBox(panel, label="Add escape vias")
        self.via_diameter = wx.TextCtrl(panel, value="0.60")
        self.via_drill = wx.TextCtrl(panel, value="0.30")
        for label, control in (("Footprint reference (blank = all):", self.ref), ("Pattern:", self.pattern), ("Track width (mm):", self.width), ("Fanout length (mm):", self.length), ("Pad clearance (mm):", self.clearance), ("Escape layer:", self.escape_layer), ("Via diameter (mm):", self.via_diameter), ("Via drill (mm):", self.via_drill)):
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(control, 1, wx.EXPAND)
        grid.AddGrowableCol(1, 1)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        root.Add(self.add_vias, 0, wx.LEFT | wx.RIGHT, 10)
        self.status = wx.StaticText(panel, label="Select a footprint reference or leave blank for all SMD footprints.")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        actions = (("Preview", self.preview), ("Clear Preview", self.clear_preview), ("Generate", self.generate), ("Undo", self.undo), ("Redo", self.redo))
        for text, handler in actions:
            button = wx.Button(panel, label=text)
            button.Bind(wx.EVT_BUTTON, handler)
            row.Add(button, 0, wx.ALL, 5)
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row.Add(help_btn, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        panel.SetSizer(root)

    def _layer(self, pad: Any) -> int:
        choice = self.escape_layer.GetValue()
        if choice == "F.Cu": return pcbnew.F_Cu
        if choice == "B.Cu": return pcbnew.B_Cu
        return pad.GetLayer()

    def _plan(self) -> List[Tuple[Any, Any, Any]]:
        try:
            width = pcbnew.FromMM(float(self.width.GetValue()))
            length = pcbnew.FromMM(float(self.length.GetValue()))
            via_diameter = pcbnew.FromMM(float(self.via_diameter.GetValue()))
            via_drill = pcbnew.FromMM(float(self.via_drill.GetValue()))
        except (TypeError, ValueError):
            raise ValueError("Width and length must be numeric millimetre values.")
        wanted = self.ref.GetValue().strip().upper()
        result = []
        for fp in self.board.GetFootprints():
            if wanted and fp.GetReference().upper() != wanted:
                continue
            for pad in fp.Pads():
                if pad.GetAttribute() not in (getattr(pcbnew, "PAD_ATTRIB_SMD", 0), 0):
                    continue
                pos = pad.GetPosition()
                center = fp.GetPosition()
                angle = math.atan2(_coord(pos.y) - _coord(center.y), _coord(pos.x) - _coord(center.x))
                if self.pattern.GetValue() == "BGA/LGA Grid Escape":
                    # Grid escape is radial for inner pads and orthogonal for
                    # edge pads, which provides a useful BGA/LGA starting pattern.
                    dx = _coord(pos.x) - _coord(center.x)
                    dy = _coord(pos.y) - _coord(center.y)
                    if abs(dx) >= abs(dy):
                        angle = 0.0 if dx >= 0 else math.pi
                    else:
                        angle = math.pi / 2 if dy >= 0 else -math.pi / 2
                elif self.pattern.GetValue() == "Perimeter Escape":
                    angle = math.atan2(_coord(pos.y) - _coord(center.y), _coord(pos.x) - _coord(center.x))
                end = pcbnew.VECTOR2I(pos.x + int(math.cos(angle) * length), pos.y + int(math.sin(angle) * length))
                result.append((pad, end, width, via_diameter, via_drill))
        return result

    def preview(self, _event: Any) -> None:
        try:
            self.clear_preview(None)
            plan = self._plan()
            for pad, end, width, _diameter, _drill in plan:
                track = pcbnew.PCB_TRACK(self.board)
                track.SetStart(pad.GetPosition()); track.SetEnd(end); track.SetWidth(width); track.SetLayer(self._layer(pad)); track.SetNetCode(pad.GetNetCode())
                self.board.Add(track); self.preview_items.append(track)
            if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
            self.status.SetLabel(f"Previewing {len(plan)} fanout tracks. Clear or Generate to continue.")
        except Exception as exc:
            self.status.SetLabel(str(exc))

    def clear_preview(self, _event: Any) -> None:
        for item in self.preview_items:
            try: self.board.Remove(item)
            except Exception: pass
        self.preview_items = []
        if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()

    def generate(self, _event: Any) -> None:
        try:
            self.clear_preview(None)
            plan = self._plan()
            created = []
            for pad, end, width, diameter, drill in plan:
                track = pcbnew.PCB_TRACK(self.board)
                track.SetStart(pad.GetPosition())
                track.SetEnd(end)
                track.SetWidth(width)
                track.SetLayer(self._layer(pad))
                track.SetNetCode(pad.GetNetCode())
                self.board.Add(track)
                created.append(track)
                if self.add_vias.GetValue() and pad.GetNetCode():
                    via = pcbnew.PCB_VIA(self.board)
                    via.SetPosition(end); via.SetDrill(int(drill)); via.SetWidth(int(diameter)); via.SetNetCode(pad.GetNetCode())
                    self.board.Add(via); created.append(via)
            self.undo_stack.append(created); self.redo_stack.clear()
            if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
            self.status.SetLabel(f"Generated {len(plan)} fanout tracks. Review clearance and routing before fabrication.")
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Fanout Generator", wx.OK | wx.ICON_ERROR)

    def undo(self, _event: Any) -> None:
        if not self.undo_stack: return
        items = self.undo_stack.pop()
        for item in items:
            try: self.board.Remove(item)
            except Exception: pass
        self.redo_stack.append(items)
        if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
        self.status.SetLabel("Last fanout operation undone.")

    def redo(self, _event: Any) -> None:
        if not self.redo_stack: return
        items = self.redo_stack.pop()
        for item in items:
            try: self.board.Add(item)
            except Exception: pass
        self.undo_stack.append(items)
        if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
        self.status.SetLabel("Last fanout operation redone.")
