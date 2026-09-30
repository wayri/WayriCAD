"""Small stdlib-only handoff from KiCad's managed venv to a tested runtime."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor


def relaunch(root, entrypoint, *, profile='ipc', loading=None):
    from .runtime_setup import (ensure_runtime, child_environment, REQUIREMENTS_IPC,
                                REQUIREMENTS_EXTRACT, REQUIREMENTS_BOM,
                                REQUIREMENTS_QUICK_PI, REQUIREMENTS_QUICK_THERM,
                                REQUIREMENTS_MAGNETICS)
    requirements = {} if profile in {'quick-pi-board', 'quick-therm-board'} else dict(REQUIREMENTS_IPC)
    if profile == 'extract':
        requirements.update(REQUIREMENTS_EXTRACT)
    if profile == 'bom':
        requirements.update(REQUIREMENTS_BOM)
    if profile in {'quick-pi', 'quick-pi-board'}:
        requirements.update(REQUIREMENTS_QUICK_PI)
    if profile in {'quick-therm', 'quick-therm-board'}:
        requirements.update(REQUIREMENTS_QUICK_THERM)
    if profile in {'quick-pi-board', 'quick-therm-board'}:
        requirements.pop('kipy', None)
    if profile == 'magnetics':
        requirements.update(REQUIREMENTS_MAGNETICS)
    if profile == 'mechanical':
        requirements['OpenGL'] = 'PyOpenGL>=3.1,<4'
    if loading is not None and loading.window is not None:
        # Dependency preparation can take minutes. Keep the splash painting
        # while pip runs without moving any wx calls off the GUI thread.
        with ThreadPoolExecutor(max_workers=1) as worker:
            prepared = worker.submit(ensure_runtime, requirements)
            while not prepared.done():
                loading.tick()
                time.sleep(0.05)
            python = prepared.result()
    else:
        python = ensure_runtime(requirements)
    if (sys.flags.isolated and
            os.path.normcase(os.path.abspath(python)) == os.path.normcase(os.path.abspath(sys.executable))):
        return None
    # Preserve lexical venv paths: Unix venv executables symlink to the base Python.
    command = [str(python), '-I', str(Path(root) / entrypoint), *sys.argv[1:]]
    # KiCad's GUI host may expose invalid inherited console handles on Windows.
    # Give the managed GUI process valid standard handles or Python can exit 1
    # before the plugin has a chance to display its own error dialog.
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    env = child_environment()
    if loading is None or loading.window is None:
        return subprocess.call(command, env=env, **options)
    with tempfile.TemporaryDirectory(prefix='wayricad-loading-') as folder:
        ready = Path(folder) / 'ready'
        env['WAYRICAD_SPLASH_READY'] = str(ready)
        process = subprocess.Popen(command, env=env, **options)
        while process.poll() is None and not ready.is_file():
            loading.tick()
            time.sleep(0.05)
        loading.finish()
        return process.wait()


def failure(error, title='WayriCAD'):
    from .context import redact_error
    message = redact_error(error)
    print(title + ': ' + message, file=sys.stderr)
    try:
        import wx
        from .loading import ensure_wx_app
        app = ensure_wx_app(wx)
        wx.MessageBox(message, title, wx.OK | wx.ICON_ERROR)
    except Exception:
        # The managed interpreter often has no wx precisely when setup fails.
        # Keep an actionable message visible instead of requiring that dependency
        # to explain why the dependency could not be prepared.
        try:
            if sys.platform == 'win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            else:
                import tkinter
                from tkinter import messagebox
                window = tkinter.Tk(); window.withdraw()
                try: messagebox.showerror(title, message, parent=window)
                finally: window.destroy()
        except Exception:
            # Headless hosts retain stderr; KiCad 10.0.1+ also shows plugin warnings.
            pass
    return 1
