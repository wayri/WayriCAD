"""Standalone native window and worker for QuickTherm."""

import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def package():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    if (root.parent / "wayricad_runtime").is_dir():
        sys.path.insert(0, str(root.parent))
    name = "wayricad_quick_therm_worker"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, root / "__init__.py", submodule_search_locations=[str(root)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", nargs=2, metavar=("REQUEST", "RESPONSE"))
    parser.add_argument("--board", type=Path)
    parser.add_argument("--ui", action="store_true")
    args = parser.parse_args(argv)
    name = package()
    if args.worker:
        request, response = map(Path, args.worker)
        try:
            if request.resolve() == response.resolve():
                raise ValueError("Worker response must not overwrite the request file.")
            payload = json.loads(request.read_text(encoding="utf-8"))
            if payload.get("board_path") and Path(payload["board_path"]).resolve() == response.resolve():
                raise ValueError("Worker response must not overwrite the source PCB.")
            result = importlib.import_module(".service", name).execute(payload)
            if payload.get("html_output"):
                started = time.monotonic()
                if payload.get("_emit_progress"):
                    print('WAYRICAD_PROGRESS '+json.dumps({"stage":"report rendering",
                        "completed":0,"total":1,"percent":0,"elapsed_s":0,"eta_s":None}),
                        flush=True)
                if payload.get('action') == 'transient':
                    from wayricad_runtime.transient_study import write_study_report
                    write_study_report(payload['html_output'], result)
                else:
                    importlib.import_module(".report", name).write_report(payload["html_output"], result)
                if payload.get("_emit_progress"):
                    print('WAYRICAD_PROGRESS '+json.dumps({"stage":"report rendering",
                        "completed":1,"total":1,"percent":100,
                        "elapsed_s":time.monotonic()-started,"eta_s":0}), flush=True)
            status = 0
        except Exception as exc:
            result = {"error": str(exc), "error_type": type(exc).__name__}
            status = 2

        def convert(value):
            if hasattr(value, "tolist"):
                return value.tolist()
            if hasattr(value, "item"):
                return value.item()
            raise TypeError(type(value).__name__)

        response.write_text(json.dumps(result, default=convert, allow_nan=False), encoding="utf-8")
        return status
    if not args.board:
        parser.error("--board is required for the native window")
    sys.argv = sys.argv[:1]
    import wx

    app = wx.App(False)
    try:
        frame = importlib.import_module(".ui", name).QuickThermFrame(None, args.board)
        frame.Show()
        ready = os.environ.get("WAYRICAD_SPLASH_READY")
        if ready:
            Path(ready).touch()
        app.MainLoop()
        return 0
    except Exception as exc:
        wx.MessageBox(str(exc), "WayriCAD QuickTherm", wx.OK | wx.ICON_ERROR)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
