import hashlib
import math


def finding(rule, refs, summary, action, evidence='exact', measured=None, limit=None, severity='error', **extra):
    refs = sorted(set(refs))
    identity = '|'.join([rule, *refs, str(extra.get('location_key', ''))])
    return dict(id=hashlib.sha256(identity.encode()).hexdigest()[:16], rule=rule,
                refs=refs, summary=summary, action=action, evidence=evidence,
                measured=measured, limit=limit, severity=severity, **extra)


def gaps(a, b):
    return [max(a[i] - b[i+3], b[i] - a[i+3], 0.0) for i in range(3)]


def bbox_distance(a, b):
    return math.sqrt(sum(v*v for v in gaps(a, b)))


def maximum_height_findings(body, thickness, config):
    """Check both outward PCB-face allowances, irrespective of mounting side.

    CAD bounds can conservatively enclose curved geometry. Marker points locate
    those bounds, rather than claiming a closest witness on the solid surface.
    """
    bounds = body['bounds']
    x, y = [(bounds[i] + bounds[i+3])/2 for i in range(2)]
    for side, face, extreme, direction in (('top', thickness, bounds[5], 1),
                                            ('bottom', 0, bounds[2], -1)):
        height = max(0, direction * (extreme-face))
        limit = config[side+'_height_mm']
        if height <= limit + 1e-7:
            continue
        position = [x, y, extreme]
        excess = height-limit
        yield finding('height.maximum', [body['ref']],
                      f'Component exceeds {side} height limit by {excess:.6g} mm',
                      'Choose a lower component, correct model placement/standoff or revise the height allowance.',
                      evidence='conservative CAD height envelope from STEP solid',
                      measured=height, limit=limit, unit='mm', location_key=side,
                      side=side, height_mm=height, excess_mm=excess, tolerance_mm=1e-7,
                      points=[[[x,y,face], position]], label_position=position,
                      limit_point=[x,y,face+direction*limit],
                      marker_evidence='CAD bounds marker; not a closest-surface witness')


def candidate_pairs(bodies, margin):
    """Sweep broad phase: no pair within margin can be lost."""
    bodies = list(bodies)
    if not bodies:
        return
    # Sweep the most spread-out axis, so vertical/rotated layouts do not
    # degenerate simply because all their X intervals coincide.
    axis = max(range(3), key=lambda i: max(b['bounds'][i] for b in bodies) - min(b['bounds'][i] for b in bodies))
    active = []
    for item in sorted(bodies, key=lambda item: item['bounds'][axis]):
        active = [other for other in active if other['bounds'][axis+3] + margin >= item['bounds'][axis]]
        for other in active:
            if bbox_distance(item['bounds'], other['bounds']) <= margin:
                yield other, item
        active.append(item)


def finish(report, config):
    for issue in report['findings']:
        issue['waiver'] = config['waivers'].get(issue['id'], '')
    report['findings'].sort(key=lambda f: (bool(f['waiver']), {'error': 0, 'warning': 1, 'info': 2}[f['severity']], f['rule'], f['refs']))
    report['status'] = ('incomplete' if report['coverage']['gaps'] else
                        'review_required' if any(not f['waiver'] and f['severity'] in ('error', 'warning') for f in report['findings']) else
                        'passed_with_waivers' if any(f['waiver'] for f in report['findings']) else 'passed')
    return report

