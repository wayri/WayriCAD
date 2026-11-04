"""Saved-board Quick SI jobs, isolated from wx and live SWIG objects."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
import re
from wayricad_runtime.saved_board import assert_current, load_board, provenance


def source_fingerprints(board_path):
    """Hash saved geometry, project rules and custom rules, including absence."""
    path=Path(board_path).resolve()
    if path.suffix.lower()!='.kicad_pcb' or not path.is_file():raise ValueError('Choose a saved KiCad PCB.')
    return {str(item):hashlib.sha256(item.read_bytes()).hexdigest() if item.is_file() else None
            for item in (path,path.with_suffix('.kicad_pro'),path.with_suffix('.kicad_dru'))}


def require_source(request):
    current=source_fingerprints(request['board_path'])
    if not request.get('source_fingerprints') or current!=request['source_fingerprints']:
        raise ValueError('The saved PCB or project rules changed. Reopen Quick SI and rerun.')
    return current


def bind_saved_result(report, board_path, fingerprints, *, board=None):
    """Attach the worker's original saved-PCB evidence without computing a new hash."""
    path = Path(board_path).resolve()
    expected = fingerprints.get(str(path)) if isinstance(fingerprints, dict) else None
    if path.suffix.lower() != '.kicad_pcb' or not isinstance(expected, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', expected):
        raise ValueError('Quick SI results need the original saved-PCB fingerprint.')
    declared = report.get('source_sha256')
    if declared is not None and declared != expected:
        raise ValueError('Quick SI result belongs to a different saved PCB snapshot.')
    declared_path = report.get('source_path')
    if declared_path:
        other = Path(declared_path)
        if (other if other.is_absolute() else path.parent / other).resolve() != path:
            raise ValueError('Quick SI result declares a different source board.')
    result = dict(report, source_path=str(path), source_sha256=expected,
                  source_fingerprints=dict(fingerprints))
    evidence = provenance(board)
    if evidence is not None:
        result['saved_board_provenance'] = evidence
    return result


def execute(request):
    """Load and analyze one saved snapshot inside the owned worker process."""
    before=require_source(request)
    import pcbnew
    board=load_board(str(Path(request['board_path']).resolve()), pcbnew=pcbnew)
    if board is None:raise ValueError('KiCad could not load this saved PCB.')
    def guard():
        require_source(request)
        assert_current(board)
    if request.get('mode')=='neighbours':
        from .neighbours import map_board
        report=map_board(board,request.get('settings'),guard=guard)
        guard()
        report=bind_saved_result(report,request['board_path'],before,board=board)
        return {'neighbours':report,'source_fingerprints':before}
    if request.get('mode')=='study':
        from .study import run_study
        report=run_study(board,request['study'],guard=guard)
        guard()
        report=bind_saved_result(report,request['board_path'],before,board=board)
        return {'study':report,'source_fingerprints':before}
    from .quick_si import analyze
    report,path=analyze(board,request['net'],request['start'],request['end'],request.get('reference','Auto'),**request.get('inputs',{}))
    guard()
    identifiers=[str(item.m_Uuid.AsString()) for item in path.board_items]
    report=bind_saved_result(report,request['board_path'],before,board=board)
    report['board_item_ids']=identifiers
    report['endpoint_bindings']={'net_name':request['net'],'source':request['start'],'sink':request['end']}
    return {'report':report,'path_data':{key:value for key,value in vars(path).items() if key!='board_items'},
            'board_item_ids':identifiers,'source_fingerprints':before}


def restore_path(payload,board):
    """Reattach UUIDs only on the UI thread to its original local board."""
    assert_current(board)
    from dataclasses import fields
    from .measurement import PathMeasurement
    names={field.name for field in fields(PathMeasurement)}-{'board_items'}
    data=payload['path_data']
    if set(data)-names:raise ValueError('Quick SI worker returned unknown path fields.')
    path=PathMeasurement(**data)
    index={}
    for item in [*board.GetTracks(),*board.Zones()]:
        identifier=str(item.m_Uuid.AsString())
        if identifier in index:raise ValueError('The local preview has duplicate item UUIDs. Reopen Quick SI.')
        index[identifier]=item
    ids=payload.get('board_item_ids',[])
    if len(set(ids))!=len(ids) or any(identifier not in index for identifier in ids):
        raise ValueError('The local preview no longer matches this saved result. Reopen Quick SI.')
    path.board_items=[index[identifier] for identifier in ids]
    return path


def run_job(request,cancelled=None,timeout=300,python=None):
    """Wait for one cancellable child; no board or wx objects cross threads."""
    if not math.isfinite(float(timeout)) or float(timeout)<=0:raise ValueError('Worker timeout must be finite and positive.')
    if cancelled and cancelled():raise InterruptedError('Quick SI cancelled before starting.')
    if python is None:
        if request.get('mode')=='neighbours':
            # Geometry and the local ideal-coupling model use native KiCad and
            # the standard library. Do not import/provision plotting or IPC
            # dependencies for every read-only neighbour-map request.
            from wayricad_runtime.runtime_setup import ensure_runtime
            python=ensure_runtime({})
        else:
            from wayricad_runtime.native_analysis import native_python
            python=native_python('signal_integrity_advisor_plugin')
    if cancelled and cancelled():raise InterruptedError('Quick SI cancelled before starting.')
    from wayricad_runtime.runtime_setup import child_environment
    from wayricad_runtime.analysis_process import worker_options, stop_worker
    with tempfile.TemporaryDirectory(prefix='wayricad-quick-si-') as directory:
        root=Path(directory);source=root/'request.json';target=root/'response.json'
        source.write_text(json.dumps(request,allow_nan=False),encoding='utf-8')
        environment = child_environment()
        environment['WAYRICAD_ANALYSIS_SCRATCH'] = str(root)
        with (root/'worker.log').open('w+',encoding='utf-8') as log:
            process=subprocess.Popen([str(python),'-I',str(Path(__file__).with_name('worker.py')),str(source),str(target)],
                env=environment,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                **worker_options())
            started=time.monotonic()
            try:
                while process.poll() is None:
                    if cancelled and cancelled():raise InterruptedError('Quick SI cancelled. No board files were changed.')
                    if time.monotonic()-started>timeout:raise TimeoutError('Quick SI exceeded its time budget. Reduce the eye workload or review a smaller route.')
                    time.sleep(.1)
            finally:
                if process.poll() is None:
                    stop_worker(process)
            log.seek(0);details=log.read()[-2000:]
            if not target.is_file():raise RuntimeError('Quick SI worker produced no result. '+details)
            try:result=json.loads(target.read_text(encoding='utf-8'))
            except (OSError,ValueError) as error:raise RuntimeError('Quick SI worker returned an invalid result. '+details) from error
            if not isinstance(result,dict):raise RuntimeError('Quick SI worker returned an invalid result object.')
            if result.get('error'):raise ValueError(result['error'])
            if process.returncode:raise RuntimeError('Quick SI worker failed. '+details)
            require_source(request)
            if result.get('source_fingerprints')!=request['source_fingerprints']:raise ValueError('Quick SI worker analyzed a different source snapshot.')
            return result
