"""Whole-net routing coverage needed before exporting a point-to-point circuit."""
from __future__ import annotations

from collections import defaultdict
import math


def circuit_topology(board, path, terminal_count):
    """Check that the screened path accounts for all routing on its signal net.

    This is a routing-inventory check, not an electromagnetic model. Native
    track lengths are compared with the ordered path sections, so a reused item
    UUID alone cannot hide an unmodeled piece of copper. Zones cannot establish
    a unique one-dimensional channel and remain unsupported here.
    """
    answer = {'complete': False, 'branch_count': None, 'stub_count': None,
              'unmodeled_item_uuids': [], 'length_mismatches': [],
              'scope': 'Whole selected signal-net routing inventory', 'notes': []}
    if terminal_count != 2:
        answer['notes'].append('A circuit export requires exactly two signal pads; other loads need an explicit branched circuit.')
        return answer
    if path.status not in ('ok', 'partial') or not path.segments:
        answer['notes'].append('The endpoint route is disconnected or has no resolved sections.')
        return answer
    represented = defaultdict(float)
    kinds = defaultdict(set)
    for section in path.segments:
        identifier = section.get('item_uuid')
        length = section.get('length_mm')
        if (not identifier or isinstance(length, bool) or not isinstance(length, (int, float))
                or not math.isfinite(length) or length < 0):
            answer['notes'].append('A routed section has no exact item identity or valid length.')
            return answer
        represented[identifier] += length
        kinds[identifier].add(section.get('kind'))
    try:
        inventory = {}
        for item in board.GetTracks():
            if str(item.GetNetname()) != path.net_name:
                continue
            identifier = str(item.m_Uuid.AsString())
            if not identifier or identifier in inventory:
                raise ValueError('Duplicate or missing copper item UUID.')
            inventory[identifier] = item
        for zone in board.Zones():
            if str(zone.GetNetname()) == path.net_name:
                answer['notes'].append('Filled-zone paths require a field or reviewed multi-terminal equivalent circuit.')
                return answer
        answer['unmodeled_item_uuids'] = sorted(set(inventory) ^ set(represented))
        for identifier, item in inventory.items():
            if identifier not in represented:
                continue
            native_kind=item.GetClass()
            expected={'via'} if native_kind=='PCB_VIA' else {'track'} if native_kind in ('PCB_TRACK','PCB_ARC') else None
            if expected is None or kinds[identifier]!=expected:
                raise ValueError('A section kind differs from its native copper item: '+identifier)
            if native_kind=='PCB_VIA':continue
            length = float(item.GetLength()) / 1e6
            if not math.isfinite(length) or length <= 0:
                raise ValueError('A track has no finite native length.')
            # Arc chords have a bounded discretization error; straight tracks
            # retain a one-micrometre absolute tolerance only.
            arc = native_kind == 'PCB_ARC'
            tolerance = max(.001, length * .002) if arc else .001
            if abs(length - represented[identifier]) > tolerance:
                answer['length_mismatches'].append(
                    {'item_uuid': identifier, 'native_length_mm': length,
                     'represented_length_mm': represented[identifier],
                     'tolerance_mm': tolerance})
        if answer['unmodeled_item_uuids'] or answer['length_mismatches']:
            answer['notes'].append('Unmodeled routing, branches, loops or stubs remain; choose an unbranched complete channel.')
            return answer
    except (AttributeError, TypeError, ValueError, RuntimeError) as error:
        answer['notes'].append('Whole-net topology is unverified: ' + str(error))
        return answer
    answer.update(complete=True, branch_count=0, stub_count=0,
                  routing_item_count=len(inventory))
    return answer
