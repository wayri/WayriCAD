"""Deterministic budget screening of existing Quick SI route reports."""
from copy import deepcopy
import math
from .protocol_profiles import get_profile

_BUDGETS = {'max_delay_ns', 'max_skew_ps', 'max_impedance_error_percent', 'max_delay_to_rise_ratio'}


def _number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def screen_suite(profile_id, paths, *, budgets=None):
    """Compare reviewed routes with explicit user budgets; never certify a protocol.

    Each route may declare suite_role (P/N or clock/data) and suite_group.
    Missing roles never imply an ordered pair. Differential impedance cannot be
    inferred from the independent single-ended Quick SI model.
    """
    profile = get_profile(profile_id)
    budgets = dict(budgets or {})
    unknown = set(budgets) - _BUDGETS
    if unknown:
        raise ValueError('Unknown user budget: ' + ', '.join(sorted(unknown)))
    for key, value in budgets.items():
        if not _number(value):
            raise ValueError(key + ' must be a finite nonnegative number.')
    if not isinstance(paths, (list, tuple)):
        raise ValueError('Paths must be a list of Quick SI reports.')
    if len(paths) > 64:
        raise ValueError('At most 64 routes may be screened in one suite.')
    checks = []

    def add(key, status, measured=None, limit=None, unit='', evidence='', **extra):
        checks.append(dict(id=key, status=status, measured=measured, limit=limit,
                           unit=unit, evidence=evidence, **extra))

    def compare(key, measured, budget, unit, evidence):
        limit = budgets.get(budget)
        state = 'UNKNOWN' if measured is None or limit is None else ('WITHIN_BUDGET' if measured <= limit else 'REVIEW')
        add(key, state, measured, limit, unit, evidence + (' Supply user budget ' + budget + '.' if limit is None else ' User budget, not a standards limit.'))

    if profile['topology'] == 'interface-required':
        add('interface', 'BLOCKED', evidence=profile['instructions'])
    if not paths:
        add('routes', 'BLOCKED', evidence='Add reviewed Quick SI routes with source and sink pads.')
    hashes = {p.get('board_sha256') for p in paths if isinstance(p, dict) and isinstance(p.get('board_sha256'), str) and p.get('board_sha256')}
    if len(hashes) > 1:
        add('board_revision', 'BLOCKED', evidence='Routes come from different saved board revisions; rerun them together.')
    valid = []
    identities = set()
    for index, report in enumerate(paths):
        prefix = 'route.%d.' % index
        if not isinstance(report, dict) or report.get('schema') != 'wayricad.quick-si/v1':
            add(prefix + 'report', 'BLOCKED', evidence='Expected a Quick SI v1 report.'); continue
        path = report.get('path')
        if not isinstance(path, dict) or path.get('status') not in ('ok', 'partial') or report.get('status') not in ('SCREENED', 'INCOMPLETE'):
            add(prefix + 'path', 'BLOCKED', evidence='Route is unresolved; choose connected start/end pads.'); continue
        identity = (path.get('net_name'), path.get('start_pad'), path.get('end_pad'))
        if not all(isinstance(value, str) and value.strip() for value in identity):
            add(prefix + 'identity', 'BLOCKED', evidence='Net name, start pad and end pad must be nonempty strings.'); continue
        if identity[1] == identity[2]:
            add(prefix + 'identity', 'BLOCKED', evidence='Source and receiver must be distinct pads.'); continue
        identity = (identity[0], *sorted(identity[1:]))
        if any(key in report and not isinstance(report[key], dict) for key in ('inputs', 'eye')):
            add(prefix + 'schema', 'BLOCKED', evidence='Optional inputs and eye fields must be JSON objects.'); continue
        if 'eye' in report and 'inputs' in report['eye'] and not isinstance(report['eye']['inputs'], dict):
            add(prefix + 'schema', 'BLOCKED', evidence='Eye inputs must be a JSON object.'); continue
        if 'board_sha256' in report and not isinstance(report['board_sha256'], str):
            add(prefix + 'schema', 'BLOCKED', evidence='Board revision hash must be a string.'); continue
        if any(key in report and not isinstance(report[key], str) for key in ('suite_role', 'suite_group')):
            add(prefix + 'schema', 'BLOCKED', evidence='Suite role and group must be strings.'); continue
        if 'segments' in path and (not isinstance(path['segments'], list) or not all(isinstance(s, dict) for s in path['segments'])):
            add(prefix + 'schema', 'BLOCKED', evidence='Path segments must be a list of JSON objects.'); continue
        if all(identity) and identity in identities:
            add(prefix + 'duplicate', 'BLOCKED', evidence='Duplicate route cannot supply independent pair/bus evidence.'); continue
        identities.add(identity)
        segments = path.get('segments')
        sections = [s for s in segments if isinstance(s, dict) and s.get('kind') != 'via'] if isinstance(segments, list) else []
        covered = sum(bool(s.get('reference_layer') and s.get('reference_net')) for s in sections)
        add(prefix + 'reference_coverage', 'INFO' if sections and covered == len(sections) else 'UNKNOWN',
            measured=covered, limit=len(sections) if sections else None, unit='sections',
            evidence='Sections with an identified filled reference layer/net: %d/%d. This is geometric reference evidence, not solved return-current continuity; absent segment evidence stays unknown.' % (covered, len(sections)))
        via_count, changes = path.get('via_count'), path.get('layer_changes')
        counts_valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (via_count, changes))
        no_transitions = counts_valid and via_count == 0 and changes == 0
        add(prefix + 'return_transitions', 'INFO' if no_transitions else 'UNKNOWN',
            measured=changes if _number(changes) else None, unit='layer changes',
            evidence=('No vias or layer changes reported; same-layer reference coverage is evaluated separately.' if no_transitions else
                      'Reported vias: %s; layer changes: %s. Quick SI does not solve via discontinuities, return-via connectivity or reference-transfer impedance; inspect the return-path tool.' % (via_count, changes)))
        eye = report.get('eye')
        if eye is not None:
            eye_inputs = eye.get('inputs', {}) if isinstance(eye, dict) else {}
            eye_rate = eye_inputs.get('bitrate_mbps') if isinstance(eye_inputs, dict) else None
            expected = profile['rate_Gbps'] * 1000 if profile['rate_Gbps'] is not None else None
            available = isinstance(eye, dict) and eye.get('status') == 'ILLUSTRATIVE' and _number(eye_rate) and eye_rate > 0
            comparable = available and expected is not None and profile['nyquist_GHz'] is not None
            state = ('INFO' if math.isclose(eye_rate, expected, rel_tol=1e-9) else 'REVIEW') if comparable else 'UNKNOWN'
            add(prefix + 'eye_rate', state, measured=eye_rate if _number(eye_rate) else None, limit=expected, unit='Mb/s',
                evidence='Optional ideal uniform-line PRBS7 eye rate versus selected data-rate preset. Matching rates do not establish an eye mask, receiver margin, protocol encoding or compliance. ' +
                         ('Rate matches the preset.' if comparable and state == 'INFO' else 'Rerun the illustrative eye at the preset rate.' if comparable else 'Eye unavailable, or profile has no applicable NRZ rate.'))
        delay = report.get('delay_ns')
        delay = delay if _number(delay) else None
        compare(prefix + 'delay', delay, 'max_delay_ns', 'ns', str(report.get('delay_source', 'No delay provenance.')))
        ratio = report.get('delay_to_rise_ratio')
        compare(prefix + 'edge', ratio if _number(ratio) else None, 'max_delay_to_rise_ratio', 'ratio',
                'Delay / user rise time. Rise time, source and load inputs are assumptions; the preset rate does not establish edge time.')
        target = profile['target_impedance_ohm']
        if profile['impedance_kind'] == 'differential':
            add(prefix + 'impedance', 'UNKNOWN', limit=target, unit='ohm differential',
                evidence='Independent route Z0 is single-ended. A coupled differential model is required; two times Z0 is not extracted differential impedance.')
        elif target is not None:
            z0 = report.get('z0_ohm')
            extracted = _number(z0) and z0 > 0 and str(report.get('z0_source', '')).startswith('Uniform routed-line approximation')
            error = abs(z0 - target) / target * 100 if extracted else None
            compare(prefix + 'impedance', error, 'max_impedance_error_percent', '%',
                    'Nominal vendor routing target %g ohm; only a board/reference-geometry uniform-line estimate qualifies. %s' % (target, report.get('z0_source', 'unavailable')))
        else:
            add(prefix + 'impedance', 'INFO', evidence='No universal PCB impedance target is defined for this profile.')
        valid.append((index, report, delay))
    topology = profile['topology']
    if topology in ('differential', 'bus'):
        groups = {}
        for index, report, delay in valid:
            role = str(report.get('suite_role', '')).strip().lower()
            group = str(report.get('suite_group', '')).strip()
            if not group or role not in (('p', 'n') if topology == 'differential' else ('clock', 'data')):
                add('route.%d.assignment' % index, 'UNKNOWN', evidence='Assign explicit role and group for pair/bus timing.'); continue
            groups.setdefault(group, []).append((role, index, delay))
        if not groups:
            add('groups', 'UNKNOWN', evidence='No explicitly assigned pair/bus group is available.')
        for group, members in sorted(groups.items()):
            clocks = [m for m in members if m[0] == ('p' if topology == 'differential' else 'clock')]
            data = [m for m in members if m[0] == ('n' if topology == 'differential' else 'data')]
            complete = len(clocks) == 1 and len(data) >= 1 and (topology != 'differential' or len(data) == 1)
            if not complete:
                add('group.' + group + '.membership', 'UNKNOWN', evidence='Requires exactly one P and N, or one clock and at least one data route.'); continue
            nets = [paths[m[1]]['path']['net_name'] for m in members]
            if len(nets) != len(set(nets)):
                add('group.' + group + '.membership', 'BLOCKED', evidence='Pair/bus members must be independently routed nets; multiple endpoint paths on the same net cannot stand in for separate signals.'); continue
            measured = max(abs(m[2] - clocks[0][2]) * 1000 for m in data) if all(m[2] is not None for m in members) else None
            compare('group.' + group + '.skew', measured, 'max_skew_ps', 'ps',
                    'Maximum route propagation-delay difference to P/clock. Excludes transmitter, receiver, clock insertion, setup/hold and package delays.')
    states = {c['status'] for c in checks}
    status = ('BLOCKED' if 'BLOCKED' in states else 'REVIEW' if 'REVIEW' in states
              else 'INCOMPLETE' if 'UNKNOWN' in states else 'WITHIN_BUDGET')
    return dict(schema='wayricad.protocol-suite/v1', profile=profile, status=status,
                checks=checks, budgets=deepcopy(budgets), route_count=len(paths),
                limitations=profile['limitations'] + ['WITHIN_BUDGET describes only evaluated route budgets, never standards compliance. Protocol rate/Nyquist is informational, not simulated channel bandwidth.'])
