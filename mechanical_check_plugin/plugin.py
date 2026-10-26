"""Optional native KiCad 10 action; the PCM package also has an IPC launcher."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if not (ROOT / 'wayricad_runtime').is_dir():
    sys.path.insert(0, str(ROOT.parent))
try:
    import pcbnew
except ImportError:
    pcbnew = None

if pcbnew is not None:
    class MechanicalCheckPlugin(pcbnew.ActionPlugin):
        def defaults(self):
            self.name = 'WayriCAD Mechanical Check'
            self.category = 'Mechanical validation'
            self.description = 'Review saved-board fit, hardware and model coverage'
            self.show_toolbar_button = True
            root = Path(__file__).resolve().parent
            self.icon_file_name = str(root / 'resources/icon-24.png')
            self.dark_icon_file_name = str(root / 'resources/icon-dark-24.png')

        def Run(self):
            # The editor's embedded Python cannot acquire private dependencies.
            # Match the IPC/standalone runtime before importing the viewer.
            from wayricad_runtime.runtime_setup import ensure_runtime, child_environment, REQUIREMENTS_MECHANICAL
            from wayricad_runtime.bootstrap import failure
            from wayricad_runtime.loading import LoadingWindow
            loading = LoadingWindow('Mechanical Check')
            try:
                board = pcbnew.GetBoard()
                path = board.GetFileName() if board else None
                # Keep KiCad's event loop painting while a cold runtime downloads
                # wheels; only the main thread touches wx, as in the IPC bootstrap.
                with ThreadPoolExecutor(max_workers=1) as worker:
                    prepared = worker.submit(ensure_runtime, REQUIREMENTS_MECHANICAL)
                    while not prepared.done():
                        loading.tick()
                        time.sleep(0.05)
                    python = prepared.result()
                command = [str(python), '-I', str(ROOT / 'launch.py'), '--gui']
                if path:
                    command.append(path)
                self.process = subprocess.Popen(command, env=child_environment(),
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except Exception as exc:
                loading.finish()
                failure(exc, 'WayriCAD Mechanical Check')
            finally:
                loading.finish()


