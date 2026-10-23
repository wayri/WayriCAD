"""Open the Assistant against the originating editor's saved board."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if not (ROOT / 'wayricad_runtime').is_dir():
    sys.path.insert(0, str(ROOT.parent))


def main():
    from wayricad_runtime.bootstrap import relaunch, failure
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--board', type=Path)
        args = parser.parse_args()
        status = relaunch(ROOT, 'desktop_entrypoint.py')
        if status is not None:
            return status
        from wayricad_runtime.native_analysis import active_saved_board, child_environment
        board = args.board if args.board else active_saved_board()
        return subprocess.call([sys.executable, '-I', str(ROOT / 'assistantmain.py'),
                                '--board', str(board)], env=child_environment(),
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as exc:
        return failure(exc, 'WayriCAD Assistant')


if __name__ == '__main__':
    raise SystemExit(main())
