"""Conservative copper policy for detached source repair.

A net name is not electrical evidence. Only identical numbered-pad partitions
justify relabelling existing copper. Changed partitions require native review;
this module neither guesses fanout ownership nor deletes routed objects.
"""
from collections import Counter, defaultdict
import copy

from . import sexpr as sx
from .board import fp_reference, net_name, net_table
from .model import MergeError

COPPER = {'segment', 'arc', 'via', 'zone'}
FILL_CACHE = {'filled_polygon', 'fill_segments'}


def copper_items(board):
    # Footprint-owned copper zones require the same proof as board zones.
    items = [item for item in sx.children(board) if sx.tag(item) in COPPER - {'zone'}]
    items.extend(item for item in sx.walk(board) if sx.tag(item) == 'zone')
    return [item for item in items
            if not (sx.tag(item) == 'zone' and sx.child(item, 'keepout') is not None)]


def copper_geometry(board):
    """Identity/geometry invariant excluding only net labels and fill caches."""
    records = []
    for original in copper_items(board):
        item = copy.deepcopy(original)
        for tag in {'net', 'net_name'} | FILL_CACHE:
            sx.remove(item, tag)
        records.append(sx.dumps(item))
    return sorted(records)


class CopperReviewRequired(MergeError):
    def __init__(self, report):
        self.report = report
        details = []
        for entry in report['blocked_nets'][:4]:
            counts = ', '.join(f'{count} {kind}' for kind, count in entry['counts'].items())
            examples = ', '.join(f"{item['kind']} {item['uuid']}" for item in entry['items'][:5])
            pads = ', '.join(f"{p['reference']}.{p['pad']} -> {p['after'] or '(unconnected)'}"
                             for p in entry['changed_pads'][:4])
            details.append(f"{entry['net']!r}: {counts}; UUIDs: {examples}."
                           + (f' Changed pads: {pads}.' if pads else '')
                           + f" {entry['reason']}")
        if len(report['blocked_nets']) > 4:
            details.append(f"And {len(report['blocked_nets']) - 4} additional affected nets.")
        super().__init__('Source repair blocked: copper connectivity needs review. No copper was '
                         'removed and no repair copy will be published.\n' + '\n'.join(details)
                         + '\nRepair only the affected fanout/net connections in a detached KiCad '
                           'source copy, refill and check it, then preview again. Whole-net copper '
                           'deletion is not an automatic repair.')


def inspect_copper(board, schematic, mapping):
    """Return complete item identities without changing any board node."""
    table = net_table(board)
    targets = {pin: name for name, pins in schematic.nets.items() for pin in pins}
    changes = defaultdict(list)
    for fp in sx.children(board, 'footprint'):
        ref = fp_reference(fp)
        for pad in sx.children(fp, 'pad'):
            if not str(pad[1]):
                continue
            old = net_name(pad, table)
            new = targets.get((ref, str(pad[1])), '')
            if old and new != mapping.get(old, old):
                changes[old].append({'reference': ref, 'pad': str(pad[1]),
                                     'before': old, 'after': new})
    blocked = defaultdict(list)
    items = copper_items(board)
    for item in items:
        old = net_name(item, table)
        if old and old not in mapping:
            blocked[old].append({'kind': sx.tag(item),
                                 'uuid': sx.value(item, 'uuid') or sx.value(item, 'tstamp')})
    entries = []
    for name, affected in sorted(blocked.items()):
        affected.sort(key=lambda item: (item['kind'], item['uuid']))
        entries.append({'net': name, 'counts': dict(sorted(Counter(i['kind'] for i in affected).items())),
                        'items': affected, 'changed_pads': changes[name],
                        'reason': 'No unique identical numbered-pad partition proves the target net; '
                                  'it may have split, merged, lost a pin, or lack a pad anchor.'})
    return {'policy': 'preserve_copper_or_block', 'blocked_nets': entries,
            'preserved_copper_counts': dict(sorted(Counter(sx.tag(i) for i in items).items())),
            'removed_copper_count': 0,
            'net_renames': {old: new for old, new in sorted(mapping.items()) if old != new}}


def require_preservable_copper(board, schematic, mapping):
    report = inspect_copper(board, schematic, mapping)
    if report['blocked_nets']:
        raise CopperReviewRequired(report)
    return report


def remap_preserved_copper(board, schematic, mapping, invalidate_fill=False):
    """All-or-nothing relabel; keep IDs, contours, routes and group membership."""
    report = require_preservable_copper(board, schematic, mapping)
    table = net_table(board)
    invalidated = []
    for item in copper_items(board):
        old = net_name(item, table)
        if old in mapping:
            sx.put(item, 'net', sx.q(mapping[old]))
            if sx.tag(item) == 'zone':
                # Modern native serialization uses the quoted net directly.
                sx.remove(item, 'net_name')
        if invalidate_fill and sx.tag(item) == 'zone':
            if any(sx.children(item, tag) for tag in FILL_CACHE):
                invalidated.append(sx.value(item, 'uuid') or sx.value(item, 'tstamp'))
            for tag in FILL_CACHE:
                sx.remove(item, tag)
    report['invalidated_zone_fill_uuids'] = invalidated
    report['zone_refill_required'] = bool(invalidate_fill and any(sx.tag(i) == 'zone' for i in copper_items(board)))
    return report
