"""Run filled-polygon electrical analysis in KiCad's native geometry runtime.

The IPC action supplies the active board's saved path. Native geometry is not
emulated by the IPC facade; this window explicitly analyzes a saved snapshot.
"""
import argparse
import importlib
import os
from pathlib import Path
import subprocess
import sys
import types
import uuid


sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

FRAMES = {
    'trace_impedance_plugin': ('trace_impedance_plugin', 'TraceFrame'),
    'signal_integrity_advisor_plugin': ('signal_integrity_advisor_plugin', 'SignalIntegrityFrame'),
}


class LoadingCancelled(Exception):
    """The user closed the loading window before the analysis window opened."""


def _loading_window(wx, tool):
    """Paint a status frame before KiCad's short blocking board read."""
    title = 'Trace RLC / Impedance' if tool == 'trace_impedance_plugin' else 'Quick SI'

    class LoadingWindow(wx.Frame):
        def __init__(self):
            super().__init__(None, title=f'WayriCAD {title} — Loading', size=(400, 142),
                             style=wx.CAPTION | wx.CLOSE_BOX | wx.FRAME_TOOL_WINDOW)
            self.cancelled = False
            panel = wx.Panel(self)
            body = wx.BoxSizer(wx.VERTICAL)
            heading = wx.StaticText(panel, label=f'Opening {title}')
            font = heading.GetFont()
            font.MakeBold()
            heading.SetFont(font)
            body.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)
            self.detail = wx.StaticText(panel, label='Reading the saved PCB…')
            body.Add(self.detail, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)
            body.Add(wx.StaticText(panel, label='This read-only step may take a few seconds.'),
                     0, wx.LEFT | wx.RIGHT | wx.TOP, 16)
            panel.SetSizer(body)
            self.Bind(wx.EVT_CLOSE, self._cancel)
            self.CentreOnScreen()

        def _cancel(self, _event):
            self.cancelled = True
            self.Hide()

        def stage(self, message):
            if not self.cancelled:
                self.detail.SetLabel(message)
                wx.YieldIfNeeded()

        def start(self):
            self.Show()
            wx.YieldIfNeeded()

        def finish(self):
            self.Unbind(wx.EVT_CLOSE)
            self.Hide()
            self.Destroy()

    return LoadingWindow()


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
        "import importlib,sys,types;from pathlib import Path;"
        "root=Path(sys.argv[1]);sys.path.insert(0,str(root));"
        "sys.path.insert(0,str(root.parent));"
        "from wayricad_runtime.launcher import _package_version;"
        "name='wayricad_electrical_cli';"
        "package=types.ModuleType(name);package.__package__=name;package.__path__=[str(root)];"
        "version=_package_version(root);"
        "package.__version__=version if version is not None else '';sys.modules[name]=package;"
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


def create_frame(root, tool, board_path, selection_ids=(), status=None, cancelled=None):
    import pcbnew
    import wx
    sys.path.insert(0,str(Path(root).resolve()))
    if (Path(root).resolve().parent / 'wayricad_runtime').is_dir():
        sys.path.insert(0,str(Path(root).resolve().parent))
    module_name, frame_name = FRAMES[tool]
    root = Path(root).resolve()
    # A source initializer may register a legacy SWIG ActionPlugin. A fresh
    # package namespace per window avoids that side effect and stale modules
    # when multiple electrical windows open in one KiCad Python process.
    if not (root / module_name / '__init__.py').is_file() and not (root / (module_name + '.py')).is_file():
        raise ValueError('The electrical-analysis package is incomplete. Reinstall its ZIP.')
    from .launcher import _package_version
    package = 'wayricad_native_electrical_' + uuid.uuid4().hex
    loaded = types.ModuleType(package)
    loaded.__package__ = package
    loaded.__path__ = [str(root)]
    version = _package_version(root)
    if version is not None:
        loaded.__version__ = version
    sys.modules[package] = loaded
    module = importlib.import_module('.' + module_name, package)
    board = pcbnew.LoadBoard(str(board_path))
    if status is not None:
        status('Preparing the analysis window…')
    if cancelled is not None and cancelled():
        raise LoadingCancelled()
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
    loading = None
    try:
        import wx
        app = wx.App.Get() or wx.App(False)
        loading = _loading_window(wx, args.tool)
        loading.start()
        app, frame = create_frame(args.root, args.tool, args.board,
                                  filter(None, args.selection_ids.split(',')),
                                  status=loading.stage,
                                  cancelled=lambda: loading.cancelled)
        if loading.cancelled:
            frame.Destroy()
            return 0
        frame.Show()
        loading.finish()
        loading = None
        app.MainLoop()
        return 0
    except LoadingCancelled:
        return 0
    except Exception as exc:
        if loading is not None:
            loading.finish()
            loading = None
        import wx
        app = wx.App.Get() or wx.App(False)
        wx.MessageBox(str(exc), 'WayriCAD electrical analysis', wx.OK | wx.ICON_ERROR)
        return 1
    finally:
        if loading is not None:
            loading.finish()


if __name__ == '__main__':
    raise SystemExit(main())
