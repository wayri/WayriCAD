"""Discover a compatible local interpreter without importing its binary modules."""
import os
from pathlib import Path
import subprocess
import sys


def candidates():
    explicit = os.environ.get('WAYRICAD_KICAD_PYTHON')
    if explicit:
        yield Path(explicit)
    yield Path(sys.executable)
    program_files = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))
    for path in sorted((program_files / 'KiCad').glob('10.*/bin/python.exe'), reverse=True):
        yield path
    for path in ('/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3',
                 '/usr/bin/python3'):
        yield Path(path)


def child_environment():
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
        env.pop(key, None)
    env['WAYRICAD_COPPER_NO_REGISTER'] = '1'
    return env


def find_native_python():
    checked = set()
    probe = ('import pcbnew as p, wx; '
             'assert str(p.Version()).startswith("10."), "KiCad 10 required"; '
             'assert hasattr(p,"SHAPE_POLY_SET")')
    for path in candidates():
        if not path.is_file() or str(path.resolve()).casefold() in checked:
            continue
        checked.add(str(path.resolve()).casefold())
        try:
            result = subprocess.run([str(path), '-c', probe], env=child_environment(),
                                    capture_output=True, timeout=12,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode == 0:
                return path
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError('Copper Balancer needs KiCad 10 with its native Python geometry libraries. '
                       'Install KiCad 10 or set WAYRICAD_KICAD_PYTHON to its Python executable. '
                       'KiCad 11 native geometry is not yet supported.')


def launch(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        python = find_native_python()
        process = subprocess.run([str(python), str(Path(__file__).with_name('native_app.py')), *arguments],
                                 env=child_environment(),
                                 capture_output=bool(arguments), text=True, encoding='utf-8', errors='replace',
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if arguments:
            if process.stdout:
                print(process.stdout, end='')
            if process.stderr:
                print(process.stderr, end='', file=sys.stderr)
        return process.returncode
    except Exception as exc:
        if arguments:
            print(str(exc), file=sys.stderr)
        else:
            import wx
            app = wx.App.Get() or wx.App(False)
            wx.MessageBox(str(exc), 'WayriCAD Copper Balancer', wx.OK | wx.ICON_ERROR)
        return 1
