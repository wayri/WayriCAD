"""Readable, source-bound path and network context for offline reports.

Only explicit saved relationships are shown. This module never opens a board,
resolves an input path, or guesses a connection from a similar net or pin name.
"""
from __future__ import annotations

from html import escape
import math
import re


UNKNOWN = 'Unknown'
_PATH_KEYS = ('board_path', 'source_path', 'study_input_path', 'model_path', 'ibis_path')
_CHILD_KEYS = ('request', 'geometry', 'batch', 'cases', 'electrical', 'return_conduction',
               'report', 'source', 'import_source', 'source_result', 'power_tree', 'shared_returns')


def _value(value):
    if value is None or value == '':
        return UNKNOWN
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, '.9g') if math.isfinite(value) else UNKNOWN
    return str(value)


def _joined(values):
    if isinstance(values, (tuple, list)):
        return ', '.join(_value(value) for value in values) if values else UNKNOWN
    return _value(values)


def _section(title, columns, rows):
    return {'title': title, 'columns': tuple(columns),
            'rows': [tuple(_value(value) for value in row) for row in rows]}


def _source_rows(bundle):
    rows, seen = [], set()

    def visit(node, scope, depth):
        if depth > 6 or not isinstance(node, dict):
            return
        for key in _PATH_KEYS:
            path = node.get(key)
            if isinstance(path, str) and path:
                row = (scope, key.replace('_', ' '), path)
                if row not in seen:
                    seen.add(row); rows.append(row)
        # EMerge records its verified source as {path, sha256}. This is a
        # filesystem path only in these explicit source-custody objects.
        if scope.endswith((' / source', ' / import_source', ' / source_result')):
            path = node.get('path')
            if isinstance(path, str) and path:
                row = (scope, 'recorded source', path)
                if row not in seen:
                    seen.add(row); rows.append(row)
        fingerprints = node.get('source_fingerprints')
        if isinstance(fingerprints, dict):
            for path in fingerprints:
                if isinstance(path, str) and path:
                    row = (scope, 'fingerprinted source', path)
                    if row not in seen:
                        seen.add(row); rows.append(row)
        for key in _CHILD_KEYS:
            child = node.get(key)
            if isinstance(child, dict):
                visit(child, scope+' / '+key, depth+1)
            elif isinstance(child, list):
                for index, item in enumerate(child):
                    if isinstance(item, dict):
                        visit(item, scope+' / '+key+' '+str(index+1), depth+1)

    visit(bundle, 'Result', 0)
    return rows


def _terminal_index(geometry):
    index = {}
    for row in geometry.get('terminals', []):
        if not isinstance(row, dict):
            continue
        for key in ('id', 'pad_uuid', 'label'):
            if row.get(key) is not None:
                index.setdefault(str(row[key]), row)
    return index


def _pins(values, terminals, labels=None):
    if not isinstance(values, list):
        values = [values] if values is not None else []
    labels = labels if isinstance(labels, list) and len(labels) == len(values) else None
    shown = []
    for index, value in enumerate(values):
        row = terminals.get(str(value), {})
        label = labels[index] if labels else row.get('label')
        number = row.get('pad_number', row.get('pin_number'))
        if row.get('reference') and number is not None:
            identity = str(row['reference'])+'.'+str(number)
            label = identity+(' ('+str(label)+')' if label and label != identity else '')
        shown.append(str(label or value))
    return _joined(shown)


def _terminal_net(values, terminals):
    if not isinstance(values, list):
        values = [values] if values is not None else []
    nets = [terminals.get(str(value), {}).get('net') for value in values]
    known = list(dict.fromkeys(str(net) for net in nets if net))
    return _joined(known) if len(known) == 1 else UNKNOWN


def _model(branch):
    details = []
    if branch.get('model'):
        details.append(str(branch['model']))
    for key, unit in (('resistance_ohm', 'Ω'), ('inductance_h', 'H'), ('fixed_drop_v', 'V')):
        if branch.get(key) is not None:
            details.append(key.replace('_', ' ')+': '+_value(branch[key])+' '+unit)
    diode = branch.get('diode')
    if isinstance(diode, dict):
        details.extend(name+': '+_value(diode.get(key))+' '+unit for key, name, unit in (
            ('vf_ref_v', 'Diode Vf ref', 'V'), ('reference_current_a', 'I ref', 'A'),
            ('ideality', 'Ideality', ''), ('temperature_c', 'Temperature', '°C')))
    return '; '.join(details) if details else UNKNOWN


def _pi_sections(bundle):
    cases = []
    if isinstance(bundle.get('request'), dict) and (bundle['request'].get('net') or bundle['request'].get('source_terminal')):
        cases.append(('Result', bundle))
    batch = bundle.get('batch', {})
    if isinstance(batch, dict):
        for index, case in enumerate(batch.get('cases', [])):
            if not isinstance(case, dict):
                continue
            electrical = case.get('electrical')
            if isinstance(electrical, dict):
                cases.append((str(case.get('name') or case.get('id') or 'Case '+str(index+1)), electrical))
    if not cases:
        return []
    networks, endpoints, stages = [], [], []
    for name, case in cases:
        request = case.get('request', case)
        geometry = case.get('geometry', {})
        result = case.get('result', {})
        units = case.get('terminal_units', {})
        if not isinstance(request, dict):
            request = {}
        if not isinstance(geometry, dict):
            geometry = {}
        if not isinstance(result, dict):
            result = {}
        if not isinstance(units, dict):
            units = {}
        terminals = _terminal_index(geometry)
        nets = geometry.get('nets')
        networks.append((name, request.get('net'), _joined(nets) if isinstance(nets, list)
                         else geometry.get('net'), case.get('model'),
                         result.get('sink_current_A', request.get('sink_current'))))
        sources = units.get('source_terminals') or request.get('source_terminals') or request.get('source_terminal')
        endpoints.append((name, 'Source', _terminal_net(sources, terminals),
                          _pins(sources, terminals, units.get('source_labels')),
                          result.get('source_current_A')))
        loads = units.get('loads') if isinstance(units.get('loads'), list) else None
        requested = request.get('sinks') if isinstance(request.get('sinks'), list) else None
        if not requested:
            requested = [dict(terminal=request.get('sink_terminal'),
                              terminals=request.get('sink_terminals'), current_A=request.get('sink_current'))]
        for index, sink in enumerate(requested):
            if not isinstance(sink, dict):
                continue
            unit = loads[index] if loads and index < len(loads) and isinstance(loads[index], dict) else {}
            pins = unit.get('terminals') or sink.get('terminals') or sink.get('terminal')
            current = unit.get('current_A', sink.get('current_A'))
            if current is None and index == 0:
                current = sink.get('current_A', request.get('sink_current'))
            endpoints.append((name, 'Load '+str(index+1), _terminal_net(pins, terminals),
                              _pins(pins, terminals, unit.get('labels')), current))
        series = request.get('series')
        if isinstance(series, list):
            for index, stage in enumerate(series):
                if not isinstance(stage, dict):
                    continue
                for parallel, branch in enumerate([stage, *(stage.get('parallel') or [])]):
                    if not isinstance(branch, dict):
                        continue
                    from_pins = branch.get('from_pads') or branch.get('from_terminals') or branch.get('from_pad')
                    to_pins = branch.get('to_pads') or branch.get('to_terminals') or branch.get('to_pad')
                    stages.append((name, str(index+1)+(' parallel '+str(parallel) if parallel else ''),
                        _terminal_net(from_pins, terminals), _pins(from_pins, terminals),
                        branch.get('reference', branch.get('id')), _model(branch),
                        _pins(to_pins, terminals), _terminal_net(to_pins, terminals)))
    sections = [_section('PI nets and series-network scope',
                ('Case', 'Requested net', 'Solved nets', 'Model', 'Sink current A'), networks),
                _section('PI source and load pin groups',
                ('Case', 'Role', 'Net', 'Reference.pin numbers', 'Total current A'), endpoints)]
    if stages:
        sections.append(_section('Explicit PI series stages',
            ('Case', 'Stage', 'From net', 'From pins', 'Component', 'Declared model', 'To pins', 'To net'), stages))
    if len(networks) > 1:
        for network in networks:
            net = network[2] if network[2] != UNKNOWN else network[1]
            title = 'PI case '+network[0]+' · Net '+_value(net)
            sections.append(_section(title+' · network',
                ('Case', 'Requested net', 'Solved nets', 'Model', 'Sink current A'), [network]))
            sections.append(_section(title+' · source and load pins',
                ('Case', 'Role', 'Net', 'Reference.pin numbers', 'Total current A'),
                [row for row in endpoints if row[0] == network[0]]))
            if stages:
                sections.append(_section(title+' · series stages',
                    ('Case', 'Stage', 'From net', 'From pins', 'Component', 'Declared model', 'To pins', 'To net'),
                    [row for row in stages if row[0] == network[0]]))
    return sections


def _si_sections(bundle):
    cases = []
    if isinstance(bundle.get('path'), dict):
        cases.append(('Result', bundle, {}))
    for index, case in enumerate(bundle.get('cases', [])):
        if isinstance(case, dict):
            cases.append((str(case.get('id') or 'Case '+str(index+1)), case.get('report', {}), case))
    if not cases:
        return []
    routes, segments = [], []
    for name, report, case in cases:
        report = report if isinstance(report, dict) else {}
        path = report.get('path', {})
        path = path if isinstance(path, dict) else {}
        routes.append((name, case.get('net'), path.get('net_name'),
            case.get('start', path.get('start_pad')), case.get('end', path.get('end_pad')),
            path.get('reference_layer', case.get('reference')),
            path.get('length_mm'), case.get('status', report.get('status'))))
        for index, segment in enumerate(path.get('segments', [])):
            if not isinstance(segment, dict):
                continue
            segments.append((name, index+1, segment.get('kind'), segment.get('layer'),
                _joined(segment.get('start_mm')), _joined(segment.get('end_mm')),
                segment.get('length_mm'), segment.get('reference_net'),
                segment.get('reference_layer'), segment.get('impedance_ohm'), segment.get('status')))
    sections = [_section('SI signal paths and endpoints',
        ('Case', 'Requested net', 'Reported net', 'Source pin', 'Receiver pin',
         'Reference layer', 'Length mm', 'Status'), routes)]
    if segments:
        sections.append(_section('Stored SI route sections',
            ('Case', 'Section', 'Kind', 'Layer', 'Start XY mm', 'End XY mm',
             'Length mm', 'Reference net', 'Reference layer', 'Impedance Ω', 'Status'), segments))
    if len(routes) > 1:
        for route in routes:
            net = route[2] if route[2] != UNKNOWN else route[1]
            title = 'SI net '+_value(net)+' · Path '+_value(route[3])+' → '+_value(route[4])
            sections.append(_section(title,
                ('Case', 'Requested net', 'Reported net', 'Source pin', 'Receiver pin',
                 'Reference layer', 'Length mm', 'Status'), [route]))
            local = [row for row in segments if row[0] == route[0]]
            if local:
                sections.append(_section(title+' · route sections',
                    ('Case', 'Section', 'Kind', 'Layer', 'Start XY mm', 'End XY mm',
                     'Length mm', 'Reference net', 'Reference layer', 'Impedance Ω', 'Status'), local))
    return sections


def _thermal_sections(bundle):
    network = bundle.get('thermal_network', {})
    thermal = bundle.get('quick_therm', {})
    if not isinstance(network, dict) or not isinstance(thermal, dict):
        return []
    components = network.get('components') or thermal.get('components')
    if not isinstance(components, list) or not components:
        return []
    rows = []
    for component in components:
        if not isinstance(component, dict):
            continue
        reference, pad = component.get('reference'), component.get('source_pad_number')
        pins = str(reference)+'.'+str(pad) if reference and pad is not None else UNKNOWN
        rows.append((reference, component.get('source_net'), pins, component.get('heat_path'),
                     component.get('power_w'), component.get('source_distribution')))
    return [_section('Thermal component source nets and heat paths',
        ('Component', 'Source net', 'Source reference.pin', 'Heat path', 'Power W', 'Source mapping'), rows)]


def _power_tree_sections(bundle):
    tree = bundle.get('power_tree', bundle)
    if not isinstance(tree, dict) or not isinstance(tree.get('nodes'), list):
        return []
    nodes = [row for row in tree['nodes'] if isinstance(row, dict)]
    edges = [row for row in tree.get('edges', []) if isinstance(row, dict)]
    sections = [_section('Declared power-tree nodes',
        ('ID', 'Kind', 'Label', 'Net', 'Return net', 'Reference', 'Isolation domain', 'Reviewed'),
        [(row.get('id'), row.get('kind'), row.get('label'), row.get('net'), row.get('return_net'),
          row.get('reference'), row.get('domain'), row.get('reviewed')) for row in nodes])]
    if edges:
        sections.append(_section('Declared energy-flow edges (not electrical shorts)',
            ('Source node', 'Target node', 'Reviewed'),
            [(row.get('source'), row.get('target'), row.get('reviewed')) for row in edges]))
    return sections


def _emerge_sections(bundle):
    config = bundle.get('config')
    if not isinstance(config, dict) or not isinstance(bundle.get('port_count'), int):
        return []
    region = bundle.get('region', {})
    region = region if isinstance(region, dict) else {}
    physical = config.get('mode') == 'pcb_region'
    sections = [_section('EMerge recorded network scope',
        ('Study mode', 'Geometry scope', 'Signal net', 'Reference net', 'Port count', 'PCB pin identity'),
        [(config.get('mode'), bundle.get('model_scope'),
          config.get('signal_net') if physical else None,
          config.get('reference_net') if physical else None,
          bundle.get('port_count'), None)])]
    ports = region.get('ports', []) if physical else []
    if isinstance(ports, list) and ports:
        sections.append(_section('EMerge declared boundary ports (not PCB pins)',
            ('Port number', 'Signal net', 'Reference net', 'Boundary start XY mm',
             'Boundary end XY mm', 'Width mm', 'PCB pin number'),
            [(port.get('number'), port.get('signal_net'), port.get('reference_net'),
              _joined(port.get('a_mm')), _joined(port.get('b_mm')), port.get('width_mm'), None)
             for port in ports if isinstance(port, dict)]))
    return sections


def report_context(bundle):
    """Return ordered, compact tables of provided source, net, pin and path facts."""
    if not isinstance(bundle, dict):
        return []
    sections = []
    sources = _source_rows(bundle)
    if sources:
        sections.append(_section('Full recorded source paths', ('Scope', 'Role', 'Path as stored'), sources))
    sections.extend(_pi_sections(bundle))
    sections.extend(_si_sections(bundle))
    sections.extend(_thermal_sections(bundle))
    sections.extend(_power_tree_sections(bundle))
    sections.extend(_emerge_sections(bundle))
    return sections


def _scope_heading(sections):
    endpoint_rows = next((item['rows'] for item in sections
                          if item['title'] == 'PI source and load pin groups'), [])

    def pi_path(case):
        group = [row for row in endpoint_rows if row[0] == case]
        source = next((row[3] for row in group if row[1] == 'Source'), UNKNOWN)
        loads = [row[1]+': '+row[3] for row in group if row[1].startswith('Load')]
        return ' · Path: '+source+' → '+('; '.join(loads) if loads else UNKNOWN)

    for section in sections:
        if section['title'] == 'PI nets and series-network scope':
            rows = section['rows']
            if len(rows) > 1:
                return 'Combined PI case scope — '+ '; '.join(
                    row[0]+': '+(row[2] if row[2] != UNKNOWN else row[1])+pi_path(row[0]) for row in rows)
            if rows:
                net = rows[0][2] if rows[0][2] != UNKNOWN else rows[0][1]
                return ('Series network: ' if ',' in net or '→' in net else 'Net: ')+net+pi_path(rows[0][0])
        if section['title'] == 'SI signal paths and endpoints':
            rows = section['rows']
            if len(rows) > 1:
                return 'Combined SI signal-path scope — '+ '; '.join(
                    (row[2] if row[2] != UNKNOWN else row[1])+': '+row[3]+' → '+row[4]
                    for row in rows)
            if rows:
                row = rows[0]
                net = row[2] if row[2] != UNKNOWN else row[1]
                return 'Net: '+net+' · Path: '+row[3]+' → '+row[4]
        if section['title'] == 'Thermal component source nets and heat paths':
            nets = list(dict.fromkeys(row[1] for row in section['rows'] if row[1] != UNKNOWN))
            return 'Thermal source net: '+nets[0] if len(nets) == 1 else 'Combined thermal source nets: '+_joined(nets)
        if section['title'] == 'EMerge recorded network scope':
            row = section['rows'][0]
            if row[0] == 'pcb_region':
                ports = next((item['rows'] for item in sections
                              if item['title'] == 'EMerge declared boundary ports (not PCB pins)'), [])
                return ('Net: '+row[2]+' · Reference net: '+row[3]+' · Boundary ports: '+
                        _joined([port[0] for port in ports]))
            return 'EMerge '+row[0]+' template · PCB net and pin path: Unknown'
    return 'Net: Unknown · Path: Unknown'


def report_context_html(bundle):
    """Render context as escaped tables suitable for an offline HTML report."""
    sections = report_context(bundle)
    heading = _scope_heading(sections)
    html = '<section class="report-context" aria-label="Recorded net and path scope"><h2>'+escape(heading)+'</h2>'
    for section in sections:
        html += '<h3>'+escape(section['title'])+'</h3><table><thead><tr>'
        html += ''.join('<th>'+escape(column)+'</th>' for column in section['columns'])
        html += '</tr></thead><tbody>'
        html += ''.join('<tr>'+''.join('<td>'+escape(value)+'</td>' for value in row)+'</tr>'
                        for row in section['rows'])
        html += '</tbody></table>'
    return html+'</section>'


def _report_heading(document):
    """Find the visible title, excluding script/style text that resembles HTML."""
    protected = [(match.start(), match.end()) for match in re.finditer(
        r'<(script|style)\b[^>]*>.*?</\1\s*>', document, re.I | re.S)]
    for match in re.finditer(r'<h1\b[^>]*>.*?</h1\s*>', document, re.I | re.S):
        if not any(start <= match.start() < end for start, end in protected):
            return match
    return None


def _report_end(document, after):
    protected = [(match.start(), match.end()) for match in re.finditer(
        r'<(script|style)\b[^>]*>.*?</\1\s*>', document, re.I | re.S)]
    main_tags = list(re.finditer(r'</?main\b[^>]*>', document[:after], re.I))
    inside_main = bool(main_tags and not main_tags[-1].group().lower().startswith('</'))
    pattern = r'</main\s*>' if inside_main else r'</(?:body|html)\s*>'
    for match in re.finditer(pattern, document[after:], re.I):
        position = after+match.start()
        if not any(start <= position < end for start, end in protected):
            return position
    return len(document)


def organize_report(document, bundle):
    """Place recorded scope above all existing plots/data without changing them."""
    if 'data-wayricad-scope="1"' in document:
        return document
    sections = report_context(bundle)
    first = _report_heading(document)
    if not sections or first is None:
        return document
    heading = _scope_heading(sections)
    after = first.end()
    header_tags = list(re.finditer(r'</?header\b[^>]*>', document[:after], re.I))
    if header_tags and not header_tags[-1].group().lower().startswith('</'):
        close = re.search(r'</header\s*>', document[after:], re.I)
        if close:
            after += close.end()
    context = report_context_html(bundle)
    start = ('<section class="report-scoped-body" data-wayricad-scope="1">'
             '<h2>'+escape(heading)+' — plots and data</h2>')
    end = _report_end(document, after)
    return document[:after]+context+start+document[after:end]+'</section>'+document[end:]
