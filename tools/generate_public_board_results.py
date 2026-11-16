"""Generate revision-bound public-board studies without editing their PCBs.

Run with KiCad Python and the existing scientific dependencies. The checked-in
study specification names exact public hosted board bytes, not local projects.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT = ROOT / 'docs/examples/public-boards'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def checked_board(root, spec):
    """Reject traversal and changed inputs before any native code runs."""
    root = Path(root).resolve()
    path = (root / spec['filename']).resolve()
    if path.parent != root or path.suffix != '.kicad_pcb':
        raise ValueError('Board must be one named PCB in the declared input directory.')
    expected = spec['sha256']
    if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
        raise ValueError('A pinned board SHA-256 is required.')
    if sha(path) != expected:
        raise ValueError('Public board fingerprint mismatch: ' + path.name)
    return path


def snapshots(path):
    return {p.name: sha(p) if p.is_file() else None for p in
            (path, path.with_suffix('.kicad_pro'), path.with_suffix('.kicad_dru'))}


def run_case(case, board):
    request = dict(case['request'], board_path=str(board))
    kind = case['kind']
    if kind == 'quick-pi':
        from quick_pi_plugin.service import execute
        return execute(request), 'Quick PI', 'quick_pi_plugin', {
            'points_mm': 'mm', 'potential_V': 'V', 'cell_power_W': 'W',
            'cell_J_A_mm2': 'A/mm2'}, 'front-depth'
    if kind == 'quick-si':
        from signal_integrity_advisor_plugin.service import execute, source_fingerprints
        request['source_fingerprints'] = source_fingerprints(board)
        return execute(request)['report'], 'Quick SI', 'signal_integrity_advisor_plugin', {
            'length_mm': 'mm', 'delay_ns': 'ns', 'z0_ohm': 'ohm'}, None
    if kind == 'quick-therm':
        from quick_therm_plugin.service import execute
        request['expected_source_sha256'] = sha(board)
        return execute(request), 'QuickTherm', 'quick_therm_plugin', {
            'x_centers_mm': 'mm', 'y_centers_mm': 'mm',
            'values_c': 'degC', 'power_w': 'W'}, 'front-depth'
    raise ValueError('Unsupported public example kind: ' + str(kind))


def numerical_summary(kind, bundle):
    if kind == 'quick-pi':
        result = bundle['result']
        return {key: result[key] for key in ('voltage_drop_V', 'drop_over_current_ohm',
            'total_power_W', 'current_balance_error_A', 'energy_relative_error',
            'floating_nodes', 'floating_triangles')}
    if kind == 'quick-therm':
        result = bundle['thermal_network']
        return dict(status=result['status'], heat_balance=result['heat_balance'],
            layer_ranges=[{key: row[key] for key in ('name', 'sampled_min_c', 'sampled_max_c')}
                          for row in result['layers']])
    return {key: bundle.get(key) for key in ('status', 'delay_ns', 'z0_ohm', 'blockers')} | {
        'eye_status': bundle.get('eye', {}).get('status'),
        'eye_limitations': bundle.get('eye', {}).get('blockers', [])}


def generate(board_root, output, specification, selected=None):
    import pcbnew
    from wayricad_runtime.pocket_kivi_export import portable_json
    from wayricad_runtime.pocket_report import evidence_context
    from wayricad_runtime.report_ui import publish_documents
    spec = json.loads(Path(specification).read_text(encoding='utf-8-sig'))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    boards = {b['id']: b for b in spec['boards']}
    cases = spec['cases']
    if selected:
        unknown = set(selected) - {c['id'] for c in cases}
        if unknown:
            raise ValueError('Unknown case IDs: ' + ', '.join(sorted(unknown)))
        cases = [c for c in cases if c['id'] in selected]
    # Validate all selected board inputs before publishing any result.
    paths = {key: checked_board(board_root, boards[key]) for key in
             {c['board_id'] for c in cases}}
    inputs = {key: snapshots(path) for key, path in paths.items()}
    specification_hash = sha(specification)
    from tools.generate_pocket_kivi_examples import MODULES, source_sha
    producer_modules = {name: source_sha(ROOT / name) for name in MODULES}
    generator_hash = source_sha(__file__)
    rows, documents = [], {}

    def guard():
        if any(snapshots(paths[key]) != value for key, value in inputs.items()):
            raise ValueError('Saved inputs changed during collection generation.')
        if sha(specification) != specification_hash or source_sha(__file__) != generator_hash:
            raise ValueError('Study specification or generator changed during generation.')
        if any(source_sha(ROOT / name) != value for name, value in producer_modules.items()):
            raise ValueError('Producer source changed during generation; rerun.')
    for case in cases:
        if not re.fullmatch('[a-z0-9-]+', case['id']):
            raise ValueError('Invalid case ID.')
        board = paths[case['board_id']]
        before = snapshots(board)
        started = time.monotonic()
        print('Running ' + case['id'], flush=True)
        bundle, tool, package, units, z_basis = run_case(case, board)
        if snapshots(board) != before:
            raise ValueError('Producer changed saved input bytes: ' + board.name)
        if any(source_sha(ROOT / name) != digest for name, digest in producer_modules.items()):
            raise ValueError('Producer source changed during generation; rerun.')
        context = evidence_context(bundle, tool=tool, package=package,
            board_path=board, units=units, z_basis=z_basis,
            coordinate_frame=None if case['kind'] == 'quick-si' else 'KiCad PCB XY in mm')
        payload = portable_json(bundle, **context)
        filename = case['id'] + '.pocket-kivi.json'
        documents[output / filename] = payload
        row = {k: v for k, v in case.items() if k != 'request'}
        row.update(status='computed', result_path=filename,
            source_path='../../public-hardware/' + board.name,
            source_sha256=sha(board), source_bytes=board.stat().st_size,
            result_sha256=hashlib.sha256(payload).hexdigest(), result_bytes=len(payload),
            producer_version=context['version'], elapsed_s=round(time.monotonic() - started, 3),
            request=case['request'], saved_inputs=before)
        row['description'] = row['summary']
        row['summary'] = numerical_summary(case['kind'], bundle)
        rows.append(row)
        receipt = dict(schema='wayricad.public-board-study/v1', generated_at=datetime.now(timezone.utc).isoformat(),
            source_commit=commit, python=sys.version.split()[0], kicad=pcbnew.GetBuildVersion(),
            producer_modules=producer_modules, producer_source_normalization='CRLF to LF only',
            generator_sha256=generator_hash, specification_sha256=specification_hash, case=row)
        documents[output / (case['id'] + '.provenance.json')] = json.dumps(receipt, indent=2, allow_nan=False) + '\n'
        row['provenance_path'] = case['id'] + '.provenance.json'
        print(json.dumps({k: row[k] for k in ('id', 'result_bytes', 'elapsed_s')}), flush=True)
    manifest = dict(schema='wayricad.integration-gallery/v1', source_commit=commit,
        producer_version=rows[0]['producer_version'] if rows else None,
        generated_at=datetime.now(timezone.utc).isoformat(), boards=spec['boards'], cases=rows)
    documents[output / 'manifest.json'] = json.dumps(manifest, indent=2, allow_nan=False) + '\n'
    publish_documents(documents, sources=[specification, *paths.values()], source_guard=guard)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=DEFAULT)
    parser.add_argument('--specification', type=Path, default=DEFAULT / 'studies.json')
    parser.add_argument('--case', action='append', dest='selected')
    args = parser.parse_args()
    generate(args.board_root, args.output, args.specification, args.selected)


if __name__ == '__main__':
    main()
