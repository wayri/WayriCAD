import os
import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path


class Cancelled(Exception):
    pass


def discover():
    kicad_cli = os.environ.get('WAYRICAD_MECHANICAL_KICAD_CLI') or shutil.which('kicad-cli')
    kicad_python = os.environ.get('WAYRICAD_MECHANICAL_KICAD_PYTHON')
    freecad_python = os.environ.get('WAYRICAD_MECHANICAL_FREECAD_PYTHON')
    if os.name == 'nt':
        # The extraction worker uses SWIG. Do not accidentally select KiCad 11
        # (or lexically prefer 9 over 10) when several releases are installed.
        installations = sorted(Path(os.environ.get('PROGRAMFILES', 'C:/Program Files'), 'KiCad').glob('10.*/bin/kicad-cli.exe'), reverse=True)
        if not kicad_cli and installations:
            kicad_cli = str(installations[0])
        if not kicad_python and kicad_cli:
            native_python = Path(kicad_cli).with_name('python.exe')
            if native_python.is_file():
                kicad_python = str(native_python)
        roots = [Path(os.environ.get('LOCALAPPDATA', ''), 'Programs'), Path(os.environ.get('PROGRAMFILES', 'C:/Program Files'))]
        for root in roots:
            candidates = sorted(root.glob('FreeCAD*/bin/python.exe'), reverse=True)
            if not freecad_python and candidates:
                freecad_python = str(candidates[0])
    else:
        if not kicad_python and importlib.util.find_spec('pcbnew') is not None:
            kicad_python = sys.executable
    return dict(kicad_cli=kicad_cli, kicad_python=kicad_python, freecad_python=freecad_python)


def run_process(args, log, cancel=None, timeout=1800):
    env = os.environ.copy()
    env.pop('PYTHONHOME', None)
    env.pop('VIRTUAL_ENV', None)
    src = str(Path(__file__).resolve().parents[1])
    env['PYTHONPATH'] = src
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    start = time.monotonic()
    with open(log, 'w', encoding='utf-8') as stream:
        process = subprocess.Popen([str(a) for a in args], stdout=stream, stderr=subprocess.STDOUT,
                                   env=env, creationflags=flags)
        try:
            while process.poll() is None:
                if cancel and cancel.is_set():
                    raise Cancelled('Validation cancelled')
                if time.monotonic() - start > timeout:
                    raise RuntimeError('Geometry process exceeded the time limit; see ' + str(log))
                time.sleep(.1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if process.returncode:
            raise RuntimeError(Path(log).read_text(encoding='utf-8', errors='replace')[-4000:])

