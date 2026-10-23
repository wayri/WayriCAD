"""Measure a saved-board preview in a fresh KiCad-native Python process.

This read-only microbenchmark measures extraction, offscreen raster work and
exact picking. It does not measure an editor IPC session or a scientific solve.
Run several separate processes before comparing revisions; filesystem caches
are not purged. Reports contain the board basename/hash, not its local path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def measure(board_path, nets, samples=30):
    """Return phase timings without changing the board or its project files."""
    started = time.perf_counter()
    import wx
    import pcbnew
    sys.path.insert(0, str(ROOT))
    from wayricad_runtime.preview import GeometryPreview
    imports = time.perf_counter() - started
    before = hashlib.sha256(board_path.read_bytes()).hexdigest()
    started = time.perf_counter()
    board = pcbnew.LoadBoard(str(board_path))
    load = time.perf_counter() - started
    app = wx.GetApp() or wx.App(False)
    frame = wx.Frame(None, size=(1180, 820))
    view = GeometryPreview(frame, compact=True)
    view.SetSize((1120, 650))
    try:
        started = time.perf_counter()
        view.set_board(board, pcbnew)
        extraction = time.perf_counter() - started
        started = time.perf_counter()
        view._bitmap_for_view()
        initial_raster = time.perf_counter() - started
        available = {row[0] for rows in view._context_identity.values() for row in rows if row[0]}
        chosen = nets or sorted(available)[:2]
        if not chosen or any(net not in available for net in chosen):
            raise ValueError('Choose exact nets that exist in this saved PCB.')
        matches, rasters = [], []
        for net in (chosen * 3):
            started = time.perf_counter()
            view.set_highlight(nets=[net])
            matches.append(time.perf_counter() - started)
            started = time.perf_counter()
            view._bitmap_for_view()
            rasters.append(time.perf_counter() - started)
        started = time.perf_counter()
        view.pick_net((250, 250))
        first_pick = time.perf_counter() - started
        started = time.perf_counter()
        for index in range(samples):
            view.pick_net((250 + index % 30 * 10, 250))
        warm_pick = (time.perf_counter() - started) / samples
        fields = ('context_lines', 'context_pads', 'context_rings', 'context_vias',
                  'footprint_lines', 'references', 'net_targets', '_context_identity')
        geometry = json.dumps({key: getattr(view, key) for key in fields}, sort_keys=True)
        after = hashlib.sha256(board_path.read_bytes()).hexdigest()
        if before != after:
            raise ValueError('Source changed during the benchmark; results are not comparable.')
        return dict(schema='wayricad.preview-benchmark/v1', board=board_path.name,
                    board_sha256=before, geometry_sha256=hashlib.sha256(geometry.encode()).hexdigest(),
                    runtime=sys.version, kicad=pcbnew.GetBuildVersion(), wx=wx.version(),
                    viewport_pixels=[1120, 650], nets=chosen, source_unchanged=True,
                    tracks=len(view.context_lines), pads=len(view.context_pads),
                    vias=len(view.context_vias), selectable_items=len(view.net_targets),
                    imports_s=imports, native_load_s=load, display_extraction_s=extraction,
                    initial_raster_s=initial_raster, highlight_s=matches, selected_raster_s=rasters,
                    repeated_selected_raster_median_s=statistics.median(rasters[1:] or rasters),
                    first_pick_s=first_pick, repeated_pick_mean_s=warm_pick,
                    scope='Fresh-process display benchmark; no OS-cache purge, IPC or solver timing.')
    finally:
        frame.Destroy()
        app.Yield()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path, required=True)
    parser.add_argument('--net', action='append', default=[], help='Exact net; repeat to alternate selections.')
    parser.add_argument('--samples', type=int, default=30)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    board, output = args.board.resolve(), args.output.resolve()
    if not board.is_file() or board.suffix.lower() != '.kicad_pcb':
        parser.error('Choose an existing saved .kicad_pcb file.')
    if output.suffix.lower() != '.json' or output.exists() or output == board:
        parser.error('Choose a new .json report file.')
    if not 1 <= args.samples <= 1000:
        parser.error('Choose 1–1000 pick samples.')
    try:
        result = measure(board, args.net, args.samples)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, ImportError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
