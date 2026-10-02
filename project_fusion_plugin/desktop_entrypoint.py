"""KiCad IPC launcher for the native saved-file dialog.

Do not import the SWIG registration initializer in a standalone process.
KiCad's configured IPC Python may lack wx; probe its bundled Python as well.
"""
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types


def candidates():
    paths = [Path(sys.executable), Path(sys.base_prefix) / 'python.exe']
    cli = shutil.which('kicad-cli')
    if cli:
        paths.append(Path(cli).parent / ('python.exe' if os.name == 'nt' else 'python3'))
    if os.name == 'nt':
        paths.append(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) /
                     'KiCad' / '10.0' / 'bin' / 'python.exe')
    return list(dict.fromkeys(p for p in paths if p.is_file()))


def environment():
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
        env.pop(key, None)
    return env


def main():
    if '--native-gui' not in sys.argv:
        errors = []
        for python in candidates():
            probe = subprocess.run([str(python), '-I', '-c',
                                    'import wx; assert wx.VERSION >= (4, 0)'],
                                   env=environment(), capture_output=True, text=True,
                                   timeout=15,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if probe.returncode:
                errors.append(str(python) + ': ' + probe.stderr.strip())
                continue
            return subprocess.call([str(python), '-I', str(Path(__file__).resolve()),
                                    '--native-gui'], env=environment(),
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        raise RuntimeError('Wayri Project Fusion needs Python with wxPython. '
                           'Use KiCad 10 bundled Python.\n' + '\n'.join(errors))
    import wx
    package = types.ModuleType('_wayri_fusion_desktop')
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules[package.__name__] = package
    dialog_type = importlib.import_module(package.__name__ + '.gui').FusionDialog
    app = wx.GetApp() or wx.App(False)
    dialog = dialog_type(None)
    if '--review-plan' in sys.argv:
        index=sys.argv.index('--review-plan')
        if index+1>=len(sys.argv):raise ValueError('--review-plan needs a saved plan path')
        dialog.load_workspace_plan(sys.argv[index+1])
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
