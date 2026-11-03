"""Bounded saved-net route suggestions; no component model or copper solve."""
from __future__ import annotations

from collections import deque
from itertools import combinations
import re


def board_inventory(board):
    """Read native saved-board pad identities without changing the design."""
    rows = []
    for footprint in board.GetFootprints():
        owner, ref = footprint.m_Uuid.AsString(), str(footprint.GetReference())
        for pad in footprint.Pads():
            if pad.GetNetCode() <= 0:
                continue
            number = str(pad.GetNumber())
            rows.append(dict(id=pad.m_Uuid.AsString(), footprint_uuid=owner,
                             reference=ref, pad_number=number, label=ref + '.' + number,
                             net=str(pad.GetNetname()), component_value=str(footprint.GetValue())))
    return dict(terminals=rows, nets=sorted({row['net'] for row in rows}))


def infer_series_paths(inventory, source, sink, *, include_unknown=False,
                       max_routes=24, max_stages=16, max_expansions=5000):
    """Suggest net chains and parallel devices for explicit electrical review.

    A component spanning two nets is only a possible current path. Multipin
    devices may expose control pins; all proposed and excluded pins are retained
    for review. Capacitors, connectors, ICs and unrecognised references are omitted
    by default. This does not establish connected copper, device state or bias.
    """
    if not 1 <= max_routes <= 128 or not 1 <= max_stages <= 128 or not 1 <= max_expansions <= 50000:
        raise ValueError('Choose bounded route, stage and search limits.')
    rows = inventory.get('terminals', [])
    ids = [row.get('id') for row in rows]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError('Path discovery needs unique saved pad identities.')
    def resolve(value):
        matches = [row for row in rows if value in (row['id'], row.get('label'))]
        if len(matches) != 1 or not matches[0].get('net'):
            raise ValueError('Choose one unambiguous assigned source and sink pad.')
        return matches[0]
    start, end = resolve(source), resolve(sink)
    if start['id'] == end['id']:
        raise ValueError('Source and sink must be different pads.')
    grouped = {}
    for row in rows:
        if row.get('footprint_uuid'):
            grouped.setdefault(row['footprint_uuid'], []).append(row)
    endpoint_owners = {start.get('footprint_uuid'), end.get('footprint_uuid')}
    pairs, omitted = {}, []
    def pin_order(row):
        return (str(row.get('pad_number', row.get('label', ''))), str(row['id']))
    for owner, pads in sorted(grouped.items()):
        if owner in endpoint_owners:
            continue
        refs = {str(row.get('reference', row.get('label', '').rsplit('.', 1)[0])) for row in pads}
        if len(refs) != 1:
            raise ValueError('A footprint has inconsistent reference identity.')
        ref = next(iter(refs))
        if not include_unknown and not re.fullmatch(r'(?:R|L|FB|F|D|Q|SW|NT)\d+', ref, re.I):
            omitted.append(ref)
            continue
        nets = sorted({row['net'] for row in pads if row.get('net')})
        # Large multifunction parts cannot create an unbounded pair graph.
        if len(nets) > 12:
            omitted.append(ref)
            continue
        for left, right in combinations(nets, 2):
            incoming = sorted((row for row in pads if row.get('net') == left), key=pin_order)
            outgoing = sorted((row for row in pads if row.get('net') == right), key=pin_order)
            pairs.setdefault((left, right), []).append(dict(
                reference=ref, footprint_uuid=owner,
                from_pads=[row['id'] for row in incoming], to_pads=[row['id'] for row in outgoing],
                excluded_pads=[row['id'] for row in sorted(pads, key=pin_order)
                               if row.get('net') not in (left, right)],
                component_value=str(pads[0].get('component_value', ''))))
    graph = {}
    for left, right in pairs:
        graph.setdefault(left, []).append(right)
        graph.setdefault(right, []).append(left)
    queue = deque([([start['net']], [], set())])
    routes, expansions, truncated = [], 0, False
    while queue:
        nets, stages, used = queue.popleft()
        if nets[-1] == end['net']:
            routes.append(dict(nets=nets, stages=stages))
            if len(routes) >= max_routes:
                truncated = bool(queue)
                break
            continue
        if len(stages) >= max_stages:
            truncated = True
            continue
        for other in sorted(graph.get(nets[-1], [])):
            if other in nets:
                continue
            expansions += 1
            if expansions > max_expansions:
                truncated = True
                queue.clear()
                break
            left, right = sorted((nets[-1], other))
            parts = []
            for original in sorted(pairs[(left, right)], key=lambda p: (p['reference'], p['footprint_uuid'])):
                if original['footprint_uuid'] in used:
                    continue
                part = dict(original)
                if nets[-1] != left:
                    part['from_pads'], part['to_pads'] = part['to_pads'], part['from_pads']
                parts.append(part)
            if parts:
                # A footprint proposed in this parallel bank cannot recur later.
                queue.append(([*nets, other], [*stages, dict(from_net=nets[-1], to_net=other, parts=parts)],
                              used | {part['footprint_uuid'] for part in parts}))
    def group(row):
        return [row['id'], *[p['id'] for p in sorted(rows, key=pin_order)
                            if p['id'] != row['id'] and row.get('footprint_uuid')
                            and p.get('footprint_uuid') == row['footprint_uuid'] and p.get('net') == row['net']]]
    return dict(schema='wayricad.series-candidates/v1', source=start['id'], sink=end['id'],
                source_terminals=group(start), sink_terminals=group(end), routes=routes,
                truncated=truncated, omitted_references=sorted(set(omitted)),
                source_sha256=inventory.get('source_sha256'),
                notice='Saved-net suggestions only. Review current pins, excluded pins, parallel parts and device state; enter explicit component models. Copper continuity is checked when solving.')
