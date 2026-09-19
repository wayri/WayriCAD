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
import uuid


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


def run_cli(root, argv):
    """Run an independently installed electrical CLI with native KiCad geometry."""
    script = (
        "import importlib,importlib.util,sys;from pathlib import Path;"
        "root=Path(sys.argv[1]);sys.path.insert(0,str(root));"
        "sys.path.insert(0,str(root.parent));"
        "name='wayricad_electrical_cli';"
        "spec=importlib.util.spec_from_file_location(name,root/'__init__.py',submodule_search_locations=[str(root)]);"
        "package=importlib.util.module_from_spec(spec);sys.modules[name]=package;spec.loader.exec_module(package);"
        "module=importlib.import_module('.cli',name);raise SystemExit(module.main(sys.argv[2:]))"
    )
    process = subprocess.run([str(native_python()), '-I', '-X', 'utf8', '-c', script,
                              str(Path(root).resolve()), *argv],
                             env=child_environment(), capture_output=True,
                             text=True, encoding='utf-8', errors='replace',
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    sys.stdout.write(process.stdout)
    sys.stderr.write(process.stderr)
    return process.returncode


def launch(root, tool):
    from .context import connect, saved_board
    client = connect()
    source = saved_board(client)
    # Selection is only a hint against the same editor's saved snapshot.
    selection = []
    try:
        from .ipc import uid
        selection = [str(uuid.UUID(uid(item))) for item in client.get_board().get_selection()][:200]
    except Exception:
        pass
    process = subprocess.Popen([str(native_python()), '-I', str(Path(__file__).resolve()),
                                '--root', str(root), '--tool', tool, '--board', str(source),
                                '--selection-ids', ','.join(selection)],
                               env=child_environment(),
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return process.wait()


def restore_selection(board, identifiers):
    """Seed only IDs present in the saved board; never mutate the live editor."""
    selected = {str(uuid.UUID(value)) for value in identifiers}
    if len(selected) > 200:
        raise ValueError('Selection hint exceeds 200 board items.')
    items = list(board.GetTracks()) + list(board.Zones())
    for footprint in board.GetFootprints():
        items.append(footprint)
        items.extend(footprint.Pads())
    for item in items:
        if str(item.m_Uuid.AsString()) in selected:
            item.SetSelected()


def create_frame(root, tool, board_path, selection_ids=()):
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
    restore_selection(board, selection_ids)
    app = wx.App.Get() or wx.App(False)
    frame = getattr(module, frame_name)(None, board, saved_board=True)
    return app, frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--tool', required=True, choices=FRAMES)
    parser.add_argument('--board', required=True, type=Path)
    parser.add_argument('--selection-ids', default='', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        app, frame = create_frame(args.root, args.tool, args.board,
                                  filter(None, args.selection_ids.split(',')))
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
