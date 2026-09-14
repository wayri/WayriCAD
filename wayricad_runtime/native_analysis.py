"""Run filled-polygon electrical analysis in KiCad's native geometry runtime.

The IPC action supplies the active board's saved path. Native geometry is not
emulated by the IPC facade; this window explicitly analyzes a saved snapshot.
"""
import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


FRAMES = {
    'trace_impedance_plugin': ('trace_impedance_plugin', 'TraceFrame'),
    'signal_integrity_advisor_plugin': ('signal_integrity_advisor_plugin', 'SignalIntegrityFrame'),
}


def child_environment():
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
        env.pop(key, None)
    return env


def native_python():
    candidates = [os.environ.get('WAYRICAD_KICAD_PYTHON', ''), sys.executable]
    program_files = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))
    candidates.extend(sorted((program_files / 'KiCad').glob('10.*/bin/python.exe'), reverse=True))
    candidates.extend(('/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3', '/usr/bin/python3'))
    seen = set()
    probe = ('import pcbnew as p,wx; assert str(p.Version()).startswith("10."); '
             'assert hasattr(p,"SHAPE_POLY_SET") and hasattr(p,"LoadBoard")')
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_file() or str(path.resolve()).casefold() in seen:
            continue
        seen.add(str(path.resolve()).casefold())
        try:
            result = subprocess.run([str(path), '-c', probe], env=child_environment(),
                                    capture_output=True, timeout=12,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode == 0:
                return path
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise RuntimeError('RLC and impedance analysis need KiCad 10 native Python geometry. '
                       'Install KiCad 10 or set WAYRICAD_KICAD_PYTHON to its Python executable.')


def active_saved_board():
    from kipy import KiCad
    board = KiCad().get_board()
    path = Path(board.name)
    if not path.is_absolute():
        path = Path(board.get_project().path) / path
    if not path.is_file() or path.suffix.lower() != '.kicad_pcb':
        raise ValueError('Save the PCB in KiCad before opening electrical analysis.')
    return path.resolve()


def launch(root, tool):
    source = active_saved_board()
    process = subprocess.Popen([str(native_python()), str(Path(__file__).resolve()),
                                '--root', str(root), '--tool', tool, '--board', str(source)],
                               env=child_environment(),
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return process.wait()


def create_frame(root, tool, board_path):
    import pcbnew
    import wx
    module_name, frame_name = FRAMES[tool]
    root = Path(root).resolve()
    # Installed PCM folders have arbitrary package IDs. Load their modules
    # under a private package name so all relative imports stay self-contained.
    package = 'wayricad_native_electrical'
    spec = importlib.util.spec_from_file_location(package, root / '__init__.py',
                                                 submodule_search_locations=[str(root)])
    if spec is None or spec.loader is None:
        raise ValueError('The electrical-analysis package is incomplete. Reinstall its ZIP.')
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[package] = loaded
    spec.loader.exec_module(loaded)
    module = importlib.import_module('.' + module_name, package)
    board = pcbnew.LoadBoard(str(board_path))
    if board is None:
        raise ValueError('KiCad could not load the saved board.')
    app = wx.App.Get() or wx.App(False)
    frame = getattr(module, frame_name)(None, board, saved_board=True)
    return app, frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--tool', required=True, choices=FRAMES)
    parser.add_argument('--board', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        app, frame = create_frame(args.root, args.tool, args.board)
        frame.Show()
        app.MainLoop()
        return 0
    except Exception as exc:
        import wx
        app = wx.App.Get() or wx.App(False)
        wx.MessageBox(str(exc), 'WayriCAD electrical analysis', wx.OK | wx.ICON_ERROR)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
