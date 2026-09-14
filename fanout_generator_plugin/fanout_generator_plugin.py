"""Reviewed pad escapes with adjustable angles and differential-pair geometry."""

from __future__ import annotations

import os
import hashlib
import json
from typing import Any, List, Tuple

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import select_items
from .geometry_preview import GeometryPreview
try:
    from .wayricad_runtime.routing_ui import build_fanout
except ImportError:
    from wayricad_runtime.routing_ui import build_fanout
try:
    from .wayricad_runtime.operations import add_group, remove_group
except ImportError:
    from wayricad_runtime.operations import add_group, remove_group
try:
    from .wayricad_runtime.geometry import board_fingerprint
except ImportError:
    from wayricad_runtime.geometry import board_fingerprint


try:
    from .wayricad_runtime.routing import plan_fanout, fanout_items, FanoutPlan, project_netclasses
except ImportError:
    from wayricad_runtime.routing import plan_fanout, fanout_items, FanoutPlan, project_netclasses

class FanoutGeneratorPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "WayriCAD Fanout Generator"
        self.category = "Routing"
        self.description = "Preview angled, staggered and paired pad escapes before applying them."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "resources", "icon-24.png")
        self.dark_icon_file_name = os.path.join(os.path.dirname(__file__), "resources", "icon-dark-24.png")
        self.version = "3.0.0"

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
            wx.MessageBox(str(exc), "WayriCAD Fanout Generator", wx.OK | wx.ICON_ERROR)


class FanoutFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="WayriCAD Fanout Generator", size=(1180, 780), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((960, 680))
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

    def _build_ui(self):
        build_fanout(self, pcbnew, lambda: open_help(self))

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

    def _plan(self):
        settings = self._settings_snapshot()
        plans, self.plan_rejections = plan_fanout(self.board, pcbnew, settings)
        return plans

    def _settings_snapshot(self):
        return {name:getattr(self,name).GetValue() for name in self._settings_names}

    def _rules_fingerprint(self):
        canonical=json.dumps(project_netclasses(self.board),sort_keys=True,separators=(',',':'),ensure_ascii=True)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def _assert_preview_current(self, ignored=()):
        if self._settings_snapshot()!=self.preview_settings:
            raise ValueError('Settings changed. Create a fresh preview.')
        if self._rules_fingerprint()!=self.preview_rules_fingerprint:
            raise ValueError('Project netclass rules changed. Create a fresh preview.')
        if board_fingerprint(self.board,ignored)!=self.preview_fingerprint:
            raise ValueError('Board changed. Create a fresh preview.')

    def preview(self, _event: Any, silent: bool = False) -> None:
        try:
            self.clear_preview(None)
            self.preview_settings=self._settings_snapshot()
            self.preview_rules_fingerprint=self._rules_fingerprint()
            self.preview_plan = self._plan()
            self.geometry_preview.set_board(self.board, pcbnew)
            self.preview_fingerprint = board_fingerprint(self.board)
            self._assert_preview_current()
            lines = []
            points = []
            line_widths = []
            point_diameters = []
            point_drills = []
            pads = []
            outlines = []
            seen_footprints = set()
            for plan in self.preview_plan:
                fp, pad, end = plan.footprint, plan.pad, plan.end
                if id(fp) not in seen_footprints:
                    seen_footprints.add(id(fp)); box = fp.GetBoundingBox()
                    outlines.append((pcbnew.ToMM(box.GetLeft()), pcbnew.ToMM(box.GetTop()), pcbnew.ToMM(box.GetRight()), pcbnew.ToMM(box.GetBottom())))
                start = pad.GetPosition()
                pads.append((pcbnew.ToMM(start.x), pcbnew.ToMM(start.y)))
                if plan.add_track:
                    for a,b in zip(plan.path,plan.path[1:]):
                        lines.append((pcbnew.ToMM(a.x),pcbnew.ToMM(a.y),pcbnew.ToMM(b.x),pcbnew.ToMM(b.y)))
                        line_widths.append(pcbnew.ToMM(plan.width))
                if plan.start_via:
                    points.append((pcbnew.ToMM(start.x), pcbnew.ToMM(start.y)))
                    point_diameters.append(pcbnew.ToMM(plan.via_diameter));point_drills.append(pcbnew.ToMM(plan.via_drill))
                if plan.add_via:
                    points.append((pcbnew.ToMM(end.x), pcbnew.ToMM(end.y)))
                    point_diameters.append(pcbnew.ToMM(plan.via_diameter));point_drills.append(pcbnew.ToMM(plan.via_drill))
                index = self.preview_list.InsertItem(self.preview_list.GetItemCount(), str(fp.GetReference()))
                result_kind = "Via in pad" if not plan.add_track else ("Track + via" if plan.add_via or plan.start_via else "Track")
                values = (str(pad.GetNumber()), str(pad.GetNetname()), str(self.board.GetLayerName(plan.layer)), f"{result_kind} | {plan.pattern}",f"{plan.length_mm:.3f}",plan.pair_id or '—')
                for column, value in enumerate(values, 1):
                    self.preview_list.SetItem(index, column, value)
            self.geometry_preview.set_geometry(lines, points, pads=pads, outlines=outlines,
                point_diameters=point_diameters,
                point_drills=point_drills,
                line_widths=line_widths,
                pad_sizes=[(pcbnew.ToMM(plan.pad.GetSize().x),pcbnew.ToMM(plan.pad.GetSize().y),-float(plan.pad.GetOrientationDegrees())) for plan in self.preview_plan])
            self.preview_items = fanout_items(self.board, pcbnew, self.preview_plan)
            self.show_button.Enable(bool(self.preview_plan))
            self.commit_button.Enable(bool(self.preview_items))
            for rejection in self.plan_rejections:
                index=self.preview_list.InsertItem(self.preview_list.GetItemCount(), "Rejected")
                self.preview_list.SetItem(index,4,rejection)
            pair_count=len({p.pair_id for p in self.preview_plan if p.pair_id})
            self.status.SetLabel(f"Preview: {len(self.preview_plan)} escapes, {pair_count} pairs, {len(self.plan_rejections)} rejected. " + '; '.join(self.plan_rejections[:2]))
            if not self.preview_plan and not silent:
                wx.MessageBox("No fanouts accepted. Inspect rejection reasons, pad scope, and dimensions.", "No fanout preview", wx.OK | wx.ICON_INFORMATION)
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
            self._assert_preview_current()
            self.preview_items = fanout_items(self.board, pcbnew, self.preview_plan)
            select_items(self.board, [p.pad for p in self.preview_plan])
            if hasattr(pcbnew, "Refresh"):
                pcbnew.Refresh()
            self.commit_button.Enable(bool(self.preview_items))
            self.status.SetLabel(f"Prepared placement: {len(self.preview_items)} prepared items. Commit adds them to the PCB.")
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
                if str(group.GetName()).startswith("WayriCAD Fanout Commit"):
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
        name = name or "WayriCAD Fanout Commit " + str(len(self._persistent_groups()) + 1).zfill(3)
        return add_group(self.board, items, name, pcbnew.PCB_GROUP)

    def generate(self, _event: Any) -> None:
        try:
            if not self.preview_items:
                wx.MessageBox("Create and inspect a preview before committing.", "Preview required", wx.OK | wx.ICON_INFORMATION)
                return
            created = list(self.preview_items)
            self._assert_preview_current(self.preview_items)
            group = self._new_commit_group(created)
            self.preview_items = []
            self.preview_plan = []
            self.show_button.Enable(False)
            self.undo_stack.append(group)
            self.redo_stack.clear()
            self.commit_button.Enable(False)
            self.undo_button.Enable(True)
            self.redo_button.Enable(False)
            select_items(self.board, created)
            self.status.SetLabel(f"Committed {len(created)} board items in a persistent WayriCAD group. Run DRC before saving.")
        except Exception as exc:
            wx.MessageBox(str(exc), "WayriCAD Fanout Generator", wx.OK | wx.ICON_ERROR)

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

    def _update_controls(self) -> None:
        via_in_pad = self.output_mode.GetValue() == "Via-in-pad"
        forced = self.pattern.GetValue().startswith("Dogbone") or via_in_pad
        self.pattern.Enable(not via_in_pad)
        for control in (self.length,self.angle_mode,self.escape_angle,self.launch_length,self.stagger_pitch,self.angle_offset,self.offset_x,self.offset_y,self.pair_mode):control.Enable(not via_in_pad)
        netclass_rules=self.use_netclass_rules.GetValue()
        self.width.Enable(not via_in_pad and not netclass_rules)
        self.via_diameter.Enable(not netclass_rules);self.via_drill.Enable(not netclass_rules)
        self.clearance.Enable(not netclass_rules)
        paired=self.pair_mode.GetValue()!='Independent' and not via_in_pad
        self.pair_gap.Enable(paired and not netclass_rules);self.max_pair_skew.Enable(paired)
        angle_used=self.angle_mode.GetValue()!='Pattern' or self.pattern.GetValue() in ('Custom-angle spread','Straight + angled escape')
        self.escape_angle.Enable(not via_in_pad and angle_used)
        self.escape_angle.Show(not via_in_pad and angle_used);self.angle_label.Show(not via_in_pad and angle_used)
        self.angle_label.SetLabel({'Pattern':'Spread angle (degrees)','Board absolute':'Board angle (degrees)','Footprint relative':'Footprint angle (degrees)'}[self.angle_mode.GetValue()])
        self.escape_angle.GetParent().FitInside();self.Layout()
        self.escape_layer.Enable(not via_in_pad)
        self.add_vias.Enable(not forced)
        if forced: self.add_vias.SetValue(True)

    def on_config_changed(self, _event: Any) -> None:
        self._update_controls()
        self.clear_preview(None)
        self.status.SetLabel("Settings changed; create a fresh preview before committing.")

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
