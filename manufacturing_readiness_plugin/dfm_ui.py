"""Dedicated native vendor DRC / DFM / DFA workspace."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import threading

import wx

from . import checklists
from .dfm_checks import audit_snapshot, source_inputs
from .dfm_present import BASIS_LABELS, FAMILIES, describe, displayed_status, evidence_entries, family
from .common_checklist import with_common_checks

def context_label(key, value):
    if isinstance(value, list): value = value[0]
    if key == 'copper_basis': value = BASIS_LABELS.get(value, value)
    return str(value) if value is not None else ''


class FindingCanvas(wx.Panel):
    def __init__(self, parent, selected):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.scene = {}; self.ids = []; self.zoom = 1.; self.selected = selected
        self.center = None; self.drag = None
        self.dimensions = []
        self.visible_layers = None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_MOUSEWHEEL, self.wheel)
        self.Bind(wx.EVT_LEFT_UP, self.pick)
        self.Bind(wx.EVT_LEFT_DCLICK, lambda event: self.fit())
        self.Bind(wx.EVT_MIDDLE_DOWN, self.pan_start); self.Bind(wx.EVT_MIDDLE_UP, self.pan_end)
        self.Bind(wx.EVT_MOTION, self.pan_move)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda event: setattr(self, 'drag', None))
        self.SetToolTip('Wheel: zoom. Middle drag: pan. Double-click: fit. Click copper to inspect its related findings.')

    def fit(self):
        self.zoom = 1.; self.center = None; self.Refresh()

    def wheel(self, event):
        self.zoom = min(50., max(.2, self.zoom * (1.25 if event.GetWheelRotation() > 0 else .8)))
        self.Refresh()

    def pan_start(self, event):
        self.drag = (event.GetX(), event.GetY())
        self.CaptureMouse()

    def pan_end(self, _event):
        self.drag = None
        if self.HasCapture(): self.ReleaseMouse()

    def pan_move(self, event):
        if self.drag is None: return
        scale, _project, inverse = self.transform()
        width, height = self.GetClientSize(); cx, cy = inverse((width/2, height/2))
        self.center = (cx-(event.GetX()-self.drag[0])/scale, cy-(event.GetY()-self.drag[1])/scale)
        self.drag = (event.GetX(), event.GetY()); self.Refresh()

    def focus(self):
        points = [point for row in self.scene.get('primitives', [])
                  if row.get('uuid') in self.ids or row.get('parent_uuid') in self.ids for point in row.get('points', [])]
        if not points: return
        xs, ys = zip(*points); a, b, c, d = min(xs), min(ys), max(xs), max(ys)
        self.center = ((a+c)/2, (b+d)/2)
        extent = self.scene.get('bounds') or [0, 0, 1, 1]
        self.zoom = min(50., max(1., min((extent[2]-extent[0])/max(2., c-a+2), (extent[3]-extent[1])/max(2., d-b+2))))
        self.Refresh()

    def transform(self):
        a, b, c, d = self.scene.get('bounds') or [0, 0, 1, 1]
        width, height = self.GetClientSize()
        scale = min(max(1, width - 30) / max(.01, c-a), max(1, height - 30) / max(.01, d-b)) * self.zoom
        cx, cy = self.center or ((a+c)/2, (b+d)/2)
        return scale, lambda point: (width/2 + (point[0]-cx)*scale, height/2 + (point[1]-cy)*scale), lambda point: (cx+(point[0]-width/2)/scale, cy+(point[1]-height/2)/scale)

    def paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self); dc.SetBackground(wx.Brush('#f7fafb')); dc.Clear()
        if not self.scene:
            dc.DrawText('Run checks to load the saved board and finding locations.', 15, 15); return
        from wayricad_runtime.board_render import draw_wx
        scale, project, _inverse = self.transform()
        gc = wx.GraphicsContext.Create(dc)
        draw_wx(gc, self.scene, project, visible_layers=self.visible_layers, highlight_ids=self.ids, scale=scale, alpha=.8)
        gc.SetPen(wx.Pen('#153d96', 2)); gc.SetBrush(wx.Brush('#153d96'))
        gc.SetFont(self.GetFont(), wx.Colour('#153d96'))
        for dimension in self.dimensions:
            if dimension['uuid'] not in self.ids: continue
            if self.visible_layers is not None and dimension.get('layer') not in self.visible_layers: continue
            a, b = project(dimension['start_mm']), project(dimension['end_mm'])
            gc.StrokeLine(*a, *b)
            dx, dy = b[0]-a[0], b[1]-a[1]; length = max(.001, (dx*dx+dy*dy)**.5)
            ux, uy = dx/length, dy/length
            for point, sign in ((a, 1), (b, -1)):
                path = gc.CreatePath(); path.MoveToPoint(*point)
                path.AddLineToPoint(point[0]+sign*ux*6-uy*3, point[1]+sign*uy*6+ux*3)
                path.AddLineToPoint(point[0]+sign*ux*6+uy*3, point[1]+sign*uy*6-ux*3)
                path.CloseSubpath(); gc.FillPath(path)
            gc.DrawText(f'{dimension["actual_mm"]:.4g} mm track width', (a[0]+b[0])/2+7, (a[1]+b[1])/2+7)

    def pick(self, event):
        if not self.scene: return
        from wayricad_runtime.board_render import hit_test
        scale, _project, inverse = self.transform()
        point = inverse((event.GetX(), event.GetY()))
        item = hit_test(self.scene, *point, visible_layers=self.visible_layers, tolerance_mm=8/scale)
        if item: self.selected(item['uuid'])

    def report_png(self, identifiers):
        import base64
        import tempfile
        from wayricad_runtime.board_render import draw_wx
        bitmap = wx.Bitmap(1100, 740); dc = wx.MemoryDC(bitmap)
        try:
            dc.SetBackground(wx.Brush('#ffffff')); dc.Clear()
            a, b, c, d = self.scene.get('bounds') or [0, 0, 1, 1]
            scale = min(1060/max(.01, c-a), 700/max(.01, d-b))
            project = lambda point: (550+(point[0]-(a+c)/2)*scale, 370+(point[1]-(b+d)/2)*scale)
            draw_wx(wx.GraphicsContext.Create(dc), self.scene, project, highlight_ids=identifiers, scale=scale, alpha=.9)
        finally:
            dc.SelectObject(wx.NullBitmap)
        with tempfile.TemporaryDirectory(prefix='wayricad-dfm-image-') as directory:
            image_path = Path(directory)/'board.png'
            if not bitmap.SaveFile(str(image_path), wx.BITMAP_TYPE_PNG): raise ValueError('Could not render the board image.')
            return base64.b64encode(image_path.read_bytes()).decode('ascii')


class DFMFrame(wx.Frame):
    def __init__(self, parent, board, saved_board=False):
        super().__init__(parent, title='WayriCAD DFM / DFA Studio', size=(1220, 820))
        self.board = board; self.path = Path(board.GetFileName()).resolve()
        self.document = None; self.bundle = None; self.rows = []; self.busy = False
        self._sha_cache = None
        self.scope_dirty = False
        self.input_checklists = set()
        self.cancel = threading.Event(); self.closing = False; self.process = None
        self.pending_change = False
        self.catalog = json.loads(Path(__file__).with_name('vendor_catalog.json').read_text(encoding='utf-8'))
        self.profiles = [with_common_checks(row) for row in self.catalog['profiles']]
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(panel, label='Vendor / service'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.profile = wx.Choice(panel, choices=[item['name'] for item in self.profiles]); self.profile.SetSelection(0)
        row.Add(self.profile, 1, wx.RIGHT, 6)
        for label, callback in [('Vendors…', self.vendors), ('Load checklist…', self.load), ('Save checklist…', self.save), ('Rule preview…', self.preview_rules)]:
            button = wx.Button(panel, label=label); button.Bind(wx.EVT_BUTTON, callback); row.Add(button, 0, wx.RIGHT, 5)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 10)
        scope = wx.FlexGridSizer(2, 8, 4, 8); self.context_fields = {}
        labels = []; controls = []
        for key, label in [('board_type', 'Board'), ('copper_oz', 'Copper oz'), ('copper_basis', 'Copper basis'),
                           ('inner_copper_oz', 'Inner copper oz'), ('layers', 'Layers'), ('material', 'Material'),
                           ('thickness_mm', 'Thickness mm'), ('finish', 'Finish')]:
            labels.append(wx.StaticText(panel, label=label))
            control = wx.TextCtrl(panel, size=(155 if key == 'copper_basis' else 95 if key not in ('board_type', 'finish') else 130, -1))
            self.context_fields[key] = control; controls.append(control)
            control.Bind(wx.EVT_TEXT, self.invalidate)
        for index in range(8): scope.AddGrowableCol(index, 1)
        for label in labels: scope.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
        for control in controls: scope.Add(control, 1, wx.EXPAND)
        root.Add(scope, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        options = wx.BoxSizer(wx.HORIZONTAL)
        self.confirm = wx.CheckBox(panel, label='I confirmed this service and process against the board and quote')
        options.Add(self.confirm, 1, wx.ALIGN_CENTER_VERTICAL)
        self.background = wx.CheckBox(panel, label='Check after saved changes'); options.Add(self.background, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.run_button = wx.Button(panel, label='Run vendor DRC / DFM checks'); self.run_button.Bind(wx.EVT_BUTTON, self.run)
        options.Add(self.run_button, 0, wx.RIGHT, 6)
        stop = wx.Button(panel, label='Cancel'); stop.Bind(wx.EVT_BUTTON, lambda event: self.cancel.set()); options.Add(stop)
        root.Add(options, 0, wx.EXPAND | wx.ALL, 10)
        self.notice = wx.StaticText(panel, label='Saved-design checks. Unknown and manual requirements are not passing checks.')
        root.Add(self.notice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        split = wx.SplitterWindow(panel)
        left = wx.Panel(split); left_layout = wx.BoxSizer(wx.VERTICAL)
        self.filter = wx.SearchCtrl(left); self.filter.SetDescriptiveText('Find rule, reference, net or status'); self.filter.Bind(wx.EVT_TEXT, self.refresh_rows)
        left_layout.Add(self.filter, 0, wx.EXPAND | wx.ALL, 5)
        self.family_choice = wx.Choice(left, choices=list(FAMILIES)); self.family_choice.SetSelection(0)
        self.family_choice.Bind(wx.EVT_CHOICE, self.refresh_rows)
        left_layout.Add(self.family_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.severity_choice = wx.Choice(left, choices=['All statuses', 'FAIL', 'WARN', 'UNKNOWN', 'PASS', 'N/A'])
        self.severity_choice.SetSelection(0); self.severity_choice.Bind(wx.EVT_CHOICE, self.refresh_rows)
        left_layout.Add(self.severity_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.table = wx.ListCtrl(left, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (name, width) in enumerate([('Status', 85), ('Category', 65), ('Rule / finding', 300), ('Measured / required', 240)]): self.table.InsertColumn(index, name, width=width)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.selected)
        left_layout.Add(self.table, 1, wx.EXPAND); left.SetSizer(left_layout)
        right = wx.Panel(split); right_layout = wx.BoxSizer(wx.VERTICAL)
        self.layer_choice = wx.Choice(right, choices=['All layers']); self.layer_choice.SetSelection(0)
        self.layer_ids = [None]; self.layer_choice.Bind(wx.EVT_CHOICE, self.layer_changed)
        right_layout.Add(self.layer_choice, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.canvas = FindingCanvas(right, self.pick_object); right_layout.Add(self.canvas, 2, wx.EXPAND)
        self.detail = wx.TextCtrl(right, style=wx.TE_MULTILINE | wx.TE_READONLY); right_layout.Add(self.detail, 1, wx.EXPAND | wx.TOP, 5)
        tools = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [('Cross-probe in PCB', self.cross_probe), ('Focus', lambda event: self.canvas.focus()), ('Fit', lambda event: self.canvas.fit()), ('Attach evidence…', self.evidence), ('Export report…', self.export)]:
            button = wx.Button(right, label=label); button.Bind(wx.EVT_BUTTON, handler); tools.Add(button, 0, wx.RIGHT, 5)
        right_layout.Add(tools, 0, wx.ALL, 5); right.SetSizer(right_layout)
        split.SplitVertically(left, right, 610); split.SetMinimumPaneSize(240)
        root.Add(split, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.footer = wx.StaticText(panel); root.Add(self.footer, 0, wx.EXPAND | wx.ALL, 10)
        panel.SetSizer(root)
        work = wx.Display(max(0, wx.Display.GetFromWindow(self))).GetClientArea()
        self.SetSize((min(1220, work.width-24), min(820, work.height-40))); self.Centre()
        self.profile.Bind(wx.EVT_CHOICE, self.choose_profile)
        self.Bind(wx.EVT_CLOSE, self.close)
        self.timer = wx.Timer(self); self.Bind(wx.EVT_TIMER, self.tick, self.timer); self.timer.Start(2000)
        self.signature = None; self.choose_profile()

    def context(self):
        process = self.document['profile']['process']; result = {}
        for key in self.context_fields:
            if key not in process: continue
            value = self.context_fields[key].GetValue().strip()
            if key == 'copper_basis': value = {label: basis for basis, label in BASIS_LABELS.items()}.get(value, value)
            result[key] = int(value) if key == 'layers' else float(value) if key in ('copper_oz', 'inner_copper_oz', 'thickness_mm') else value
        return result

    def choose_profile(self, _event=None):
        self.document = checklists.new_checklist(self.profiles[self.profile.GetSelection()]); self.clear_view()
        process = self.document['profile']['process']
        for key, control in self.context_fields.items():
            value = process.get(key)
            control.ChangeValue(context_label(key, value))
            control.Enable(key in process)
        self.context_fields['layers'].ChangeValue(str(self.board.GetCopperLayerCount()))
        scope_notes = '\n\n'.join(note for note in (self.document['profile']['process'].get('notes', ''),
                                                  self.document['profile'].get('notes', '')) if note)
        self.confirm.SetToolTip(scope_notes or 'Confirm the selected process against the saved PCB and supplier quote.')
        self.scope_dirty = False; self.update_run_caption()
        self.confirm.SetValue(False); self.refresh_rows()

    def vendors(self, _event):
        if self.busy: return
        from .vendor_catalog_ui import choose_vendor
        name = choose_vendor(self, self.catalog)
        if name:
            index = next((index for index, profile in enumerate(self.profiles) if profile['vendor'] == name), None)
            if index is not None: self.profile.SetSelection(index); self.choose_profile()

    def invalidate(self, _event=None):
        self.clear_view()
        self.scope_dirty = True; self.update_run_caption()
        self.confirm.SetValue(False); self.refresh_rows()

    def update_run_caption(self):
        if not self.document: return
        try:
            preview = checklists.compile_native_rules(self.document['profile'], self.context())
            label = 'Run vendor DRC / DFM checks' if preview['compiled_rule_ids'] else 'Run project DRC · manual vendor checks'
        except ValueError:
            label = 'Run checks · review process scope'
        self.run_button.SetLabel(label)

    def clear_view(self):
        self.bundle = None
        if hasattr(self, 'canvas'):
            self.canvas.scene = {}; self.canvas.ids = []; self.canvas.dimensions = []; self.canvas.Refresh()
            self.detail.SetValue('Run checks for the current saved design and process to update this view.')

    def current_sha(self, fresh=False):
        signature = tuple((self.path.with_suffix(suffix).stat().st_mtime_ns, self.path.with_suffix(suffix).stat().st_size)
                          if self.path.with_suffix(suffix).is_file() else None for suffix in ('.kicad_pcb', '.kicad_pro', '.kicad_dru'))
        key = (signature, json.dumps(self.context(), sort_keys=True))
        if fresh or self._sha_cache is None or self._sha_cache[0] != key:
            self._sha_cache = (key, source_inputs(self.path, self.context())[1])
        return self._sha_cache[1]

    def refresh_rows(self, _event=None):
        if not self.document: return
        try: sha = '0'*64 if self.scope_dirty or self.document['run'] is None else self.current_sha()
        except (ValueError, OSError): sha = '0' * 64
        state, rule_entries, entries = evidence_entries(self.document, sha, self.bundle)
        self.all_rows = entries
        query = self.filter.GetValue().casefold(); selected_family = self.family_choice.GetStringSelection()
        self.rows = [item for item in entries if query in json.dumps(item, ensure_ascii=False).casefold()
                     and (selected_family == FAMILIES[0] or family(item) == selected_family)
                     and (self.severity_choice.GetSelection() == 0 or displayed_status(item) == self.severity_choice.GetStringSelection())]
        self.table.DeleteAllItems()
        for item in self.rows:
            rule = item.get('rule', {}); status = displayed_status(item)
            index = self.table.InsertItem(self.table.GetItemCount(), status)
            self.table.SetItem(index, 1, rule.get('category', 'Native'))
            self.table.SetItem(index, 2, rule.get('title', item.get('message', '')))
            limits = [f'{key} {rule[key]} {rule.get("unit") or ""}' for key in ('minimum', 'maximum') if rule.get(key) is not None]
            self.table.SetItem(index, 3, ' · '.join(limits) or item['message'])
            self.table.SetItemTextColour(index, wx.Colour('#b43f36' if status == 'FAIL' else '#237a48' if status == 'PASS' else '#7b650d'))
        counts = {status: sum(displayed_status(item) == status for item in rule_entries) for status in ('PASS', 'FAIL', 'WARN', 'UNKNOWN', 'N/A')}
        self.footer.SetLabel('Requirements: '+' · '.join(f'{value} {key}' for key, value in counts.items())
                             + f' · {len((self.bundle or {}).get("findings", []))} native findings'
                             + (' · STALE / not checked' if state['stale'] else ''))

    def run(self, _event=None):
        if self.busy: return
        if not self.confirm.GetValue():
            wx.MessageBox('Confirm the manufacturer service, materials and process scope first.', 'Process scope', wx.OK | wx.ICON_INFORMATION, self); return
        try:
            profile, context = deepcopy(self.document['profile']), self.context()
            preview = checklists.compile_native_rules(profile, context)
            project_drc = not bool(preview['compiled_rule_ids'])
            self.document['selected_context'] = deepcopy(context)
        except (ValueError, OSError) as exc: self.notice.SetLabel(str(exc)); return
        self.busy = True; self.cancel.clear(); self.run_button.Disable(); self.profile.Disable()
        self.pending_change = False
        self.notice.SetLabel('Checking a private saved-design copy; PCB editing remains available.')
        def worker():
            result = scene = error = None
            def active_process(process):
                self.process = process
                if process is not None and self.cancel.is_set() and process.poll() is None:
                    process.terminate()
            try:
                result = audit_snapshot(self.path, profile, context, cancelled=self.cancel.is_set, process_hook=active_process, project_drc=project_drc)
                if self.cancel.is_set(): raise InterruptedError('Vendor checks cancelled.')
                from wayricad_runtime.board_render import extract_board
                import pcbnew
                from wayricad_runtime.saved_board import load_board, assert_current, provenance
                saved = load_board(self.path, pcbnew=pcbnew)
                if saved is None: raise ValueError('Could not load the current saved board for the preview.')
                if saved.GetCopperLayerCount() != context['layers']:
                    raise ValueError('The saved PCB layer count does not match the selected manufacturing process.')
                from .dfm_dimensions import track_width_dimensions
                identifiers = {item['uuid'] for finding in result['findings'] for item in finding.get('items', []) if item.get('uuid')}
                result['dimensions'] = track_width_dimensions(saved.GetTracks(), identifiers, pcbnew.ToMM)
                scene = extract_board(saved)
                assert_current(saved)
                record = provenance(saved)
                if record is not None: result['saved_board_provenance'] = record
            except Exception as exc: error = str(exc)
            wx.CallAfter(self.finished, result, scene, error, checklists.profile_digest(profile), context)
        threading.Thread(target=worker, daemon=True).start()

    def finished(self, result, scene, error, profile_sha, context):
        if self.closing: return
        self.busy = False; self.run_button.Enable(); self.profile.Enable()
        if error: self.notice.SetLabel(error); return
        try: current_context = self.context()
        except ValueError:
            self.notice.SetLabel('Process inputs changed during checking; results were discarded.'); return
        if checklists.profile_digest(self.document['profile']) != profile_sha or current_context != context:
            self.notice.SetLabel('Inputs changed during checking; results were discarded.'); return
        if self.current_sha(fresh=True) != result['source_sha256']:
            self.pending_change = True
            self.notice.SetLabel('Saved source changed during checking; run again.'); return
        self.document = checklists.record_run(self.document, result['source_sha256'], result['results'])
        self.scope_dirty = False
        self.bundle = result; self.canvas.scene = scene; self.canvas.ids = []
        self.canvas.dimensions = result['dimensions']['items']; self.canvas.Refresh()
        self.layer_ids = [None, *scene.get('layers', {})]
        self.layer_choice.Set(['All layers', *scene.get('layers', {}).values()]); self.layer_choice.SetSelection(0)
        self.canvas.visible_layers = None
        self.notice.SetLabel(result['notice']); self.notice.SetToolTip(result['notice']); self.refresh_rows()

    def tick(self, _event):
        try:
            signature = tuple((self.path.with_suffix(suffix).stat().st_mtime_ns, self.path.with_suffix(suffix).stat().st_size)
                              if self.path.with_suffix(suffix).is_file() else None for suffix in ('.kicad_pcb', '.kicad_pro', '.kicad_dru'))
        except OSError: return
        previous, self.signature = self.signature, signature
        if previous is not None and previous != signature:
            self.clear_view(); self.refresh_rows()
            self.pending_change = True
        if self.pending_change and self.background.GetValue() and self.confirm.GetValue() and not self.busy: self.run()

    def selected(self, event):
        item = self.rows[event.GetIndex()]; self.canvas.ids = item.get('object_ids', []); self.canvas.Refresh()
        self.detail.SetValue(describe(item, self.document['profile']))

    def layer_changed(self, _event):
        layer = self.layer_ids[self.layer_choice.GetSelection()]
        self.canvas.visible_layers = None if layer is None else [layer]
        self.canvas.Refresh()

    def pick_object(self, identifier):
        for index, item in enumerate(self.rows):
            if identifier in item.get('object_ids', []): self.table.Select(index); self.table.EnsureVisible(index); return
        self.detail.SetValue('No finding is linked to this saved-board item: ' + identifier)

    def cross_probe(self, _event):
        if not self.current_result(): return
        try:
            from wayricad_runtime.analysis_selection import select_origin
            select_origin(self.path, self.canvas.ids, expected_sha256=self.bundle['board_sha256'], focus=True)
        except Exception as exc: self.notice.SetLabel(str(exc))

    def current_result(self):
        try:
            if self.bundle is not None and self.current_sha(fresh=True) == self.bundle['source_sha256']:
                return True
        except (ValueError, OSError):
            pass
        self.clear_view()
        self.notice.SetLabel('Run checks for the current saved design and process before exporting or cross-probing.')
        return False

    def evidence(self, _event):
        index = self.table.GetFirstSelected()
        if index < 0 or 'rule_id' not in self.rows[index]: return
        with wx.TextEntryDialog(self, 'Describe the measurement or supplier confirmation, including its source.', 'Attach manual evidence') as dialog:
            if dialog.ShowModal() == wx.ID_OK and dialog.GetValue().strip():
                try:
                    self.store_context()
                    rule_id = self.rows[index]['rule_id']; sha = self.current_sha(fresh=True)
                    self.document = checklists.add_manual_evidence(self.document, rule_id, sha, dialog.GetValue())
                    if self.rows[index].get('rule', {}).get('backend') == 'manual':
                        choices = ['Attach evidence; leave untested', 'Pass based on this evidence', 'Fail based on this evidence']
                        with wx.SingleChoiceDialog(self, 'Record your evaluation of this manual requirement.', 'Manual evaluation', choices) as evaluation:
                            if evaluation.ShowModal() == wx.ID_OK and evaluation.GetSelection() > 0:
                                state = checklists.checklist_state(self.document, sha)
                                results = deepcopy(self.document['run']['results']) if not state['stale'] else []
                                results = [row for row in results if row['rule_id'] != rule_id]
                                results.append(dict(rule_id=rule_id, status='PASS' if evaluation.GetSelection() == 1 else 'FAIL',
                                                    message='Manual evaluation with attached evidence: ' + dialog.GetValue()))
                                self.document = checklists.record_run(self.document, sha, results)
                    self.refresh_rows()
                except (ValueError, OSError) as exc: self.notice.SetLabel(str(exc))

    def store_context(self):
        context = self.context()
        checklists.compile_native_rules(self.document['profile'], context)
        self.document['selected_context'] = deepcopy(context)
        self.scope_dirty = False

    def preview_rules(self, _event):
        try:
            preview = checklists.compile_native_rules(self.document['profile'], self.context())
            text = preview['text'] if preview['compiled_rule_ids'] else 'No native vendor rules are available. This checklist can run saved project DRC and retain vendor-specific checks as manual/unknown.\n\n'+preview['text']
        except ValueError as exc: self.notice.SetLabel(str(exc)); return
        dialog = wx.Dialog(self, title='Native vendor-rule preview · no project files are changed', size=(800, 520), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        layout = wx.BoxSizer(wx.VERTICAL); layout.Add(wx.TextCtrl(dialog, value=text, style=wx.TE_MULTILINE | wx.TE_READONLY), 1, wx.EXPAND | wx.ALL, 10)
        layout.Add(dialog.CreateButtonSizer(wx.OK), 0, wx.ALIGN_RIGHT | wx.ALL, 10); dialog.SetSizer(layout)
        try: dialog.ShowModal()
        finally: dialog.Destroy()

    def load(self, _event):
        if self.busy: return
        with wx.FileDialog(self, 'Load checklist', wildcard='Checklist JSON (*.json)|*.json', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            try:
                try: self.document = checklists.load_checklist(dialog.GetPath())
                except ValueError:
                    self.document = checklists.new_checklist(with_common_checks(checklists.load_profile(dialog.GetPath())))
                self.clear_view()
                self.input_checklists.add(Path(dialog.GetPath()).resolve())
                profile = self.document['profile']; self.profiles.append(profile); self.profile.Append(profile['name']); self.profile.SetSelection(len(self.profiles)-1)
                selected_context = self.document.get('selected_context', {})
                for key, control in self.context_fields.items():
                    value = selected_context.get(key, profile['process'].get(key)); control.ChangeValue(context_label(key, value)); control.Enable(key in profile['process'])
                self.scope_dirty = False; self.update_run_caption()
                self.confirm.SetValue(False); self.refresh_rows()
            except (ValueError, OSError) as exc: self.notice.SetLabel(str(exc))

    def save(self, _event):
        with wx.FileDialog(self, 'Save checklist', defaultDir=str(self.path.parent), defaultFile=self.path.stem+'-checklist.json', wildcard='Checklist JSON (*.json)|*.json', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self.store_context()
                    checklists.save_checklist(dialog.GetPath(), self.document)
                    self.input_checklists.add(Path(dialog.GetPath()).resolve())
                except (ValueError, OSError) as exc: self.notice.SetLabel(str(exc))

    def export(self, _event):
        if not self.current_result(): return
        with wx.FileDialog(self, 'Export DFM / DFA report', defaultDir=str(self.path.parent), defaultFile=self.path.stem+'-dfm.html', wildcard='HTML report (*.html)|*.html|PDF report (*.pdf)|*.pdf', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            try:
                from .dfm_report import export_report
                identifiers = {identifier for row in self.all_rows if row['status'] == 'FAIL' for identifier in row.get('object_ids', [])}
                export_report(dialog.GetPath(), self.path, self.context(), self.bundle, self.document, self.all_rows,
                              board_png=self.canvas.report_png(identifiers), protected_sources=self.input_checklists)
            except Exception as exc: self.notice.SetLabel(str(exc))

    def close(self, _event):
        self.closing = True; self.cancel.set(); self.timer.Stop()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        self.Destroy()
