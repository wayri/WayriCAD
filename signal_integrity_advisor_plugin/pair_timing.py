"""Propagation-only pair matching from explicitly assigned route report snapshots."""
from __future__ import annotations

import math


def _finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def pair_timing(paths, *, frequency_hz=None, reference_group=None):
    """Compare P/N delays and lane mean delays in seconds/degrees.

    Positive skew means N arrives later than P. Phase mismatch is the additional
    N propagation phase, -360*f*(tN-tP), excluding the intended 180-degree
    differential polarity. Inter-pair skew uses the arithmetic mean leg delay,
    not receiver crossing time. Frequency is explicit, never a protocol rate.
    """
    if frequency_hz is not None and (not _finite(frequency_hz) or frequency_hz <= 0):
        raise ValueError('Timing frequency must be finite and positive in Hz.')
    if not isinstance(paths, (list, tuple)) or len(paths) > 64:
        raise ValueError('Pair timing requires at most 64 route reports.')
    if reference_group is not None and (not isinstance(reference_group, str) or not reference_group.strip()):
        raise ValueError('Reference pair group must be a nonempty string.')
    groups = {}
    for index, report in enumerate(paths):
        if not isinstance(report, dict):
            continue
        role, group = report.get('suite_role'), report.get('suite_group')
        if not isinstance(role, str) or not isinstance(group, str) or role.strip().lower() not in ('p', 'n') or not group.strip():
            continue
        groups.setdefault(group.strip(), []).append((index, role.strip().lower(), report))
    if reference_group is not None and reference_group not in groups:
        raise ValueError('Reference pair group is not present in the assigned routes.')
    hashes = {r.get('board_sha256') for r in paths if isinstance(r, dict) and isinstance(r.get('board_sha256'), str) and r.get('board_sha256')}
    identities = {}
    duplicate_indices = set()
    for index, report in enumerate(paths):
        path = report.get('path') if isinstance(report, dict) else None
        if not isinstance(path, dict):
            continue
        values = [path.get(k) for k in ('net_name', 'start_pad', 'end_pad')]
        if not all(isinstance(value, str) and value.strip() for value in values):
            continue
        identity = (values[0], *sorted(values[1:]))
        if identity in identities:
            duplicate_indices.update((index, identities[identity]))
        else:
            identities[identity] = index
    rows = []
    for group, members in sorted(groups.items()):
        row = dict(group=group, status='UNKNOWN', route_indices=[i for i, _, _ in members],
                   p_delay_ns=None, n_delay_ns=None, signed_skew_ps=None, absolute_skew_ps=None,
                   mean_delay_ns=None, phase_mismatch_deg=None, wrapped_phase_mismatch_deg=None,
                   reference_group=None, lane_skew_ps=None, lane_phase_deg=None, evidence=[])
        rows.append(row)
        positives = [r for _, role, r in members if role == 'p']
        negatives = [r for _, role, r in members if role == 'n']
        if len(positives) != 1 or len(negatives) != 1:
            row['evidence'].append('Assign exactly one independent P route and one N route.')
            continue
        p, n = positives[0], negatives[0]
        if any(index in duplicate_indices for index, _, _ in members):
            row['status'] = 'BLOCKED'; row['evidence'].append('Duplicate route snapshots cannot supply independent pair evidence.'); continue
        if len(hashes) > 1:
            row['status'] = 'BLOCKED'; row['evidence'].append('Different saved board revisions cannot be compared.'); continue
        valid = True
        for role, report in (('p', p), ('n', n)):
            path = report.get('path', {})
            delay = report.get('delay_ns')
            source = report.get('delay_source')
            resolved = (report.get('schema') == 'wayricad.quick-si/v1' and
                        report.get('status') in ('SCREENED', 'INCOMPLETE', 'APPROXIMATE') and
                        isinstance(path, dict) and path.get('status') in ('ok', 'partial') and
                        all(isinstance(path.get(k), str) and path[k].strip() for k in ('net_name', 'start_pad', 'end_pad')) and
                        path.get('start_pad') != path.get('end_pad') and
                        _finite(delay) and delay >= 0 and isinstance(source, str) and source.strip() and source != 'unavailable')
            if resolved:
                row[role + '_delay_ns'] = delay
                row['evidence'].append(role.upper() + ': ' + source)
            else:
                valid = False; row['evidence'].append(role.upper() + ': missing resolved delay, endpoints or model provenance.')
        p_path, n_path = p.get('path'), n.get('path')
        if isinstance(p_path, dict) and isinstance(n_path, dict) and p_path.get('net_name') == n_path.get('net_name'):
            valid = False; row['evidence'].append('P and N must be different routed nets.')
        if not valid:
            continue
        # A missing hash cannot establish that two reports describe one revision.
        if any(not isinstance(r.get('board_sha256'), str) or not r['board_sha256'].strip() for r in (p, n)):
            row['evidence'].append('Saved board revision fingerprints are required for pair comparison.'); continue
        skew_ns = row['n_delay_ns'] - row['p_delay_ns']
        if not _finite(skew_ns * 1000):
            raise ValueError('Route delays exceed the finite skew calculation range.')
        row.update(status='ESTIMATED', signed_skew_ps=skew_ns * 1000,
                   absolute_skew_ps=abs(skew_ns) * 1000,
                   mean_delay_ns=row['p_delay_ns']/2 + row['n_delay_ns']/2)
        if frequency_hz is not None:
            phase = -360 * (frequency_hz * 1e-9) * skew_ns
            if not math.isfinite(phase):
                raise ValueError('Frequency and delays exceed the finite phase calculation range.')
            row.update(phase_mismatch_deg=phase, wrapped_phase_mismatch_deg=(phase + 180) % 360 - 180)
    reference = reference_group or next((r['group'] for r in rows if r['status'] == 'ESTIMATED'), None)
    base = next((r for r in rows if r['group'] == reference and r['status'] == 'ESTIMATED'), None)
    for row in rows:
        row['reference_group'] = reference
        if row['status'] == 'ESTIMATED' and base is not None:
            delta = row['mean_delay_ns'] - base['mean_delay_ns']
            if not _finite(delta * 1000):
                raise ValueError('Route delays exceed the finite lane skew calculation range.')
            row['lane_skew_ps'] = delta * 1000
            if frequency_hz is not None:
                phase = -360 * (frequency_hz * 1e-9) * delta
                if not math.isfinite(phase):
                    raise ValueError('Frequency and delays exceed the finite phase calculation range.')
                row['lane_phase_deg'] = phase
    return dict(schema='wayricad.si-pair-timing/v1', frequency_hz=frequency_hz,
                reference_group=reference, pairs=rows,
                conventions='Signed skew = N - P; propagation phase mismatch = -360*f*(tN-tP), excluding intended differential inversion. Lane skew compares mean P/N delays.',
                limitations=['Independent route propagation estimates, not a coupled differential or dispersive phase solution.',
                             'Package, transmitter/receiver, launch, via discontinuity and common-mode conversion delays are not solved.',
                             'Review source-to-receiver direction and model evidence for both legs. Missing evidence remains unknown.',
                             'No protocol phase/skew limit is inferred; compare against explicit engineering budgets.'])
