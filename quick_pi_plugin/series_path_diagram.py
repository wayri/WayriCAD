"""Read-only saved-track evidence and a schematic series/parallel diagram.

Length evidence is deliberately narrower than copper connectivity: only exact
same-layer endpoint chains of saved tracks/arcs are measured. Zones, offsets
inside pad copper, and via barrels do not acquire invented routed lengths.
"""
from __future__ import annotations

from collections import defaultdict
from heapq import heappop, heappush
from html import escape
import math
import textwrap


def saved_path_geometry(board, net=None):
    """Capture optional native display evidence without requiring it for a solve.

    Portable analysis adapters may supply electrical geometry without native pad
    centers or tracks. Their wire lengths remain explicitly unavailable.
    """
    def unavailable():
        return dict(schema=1, status='unavailable', pads={}, tracks=[],
                    notice='Native pad centers and saved track geometry are unavailable; routed wire lengths are unknown.')
    if not all(callable(getattr(board, name, None)) for name in ('GetEnabledLayers', 'GetFootprints', 'GetTracks')):
        return unavailable()
    try:
        import pcbnew
    except ImportError:
        return unavailable()
    def point(value):
        return [float(pcbnew.ToMM(value.x)), float(pcbnew.ToMM(value.y))]
    copper = list(board.GetEnabledLayers().CuStack())
    pads = {pad.m_Uuid.AsString(): dict(position_mm=point(pad.GetPosition()),
            layers=[int(layer) for layer in copper if pad.IsOnLayer(layer)], net=str(pad.GetNetname()))
            for fp in board.GetFootprints() for pad in fp.Pads() if pad.GetNetCode() > 0 and (net is None or pad.GetNetname() == net)}
    tracks = []
    for item in board.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA) or item.GetNetCode() <= 0 or (net is not None and item.GetNetname() != net):
            continue
        length = float(pcbnew.ToMM(item.GetLength()))
        if math.isfinite(length) and length > 0:
            tracks.append(dict(id=item.m_Uuid.AsString(), net=str(item.GetNetname()),
                layer=int(item.GetLayer()), start_mm=point(item.GetStart()),
                end_mm=point(item.GetEnd()), length_mm=length))
            if callable(getattr(item, "GetMid", None)):
                tracks[-1].update(kind="arc", mid_mm=point(item.GetMid()))
    return dict(schema=1, status='captured', pads=pads, tracks=tracks,
                notice='Planar saved track/arc centerlines only; via barrels and zone travel are not assigned a wire length.')


def _point(value):
    if (isinstance(value, (list, tuple)) and len(value) == 2 and
        all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)):
        return tuple(round(float(v), 9) for v in value)
    return None


def copper_lengths(node, evidence, *, representative=False):
    """Describe each reviewed pad pair, distinguishing routed and estimated lengths."""
    pads = evidence.get('pads', {}) if isinstance(evidence, dict) else {}
    graph = defaultdict(list)
    for row in evidence.get('tracks', []) if isinstance(evidence, dict) else []:
        if row.get('net') != node.get('net'):
            continue
        start, end = _point(row.get('start_mm')), _point(row.get('end_mm'))
        length = row.get('length_mm')
        layer = row.get('layer')
        if (start is None or end is None or not isinstance(layer, int) or isinstance(layer, bool) or
            not isinstance(length, (int, float)) or isinstance(length, bool) or not math.isfinite(length) or
            length <= 0 or length + 1e-7 < math.dist(start, end)):
            continue
        a, b = (layer, start), (layer, end)
        graph[a].append((b, length, row.get('id'))); graph[b].append((a, length, row.get('id')))

    def endpoints(pins):
        result = {}
        for pin in sorted(pins, key=lambda p: p['id']):
            row = pads.get(pin['id'], {})
            position = _point(row.get('position_mm'))
            if position is not None and row.get('net') == node.get('net'):
                for layer in row.get('layers', []):
                    result.setdefault((layer,position),pin['id'])
        return result

    def measured(starts, ends):
        targets = endpoints(ends)
        roots = endpoints(starts)
        queue, distance, predecessors = [], {}, {}
        for key in roots:
            distance[key] = 0.
            heappush(queue, (0., key))
        while queue and targets:
            value, key = heappop(queue)
            if value != distance[key]:
                continue
            if key in targets and value > 0:
                target = targets[key]
                route = []
                while key in predecessors:
                    key, track = predecessors[key]
                    if track:
                        route.append(track)
                return value, list(reversed(route)), roots[key], target
            for other, length, track in graph.get(key, []):
                total = value + length
                if total < distance.get(other, math.inf):
                    distance[other] = total
                    predecessors[other] = (key, track)
                    heappush(queue, (total, other))
        return None

    result = []
    incoming, outgoing = node.get('incoming_pins', []), node.get('outgoing_pins', [])
    if representative:
        # Multi-source Dijkstra finds the shortest physical pad pair in one pass.
        match = measured(incoming,outgoing)
        if match:
            length, route, start, end = match
            return [dict(from_pad=start,to_pad=end,length_mm=length,status='saved_track_chain',track_ids=route)]
        return []
    for start in incoming:
        for end in outgoing:
            if len(result) >= 2048:
                return result + [dict(status='unavailable', label='Additional pair lengths unavailable: display limit reached.', length_mm=None)]
            left, right = pads.get(start['id'], {}), pads.get(end['id'], {})
            measurement = measured([start], [end])
            length, route = measurement[:2] if measurement is not None else (None, [])
            label = start['label'] + ' → ' + end['label']
            if length is not None:
                status = 'saved_track_chain'
                detail = f'{length:.6g} mm · shortest planar saved track/arc chain'
            else:
                a, b = _point(left.get('position_mm')), _point(right.get('position_mm'))
                if a is not None and b is not None:
                    length, status = math.dist(a, b), 'estimated_straight_distance'
                    detail = f'{length:.6g} mm · estimated straight distance; routed length unknown'
                else:
                    status, detail = 'unavailable', 'wire length unavailable'
            result.append(dict(from_pad=start['id'], to_pad=end['id'], length_mm=length,
                               status=status, label=label + ': ' + detail, track_ids=route))
    return result


def load_track_chains(request, evidence, *, representative=False):
    '''Exact saved-track candidates for each load unit of a single-net solve.'''
    from .service import sink_requests

    try:
        loads = sink_requests(request)
    except ValueError:
        return []
    sources = request.get('source_terminals') or [request.get('source_terminal', request.get('source'))]

    def pins(ids):
        return [dict(id=identity, label=identity) for identity in ids if identity is not None]

    return [copper_lengths(dict(net=request.get('net'), incoming_pins=pins(sources),
                                outgoing_pins=pins(load.get('terminals') or [load.get('terminal')])), evidence, representative=representative)
            for load in loads]


def diagram_layout(tree):
    """Device-independent drawing commands; every parallel component gets a lane."""
    width, y, commands = 1100, 12, []
    palettes = {'source': ('#e2f1fc', '#2476a8'), 'copper': ('#fff2d5', '#ad7316'),
                'load': ('#f1e8fb', '#7950a5'), 'sink': ('#f1e8fb', '#7950a5')}
    def text(x, top, value, size=13):
        nonlocal y
        right = 940 if x == 160 else width - 40
        lines = textwrap.wrap(str(value), width=max(18, int((right - x) / (size * .55))),
                              break_long_words=True, break_on_hyphens=False) or ['']
        for index, line in enumerate(lines):
            commands.append(dict(kind='text', x=x, y=top + index * (size + 6), text=line, size=size))
        return len(lines) * (size + 6)
    def line(x1, y1, x2, y2):
        commands.append(dict(kind='line', x1=x1, y1=y1, x2=x2, y2=y2))
    def arrow(top, bottom):
        line(550, top, 550, bottom)
        line(543, bottom - 7, 550, bottom)
        line(557, bottom - 7, 550, bottom)
    def pins(values):
        return ', '.join(pin['label'] for pin in values) or 'Unknown'
    text(30, y, 'Sequential power path · source to load', 18); y += 28
    text(30, y, 'Blue: source   Amber: copper rail   Green: in-path devices   Violet: load', 12); y += 25
    text(30, y, 'Reviewed series connectivity; return branches are not forward-path stages.', 12); y += 30
    for number, node in enumerate(tree['nodes'], 1):
        if number > 1:
            arrow(y, y + 18); y += 26
        if node['kind'] == 'parallel_stage':
            entry = y
            y += text(80, y, str(number) + '. ' + node['label'] + ' · parallel stage', 16) + 6
            top = y
            line(550, entry, 550, top - 8)
            for part in node.get('parts', []):
                start = y
                y += text(160, y + 6, str(part['reference']) + ' · ' + _model(part), 15) + 6
                y += text(160, y, 'Pins: ' + pins(part['incoming_pins']) + ' → ' + pins(part['outgoing_pins']))
                metrics = _metric_text(part)
                if metrics:
                    y += text(160, y, metrics)
                y += 7
                commands.append(dict(kind='rect', x=140, y=start, width=820, height=y-start,
                                     fill='#e3f4ec', stroke='#258265'))
                center = (start + y) / 2
                line(80, center, 140, center); line(960, center, 1020, center)
                y += 8
            line(80, top, 80, y); line(1020, top, 1020, y)
            line(550, top - 8, 80, top - 8); line(80, top - 8, 80, top)
            line(1020, y, 550, y); line(550, y, 550, y + 10); y += 14
        else:
            start = y
            y += 10
            label = ('Net ' if node['kind'] == 'copper' else '') + node['label']
            y += text(160, y, str(number) + '. ' + label, 16)
            if node.get('pins'):
                y += text(160, y, 'Pins: ' + pins(node['pins']))
            if node['kind'] == 'copper':
                y += text(160, y, wire_length_summary(node), 12)
            metrics = _metric_text(node)
            if metrics:
                y += text(160, y, metrics)
            y += 12
            fill, stroke = palettes.get(node['kind'], ('#e2f1fc', '#2476a8'))
            commands.append(dict(kind='rect', x=140, y=start, width=820, height=y-start,
                                 fill=fill, stroke=stroke))
    return dict(width=width, height=y + 20, commands=commands)


def wire_length_summary(node):
    """Compact length evidence for the canvas; the tree retains every pad pair."""
    rows = node.get('wire_lengths', [])
    summaries = []
    for status, label in (('saved_track_chain', 'Saved track chains'),
                          ('estimated_straight_distance', 'Estimated straight distance')):
        values = [row['length_mm'] for row in rows if row.get('status') == status and
                  isinstance(row.get('length_mm'), (int, float)) and math.isfinite(row['length_mm'])]
        if values:
            low, high = min(values), max(values)
            length = f'{low:.6g}' if low == high else f'{low:.6g}–{high:.6g}'
            summaries.append(f'{label}: {len(values)} pad pair(s), {length} mm' +
                             (' (routed length unknown)' if status == 'estimated_straight_distance' else ''))
    missing = sum(row.get('status') == 'unavailable' and 'from_pad' in row for row in rows)
    if missing or not rows:
        summaries.append('wire length unavailable' + (f': {missing} pad pair(s)' if missing else ''))
    if any(row.get('status') == 'unavailable' and 'from_pad' not in row for row in rows):
        summaries.append('Additional pair lengths unavailable')
    return ' · '.join(summaries) + ' · All pair details in Power and pin details'


def _model(part):
    model = part.get('model', {})
    description = str(model.get('model', '')).strip()
    values = [f'{label} {model[key]:.6g} {unit}' for key, label, unit in
              (('resistance_ohm', 'R', 'Ω'), ('inductance_h', 'L', 'H'), ('fixed_drop_v', 'Vf', 'V'))
              if model.get(key) is not None and model[key] != 0]
    if model.get('diode'):
        diode = model['diode']
        values.append('diode(' + ', '.join(f'{label}={diode[key]:.6g}{unit}' for key, label, unit in
            (('vf_ref_v', 'Vf', 'V'), ('reference_current_a', 'Iref', 'A'),
             ('ideality', 'n', ''), ('temperature_c', 'T', 'C')) if diode.get(key) is not None) + ')')
    parameters = ', '.join(values)
    return ' · '.join(value for value in (description, parameters) if value) or 'reviewed model'


def _metric_text(row):
    return ' · '.join(f'{label} {row[key]:.6g} {unit}' for key, label, unit in
        (('voltage_V', 'V', 'V'), ('voltage_before_V', 'Vin', 'V'), ('voltage_after_V', 'Vout', 'V'),
         ('current_A', 'I', 'A'), ('voltage_drop_V', 'drop', 'V'), ('loss_W', 'loss', 'W'))
        if row.get(key) is not None)


def diagram_svg(tree):
    """Export the same complete schematic as the native scrollable canvas."""
    layout = diagram_layout(tree)
    output = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout["width"]}" height="{layout["height"]}" '
              f'viewBox="0 0 {layout["width"]} {layout["height"]}" role="img" aria-label="Reviewed series path diagram">',
              '<rect width="100%" height="100%" fill="white"/>']
    # Draw wires and boxes behind labels, including all parallel branch lanes.
    for command in sorted(layout['commands'], key=lambda c: c['kind'] == 'text'):
        if command['kind'] == 'line':
            output.append('<line ' + ' '.join(f'{key}="{command[key]}"' for key in ('x1', 'y1', 'x2', 'y2')) + ' stroke="#426878" stroke-width="2"/>')
        elif command['kind'] == 'rect':
            output.append('<rect ' + ' '.join(f'{key}="{command[key]}"' for key in ('x', 'y', 'width', 'height')) +
                          f' fill="{command.get("fill", "#eef5f4")}" stroke="{command.get("stroke", "#426878")}" rx="5"/>')
        else:
            output.append(f'<text x="{command["x"]}" y="{command["y"] + command["size"]}" '
                          f'font-family="sans-serif" font-size="{command["size"]}" fill="#172c34">{escape(command["text"])}</text>')
    output.append('</svg>')
    return ''.join(output)
