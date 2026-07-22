"""Conservative radial fanout generator for selected/all SMD pads."""

from __future__ import annotations

import math
import os
import fnmatch
from dataclasses import dataclass
from typing import Any, List, Tuple

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import select_items
from .guided_ui import add_workflow
from .geometry_preview import GeometryPreview


def _coord(value: Any) -> float:
    return float(value) / 1_000_000.0 if hasattr(value, "__float__") else float(value)


@dataclass
class FanoutPlan:
    footprint: Any
    pad: Any
    end: Any
    width: int
    via_diameter: int
    via_drill: int
    add_track: bool = True
    add_via: bool = False
    pattern: str = "Radial outward"


class FanoutGeneratorPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Fanout Generator"
        self.category = "Routing"
        self.description = "Generate conservative radial fanout tracks from SMD pads."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.7.0"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            existing = getattr(self, "_frame", None)
            if existing is not None and existing:
                existing.Show()
                existing.Raise()
                return
            self._frame = FanoutFrame(None, board)
            self._frame.Show()
            self._frame.Raise()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Fanout Generator", wx.OK | wx.ICON_ERROR)


class FanoutFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Fanout Generator", size=(860, 820), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.board = board
        self.preview_plan: List[FanoutPlan] = []
        self.preview_items: List[Any] = []
        self.undo_stack: List[Any] = []
        self.redo_stack: List[Tuple[str, List[Any]]] = []
        self.last_selection_signature: Tuple[Any, ...] = ()
        self.selection_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_selection_timer, self.selection_timer)
        self._build_ui()
        self.undo_stack = self._persistent_groups()
        self.undo_button.Enable(bool(self.undo_stack))
        self._sync_selection(force=True)
        self.selection_timer.Start(500)
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
        self.scope = wx.ComboBox(panel, choices=["Selected pads", "Selected footprints", "Reference wildcard", "All SMD pads"], style=wx.CB_READONLY)
        self.scope.SetSelection(1)
        self.width = wx.TextCtrl(panel, value="0.20")
        self.length = wx.TextCtrl(panel, value="1.50")
        self.pattern = wx.ComboBox(panel, choices=[
            "Dogbone outward", "Dogbone inward", "BGA/LGA grid outward",
            "Quadrant outward", "Quadrant inward", "Four-corner outward",
            "Four-corner inward", "Perimeter outward", "Radial outward", "Via-in-pad",
        ], style=wx.CB_READONLY)
        self.pattern.SetSelection(0)
        self.escape_layer = wx.ComboBox(panel, choices=["Pad layer", "F.Cu", "B.Cu"], style=wx.CB_READONLY)
        self.escape_layer.SetSelection(0)
        self.add_vias = wx.CheckBox(panel, label="Add escape vias")
        self.via_diameter = wx.TextCtrl(panel, value="0.60")
        self.via_drill = wx.TextCtrl(panel, value="0.30")
        for label, control in (("Pad scope:", self.scope), ("Reference wildcard:", self.ref), ("Pattern:", self.pattern), ("Track width (mm):", self.width), ("Fanout length (mm):", self.length), ("Escape layer:", self.escape_layer), ("Via diameter (mm):", self.via_diameter), ("Via drill (mm):", self.via_drill)):
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(control, 1, wx.EXPAND)
        grid.AddGrowableCol(1, 1)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        options = wx.BoxSizer(wx.HORIZONTAL)
        options.Add(self.add_vias, 0, wx.RIGHT, 16)
        self.auto_refresh = wx.CheckBox(panel, label="Auto-refresh from PCB selection")
        self.auto_refresh.SetValue(True)
        options.Add(self.auto_refresh, 0, wx.RIGHT, 16)
        self.selection_status = wx.StaticText(panel, label="PCB selection: none")
        options.Add(self.selection_status, 1, wx.ALIGN_CENTER_VERTICAL)
        root.Add(options, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.geometry_preview = GeometryPreview(panel, "Configure settings, then click Preview in Window.")
        root.Add(self.geometry_preview, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.preview_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("Footprint", 110), ("Pad", 80), ("Net", 220), ("Layer", 100), ("Result", 140))):
            self.preview_list.InsertColumn(index, label, width=width)
        self.preview_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_preview_row_activated)
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
        for control in (self.pattern, self.escape_layer, self.scope):
            control.Bind(wx.EVT_COMBOBOX, self.on_config_changed)
        self.add_vias.Bind(wx.EVT_CHECKBOX, self.on_config_changed)
        self.workflow.set_step(0, "Choose a footprint and geometry, then Preview in Window.")

    def _layer(self, pad: Any) -> int:
        choice = self.escape_layer.GetValue()
        if choice == "F.Cu": return pcbnew.F_Cu
        if choice == "B.Cu": return pcbnew.B_Cu
        return pad.GetLayer()

    def _selected_pad_keys(self) -> set[Tuple[str, str]]:
        return {
            (str(fp.GetReference()), str(pad.GetNumber()))
            for fp in self.board.GetFootprints()
            for pad in fp.Pads()
            if bool(getattr(pad, "IsSelected", lambda: False)())
        }

    def _selected_footprint_refs(self) -> set[str]:
        refs = {
            str(fp.GetReference()) for fp in self.board.GetFootprints()
            if bool(getattr(fp, "IsSelected", lambda: False)())
        }
        refs.update(ref for ref, _pin in self._selected_pad_keys())
        return refs

    def _eligible_pads(self) -> List[Tuple[Any, Any]]:
        scope = self.scope.GetValue()
        selected_pads = self._selected_pad_keys()
        selected_refs = self._selected_footprint_refs()
        patterns = [item.strip().upper() for item in self.ref.GetValue().split(",") if item.strip()]
        result = []
        for fp in self.board.GetFootprints():
            ref = str(fp.GetReference())
            if scope == "Selected footprints" and ref not in selected_refs:
                continue
            if scope == "Reference wildcard" and not any(fnmatch.fnmatchcase(ref.upper(), pattern) for pattern in patterns):
                continue
            for pad in fp.Pads():
                if pad.GetAttribute() not in (getattr(pcbnew, "PAD_ATTRIB_SMD", 0), 0):
                    continue
                if scope == "Selected pads" and (ref, str(pad.GetNumber())) not in selected_pads:
                    continue
                result.append((fp, pad))
        return result

    def _escape_angle(self, pattern: str, fp: Any, pad: Any) -> float:
        pos = pad.GetPosition()
        center = fp.GetPosition()
        dx = _coord(pos.x) - _coord(center.x)
        dy = _coord(pos.y) - _coord(center.y)
        radial = math.atan2(dy, dx) if dx or dy else 0.0
        inward = "inward" in pattern.lower()
        if pattern.startswith("Quadrant"):
            angle = math.atan2(1.0 if dy >= 0 else -1.0, 1.0 if dx >= 0 else -1.0)
        elif pattern.startswith("Four-corner"):
            box = fp.GetBoundingBox()
            corner_x = box.GetRight() if dx >= 0 else box.GetLeft()
            corner_y = box.GetBottom() if dy >= 0 else box.GetTop()
            angle = math.atan2(_coord(corner_y) - _coord(pos.y), _coord(corner_x) - _coord(pos.x))
        elif pattern.startswith("BGA/LGA") or pattern.startswith("Perimeter"):
            if abs(dx) >= abs(dy):
                angle = 0.0 if dx >= 0 else math.pi
            else:
                angle = math.pi / 2 if dy >= 0 else -math.pi / 2
        else:
            angle = radial
        return angle + (math.pi if inward else 0.0)

    def _plan(self) -> List[FanoutPlan]:
        try:
            width = pcbnew.FromMM(float(self.width.GetValue()))
            length = pcbnew.FromMM(float(self.length.GetValue()))
            via_diameter = pcbnew.FromMM(float(self.via_diameter.GetValue()))
            via_drill = pcbnew.FromMM(float(self.via_drill.GetValue()))
        except (TypeError, ValueError):
            raise ValueError("Width and length must be numeric millimetre values.")
        result: List[FanoutPlan] = []
        pattern = self.pattern.GetValue()
        for fp, pad in self._eligible_pads():
            pos = pad.GetPosition()
            via_in_pad = pattern == "Via-in-pad"
            angle = self._escape_angle(pattern, fp, pad)
            end = pcbnew.VECTOR2I(pos.x, pos.y) if via_in_pad else pcbnew.VECTOR2I(
                pos.x + int(math.cos(angle) * length),
                pos.y + int(math.sin(angle) * length),
            )
            forced_via = via_in_pad or pattern.startswith("Dogbone")
            result.append(FanoutPlan(
                fp, pad, end, width, via_diameter, via_drill,
                add_track=not via_in_pad,
                add_via=bool(pad.GetNetCode()) and (forced_via or self.add_vias.GetValue()),
                pattern=pattern,
            ))
        return result

    def preview(self, _event: Any, silent: bool = False) -> None:
        try:
            self.clear_preview(None)
            self.preview_plan = self._plan()
            lines = []
            points = []
            pads = []
            for plan in self.preview_plan:
                fp, pad, end = plan.footprint, plan.pad, plan.end
                start = pad.GetPosition()
                pads.append((pcbnew.ToMM(start.x), pcbnew.ToMM(start.y)))
                if plan.add_track:
                    lines.append((pcbnew.ToMM(start.x), pcbnew.ToMM(start.y), pcbnew.ToMM(end.x), pcbnew.ToMM(end.y)))
                if plan.add_via:
                    points.append((pcbnew.ToMM(end.x), pcbnew.ToMM(end.y)))
                index = self.preview_list.InsertItem(self.preview_list.GetItemCount(), str(fp.GetReference()))
                result_kind = "Via in pad" if not plan.add_track else ("Track + via" if plan.add_via else "Track")
                values = (str(pad.GetNumber()), str(pad.GetNetname()), str(self.escape_layer.GetValue()), f"{result_kind} | {plan.pattern}")
                for column, value in enumerate(values, 1):
                    self.preview_list.SetItem(index, column, value)
            self.geometry_preview.set_geometry(lines, points, pads=pads)
            self.show_button.Enable(bool(self.preview_plan))
            self.commit_button.Enable(False)
            self.status.SetLabel(f"Window preview: {len(self.preview_plan)} fanouts. The PCB has not been changed.")
            self.workflow.set_step(1, "Inspect the canvas and table, then Show on PCB for placement and clearance review.")
            if not self.preview_plan and not silent:
                wx.MessageBox("No eligible SMD pads matched. Check the footprint reference and pattern settings.", "No fanout preview", wx.OK | wx.ICON_INFORMATION)
        except Exception as exc:
            self.status.SetLabel(str(exc))
            if not silent:
                wx.MessageBox(str(exc), "Fanout preview failed", wx.OK | wx.ICON_ERROR)

    def show_on_pcb(self, _event: Any) -> None:
        if not self.preview_plan:
            wx.MessageBox("Create and inspect the in-window preview first.", "Window preview required", wx.OK | wx.ICON_INFORMATION)
            return
        try:
            self.clear_pcb_preview()
            for plan in self.preview_plan:
                pad, end = plan.pad, plan.end
                if plan.add_track:
                    track = pcbnew.PCB_TRACK(self.board)
                    track.SetStart(pad.GetPosition())
                    track.SetEnd(end)
                    track.SetWidth(plan.width)
                    track.SetLayer(self._layer(pad))
                    track.SetNetCode(pad.GetNetCode())
                    self.board.Add(track)
                    self.preview_items.append(track)
                if plan.add_via:
                    via = pcbnew.PCB_VIA(self.board)
                    via.SetPosition(end)
                    via.SetDrill(int(plan.via_drill))
                    via.SetWidth(int(plan.via_diameter))
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

    def _persistent_groups(self) -> List[Any]:
        groups = []
        for group in getattr(self.board, "Groups", lambda: [])():
            try:
                if str(group.GetName()).startswith("KiWay Fanout Commit"):
                    groups.append(group)
            except Exception:
                continue
        return groups

    @staticmethod
    def _group_items(group: Any) -> List[Any]:
        for getter_name in ("GetItems", "GetBoardItems"):
            getter = getattr(group, getter_name, None)
            if callable(getter):
                try:
                    return list(getter())
                except Exception:
                    continue
        return []

    def _new_commit_group(self, items: List[Any], name: str = "") -> Any:
        if not hasattr(pcbnew, "PCB_GROUP"):
            return list(items)
        group = pcbnew.PCB_GROUP(self.board)
        group.SetName(name or f"KiWay Fanout Commit {len(self._persistent_groups()) + 1:03d}")
        self.board.Add(group)
        for item in items:
            group.AddItem(item)
        return group

    def generate(self, _event: Any) -> None:
        try:
            if not self.preview_items:
                wx.MessageBox("Create and inspect a preview before committing.", "Preview required", wx.OK | wx.ICON_INFORMATION)
                return
            created = list(self.preview_items)
            self.preview_items = []
            group = self._new_commit_group(created)
            self.undo_stack.append(group)
            self.redo_stack.clear()
            self.commit_button.Enable(False)
            self.undo_button.Enable(True)
            self.redo_button.Enable(False)
            select_items(self.board, created)
            self.status.SetLabel(f"Committed {len(created)} board items in a persistent KiWay group. Run DRC before saving.")
            self.workflow.set_step(3, "Run DRC and save the board. Reopen this plugin later to undo the latest named KiWay group.")
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Fanout Generator", wx.OK | wx.ICON_ERROR)

    def undo(self, _event: Any) -> None:
        if not self.undo_stack:
            self.status.SetLabel("Nothing to undo.")
            return
        entry = self.undo_stack.pop()
        if isinstance(entry, list):
            name, items = "KiWay Fanout Commit", entry
        else:
            name, items = str(entry.GetName()), self._group_items(entry)
            for item in items:
                try:
                    entry.RemoveItem(item)
                except Exception:
                    pass
            try:
                self.board.Remove(entry)
            except Exception:
                pass
        for item in items:
            try:
                self.board.Remove(item)
            except Exception:
                pass
        self.redo_stack.append((name, items))
        self.undo_button.Enable(bool(self.undo_stack))
        self.redo_button.Enable(True)
        if hasattr(pcbnew, "Refresh"):
            pcbnew.Refresh()
        self.status.SetLabel(f"Undid one fanout operation ({len(items)} items).")

    def redo(self, _event: Any) -> None:
        if not self.redo_stack:
            self.status.SetLabel("Nothing to redo.")
            return
        name, items = self.redo_stack.pop()
        for item in items:
            try:
                self.board.Add(item)
            except Exception:
                pass
        group = self._new_commit_group(items, name)
        self.undo_stack.append(group)
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

    def _selection_signature(self) -> Tuple[Any, ...]:
        return tuple(sorted(self._selected_footprint_refs())), tuple(sorted(self._selected_pad_keys()))

    def _sync_selection(self, force: bool = False) -> None:
        signature = self._selection_signature()
        if not force and signature == self.last_selection_signature:
            return
        self.last_selection_signature = signature
        refs, pads = signature
        self.selection_status.SetLabel(f"PCB selection: {len(refs)} footprints, {len(pads)} pads")
        if len(refs) == 1 and self.scope.GetValue() in ("Selected pads", "Selected footprints"):
            self.ref.ChangeValue(str(refs[0]))
        if self.auto_refresh.GetValue() and not self.preview_items:
            self.preview(None, silent=True)

    def on_selection_timer(self, _event: Any) -> None:
        try:
            self._sync_selection()
        except Exception:
            pass

    def on_preview_row_activated(self, event: Any) -> None:
        index = event.GetIndex()
        if 0 <= index < len(self.preview_plan):
            select_items(self.board, [self.preview_plan[index].pad])
            self.status.SetLabel(
                f"Selected {self.preview_plan[index].footprint.GetReference()}.{self.preview_plan[index].pad.GetNumber()} on PCB."
            )

    def on_close(self, event: Any) -> None:
        self.selection_timer.Stop()
        self.clear_preview(None)
        event.Skip()
