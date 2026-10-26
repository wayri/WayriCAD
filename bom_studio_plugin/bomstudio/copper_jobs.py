"""Owned, cancellable saved-board copper analysis; no project writes."""
from pathlib import Path
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time


def source_path(app, explicit=None):
    if explicit is not None and (not isinstance(explicit,str) or not explicit.strip()):
        raise ValueError('Choose a saved .kicad_pcb file.')
    if explicit:
        path=Path(explicit).expanduser()
        if not path.is_absolute() and app.workspace is not None:
            path=app.workspace.project.pro_path.parent/path
        elif not path.is_absolute():raise ValueError('Choose an absolute PCB path when no project is open.')
    elif getattr(app,'board_path',None):path=Path(app.board_path)
    elif app.workspace is not None:
        path=Path(app.workspace.state.get('health_settings',{}).get('board_path') or app.workspace.project.pro_path.with_suffix('.kicad_pcb'))
        if not path.is_absolute():path=app.workspace.project.pro_path.parent/path
    else:raise ValueError('Choose a saved .kicad_pcb file; a schematic is not required.')
    path=path.resolve()
    if path.suffix.lower()!='.kicad_pcb' or not path.is_file():raise ValueError('Choose an existing saved .kicad_pcb file.')
    if path.stat().st_size>64*1024*1024:raise ValueError('PCB exceeds the 64 MiB read limit.')
    return path


def check_source(report):
    source=report.get('source',{})
    path=Path(source.get('path',''))
    if not source.get('sha256') or not path.is_file() or path.stat().st_size>64*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:
        raise ValueError('Saved PCB changed or is unavailable. Analyze it again before exporting.')


def run(path, progress=lambda *_:None, cancelled=lambda:False, timeout=300):
    if isinstance(timeout,bool) or not math.isfinite(timeout) or not 1<=timeout<=600:raise ValueError('Copper timeout must be between 1 and 600 seconds.')
    from .board_analytics import prepare_geometry
    if not prepare_geometry():raise ValueError('Copper geometry requires Shapely; prepare the private runtime or standalone requirements.')
    path=Path(path).resolve()
    if path.suffix.lower()!='.kicad_pcb' or not path.is_file() or path.stat().st_size>64*1024*1024:raise ValueError('Choose a saved PCB no larger than 64 MiB.')
    expected=hashlib.sha256(path.read_bytes()).hexdigest()
    if cancelled():raise InterruptedError('Copper analysis canceled.')
    progress(0,None,'Reading saved PCB and computing copper unions; no board writes.')
    with tempfile.TemporaryDirectory(prefix='wayricad-copper-') as directory:
        folder=Path(directory);request=folder/'request.json';response=folder/'response.json';log=folder/'worker.log'
        request.write_text(json.dumps({'board':str(path),'sha256':expected}),encoding='utf-8')
        environment=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
        for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'):environment.pop(key,None)
        command=[sys.executable,'-I',str(Path(__file__).with_name('copper_worker.py')),str(request),str(response)]
        started=time.monotonic()
        with log.open('wb') as stream:
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                while process.poll() is None:
                    if cancelled():raise InterruptedError('Copper analysis canceled; saved PCB unchanged.')
                    elapsed=time.monotonic()-started
                    if elapsed>timeout:raise TimeoutError('Copper analysis exceeded its time budget; narrow the board or retry. No partial result was accepted.')
                    progress(0,None,f'Computing saved copper unions · {elapsed:.0f} s. Cancel remains available.')
                    time.sleep(.1)
                if cancelled():raise InterruptedError('Copper analysis canceled.')
                if process.returncode or not response.is_file():
                    detail=log.read_text(encoding='utf-8',errors='replace')[-4000:]
                    raise ValueError('Copper analysis failed: '+detail)
                if response.stat().st_size>32*1024*1024:raise ValueError('Copper report exceeds the 32 MiB result limit.')
                report=json.loads(response.read_text(encoding='utf-8'))
                check_source(report)
                if report['source']['sha256']!=expected:raise ValueError('Saved PCB changed during analysis; result discarded.')
                progress(1,1,'Copper analysis ready; saved PCB unchanged.')
                return report
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
