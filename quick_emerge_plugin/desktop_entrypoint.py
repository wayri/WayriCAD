"""Open Quick EMerge with the originating saved PCB and a private desktop runtime."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if not (ROOT / 'wayricad_runtime').is_dir():
    sys.path.insert(0, str(ROOT.parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path)
    args = parser.parse_args(argv)
    from wayricad_runtime.bootstrap import failure, relaunch
    from wayricad_runtime.loading import LoadingWindow
    loading = None
    try:
        if not os.environ.get('WAYRICAD_SPLASH_READY'):
            loading = LoadingWindow('WayriCAD Quick EMerge')
        status = relaunch(ROOT, 'desktop_entrypoint.py', profile='quick-emerge', loading=loading)
        if status is not None:
            return status
        from wayricad_runtime.context import saved_board
        board = args.board.resolve() if args.board else saved_board()
        if not board.is_file() or board.suffix.lower() != '.kicad_pcb':
            raise ValueError('Choose a saved KiCad PCB. Save the originating board and reopen Quick EMerge.')
        # Load the package through its standalone loader, including flat PCM installs.
        import importlib.util
        spec = importlib.util.spec_from_file_location('wayricad_quick_emerge_main', ROOT / '__main__.py')
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        return entry.main(['--board', str(board)], on_ready=loading.finish if loading else None)
    except Exception as exc:
        return failure(exc, 'WayriCAD Quick EMerge')
    finally:
        if loading:
            loading.finish()


if __name__ == '__main__':
    raise SystemExit(main())
