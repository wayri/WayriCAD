"""Bounded, read-only native window probes (not live-editor compatibility tests).

Run with a complete desktop Python; --python selects KiCad's Python for children.
All evidence and child caches are confined to --output. No plugin installers run.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import types

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "bulk_label_editor_plugin": ("bulk_label_editor_plugin", "BulkLabelEditorFrame", "board"),
    "fanout_generator_plugin": ("fanout_generator_plugin", "FanoutFrame", "board"),
    "via_stitching_plugin": ("via_stitching_plugin", "ViaFrame", "board"),
    "copper_balancer_plugin": ("copper_balancer.dialog", "CopperBalancerDialog", "board"),
    "quick_pi_plugin": ("ui", "QuickPIFrame", "path"),
    "signal_integrity_advisor_plugin": ("signal_integrity_advisor_plugin", "SignalIntegrityFrame", "saved"),
    "manufacturing_readiness_plugin": ("dfm_ui", "DFMFrame", "saved"),
    "extract_pins_plugin": ("plugin_dialog_v2", "PluginDialogV2", "selection"),
    "heater_designer_plugin": ("heater_designer_plugin", "HeaterFrame", "board"),
    "planar_magnetics_plugin": ("planar_magnetics_plugin", "MagneticsFrame", "board"),
    "mechanical_check_plugin": ("wayricad_mechanical.ui", "Window", "mechanical"),
    "harness_workbench_plugin": ("harness_workbench_plugin", "HarnessFrame", "empty"),
    "protocol_constraint_composer_plugin": ("studio_ui", "ConstraintStudioFrame", "studio"),
    "portable_web_export_plugin": ("ui", "PortableWebExportFrame", "path"),
    "suite_assistant_plugin": ("gui", "AssistantFrame", "assistant"),
    "embed_3d_plugin": ("ui", "EmbedDialog", "embed"),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classify(returncode, state, timed_out=False):
    if timed_out:
        return "timeout"
    if returncode and (returncode < 0 or returncode & 0x80000000):
        return "native_exit"
    if state.get("status") in ("dependency_failure", "python_error"):
        return state["status"]
    if returncode == 0 and state.get("stage") == "completed":
        return "passed"
    return "incomplete" if returncode == 0 else "python_error"


def child(args):
    # Only the owned child suppresses OS crash dialogs. Never change the host.
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
        ctypes.windll.kernel32.WerSetFlags(0x0004)
    import faulthandler
    faulthandler.enable()
    state = {"plugin": args.child, "status": "running", "stage": "starting", "events": []}
    def record(stage, **values):
        state.update(stage=stage, **values)
        state["events"].append({"stage": stage, "attempt": state.get("attempt")})
        args.state.write_text(json.dumps(state, indent=2), encoding="utf-8")
    try:
        record("import_native", python=sys.version, executable=sys.executable)
        import pcbnew
        import wx
        module, name, kind = TARGETS[args.child]
        record("load_board", kicad=pcbnew.Version(), wx=wx.version())
        app = None
        if args.load_order == "app-first":
            app = wx.App(False)
        needs_board = kind in {"board", "saved", "selection", "embed"}
        board = pcbnew.LoadBoard(str(args.board)) if needs_board else None
        if needs_board and board is None:
            raise RuntimeError("LoadBoard returned no board")
        app = app or wx.App.Get() or wx.App(False)
        app.SetExitOnFrameDelete(False)
        pcbnew.GetBoard = lambda: board
        def refused(*unused, **kwargs):
            raise RuntimeError("PCB writes are forbidden during lifecycle audit")
        pcbnew.SaveBoard = refused
        pcbnew.BOARD.Save = refused
        def message(message, *unused, **kwargs):
            raise RuntimeError("Plugin requested a message box: " + str(message))
        wx.MessageBox = message
        source = args.source
        state["load_order"] = args.load_order if needs_board else "no_native_board_preload"
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(source))
        if kind == "mechanical":
            sys.path.insert(0, str(source / "src"))
            target = importlib.import_module(module)
        else:
            package = "wayricad_lifecycle_probe"
            namespace = types.ModuleType(package)
            namespace.__package__ = package
            namespace.__path__ = [str(source)]
            sys.modules[package] = namespace
            parts = module.split(".")
            for depth in range(1, len(parts)):
                parent = package + "." + ".".join(parts[:depth])
                namespace = types.ModuleType(parent)
                namespace.__path__ = [str(source.joinpath(*parts[:depth]))]
                namespace.__package__ = parent
                sys.modules[parent] = namespace
            record("import_plugin")
            target = importlib.import_module("." + module, package)
        state["module_path"] = str(Path(target.__file__).resolve())
        state["module_sha256"] = digest(target.__file__)
        window_type = getattr(target, name)
        windows = []
        errors = []
        def callback_error(exc_type, value, tb):
            errors.append(str(value))
            traceback.print_exception(exc_type, value, tb)
            record("callback_error", status="python_error", error=str(value))
            app.ExitMainLoop()
        sys.excepthook = callback_error
        for attempt in (1, 2):
            record("construct", attempt=attempt)
            if kind == "path":
                frame = window_type(None, args.board)
            elif kind == "mechanical":
                frame = window_type(board_path=args.board)
            elif kind == "selection":
                frame = window_type(None, [])
            elif kind == "empty":
                frame = window_type(None)
            elif kind == "studio":
                frame = window_type(None, board_path=str(args.board), board=board)
            elif kind == "assistant":
                frame = window_type(None, board=args.board, output_root=args.state.parent / "assistant-results")
            elif kind == "embed":
                bridge = importlib.import_module(".native", package).NativeBridge(pcbnew)
                frame = window_type(None, bridge)
            else:
                frame = window_type(None, board, **({"saved_board": True} if kind == "saved" else {}))
            windows.append(frame)
            if kind != "embed":
                frame.Show()
                record("shown", title=frame.GetTitle())
            def close():
                if not frame.IsShown():
                    raise RuntimeError("Window is not shown")
                record("closing")
                frame.Close()
                if kind == "embed":
                    return
                if isinstance(frame, wx.Dialog) and frame:
                    frame.Destroy()
                # Analysis windows can veto close until their worker cancels.
                # Wait for actual destruction; the parent bounds this wait.
                def closed():
                    if not frame:
                        app.ExitMainLoop()
                    else:
                        wx.CallLater(100, closed)
                wx.CallLater(100, closed)
            timer = wx.CallLater(900, close)
            if kind == "embed":
                record("show_modal", title=frame.GetTitle())
                frame.ShowModal()
            else:
                app.MainLoop()
            timer.Stop()
            if errors:
                raise RuntimeError("wx callback failed: " + errors[-1])
            if frame and frame.IsShown():
                raise RuntimeError("Window remained visible after close")
            if frame:
                frame.Destroy()
            record("closed")
        record("completed", status="completed")
        return 0
    except BaseException as exc:
        status = "dependency_failure" if isinstance(exc, (ModuleNotFoundError, ImportError)) else "python_error"
        record("exception", status=status, error=f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--board", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--site-packages", type=Path)
    parser.add_argument("--installed-root", type=Path)
    parser.add_argument("--plugins", nargs="+", choices=TARGETS, default=list(TARGETS))
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--load-order", choices=("board-first", "app-first"), default="board-first")
    parser.add_argument("--child", choices=TARGETS, help=argparse.SUPPRESS)
    parser.add_argument("--source", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--state", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.board = args.board.resolve(strict=True)
    if args.child:
        return child(args)
    if not args.python or not args.output or not 1 <= args.timeout <= 30:
        parser.error("Supply --python and --output, with --timeout between 1 and 30 seconds")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", PYTHONUTF8="1")
    for key in ("TEMP", "TMP", "MPLCONFIGDIR", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
        directory = args.output / key.lower()
        directory.mkdir()
        environment[key] = str(directory)
    if args.site_packages:
        environment["PYTHONPATH"] = str(args.site_packages.resolve())
    before = digest(args.board)
    results = []
    for plugin in args.plugins:
        manifest = json.loads((ROOT / plugin / "plugin.json").read_text(encoding="utf-8"))
        source = args.installed_root / manifest["identifier"].replace(".", "_") if args.installed_root else ROOT / plugin
        state_path = args.output / (plugin + ".json")
        command = [str(args.python), "-B", str(Path(__file__).resolve()), "--child", plugin,
                   "--board", str(args.board), "--source", str(source), "--state", str(state_path),
                   "--load-order", args.load_order]
        start = time.monotonic()
        timed_out = False
        with (args.output / (plugin + ".stdout.log")).open("wb") as stdout, (args.output / (plugin + ".stderr.log")).open("wb") as stderr:
            process = subprocess.Popen(command, env=environment, cwd=args.output, stdout=stdout, stderr=stderr,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                code = process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                else:
                    process.kill()
                code = process.wait()
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        after = digest(args.board)
        result = dict(plugin=plugin, identifier=manifest["identifier"], source=str(source),
                      manifest_sha256=digest(source / "plugin.json"),
                      status=classify(code, state, timed_out), returncode=code,
                      exit_hex=f"0x{code & 0xffffffff:08X}", seconds=round(time.monotonic()-start, 2),
                      state=state, board_sha256_before=before, board_sha256_after=after)
        if before != after:
            result["status"] = "board_changed"
        results.append(result)
        (args.output / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(plugin, result["status"], result["exit_hex"], state.get("stage"), flush=True)
        if before != after:
            break
    return 0 if all(row["status"] == "passed" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
