"""Launch the local viewer in KiCad 10's native Python, with saved-file context."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))


def saved_board_path(client):
    """Read document identity only; never save or claim an in-memory snapshot."""
    document = client.get_board().document
    filename = getattr(document, 'board_filename', '')
    if not filename:
        return None
    path = Path(filename)
    if not path.is_absolute():
        directory = getattr(getattr(document, 'project', None), 'path', '')
        if not directory:
            return None
        path = Path(directory) / path
    return str(path.resolve()) if path.is_file() else None


def main():
    from wayricad_mechanical.runtime import discover
    python = discover()['kicad_python']
    if not python:
        return notify_error('Install KiCad 10, or set WAYRICAD_MECHANICAL_KICAD_PYTHON to its Python executable. The mechanical extractor currently requires pcbnew from KiCad 10.')
    board = None
    try:
        from kipy import KiCad
        board = saved_board_path(KiCad(timeout_ms=1500))
    except Exception as exc:
        print('Saved board context unavailable; choose a board in the local window: ' + str(exc), file=sys.stderr)
    args = [python, str(ROOT / 'launch.py'), '--gui']
    if board:
        args.append(board)
    env = os.environ.copy()
    # KiCad's managed IPC interpreter may point at incompatible Python/Tcl DLLs.
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
        env.pop(key, None)
    try:
        child = subprocess.run(args, env=env, capture_output=True, text=True,
                               encoding='utf-8', errors='replace',
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except OSError as exc:
        return notify_error('Could not start KiCad Python: ' + str(exc) + '\nCheck WAYRICAD_MECHANICAL_KICAD_PYTHON.')
    if child.returncode:
        details = (child.stderr or child.stdout).strip()[-1800:]
        return notify_error('The local viewer could not finish. KiCad 10 Python must include pcbnew, wxPython and PyOpenGL.\nRun launch.py --doctor to check runtime paths.\n\n' + details)
    return 0


def notify_error(message):
    """Keep launch failures visible even when KiCad starts without a terminal."""
    print(message, file=sys.stderr)
    try:
        import wx
        app = wx.App.Get() or wx.App(False)
        wx.MessageBox(message, 'WayriCAD Mechanical Check', wx.OK | wx.ICON_ERROR)
    except Exception:
        pass
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
