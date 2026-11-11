"""Task-oriented grouping and evidence descriptions for manufacturing findings."""
from __future__ import annotations

FAMILIES = ('All checks', 'Routing and copper', 'Holes and vias', 'Solder mask',
            'Silkscreen', 'Assembly and placement', 'Edges and panelization', 'Process and documentation')
BASIS_LABELS = {'starting': 'Starting copper', 'finished': 'Finished copper',
                'vendor_order_option': 'Vendor order option'}


def evidence_entries(document, source_sha256, bundle=None):
    from .checklists import checklist_state
    state = checklist_state(document, source_sha256)
    rules = {rule['id']: rule for rule in document['profile']['rules']}
    requirements = [dict(item, rule=rules[item['rule_id']]) for item in state['results']]
    entries = list(requirements)
    if bundle and bundle['source_sha256'] == source_sha256:
        for finding in bundle.get('findings', []):
            entries.append(dict(status='FAIL', message=finding.get('description', ''), finding=finding,
                                object_ids=[item['uuid'] for item in finding.get('items', []) if item.get('uuid')]))
    return state, requirements, entries


def family(entry):
    rule = entry.get('rule', {})
    finding = entry.get('finding', {})
    text = ' '.join(str(value) for value in (rule.get('constraint', ''), rule.get('title', ''),
                                            finding.get('type', ''), finding.get('description', ''))).casefold()
    if 'silk' in text or 'legend' in text: return FAMILIES[4]
    if 'mask' in text: return FAMILIES[3]
    if any(word in text for word in ('edge', 'panel', 'tooling', 'fiducial', 'v-cut', 'v-score')): return FAMILIES[6]
    if any(word in text for word in ('courtyard', 'assembly', 'placement', 'paste', 'component height', 'rework', 'bga')): return FAMILIES[5]
    if any(word in text for word in ('drill', 'hole', 'via', 'annular', 'slot')): return FAMILIES[2]
    if any(word in text for word in ('track', 'trace', 'clearance', 'copper', 'shorting', 'unconnected')): return FAMILIES[1]
    if rule.get('category') == 'DFA': return FAMILIES[5]
    return FAMILIES[7]


def displayed_status(entry):
    severity = entry.get('rule', {}).get('severity', entry.get('finding', {}).get('severity', 'error'))
    return 'WARN' if entry['status'] == 'FAIL' and severity == 'warning' else entry['status']


def describe(entry, profile):
    rule = entry.get('rule', {}); finding = entry.get('finding', {})
    lines = [rule.get('title', finding.get('type', 'Native finding')).replace('_', ' '),
             family(entry) + ' · ' + displayed_status(entry), '', entry.get('message', '')]
    for key, label in (('minimum', 'Minimum'), ('maximum', 'Maximum')):
        if rule.get(key) is not None: lines.append(f'{label}: {rule[key]:g} {rule.get("unit") or ""}')
    if entry.get('actual') is not None: lines.append('Measured: ' + str(entry['actual']))
    if rule.get('notes'): lines += ['', rule['notes']]
    items = finding.get('items', [])
    if items:
        lines += ['', 'Affected board items:']
        for item in items:
            position = item.get('pos', {})
            location = f' · X {position["x"]:g}, Y {position["y"]:g} mm' if 'x' in position and 'y' in position else ''
            lines.append(str(item.get('description', item.get('uuid', 'Item'))) + location)
    elif entry.get('object_ids'):
        lines += ['', 'Board item identities:', *entry['object_ids']]
    if finding:
        from .assembly_checks import corrective_action
        lines += ['', 'Suggested review / correction:', corrective_action(finding)]
    sources = {source['id']: source for source in profile['sources']}
    for identifier in rule.get('source_ids', []):
        source = sources[identifier]
        lines += ['', source['title'], source['url'], 'Source checked: ' + str(source['verified'] or 'Not verified')]
    for note in entry.get('manual_evidence', []): lines += ['', 'Attached evidence: ' + note['detail']]
    if entry.get('waiver'):
        lines += ['', 'Waiver (does not change the measured result): ' + entry['waiver']['reason']]
    return '\n'.join(lines)
