"""Measure first-plan fanout performance without changing the supplied board.

Use KiCad's Python. Each trial loads a fresh board and planner; loading and
source-integrity checks are outside planning time. The baseline routing module
comes from a Git revision, while its geometry helpers use the current checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _worker(args):
    import pcbnew
    from wayricad_runtime.geometry import board_fingerprint
    from wayricad_runtime import routing
    if args.worker == 'baseline':
        source = subprocess.check_output(['git', 'show', args.baseline_ref+':wayricad_runtime/routing.py'], cwd=ROOT)
        name = 'wayricad_runtime._fanout_benchmark_baseline'
        routing = types.ModuleType(name)
        routing.__package__ = 'wayricad_runtime'
        sys.modules[name] = routing
        exec(compile(source, '<baseline routing>', 'exec'), routing.__dict__)
    board_path = Path(args.board)
    file_before = hashlib.sha256(board_path.read_bytes()).hexdigest()
    board = pcbnew.LoadBoard(str(board_path))
    before = board_fingerprint(board)
    settings = json.loads(args.settings)
    start = time.perf_counter()
    plans, rejected = routing.plan_fanout(board, pcbnew, settings)
    elapsed = time.perf_counter()-start
    records = []
    for plan in plans:
        row = {}
        for key, value in vars(plan).items():
            if key == 'footprint': value = value.GetReference()
            elif key == 'pad': value = value.GetNumber()
            elif key in ('start', 'end'): value = [value.x, value.y] if value is not None else None
            elif key in ('path', 'connector_region'): value = [[point.x, point.y] for point in value]
            row[key] = value
        records.append(row)
    if before != board_fingerprint(board) or file_before != hashlib.sha256(board_path.read_bytes()).hexdigest():
        raise RuntimeError('Read-only planner changed the source board.')
    payload = json.dumps(dict(plans=records, rejected=rejected), sort_keys=True, separators=(',', ':'))
    print(json.dumps(dict(seconds=elapsed, accepted=len(plans), rejected=len(rejected),
                          result_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                          board_sha256=file_before, source_unchanged=True, kicad=pcbnew.Version())), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', required=True)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--settings', default='{"scope":"Reference wildcard","ref":"U35","pattern":"Radial outward","add_vias":false,"width":0.15,"clearance":0.1}')
    parser.add_argument('--trials', type=int, default=3)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', choices=('baseline', 'candidate'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    if args.worker:
        _worker(args)
        return
    rows = {mode: [] for mode in ('baseline', 'candidate')}
    for _ in range(args.trials):
        for mode in rows:
            command = [sys.executable, str(Path(__file__).resolve()), '--board', args.board,
                       '--baseline-ref', args.baseline_ref, '--settings', args.settings, '--worker', mode]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True, timeout=600)
            rows[mode].append(json.loads(completed.stdout.strip().splitlines()[-1]))
    hashes = {row['result_sha256'] for trials in rows.values() for row in trials}
    if len(hashes) != 1:
        raise RuntimeError('Baseline and candidate differ in exact plans or rejection reasons.')
    result = dict(settings=json.loads(args.settings), trials=rows, exact_equivalence=True,
                  medians={mode: statistics.median(row['seconds'] for row in values) for mode, values in rows.items()})
    result['speedup'] = result['medians']['baseline']/result['medians']['candidate']
    text = json.dumps(result, indent=2)
    if args.output: args.output.write_text(text+'\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
