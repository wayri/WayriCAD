"""IPC action opens a native saved-board Quick PI window."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
if not (ROOT/'wayricad_runtime').is_dir():sys.path.insert(0,str(ROOT.parent))


def main():
    from wayricad_runtime.native_analysis import native_python,child_environment,active_saved_board
    board=active_saved_board()
    process=subprocess.Popen([str(native_python()),str(ROOT/'quickmain.py'),'--board',str(board),'--ui'],
        env=child_environment(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return process.wait()


if __name__=='__main__':raise SystemExit(main())
