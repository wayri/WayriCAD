"""Reviewed pad escapes with adjustable angles and differential-pair geometry."""

from __future__ import annotations

import os
import hashlib
import json
import fnmatch
from copy import deepcopy
from pathlib import Path
from typing import Any, List, Tuple

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import select_items
from .geometry_preview import GeometryPreview
try:
    from .wayricad_runtime.routing_ui import build_fanout, choose_review_destination
except ImportError:
    from wayricad_runtime.routing_ui import build_fanout, choose_review_destination
try:
    from .wayricad_runtime.operations import add_group, remove_group
except ImportError:
    from wayricad_runtime.operations import add_group, remove_group
try:
    from .wayricad_runtime.geometry import board_fingerprint
    from .wayricad_runtime.ipc import read_snapshot
except ImportError:
    from wayricad_runtime.geometry import board_fingerprint
    from wayricad_runtime.ipc import read_snapshot


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
        self.version = "3.6.30"

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
        self._live_call = None
        self._preview_busy = False
        self._closing = False
        self._context_fingerprint = None
        self._routing_job = None
        self._queued_preview = False
        self._preview_revision = 0
        self._review_geometry = None
        self._snapshot_cache = None
        self._context_file_stamp = None
        self.preview_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._poll_preview, self.preview_timer)
        self.selection_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_selection_timer, self.selection_timer)
        self._build_ui()
        self.undo_stack = self._persistent_groups()
        self.undo_button.Enable(bool(self.undo_stack))
        self._sync_selection(force=True)
        self.selection_timer.Start(500)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self.Bind(wx.EVT_ACTIVATE, self._activated)
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
        settings={name:getattr(self,name).GetValue() for name in self._settings_names}
        settings.update(groups=deepcopy(self.fanout_groups),unmatched=self.group_unmatched)
        return settings

    def _rules_fingerprint(self):
        canonical=json.dumps(project_netclasses(self.board),sort_keys=True,separators=(',',':'),ensure_ascii=True)
        rules=Path(self.board.GetFileName()).with_suffix('.kicad_dru') if self.board.GetFileName() else None
        native=rules.read_bytes() if rules and rules.exists() else b''
        return hashlib.sha256(canonical.encode('utf-8')+native).hexdigest()

    def _assert_preview_current(self, ignored=()):
        if self._settings_snapshot()!=self.preview_settings:
            raise ValueError('Settings changed. Create a fresh preview.')
        if self._rules_fingerprint()!=self.preview_rules_fingerprint:
            raise ValueError('Project netclass rules changed. Create a fresh preview.')
        fingerprint=board_fingerprint(self.board,ignored)
        if fingerprint!=self.preview_fingerprint:
            raise ValueError('Board changed. Create a fresh preview.')
        if getattr(self,'_preview_identity',None):
            from wayricad_runtime.routing_worker import assert_current
            assert_current(self.board,pcbnew,self._preview_identity,current_fingerprint=fingerprint)

    def preview(self, _event: Any, silent: bool = False) -> None:
        self._cancel_live_preview()
        if self._preview_busy:
            self._queued_preview = True
            if self._routing_job:self._routing_job.cancel()
            return
        try:
            from wayricad_runtime.routing_worker import start_job
            self.clear_preview(None)
            self.preview_settings = self._settings_snapshot()
            self.preview_rules_fingerprint = self._rules_fingerprint()
            self._job_revision = self._preview_revision
            self._job_selection = self.last_selection_signature
            mode = 'live' if self.snapshot_mode.GetValue().startswith('Live') else 'auto'
            path=Path(self.board.GetFileName()) if self.board.GetFileName() else None
            stat=path.stat() if path and path.is_file() else None
            self._job_file_stamp=(mode,str(path.resolve()) if path else '',stat.st_mtime_ns,stat.st_size) if stat else (mode,'',None,None)
            include_context=(self._context_fingerprint is None or self._job_file_stamp!=self._context_file_stamp
                             or mode=='live' or hasattr(self.board,'raw'))
            self.status.SetLabel('Capturing a live snapshot… this first capture can take several seconds.' if mode == 'live' else 'Planning from a private saved-board snapshot…')
            self.status.Update()
            self._routing_job = start_job(self.board, pcbnew, self.preview_settings, kind='fanout',
                include_context=include_context, snapshot_mode=mode, timeout=60)
            self._preview_busy = True
            self.preview_progress.Pulse();self.preview_cancel.Enable()
            self.preview_badge.SetLabel('PLANNING · board unchanged')
            self.preview_counts.SetLabel('Checking the chosen pads…')
            self.preview_timer.Start(80)
        except Exception as exc:
            self._preview_busy = False
            self.status.SetLabel(str(exc));self.preview_badge.SetLabel('INPUT NEEDED')
            if not silent:wx.MessageBox(str(exc), 'Fanout preview', wx.OK | wx.ICON_INFORMATION)

    def _poll_preview(self, event=None):
        job = self._routing_job
        if job is None:return
        if not job.done():
            self.preview_progress.Pulse()
            self.preview_counts.SetLabel(f'Planning · {job.elapsed:.1f} s · board unchanged')
            return
        self.preview_timer.Stop();self._routing_job = None;self._preview_busy = False
        self.preview_cancel.Disable();self.preview_progress.SetValue(0)
        try:
            result = job.result()
            if self._closing:return
            if self._job_revision != self._preview_revision or self.preview_settings != self._settings_snapshot():
                self.status.SetLabel('Settings changed; outdated preview discarded.')
            elif self._job_selection != self.last_selection_signature:
                self.status.SetLabel('Selection changed; outdated preview discarded.')
            else:
                if result.get('identity',{}).get('mode')=='saved' and bool(getattr(self.board,'IsModified',lambda:False)()):
                    raise ValueError('The PCB has unsaved changes. Save them and refresh, or explicitly choose a live snapshot.')
                self._preview_identity=result.get('identity')
                self._render_preview(result)
        except Exception as exc:
            if not self._closing:
                self.status.SetLabel(str(exc));self.preview_badge.SetLabel('CANCELLED' if 'cancel' in str(exc).lower() else 'NEEDS REVIEW')
        finally:
            job.close()
        if self._queued_preview and not self._closing:
            self._queued_preview = False
            self._schedule_live_preview()

    def cancel_preview(self, event=None):
        self._queued_preview = False
        if self._routing_job:self._routing_job.cancel()
        self.preview_badge.SetLabel('CANCELLING')

    def _render_preview(self, result):
        self._preview_busy = True
        try:
            from wayricad_runtime.geometry import item_id
            pads = {item_id(pad): (fp, pad) for fp in self.board.GetFootprints() for pad in fp.Pads()}
            layers={str(self.board.GetLayerName(layer)):int(layer) for layer in self.board.GetEnabledLayers().CuStack()}
            self.preview_plan = []
            for record in result.get('candidates', []):
                values = dict(record);pad_id=values.pop('pad_uuid');fp_id=values.pop('footprint_uuid')
                if pad_id not in pads:raise ValueError('A planned pad no longer exists; create a fresh preview.')
                fp,pad=pads[pad_id]
                if item_id(fp)!=fp_id:raise ValueError('A planned pad changed footprint; create a fresh preview.')
                layer_name=values.pop('layer_name')
                if layer_name not in layers:raise ValueError('The planned copper layer is no longer enabled; create a fresh preview.')
                values['layer']=layers[layer_name]
                values['net_code']=pad.GetNetCode()
                for name in ('start','end'):values[name]=pcbnew.VECTOR2I(*values[name])
                for name in ('path','connector_region'):values[name]=[pcbnew.VECTOR2I(*point) for point in values[name]]
                self.preview_plan.append(FanoutPlan(footprint=fp,pad=pad,**values))
            self.plan_rejections=result.get('rejected',[])
            self.preview_fingerprint=result['source_fingerprint']
            if result.get('context'):
                for name,value in result['context'].items():setattr(self.geometry_preview,name,value)
                self.geometry_preview.invalidate_scene();self._context_fingerprint=self.preview_fingerprint
                self._context_file_stamp=self._job_file_stamp
            self.preview_list.Freeze()
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
                values = (str(pad.GetNumber()), str(pad.GetNetname()), str(self.board.GetLayerName(plan.layer)), f"{result_kind} | {plan.pattern}",f"{plan.length_mm:.3f}",plan.pair_id or '—',plan.group_name)
                for column, value in enumerate(values, 1):
                    self.preview_list.SetItem(index, column, value)
            self.geometry_preview.set_geometry(lines, points, pads=pads, outlines=outlines,
                point_diameters=point_diameters,
                point_drills=point_drills,
                line_widths=line_widths,
                pad_sizes=[(pcbnew.ToMM(plan.pad.GetSize().x),pcbnew.ToMM(plan.pad.GetSize().y),-float(plan.pad.GetOrientationDegrees())) for plan in self.preview_plan])
            self._review_geometry = {name:list(getattr(self.geometry_preview,name)) for name in
                ('lines','points','pads','outlines','point_diameters','point_drills','line_widths','pad_sizes')}
            self._review_focus = [point for outline in outlines for point in (outline[:2],outline[2:])]
            self.on_review_mode(None)
            self.preview_items = fanout_items(self.board, pcbnew, self.preview_plan)
            self.export_button.Enable(any(p.local_clearance for p in self.preview_plan))
            self.show_button.Enable(bool(self.preview_plan))
            self.commit_button.Enable(bool(self.preview_items) and not any(p.local_clearance for p in self.preview_plan))
            for rejection in self.plan_rejections:
                index=self.preview_list.InsertItem(self.preview_list.GetItemCount(), "Rejected")
                self.preview_list.SetItem(index,4,rejection)
            self.preview_list.Thaw()
            self._update_style_preview()
            pair_count=len({p.pair_id for p in self.preview_plan if p.pair_id})
            self.status.SetLabel(f"Preview: {len(self.preview_plan)} escapes, {pair_count} pairs, {len(self.plan_rejections)} rejected. " + ('Local clearance: export a review project. ' if any(p.local_clearance for p in self.preview_plan) else '') + '; '.join(self.plan_rejections[:2]))
            self.preview_counts.SetLabel(f'{len(self.preview_plan)} accepted · {len(self.plan_rejections)} rejected · {pair_count} pairs')
            self.preview_badge.SetLabel('3 · REVIEW / APPLY' if self.preview_plan else '3 · REVIEW REJECTIONS')
        except Exception as exc:
            self.status.SetLabel(str(exc))
            self.commit_button.Disable();self.preview_badge.SetLabel('NEEDS REVIEW')
        finally:
            if self.preview_list.IsFrozen():self.preview_list.Thaw()
            self._preview_busy = False

    def on_review_mode(self,event=None):
        if self._review_geometry is None:return
        geometry = self._review_geometry if self.review_mode.GetSelection() else {}
        self.geometry_preview.focus_points=list(self._review_focus)
        self.geometry_preview.set_geometry(**geometry)
        self.geometry_preview.Refresh()

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
            self.commit_button.Enable(bool(self.preview_items) and not any(p.local_clearance for p in self.preview_plan))
            self.status.SetLabel(f"Prepared placement: {len(self.preview_items)} prepared items. Commit adds them to the PCB.")
        except Exception as exc:
            self.clear_pcb_preview()
            self.status.SetLabel(str(exc))
            wx.MessageBox(str(exc), "Placement review failed", wx.OK | wx.ICON_ERROR)

    def clear_pcb_preview(self) -> None:
        self.preview_items = []
        self.commit_button.Enable(False)

    def clear_preview(self, _event: Any) -> None:
        self._preview_revision += 1
        if self._routing_job:
            self._routing_job.cancel()
            self._queued_preview = _event is None and not self._closing
        self._cancel_live_preview()
        self.clear_pcb_preview()
        self.preview_plan = []
        self.export_button.Disable()
        self.preview_list.DeleteAllItems()
        self.geometry_preview.clear()
        self.style_preview.clear()
        self.style_summary.SetLabel('Choose a component and style to preview.')
        self._review_geometry = None
        self.preview_counts.SetLabel('No current candidates · choose scope and style')
        self.preview_badge.SetLabel('1 · SELECT TARGETS')
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
            if any(p.local_clearance for p in self.preview_plan):
                raise ValueError('Local clearance requires Export review project; the live board is unchanged.')
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
            self.status.SetLabel(f"Committed {len(created)} board items. Refill zones (B), then run DRC before saving.")
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

    def export_connector_review(self, _event):
        try:
            if not self.preview_plan:raise ValueError('Create and inspect a preview first.')
            self._assert_preview_current(self.preview_items)
            destination=choose_review_destination(self)
            if destination is None:return
            try:
                from .wayricad_runtime.connector_review import export_connector_review
            except ImportError:
                from wayricad_runtime.connector_review import export_connector_review
            if destination.exists():raise ValueError('Choose a new project name; existing outputs are preserved.')
            result=export_connector_review(self.board, pcbnew, self.preview_plan, destination.with_suffix(''), name=destination.stem)
            self.status.SetLabel('Exported review project. Open it in KiCad, refill zones (B), then run DRC before adopting the routes.')
        except Exception as exc:
            wx.MessageBox(str(exc), 'Connector review export', wx.OK|wx.ICON_ERROR)

    def _update_controls(self) -> None:
        if hasattr(self,'snapshot_mode'):
            self.auto_refresh.Enable(hasattr(self.board,'raw') or not self.snapshot_mode.GetValue().startswith('Live'))
        wildcard = self.scope.GetValue() == 'Reference wildcard'
        self.ref.Show(wildcard);self.ref_label.Show(wildcard)
        connector = self.pattern.GetValue() == 'Connector edge'
        self.connector_exit.Show(connector);self.connector_exit_label.Show(connector)
        for control in (self.connector_exit,self.connector_edge_margin,self.connector_clearance):control.Enable(connector)
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
        if _event is not None and _event.GetEventObject() is self.pattern and self.pattern.GetValue()=='Connector edge':
            self.add_vias.SetValue(False);self.routing_mode.SetValue('Fixed');self.pair_mode.SetValue('Independent')
        self._update_controls()
        self.clear_preview(None)
        self._schedule_live_preview()

    def _selection_signature(self) -> Tuple[Any, ...]:
        with read_snapshot(self.board):
            if hasattr(self.board, 'read_snapshot'):
                refs=set();pads=set()
                for item in self.board.GetSelection():
                    if item.GetClass()=='FOOTPRINT':refs.add(str(item.GetReference()))
                    elif item.GetClass()=='PAD':
                        parent=item.GetParentFootprint()
                        if parent is None:
                            # Older API payloads may lack parent identifiers.
                            return tuple(sorted(self._selected_footprint_refs())), tuple(sorted(self._selected_pad_keys()))
                        ref=str(parent.GetReference());refs.add(ref)
                        pads.add((ref,str(item.GetNumber())))
                return tuple(sorted(refs)),tuple(sorted(pads))
            refs=set();pads=set()
            for fp in self.board.GetFootprints():
                ref=str(fp.GetReference())
                if fp.IsSelected():refs.add(ref)
                for pad in fp.Pads():
                    if pad.IsSelected():refs.add(ref);pads.add((ref,str(pad.GetNumber())))
            return tuple(sorted(refs)),tuple(sorted(pads))

    def _sync_selection(self, force: bool = False) -> None:
        signature = self._selection_signature()
        if not force and signature == self.last_selection_signature:
            return
        self.last_selection_signature = signature
        refs, pads = signature
        self.selection_status.SetLabel(f"PCB selection: {len(refs)} footprints, {len(pads)} pads")
        if len(refs) == 1 and self.scope.GetValue() in ("Selected pads", "Selected footprints"):
            self.ref.ChangeValue(str(refs[0]))
        self.clear_preview(None)
        self._schedule_live_preview()

    def on_selection_timer(self, _event: Any) -> None:
        if self._preview_busy or not self.IsShownOnScreen() or not self.IsActive():return
        try:
            self._sync_selection()
        except Exception:
            pass

    def _activated(self,event):
        if event.GetActive() and not self._closing:
            self._sync_selection()
        event.Skip()

    def on_preview_row_activated(self, event: Any) -> None:
        index = event.GetIndex()
        if 0 <= index < len(self.preview_plan):
            select_items(self.board, [self.preview_plan[index].pad])
            self.status.SetLabel(
                f"Selected {self.preview_plan[index].footprint.GetReference()}.{self.preview_plan[index].pad.GetNumber()} on PCB."
            )

    def _cancel_live_preview(self):
        if self._live_call is not None:
            self._live_call.Stop();self._live_call=None

    def _schedule_live_preview(self):
        self._cancel_live_preview()
        if hasattr(self,'snapshot_mode') and self.snapshot_mode.GetValue().startswith('Live') and not hasattr(self.board,'raw'):
            self.status.SetLabel('Live native capture is manual. Click Refresh preview; save the board for automatic fast previews.')
            return
        if self._closing:return
        if not self.auto_refresh.GetValue():
            self.status.SetLabel('Choose pads and a style, then Refresh preview. Apply stays separate.')
            return
        refs,pads=self.last_selection_signature or ((),())
        if self.scope.GetValue() in ('Selected pads','Selected footprints') and not (pads if self.scope.GetValue()=='Selected pads' else refs):
            self.status.SetLabel('Select footprints or pads in PCB Editor. The preview follows your selection.')
            return
        if self.scope.GetValue() in ('All SMD pads','All connector pads') or (self.scope.GetValue()=='Reference wildcard' and self.ref.GetValue().strip() in ('','*')):
            self.status.SetLabel('Whole-board scope: click Refresh preview to run all pads. Live preview follows selected components.')
            return
        self.status.SetLabel('Updating preview… Apply will be available after checks complete.')
        self._live_call=wx.CallLater(300,self._run_live_preview)

    def _run_live_preview(self):
        self._live_call=None
        if self._closing or not self.auto_refresh.GetValue():return
        self.preview(None,silent=True)

    def on_live_preview_changed(self,event):
        if self.auto_refresh.GetValue():self._schedule_live_preview()
        else:self._cancel_live_preview()

    def _update_style_preview(self,event=None):
        refs,pads=self.last_selection_signature or ((),())
        targets=set(refs)|{str(plan.footprint.GetReference()) for plan in self.preview_plan}
        if self.scope.GetValue()=='Reference wildcard':
            patterns=[part.strip().upper() for part in self.ref.GetValue().split(',') if part.strip()]
            targets.update(str(fp.GetReference()) for fp in self.board.GetFootprints()
                           if any(fnmatch.fnmatchcase(str(fp.GetReference()).upper(),pattern) for pattern in patterns))
        choices=sorted(targets)
        current=self.style_component.GetValue()
        if choices != list(self.style_component.GetStrings()):
            self.style_component.SetItems(choices)
        chosen=current if current in choices else choices[0] if choices else ''
        self.style_component.SetValue(chosen)
        self.style_preview.set_board_context(self.geometry_preview)
        plans=[plan for plan in self.preview_plan if str(plan.footprint.GetReference())==chosen]
        lines=[];points=[];widths=[];diameters=[];drills=[];centres=[]
        for plan in plans:
            start=plan.start or plan.pad.GetPosition()
            centres.append((pcbnew.ToMM(start.x),pcbnew.ToMM(start.y)))
            if plan.add_track:
                for a,b in zip(plan.path,plan.path[1:]):
                    lines.append((pcbnew.ToMM(a.x),pcbnew.ToMM(a.y),pcbnew.ToMM(b.x),pcbnew.ToMM(b.y)))
                    widths.append(pcbnew.ToMM(plan.width))
            for pos in ([start] if plan.start_via else [])+([plan.end] if plan.add_via else []):
                points.append((pcbnew.ToMM(pos.x),pcbnew.ToMM(pos.y)))
                diameters.append(pcbnew.ToMM(plan.via_diameter));drills.append(pcbnew.ToMM(plan.via_drill))
        focus=[]
        for fp in self.board.GetFootprints():
            if str(fp.GetReference())==chosen:
                focus=[(pcbnew.ToMM(p.GetPosition().x),pcbnew.ToMM(p.GetPosition().y)) for p in fp.Pads()]
                break
        self.style_preview.focus_points=focus
        self.style_preview.set_geometry(lines,points,pads=focus or centres,line_widths=widths,point_diameters=diameters,point_drills=drills)
        self.style_preview.fit()
        styles={plan.pattern for plan in plans}
        label=('Via-in-pad' if self.output_mode.GetValue()=='Via-in-pad' else self.pattern.GetValue()) if len(styles)<=1 else f'{len(styles)} styles (group rules)'
        self.style_summary.SetLabel(f'{chosen or "No component"} - {label}\n{len(plans)} accepted escapes. Teal = proposed; gold = pads.')
        self.style_summary.SetToolTip('Actual clearance-checked candidates for this component. Rejected pins stay in Candidate details; no hypothetical copper is shown.')
        self.style_summary.Wrap(max(180,self.style_summary.GetParent().GetClientSize().width-16))
        self.style_summary.InvalidateBestSize()
        self.settings_pane.GetSizer().Layout();self.settings_pane.FitInside()
        self.Layout()

    def on_close(self, event: Any) -> None:
        self._closing=True
        self.selection_timer.Stop()
        self.clear_preview(None)
        self.preview_timer.Stop()
        if self._routing_job:self._routing_job.close()
        event.Skip()

    def _on_destroy(self,event):
        if event.GetEventObject() is self:
            self._closing=True;self._cancel_live_preview();self.selection_timer.Stop()
        event.Skip()

    def Destroy(self):
        self._closing=True;self._cancel_live_preview();self.selection_timer.Stop()
        self.preview_timer.Stop()
        if self._routing_job:self._routing_job.close()
        return super().Destroy()
