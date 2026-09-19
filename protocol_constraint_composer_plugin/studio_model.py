"""UI-independent commands for the visual constraint workbench.

All edits return a cloned workspace. The desktop owns history and filesystem dialogs.
"""
from __future__ import annotations
import copy
from dataclasses import asdict
import math

from .constraint_studio.catalog import SPECS, CATALOG, SEVERITIES
from .constraint_studio.engineering import builtin_profiles, install_profile
from .constraint_studio.inspection import items_from_board, priority_trace, rule_match
from .constraint_studio.linked_areas import all_areas, area_polygon
from .constraint_studio.model import Rule, Constraint, RuleDocument, lint
from .constraint_studio.profiles import matrix_rules, replace_generated
from .constraint_studio.workspace import get_path, set_path, parse_scalar
from .studio_bridge import overview


def index(value, rows):
    if type(value) is not int or not 0 <= value < len(rows):
        raise ValueError('The selected row no longer exists. Refresh the workspace.')
    return value


def snapshot(workspace):
    summary = overview(workspace)
    items = items_from_board(workspace.context, workspace.project)
    regions, omitted = [], []
    for area in all_areas(workspace.context):
        if not area.get('rule_area'): continue
        try: regions.append({'name': area['name'], 'points': area_polygon(area)})
        except ValueError: omitted.append(area['name'])
    return {
        'revision': workspace.state(), 'board': str(workspace.board_path or ''),
        'name': workspace.board_path.name if workspace.board_path else 'No project open',
        'dirty': workspace.dirty, 'rules': [dict(asdict(rule), index=i) for i, rule in enumerate(workspace.document.rules)],
        'summary': {k: v for k, v in summary.items() if k != 'issues'},
        'issues': [asdict(issue) for issue in summary['issues']],
        'specs': [asdict(spec) for spec in SPECS], 'severities': SEVERITIES,
        'items': [dict(index=i, label=item.label, uid=item.uid, kind=item.kind, net=item.net,
                       reference=item.reference, points=item.points, layers=item.layers,
                       geometry=item.geometry, radius=item.radius) for i, item in enumerate(items)],
        'regions': regions, 'omitted_regions': omitted,
        'components': [fp.reference for fp in workspace.context.footprints],
        'nets': sorted(set(workspace.context.nets) | {item.net for item in items if item.net}),
        'layers': workspace.context.layers,
        'classes': copy.deepcopy(workspace.project.get('net_settings', {}).get('classes', [])),
        'patterns': copy.deepcopy(workspace.project.get('net_settings', {}).get('netclass_patterns', [])),
        'settings': [dict(path=list(path), value=value) for path, value in workspace.settings_rows()],
        'profiles': builtin_profiles(),
    }


def checked_rule(rule):
    if rule.severity not in [''] + SEVERITIES: raise ValueError('Unknown severity')
    document = RuleDocument(); document.append(rule)
    RuleDocument.load(document.emit())
    # Disabled invalid rules must still be repaired before they can be saved here.
    active = copy.deepcopy(document); active.rules[0].enabled = True
    errors = [issue.message for issue in lint(active) if issue.severity == 'error']
    if errors: raise ValueError('\n'.join(errors))


def mutation(workspace, method, data):
    if data.get('revision') != workspace.state():
        raise ValueError('Workspace changed since this view was loaded. Refresh before editing.')
    w = workspace.clone()
    rules = w.document.rules
    if method == 'save_rule':
        i = data.get('index')
        rule = copy.deepcopy(rules[index(i, rules)]) if i is not None else Rule('New rule')
        values = data['rule']
        for field in ('name', 'condition', 'layer', 'severity', 'notes'):
            setattr(rule, field, str(values.get(field, getattr(rule, field))).strip())
        if type(values.get('enabled', True)) is not bool: raise ValueError('Enabled must be boolean')
        rule.enabled = values.get('enabled', True)
        constraints = []
        for row in values['constraints']:
            old = row.get('index')
            constraint = copy.deepcopy(rule.constraints[index(old, rule.constraints)]) if old is not None else Constraint(row['kind'])
            kind = str(row['kind'])
            if kind not in CATALOG and (old is None or kind != constraint.kind): raise ValueError('Unknown constraint type')
            if kind != constraint.kind and constraint.extras: raise ValueError('This clause has preserved syntax; edit it in the detailed editor.')
            constraint.kind = kind
            constraint.values = {str(k): str(v).strip() for k, v in row.get('values', {}).items() if str(v).strip()}
            if any(k not in ('min', 'opt', 'max') for k in constraint.values): raise ValueError('Unknown constraint field')
            if kind in CATALOG and any(k not in CATALOG[kind].fields for k in constraint.values): raise ValueError('This constraint does not support that value field')
            constraint.argument = str(row.get('argument', ''))
            constraint.within_diff_pairs = bool(row.get('within_diff_pairs', False))
            constraints.append(constraint)
        rule.constraints = constraints; checked_rule(rule)
        if i is None: w.document.append(rule)
        else: rules[i] = rule
    elif method == 'set_value':
        rule = rules[index(data['rule'], rules)]
        c = rule.constraints[index(data['constraint'], rule.constraints)]
        field = data['field']
        if c.kind not in CATALOG or field not in CATALOG[c.kind].fields: raise ValueError('This field is not editable for the constraint')
        c.values[field] = str(data['value']).strip(); checked_rule(rule)
    elif method in ('toggle', 'duplicate', 'delete', 'move'):
        i = index(data['index'], rules)
        if method == 'toggle': rules[i].enabled = not rules[i].enabled
        elif method == 'duplicate': w.document.append(rules[i].clone())
        elif method == 'delete': rules.pop(i)
        else:
            delta = data['delta']
            if delta not in (-1, 1): raise ValueError('Priority must move one position')
            w.document.move(i, delta)
    elif method == 'matrix':
        compiled = compile_matrix(data)
        if not compiled: raise ValueError('Enter at least one matrix value before staging.')
        for rule in compiled: checked_rule(rule)
        replace_generated(w.document, compiled, 'CS-MATRIX ' + data['group'])
    elif method == 'profile':
        profiles = {p['id']: p for p in builtin_profiles()}
        if data['id'] not in profiles: raise ValueError('Unknown constraint set')
        install_profile(w, profiles[data['id']], data['bindings'], str(data['instance']),
                        apply_floors=bool(data.get('apply_floors')), approve_migration=False)
    elif method == 'netclass':
        rows = w.project.get('net_settings', {}).get('classes', [])
        row = rows[index(data['index'], rows)]
        key = data['key']
        allowed = ('clearance','track_width','via_diameter','via_drill','microvia_diameter','microvia_drill','diff_pair_width','diff_pair_gap','diff_pair_via_gap')
        if key not in allowed: raise ValueError('Use the native editor to migrate class names or custom fields.')
        value = str(data['value']).strip()
        number = None if value in ('', 'null') else float(value)
        if number is not None and (not math.isfinite(number) or number < 0): raise ValueError('Use a finite, nonnegative dimension or null.')
        row[key] = number
    elif method == 'setting':
        path = tuple(data['path'])
        if path not in {path for path, _ in w.settings_rows()}: raise ValueError('Unknown editable project field')
        set_path(w.project, path, parse_scalar(str(data['value']), get_path(w.project, path)))
    else:
        raise ValueError('Unknown workspace command: ' + method)
    return w


def compile_matrix(data):
    labels = [str(label).strip() for label in data['labels']]
    if not 1 <= len(labels) <= 40: raise ValueError('Use between 1 and 40 matrix labels')
    group = str(data.get('group', '')).strip()
    if not group or '\n' in group or '\r' in group: raise ValueError('Enter a one-line matrix group name')
    cells = {(int(row['i']), int(row['j'])): str(row['value']) for row in data['cells']}
    if any(not (0 <= i < len(labels) and 0 <= j < len(labels)) for i, j in cells): raise ValueError('Matrix cell outside labels')
    return matrix_rules(labels, cells, data.get('kind', 'clearance'), data.get('scope', 'netclass'),
                        data.get('layer', ''), group, data.get('region', ''))


def inspect_scope(workspace, data):
    rules = workspace.document.rules
    rule = rules[index(data['rule'], rules)]
    items = items_from_board(workspace.context, workspace.project)
    matches = [rule_match(rule, item, context=workspace.context) for item in items]
    result = {'matches': [dict(index=i, value=match.value, reasons=match.reasons) for i, match in enumerate(matches)]}
    if data.get('a') is not None:
        a = items[index(data['a'], items)]
        b = items[index(data['b'], items)] if data.get('b') is not None else None
        kind = data.get('kind') or (rule.constraints[0].kind if rule.constraints else 'clearance')
        result['trace'] = priority_trace(workspace.document, kind, a, b, workspace.context, workspace.floors)
    return result
