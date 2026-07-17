"""Net-aware ground/signal via stitching grid generator."""

from __future__ import annotations

import os
from typing import Any, Iterable, List, Set, Tuple

import pcbnew
import wx


class ViaStitchingPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Via Stitching"
        self.category = "Routing"
        self.description = "Generate a configurable ground-via stitching grid."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.2.0"

    def Run(self) -> None:
        ViaFrame(None, pcbnew.GetBoard()).Show()


class ViaFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Via Stitching", size=(720, 560))
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
        self.spacing = wx.TextCtrl(panel, value="2.50")
        self.edge = wx.TextCtrl(panel, value="1.00")
        self.drill = wx.TextCtrl(panel, value="0.30")
        self.diameter = wx.TextCtrl(panel, value="0.60")
        self.net_choice = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.skip_refs = wx.TextCtrl(panel, value="")
        self.universal = wx.CheckBox(panel, label="Universal board bounds")
        self.universal.SetValue(True)
        self.x_min = wx.TextCtrl(panel, value="0")
        self.y_min = wx.TextCtrl(panel, value="0")
        self.x_max = wx.TextCtrl(panel, value="100")
        self.y_max = wx.TextCtrl(panel, value="100")
        for label, control in (("Grid spacing (mm):", self.spacing), ("Edge inset (mm):", self.edge), ("Drill (mm):", self.drill), ("Via diameter (mm):", self.diameter), ("Net to stitch:", self.net_choice), ("Skip footprint refs (comma separated):", self.skip_refs)):
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(control, 1, wx.EXPAND)
        grid.AddGrowableCol(1, 1)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        root.Add(self.universal, 0, wx.LEFT | wx.RIGHT, 10)
        bounds = wx.BoxSizer(wx.HORIZONTAL)
        for label, control in (("X min mm", self.x_min), ("Y min mm", self.y_min), ("X max mm", self.x_max), ("Y max mm", self.y_max)):
            bounds.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
            bounds.Add(control, 1, wx.ALL, 3)
        select_bounds = wx.Button(panel, label="Use Selected Items Bounds")
        select_bounds.Bind(wx.EVT_BUTTON, self.use_selection_bounds)
        bounds.Add(select_bounds, 0, wx.ALL, 3)
        root.Add(bounds, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self.skip_parts = wx.CheckBox(panel, label="Skip footprint bodies / parts")
        self.skip_tracks = wx.CheckBox(panel, label="Skip locations occupied by tracks")
        self.skip_zones = wx.CheckBox(panel, label="Skip locations inside copper zones")
        self.skip_keepouts = wx.CheckBox(panel, label="Skip locations inside keepouts / board drawings")
        for checkbox in (self.skip_parts, self.skip_tracks, self.skip_zones, self.skip_keepouts):
            checkbox.SetValue(True)
            root.Add(checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.status = wx.StaticText(panel, label="Select a net. Candidates overlapping enabled exclusions are skipped.")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for text, handler in (("Preview", self.preview), ("Clear Preview", self.clear_preview), ("Generate", self.generate), ("Undo", self.undo), ("Redo", self.redo)):
            button = wx.Button(panel, label=text)
            button.Bind(wx.EVT_BUTTON, handler)
            row.Add(button, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        panel.SetSizer(root)
        self._load_nets()

    def _load_nets(self) -> None:
        names: Set[str] = set()
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                name = pad.GetNetname() if hasattr(pad, "GetNetname") else ""
                if name:
                    names.add(name)
        self.net_choice.Append("<No net>")
        for name in sorted(names):
            self.net_choice.Append(name)
        self.net_choice.SetSelection(0)

    def _selected_net(self) -> tuple[str, int]:
        name = self.net_choice.GetValue()
        if not name or name == "<No net>":
            return "", 0
        find_net = getattr(self.board, "FindNet", None)
        if callable(find_net):
            net = find_net(name)
            if net is not None:
                return name, int(net.GetNetCode())
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() == name:
                    return name, int(pad.GetNetCode())
        return name, 0

    def _excluded_refs(self) -> Set[str]:
        return {item.strip().upper() for item in self.skip_refs.GetValue().split(",") if item.strip()}

    def _contains(self, item: Any, position: Any) -> bool:
        getter = getattr(item, "GetBoundingBox", None)
        if not callable(getter):
            return False
        try:
            return bool(getter().Contains(position))
        except Exception:
            return False

    def _blocked(self, position: Any) -> bool:
        if self.skip_parts.GetValue():
            excluded = self._excluded_refs()
            for fp in self.board.GetFootprints():
                if fp.GetReference().upper() in excluded or self._contains(fp, position):
                    return True
        if self.skip_tracks.GetValue():
            tracks = getattr(self.board, "GetTracks", lambda: [])()
            if any(self._contains(track, position) for track in tracks):
                return True
        if self.skip_zones.GetValue():
            zones = getattr(self.board, "Zones", lambda: [])()
            if any(self._contains(zone, position) for zone in zones):
                return True
        if self.skip_keepouts.GetValue():
            drawings = getattr(self.board, "GetDrawings", lambda: [])()
            if any(self._contains(drawing, position) for drawing in drawings):
                return True
        return False

    def use_selection_bounds(self, _event: Any) -> None:
        """Use the bounding rectangle of selected footprints/graphics as the stitch area."""
        try:
            selection = list(self.board.GetSelection()) if hasattr(self.board, "GetSelection") else []
            boxes = [item.GetBoundingBox() for item in selection if hasattr(item, "GetBoundingBox")]
            if not boxes:
                raise ValueError("Select at least one footprint or graphic in PCB Editor first.")
            left = min(box.GetLeft() for box in boxes)
            top = min(box.GetTop() for box in boxes)
            right = max(box.GetRight() for box in boxes)
            bottom = max(box.GetBottom() for box in boxes)
            self.x_min.SetValue(f"{left / 1000000.0:.3f}")
            self.y_min.SetValue(f"{top / 1000000.0:.3f}")
            self.x_max.SetValue(f"{right / 1000000.0:.3f}")
            self.y_max.SetValue(f"{bottom / 1000000.0:.3f}")
            self.universal.SetValue(False)
            self.status.SetLabel("Selection bounds loaded. Preview to inspect the stitching area.")
        except Exception as exc:
            wx.MessageBox(str(exc), "Bounds selection", wx.OK | wx.ICON_ERROR)

    def _bounds(self) -> Tuple[int, int, int, int]:
        if self.universal.GetValue():
            box = self.board.GetBoardEdgesBoundingBox()
            return box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom()
        return tuple(int(pcbnew.FromMM(float(value.GetValue()))) for value in (self.x_min, self.y_min, self.x_max, self.y_max))

    def _plan(self) -> List[Any]:
        spacing = pcbnew.FromMM(float(self.spacing.GetValue()))
        inset = pcbnew.FromMM(float(self.edge.GetValue()))
        drill = pcbnew.FromMM(float(self.drill.GetValue()))
        diameter = pcbnew.FromMM(float(self.diameter.GetValue()))
        _net_name, net_code = self._selected_net()
        left, top, right, bottom = self._bounds()
        result = []
        x = left + inset
        while x <= right - inset:
            y = top + inset
            while y <= bottom - inset:
                position = pcbnew.VECTOR2I(int(x), int(y))
                if self._blocked(position):
                    y += spacing
                    continue
                via = pcbnew.PCB_VIA(self.board)
                via.SetPosition(position)
                via.SetDrill(int(drill))
                via.SetWidth(int(diameter))
                via.SetNetCode(net_code)
                result.append(via)
                y += spacing
            x += spacing
        return result

    def preview(self, _event: Any) -> None:
        try:
            self.clear_preview(None)
            plan = self._plan()
            for via in plan:
                self.board.Add(via); self.preview_items.append(via)
            if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
            self.status.SetLabel(f"Previewing {len(plan)} vias. Clear or Generate to continue.")
        except Exception as exc: self.status.SetLabel(str(exc))

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
            for via in plan: self.board.Add(via)
            self.undo_stack.append(plan); self.redo_stack.clear()
            if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
            self.status.SetLabel(f"Created {len(plan)} vias. Run DRC and review board-edge/keepout clearances.")
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Via Stitching", wx.OK | wx.ICON_ERROR)

    def undo(self, _event: Any) -> None:
        if not self.undo_stack: return
        items = self.undo_stack.pop()
        for item in items:
            try: self.board.Remove(item)
            except Exception: pass
        self.redo_stack.append(items)
        if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
        self.status.SetLabel("Last stitching operation undone.")

    def redo(self, _event: Any) -> None:
        if not self.redo_stack: return
        items = self.redo_stack.pop()
        for item in items:
            try: self.board.Add(item)
            except Exception: pass
        self.undo_stack.append(items)
        if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
        self.status.SetLabel("Last stitching operation redone.")
