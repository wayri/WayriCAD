"""Native saved-board extraction runs outside both desktop and solver Python."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

from .dependencies import run_command


def native_python():
    explicit = os.environ.get('WAYRICAD_QUICK_EMERGE_KICAD_PYTHON')
    candidates = [Path(explicit)] if explicit else [Path(sys.executable)]
    if not explicit and os.name == 'nt':
        root = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'KiCad'
        if root.is_dir():
            candidates.extend(sorted(root.glob('*/bin/python.exe'), reverse=True))
    if not explicit and os.name != 'nt':
        candidates.extend(Path(p) for name in ('python3', 'python') if (p := shutil.which(name)))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            probe = subprocess.run([str(candidate), '-I', '-c', 'import pcbnew; print(pcbnew.Version())'],
                                   capture_output=True, text=True, timeout=15,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if probe.returncode == 0:
                return candidate.resolve()
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise RuntimeError('Native KiCad Python is required to read rule areas. Set WAYRICAD_QUICK_EMERGE_KICAD_PYTHON to the installed KiCad Python executable.')


def extract_region(board, area=None, *, cancel=None, progress=lambda text: None):
    cancel = cancel or threading.Event()
    python = native_python()
    scratch = os.environ.get('WAYRICAD_QUICK_EMERGE_SCRATCH') or None
    with tempfile.TemporaryDirectory(prefix='quick-emerge-region-', dir=scratch) as directory:
        output = Path(directory)/'extraction.json'
        command = [python, '-I', Path(__file__).with_name('region_worker.py'), '--board', Path(board).resolve(), '--output', output]
        if area:
            command.extend(['--area', area])
        progress('Reading saved rule-area polygons and filled copper in native KiCad Python…')
        try:
            run_command(command, log=Path(directory)/'native.log', cancel=cancel, timeout=120, progress=progress)
        except RuntimeError as exc:
            if output.is_file():
                error = json.loads(output.read_text(encoding='utf-8')).get('error')
                if error:
                    raise ValueError(error) from exc
            log = Path(directory)/'native.log'
            detail = log.read_text(encoding='utf-8', errors='replace')[-4000:] if log.is_file() else str(exc)
            raise RuntimeError('Native region extraction failed: '+detail) from exc
        result = json.loads(output.read_text(encoding='utf-8'))
        if result.get('error'):
            raise ValueError(result['error'])
        return result
