"""Open, close, and reopen selected KiCad 10 native action windows on a saved test PCB.

This is an opt-in local check. It uses KiCad's bundled Python and wx runtime,
does not enter apply/commit handlers, and compares the saved PCB bytes afterward.
Run with: <KiCad Python> tools/smoke_native_open.py <test.kicad_pcb>
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import argparse
import json
from pathlib import Path
import sys
import types

if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0002)  # Keep owned probe crashes from blocking on an OS dialog.


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    import pcbnew
    import wx

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path, help="Disposable saved test PCB")
    parser.add_argument("--installed-root", type=Path,
                        help="KiCad's 3rdparty/plugins directory; default checks source modules")
    parser.add_argument("--menu", action="store_true",
                        help="Exercise the installed PCM menu bridge, including its delegate Run method")
    options = parser.parse_args(sys.argv[1:] if argv is None else argv)
    path = options.board.resolve()
    if path.suffix.lower() != ".kicad_pcb" or not path.is_file():
        raise SystemExit("Pass a saved .kicad_pcb test board.")
    installed_root = options.installed_root.resolve() if options.installed_root else None
    if options.menu and installed_root is None:
        parser.error("--menu requires --installed-root")
    if installed_root is None:
        sys.path.insert(0, str(ROOT))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    board = pcbnew.LoadBoard(str(path))
    if board is None:
        raise RuntimeError("KiCad could not load the test board")
    app = wx.App.Get() or wx.App(False)
    original_board = pcbnew.GetBoard
    original_message = wx.MessageBox
    original_register = pcbnew.ActionPlugin.register
    pcbnew.GetBoard = lambda: board
    wx.MessageBox = lambda message, *rest, **kwargs: (_ for _ in ()).throw(RuntimeError(str(message)))

    def source_for(folder):
        if installed_root:
            manifest = json.loads((ROOT / folder / "plugin.json").read_text(encoding="utf-8"))
            source = installed_root / manifest["identifier"].replace(".", "_")
            if not (source / "plugin.json").is_file():
                raise RuntimeError(f"Installed package missing: {source}")
            return source
        return ROOT / folder

    def load(folder, module, class_name):
        # Source initializers call ActionPlugin.register(), which requires a
        # running PCB Editor. The installed IPC launcher uses this same light
        # package namespace to import tool modules without that registration.
        source = source_for(folder)
        if installed_root:
            sys.path.insert(0, str(source))
        package = "wayricad_smoke_" + folder
        namespace = types.ModuleType(package)
        namespace.__package__ = package
        namespace.__path__ = [str(source)]
        sys.modules[package] = namespace
        parts = module.split(".")
        for depth in range(1, len(parts)):
            parent_name = package + "." + ".".join(parts[:depth])
            parent = types.ModuleType(parent_name)
            parent.__package__ = parent_name
            parent.__path__ = [str(source / Path(*parts[:depth]))]
            sys.modules[parent_name] = parent
        target = importlib.import_module("." + module, package)
        return getattr(target, class_name)

    def menu_action(folder, title):
        source = source_for(folder)
        sys.path.insert(0, str(source))
        registered = []
        pcbnew.ActionPlugin.register = lambda self: (self.defaults(), registered.append(self))
        try:
            package = "wayricad_menu_smoke_" + folder
            spec = importlib.util.spec_from_file_location(
                package, source / "__init__.py", submodule_search_locations=[str(source)])
            namespace = importlib.util.module_from_spec(spec)
            sys.modules[package] = namespace
            spec.loader.exec_module(namespace)
        finally:
            pcbnew.ActionPlugin.register = original_register
        matches = [action for action in registered if action.name.endswith(title)]
        if len(matches) != 1:
            raise RuntimeError(f"{title}: expected one installed menu action, got {len(matches)}")
        return matches[0]

    BulkLabelEditorPlugin = load("bulk_label_editor_plugin", "bulk_label_editor_plugin", "BulkLabelEditorPlugin")
    FanoutGeneratorPlugin = load("fanout_generator_plugin", "fanout_generator_plugin", "FanoutGeneratorPlugin")
    ViaStitchingPlugin = load("via_stitching_plugin", "via_stitching_plugin", "ViaStitchingPlugin")
    TraceImpedancePlugin = load("trace_impedance_plugin", "trace_impedance_plugin", "TraceImpedancePlugin")
    CopperBalancerDialog = load("copper_balancer_plugin", "copper_balancer.dialog", "CopperBalancerDialog")

    actions = (
        ("Bulk Label Editor", lambda: BulkLabelEditorPlugin(), "action"),
        ("Fanout Generator", lambda: FanoutGeneratorPlugin(), "action"),
        ("Via Stitching", lambda: ViaStitchingPlugin(), "action"),
        ("Trace RLC / Impedance", lambda: TraceImpedancePlugin(), "action"),
        ("Copper Balancer", lambda: CopperBalancerDialog(None, board), "dialog"),
    )
    if options.menu:
        actions = tuple((title, lambda folder=folder, title=title: menu_action(folder, title), "menu")
                        for title, folder in (
                            ("Bulk Label Editor", "bulk_label_editor_plugin"),
                            ("Fanout Generator", "fanout_generator_plugin"),
                            ("Via Stitching", "via_stitching_plugin"),
                            ("Trace RLC / Impedance Analyzer", "trace_impedance_plugin"),
                            ("Copper Balancer", "copper_balancer_plugin"),
                        ))
    try:
        for title, construct, kind in actions:
            action = construct() if kind in ("action", "menu") else None
            for attempt in (1, 2):
                existing = set(wx.GetTopLevelWindows())
                modal_seen = []
                if kind == "menu" and title == "Copper Balancer":
                    def close_modal():
                        for window in wx.GetTopLevelWindows():
                            if window not in existing and isinstance(window, wx.Dialog) and window.IsShown():
                                modal_seen.append(window.GetTitle())
                                window.EndModal(wx.ID_CANCEL)
                    modal_timer = wx.CallLater(300, close_modal)
                if kind in ("action", "menu"):
                    try:
                        action.Run()
                    except BaseException:
                        if kind == "menu" and title == "Copper Balancer":
                            modal_timer.Stop()
                        raise
                else:
                    dialog = construct()
                    dialog.Show()
                wx.Yield()
                windows = [window for window in wx.GetTopLevelWindows()
                           if window not in existing and window.IsShown()]
                if kind == "menu" and title == "Copper Balancer":
                    if not modal_seen:
                        raise RuntimeError(f"{title}: modal window did not open on attempt {attempt}")
                    print(f"{title}: opened and closed attempt {attempt}")
                    continue
                if kind == "dialog" and dialog not in windows:
                    raise RuntimeError(f"{title}: dialog did not open on attempt {attempt}")
                if not windows:
                    raise RuntimeError(f"{title}: no visible window on attempt {attempt}")
                for window in windows:
                    window.Close()
                    wx.Yield()
                    if window:
                        window.Destroy()
                wx.Yield()
                print(f"{title}: opened and closed attempt {attempt}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != before:
                raise RuntimeError(f"{title}: source board changed during read-only launch")
    finally:
        pcbnew.GetBoard = original_board
        wx.MessageBox = original_message
        pcbnew.ActionPlugin.register = original_register
    print("Five native tools opened twice; test board bytes unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
