"""Launch independently so the project can be closed before an offline apply."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import pcbnew


def native_python():
    """Locate a real KiCad Python executable, never the PCB editor executable."""
    candidates = [Path(sys.base_prefix) / 'python.exe', Path(sys.prefix) / 'python.exe',
                  Path(sys.base_prefix) / 'bin/python3', Path(sys.prefix) / 'bin/python3']
    if re.fullmatch(r'pythonw?(?:\d+(?:\.\d+)*)?', Path(sys.executable).stem.lower()):
        candidates.insert(0, Path(sys.executable))
    for prefix in ('KICAD10', 'KICAD'):
        if os.environ.get(prefix):
            candidates.append(Path(os.environ[prefix]) / 'bin' / 'python.exe')
    if os.name != 'nt' and shutil.which('python3'):
        candidates.append(Path(shutil.which('python3')))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError('KiCad bundled Python was not found. Run wayricad-variants gui with a Python runtime containing wxPython.')


class VariantManagerAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'WayriCAD Variant Manager'
        self.category = 'Project management'
        self.description = 'Preview, compare and manage native assembly variants with verified backups'
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).with_name('icon.png'))
        self.dark_icon_file_name = self.icon_file_name

    def Run(self):
        import wx
        try:
            board = pcbnew.GetBoard()
            project = board.GetFileName() if board else ''
            subprocess.Popen([str(native_python()), '-I', str(Path(__file__).with_name('desktop_entrypoint.py')),
                              '--project', project], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception as exc:
            wx.MessageBox(str(exc), self.name, wx.OK | wx.ICON_ERROR)
