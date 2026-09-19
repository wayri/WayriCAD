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


sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

FRAMES = {
    'trace_impedance_plugin': ('trace_impedance_plugin', 'TraceFrame'),
    'signal_integrity_advisor_plugin': ('signal_integrity_advisor_plugin', 'SignalIntegrityFrame'),
}


def child_environment():
    from wayricad_runtime.runtime_setup import child_environment as environment
    return environment()


def native_python():
    from wayricad_runtime.runtime_setup import ensure_runtime, REQUIREMENTS_IPC
    return ensure_runtime(REQUIREMENTS_IPC)


def active_saved_board():
    from .context import saved_board
    return saved_board()


def launch(root, tool):
    source = active_saved_board()
    process = subprocess.Popen([str(native_python()), '-I', str(Path(__file__).resolve()),
                                '--root', str(root), '--tool', tool, '--board', str(source)],
                               env=child_environment(),
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return process.wait()


def create_frame(root, tool, board_path):
    import pcbnew
    import wx
    sys.path.insert(0,str(Path(root).resolve()))
    if (Path(root).resolve().parent / 'wayricad_runtime').is_dir():
        sys.path.insert(0,str(Path(root).resolve().parent))
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
