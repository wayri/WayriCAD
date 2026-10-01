"""IPC action opens a native saved-board Quick PI window."""
from pathlib import Path
import argparse
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
if not (ROOT/'wayricad_runtime').is_dir():sys.path.insert(0,str(ROOT.parent))


def main():
    from wayricad_runtime.bootstrap import relaunch, failure
    from wayricad_runtime.loading import LoadingWindow
    loading = LoadingWindow('WayriCAD Quick PI') if not os.environ.get('WAYRICAD_SPLASH_READY') else None
    try:
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--board',type=Path)
        args=parser.parse_args()
        status=relaunch(ROOT, 'desktop_entrypoint.py',
                        profile='quick-pi-board' if args.board else 'quick-pi', loading=loading)
        if status is not None:return status
        from wayricad_runtime.native_analysis import child_environment,active_saved_board
        board=args.board.resolve() if args.board else active_saved_board()
        if not board.is_file() or board.suffix.lower() != '.kicad_pcb':
            raise ValueError('Choose a saved KiCad PCB.')
        command=[sys.executable,'-I',str(ROOT/'quickmain.py'),'--board',str(board),'--ui']
        process=subprocess.Popen(command,
            env=child_environment(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return process.wait()
    except Exception as exc:
        return failure(exc, 'WayriCAD Quick PI')
    finally:
        if loading:loading.finish()


if __name__=='__main__':raise SystemExit(main())
