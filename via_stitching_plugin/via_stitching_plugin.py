"""Net-aware ground/signal via stitching grid generator."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Set, Tuple

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import select_items
from .geometry_preview import GeometryPreview
try:
    from .wayricad_runtime.routing_ui import build_stitching
except ImportError:
    from wayricad_runtime.routing_ui import build_stitching
try:
    from .wayricad_runtime.operations import add_group, remove_group
except ImportError:
    from wayricad_runtime.operations import add_group, remove_group
try:
    from .wayricad_runtime.geometry import board_fingerprint
except ImportError:
    from wayricad_runtime.geometry import board_fingerprint


try:
    from .wayricad_runtime.routing import plan_stitching
except ImportError:
    from wayricad_runtime.routing import plan_stitching

class ViaStitchingPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "WayriCAD Via Stitching"
        self.category = "Routing"
        self.description = "Generate a configurable ground-via stitching grid."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "resources", "icon-24.png")
        self.dark_icon_file_name = os.path.join(os.path.dirname(__file__), "resources", "icon-dark-24.png")
        self.version = "3.1.0"

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
            wx.MessageBox(str(exc), "WayriCAD Via Stitching", wx.OK | wx.ICON_ERROR)


class ViaFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="WayriCAD Via Stitching", size=(1180, 780), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((960, 680))
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

    def _build_ui(self):
        build_stitching(self, pcbnew, lambda: open_help(self))

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

    def _plan(self):
        settings = {name: getattr(self, name).GetValue() for name in self._settings_names}
        plans, self.plan_rejections = plan_stitching(self.board, pcbnew, settings)
        return plans

    def preview(self, _event: Any, silent: bool = False) -> None:
        try:
            self.clear_preview(None)
            self.preview_plan = self._plan()
            self.geometry_preview.set_board(self.board, pcbnew)
            self.preview_fingerprint=board_fingerprint(self.board)
            net_name, _net_code = self._selected_net()
            points = []
            for number, via in enumerate(self.preview_plan, 1):
                position = via.GetPosition()
                points.append((pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)))
                index = self.preview_list.InsertItem(self.preview_list.GetItemCount(), str(number))
                values = (net_name or "<No net>", f"{pcbnew.ToMM(position.x):.3f}", f"{pcbnew.ToMM(position.y):.3f}", "Accepted")
                for column, value in enumerate(values, 1):
                    self.preview_list.SetItem(index, column, value)
            left, top, right, bottom = self._bounds()
            outline = [(pcbnew.ToMM(left), pcbnew.ToMM(top), pcbnew.ToMM(right), pcbnew.ToMM(bottom))]
            self.geometry_preview.set_geometry(points=points, outlines=outline, point_diameters=[float(self.diameter.GetValue())] * len(points),point_drills=[float(self.drill.GetValue())]*len(points))
            self.preview_items = list(self.preview_plan)
            self.show_button.Enable(bool(self.preview_plan))
            self.commit_button.Enable(bool(self.preview_items))
            self.status.SetLabel(f"Window preview: {len(self.preview_plan)} accepted vias. The PCB has not been changed.")
            if self.plan_rejections:
                detail = ", ".join(f"{count} {reason}" for reason, count in sorted(self.plan_rejections.items()))
                self.status.SetLabel(f"Window preview: {len(self.preview_plan)} accepted; rejected {detail}.")
            for reason,count in sorted(self.plan_rejections.items()):
                index=self.preview_list.InsertItem(self.preview_list.GetItemCount(),str(count))
                self.preview_list.SetItem(index,4,"Rejected: "+reason)
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
            if board_fingerprint(self.board)!=self.preview_fingerprint:raise ValueError('Board changed. Create a fresh preview.')
            for via in self.preview_plan:
                self.preview_items.append(via)
            self.status.SetLabel("Reviewed candidates are ready to commit.")
            if hasattr(pcbnew, "Refresh"):
                pcbnew.Refresh()
            self.commit_button.Enable(bool(self.preview_items))
            self.status.SetLabel(f"Prepared placement: {len(self.preview_items)} prepared vias. Commit adds them to the PCB.")
        except Exception as exc:
            self.clear_pcb_preview()
            self.status.SetLabel(str(exc))
            wx.MessageBox(str(exc), "Placement review failed", wx.OK | wx.ICON_ERROR)

    def clear_pcb_preview(self) -> None:
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

    def _persistent_groups(self) -> List[Any]:
        groups = []
        for group in getattr(self.board, "Groups", lambda: [])():
            try:
                if str(group.GetName()).startswith("WayriCAD Via Stitch Commit"):
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
        name = name or "WayriCAD Via Stitch Commit " + str(len(self._persistent_groups()) + 1).zfill(3)
        return add_group(self.board, items, name, pcbnew.PCB_GROUP)

    def generate(self, _event: Any) -> None:
        try:
            if not self.preview_items:
                wx.MessageBox("Create and inspect a preview before committing.", "Preview required", wx.OK | wx.ICON_INFORMATION)
                return
            committed = list(self.preview_items)
            if board_fingerprint(self.board,self.preview_items)!=self.preview_fingerprint:raise ValueError('Board changed. Clear and regenerate the preview before committing.')
            group = self._new_commit_group(committed)
            self.preview_items = []
            self.preview_plan = []
            self.show_button.Enable(False)
            self.undo_stack.append(group)
            self.redo_stack.clear()
            self.commit_button.Enable(False)
            self.undo_button.Enable(True)
            self.redo_button.Enable(False)
            select_items(self.board, committed)
            self.status.SetLabel(f"Committed {len(committed)} vias in a persistent WayriCAD group. Run DRC before saving.")
        except Exception as exc:
            wx.MessageBox(str(exc), "WayriCAD Via Stitching", wx.OK | wx.ICON_ERROR)

    def undo(self, _event: Any) -> None:
        if not self.undo_stack:
            self.status.SetLabel("Nothing to undo.")
            return
        group = self.undo_stack[-1]
        try:
            items = self._group_items(group)
            name = str(group.GetName())
            remove_group(self.board, group, items)
        except Exception as exc:
            self.recovery_error = exc
            wx.MessageBox(str(exc), "Undo failed", wx.OK | wx.ICON_ERROR)
            return
        self.undo_stack.pop()
        self.redo_stack.append((name, items))
        self.undo_button.Enable(bool(self.undo_stack))
        self.redo_button.Enable(True)
        pcbnew.Refresh()
        self.status.SetLabel(f"Undid {len(items)} items.")

    def redo(self, _event: Any) -> None:
        if not self.redo_stack:
            self.status.SetLabel("Nothing to redo.")
            return
        name, items = self.redo_stack[-1]
        try:
            group = self._new_commit_group(items, name)
        except Exception as exc:
            self.recovery_error = exc
            wx.MessageBox(str(exc), "Redo failed", wx.OK | wx.ICON_ERROR)
            return
        self.redo_stack.pop()
        self.undo_stack.append(group)
        self.undo_button.Enable(True)
        self.redo_button.Enable(bool(self.redo_stack))
        pcbnew.Refresh()
        self.status.SetLabel(f"Restored {len(items)} items.")

    def on_config_changed(self, _event: Any) -> None:
        self.clear_preview(None)
        self.status.SetLabel("Settings changed; create a fresh preview before committing.")

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
        index=event.GetIndex()
        if 0 <= index < len(self.geometry_preview.points):
            self.geometry_preview.pick=index
            self.geometry_preview.Refresh()
            x,y=self.geometry_preview.points[index]
            self.status.SetLabel(f"Candidate {index + 1}: {x:.3f}, {y:.3f} mm.")

    def on_close(self, event: Any) -> None:
        self.selection_timer.Stop()
        self.clear_preview(None)
        event.Skip()
