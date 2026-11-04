"""Saved-board bulk extraction workspace, linked copper review and reports."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
from html import escape
import io
import json
import math
from pathlib import Path
import threading
from wayricad_runtime.saved_board import assert_current, load_board, provenance


def source_fingerprints(board_path):
    source = Path(board_path).resolve()
    if not source.is_file() or source.suffix.lower() != '.kicad_pcb':
        raise ValueError('Open and save a PCB before running bulk extraction.')
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            for path in (source, source.with_suffix('.kicad_pro'), source.with_suffix('.kicad_dru'))}


def verify_sources(fingerprints):
    for name, expected in fingerprints.items():
        path = Path(name)
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual != expected:
            raise ValueError('PCB/project/rules changed. Reopen the saved board and rerun before using this result.')


def extract_saved(board_path, *, nets=None, bundles=None, frequency_mhz=100., infer_references=True,
                  max_sections=20000, cancelled=None, progress=None):
    """Load private native geometry; never share the editor's mutable board."""
    import pcbnew
    from .measurement import TraceMeasurementEngine
    from .bulk import extract_board
    fingerprints = source_fingerprints(board_path)
    source = str(Path(board_path).resolve())
    if cancelled is not None and cancelled():
        raise ValueError('Bulk extraction cancelled before board loading.')
    board = load_board(source, pcbnew=pcbnew)
    if board is None:
        raise ValueError('KiCad could not read the saved PCB.')
    verify_sources(fingerprints)
    result = extract_board(TraceMeasurementEngine(board), nets=nets, bundles=bundles,
                          frequency_mhz=frequency_mhz, infer_references=infer_references,
                          max_sections=max_sections, cancelled=cancelled, progress=progress)
    verify_sources(fingerprints)
    assert_current(board)
    document = {'schema': 'wayricad.rlc-bulk-study/v1', 'board_path': source,
                'source_sha256': fingerprints[source], 'source_files': fingerprints,
                'request': {'nets': nets, 'bundles': bundles, 'frequency_mhz': frequency_mhz,
                            'infer_references': infer_references, 'max_sections': max_sections},
                'result': result}
    evidence = provenance(board)
    if evidence is not None:
        document['saved_board_provenance'] = evidence
    return document, board


class BulkController:
    """One cancellable operation; late callbacks cannot revive stale results."""
    def __init__(self):
        self.busy = False; self.closed = False; self.generation = 0
        self.cancel_event = threading.Event()

    def start(self, operation, finished, dispatch, progress=None):
        if self.closed or self.busy:
            raise ValueError('A bulk operation is already running or the workspace is closed.')
        self.busy = True; self.generation += 1
        token = self.generation; self.cancel_event = threading.Event()
        def notify(done, total):
            if progress is not None:
                dispatch(self._progress, token, progress, done, total)
        def worker():
            result = None; error = None
            try:
                result = operation(self.cancel_event.is_set, notify)
            except Exception as exc:
                error = str(exc) or type(exc).__name__
            dispatch(self._deliver, token, finished, result, error)
        self.thread = threading.Thread(target=worker, name='RLC bulk extraction', daemon=True)
        self.thread.start()

    def _progress(self, token, callback, done, total):
        if not self.closed and token == self.generation:
            callback(done, total)

    def _deliver(self, token, callback, result, error):
        if self.closed or token != self.generation:
            return
        self.busy = False
        callback(result, error)

    def cancel(self):
        self.cancel_event.set()

    def close(self):
        self.closed = True; self.generation += 1; self.cancel()


def _value(value):
    return f'{value:.7g}' if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else 'Unknown'


def _plot_geometry(row):
    sections = [section for section in row['sections'] if section.get('start_mm') is not None and section.get('end_mm') is not None]
    points = [point for section in sections for point in (section['start_mm'], section['end_mm'])]
    if not points:
        return []
    left = min(p[0] for p in points); right = max(p[0] for p in points)
    top = min(p[1] for p in points); bottom = max(p[1] for p in points)
    scale = min(850/max(right-left, .5), 270/max(bottom-top, .5))
    return [(section, (25+(section['start_mm'][0]-left)*scale, 25+(section['start_mm'][1]-top)*scale),
             (25+(section['end_mm'][0]-left)*scale, 25+(section['end_mm'][1]-top)*scale),
             max(2., min(18., section.get('width_mm', .15)*scale))) for section in sections]


def _diagram(row, raster=False):
    geometry = _plot_geometry(row)
    if not geometry:
        return '<p>No routed section coordinates; zone-only or unsupported geometry remains unresolved.</p>'
    if raster:
        # reportlab's supported PNG path uses Pillow; no additional runtime is
        # installed by exporting. PNG compression preserves every drawn pixel.
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (900, 320), '#f8fafc'); drawing = ImageDraw.Draw(image)
        for section, a, b, width in geometry:
            colour = '#25855e' if section.get('status') == 'ok' else '#bb8127'
            if section.get('kind') == 'via':
                drawing.ellipse((a[0]-4, a[1]-4, a[0]+4, a[1]+4), outline=colour, width=2)
            else:
                drawing.line((a, b), fill=colour, width=round(width))
        stream = io.BytesIO(); image.save(stream, format='PNG', optimize=True)
        return '<img alt="Saved copper sections; green modeled, amber partial" src="data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')+'">'
    output = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 320" role="img" aria-label="Saved copper sections">']
    for section, a, b, width in geometry:
        colour = '#25855e' if section.get('status') == 'ok' else '#bb8127'
        title = escape(str(section['section_id'])+' · '+str(section.get('layer'))+' · Z0 '+_value(section.get('impedance_ohm'))+' ohm')
        shape = (f'<circle cx="{a[0]:.3f}" cy="{a[1]:.3f}" r="4" fill="none" stroke="{colour}"><title>{title}</title></circle>' if section.get('kind') == 'via' else
                 f'<path d="M{a[0]:.3f},{a[1]:.3f} L{b[0]:.3f},{b[1]:.3f}" stroke="{colour}" stroke-width="{width:.3f}"><title>{title}</title></path>')
        output.append(shape)
    return ''.join(output)+'</svg>'


def report_html(document, *, raster=False):
    from wayricad_runtime.report_ui import enhance_report
    result = document['result']; output = ['<!doctype html><html><head><meta charset="utf-8"><title>RLC all nets and bundles</title></head><body><h1>RLC all nets and bundles</h1>']
    output.append('<p>Source: '+escape(document['board_path'])+'<br>SHA-256: '+escape(document['source_sha256'])+'</p>')
    output.append('<p>Frequency: '+_value(result['frequency_mhz'])+' MHz. Green: supported section model. Amber: partial/unknown. Centreline overview: widths are adjusted for visibility. Geometry uses saved section endpoints; arc coverage is chorded while reported length is exact.</p>')
    output.extend('<p>'+escape(str(notice))+'</p>' for notice in result['limitations'])
    for bundle in result['bundles']:
        output.append('<h2>Bundle: '+escape(bundle['name'])+'</h2><p>'+escape(', '.join(bundle['nets']))+'</p><p>'+escape(bundle['notice'])+'</p>')
    for index, row in enumerate(result['nets']):
        output.append('<h2>Net: '+escape(row.get('display_name', row['net']))+'</h2>')
        memberships = [bundle['name'] for bundle in result['bundles'] if row['net'] in bundle['nets']]
        output.append('<p>Status: '+escape(row['status'])+' · Bundles: '+escape(', '.join(memberships) or 'None')+'<br>Pins: '+escape(', '.join(row['pads']) or 'No named terminals')+'</p>')
        output.append(_diagram(row, raster))
        for section in row['sections']:
            output.append('<h3>Section '+escape(section['section_id'])+' · '+escape(section.get('layer', 'Unknown layer'))+'</h3>')
            metrics = [('length_mm', 'Length', 'mm'), ('resistance_ohm', 'R DC', 'ohm'), ('resistance_ac_ohm', 'R AC', 'ohm'),
                       ('inductance_nh', 'L', 'nH'), ('capacitance_pf', 'C', 'pF'), ('impedance_ohm', 'Z0', 'ohm')]
            output.append('<p>'+escape(' · '.join(label+' '+_value(section.get(key))+' '+unit for key, label, unit in metrics))+'</p>')
            output.append('<p>'+escape('Status: '+section.get('status', 'unknown')+' · Reference: '+str(section.get('reference_net') or 'Unknown')+' / '+str(section.get('reference_layer') or 'Unknown')+' · '+str(section.get('model', 'Model unavailable')))+ '</p>')
            for candidate in section.get('reference_candidates', []):
                output.append('<p>Reference candidate: '+escape(str(candidate['net'])+' / '+candidate['layer']+' / '+candidate['island_id'])+'</p>')
            for blocker in section.get('blockers', []):
                output.append('<p>'+escape(str(blocker.get('code', 'Unknown'))+': '+str(blocker.get('message', '')))+ '</p>')
        for zone in row['zones']:
            output.append('<h3>Zone '+escape(zone['id'])+' · '+escape(zone['layer'])+'</h3><p>'+escape(zone['reason'])+'</p>')
    output.append('<h2>Coverage</h2><pre>'+escape(json.dumps(result['coverage'], indent=2))+'</pre></body></html>')
    return enhance_report(''.join(output), status=result['status'].upper(),
                          summary=[('Nets', str(len(result['nets']))), ('Sections', str(result['coverage']['extracted_sections']))],
                          notice='Per-section estimates; unknown fields and incomplete coverage are not a passing network extraction.')


def export_report(path, document, *, pdf=False):
    from wayricad_runtime.report_ui import publish_documents, report_paths
    from wayricad_runtime.report_context import organize_report
    fingerprints = document['source_files']
    verify_sources(fingerprints)
    output, evidence = report_paths(path)
    html = organize_report(report_html(document, raster=pdf), document)
    documents = {output: html, evidence: json.dumps(document, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n'}
    if pdf:
        from wayricad_runtime.pdf_report import pdf_bytes
        documents[output.with_suffix('.pdf')] = pdf_bytes(html, title='RLC all nets and bundles')
    publish_documents(documents, sources=list(fingerprints), source_guard=lambda: verify_sources(fingerprints))
    return {'html': str(output), 'json': str(evidence), **({'pdf': str(output.with_suffix('.pdf'))} if pdf else {})}


def create_bulk_frame(parent):
    import wx
    from .bulk import available_nets, normalize_bundles
    from .measurement import PathMeasurement
    from .trace_impedance_plugin import RoutePreview
    from .preview_kit import add_zoom_toolbar

    class BulkFrame(wx.Frame):
        def __init__(self):
            super().__init__(parent, title='WayriCAD RLC · All nets / Bundles', size=(1120, 850))
            self.source = Path(parent.board.GetFileName()).resolve()
            self.controller = BulkController(); self.document = None; self.snapshot_board = None
            self._closed = False; self._table_sections = []; self._selected_net = None
            panel = wx.Panel(self); layout = wx.BoxSizer(wx.VERTICAL)
            layout.Add(wx.StaticText(panel, label='Extract saved copper sections across nets and named bundles. No aggregate-net or coupled impedance is inferred.'), 0, wx.EXPAND | wx.ALL, 8)
            settings = wx.BoxSizer(wx.HORIZONTAL)
            self.scope = wx.Choice(panel, choices=['All saved nets', 'Checked nets', 'Bundle members'])
            self.scope.SetSelection(0); settings.Add(self.scope, 0, wx.ALL, 4)
            settings.Add(wx.StaticText(panel, label='Frequency MHz'), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
            self.frequency = wx.TextCtrl(panel, value=parent.frequency.GetValue(), size=(85, -1)); settings.Add(self.frequency, 0, wx.ALL, 4)
            settings.Add(wx.StaticText(panel, label='Section budget'), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
            self.budget = wx.TextCtrl(panel, value='20000', size=(85, -1)); settings.Add(self.budget, 0, wx.ALL, 4)
            self.infer = wx.CheckBox(panel, label='Infer reference planes from filled copper'); self.infer.SetValue(True); settings.Add(self.infer, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
            self.run = wx.Button(panel, label='Extract sections'); self.run.Bind(wx.EVT_BUTTON, self.on_run); settings.Add(self.run, 0, wx.ALL, 4)
            self.cancel = wx.Button(panel, label='Cancel'); self.cancel.Disable(); self.cancel.Bind(wx.EVT_BUTTON, self.on_cancel); settings.Add(self.cancel, 0, wx.ALL, 4)
            layout.Add(settings, 0, wx.EXPAND)
            top = wx.BoxSizer(wx.HORIZONTAL)
            self.available = available_nets(parent.engine)
            self.nets = wx.CheckListBox(panel, choices=[net or '(unassigned copper)' for net in self.available], size=(280, 110)); top.Add(self.nets, 1, wx.EXPAND | wx.ALL, 4)
            bundle_box = wx.BoxSizer(wx.VERTICAL)
            self.bundles = wx.TextCtrl(panel, value='{"schema":"wayricad.rlc-bundles/v1","bundles":[]}', style=wx.TE_MULTILINE, size=(500, 90)); bundle_box.Add(self.bundles, 1, wx.EXPAND)
            row = wx.BoxSizer(wx.HORIZONTAL)
            self.bundle_buttons = []
            for label, handler in [('Load bundles…', self.load_bundles), ('Save bundles…', self.save_bundles)]:
                button = wx.Button(panel, label=label); button.Bind(wx.EVT_BUTTON, handler); row.Add(button, 0, wx.RIGHT, 5); self.bundle_buttons.append(button)
            bundle_box.Add(row, 0, wx.TOP, 4); top.Add(bundle_box, 2, wx.EXPAND | wx.ALL, 4); layout.Add(top, 0, wx.EXPAND)
            self.summary = wx.StaticText(panel, label='Choose all nets, checked nets or explicit bundle members, then extract.'); layout.Add(self.summary, 0, wx.EXPAND | wx.ALL, 8)
            splitter = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
            self.net_results = wx.ListCtrl(splitter, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            for col, (name, width) in enumerate([('Net / full path', 230), ('Status', 100), ('Sections', 70)]): self.net_results.InsertColumn(col, name, width=width)
            self.net_results.Bind(wx.EVT_LIST_ITEM_SELECTED, self.net_selected)
            right = wx.Panel(splitter); right_layout = wx.BoxSizer(wx.VERTICAL)
            self.preview = RoutePreview(right); self.preview.SetMinSize((-1, 200)); self.preview.on_pick = self.preview_selected
            right_layout.Add(self.preview, 2, wx.EXPAND | wx.ALL, 4); add_zoom_toolbar(right, self.preview, right_layout)
            self.sections = wx.ListCtrl(right, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            for col, (name, width) in enumerate([('Section / UUID', 210), ('Layer', 80), ('Reference net / layer', 210), ('Status', 80), ('R DC Ω', 85), ('L nH', 85), ('C pF', 85), ('Z0 Ω', 85)]): self.sections.InsertColumn(col, name, width=width)
            self.sections.Bind(wx.EVT_LIST_ITEM_SELECTED, self.section_selected)
            self.sections.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.cross_probe)
            right_layout.Add(self.sections, 1, wx.EXPAND | wx.ALL, 4); right.SetSizer(right_layout)
            splitter.SplitVertically(self.net_results, right, 340); splitter.SetMinimumPaneSize(160); layout.Add(splitter, 1, wx.EXPAND | wx.ALL, 4)
            self.details = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 95)); layout.Add(self.details, 0, wx.EXPAND | wx.ALL, 4)
            buttons = wx.BoxSizer(wx.HORIZONTAL)
            self.cross = wx.Button(panel, label='Select section in PCB'); self.cross.Bind(wx.EVT_BUTTON, self.cross_probe); buttons.Add(self.cross, 0, wx.ALL, 4)
            self.exports = []
            for label, pdf in [('Export HTML…', False), ('Export PDF…', True)]:
                button = wx.Button(panel, label=label); button.Bind(wx.EVT_BUTTON, lambda e, pdf=pdf: self.on_export(pdf)); buttons.Add(button, 0, wx.ALL, 4); self.exports.append(button)
            layout.Add(buttons, 0, wx.ALIGN_RIGHT); panel.SetSizer(layout)
            for control, event in [(self.scope, wx.EVT_CHOICE), (self.frequency, wx.EVT_TEXT), (self.budget, wx.EVT_TEXT), (self.infer, wx.EVT_CHECKBOX), (self.nets, wx.EVT_CHECKLISTBOX), (self.bundles, wx.EVT_TEXT)]: control.Bind(event, self.invalidate)
            self.Bind(wx.EVT_CLOSE, self.on_close); self._buttons()
            self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
            self.source_timer = wx.Timer(self); self.Bind(wx.EVT_TIMER, self.check_source, self.source_timer); self.source_timer.Start(1500)
            work = wx.Display(max(0, wx.Display.GetFromWindow(parent))).GetClientArea()
            self.SetSize(min(self.GetSize().width, work.width-20), min(self.GetSize().height, work.height-40)); self.CentreOnParent()

        def _buttons(self):
            busy = self.controller.busy
            for control in (self.scope, self.frequency, self.budget, self.infer, self.nets, self.bundles): control.Enable(not busy)
            for button in self.bundle_buttons: button.Enable(not busy)
            self.run.Enable(not busy); self.cancel.Enable(busy)
            self.cross.Enable(bool(self.document) and not busy)
            for button in self.exports: button.Enable(bool(self.document) and not busy)

        def invalidate(self, _event=None):
            self.document = None; self.snapshot_board = None; self.net_results.DeleteAllItems(); self.sections.DeleteAllItems(); self._table_sections = []
            self.preview.show_measurement(None); self.details.Clear(); self.summary.SetLabel('Settings changed. Extract again before using results.'); self._buttons()

        def _bundle_definition(self):
            document = json.loads(self.bundles.GetValue())
            normalize_bundles(document, available_nets(parent.engine))
            return document

        def on_run(self, _event=None):
            try:
                scope = self.scope.GetSelection(); bundles = self._bundle_definition() if scope == 2 else None
                nets = None if scope == 0 else [self.available[i] for i in self.nets.GetCheckedItems()] if scope == 1 else []
                if scope == 1 and not nets: raise ValueError('Check at least one net.')
                if scope == 2 and not bundles['bundles']: raise ValueError('Add or load a bundle with exact net names.')
                frequency = float(self.frequency.GetValue())
                budget = int(self.budget.GetValue())
                infer = self.infer.GetValue()
                self.invalidate()
                self.controller.start(lambda cancel, progress: extract_saved(self.source, nets=nets, bundles=bundles,
                    frequency_mhz=frequency, infer_references=infer, max_sections=budget, cancelled=cancel, progress=progress), self.finished,
                    wx.CallAfter, lambda done, total: self.summary.SetLabel(f'Extracted {done} / {total} copper items…'))
                self.summary.SetLabel('Reading the saved board and extracting supported sections…'); self._buttons()
            except Exception as exc: wx.MessageBox(str(exc), 'Bulk extraction', wx.OK | wx.ICON_INFORMATION, self)

        def on_cancel(self, _event=None):
            self.controller.cancel(); self.summary.SetLabel('Cancellation requested; waiting for the current native read/section to finish.')

        def finished(self, value, error):
            if error:
                self.summary.SetLabel(error); self._buttons(); return
            self.document, self.snapshot_board = value
            try:
                verify_sources(self.document['source_files'])
                assert_current(self.snapshot_board)
            except Exception as exc:
                self.invalidate(); self.summary.SetLabel(str(exc)); return
            self.source_stat = self._stat_sources()
            result = self.document['result']; coverage = result['coverage']
            self.summary.SetLabel(f"{result['status']} · {coverage['selected_nets']} nets · {coverage['extracted_sections']} sections · {coverage['completed_items']}/{coverage['physical_items']} items. Per-section estimates; unresolved fields remain unknown.")
            for row in result['nets']:
                index = self.net_results.InsertItem(self.net_results.GetItemCount(), row.get('display_name', row['net']))
                self.net_results.SetItem(index, 1, row['status']); self.net_results.SetItem(index, 2, str(len(row['sections'])))
            self._buttons()
            if result['nets']: self.net_results.Select(0)

        def _stat_sources(self):
            result = {}
            for name in self.document['source_files']:
                try:
                    stat = Path(name).stat(); result[name] = (stat.st_size, stat.st_mtime_ns)
                except OSError: result[name] = None
            return result

        def check_source(self, _event=None):
            if self.document and not self.controller.busy and self._stat_sources() != self.source_stat:
                self.invalidate(); self.summary.SetLabel('Saved PCB/project/rules changed. Reopen the board and extract again.')

        def net_selected(self, event):
            if not self.document: return
            row = self.document['result']['nets'][event.GetIndex()]; self._selected_net = row['net']; self._table_sections = row['sections']
            self.sections.DeleteAllItems()
            for section in self._table_sections:
                index = self.sections.InsertItem(self.sections.GetItemCount(), section['section_id'])
                for col, value in enumerate([section.get('layer', ''), (section.get('reference_net') or 'Unknown')+' / '+(section.get('reference_layer') or 'Unknown'), section.get('status', 'unknown'), *[_value(section.get(key)) for key in ('resistance_ohm', 'inductance_nh', 'capacitance_pf', 'impedance_ohm')]], 1): self.sections.SetItem(index, col, str(value))
            uuids = {section['item_uuid'] for section in row['sections']}
            items = [item for item in self.snapshot_board.GetTracks() if str(item.m_Uuid.AsString()) in uuids]
            items += [zone for zone in self.snapshot_board.Zones() if str(zone.GetNetname()) == row['net']]
            measurement = PathMeasurement(net_name=row['net'], start_pad='', end_pad='', board_items=items, segments=row['sections'])
            self.preview.board = self.snapshot_board; self.preview.show_measurement(measurement); self.preview.set_colour_mode(3)
            self.details.SetValue('Net: '+row['net']+'\nPins: '+(', '.join(row['pads']) or 'No named terminals')+'\n'+ '\n'.join(zone['layer']+': '+zone['reason'] for zone in row['zones']))

        def section_selected(self, event):
            index = event.GetIndex()
            if not self.document or index >= len(self._table_sections): return
            section = self._table_sections[index]; self.preview.selected_uuid = section['item_uuid']; self.preview.Refresh()
            self.details.SetValue(json.dumps(section, ensure_ascii=False, indent=2))

        def preview_selected(self, data):
            if not isinstance(data, tuple) or data[0] != 'section': return
            index = next((i for i, section in enumerate(self._table_sections) if section['item_uuid'] == data[1]), None)
            if index is not None: self.sections.Select(index); self.sections.EnsureVisible(index)

        def cross_probe(self, _event=None):
            index = self.sections.GetFirstSelected()
            if not self.document or index < 0: return
            section = self._table_sections[index]; document = self.document
            def select(cancel, progress):
                from wayricad_runtime.analysis_selection import select_origin
                verify_sources(document['source_files'])
                return select_origin(document['board_path'], [section['item_uuid']], expected_sha256=document['source_sha256'], focus=True, return_details=True)
            self.controller.start(select, lambda value, error: (self.summary.SetLabel(error or f"Selected {value['count']} item(s) in the originating PCB Editor."), self._buttons()), wx.CallAfter)
            self._buttons()
            self.cancel.Disable()

        def load_bundles(self, _event=None):
            if self.controller.busy: return
            with wx.FileDialog(self, 'Load RLC bundles', defaultDir=str(self.source.parent), wildcard='JSON (*.json)|*.json', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as picker:
                if picker.ShowModal() != wx.ID_OK: return
                try:
                    document = json.loads(Path(picker.GetPath()).read_text(encoding='utf-8')); normalize_bundles(document, available_nets(parent.engine))
                    self.bundles.SetValue(json.dumps(document, ensure_ascii=False, indent=2))
                except Exception as exc: wx.MessageBox(str(exc), 'Could not load bundles', wx.OK | wx.ICON_ERROR, self)

        def save_bundles(self, _event=None):
            if self.controller.busy: return
            try: document = self._bundle_definition()
            except Exception as exc: wx.MessageBox(str(exc), 'Could not save bundles', wx.OK | wx.ICON_ERROR, self); return
            with wx.FileDialog(self, 'Save RLC bundles', defaultDir=str(self.source.parent), defaultFile=self.source.stem+'-bundles.json', wildcard='JSON (*.json)|*.json', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as picker:
                if picker.ShowModal() == wx.ID_OK:
                    from .cli import write_report
                    try: write_report(Path(picker.GetPath()), document, self.source)
                    except Exception as exc: wx.MessageBox(str(exc), 'Could not save bundles', wx.OK | wx.ICON_ERROR, self)

        def on_export(self, pdf):
            if not self.document or self.controller.busy: return
            extension = 'pdf' if pdf else 'html'
            with wx.FileDialog(self, 'Export bulk RLC report', defaultDir=str(self.source.parent), defaultFile=self.source.stem+'-rlc-bulk.'+extension,
                               wildcard=extension.upper()+' (*.'+extension+')|*.'+extension, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as picker:
                if picker.ShowModal() != wx.ID_OK: return
                destination = picker.GetPath(); document = deepcopy(self.document)
            self.controller.start(lambda cancel, progress: export_report(destination, document, pdf=pdf),
                lambda value, error: (self.summary.SetLabel(error or 'Exported '+', '.join(value.values())), self._buttons()), wx.CallAfter)
            self._buttons()
            self.cancel.Disable()

        def on_close(self, event):
            self._closed = True; self.source_timer.Stop(); self.controller.close(); event.Skip()

        def on_destroy(self, event):
            if event.GetEventObject() is self:
                self._closed = True; self.source_timer.Stop(); self.controller.close()
            event.Skip()

    return BulkFrame()
