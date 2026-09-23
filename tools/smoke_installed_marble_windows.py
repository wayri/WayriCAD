"""Check installed native WayriCAD windows against a saved Marble PCB.

Each invocation checks one plugin in a disposable Python process. It only
constructs and shows the window; it does not invoke apply/export handlers.
"""
import argparse
import ctypes
import importlib
import json
import os
from pathlib import Path
import sys
import types

if sys.platform == "win32":
    ctypes.windll.kernel32.SetErrorMode(0x0002)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("quick-pi", "quick-si", "mechanical", "extract-pins"))
    parser.add_argument("root", type=Path)
    parser.add_argument("board", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root, board = args.root.resolve(), args.board.resolve()
    if not (root / "plugin.json").is_file() or not board.is_file():
        parser.error("Installed plugin and saved board must exist")
    sys.path.insert(0, str(root))
    import wx
    app = wx.App.Get() or wx.App(False)
    result = {"kind": args.kind, "status": "starting", "windows": []}

    def record(status, **extra):
        result.update(status=status, **extra)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")

    try:
        if args.kind == "quick-si":
            from wayricad_runtime.native_analysis import create_frame
            _, frame = create_frame(root, "signal_integrity_advisor_plugin", board)
        elif args.kind == "mechanical":
            sys.path.insert(0, str(root / "src"))
            from wayricad_mechanical.ui import Window
            frame = Window(board_path=board)
        elif args.kind == "extract-pins":
            import pcbnew
            saved_board = pcbnew.LoadBoard(str(board))
            pcbnew.GetBoard = lambda: saved_board
            package = "wayricad_installed_extract_pins_audit"
            namespace = types.ModuleType(package)
            namespace.__package__ = package
            namespace.__path__ = [str(root)]
            sys.modules[package] = namespace
            frame = importlib.import_module(".plugin_dialog_v2", package).PluginDialogV2(None, [])
            frame.OnConnectorPreset(None)
            result["preview_rows"] = len(frame.preview_rows)
            result["connector_summary"] = frame.connector_summary.GetLabel()
            if result["preview_rows"] < 300:
                raise AssertionError("Marble J* connector preview is unexpectedly small")
        else:
            import pcbnew
            package = "wayricad_installed_quick_pi_audit"
            namespace = types.ModuleType(package)
            namespace.__package__ = package
            namespace.__path__ = [str(root)]
            sys.modules[package] = namespace
            frame = importlib.import_module(".ui", package).QuickPIFrame(None, board)
        frame.Show()
        record("shown", windows=[{"title": frame.GetTitle(), "class": type(frame).__name__}])

        def inspect():
            try:
                shown = [window for window in wx.GetTopLevelWindows() if window.IsShown()]
                record("passed" if frame in shown else "failed",
                       windows=[{"title": window.GetTitle(), "class": type(window).__name__}
                                for window in shown])
            except Exception as exc:
                record("failed", error=f"{type(exc).__name__}: {exc}")
            finally:
                for window in list(wx.GetTopLevelWindows()):
                    window.Close()
                wx.CallLater(300, app.ExitMainLoop)

        wx.CallLater(1200, inspect)
        app.MainLoop()
    except BaseException as exc:
        record("failed", error=f"{type(exc).__name__}: {exc}")
        return 1
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
