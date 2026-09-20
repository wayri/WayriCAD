"""Read-only STEP solid inspection through a separately installed FreeCAD Python."""
import json
import os
from pathlib import Path
import subprocess
import tempfile


def discover_python():
    explicit=os.environ.get('WAYRICAD_MAGNETICS_FREECAD_PYTHON') or os.environ.get('WAYRICAD_MECHANICAL_FREECAD_PYTHON')
    if explicit:return explicit
    if os.name=='nt':
        for root in (Path(os.environ.get('LOCALAPPDATA',''),'Programs'),Path(os.environ.get('PROGRAMFILES','C:/Program Files'))):
            candidates=sorted(root.glob('FreeCAD*/bin/python.exe'),reverse=True)
            if candidates:return str(candidates[0])
    raise ValueError('Set WAYRICAD_MAGNETICS_FREECAD_PYTHON to a Python executable that imports FreeCAD and Part. STEP inspection is optional.')


def inspect_step(path, python=None):
    source=Path(path).resolve()
    if source.suffix.lower() not in ('.step','.stp') or not source.is_file():raise ValueError('Choose an existing .step or .stp file')
    if source.stat().st_size>100*1024*1024:raise ValueError('STEP inspection is limited to 100 MiB')
    env=os.environ.copy()
    for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','CONDA_PREFIX'):env.pop(key,None)
    with tempfile.TemporaryDirectory(prefix='wayricad-core-') as folder:
        output=Path(folder)/'geometry.json'
        result=subprocess.run([python or discover_python(),str(Path(__file__).with_name('step_core_worker.py')),str(source),str(output)],
            env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode or not output.is_file():raise ValueError('FreeCAD could not inspect a valid STEP solid: '+result.stderr[-1500:])
        return json.loads(output.read_text(encoding='utf-8'))
