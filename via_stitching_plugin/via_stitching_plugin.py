"""Net-aware ground/signal via stitching grid generator."""

from __future__ import annotations

import os
from typing import Any, Iterable, List, Set, Tuple

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import select_items
from .guided_ui import add_workflow
from .geometry_preview import GeometryPreview


class ViaStitchingPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Via Stitching"
        self.category = "Routing"
        self.description = "Generate a configurable ground-via stitching grid."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.5.0"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            dialog = ViaFrame(None, board)
            dialog.ShowModal()
            dialog.Destroy()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Via Stitching", wx.OK | wx.ICON_ERROR)


class ViaFrame(wx.Dialog):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Via Stitching", size=(920, 850), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.board = board
        self.preview_plan: List[Any] = []
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
            "Via Stitching",
            "Review accepted via positions in this window first, show them temporarily on the PCB second, then commit.",
            ("Configure", "Window preview", "PCB preview", "Commit"),
        )
        grid = wx.FlexGridSizer(0, 2, 6, 8)
        self.spacing = wx.TextCtrl(panel, value="2.50")
        self.edge = wx.TextCtrl(panel, value="1.00")
        self.drill = wx.TextCtrl(panel, value="0.30")
        self.diameter = wx.TextCtrl(panel, value="0.60")
        self.net_choice = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.advanced = wx.CollapsiblePane(panel, label="Area and exclusion settings")
        advanced_panel = self.advanced.GetPane()
        advanced_root = wx.BoxSizer(wx.VERTICAL)
        self.skip_refs = wx.TextCtrl(advanced_panel, value="")
        self.universal = wx.CheckBox(advanced_panel, label="Use full board bounds")
        self.universal.SetValue(True)
        self.x_min = wx.TextCtrl(advanced_panel, value="0")
        self.y_min = wx.TextCtrl(advanced_panel, value="0")
        self.x_max = wx.TextCtrl(advanced_panel, value="100")
        self.y_max = wx.TextCtrl(advanced_panel, value="100")
        for label, control in (("Net to stitch:", self.net_choice), ("Grid spacing (mm):", self.spacing), ("Edge inset (mm):", self.edge), ("Drill (mm):", self.drill), ("Via diameter (mm):", self.diameter)):
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(control, 1, wx.EXPAND)
        grid.AddGrowableCol(1, 1)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        advanced_root.Add(self.universal, 0, wx.LEFT | wx.RIGHT, 8)
        bounds = wx.BoxSizer(wx.HORIZONTAL)
        for label, control in (("X min mm", self.x_min), ("Y min mm", self.y_min), ("X max mm", self.x_max), ("Y max mm", self.y_max)):
            bounds.Add(wx.StaticText(advanced_panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
            bounds.Add(control, 1, wx.ALL, 3)
        select_bounds = wx.Button(advanced_panel, label="Use PCB Selection Bounds")
        select_bounds.Bind(wx.EVT_BUTTON, self.use_selection_bounds)
        bounds.Add(select_bounds, 0, wx.ALL, 3)
        advanced_root.Add(bounds, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        skip_row = wx.BoxSizer(wx.HORIZONTAL)
        skip_row.Add(wx.StaticText(advanced_panel, label="Skip refs:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        skip_row.Add(self.skip_refs, 1, wx.EXPAND)
        advanced_root.Add(skip_row, 0, wx.EXPAND | wx.ALL, 8)
        self.skip_parts = wx.CheckBox(advanced_panel, label="Footprints")
        self.skip_tracks = wx.CheckBox(advanced_panel, label="Tracks")
        self.skip_zones = wx.CheckBox(advanced_panel, label="Copper zones")
        self.skip_keepouts = wx.CheckBox(advanced_panel, label="Keepouts / drawings")
        exclusion_row = wx.BoxSizer(wx.HORIZONTAL)
        for checkbox in (self.skip_parts, self.skip_tracks, self.skip_zones, self.skip_keepouts):
            checkbox.SetValue(True)
            exclusion_row.Add(checkbox, 0, wx.RIGHT, 10)
        advanced_root.Add(exclusion_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        advanced_panel.SetSizer(advanced_root)
        root.Add(self.advanced, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.geometry_preview = GeometryPreview(panel, "Configure settings, then click Preview in Window.")
        root.Add(self.geometry_preview, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.preview_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("#", 55), ("Net", 220), ("X (mm)", 110), ("Y (mm)", 110), ("Result", 150))):
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
                button.SetToolTip("Temporarily add the reviewed via positions to the PCB and select them.")
            elif text == "Commit to PCB":
                self.commit_button = button
                button.Enable(False)
                button.SetToolTip("Keep the exact temporary PCB preview as one plugin operation.")
            elif text == "Undo Last Commit":
                self.undo_button = button
                button.Enable(False)
                button.SetToolTip("Remove every via from the most recent stitching commit.")
            elif text == "Redo Last Commit":
                self.redo_button = button
                button.Enable(False)
                button.SetToolTip("Restore every via removed by Undo Last Commit.")
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row.Add(help_btn, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        panel.SetSizer(root)
        self._load_nets()
        for control in (self.spacing, self.edge, self.drill, self.diameter, self.skip_refs, self.x_min, self.y_min, self.x_max, self.y_max):
            control.Bind(wx.EVT_TEXT, self.on_config_changed)
        self.net_choice.Bind(wx.EVT_COMBOBOX, self.on_config_changed)
        for control in (self.universal, self.skip_parts, self.skip_tracks, self.skip_zones, self.skip_keepouts):
            control.Bind(wx.EVT_CHECKBOX, self.on_config_changed)
        self.workflow.set_step(0, "Select a net and spacing, then Preview in Window. Advanced area/exclusion settings are optional.")

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
            self.preview_plan = self._plan()
            net_name, _net_code = self._selected_net()
            points = []
            for number, via in enumerate(self.preview_plan, 1):
                position = via.GetPosition()
                points.append((pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)))
                index = self.preview_list.InsertItem(self.preview_list.GetItemCount(), str(number))
                values = (net_name or "<No net>", f"{pcbnew.ToMM(position.x):.3f}", f"{pcbnew.ToMM(position.y):.3f}", "Accepted")
                for column, value in enumerate(values, 1):
                    self.preview_list.SetItem(index, column, value)
            self.geometry_preview.set_geometry(points=points)
            self.show_button.Enable(bool(self.preview_plan))
            self.commit_button.Enable(False)
            self.status.SetLabel(f"Window preview: {len(self.preview_plan)} accepted vias. The PCB has not been changed.")
            self.workflow.set_step(1, "Inspect the canvas and table, then Show on PCB for clearance review.")
            if not self.preview_plan:
                wx.MessageBox("No via candidates survived the selected bounds and exclusions.", "No stitching preview", wx.OK | wx.ICON_INFORMATION)
        except Exception as exc:
            self.status.SetLabel(str(exc))
            wx.MessageBox(str(exc), "Via preview failed", wx.OK | wx.ICON_ERROR)

    def show_on_pcb(self, _event: Any) -> None:
        if not self.preview_plan:
            wx.MessageBox("Create and inspect the in-window preview first.", "Window preview required", wx.OK | wx.ICON_INFORMATION)
            return
        try:
            self.clear_pcb_preview()
            for via in self.preview_plan:
                self.board.Add(via)
                self.preview_items.append(via)
            select_items(self.board, self.preview_items)
            if hasattr(pcbnew, "Refresh"):
                pcbnew.Refresh()
            self.commit_button.Enable(bool(self.preview_items))
            self.status.SetLabel(f"PCB preview: {len(self.preview_items)} temporary vias selected. Commit or clear them.")
            self.workflow.set_step(2, "Inspect temporary PCB clearances, then Commit to PCB.")
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
            self.workflow.set_step(0, "Adjust settings, then Preview in Window again.")

    def generate(self, _event: Any) -> None:
        try:
            if not self.preview_items:
                wx.MessageBox("Create and inspect a preview before committing.", "Preview required", wx.OK | wx.ICON_INFORMATION)
                return
            committed = list(self.preview_items)
            self.preview_items = []
            self.undo_stack.append(committed)
            self.redo_stack.clear()
            self.commit_button.Enable(False)
            self.undo_button.Enable(True)
            self.redo_button.Enable(False)
            select_items(self.board, committed)
            self.status.SetLabel(f"Committed {len(committed)} vias. Run DRC before saving or fabrication.")
            self.workflow.set_step(3, "Run DRC, inspect clearances, and save the board. Undo Last Commit removes the whole operation.")
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Via Stitching", wx.OK | wx.ICON_ERROR)

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
        self.status.SetLabel(f"Undid one stitching operation ({len(items)} vias).")

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
        self.status.SetLabel(f"Redid one stitching operation ({len(items)} vias).")

    def on_config_changed(self, _event: Any) -> None:
        self.clear_preview(None)
        self.status.SetLabel("Settings changed; create a fresh preview before committing.")
        self.workflow.set_step(0, "Preview the updated settings in this window.")

    def on_close(self, event: Any) -> None:
        self.clear_preview(None)
        event.Skip()
