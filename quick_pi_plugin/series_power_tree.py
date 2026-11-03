"""Ordered series-path power accounting, distinct from converter-intent trees.

Saved net identity supplies topology. Solved electrode powers supply metrics;
parallel pad currents and converter efficiency are never inferred.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
from html import escape
import math


def _finite(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _sum(values):
    values = list(values)
    return math.fsum(values) if values and all(value is not None for value in values) else None


def _power(voltage, current):
    return voltage * current if voltage is not None and current is not None else None


def _metrics(incoming, outgoing, current, *, efficiency=True):
    loss = incoming - outgoing if incoming is not None and outgoing is not None else None
    valid = efficiency and incoming is not None and outgoing is not None and incoming > 0 and 0 <= outgoing <= incoming * (1 + 1e-9)
    return dict(current_A=current, input_power_W=incoming, output_power_W=outgoing,
                loss_W=loss, voltage_drop_V=loss / current if loss is not None and current not in (None, 0) else None,
                voltage_before_V=incoming / current if incoming is not None and current not in (None, 0) else None,
                voltage_after_V=outgoing / current if outgoing is not None and current not in (None, 0) else None,
                efficiency_fraction=outgoing / incoming if valid else None)


def build_series_power_tree(bundle):
    """Return an ordered, JSON-safe topology and DC budget, or None for non-series.

    Copper node voltages are current-weighted electrode voltages, not a claim that
    a resistive net is equipotential. Each component/pad group remains explicit.
    No return network or voltage-converter behavior is added to the series model.
    """
    request = bundle.get('request') or {}
    stages = request.get('series')
    if not stages:
        return None
    mesh = bundle.get('mesh') or {}
    geometry = bundle.get('geometry') or mesh.get('geometry') or {}
    terminals = geometry.get('terminals', [])
    lookup = {str(row['id']): row for row in terminals}
    label_counts = Counter(row.get('label') for row in terminals)
    for row in terminals:
        if label_counts[row.get('label')] == 1:
            lookup[str(row.get('label'))] = row
    def terminal(value):
        row = lookup.get(str(value), {})
        return dict(id=str(row.get('id', value)), label=str(row.get('label', value)), net=row.get('net'))
    def group(row, side):
        values = row.get(side + '_terminals') or row.get(side + '_pads') or [row.get(side + '_pad') or row.get(side + '_terminal')]
        return [terminal(value) for value in values if value is not None]
    source_ids = request.get('source_terminals') or [request.get('source_terminal', request.get('source'))]
    sink_ids = request.get('sink_terminals') or [request.get('sink_terminal', request.get('sink'))]
    source_pins = [terminal(value) for value in source_ids if value is not None]
    sink_pins = [terminal(value) for value in sink_ids if value is not None]
    result = bundle.get('result') or {}
    solved = {str(row['id']): row for row in result.get('components', [])}
    mesh_parts = iter(mesh.get('lumped_branches', []))
    feasible = result.get('feasibility', {}).get('feasible') is not False
    banks = []
    for index, stage in enumerate(stages):
        parts = []
        for branch in [stage, *stage.get('parallel', [])]:
            meta = next(mesh_parts, branch)
            data = solved.get(str(meta.get('id')), {})
            incoming, outgoing = group(meta, 'from'), group(meta, 'to')
            current = _finite(data.get('current_A'))
            before, after = _finite(data.get('voltage_before_V')), _finite(data.get('voltage_after_V'))
            reference = branch.get('reference') or (incoming[0]['label'].rsplit('.', 1)[0] if incoming else str(branch.get('id', 'Component')))
            part = dict(id=str(meta.get('id', reference)), reference=reference,
                        incoming_pins=incoming, outgoing_pins=outgoing,
                        model={key: deepcopy(branch[key]) for key in ('model', 'resistance_ohm', 'inductance_h', 'fixed_drop_v', 'diode') if key in branch},
                        **_metrics(_power(before, current), _power(after, current), current, efficiency=feasible))
            # Preserve the solver's dissipated power independently of endpoint accounting.
            part['modeled_loss_W'] = _finite(data.get('power_W'))
            parts.append(part)
        bank_current = _sum(part['current_A'] for part in parts)
        banks.append(dict(id=f'stage-{index + 1}', kind='parallel_stage', label=' || '.join(str(part['reference']) for part in parts),
                          parts=parts, **_metrics(_sum(part['input_power_W'] for part in parts),
                          _sum(part['output_power_W'] for part in parts), bank_current, efficiency=feasible)))
    current = _finite(result.get('source_current_A'))
    source_power = _power(_finite(result.get('source_voltage_V')), current)
    sinks = result.get('sinks') or [dict(voltage_V=result.get('sink_voltage_V'), current_A=result.get('sink_current_A'))]
    load_power = _sum(_power(_finite(row.get('voltage_V')), _finite(row.get('current_A'))) for row in sinks)
    nodes = [dict(id='source', kind='source', label='Source', pins=source_pins,
                  voltage_V=_finite(result.get('source_voltage_V')), current_A=current, output_power_W=source_power)]
    for index in range(len(banks) + 1):
        incoming_pins = source_pins if index == 0 else [pin for part in banks[index - 1]['parts'] for pin in part['outgoing_pins']]
        outgoing_pins = sink_pins if index == len(banks) else [pin for part in banks[index]['parts'] for pin in part['incoming_pins']]
        net = next((pin['net'] for pin in incoming_pins + outgoing_pins if pin.get('net') is not None), None)
        if net is None and index < len(geometry.get('nets', [])):
            net = geometry['nets'][index]
        incoming = source_power if index == 0 else banks[index - 1]['output_power_W']
        outgoing = load_power if index == len(banks) else banks[index]['input_power_W']
        nodes.append(dict(id=f'copper-{index + 1}', kind='copper', label=str(net or f'Copper segment {index + 1}'), net=net,
                          incoming_pins=incoming_pins, outgoing_pins=outgoing_pins,
                          **_metrics(incoming, outgoing, current, efficiency=feasible)))
        if index < len(banks):
            nodes.append(banks[index])
    nodes.append(dict(id='load', kind='load', label='Load', pins=sink_pins, input_power_W=load_power,
                      voltage_V=_finite(result.get('sink_voltage_V')),
                      current_A=_sum(_finite(row.get('current_A')) for row in sinks)))
    copper = [node for node in nodes if node['kind'] == 'copper']
    nets = [node['net'] for node in copper if node['net'] is not None]
    repeated = len(nets) != len(set(nets))
    if repeated:
        for node in copper:
            node.update(_metrics(None, None, None))
            node['accounting_status'] = 'unavailable_repeated_net'
            node['accounting_notice'] = ('Repeated physical nets can bypass ordered stages; '
                                         'per-occurrence copper current, loss, voltage and efficiency cannot be allocated from this path.')
    return dict(schema='series-power-tree-1', status='solved' if result else 'topology_only',
                source_sha256=geometry.get('source_sha256', bundle.get('source_sha256')),
                feasible=result.get('feasibility', {}).get('feasible'), nodes=nodes,
                edges=[dict(source=a['id'], target=b['id']) for a, b in zip(nodes, nodes[1:])],
                summary=_metrics(source_power, load_power, current, efficiency=feasible),
                notice='DC series-path accounting; copper voltages are current-weighted electrode values. '
                       'Each reviewed pad group is counted once; individual pad-current sharing is unknown. '
                       'Stage efficiency means transmitted DC power / incoming DC power, not converter efficiency. '
                       'Return-path loss is excluded unless explicitly modeled. Infeasible results are diagnostics; efficiency is unavailable.' +
                       (' Repeated physical nets prevent per-occurrence copper accounting; those metrics are unavailable.' if repeated else ''))


def series_path_tree(path, inventory):
    """Build a topology-only tree from a reviewed inferred/saved path."""
    from .series_editor import parse_saved_path
    return build_series_power_tree(dict(request=parse_saved_path(path, inventory), geometry=inventory))


def tree_text(tree):
    """Compact native-output text, retaining every stage, net and pin group."""
    if tree is None:
        return ''
    lines = [tree['notice']]
    def pins(values):
        return ', '.join(pin['label'] for pin in values) or 'Unknown'
    def metrics(row):
        labels = [('voltage_V', 'Potential', 'V'), ('voltage_before_V', 'Vin', 'V'), ('voltage_after_V', 'Vout', 'V'),
                  ('current_A', 'I', 'A'), ('voltage_drop_V', 'drop', 'V'), ('loss_W', 'loss', 'W'),
                  ('input_power_W', 'Pin', 'W'), ('output_power_W', 'Pout', 'W')]
        output = [f'{name} {row[key]:.6g} {unit}' for key, name, unit in labels if row.get(key) is not None]
        if row.get('efficiency_fraction') is not None:
            output.append(f"transmission {100 * row['efficiency_fraction']:.6g}%")
        return ' · '.join(output) or 'Not solved'
    if tree.get('summary'):
        lines.append('Whole path: ' + metrics(tree['summary']))
    for node in tree['nodes']:
        lines.append('\n' + node['label'] + ' [' + node['kind'] + ']')
        lines.append(metrics(node))
        if node.get('accounting_notice'):
            lines.append(node['accounting_notice'])
        if node.get('pins'):
            lines.append('Pins: ' + pins(node['pins']))
        for row in [node, *node.get('parts', [])]:
            if row is not node:
                lines.append(str(row['reference']) + ': ' + metrics(row))
            if 'incoming_pins' in row:
                lines.append('Incoming: ' + pins(row['incoming_pins']) + ' → outgoing: ' + pins(row['outgoing_pins']))
    return '\n'.join(lines)


def _tree_png(tree):
    """Small lossless diagram for the PDF renderer's existing PNG support."""
    import base64
    import io
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import FancyBboxPatch
    count = len(tree['nodes'])
    figure = Figure(figsize=(9, count * .48 + .1), dpi=120)
    FigureCanvasAgg(figure)
    axes = figure.add_axes([0, 0, 1, 1])
    axes.set_xlim(0, 9); axes.set_ylim(count, 0); axes.axis('off')
    for index, row in enumerate(tree['nodes']):
        if index:
            axes.plot([4.5, 4.5], [index - .1, index + .1], color='#507070', linewidth=1)
        axes.add_patch(FancyBboxPatch((.1, index + .1), 8.8, .8, boxstyle='round,pad=0,rounding_size=.08',
                                     facecolor='#eef5f4', edgecolor='#507070', linewidth=.8))
        axes.text(.24, index + .5, row['label'] + ' · ' + row['kind'], va='center', fontsize=10, parse_math=False)
    output = io.BytesIO(); figure.savefig(output, format='png', dpi=120)
    return base64.b64encode(output.getvalue()).decode('ascii')


def tree_html(tree, *, raster=False):
    """Offline compact vector topology and per-node evidence for HTML/PDF."""
    if tree is None:
        return ''
    count = len(tree['nodes']); height = count * 54 + 12
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 {height}" role="img" aria-label="Series path power tree">']
    for index, row in enumerate(tree['nodes']):
        y = 8 + index * 54
        if index:
            svg.append(f'<path d="M450 {y - 12}v12" stroke="#507070" fill="none"/>')
        svg.append(f'<rect x="10" y="{y}" width="880" height="42" rx="5" fill="#eef5f4" stroke="#507070"/>')
        label = escape(row['label'] + ' · ' + row['kind'])
        svg.append(f'<text x="24" y="{y + 26}" font-family="sans-serif" font-size="16">{label}</text>')
    svg.append('</svg>')
    if raster:
        # Keep long paths legible in PDF rather than shrinking one tall image.
        diagram = ''.join('<img alt="Series path power tree, nodes ' + str(start + 1) + ' onward" src="data:image/png;base64,' +
                          _tree_png(dict(tree, nodes=tree['nodes'][start:start + 8])) + '">'
                          for start in range(0, count, 8))
    else:
        diagram = ''.join(svg)
    sections = []
    for row in tree['nodes']:
        detail = tree_text(dict(tree, notice='', nodes=[row], summary=None)).strip()
        sections.append('<h3>' + escape(row['label'] + ' · ' + row['kind']) + '</h3><pre>' + escape(detail) + '</pre>')
    summary = tree_text(dict(tree, notice='', nodes=[])).strip()
    return '<h2>Series path power tree</h2><p>' + escape(tree['notice']) + '</p><pre>' + escape(summary) + '</pre>' + diagram + ''.join(sections)
