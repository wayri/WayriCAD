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


def candidate_pairs(bodies, margin):
    """Sweep broad phase: no pair within margin can be lost."""
    active = []
    for item in sorted(bodies, key=lambda item: item['bounds'][0]):
        active = [other for other in active if other['bounds'][3] + margin >= item['bounds'][0]]
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

