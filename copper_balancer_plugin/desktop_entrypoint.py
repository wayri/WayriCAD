"""PCM entry point: launch the local saved-board workflow with KiCad Python."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if not (ROOT/'wayricad_runtime').is_dir():sys.path.insert(0,str(ROOT.parent))
from native_runner import launch

def main():
    from wayricad_runtime.bootstrap import relaunch, failure
    try:
        status=relaunch(ROOT,'desktop_entrypoint.py')
        if status is not None:return status
        from wayricad_runtime.context import saved_board
        return launch(['--gui',str(saved_board())])
    except Exception as exc:return failure(exc,'WayriCAD Copper Balancer')

if __name__ == '__main__':
    raise SystemExit(main())
