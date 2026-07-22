"""Net-aware ground/signal via stitching grid generator."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Set, Tuple

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
            self._frame = ViaFrame(None, board)
            self._frame.Show()
            self._frame.Raise()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Via Stitching", wx.OK | wx.ICON_ERROR)


class ViaFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Via Stitching", size=(920, 850), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.board = board
        self.preview_plan: List[Any] = []
        self.preview_items: List[Any] = []
        self.undo_stack: List[Any] = []
        self.redo_stack: List[Tuple[str, List[Any]]] = []
        self.last_selection_signature: Tuple[Any, ...] = ()
        self.plan_rejections: Dict[str, int] = {}
        self.selection_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_selection_timer, self.selection_timer)
        self._build_ui()
        self.undo_stack = self._persistent_groups()
        self.undo_button.Enable(bool(self.undo_stack))
        self.selection_timer.Start(500)
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
        self.require_target_zone = wx.CheckBox(advanced_panel, label="Only inside target-net copper zone")
        self.require_target_zone.SetValue(True)
        self.auto_refresh = wx.CheckBox(advanced_panel, label="Auto-refresh from PCB selection")
        self.auto_refresh.SetValue(True)
        exclusion_row = wx.BoxSizer(wx.HORIZONTAL)
        for checkbox in (self.skip_parts, self.skip_tracks, self.skip_zones, self.skip_keepouts):
            checkbox.SetValue(True)
            exclusion_row.Add(checkbox, 0, wx.RIGHT, 10)
        advanced_root.Add(exclusion_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        behavior_row = wx.BoxSizer(wx.HORIZONTAL)
        behavior_row.Add(self.require_target_zone, 0, wx.RIGHT, 18)
        behavior_row.Add(self.auto_refresh, 0)
        advanced_root.Add(behavior_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        advanced_panel.SetSizer(advanced_root)
        root.Add(self.advanced, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.geometry_preview = GeometryPreview(panel, "Configure settings, then click Preview in Window.")
        root.Add(self.geometry_preview, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.preview_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("#", 55), ("Net", 220), ("X (mm)", 110), ("Y (mm)", 110), ("Result", 150))):
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
        for control in (self.universal, self.skip_parts, self.skip_tracks, self.skip_zones, self.skip_keepouts, self.require_target_zone):
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
        hit_test = getattr(item, "HitTest", None)
        if callable(hit_test):
            try:
                return bool(hit_test(position))
            except Exception:
                pass
        getter = getattr(item, "GetBoundingBox", None)
        if not callable(getter):
            return False
        try:
            return bool(getter().Contains(position))
        except Exception:
            return False

    @staticmethod
    def _net_code(item: Any) -> int:
        try:
            return int(item.GetNetCode())
        except Exception:
            return 0

    def _target_zones(self, net_code: int) -> List[Any]:
        return [zone for zone in getattr(self.board, "Zones", lambda: [])() if self._net_code(zone) == net_code]

    def _inside_zone(self, zone: Any, position: Any) -> bool:
        hit_filled = getattr(zone, "HitTestFilledArea", None)
        if callable(hit_filled):
            try:
                return bool(hit_filled(zone.GetLayer(), position))
            except Exception:
                pass
        return self._contains(zone, position)

    def _blocked_reason(self, position: Any, net_code: int) -> str:
        if self.skip_parts.GetValue():
            excluded = self._excluded_refs()
            for fp in self.board.GetFootprints():
                if fp.GetReference().upper() in excluded or self._contains(fp, position):
                    return "footprint"
        if self.skip_tracks.GetValue():
            tracks = getattr(self.board, "GetTracks", lambda: [])()
            if any(self._net_code(track) != net_code and self._contains(track, position) for track in tracks):
                return "other-net track/via"
        if self.skip_zones.GetValue():
            zones = getattr(self.board, "Zones", lambda: [])()
            if any(self._net_code(zone) != net_code and self._inside_zone(zone, position) for zone in zones):
                return "other-net zone"
        if self.skip_keepouts.GetValue():
            drawings = getattr(self.board, "GetDrawings", lambda: [])()
            if any(self._contains(drawing, position) for drawing in drawings):
                return "keepout/drawing"
        return ""

    def use_selection_bounds(self, _event: Any, silent: bool = False) -> None:
        """Use the bounding rectangle of selected footprints/graphics as the stitch area."""
        try:
            selection = []
            for fp in self.board.GetFootprints():
                if bool(getattr(fp, "IsSelected", lambda: False)()):
                    selection.append(fp)
                selection.extend(pad for pad in fp.Pads() if bool(getattr(pad, "IsSelected", lambda: False)()))
            for collection_name in ("GetTracks", "GetDrawings", "Zones"):
                selection.extend(
                    item for item in getattr(self.board, collection_name, lambda: [])()
                    if bool(getattr(item, "IsSelected", lambda: False)())
                )
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
            if not silent:
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
        if spacing <= 0:
            raise ValueError("Grid spacing must be greater than zero.")
        _net_name, net_code = self._selected_net()
        if not net_code:
            raise ValueError("Choose a real PCB net before previewing stitching vias.")
        left, top, right, bottom = self._bounds()
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        if right - left <= 2 * inset or bottom - top <= 2 * inset:
            raise ValueError("The selected bounds are smaller than twice the edge inset.")
        target_zones = self._target_zones(net_code)
        require_zone = self.require_target_zone.GetValue() and bool(target_zones)
        rejected: Dict[str, int] = {}
        result = []
        x = left + inset
        while x <= right - inset:
            y = top + inset
            while y <= bottom - inset:
                position = pcbnew.VECTOR2I(int(x), int(y))
                if require_zone and not any(self._inside_zone(zone, position) for zone in target_zones):
                    rejected["outside target copper"] = rejected.get("outside target copper", 0) + 1
                    y += spacing
                    continue
                reason = self._blocked_reason(position, net_code)
                if reason:
                    rejected[reason] = rejected.get(reason, 0) + 1
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
        self.plan_rejections = rejected
        return result

    def preview(self, _event: Any, silent: bool = False) -> None:
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
            if self.plan_rejections:
                detail = ", ".join(f"{count} {reason}" for reason, count in sorted(self.plan_rejections.items()))
                self.status.SetLabel(f"Window preview: {len(self.preview_plan)} accepted; rejected {detail}.")
            self.workflow.set_step(1, "Inspect the canvas and table, then Show on PCB for clearance review.")
            if not self.preview_plan and not silent:
                wx.MessageBox("No via candidates survived the selected bounds and exclusions.", "No stitching preview", wx.OK | wx.ICON_INFORMATION)
        except Exception as exc:
            self.status.SetLabel(str(exc))
            if not silent:
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

    def _persistent_groups(self) -> List[Any]:
        groups = []
        for group in getattr(self.board, "Groups", lambda: [])():
            try:
                if str(group.GetName()).startswith("KiWay Via Stitch Commit"):
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
        group.SetName(name or f"KiWay Via Stitch Commit {len(self._persistent_groups()) + 1:03d}")
        self.board.Add(group)
        for item in items:
            group.AddItem(item)
        return group

    def generate(self, _event: Any) -> None:
        try:
            if not self.preview_items:
                wx.MessageBox("Create and inspect a preview before committing.", "Preview required", wx.OK | wx.ICON_INFORMATION)
                return
            committed = list(self.preview_items)
            self.preview_items = []
            group = self._new_commit_group(committed)
            self.undo_stack.append(group)
            self.redo_stack.clear()
            self.commit_button.Enable(False)
            self.undo_button.Enable(True)
            self.redo_button.Enable(False)
            select_items(self.board, committed)
            self.status.SetLabel(f"Committed {len(committed)} vias in a persistent KiWay group. Run DRC before saving.")
            self.workflow.set_step(3, "Run DRC and save. Reopen this plugin later to undo the latest named KiWay group.")
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Via Stitching", wx.OK | wx.ICON_ERROR)

    def undo(self, _event: Any) -> None:
        if not self.undo_stack:
            self.status.SetLabel("Nothing to undo.")
            return
        entry = self.undo_stack.pop()
        if isinstance(entry, list):
            name, items = "KiWay Via Stitch Commit", entry
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
        self.status.SetLabel(f"Undid one stitching operation ({len(items)} vias).")

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
        self.status.SetLabel(f"Redid one stitching operation ({len(items)} vias).")

    def on_config_changed(self, _event: Any) -> None:
        self.clear_preview(None)
        self.status.SetLabel("Settings changed; create a fresh preview before committing.")
        self.workflow.set_step(0, "Preview the updated settings in this window.")

    def _selected_items(self) -> List[Any]:
        result = []
        for fp in self.board.GetFootprints():
            if bool(getattr(fp, "IsSelected", lambda: False)()):
                result.append(fp)
            result.extend(pad for pad in fp.Pads() if bool(getattr(pad, "IsSelected", lambda: False)()))
        for collection_name in ("GetTracks", "GetDrawings", "Zones"):
            result.extend(
                item for item in getattr(self.board, collection_name, lambda: [])()
                if bool(getattr(item, "IsSelected", lambda: False)())
            )
        return result

    def _selection_signature(self) -> Tuple[Any, ...]:
        signature = []
        for item in self._selected_items():
            net_name = str(getattr(item, "GetNetname", lambda: "")())
            box = getattr(item, "GetBoundingBox", lambda: None)()
            signature.append((id(item), net_name, box.GetLeft() if box else 0, box.GetTop() if box else 0))
        return tuple(sorted(signature))

    def on_selection_timer(self, _event: Any) -> None:
        try:
            signature = self._selection_signature()
            if signature == self.last_selection_signature:
                return
            self.last_selection_signature = signature
            selected = self._selected_items()
            selected_net = next((str(getattr(item, "GetNetname", lambda: "")()) for item in selected if str(getattr(item, "GetNetname", lambda: "")())), "")
            if selected_net and self.net_choice.FindString(selected_net) != wx.NOT_FOUND:
                self.net_choice.SetValue(selected_net)
            if selected and not self.universal.GetValue():
                self.use_selection_bounds(None, silent=True)
            if self.auto_refresh.GetValue() and not self.preview_items:
                self.preview(None, silent=True)
        except Exception:
            pass

    def on_preview_row_activated(self, event: Any) -> None:
        index = event.GetIndex()
        if 0 <= index < len(self.preview_items):
            select_items(self.board, [self.preview_items[index]])
        elif 0 <= index < len(self.preview_plan):
            position = self.preview_plan[index].GetPosition()
            self.status.SetLabel(f"Candidate {index + 1}: {pcbnew.ToMM(position.x):.3f}, {pcbnew.ToMM(position.y):.3f} mm. Show on PCB to cross-select it.")

    def on_close(self, event: Any) -> None:
        self.selection_timer.Stop()
        self.clear_preview(None)
        event.Skip()
