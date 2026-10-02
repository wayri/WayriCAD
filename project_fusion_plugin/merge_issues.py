"""Read-only, row-addressable preflight for source-copy merge repairs."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

from . import sexpr as sx
from .board import fp_reference, net_name, net_table
from .model import MergeError
from .schematic import discover, new_uuid
from .variants import set_field


PLACEHOLDER = re.compile(r'^(?:[A-Za-z]+\*+|LOGO\d*|\?+)$', re.I)


def scan_source(spec):
    """Return actionable issues and an exact original-source hash guard.

    This does not run board preparation, which would stop at the first issue.
    A GUI can render every row and pass ``{issue_id: action}`` to repair.
    """
    from .repair import fingerprint

    root = Path(spec.project).with_suffix('.kicad_pro').resolve().parent
    before = fingerprint(root)
    source = discover(spec, new_uuid())
    board = sx.load(source.pcb_file)
    table = net_table(board)
    footprints = sx.children(board, 'footprint')
    counts = Counter(fp_reference(fp) for fp in footprints)
    schematic_refs = {record.old_ref for record in source.symbols}
    used = schematic_refs | {ref for ref in counts if ref and not PLACEHOLDER.fullmatch(ref)}
    next_mech = 1
    issues = []
    for fp in footprints:
        ref = fp_reference(fp)
        uid = sx.value(fp, 'uuid') or sx.value(fp, 'tstamp')
        if not uid:
            raise MergeError(f'{spec.alias}: footprint {ref!r} lacks a UUID; save it in KiCad first.')
        attr = sx.child(fp, 'attr', [])
        board_only = 'board_only' in attr
        path = sx.value(fp, 'path')
        linked = bool(path) and not board_only
        candidate = (not ref or counts[ref] > 1 or (board_only and ref in schematic_refs)
                     or bool(PLACEHOLDER.fullmatch(ref)))
        if candidate:
            netted = any(net_name(pad, table) for pad in sx.children(fp, 'pad'))
            safe = board_only and not linked and not netted
            replacement = None
            if safe:
                while f'MECH{next_mech}' in used:
                    next_mech += 1
                replacement = f'MECH{next_mech}'
                used.add(replacement)
                next_mech += 1
            issues.append({
                'id': f'{spec.alias}:pcb:{uid}', 'source': spec.alias,
                'row': spec.alias, 'reference': ref, 'pcb_uuid': uid,
                'code': 'mechanical_reference' if safe else 'pcb_reference_conflict',
                'error': (f'Board-only footprint {ref!r} needs a unique reference.' if safe else
                          f'Footprint {ref!r} has a missing, duplicate or schematic-linked reference; synchronize it in KiCad.'),
                'action': 'rename_mechanical' if safe else None,
                'suggested_reference': replacement,
            })
    placed = {fp_reference(fp): fp for fp in footprints}
    for ref, fp in placed.items():
        if ref not in schematic_refs:
            continue
        records = [record for record in source.symbols if record.old_ref == ref]
        desired = {sx.propval(record.node, 'Footprint') for record in records}
        if desired == {''}:
            issues.append({
                'id': f'{spec.alias}:footprint:{ref}', 'source': spec.alias,
                'row': spec.alias, 'reference': ref,
                'pcb_uuid': sx.value(fp, 'uuid') or sx.value(fp, 'tstamp'),
                'code': 'blank_variant_footprint',
                'error': f'{ref}: selected variant has a blank footprint; the placed PCB uses {fp[1]!s}.',
                'action': 'retain_placed_footprint', 'suggested_footprint': str(fp[1]),
            })
    if before != fingerprint(root):
        raise MergeError('Source changed during issue scan; save and scan again.')
    return {'source': spec.alias, 'project': str(source.project_file),
            'original_source_hashes': before, 'originalSourceHashes': before,
            'issues': issues}


def validate_resolutions(report, resolutions):
    """Require exact action IDs and refuse unresolved source reference conflicts."""
    issues = report['issues']
    known = {issue['id']: issue for issue in issues}
    if set(resolutions) - set(known):
        raise MergeError('Issue choices are stale or refer to another source; scan again.')
    for issue in issues:
        action = issue['action']
        if action is None:
            raise MergeError(issue['error'])
        if resolutions.get(issue['id']) != action:
            raise MergeError(f"{issue['reference']!r}: review {action.replace('_', ' ')} before repairing this source.")


def apply_to_detached_board(board_file, report, resolutions):
    """Apply only reviewed mechanical renames to a copied PCB file."""
    validate_resolutions(report, resolutions)
    board = sx.load(board_file)
    indexed = {sx.value(fp, 'uuid') or sx.value(fp, 'tstamp'): fp
               for fp in sx.children(board, 'footprint')}
    changed = []
    for issue in report['issues']:
        if issue['action'] != 'rename_mechanical':
            continue
        fp = indexed.get(issue['pcb_uuid'])
        if fp is None or fp_reference(fp) != issue['reference'] or 'board_only' not in sx.child(fp, 'attr', []):
            raise MergeError('Detached PCB differs from the reviewed issue scan; scan again.')
        set_field(fp, 'Reference', issue['suggested_reference'], board=True)
        for label in sx.children(fp, 'fp_text'):
            if len(label) > 2 and label[1] == 'reference':
                label[2] = sx.q(issue['suggested_reference'])
        changed.append({'kind': 'mechanical_reference', 'pcb_uuid': issue['pcb_uuid'],
                        'before': issue['reference'], 'after': issue['suggested_reference']})
    if changed:
        sx.save(board_file, board)
    return changed
