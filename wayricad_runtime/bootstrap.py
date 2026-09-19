"""Small stdlib-only handoff from KiCad's managed venv to a tested runtime."""
import os
from pathlib import Path
import subprocess
import sys


def relaunch(root, entrypoint, *, profile='ipc'):
    from .runtime_setup import ensure_runtime, child_environment, REQUIREMENTS_IPC, REQUIREMENTS_QUICK_PI
    requirements = dict(REQUIREMENTS_IPC)
    if profile == 'quick-pi':
        requirements.update(REQUIREMENTS_QUICK_PI)
    if profile == 'mechanical':
        requirements['OpenGL'] = 'PyOpenGL>=3.1,<4'
    python = ensure_runtime(requirements)
    if (sys.flags.isolated and
            os.path.normcase(os.path.abspath(python)) == os.path.normcase(os.path.abspath(sys.executable))):
        return None
    # Preserve lexical venv paths: Unix venv executables symlink to the base Python.
    command = [str(python), '-I', str(Path(root) / entrypoint), *sys.argv[1:]]
    return subprocess.call(command, env=child_environment(),
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def failure(error, title='WayriCAD'):
    from .context import redact_error
    message = redact_error(error)
    print(title + ': ' + message, file=sys.stderr)
    try:
        import wx
        app = wx.App.Get() or wx.App(False)
        wx.MessageBox(message, title, wx.OK | wx.ICON_ERROR)
    except Exception:
        # KiCad 10.0.1+ retains stderr in its plugin warning messages.
        pass
    return 1
