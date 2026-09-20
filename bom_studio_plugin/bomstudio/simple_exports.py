"""Read-only export recipes over staged workspace rows and existing templates."""
from copy import copy, deepcopy
import re
from .exporters import table, export


def is_test_point(row):
    """Conservative, documented classification; users can set TestPoint explicitly."""
    marker = str(row['fields'].get('TestPoint', '')).strip().lower()
    if marker in ('false', 'no', '0'):
        return False
    return marker in ('true', 'yes', '1') or bool(re.fullmatch(r'TP\d+[A-Za-z]?', row['ref'], re.I))


def prepare(workspace, options):
    if not isinstance(options, dict):
        raise ValueError('Export options must be an object.')
    kind = options.get('kind', 'bom')
    if kind not in ('bom', 'testpoints', 'dnp'):
        raise ValueError('Choose BOM, testpoints or DNP.')
    for key in ('grouped', 'exclude_testpoints', 'exclude_dnp'):
        if key in options and not isinstance(options[key], bool):
            raise ValueError(key + ' must be true or false.')
    name = options.get('template', 'Engineering')
    if not isinstance(name, str) or name not in workspace.state['templates']:
        raise ValueError('Choose an existing template.')
    staged = copy(workspace)
    staged.state = deepcopy(workspace.state)
    template = deepcopy(staged.state['templates'][name])
    # The recipe owns population/inclusion; all column/format settings survive.
    template['population'] = 'all'
    template['include_excluded'] = kind != 'bom'
    if not options.get('grouped', True):
        template['group_by'] = []
    elif not template.get('group_by'):
        template['group_by'] = ['Value', 'Footprint', 'MPN']
    template['name'] = name + ' - ' + kind
    staged.state['templates'][template['name']] = template

    def selected(variant):
        rows = workspace.rows(variant)
        if kind == 'testpoints':
            return [r for r in rows if is_test_point(r)]
        if kind == 'dnp':
            return [r for r in rows if r['flags']['dnp']]
        return [r for r in rows
                if not (options.get('exclude_testpoints', True) and is_test_point(r))
                and not (options.get('exclude_dnp', True) and r['flags']['dnp'])]

    staged.rows = selected
    return staged, template['name']


def preview(workspace, variant, options):
    staged, name = prepare(workspace, options)
    return table(staged, variant, name)


def download(workspace, variant, options, fmt='csv', draft=False):
    staged, name = prepare(workspace, options)
    return export(staged, variant, name, fmt, draft)
