"""Owned routing snapshots and cancellable isolated native preview processes.

Native serialization must run on its owning GUI thread. IPC serialization uses
a new originating-editor connection in the broker thread. Planning never reads
the live native board and never writes source or project files.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _companions(source, destination):
    hashes = {}
    for suffix in ('.kicad_pro', '.kicad_dru'):
        path = source.with_suffix(suffix)
        data = path.read_bytes() if path.is_file() else None
        hashes[suffix] = _hash(data) if data is not None else None
        if data is not None:
            destination.with_suffix(suffix).write_bytes(data)
    return hashes


def _selected(board):
    from wayricad_runtime.geometry import item_id
    result = {'footprints': [], 'pads': []}
    if hasattr(board, 'raw'):
        for item in board.GetSelection():
            if item.GetClass()=='FOOTPRINT':result['footprints'].append(item_id(item))
            elif item.GetClass()=='PAD':result['pads'].append(item_id(item))
        return result
    for fp in board.GetFootprints():
        if fp.IsSelected():result['footprints'].append(item_id(fp))
        result['pads'].extend(item_id(pad) for pad in fp.Pads() if pad.IsSelected())
    return result


def _effective_rules(board):
    """Require inspectable live effective dimensions instead of assuming saved rules."""
    values = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            net = str(pad.GetNetname())
            if not net or net in values:continue
            getter = getattr(pad, 'GetEffectiveNetClass', None)
            if getter is None:
                raise ValueError('This connection cannot verify live effective netclass dimensions. Save the project and use explicit reviewed dimensions, or use a native saved-board window.')
            rule = getter()
            values[net] = [int(getattr(rule, name)()) for name in ('GetTrackWidth', 'GetClearance', 'GetViaDiameter', 'GetViaDrill')]
    return values


def _capture_native(board, api, directory, selection, use_rules):
    source = Path(board.GetFileName()).resolve() if board.GetFileName() else None
    target = directory / 'snapshot.kicad_pcb'
    original = board.GetFileName()
    try:
        if not api.SaveBoard(str(target), board, True):
            raise ValueError('KiCad could not serialize the owned preview snapshot.')
    finally:
        if board.GetFileName() != original:
            board.SetFileName(original)
    data = target.read_bytes()
    return {'source': str(source) if source else '', 'snapshot_sha256': _hash(data),
            'mode': 'live-native',
            'companions': _companions(source, target) if source else {},
            'selection': selection if selection is not None else _selected(board),
            'effective_rules': _effective_rules(board) if use_rules else None}


def capture_identity(board, api, *, use_netclass_rules=False, selection=None):
    """Capture a fresh write-boundary identity; native serialization is synchronous."""
    with tempfile.TemporaryDirectory(prefix='wayricad-routing-check-') as temporary:
        directory = Path(temporary)
        if hasattr(board, 'raw'):
            raw = board.raw
            source = Path(board.GetFileName()).resolve()
            data = raw.get_as_string().encode('utf-8')
            target = directory / 'snapshot.kicad_pcb';target.write_bytes(data)
            if use_netclass_rules:
                _effective_rules(board)  # Explicitly rejects unavailable live dimension inspection.
            return {'source': str(source), 'snapshot_sha256': _hash(data),
                    'companions': _companions(source, target), 'selection': selection,
                    'effective_rules': None}
        return _capture_native(board, api, directory, selection, use_netclass_rules)


def assert_current(board, api, identity, *, selection=None, current_fingerprint=None):
    if identity.get('selection_scope') in {'Selected pads', 'Selected footprints'}:
        current_selection=selection if selection is not None else _selected(board)
        expected=identity.get('selection') or {}
        if any(sorted(current_selection.get(key,[]))!=sorted(expected.get(key,[])) for key in ('footprints','pads')):
            raise ValueError('PCB selection changed. Create a fresh preview before applying.')
    if identity.get('mode') == 'saved':
        from wayricad_runtime.geometry import board_fingerprint
        source = Path(board.GetFileName()).resolve()
        fingerprint = current_fingerprint if current_fingerprint is not None else board_fingerprint(board)
        if str(source) != identity.get('source') or fingerprint != identity.get('source_fingerprint'):
            raise ValueError('Board changed. Create a fresh preview before applying.')
        for suffix, expected in identity.get('companions', {}).items():
            path = source.with_suffix(suffix)
            actual = _hash(path.read_bytes()) if path.is_file() else None
            if actual != expected:raise ValueError('Project rules changed. Create a fresh preview before applying.')
        if identity.get('effective_rules') is not None and _effective_rules(board) != identity['effective_rules']:
            raise ValueError('Live netclass dimensions changed. Create a fresh preview before applying.')
        return
    current = capture_identity(board, api, use_netclass_rules=identity.get('effective_rules') is not None,
                               selection=selection)
    for key in ('source', 'snapshot_sha256', 'companions', 'effective_rules'):
        if current.get(key) != identity.get(key):
            raise ValueError('Board or project rules changed. Create a fresh preview before applying.')
    if selection is not None and identity.get('selection') != selection:
        raise ValueError('PCB selection changed. Create a fresh preview before applying.')


class RoutingJob:
    """One snapshot, one worker and one bounded result; no wx calls in the broker."""
    def __init__(self, board, api, settings, *, kind, include_context, selection, timeout, snapshot_mode):
        if kind not in {'fanout', 'stitching', 'identity'}:raise ValueError('Unknown routing worker kind.')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1<=timeout<=300:
            raise ValueError('Preview timeout must be between 1 and 300 seconds.')
        self._directory = Path(tempfile.mkdtemp(prefix='wayricad-routing-preview-'))
        self._cancel = threading.Event();self._process = None;self._result = None;self._error = None
        self.started = time.monotonic();self.identity = None;self.kind = kind
        self.capture_seconds = 0.;self._closed = False
        self.settings = dict(settings);self.include_context = bool(include_context);self.timeout = float(timeout)
        self._source = str(Path(board.GetFileName()).resolve()) if board.GetFileName() else ''
        self._selection = selection
        self._native_identity = None
        self._saved = False
        self._live_rules = None
        self._origin_facade = None
        if hasattr(board, 'raw') and selection is None:
            from wayricad_runtime.geometry import item_id
            self._selection = {'footprints': [], 'pads': []}
            for item in board.GetSelection():
                kind_name = item.GetClass()
                if kind_name == 'FOOTPRINT':self._selection['footprints'].append(item_id(item))
                elif kind_name == 'PAD':self._selection['pads'].append(item_id(item))
        if not hasattr(board, 'raw'):
            if selection is None:self._selection = _selected(board)
            saved = bool(self._source and Path(self._source).is_file())
            if snapshot_mode not in {'auto', 'saved', 'live'}:raise ValueError('Choose saved or live snapshot mode.')
            modified = bool(getattr(board, 'IsModified', lambda: False)())
            if snapshot_mode == 'saved' or (snapshot_mode == 'auto' and saved):
                if not saved or modified:
                    raise ValueError('Save PCB changes before fast preview, or explicitly choose Live snapshot (slower).')
                self._saved = True
                if settings.get('use_netclass_rules'):self._live_rules = _effective_rules(board)
            else:
                start = time.monotonic()
                self._native_identity = _capture_native(board, api, self._directory, self._selection, bool(settings.get('use_netclass_rules')))
                self.capture_seconds = time.monotonic() - start
        self._thread = threading.Thread(target=self._work, name='WayriCAD isolated routing preview', daemon=False)
        self._thread.start()

    @property
    def elapsed(self):return time.monotonic() - self.started

    def done(self):return not self._thread.is_alive()

    def cancel(self):self._cancel.set()

    def result(self):
        if not self.done():raise RuntimeError('Preview is still running.')
        if self._error:raise self._error
        return self._result

    def close(self):
        self._closed = True;self.cancel()
        if self.done():shutil.rmtree(self._directory, ignore_errors=True)

    def _capture_ipc(self):
        from wayricad_runtime.context import connect, saved_board
        client = connect();raw = client.get_board()
        if str(saved_board(client).resolve()) != self._source:
            raise ValueError('The originating PCB Editor changed boards. Reopen this tool.')
        from kipy import board_types
        from wayricad_runtime.ipc import Board
        from wayricad_runtime.geometry import board_fingerprint
        facade = Board(raw, board_types)
        self._origin_facade = facade
        before = board_fingerprint(facade)
        data = raw.get_as_string().encode('utf-8')
        target = self._directory / 'snapshot.kicad_pcb';target.write_bytes(data)
        if self.settings.get('use_netclass_rules'):
            raise ValueError('Live IPC netclass dimensions cannot yet be verified against the snapshot. Use explicit reviewed dimensions or a native saved-board workflow.')
        if board_fingerprint(facade) != before:
            raise ValueError('The originating board changed while capturing the snapshot; retry.')
        return {'source': self._source, 'snapshot_sha256': _hash(data), 'source_fingerprint': before, 'mode': 'live-ipc',
                'companions': _companions(Path(self._source), target),
                'selection': self._selection or {'footprints': [], 'pads': []}, 'effective_rules': None}

    def _work(self):
        try:
            from wayricad_runtime.runtime_setup import ensure_runtime
            from wayricad_runtime.jobs import terminate
            if self._saved:
                source = Path(self._source);target = self._directory / 'snapshot.kicad_pcb'
                data = source.read_bytes();target.write_bytes(data)
                self.identity = {'source': self._source, 'snapshot_sha256': _hash(data),
                    'companions': _companions(source, target), 'selection': self._selection,
                    'effective_rules': self._live_rules, 'mode': 'saved'}
            else:
                self.identity = self._native_identity or self._capture_ipc()
            self.identity['selection_scope']=self.settings.get('scope')
            if self._cancel.is_set():raise ValueError('Preview cancelled.')
            request = {'kind': self.kind, 'board': str(self._directory / 'snapshot.kicad_pcb'),
                       'settings': self.settings, 'context': self.include_context, 'identity': self.identity}
            input_path = self._directory / 'request.json';output_path = self._directory / 'result.json'
            input_path.write_text(json.dumps(request), encoding='utf-8')
            executable = ensure_runtime({}, timeout=min(60, self.timeout))
            if self._cancel.is_set() or self.elapsed > self.timeout:
                raise ValueError('Preview cancelled.' if self._cancel.is_set() else 'Preview time limit reached before worker launch.')
            command = [str(executable), '-I', str(Path(__file__).resolve()), '--worker', str(input_path), str(output_path)]
            with (self._directory / 'worker.log').open('wb') as log:
                self._process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
                    start_new_session=os.name != 'nt')
                while self._process.poll() is None:
                    if (self._directory / 'worker.log').stat().st_size > 8 * 1024 * 1024:
                        terminate(self._process);raise ValueError('Preview exceeded its worker log budget.')
                    if self._cancel.wait(.05) or self.elapsed > self.timeout:
                        terminate(self._process)
                        raise ValueError('Preview cancelled.' if self._cancel.is_set() else 'Preview time limit reached; narrow the component/pin scope and retry.')
                if (self._directory / 'worker.log').stat().st_size > 8 * 1024 * 1024:
                    raise ValueError('Preview exceeded its worker log budget.')
                if not output_path.is_file():
                    raise ValueError('The native preview worker did not return a result. Check the KiCad runtime.')
                if output_path.stat().st_size > 256 * 1024 * 1024:raise ValueError('Preview exceeded its result budget; narrow the scope.')
                self._result = json.loads(output_path.read_text(encoding='utf-8'))
                if self._result.get('error'):raise ValueError(self._result['error'])
                if self._process.returncode:raise ValueError('The native preview worker failed.')
                self.identity = self._result.get('identity', self.identity)
                if self._origin_facade is not None:
                    from wayricad_runtime.geometry import board_fingerprint
                    if board_fingerprint(self._origin_facade) != self.identity['source_fingerprint']:
                        raise ValueError('The originating board changed while planning. Create a fresh preview.')
                elif self._saved and _hash(Path(self._source).read_bytes()) != self.identity['snapshot_sha256']:
                    raise ValueError('The saved board changed while planning. Create a fresh preview.')
        except Exception as exc:
            self._error = exc
        finally:
            if self._process is not None:
                if self._process.poll() is None:
                    from wayricad_runtime.jobs import terminate
                    terminate(self._process)
                self._process.wait()
            if self._closed:shutil.rmtree(self._directory, ignore_errors=True)


def start_job(board, api, settings, *, kind='fanout', include_context=True, selection=None, timeout=60, snapshot_mode='auto'):
    job = RoutingJob.__new__(RoutingJob)
    try:
        job.__init__(board, api, settings, kind=kind, include_context=include_context,
                     selection=selection, timeout=timeout, snapshot_mode=snapshot_mode)
        return job
    except Exception:
        if hasattr(job, '_directory'):shutil.rmtree(job._directory, ignore_errors=True)
        raise


def _board_context(board, api):
    from types import SimpleNamespace
    from wayricad_runtime.preview import GeometryPreview
    context = SimpleNamespace(set_highlight=lambda *a, **k: None,
                              invalidate_scene=lambda *a, **k: None, Refresh=lambda *a, **k: None)
    GeometryPreview.set_board(context, board, api)
    names = ('context_lines', 'context_pads', 'context_rings', 'context_vias', 'footprint_lines',
             'references', 'focus_points', 'net_targets', '_context_identity')
    return {name: getattr(context, name) for name in names}


def _worker(request):
    import pcbnew as api
    from wayricad_runtime.routing import plan_fanout, plan_stitching, routing_rules_fingerprint
    from wayricad_runtime.geometry import item_id
    from wayricad_runtime.geometry import board_fingerprint
    board = api.LoadBoard(request['board'])
    if board is None:raise ValueError('KiCad could not load the owned snapshot.')
    identity = request['identity'];selection = identity.get('selection') or {}
    if not identity.get('source_fingerprint'):identity['source_fingerprint'] = board_fingerprint(board)
    for fp in board.GetFootprints():
        if item_id(fp) in selection.get('footprints', []):fp.SetSelected()
        for pad in fp.Pads():
            if item_id(pad) in selection.get('pads', []):pad.SetSelected()
    if identity.get('effective_rules') is not None and _effective_rules(board) != identity['effective_rules']:
        raise ValueError('Live effective netclass dimensions differ from saved project rules. Save the project and create a fresh preview.')
    result = {'identity': identity, 'snapshot_sha256': identity['snapshot_sha256'],
              'source_fingerprint': identity['source_fingerprint'],
              'rules_fingerprint': routing_rules_fingerprint(board)}
    if request['kind'] == 'fanout':
        plans, rejected = plan_fanout(board, api, request['settings'])
        records = []
        for plan in plans:
            row = {key: value for key, value in vars(plan).items() if key not in {'footprint', 'pad', 'start', 'end', 'path', 'connector_region'}}
            row.update(footprint_uuid=item_id(plan.footprint), pad_uuid=item_id(plan.pad),
                       layer_name=str(board.GetLayerName(plan.layer)),
                       start=[int(plan.start.x), int(plan.start.y)], end=[int(plan.end.x), int(plan.end.y)],
                       path=[[int(point.x), int(point.y)] for point in plan.path],
                       connector_region=[[int(point.x), int(point.y)] for point in plan.connector_region])
            records.append(row)
        result.update(candidates=records, rejected=rejected)
    elif request['kind'] == 'stitching':
        vias, rejected = plan_stitching(board, api, request['settings'])
        result.update(candidates=[dict(x=int(v.GetPosition().x), y=int(v.GetPosition().y),
            diameter=int(v.GetWidth(api.F_Cu)), drill=int(v.GetDrillValue()), net=str(v.GetNetname())) for v in vias], rejected=rejected)
    if request.get('context'):result['context'] = _board_context(board, api)
    return result


def main():
    source, destination = map(Path, sys.argv[2:4])
    try:
        request = json.loads(source.read_text(encoding='utf-8'));result = _worker(request)
    except Exception as exc:
        destination.write_text(json.dumps({'error': str(exc)}), encoding='utf-8');return 2
    destination.write_text(json.dumps(result, allow_nan=False), encoding='utf-8');return 0


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
