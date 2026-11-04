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


def saved_path_geometry(board):
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
            for fp in board.GetFootprints() for pad in fp.Pads() if pad.GetNetCode() > 0}
    tracks = []
    for item in board.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA) or item.GetNetCode() <= 0:
            continue
        length = float(pcbnew.ToMM(item.GetLength()))
        if math.isfinite(length) and length > 0:
            tracks.append(dict(id=item.m_Uuid.AsString(), net=str(item.GetNetname()),
                layer=int(item.GetLayer()), start_mm=point(item.GetStart()),
                end_mm=point(item.GetEnd()), length_mm=length))
    return dict(schema=1, status='captured', pads=pads, tracks=tracks,
                notice='Planar saved track/arc centerlines only; via barrels and zone travel are not assigned a wire length.')


def _point(value):
    if (isinstance(value, (list, tuple)) and len(value) == 2 and
        all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)):
        return tuple(round(float(v), 9) for v in value)
    return None


def copper_lengths(node, evidence):
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
        graph[a].append((b, length)); graph[b].append((a, length))

    def measured(left, right):
        a, b = _point(left.get('position_mm')), _point(right.get('position_mm'))
        if a is None or b is None:
            return None
        targets = {(layer, b) for layer in right.get('layers', [])}
        queue, distance = [], {}
        for layer in left.get('layers', []):
            key = (layer, a)
            distance[key] = 0.
            heappush(queue, (0., key))
        while queue:
            value, key = heappop(queue)
            if value != distance[key]:
                continue
            if key in targets and value > 0:
                return value
            for other, length in graph.get(key, []):
                total = value + length
                if total < distance.get(other, math.inf):
                    distance[other] = total
                    heappush(queue, (total, other))
        return None

    result = []
    incoming, outgoing = node.get('incoming_pins', []), node.get('outgoing_pins', [])
    for start in incoming:
        for end in outgoing:
            if len(result) >= 2048:
                return result + [dict(status='unavailable', label='Additional pair lengths unavailable: display limit reached.', length_mm=None)]
            left, right = pads.get(start['id'], {}), pads.get(end['id'], {})
            length = measured(left, right) if left.get('net') == right.get('net') == node.get('net') else None
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
                               status=status, label=label + ': ' + detail))
    return result


def diagram_layout(tree):
    """Device-independent drawing commands; every parallel component gets a lane."""
    width, y, commands = 1100, 12, []
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
    def pins(values):
        return ', '.join(pin['label'] for pin in values) or 'Unknown'
    text(30, y, 'Reviewed series path · schematic, not PCB geometry', 18); y += 30
    for node in tree['nodes']:
        if node['kind'] == 'parallel_stage':
            entry = y
            y += text(80, y, node['label'] + ' · parallel stage', 16) + 6
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
                commands.append(dict(kind='rect', x=140, y=start, width=820, height=y-start))
                center = (start + y) / 2
                line(80, center, 140, center); line(960, center, 1020, center)
                y += 8
            line(80, top, 80, y); line(1020, top, 1020, y)
            line(550, top - 8, 80, top - 8); line(80, top - 8, 80, top)
            line(1020, y, 550, y); line(550, y, 550, y + 10); y += 14
        else:
            if commands:
                line(550, y, 550, y + 12)
            y += 16
            label = ('Net ' if node['kind'] == 'copper' else '') + node['label']
            y += text(40, y, label, 16)
            if node.get('pins'):
                y += text(40, y, 'Pins: ' + pins(node['pins']))
            if node['kind'] == 'copper':
                y += text(40, y, wire_length_summary(node), 12)
            metrics = _metric_text(node)
            if metrics:
                y += text(40, y, metrics)
            y += 8
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
            output.append('<rect ' + ' '.join(f'{key}="{command[key]}"' for key in ('x', 'y', 'width', 'height')) + ' fill="#eef5f4" stroke="#426878" rx="5"/>')
        else:
            output.append(f'<text x="{command["x"]}" y="{command["y"] + command["size"]}" '
                          f'font-family="sans-serif" font-size="{command["size"]}" fill="#172c34">{escape(command["text"])}</text>')
    output.append('</svg>')
    return ''.join(output)
