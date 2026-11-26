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


def _diagram_display(bundle, source_voltage):
    request = bundle.get('request') or {}
    view = bundle.get('view_settings') or {}
    if ('show_exact_voltages' not in request and 'show_exact_voltages' not in view and
            request.get('voltage_tolerance_pct') is None):
        return None
    from .voltage_tolerance import show_exact
    return {'source_voltage_V': source_voltage, 'exact': show_exact(bundle)}

def build_series_power_tree(bundle, *, representative_lengths=False):
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
    from .series_path_diagram import copper_lengths
    path_geometry = geometry.get('path_geometry') or bundle.get('path_geometry') or {}
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
    for node in copper:
        node['wire_lengths'] = copper_lengths(node, path_geometry, representative=representative_lengths)
    nets = [node['net'] for node in copper if node['net'] is not None]
    repeated = len(nets) != len(set(nets))
    if repeated:
        for node in copper:
            node.update(_metrics(None, None, None))
            node['accounting_status'] = 'unavailable_repeated_net'
            node['accounting_notice'] = ('Repeated physical nets can bypass ordered stages; '
                                         'per-occurrence copper current, loss, voltage and efficiency cannot be allocated from this path.')
    return dict(schema='series-power-tree-1', status='solved' if result else 'topology_only',
                display=_diagram_display(bundle, _finite(result.get('source_voltage_V'))),
                source_sha256=geometry.get('source_sha256', bundle.get('source_sha256')),
                feasible=result.get('feasibility', {}).get('feasible'), nodes=nodes,
                edges=[dict(source=a['id'], target=b['id']) for a, b in zip(nodes, nodes[1:])],
                summary=_metrics(source_power, load_power, current, efficiency=feasible),
                notice='DC series-path accounting; copper voltages are current-weighted electrode values. '
                       'Each reviewed pad group is counted once; individual pad-current sharing is unknown. '
                       'Stage efficiency means transmitted DC power / incoming DC power, not converter efficiency. '
                       'Return-path loss is excluded unless explicitly modeled. Infeasible results are diagnostics; efficiency is unavailable. '
                       'Wire lengths use shortest planar saved track/arc endpoint chains only; via barrels and zone travel are excluded. '
                       'Estimated straight distances are not routed copper lengths.' +
                       (' Repeated physical nets prevent per-occurrence copper accounting; those metrics are unavailable.' if repeated else ''))


def build_power_result_tree(bundle):
    """Use reviewed stages or build the solved bus and independent load endpoints."""
    series = build_series_power_tree(bundle)
    if series is not None:
        return series
    result = bundle.get('result') or {}
    source_voltage = _finite(result.get('source_voltage_V'))
    source_current = _finite(result.get('source_current_A'))
    if source_voltage is None or source_current is None:
        return None

    request = bundle.get('request') or {}
    geometry = bundle.get('geometry') or (bundle.get('mesh') or {}).get('geometry') or {}
    units = bundle.get('terminal_units') or result.get('terminal_units') or {}
    terminal_rows = geometry.get('terminals', [])
    label_counts = Counter(row.get('label') for row in terminal_rows)
    terminals = {str(row['id']): row for row in terminal_rows}
    terminals.update({str(row['label']): row for row in terminal_rows
                      if row.get('label') and label_counts[row['label']] == 1})

    def pins(values, labels=()):
        selected = []
        for index, value in enumerate(values):
            if value is not None:
                row = terminals.get(str(value), {})
                label = row.get('label') or (labels[index] if index < len(labels) else value)
                selected.append(dict(id=str(row.get('id', value)), label=str(label), net=row.get('net')))
        return selected

    source_pins = pins(units.get('source_terminals') or request.get('source_terminals') or
                       [request.get('source_terminal', request.get('source'))],
                       units.get('source_labels', []))
    # Match grouped pad metadata by stable unit ID. Older single-pad results
    # can still display the reviewed request's single pad.
    evidence = {str(load['id']): load for load in units.get('loads', []) if 'id' in load}
    specs = request.get('sinks') or []
    requested = {str(spec.get('id') or spec.get('terminal') or (spec.get('terminals') or [''])[0]): spec
                 for spec in specs}
    solved = result.get('sinks')
    if not solved:
        solved = [dict(label='Load', current_A=result.get('sink_current_A'),
                       voltage_V=result.get('sink_voltage_V'),
                       voltage_drop_V=result.get('voltage_drop_V'))]
    loads = []
    path_geometry = geometry.get('path_geometry') or bundle.get('path_geometry') or {}
    from .series_path_diagram import copper_lengths
    net = request.get('net') or geometry.get('net')
    for index, row in enumerate(solved, 1):
        identifier = str(row.get('id', ''))
        unit = evidence.get(identifier, {})
        spec = requested.get(identifier, {})
        labels = unit.get('labels', [])
        ids = unit.get('terminals') or row.get('terminals') or spec.get('terminals') or [
            spec.get('terminal') or (request.get('sink_terminal') if len(solved) == 1 else None)]
        electrodes = pins(ids, labels)
        current, voltage = _finite(row.get('current_A')), _finite(row.get('voltage_V'))
        drop = _finite(row.get('voltage_drop_V'))
        if drop is None and voltage is not None:
            drop = source_voltage - voltage
        load = dict(id=f'load-{index}', terminal_unit_id=identifier or None, kind='load',
                    label=str(row.get('label') or f'Load {index}'), pins=electrodes,
                    current_A=current, voltage_V=voltage, voltage_drop_V=drop,
                    input_power_W=_power(voltage, current),
                    source_referenced_drop_power_W=_power(drop, current))
        if path_geometry and source_pins and electrodes and net:
            load['wire_lengths'] = copper_lengths({'net': net, 'incoming_pins': source_pins,
                                                   'outgoing_pins': electrodes}, path_geometry,
                                                  representative=True)
        loads.append(load)
    load_power = _sum(load['input_power_W'] for load in loads)
    source_power = _power(source_voltage, source_current)
    cold_only = result.get('joule_feedback', {}).get('solution_basis') == 'cold_baseline' or (
        bool(result.get('joule_feedback')) and result['joule_feedback'].get('converged') is False)
    feasible = (result.get('feasibility') or {}).get('feasible')
    if any(load['voltage_V'] is not None and load['voltage_V'] < 0 for load in loads):
        feasible = False
    accepted = feasible is not False
    metrics = _metrics(source_power, load_power, source_current, efficiency=accepted)
    # Keep the solver's physical power separately from signed terminal
    # accounting. A common power field cannot allocate individual path losses.
    loss = _finite(result.get('total_power_W'))
    copper = dict(id='copper', kind='copper', label=str(net or 'Selected copper'), net=net,
                  current_A=source_current, input_power_W=source_power, output_power_W=load_power,
                  loss_W=loss, voltage_before_V=source_voltage,
                  worst_path_drop_V=_finite(result.get('voltage_drop_V')),
                  modeled_copper_loss_W=_finite(result.get('conductor_power_W')),
                  modeled_contact_or_component_loss_W=_finite(result.get('component_power_W')))
    basis = 'cold_baseline' if cold_only else 'coupled_steady' if result.get('joule_feedback') else 'dc'
    return dict(schema='rail-power-tree-1', status='solved', solution_basis=basis,
                display=_diagram_display(bundle, source_voltage),
                source_sha256=geometry.get('source_sha256', bundle.get('source_sha256')),
                feasible=feasible, summary=dict(metrics, modeled_loss_W=loss),
                nodes=[dict(id='source', kind='source', label='Source', pins=source_pins,
                            voltage_V=source_voltage, current_A=source_current,
                            output_power_W=source_power), copper, *loads],
                edges=[dict(source='source', target='copper'),
                       *[dict(source='copper', target=load['id']) for load in loads]],
                notice=('Common-route loss is shown once on the copper block. Individual drops are measured '
                        'from the source to each load group. Delivered power is reported at each load. '
                        'Each drop contribution is current times source-to-load voltage drop. '
                        'Shared copper loss and individual pad current are unallocated. ' +
                        ('Joule coupling stopped. Values are the cold reference. ' if cold_only else '') +
                        ('The voltage/current constraints reject this operating point.' if not accepted else '')))

def series_path_tree(path, inventory):
    """Build a topology-only tree from a reviewed inferred/saved path."""
    from .series_editor import parse_saved_path
    return build_series_power_tree(dict(request=parse_saved_path(path, inventory), geometry=inventory))


def tree_text(tree):
    """Compact native-output text, retaining every stage, net and pin group."""
    if tree is None:
        return ''
    lines = [tree['notice']]
    display = tree.get('display')
    def pins(values):
        return ', '.join(pin['label'] for pin in values) or 'Unknown'
    if tree.get('summary'):
        lines.append('Whole path: ' + metric_text(tree['summary'], display))
    for node in tree['nodes']:
        lines.append('\n' + node['label'] + ' [' + node['kind'] + ']')
        lines.append(metric_text(node, display))
        if node.get('accounting_notice'):
            lines.append(node['accounting_notice'])
        if node.get('pins'):
            lines.append('Pins: ' + pins(node['pins']))
        for route in node.get('wire_lengths', []):
            lines.append(route.get('label') or
                         f"Representative saved planar chain: {route['length_mm']:.6g} mm")
        for row in [node, *node.get('parts', [])]:
            if row is not node:
                lines.append(str(row['reference']) + ': ' + metric_text(row, display))
            if 'incoming_pins' in row:
                lines.append('Incoming: ' + pins(row['incoming_pins']) + ' → outgoing: ' + pins(row['outgoing_pins']))
    return '\n'.join(lines)


def metric_text(row, display=None):
    """Readable values shared by native diagrams, exports and text details."""
    labels = [('voltage_V', 'V', 'V'), ('voltage_before_V', 'Vin', 'V'), ('voltage_after_V', 'Vout', 'V'),
              ('current_A', 'I', 'A'), ('voltage_drop_V', 'drop', 'V'),
              ('worst_path_drop_V', 'worst path drop', 'V'), ('loss_W', 'loss', 'W'),
              ('input_power_W', 'Pin', 'W'), ('output_power_W', 'Pout', 'W'),
              ('source_referenced_drop_power_W', 'drop contribution', 'W')]
    from .voltage_tolerance import voltage_text
    output = []
    for key, name, unit in labels:
        value = row.get(key)
        if value is None:
            continue
        if unit == 'V' and display:
            text = voltage_text(display, value, exact=display['exact'], drop=key in ('voltage_drop_V', 'worst_path_drop_V'))
        else:
            text = f'{value:.6g} {unit}'
        output.append(f'{name} {text}')
    if row.get('efficiency_fraction') is not None:
        output.append(f"transmission {100 * row['efficiency_fraction']:.6g}%")
    return ' · '.join(output) or 'Not solved'


def _tree_images(tree):
    """Rasterize the same annotated topology in readable PDF-height sections."""
    import base64
    import io
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import FancyBboxPatch
    from .series_path_diagram import diagram_layout

    layout = diagram_layout(tree)
    width, height = layout['width'], layout['height']
    commands = sorted(layout['commands'], key=lambda item: item['kind'] == 'text')
    # Choose breaks before a block near the page edge to avoid split labels.
    boundaries = sorted({int(item['y']) for item in commands if item['kind'] == 'rect'})
    top = 0
    while top < height:
        target = min(top + 1350, height)
        bottom = height if target == height else max((y for y in boundaries if top + 700 < y <= target), default=target)
        figure = Figure(figsize=(9, 9 * (bottom - top) / width), dpi=120)
        FigureCanvasAgg(figure)
        axes = figure.add_axes([0, 0, 1, 1])
        axes.set_xlim(0, width)
        axes.set_ylim(bottom, top)
        axes.axis('off')
        for item in commands:
            if item['kind'] == 'line':
                if max(item['y1'],item['y2']) >= top and min(item['y1'],item['y2']) <= bottom:
                    axes.plot([item['x1'],item['x2']], [item['y1'],item['y2']], color='#426878', linewidth=.8)
            elif item['kind'] == 'rect':
                if item['y']+item['height'] < top or item['y'] > bottom:
                    continue
                axes.add_patch(FancyBboxPatch((item['x'],item['y']),item['width'],item['height'],
                                             boxstyle='round,pad=0,rounding_size=5',
                                             facecolor=item['fill'],edgecolor=item['stroke'],linewidth=.7))
            elif top <= item['y'] < bottom:
                axes.text(item['x'],item['y'],item['text'],va='top',fontsize=item['size']*.58,
                          parse_math=False,clip_on=True)
        output = io.BytesIO()
        figure.savefig(output, format='png', dpi=120)
        yield base64.b64encode(output.getvalue()).decode('ascii')
        top = bottom

def tree_html(tree, *, raster=False):
    """Offline compact vector topology and per-node evidence for HTML/PDF."""
    if tree is None:
        return ''
    from .series_path_diagram import diagram_svg
    if raster:
        diagram = ''.join('<img alt="Annotated power path diagram" src="data:image/png;base64,' +
                          image + '">' for image in _tree_images(tree))
    else:
        diagram = diagram_svg(tree)
    sections = []
    for row in tree['nodes']:
        detail = tree_text(dict(tree, notice='', nodes=[row], summary=None)).strip()
        sections.append('<h3>' + escape(row['label'] + ' · ' + row['kind']) + '</h3><pre>' + escape(detail) + '</pre>')
    summary = tree_text(dict(tree, notice='', nodes=[])).strip()
    title = 'Solved rail power tree' if tree['schema'] == 'rail-power-tree-1' else 'Series path power tree'
    return '<h2>' + title + '</h2><p>' + escape(tree['notice']) + '</p><pre>' + escape(summary) + '</pre>' + diagram + ''.join(sections)
