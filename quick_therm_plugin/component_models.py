"""Read-only STEP placement and bounded tessellation for QuickTherm.

KiCad owns model placement; FreeCAD reads the exported solids. The private
PRODUCT identity technique follows WayriCAD Mechanical Check's extractor.
Geometry supplies display surfaces, never thermal material properties.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def discover():
    cli = os.environ.get('WAYRICAD_THERM_KICAD_CLI') or shutil.which('kicad-cli')
    native = os.environ.get('WAYRICAD_THERM_KICAD_PYTHON')
    cad = os.environ.get('WAYRICAD_THERM_FREECAD_PYTHON')
    if os.name == 'nt':
        roots = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')),
                 Path(os.environ.get('LOCALAPPDATA', ''), 'Programs'),
                 Path.home()/'AppData/Local/Programs']
        candidates = [p for root in roots for p in root.glob('KiCad/10.*/bin/kicad-cli.exe')]
        if not cli and candidates:
            cli = str(sorted(candidates, reverse=True)[0])
        if cli and not native and Path(cli).with_name('python.exe').is_file():
            native = str(Path(cli).with_name('python.exe'))
        candidates = [p for root in roots for p in root.glob('FreeCAD*/bin/python.exe')]
        if not cad and candidates:
            cad = str(sorted(candidates, reverse=True)[0])
    else:
        import importlib.util
        if not native and importlib.util.find_spec('pcbnew') is not None:
            native = sys.executable
        if not cad and importlib.util.find_spec('FreeCAD') is not None:
            cad = sys.executable
    missing = [name for name, value in [('KiCad CLI', cli), ('KiCad Python', native),
                                       ('FreeCAD Python', cad)] if not value]
    if missing:
        raise RuntimeError('STEP view needs '+', '.join(missing)+'. Install FreeCAD or configure '
                           'WAYRICAD_THERM_FREECAD_PYTHON; configure WAYRICAD_THERM_KICAD_CLI/'
                           'WAYRICAD_THERM_KICAD_PYTHON for a custom KiCad installation.')
    return cli, native, cad


def _run(args, root, cancelled, deadline):
    if cancelled and cancelled():
        raise InterruptedError('Component model loading cancelled.')
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'VIRTUAL_ENV', 'PYTHONPATH'):
        env.pop(key, None)
    with (root/'process.log').open('w+', encoding='utf-8') as log:
        process = subprocess.Popen(list(map(str, args)), stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, env=env,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                if cancelled and cancelled():
                    raise InterruptedError('Component model loading cancelled.')
                if time.monotonic() > deadline:
                    raise TimeoutError('STEP model loading exceeded 180 seconds. Reduce model complexity.')
                time.sleep(.1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        if process.returncode:
            log.seek(0)
            raise RuntimeError('STEP model process failed: '+log.read()[-2000:])


def load_component_models(board_path, expected_source_sha256, cancelled=None, progress=None):
    """Return placed triangle meshes in KiCad XY, bottom Z=0, top Z=thickness.

    Results contain hashes and coverage, without private file paths. No source
    board or model is changed. Cancellation terminates only this owned process.
    """
    path = Path(board_path).resolve()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    if before != expected_source_sha256:
        raise ValueError('Saved board changed before STEP model loading; reload it.')
    cli, native, cad = discover()
    worker = Path(__file__).with_name('component_model_worker.py')
    started=time.monotonic()
    deadline = started+180
    def show_progress(stage,percent):
        if progress:
            progress({'stage':stage,'percent':percent,'elapsed_s':time.monotonic()-started,'eta_s':None})
    with tempfile.TemporaryDirectory(prefix='wayricad-thermal-models-') as temporary:
        root = Path(temporary)
        job = {'board_path':str(path), 'source_sha256':before, 'root':str(root)}
        job_path = root/'job.json'
        job_path.write_text(json.dumps(job), encoding='utf-8')
        show_progress('Resolve STEP models',0)
        _run([native, worker, 'prepare', job_path], root, cancelled, deadline)
        prepared = json.loads((root/'prepared.json').read_text(encoding='utf-8'))
        if prepared['model_map']:
            show_progress('Place STEP models with KiCad',25)
            _run([cli, 'pcb', 'export', 'step', '--force', '--subst-models',
                  '--user-origin', '0x0mm', '-o', root/'board.step', root/'snapshot.kicad_pcb'],
                 root, cancelled, deadline)
            show_progress('Read STEP component surfaces',65)
            _run([cad, worker, 'mesh', job_path], root, cancelled, deadline)
            output = json.loads((root/'meshes.json').read_text(encoding='utf-8'))
        else:
            output = {'components':{}, 'missing':[]}
        # Source/model races invalidate the result instead of showing old solids.
        if hashlib.sha256(path.read_bytes()).hexdigest() != before:
            raise ValueError('Saved board changed while loading STEP models; reload it.')
        for model in prepared['model_files']:
            if hashlib.sha256(Path(model['path']).read_bytes()).hexdigest() != model['sha256']:
                raise ValueError('A STEP model changed while loading; run again.')
        return {'components':output['components'], 'source_sha256':before,
                'coverage':{'loaded':sorted(output['components']),
                            'missing':prepared['missing']+output['missing']},
                'coordinate_system':'KiCad XY mm; board bottom Z=0, top Z=board thickness',
                'thermal_meaning':'One reviewed RC temperature per component; geometry has no material model.'}
