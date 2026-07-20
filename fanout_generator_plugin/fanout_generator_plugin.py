"""Conservative radial fanout generator for selected/all SMD pads."""

from __future__ import annotations

import math
import os
from typing import Any, List, Tuple

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import select_items
from .guided_ui import add_workflow
from .geometry_preview import GeometryPreview


def _coord(value: Any) -> float:
    return float(value) / 1_000_000.0 if hasattr(value, "__float__") else float(value)


class FanoutGeneratorPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Fanout Generator"
        self.category = "Routing"
        self.description = "Generate conservative radial fanout tracks from SMD pads."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.5.0"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            dialog = FanoutFrame(None, board)
            dialog.ShowModal()
            dialog.Destroy()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Fanout Generator", wx.OK | wx.ICON_ERROR)


class FanoutFrame(wx.Dialog):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Fanout Generator", size=(860, 820), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.board = board
        self.preview_plan: List[Tuple[Any, Any, Any, Any, Any, Any]] = []
        self.preview_items: List[Any] = []
        self.undo_stack: List[List[Any]] = []
        self.redo_stack: List[List[Any]] = []
        self._build_ui()
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(
            panel,
            root,
            "Fanout Generator",
            "Review geometry in this window first, show it temporarily on the PCB second, then commit the exact preview.",
            ("Configure", "Window preview", "PCB preview", "Commit"),
        )
        grid = wx.FlexGridSizer(0, 2, 6, 8)
        self.ref = wx.TextCtrl(panel, value="")
        self.width = wx.TextCtrl(panel, value="0.20")
        self.length = wx.TextCtrl(panel, value="1.50")
        self.pattern = wx.ComboBox(panel, choices=["Radial", "BGA/LGA Grid Escape", "Perimeter Escape"], style=wx.CB_READONLY)
        self.pattern.SetSelection(0)
        self.escape_layer = wx.ComboBox(panel, choices=["Pad layer", "F.Cu", "B.Cu"], style=wx.CB_READONLY)
        self.escape_layer.SetSelection(0)
        self.add_vias = wx.CheckBox(panel, label="Add escape vias")
        self.via_diameter = wx.TextCtrl(panel, value="0.60")
        self.via_drill = wx.TextCtrl(panel, value="0.30")
        for label, control in (("Footprint reference (blank = all):", self.ref), ("Pattern:", self.pattern), ("Track width (mm):", self.width), ("Fanout length (mm):", self.length), ("Escape layer:", self.escape_layer), ("Via diameter (mm):", self.via_diameter), ("Via drill (mm):", self.via_drill)):
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(control, 1, wx.EXPAND)
        grid.AddGrowableCol(1, 1)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        root.Add(self.add_vias, 0, wx.LEFT | wx.RIGHT, 10)
        self.geometry_preview = GeometryPreview(panel, "Configure settings, then click Preview in Window.")
        root.Add(self.geometry_preview, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.preview_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("Footprint", 110), ("Pad", 80), ("Net", 220), ("Layer", 100), ("Result", 140))):
            self.preview_list.InsertColumn(index, label, width=width)
        root.Add(self.preview_list, 1, wx.EXPAND | wx.ALL, 10)
        self.status = wx.StaticText(panel, label="No preview yet.")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        actions = (
            ("Preview in Window", self.preview),
            ("Show on PCB", self.show_on_pcb),
            ("Clear Preview", self.clear_preview),
            ("Commit to PCB", self.generate),
            ("Undo Last Commit", self.undo),
            ("Redo Last Commit", self.redo),
        )
        for text, handler in actions:
            button = wx.Button(panel, label=text)
            button.Bind(wx.EVT_BUTTON, handler)
            row.Add(button, 0, wx.ALL, 5)
            if text == "Show on PCB":
                self.show_button = button
                button.Enable(False)
                button.SetToolTip("Temporarily add the reviewed window preview to the PCB and select it.")
            elif text == "Commit to PCB":
                self.commit_button = button
                button.Enable(False)
                button.SetToolTip("Keep the exact temporary PCB preview as one plugin operation.")
            elif text == "Undo Last Commit":
                self.undo_button = button
                button.Enable(False)
                button.SetToolTip("Remove every item from the most recent fanout commit.")
            elif text == "Redo Last Commit":
                self.redo_button = button
                button.Enable(False)
                button.SetToolTip("Restore every item removed by Undo Last Commit.")
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row.Add(help_btn, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        panel.SetSizer(root)
        for control in (self.ref, self.width, self.length, self.via_diameter, self.via_drill):
            control.Bind(wx.EVT_TEXT, self.on_config_changed)
        for control in (self.pattern, self.escape_layer):
            control.Bind(wx.EVT_COMBOBOX, self.on_config_changed)
        self.add_vias.Bind(wx.EVT_CHECKBOX, self.on_config_changed)
        self.workflow.set_step(0, "Choose a footprint and geometry, then Preview in Window.")

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
                result.append((fp, pad, end, width, via_diameter, via_drill))
        return result

    def preview(self, _event: Any) -> None:
        try:
            self.clear_preview(None)
            self.preview_plan = self._plan()
            lines = []
            points = []
            for fp, pad, end, _width, _diameter, _drill in self.preview_plan:
                start = pad.GetPosition()
                lines.append((
                    pcbnew.ToMM(start.x),
                    pcbnew.ToMM(start.y),
                    pcbnew.ToMM(end.x),
                    pcbnew.ToMM(end.y),
                ))
                if self.add_vias.GetValue() and pad.GetNetCode():
                    points.append((pcbnew.ToMM(end.x), pcbnew.ToMM(end.y)))
                index = self.preview_list.InsertItem(self.preview_list.GetItemCount(), str(fp.GetReference()))
                values = (str(pad.GetNumber()), str(pad.GetNetname()), str(self.escape_layer.GetValue()), "Track + via" if self.add_vias.GetValue() and pad.GetNetCode() else "Track")
                for column, value in enumerate(values, 1):
                    self.preview_list.SetItem(index, column, value)
            self.geometry_preview.set_geometry(lines, points)
            self.show_button.Enable(bool(self.preview_plan))
            self.commit_button.Enable(False)
            self.status.SetLabel(f"Window preview: {len(self.preview_plan)} fanouts. The PCB has not been changed.")
            self.workflow.set_step(1, "Inspect the canvas and table, then Show on PCB for placement and clearance review.")
            if not self.preview_plan:
                wx.MessageBox("No eligible SMD pads matched. Check the footprint reference and pattern settings.", "No fanout preview", wx.OK | wx.ICON_INFORMATION)
        except Exception as exc:
            self.status.SetLabel(str(exc))
            wx.MessageBox(str(exc), "Fanout preview failed", wx.OK | wx.ICON_ERROR)

    def show_on_pcb(self, _event: Any) -> None:
        if not self.preview_plan:
            wx.MessageBox("Create and inspect the in-window preview first.", "Window preview required", wx.OK | wx.ICON_INFORMATION)
            return
        try:
            self.clear_pcb_preview()
            for _fp, pad, end, width, diameter, drill in self.preview_plan:
                track = pcbnew.PCB_TRACK(self.board)
                track.SetStart(pad.GetPosition())
                track.SetEnd(end)
                track.SetWidth(width)
                track.SetLayer(self._layer(pad))
                track.SetNetCode(pad.GetNetCode())
                self.board.Add(track)
                self.preview_items.append(track)
                if self.add_vias.GetValue() and pad.GetNetCode():
                    via = pcbnew.PCB_VIA(self.board)
                    via.SetPosition(end)
                    via.SetDrill(int(drill))
                    via.SetWidth(int(diameter))
                    via.SetNetCode(pad.GetNetCode())
                    self.board.Add(via)
                    self.preview_items.append(via)
            select_items(self.board, self.preview_items)
            if hasattr(pcbnew, "Refresh"):
                pcbnew.Refresh()
            self.commit_button.Enable(bool(self.preview_items))
            self.status.SetLabel(f"PCB preview: {len(self.preview_items)} temporary items selected. Commit or clear them.")
            self.workflow.set_step(2, "Inspect the temporary PCB geometry and run visual clearance checks, then Commit to PCB.")
        except Exception as exc:
            self.clear_pcb_preview()
            self.status.SetLabel(str(exc))
            wx.MessageBox(str(exc), "PCB preview failed", wx.OK | wx.ICON_ERROR)

    def clear_pcb_preview(self) -> None:
        for item in self.preview_items:
            try:
                self.board.Remove(item)
            except Exception:
                pass
        self.preview_items = []
        self.commit_button.Enable(False)
        if hasattr(pcbnew, "Refresh"):
            pcbnew.Refresh()

    def clear_preview(self, _event: Any) -> None:
        self.clear_pcb_preview()
        self.preview_plan = []
        self.preview_list.DeleteAllItems()
        self.geometry_preview.clear()
        self.show_button.Enable(False)
        self.commit_button.Enable(False)
        if _event is not None:
            self.status.SetLabel("Preview cleared. No board changes were committed.")
            self.workflow.set_step(0, "Adjust the settings, then Preview in Window again.")

    def generate(self, _event: Any) -> None:
        try:
            if not self.preview_items:
                wx.MessageBox("Create and inspect a preview before committing.", "Preview required", wx.OK | wx.ICON_INFORMATION)
                return
            created = list(self.preview_items)
            self.preview_items = []
            self.undo_stack.append(created)
            self.redo_stack.clear()
            self.commit_button.Enable(False)
            self.undo_button.Enable(True)
            self.redo_button.Enable(False)
            select_items(self.board, created)
            self.status.SetLabel(f"Committed {len(created)} board items. Run DRC before saving or fabrication.")
            self.workflow.set_step(3, "Run DRC, finish routing, and save the board. Undo Last Commit removes the whole operation.")
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Fanout Generator", wx.OK | wx.ICON_ERROR)

    def undo(self, _event: Any) -> None:
        if not self.undo_stack:
            self.status.SetLabel("Nothing to undo.")
            return
        items = self.undo_stack.pop()
        for item in items:
            try:
                self.board.Remove(item)
            except Exception:
                pass
        self.redo_stack.append(items)
        self.undo_button.Enable(bool(self.undo_stack))
        self.redo_button.Enable(True)
        if hasattr(pcbnew, "Refresh"):
            pcbnew.Refresh()
        self.status.SetLabel(f"Undid one fanout operation ({len(items)} items).")

    def redo(self, _event: Any) -> None:
        if not self.redo_stack:
            self.status.SetLabel("Nothing to redo.")
            return
        items = self.redo_stack.pop()
        for item in items:
            try:
                self.board.Add(item)
            except Exception:
                pass
        self.undo_stack.append(items)
        self.undo_button.Enable(True)
        self.redo_button.Enable(bool(self.redo_stack))
        select_items(self.board, items)
        if hasattr(pcbnew, "Refresh"):
            pcbnew.Refresh()
        self.status.SetLabel(f"Redid one fanout operation ({len(items)} items).")

    def on_config_changed(self, _event: Any) -> None:
        self.clear_preview(None)
        self.status.SetLabel("Settings changed; create a fresh preview before committing.")
        self.workflow.set_step(0, "Preview the updated settings in this window.")

    def on_close(self, event: Any) -> None:
        self.clear_preview(None)
        event.Skip()
