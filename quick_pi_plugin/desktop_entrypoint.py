"""IPC action opens a native saved-board Quick PI window."""
from pathlib import Path
import argparse
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
if not (ROOT/'wayricad_runtime').is_dir():sys.path.insert(0,str(ROOT.parent))


def main():
    from wayricad_runtime.bootstrap import relaunch, failure
    try:
        status=relaunch(ROOT, 'desktop_entrypoint.py', profile='quick-pi')
        if status is not None:return status
        from wayricad_runtime.native_analysis import child_environment,active_saved_board
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--board',type=Path)
        args=parser.parse_args()
        board=args.board.resolve() if args.board else active_saved_board()
        if not board.is_file() or board.suffix.lower() != '.kicad_pcb':
            raise ValueError('Choose a saved KiCad PCB.')
        process=subprocess.Popen([sys.executable,'-I',str(ROOT/'quickmain.py'),'--board',str(board),'--ui'],
            env=child_environment(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return process.wait()
    except Exception as exc:
        return failure(exc, 'WayriCAD Quick PI')


if __name__=='__main__':raise SystemExit(main())
