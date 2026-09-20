"""Read-only native-board capability benchmark; execution is not design acceptance.

Run with KiCad Python. Corpus/downloads and detailed output belong in .validation.
Each board/operation gets a fresh process and a wall-clock timeout. No external
corpus code is imported. Inputs are hashed before and after the complete run.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OPERATIONS = ('inventory', 'si', 'pi', 'decoupling', 'return_path', 'manufacturing')
RAILS = '+*,VCC*,VDD*,VBUS*,VIN*,*3V3*,*5V*,*12V*'
GROUNDS = 'GND,*GND*,VSS'
ENGINE_DIRS = ('quick_pi_plugin', 'signal_integrity_advisor_plugin', 'trace_impedance_plugin',
               'manufacturing_readiness_plugin', 'wayricad_runtime')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def engine_snapshot():
    return {p.relative_to(ROOT).as_posix(): digest(p) for directory in ENGINE_DIRS
            for p in sorted((ROOT/directory).rglob('*.py')) if 'tests' not in p.relative_to(ROOT).parts}


def dump(path, data):
    def encode(value):
        if is_dataclass(value):
            return asdict(value)
        raise TypeError(type(value).__name__)
    path.write_text(json.dumps(data, indent=2, default=encode, allow_nan=False) + '\n', encoding='utf-8')


def candidates(board, p):
    pads = defaultdict(list)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() > 0:
                pads[str(pad.GetNetname())].append((f'{fp.GetReference()}.{pad.GetNumber()}', pad))
    counts = Counter(str(t.GetNetname()) for t in board.GetTracks())
    result = []
    for net, terminals in pads.items():
        # Duplicate labels cannot safely identify an electrode through the public API.
        if len(terminals) < 2 or not counts[net] or len({a for a, _ in terminals}) != len(terminals):
            continue
        terminals.sort(key=lambda item: item[0])
        first = terminals[0]
        last = max(terminals[1:], key=lambda item: (item[1].GetPosition()-first[1].GetPosition()).SquaredEuclideanNorm())
        result.append({'net': net, 'start': first[0], 'end': last[0],
                       'terminals': len(terminals), 'tracks_and_vias': counts[net],
                       'power_named': bool(re.search(r'(^[+]|VCC|VDD|VBUS|VIN|3V3|5V|12V)', net, re.I)),
                       'ground_named': bool(re.search(r'GND|VSS', net, re.I)),
                       'signal_named': bool(re.search(r'CLK|USB|TX|RX|SCL|SDA|MOSI|MISO|SCK|CAN|ETH', net, re.I))})
    return sorted(result, key=lambda row: (not row['signal_named'], row['terminals'] != 2,
                                          row['tracks_and_vias'], row['net']))


def operation(args):
    import pcbnew as p
    import wx
    # KiCad's wx log target can open a modal dialog for a nonfatal load warning.
    # This is a headless benchmark; errors still arrive through LoadBoard/throws.
    wx.Log.EnableLogging(False)
    p.ActionPlugin.register = lambda self: None
    boardfile = Path(args.board)
    board = p.LoadBoard(str(boardfile))
    if board is None:
        raise ValueError('KiCad did not load the board')
    selected = candidates(board, p)
    if args.worker == 'inventory':
        text = boardfile.read_text(encoding='utf-8-sig')
        return {'status': 'COMPLETED', 'footprints': len(list(board.GetFootprints())),
                'tracks_and_vias': len(list(board.GetTracks())), 'zones': len(list(board.Zones())),
                'layers': board.GetCopperLayerCount(), 'explicit_stackup': '(stackup' in text,
                'candidates': selected}
    if args.worker == 'si':
        from signal_integrity_advisor_plugin.quick_si import analyze
        from trace_impedance_plugin.frequency_analysis import sweep
        rows = []
        for candidate in [c for c in selected if not c['ground_named']][:args.paths]:
            try:
                report, path = analyze(board, candidate['net'], candidate['start'], candidate['end'],
                                       'Auto', rise_ns=1., frequency_mhz=100., source_ohm=20.)
                try:
                    report['frequency_sweep'] = sweep(path.as_report(), 1., 1000.)
                except ValueError as exc:
                    report['frequency_sweep'] = {'status': 'UNAVAILABLE', 'reason': str(exc)}
                rows.append({'selection': candidate, 'report': report})
            except Exception as exc:
                rows.append({'selection': candidate, 'error': str(exc), 'exception': type(exc).__name__})
        return {'status': 'COMPLETED' if rows else 'NOT_APPLICABLE', 'paths': rows}
    if args.worker == 'pi':
        from quick_pi_plugin.service import execute
        # Keep an authentic power rail when one is available. Fall back explicitly
        # to a small signal-net DC path to exercise the solver, never rename it a rail.
        eligible = [c for c in selected if not c['ground_named']]
        eligible.sort(key=lambda c: (not c['power_named'], c['tracks_and_vias'], c['net']))
        if not eligible:
            return {'status': 'NOT_APPLICABLE', 'reason': 'No routed net with distinct labeled terminals'}
        candidate = eligible[0]
        rows = []
        for edge in args.edges:
            request = {'action': 'solve', 'board_path': str(boardfile), 'net': candidate['net'],
                       'source_terminal': candidate['start'], 'sink_terminal': candidate['end'],
                       'source_voltage': 1., 'sink_current': 1., 'edge_mm': edge, 'plating_mm': .025}
            started = time.perf_counter()
            try:
                bundle = execute(request)
                result = bundle['result']
                rows.append({'edge_mm': edge, 'elapsed_s': time.perf_counter()-started,
                             'nodes': len(bundle['mesh']['points_mm']), 'triangles': len(bundle['mesh']['triangles']),
                             'warnings': bundle['geometry'].get('warnings', []),
                             'metrics': {k: v for k, v in result.items() if not isinstance(v, (list, dict))}})
            except Exception as exc:
                rows.append({'edge_mm': edge, 'elapsed_s': time.perf_counter()-started,
                             'error': str(exc), 'exception': type(exc).__name__})
                break
        solved = [r for r in rows if 'metrics' in r]
        output = {'status': 'COMPLETED' if len(solved) == len(args.edges) else 'BLOCKED',
                  'selection': candidate, 'request': request, 'meshes': rows,
                  'scope': 'Power-like net name; electrical role needs review' if candidate['power_named'] else 'Signal-net DC path; not rail coverage'}
        if len(solved) > 1:
            a, b = (r['metrics']['drop_over_current_ohm'] for r in solved[-2:])
            output['last_refinement_relative_R_change'] = abs(a-b)/abs(b) if b else None
        return output
    if args.worker == 'decoupling':
        from quick_pi_plugin.decoupling.analysis import PadNode, analyze_decoupling
        pads = [PadNode(fp.GetReference(), pad.GetNumber(), str(pad.GetNetname()),
                        p.ToMM(pad.GetPosition().x), p.ToMM(pad.GetPosition().y), fp.GetValue())
                for fp in board.GetFootprints() for pad in fp.Pads() if pad.GetNetCode() > 0]
        findings = analyze_decoupling(pads, RAILS, GROUNDS)
        return {'status': 'COMPLETED' if findings else 'NOT_APPLICABLE', 'findings': findings,
                'assumptions': {'rails': RAILS, 'grounds': GROUNDS, 'loads': 'U*', 'capacitors': 'C*', 'distance_mm': 3.}}
    if args.worker == 'return_path':
        from signal_integrity_advisor_plugin.return_path.analysis import collect_board_geometry, ReturnPathAnalyzer
        segments, vias, regions = collect_board_geometry(board)
        if not segments:
            return {'status': 'NOT_APPLICABLE', 'reason': 'No routed segments'}
        result = ReturnPathAnalyzer(GROUNDS.split(',')).audit(segments, vias, regions,
                    layer_order=[str(board.GetLayerName(layer)) for layer in board.GetEnabledLayers().CuStack()])
        return {'status': 'COMPLETED', 'segments': len(segments), 'vias': len(vias),
                'filled_reference_regions': len(regions), 'findings': result.findings}
    if args.worker == 'manufacturing':
        from manufacturing_readiness_plugin.analysis import saved_metrics, audit_metrics, FabricatorProfile
        project = boardfile.with_suffix('.kicad_pro')
        if not project.is_file():
            return {'status': 'BLOCKED', 'reason': 'No matching saved .kicad_pro; clearance rule cannot be established'}
        metrics = saved_metrics(boardfile.read_bytes(), project.read_bytes())
        return {'status': 'COMPLETED', 'profile': asdict(FabricatorProfile()),
                'checks': audit_metrics(metrics, FabricatorProfile()), 'scope': 'Saved feature/rule minima; no clearance DRC'}


def worker(args):
    started = time.perf_counter()
    try:
        result = operation(args)
    except Exception as exc:
        traceback.print_exc()
        result = {'status': 'ERROR', 'exception': type(exc).__name__, 'error': str(exc)}
    result['elapsed_s'] = time.perf_counter()-started
    dump(Path(args.output), result)


def run_one(args, board, op, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), '--worker', op, '--board', str(board),
               '--output', str(target), '--paths', str(args.paths), '--edges', *map(str, args.edges)]
    started = time.perf_counter()
    with target.with_suffix('.log').open('w', encoding='utf-8') as log:
        try:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if target.exists() and process.returncode == 0:
                result = json.loads(target.read_text(encoding='utf-8'))
            else:
                result = {'status': 'CRASH', 'exit_code': process.returncode}
        except subprocess.TimeoutExpired:
            result = {'status': 'TIMEOUT', 'budget_s': args.timeout}
    result['wall_s'] = time.perf_counter()-started
    dump(target, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--operations', nargs='+', choices=OPERATIONS, default=list(OPERATIONS))
    parser.add_argument('--timeout', type=float, default=60.)
    parser.add_argument('--paths', type=int, default=3)
    parser.add_argument('--edges', nargs='+', type=float, default=[1., .5])
    parser.add_argument('--match', default='', help='Filter corpus-relative board path substring')
    parser.add_argument('--board-list', type=Path, help='JSON list of corpus-relative PCB paths to include')
    parser.add_argument('--worker', choices=OPERATIONS)
    parser.add_argument('--board')
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    if args.corpus is None:
        parser.error('--corpus is required')
    if args.timeout <= 0 or args.paths < 1 or not args.edges or any(edge <= 0 for edge in args.edges):
        parser.error('Timeout, path count and mesh edges must be positive')
    corpus = args.corpus.resolve()
    output = args.output.resolve()
    if output == corpus or corpus in output.parents:
        parser.error('Output must be outside the input corpus')
    if output.exists() and any(output.iterdir()):
        parser.error('Use a fresh output directory to avoid mixing benchmark runs')
    output.mkdir(parents=True, exist_ok=True)
    sources = {str(p.relative_to(corpus)): digest(p) for p in sorted(corpus.rglob('*'))
               if p.is_file() and p.suffix in ('.kicad_pcb', '.kicad_pro', '.kicad_sch')}
    dump(output/'source-manifest.json', sources)
    import pcbnew, numpy, scipy, vtk
    summary = {'schema': 'wayricad.corpus-benchmark/v1', 'corpus': str(corpus),
               'engine_files_before': engine_snapshot(),
               'environment': {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(),
                               'kicad': pcbnew.Version(), 'numpy': numpy.__version__, 'scipy': scipy.__version__, 'vtk': vtk.__version__},
               'settings': {'paths_per_board': args.paths, 'mesh_edges_mm': args.edges, 'timeout_s': args.timeout},
               'interpretation': 'COMPLETED means execution only, not design pass or agreement with an external PI/SI oracle.',
               'boards': [], 'duplicates': []}
    seen = {}
    board_list = None if args.board_list is None else {
        value.replace('\\', '/') for value in json.loads(args.board_list.read_text(encoding='utf-8'))}
    for relative, sha in sources.items():
        if not relative.endswith('.kicad_pcb') or args.match not in relative.replace('\\', '/'):
            continue
        if board_list is not None and relative.replace('\\', '/') not in board_list:
            continue
        if sha in seen:
            summary['duplicates'].append({'path': relative, 'same_as': seen[sha]})
            continue
        seen[sha] = relative
        row = {'path': relative, 'sha256': sha, 'operations': {}}
        for op in args.operations:
            result = run_one(args, corpus/relative, op, output/sha[:12]/f'{op}.json')
            row['operations'][op] = result
            print(f'{relative} | {op}: {result["status"]} ({result["wall_s"]:.2f}s)', flush=True)
        summary['boards'].append(row)
        dump(output/'summary.json', summary)
    after = {str(p.relative_to(corpus)): digest(p) for p in sorted(corpus.rglob('*'))
             if p.is_file() and p.suffix in ('.kicad_pcb', '.kicad_pro', '.kicad_sch')}
    summary['source_files_unchanged'] = sources == after
    summary['engine_files_unchanged'] = summary['engine_files_before'] == engine_snapshot()
    summary['counts'] = {op: dict(Counter(b['operations'][op]['status'] for b in summary['boards'])) for op in args.operations}
    dump(output/'summary.json', summary)
    if not summary['source_files_unchanged']:
        raise RuntimeError('Input files changed during the benchmark')
    if not summary['boards']:
        raise RuntimeError('No PCB inputs matched; no benchmark coverage was produced')


if __name__ == '__main__':
    main()
