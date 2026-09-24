"""KiCad-Python smoke of the native loading window and first analysis frame.

Usage: python tests/native_analysis_loading_smoke.py BOARD.kicad_pcb trace_impedance_plugin
       python tests/native_analysis_loading_smoke.py BOARD.kicad_pcb signal_integrity_advisor_plugin
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import wx
    from wayricad_runtime import native_analysis

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board', type=Path)
    parser.add_argument('tool', choices=native_analysis.FRAMES)
    args = parser.parse_args()
    board_path = args.board.resolve()
    before = hashlib.sha256(board_path.read_bytes()).hexdigest()
    app = wx.App(False)
    loading = native_analysis._loading_window(wx, args.tool)
    loading.start()
    assert loading.IsShown()
    frame = None

    started = time.perf_counter()
    try:
        _, frame = native_analysis.create_frame(
            ROOT / args.tool, args.tool, board_path,
            status=loading.stage, cancelled=lambda: loading.cancelled)
        frame.Show()
        wx.Yield()
        assert frame.IsShown()
        assert loading.detail.GetLabel() == 'Preparing the analysis window…'
        loading.finish()
        loading = None
        wx.Yield()
        assert not any(' — Loading' in window.GetTitle() for window in wx.GetTopLevelWindows()), \
            'Loading window remained after the analysis frame opened'
        elapsed = time.perf_counter() - started
        assert hashlib.sha256(board_path.read_bytes()).hexdigest() == before
        print(json.dumps({'tool': args.tool, 'first_window_seconds': round(elapsed, 3),
                          'source_unchanged': True}), flush=True)
    finally:
        if frame is not None and frame:
            frame.Close()
            wx.Yield()
            if frame:
                frame.Destroy()
                wx.Yield()
        if loading is not None:
            loading.finish()
            wx.Yield()


if __name__ == '__main__':
    main()
    # The disposable wx host has no PCB Editor event loop. KiCad's bundled wx
    # may assert in ArtProvider during interpreter teardown after all windows
    # are closed; every assertion above has completed and output was flushed.
    os._exit(0)
