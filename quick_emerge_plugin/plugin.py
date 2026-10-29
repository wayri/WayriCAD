"""Compatibility delegate for KiCad installations with an older shared menu bridge."""
from pathlib import Path
import subprocess

class QuickEMergePlugin:
    def Run(self):
        import pcbnew
        from wayricad_runtime.runtime_setup import native_python,child_environment
        board=pcbnew.GetBoard()
        filename=board.GetFileName() if board is not None else ''
        source=Path(filename).resolve() if filename else None
        if source is None or not source.is_file() or source.suffix.lower()!='.kicad_pcb':
            raise ValueError('Open and save the originating PCB before launching Quick EMerge.')
        root=Path(__file__).resolve().parent
        subprocess.Popen([str(native_python()),'-I',str(root/'desktop_entrypoint.py'),'--board',str(source)],
                         env=child_environment(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
