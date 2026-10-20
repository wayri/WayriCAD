"""Conserved DC power budgets for offline, left-to-right Sankey diagrams."""
from __future__ import annotations

import math


def _number(value, label):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or value < 0):
        raise ValueError(label + ' must be finite and nonnegative.')
    return float(value)


def _graph(sources, loads, losses, note):
    """Check global conservation before representing a source/distribution/load budget."""
    def bounded(rows, label):
        rows = [(name, _number(value, name)) for name, value in rows]
        if len(rows) > 150:
            rest = rows[149:]
            rows = rows[:149] + [(f'{len(rest)} additional {label} (combined)', math.fsum(value for _, value in rest))]
        return rows
    sources = bounded(sources, 'sources')
    loads = bounded(loads, 'loads')
    losses = bounded(losses, 'losses')
    incoming = math.fsum(value for _, value in sources)
    outgoing = math.fsum(value for _, value in loads + losses)
    if incoming <= 0:
        raise ValueError('No positive source power is available.')
    error = abs(incoming - outgoing)
    if error > max(1e-9, incoming * 1e-6):
        raise ValueError('Source, load and loss evidence does not conserve power.')
    nodes = [{'id': 'distribution', 'label': 'Solved DC power distribution'}]
    links = []
    for kind, rows in (('source', sources), ('load', loads), ('loss', losses)):
        for index, (label, value) in enumerate(rows):
            value = _number(value, label)
            if value == 0:
                continue
            identifier = kind + str(index)
            nodes.append({'id': identifier, 'label': label})
            links.append({'source': identifier if kind == 'source' else 'distribution',
                          'target': 'distribution' if kind == 'source' else identifier,
                          'value': value})
    note += f' Power balance residual: {error:.6g} W (not redistributed).'
    return {'nodes': nodes, 'links': links, 'note': note}


def _result_graph(bundle):
    result = bundle.get('result') or {}
    if (bundle.get('physical_return') or result.get('physical_return') or
            bundle.get('return_conduction_notice') or bundle.get('return_voltage_reference')):
        raise ValueError('Return-only potentials use a ground reference. See the coupled study Sankey for physical source-to-load power.')
    voltage = _number(result.get('source_voltage_V'), 'Source voltage')
    current = _number(result.get('source_current_A'), 'Solved source current')
    loss = _number(result.get('total_power_W'), 'Total modeled loss')
    rows = result.get('sinks')
    if rows is None:
        rows = [{'label': 'Load', 'voltage_V': result.get('sink_voltage_V'),
                 'current_A': result.get('sink_current_A')}]
    if not rows:
        raise ValueError('No solved sink units are available.')
    loads = [(str(row.get('label') or row.get('id') or 'Load'),
              _number(row.get('current_A'), 'Load current') *
              _number(row.get('voltage_V'), 'Load voltage')) for row in rows]
    sink_current = math.fsum(_number(row.get('current_A'), 'Load current') for row in rows)
    if not math.isclose(sink_current, current, rel_tol=1e-6, abs_tol=1e-9):
        raise ValueError('Solved source and sink currents disagree.')
    note = ('Source at left; delivered sink power and modeled conductor/component/package losses at right. '
            'Each grouped pad unit is counted once using its solved total current; no pad split is inferred. '
            'Return loss is included only in an explicit coupled loop or shared-return budget. '
            'This is an accounting diagram, not geometric current streamlines.')
    if result.get('feasibility', {}).get('feasible') is False:
        note += ' INFEASIBLE requested-load diagnostic; not an attainable operating point.'
    return _graph([('Source unit (all source pads)', voltage * current)], loads,
                  [('Total modeled loss', loss)], note)


def shared_graph(group, cases):
    """Count common return loss once, pooling rails without inventing loss attribution."""
    members = {row['case'] for row in group['loads']}
    sources = []
    for name in sorted(members):
        result = cases[name]['electrical']['result']
        sources.append((name + ' source unit',
                        _number(result.get('source_voltage_V'), 'Source voltage') *
                        _number(result.get('source_current_A'), 'Source current')))
    loads = [(str(row['case']) + ' / ' + str(row['sink']),
              _number(row.get('load_power_W'), 'Delivered load power')) for row in group['loads']]
    return _graph(sources, loads,
                  [('Supply losses', _number(group.get('supply_loss_W'), 'Supply losses')),
                   ('Shared return loss (once)', _number(group.get('return_loss_W'), 'Shared return loss'))],
                  'Coupled shared-return budget. Sources feed a pooled distribution; no per-rail return-loss '
                  'allocation is inferred. Grouped load pads count once. Status: ' + str(group.get('status', 'UNKNOWN')) + '.')


def power_graph(bundle):
    """Return plot data, or a visible unavailable explanation for incomplete evidence."""
    try:
        return _result_graph(bundle)
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        return {'nodes': [], 'links': [], 'note': 'Power flow unavailable: ' + str(error)}


def sankey_section(bundle):
    """Render complete accounting diagrams in ordinary, batch and 3D HTML reports."""
    from wayricad_runtime.sankey import sankey_html
    batch = bundle.get('batch')
    if bundle.get('electrothermal'):
        result = bundle['electrothermal']
        if bundle.get('mode') == 'steady':
            sections = []
            for key, label in (('cold', 'Cold DC power (W)'), ('hot', 'Hot DC power (W)')):
                graph = power_graph({'result': result.get(key)})
                if key == 'hot':
                    graph['note'] += ' Coupled solver status: ' + str(result.get('status', 'UNKNOWN')) + '.'
                    if not result.get('limits', {}).get('operating_point_valid'):
                        graph['note'] += ' Operating point not accepted; diagnostic evidence only.'
                sections.append(sankey_html(label, **graph))
            return ''.join(sections)
        return sankey_html('DC power flow', [], [], note='Unavailable: a DC power budget cannot represent transient stored energy. Use the time-domain evidence plots.')
    if not batch:
        graph = power_graph(bundle)
        return sankey_html('Source-to-sink DC power (W)', **graph)
    cases = {case.get('name'): case for case in batch.get('cases', [])}
    sections = []; grouped = set()
    for group in batch.get('shared_returns', []):
        grouped.update(row.get('case') for row in group.get('loads', []))
        try:
            graph = shared_graph(group, cases)
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            graph = {'nodes': [], 'links': [], 'note': 'Power flow unavailable: ' + str(error)}
        sections.append(sankey_html(str(group.get('name', 'Shared return')) + ' power (W)', **graph))
    for name, case in cases.items():
        if name in grouped:
            continue
        if case.get('status') == 'FAILED':
            graph = {'nodes': [], 'links': [], 'note': 'Power flow unavailable: case failed. ' + str(case.get('error', 'Review case evidence.'))}
        elif case.get('shared_return'):
            graph = {'nodes': [], 'links': [], 'note': 'Power flow unavailable: shared-return group evidence missing.'}
        elif case.get('loop'):
            loop = case['loop']
            try:
                current = _number(loop.get('current_A'), 'Loop current')
                graph = _graph([(str(name) + ' source', current * _number(loop.get('source_voltage_V'), 'Source voltage'))],
                               [('Delivered load', current * _number(loop.get('delivered_load_voltage_V'), 'Delivered voltage'))],
                               [('Supply and return losses', _number(loop.get('total_loss_W'), 'Loop losses'))],
                               'Explicit supply/return loop; status: ' + str(loop.get('status', 'UNKNOWN')) + '.')
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                graph = {'nodes': [], 'links': [], 'note': 'Power flow unavailable: ' + str(error)}
        else:
            graph = power_graph(case.get('electrical', {}))
        graph['note'] += ' Case status: ' + str(case.get('status', 'UNKNOWN')) + '.'
        sections.append(sankey_html(str(name or 'Case') + ' power (W)', **graph))
    return ''.join(sections)


def write_sankey_report(path, bundle):
    """Publish an offline diagram using the normal saved-source custody checks."""
    from pathlib import Path
    from wayricad_runtime.report_ui import checked_sources, publish_documents
    path = Path(path).with_suffix('.html')
    document = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
                'content="width=device-width,initial-scale=1"><title>Quick PI power flow</title>'
                '<style>body{font:15px system-ui;margin:24px}</style><h1>Quick PI power flow</h1>' +
                sankey_section(bundle) + '</html>')
    publish_documents({path: document}, sources=checked_sources(bundle))
    return path


def open_sankey(bundle):
    """Open a lightweight offline preview without rendering copper field maps."""
    import tempfile
    import wx
    from pathlib import Path
    path = Path(tempfile.mkdtemp(prefix='wayricad-pi-power-')) / 'power-flow.html'
    write_sankey_report(path, bundle)
    if not wx.LaunchDefaultBrowser(path.as_uri()):
        raise OSError('The browser could not open the power-flow report: ' + str(path))
    return path
