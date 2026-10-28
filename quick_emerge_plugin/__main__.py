"""Native window and isolated solver worker entry points."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

if __package__ in (None, ''):
    # Supports both source package and a flat, independently installed folder.
    import importlib.util
    root = Path(__file__).resolve().parent
    name = 'quick_emerge_plugin'
    spec = importlib.util.spec_from_file_location(name, root/'__init__.py', submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    __package__ = name


def main(argv=None, *, on_ready=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--check-runtime', action='store_true')
    parser.add_argument('--qualify-runtime', type=Path, metavar='CERTIFICATE')
    args = parser.parse_args(argv)
    if args.qualify_runtime:
        from .qualification import qualify
        qualify(args.qualify_runtime.resolve())
        return 0
    if args.check_runtime:
        from .backend import runtime_info
        print(json.dumps(runtime_info()))
        return 0
    if args.worker:
        from .backend import atomic_json, run_request
        request = args.worker.resolve()
        # Never run with a result destination aliased to the input or source PCB.
        if request.name != 'request.json':
            raise ValueError('Worker input must be request.json in a dedicated run directory.')
        os.chdir(request.parent)
        try:
            run_request(request)
            atomic_json(request.parent/'status.json', {'status': 'completed'})
            return 0
        except Exception as exc:
            traceback.print_exc()
            atomic_json(request.parent/'status.json', {'status': 'failed', 'error': str(exc)})
            return 2
    if not args.board:
        parser.error('--board is required for the native window')
    from .model import source_identity
    source_identity(args.board)
    import wx
    from .ui import QuickEMergeFrame
    sys.argv = sys.argv[:1]
    from wayricad_runtime.loading import ensure_wx_app
    app = ensure_wx_app(wx)
    frame = QuickEMergeFrame(args.board, auto_setup=True)
    frame.Show()
    def visible():
        ready = os.environ.get('WAYRICAD_SPLASH_READY')
        if ready:
            Path(ready).touch()
        if on_ready:
            on_ready()
    wx.CallAfter(visible)
    app.MainLoop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
