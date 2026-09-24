"""Run Trace RLC's saved-board wx workflow with KiCad's bundled Python.

Usage: python native_marble_ui_smoke.py BOARD.kicad_pcb [--installed-root PCM_DIR]
The board is only read; the probe checks its SHA-256 before and after.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
import types


def main() -> None:
    import pcbnew
    import wx

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    parser.add_argument("--installed-root", type=Path)
    parser.add_argument("--net", default="/USB/TxD_OUT")
    parser.add_argument("--start", default="U23.42")
    parser.add_argument("--end", default="U25.8")
    args = parser.parse_args()
    path = args.board.resolve()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    load_started = time.perf_counter()
    board = pcbnew.LoadBoard(str(path))
    load_seconds = time.perf_counter() - load_started
    if board is None:
        raise RuntimeError(f"Cannot load {path}")

    source = Path(__file__).resolve().parents[1]
    if args.installed_root:
        source = args.installed_root.resolve() / "com_github_wayri_wayricad_trace-impedance"
    if not (source / "trace_impedance_plugin.py").is_file():
        raise RuntimeError(f"Trace RLC package missing in {source}")
    sys.path.insert(0, str(source))
    if not args.installed_root:
        sys.path.insert(0, str(source.parent))
    package = "wayricad_rlc_ui_smoke"
    module = types.ModuleType(package)
    module.__path__ = [str(source)]
    module.__package__ = package
    sys.modules[package] = module
    frame_class = importlib.import_module(f"{package}.trace_impedance_plugin").TraceFrame

    app = wx.App(False)
    frame_started = time.perf_counter()
    frame = frame_class(None, board, saved_board=True)
    frame.Show()
    wx.Yield()
    frame_seconds = time.perf_counter() - frame_started
    assert frame.net.SetStringSelection(args.net), f"Net not listed: {args.net}"
    frame._load_pads(None)
    assert frame.start.SetStringSelection(args.start), f"Start pad not listed: {args.start}"
    assert frame.end.SetStringSelection(args.end), f"End pad not listed: {args.end}"
    assert frame.reference.SetStringSelection("In1.Cu")
    analysis_started = time.perf_counter()
    frame.analyze(None)
    wx.Yield()
    analysis_seconds = time.perf_counter() - analysis_started
    result = frame.current
    assert result is not None, "Analyze did not produce a result"
    assert result.net_name == args.net
    assert result.start_pad == args.start and result.end_pad == args.end
    assert result.track_count > 0 and result.via_count > 0
    assert len(result.segments) == frame.sections.GetItemCount() > 0
    assert frame.table.GetItemCount() > 0 and frame.model_table.GetItemCount() > 0
    assert frame.export_button.IsEnabled()
    frame.frequency_panel.run()
    assert frame.frequency_panel.result is not None
    assert len(frame.frequency_panel.result["rows"]) == 41
    assert frame.frequency_panel.export.IsEnabled()
    previous_stackup = frame.engine._stackup_cache
    frame._load_stackup(object())
    assert frame.engine._stackup_cache is not previous_stackup, "Refresh reused the cached stackup"
    assert frame.reference.GetValue() == "In1.Cu", "Refresh discarded the selected reference layer"
    assert frame.current is None and not frame.export_button.IsEnabled(), "Refresh left stale export enabled"
    assert frame.frequency_panel.result is None and not frame.frequency_panel.export.IsEnabled()
    frame.analyze(None)
    assert frame.current is not None and frame.export_button.IsEnabled(), "Cannot reanalyze after stackup refresh"
    frame.frequency.SetValue("250")
    assert frame.current is None and not frame.export_button.IsEnabled(), "Changed input left stale export enabled"
    assert frame.sections.GetItemCount() == frame.table.GetItemCount() == 0
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert after == before, "Saved board changed during read-only UI analysis"
    print(json.dumps({"package": "installed" if args.installed_root else "source",
                      "net": args.net, "status": result.status,
                      "tracks": result.track_count, "vias": result.via_count,
                      "layers": result.layers, "sections": len(result.segments),
                      "load_seconds": round(load_seconds, 3),
                      "first_window_seconds": round(frame_seconds, 3),
                      "analysis_seconds": round(analysis_seconds, 3),
                      "source_unchanged": True}), flush=True)
    frame.Close()
    wx.Yield()
    app.Destroy()


if __name__ == "__main__":
    main()
