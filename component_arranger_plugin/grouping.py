"""Read-only placement scopes from saved schematics and native PCB objects.

Wire distances are millimetres along drawn wires, not air-line distances. Labels
are suggestions until explicitly accepted; proximity never creates an electrical
connection. Schematic coordinates describe circuit grouping, not PCB clearance.
"""

from __future__ import annotations

import heapq
import math
from pathlib import Path
import re


class GroupingError(ValueError):
    """A saved design cannot supply a reliable grouping scope."""


def _parse(text):
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text)
    stack, roots = [], []
    for token in tokens:
        if token == '(':
            node = []
            (stack[-1] if stack else roots).append(node)
            stack.append(node)
        elif token == ')':
            if not stack:
                raise GroupingError('Malformed schematic: unmatched closing parenthesis.')
            stack.pop()
        else:
            if not stack:
                raise GroupingError('Malformed schematic: text outside root expression.')
            if token.startswith('"'):
                token = re.sub(r'\\(["\\])', r'\1', token[1:-1])
            stack[-1].append(token)
    if stack or len(roots) != 1:
        raise GroupingError('Malformed schematic: incomplete or multiple root expressions.')
    return roots[0]


def _children(node, key):
    return [item for item in node if isinstance(item, list) and item and item[0] == key]


def _first(node, key, default=None):
    return next(iter(_children(node, key)), default)


def _value(node, key, default=''):
    item = _first(node, key)
    return item[1] if item and len(item) > 1 else default


def _point(node):
    try:
        return round(float(node[1]), 6), round(float(node[2]), 6)
    except (IndexError, TypeError, ValueError) as exc:
        raise GroupingError('Malformed schematic coordinate.') from exc


def _alphabet(index):
    result = ''
    while True:
        index, rem = divmod(index, 26)
        result = chr(65 + rem) + result
        if index == 0:
            return result
        index -= 1


def _clusters(symbols, edges):
    parent = {s['id']: s['id'] for s in symbols}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for a, b, _ in edges:
        ra, rb = find(a), find(b)
        parent[rb] = ra
    groups = {}
    for symbol in symbols:
        groups.setdefault(find(symbol['id']), []).append(symbol)
    ordered = sorted(groups.values(), key=lambda items: tuple(sorted(s['reference'] + s['id'] for s in items)))
    result = []
    for index, items in enumerate(ordered):
        ids = sorted(s['id'] for s in items)
        result.append({'id': _alphabet(index), 'references': sorted(s['reference'] for s in items),
                       'symbol_ids': ids, 'evidence': [e for a, b, e in edges if a in ids and b in ids]})
    return result


def _pin_locations(symbol, library, warnings):
    lib_id = _value(symbol, 'lib_id')
    definition = library.get(lib_id)
    if definition is None:
        warnings.append(f'{lib_id}: embedded symbol geometry missing; no inferred wire links.')
        return []
    at = _first(symbol, 'at', ['at', '0', '0', '0'])
    origin = _point(at)
    angle = math.radians(float(at[3]) if len(at) > 3 else 0)
    unit = int(_value(symbol, 'unit', '1'))
    mirror = _value(symbol, 'mirror')
    pins = []
    for block in _children(definition, 'symbol'):
        match = re.search(r'_(\d+)_(\d+)$', str(block[1]))
        if match and int(match[1]) not in (0, unit):
            continue
        for pin in _children(block, 'pin'):
            x, y = _point(_first(pin, 'at'))
            # Library coordinates use upward Y; sheet coordinates use downward Y.
            y = -y
            if mirror == 'x':
                y = -y
            elif mirror == 'y':
                x = -x
            pins.append((round(origin[0] + x * math.cos(angle) + y * math.sin(angle), 6),
                         round(origin[1] - x * math.sin(angle) + y * math.cos(angle), 6)))
    if not pins:
        warnings.append(f'{lib_id}: no supported embedded pins; review this symbol explicitly.')
    return sorted(set(pins))


def _on_segment(point, a, b):
    ax, ay = point[0] - a[0], point[1] - a[1]
    bx, by = b[0] - a[0], b[1] - a[1]
    return abs(ax * by - ay * bx) <= 1e-6 and min(a[0], b[0]) - 1e-6 <= point[0] <= max(a[0], b[0]) + 1e-6 and min(a[1], b[1]) - 1e-6 <= point[1] <= max(a[1], b[1]) + 1e-6


def _wire_graph(root, pins, labels):
    segments = []
    endpoints = set()
    for wire in _children(root, 'wire'):
        pts = _first(wire, 'pts', [])
        coords = [_point(x) for x in _children(pts, 'xy')]
        for a, b in zip(coords, coords[1:]):
            segments.append((a, b))
            endpoints.update((a, b))
    junctions = {_point(_first(j, 'at')) for j in _children(root, 'junction')}
    # Wire endpoints connect T branches. Crossings without junctions do not connect.
    split_points = endpoints | junctions | set(pins) | {l['point'] for l in labels}
    graph = {p: {} for p in split_points}
    for a, b in segments:
        points = sorted((p for p in split_points if _on_segment(p, a, b)), key=lambda p: math.dist(a, p))
        for p, q in zip(points, points[1:]):
            distance = math.dist(p, q)
            graph[p][q] = graph[q][p] = distance
    return graph


def _distances(graph, starts, limit=math.inf):
    distances = {p: 0.0 for p in starts}
    queue = [(0.0, p) for p in starts]
    heapq.heapify(queue)
    while queue:
        distance, point = heapq.heappop(queue)
        if distance != distances[point]:
            continue
        for target, step in graph.get(point, {}).items():
            value = distance + step
            if value <= limit and value < distances.get(target, math.inf):
                distances[target] = value
                heapq.heappush(queue, (value, target))
    return distances


def infer_schematic_groups(path, max_wire_mm=25.0, include_label_links=False,
                           include_global_links=False, proximity_mm=None):
    """Infer saved-sheet clusters and return separately reviewable label links.

    Args:
        path: Root .kicad_sch path. Child sheet files are read relative to parents.
        max_wire_mm: Maximum drawn shortest path between any two component pins.
        include_label_links: Explicit acceptance of local and hierarchical labels.
        include_global_links: Explicit acceptance of global-label connections.
        proximity_mm: Optional graphical-distance grouping heuristic in mm.

    Returns:
        JSON-compatible clusters, symbols, label_links, warnings and thresholds.
        Label-link cluster IDs always refer to the pre-acceptance wire clusters.
    """
    if not isinstance(max_wire_mm, (int, float)) or isinstance(max_wire_mm, bool) or not math.isfinite(max_wire_mm) or max_wire_mm <= 0:
        raise GroupingError('Wire-length threshold must be a positive finite number in mm.')
    if proximity_mm is not None and (not isinstance(proximity_mm, (int, float)) or isinstance(proximity_mm, bool) or not math.isfinite(proximity_mm) or proximity_mm <= 0):
        raise GroupingError('Proximity threshold must be a positive finite number in mm.')
    symbols, edges, label_records, warnings = [], [], [], []

    def load(filename, sheet_path, ancestry):
        filename = Path(filename).resolve()
        if filename in ancestry:
            raise GroupingError('Recursive schematic sheet file detected.')
        try:
            root = _parse(filename.read_text(encoding='utf-8-sig'))
        except UnicodeError as exc:
            raise GroupingError(f'Cannot decode schematic {filename.name} as UTF-8.') from exc
        except OSError as exc:
            raise GroupingError(f'Cannot read schematic {filename.name}: {exc.strerror}.') from exc
        if not root or root[0] != 'kicad_sch':
            raise GroupingError('Expected a saved KiCad schematic (.kicad_sch).')
        current_path = sheet_path or '/' + _value(root, 'uuid', filename.stem)
        library = {s[1]: s for s in _children(_first(root, 'lib_symbols', []), 'symbol')}
        local_symbols = []
        for node in _children(root, 'symbol'):
            props = {p[1]: p[2] for p in _children(node, 'property') if len(p) > 2}
            ref = props.get('Reference', '?')
            for project in _children(_first(node, 'instances', []), 'project'):
                for instance in _children(project, 'path'):
                    if instance[1].rstrip('/') == current_path.rstrip('/'):
                        ref = _value(instance, 'reference', ref)
            symbol = {'id': current_path + '/' + _value(node, 'uuid', ref), 'reference': ref,
                      'sheet_path': current_path, 'position_mm': _point(_first(node, 'at')),
                      'pins_mm': _pin_locations(node, library, warnings)}
            symbols.append(symbol)
            local_symbols.append(symbol)
        labels = []
        for kind in ('label', 'global_label', 'hierarchical_label'):
            for label in _children(root, kind):
                labels.append({'kind': kind, 'name': label[1], 'point': _point(_first(label, 'at')),
                               'sheet_path': current_path})
        graph = _wire_graph(root, [p for s in local_symbols for p in s['pins_mm']], labels)
        for index, symbol in enumerate(local_symbols):
            distances = _distances(graph, symbol['pins_mm'], max_wire_mm)
            for other in local_symbols[index + 1:]:
                distance = min((distances.get(p, math.inf) for p in other['pins_mm']), default=math.inf)
                if distance <= max_wire_mm:
                    edges.append((symbol['id'], other['id'], {'kind': 'drawn_wire', 'length_mm': round(distance, 6)}))
                elif proximity_mm is not None and math.dist(symbol['position_mm'], other['position_mm']) <= proximity_mm:
                    edges.append((symbol['id'], other['id'], {'kind': 'graphical_proximity', 'electrical_connection': False,
                                                           'distance_mm': round(math.dist(symbol['position_mm'], other['position_mm']), 6)}))
        for label in labels:
            reached = _distances(graph, [label['point']])
            label['symbol_ids'] = [s['id'] for s in local_symbols if any(p in reached for p in s['pins_mm'])]
            label_records.append(label)
        if _children(root, 'bus') or _children(root, 'bus_entry'):
            warnings.append('Bus members and bus-entry connectivity are not inferred; review these clusters explicitly.')
        if any(_first(definition, 'power') is not None for definition in library.values()):
            warnings.append('Implicit power-symbol connections are not inferred; only drawn wires and explicit label links are considered.')
        for sheet in _children(root, 'sheet'):
            properties = {p[1].lower(): p[2] for p in _children(sheet, 'property') if len(p) > 2}
            child = properties.get('sheetfile')
            if child:
                load(filename.parent / child, current_path + '/' + _value(sheet, 'uuid'), ancestry + (filename,))
            else:
                warnings.append('Sheet without a Sheetfile property was not expanded.')

    try:
        load(path, '', ())
    except GroupingError:
        raise
    except (IndexError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise GroupingError('Malformed or unsupported saved schematic structure; check coordinates, symbol instances and sheet properties.') from exc
    base = _clusters(symbols, edges)
    cluster_ids = {s: group['id'] for group in base for s in group['symbol_ids']}
    links = []
    label_groups = {}
    for label in label_records:
        # Hierarchical labels are retained as suggestions in their local instance;
        # no speculative parent-sheet pin mapping is introduced.
        scope = '*' if label['kind'] == 'global_label' else label['sheet_path']
        label_groups.setdefault((label['kind'], label['name'], scope), []).append(label)
    for (kind, name, _), labels in sorted(label_groups.items()):
        if len(labels) < 2:
            continue
        members = sorted({s for label in labels for s in label['symbol_ids']})
        ids = sorted({cluster_ids[s] for s in members})
        if len(ids) < 2:
            continue
        accepted = include_global_links if kind == 'global_label' else include_label_links
        links.append({'name': name, 'kind': kind, 'clusters': ids, 'symbol_ids': members,
                      'requires_confirmation': True, 'accepted': bool(accepted)})
        if accepted:
            edges.extend((members[0], s, {'kind': kind, 'name': name, 'explicit_opt_in': True}) for s in members[1:])
    if any(l['kind'] == 'hierarchical_label' for l in label_records):
        warnings.append('Parent sheet-pin to child hierarchical-label links are not inferred; review or select these parts explicitly.')
    return {'clusters': _clusters(symbols, edges), 'wire_clusters': base, 'symbols': symbols,
            'label_links': links, 'warnings': sorted(set(warnings)), 'threshold_mm': max_wire_mm,
            'proximity_mm': proximity_mm, 'source': 'saved_schematic'}


def board_groups(board, scope='selection'):
    """Return selected footprints, native groups, or hierarchical PCB sheet scopes.

    Selection belongs to the supplied editor board. This function does not infer
    schematic-editor selections from PCB selections and never changes selection.
    """
    if scope not in ('selection', 'sheet', 'native_groups'):
        raise GroupingError('Scope must be selection, sheet, or native_groups.')
    footprints = list(board.GetFootprints())
    def identity(item):
        value = getattr(item, 'm_Uuid', None)
        return value.AsString() if value is not None else str(item.GetReference())
    by_id = {identity(fp): fp for fp in footprints}
    scopes = []
    warnings = []
    if scope == 'selection':
        selected = {identity(fp) for fp in footprints if fp.IsSelected()}
        if hasattr(board, 'Groups'):
            seen_groups = set()
            def collect(group):
                key = str(getattr(group, 'm_Uuid', id(group)))
                if key in seen_groups:
                    return
                seen_groups.add(key)
                for item in group.GetItems():
                    if hasattr(item, 'GetReference') and identity(item) in by_id:
                        selected.add(identity(item))
                    elif hasattr(item, 'GetItems'):
                        collect(item)
            for group in board.Groups():
                if group.IsSelected():
                    collect(group)
        scopes = [('selection', sorted(selected))] if selected else []
        if not scopes:
            warnings.append('No selected PCB footprints or selected native groups. Select intended parts first.')
    elif scope == 'native_groups':
        if not hasattr(board, 'Groups'):
            warnings.append('Native PCB groups are unavailable in this KiCad API.')
        else:
            for group in board.Groups():
                members = [identity(item) for item in group.GetItems() if hasattr(item, 'GetReference') and identity(item) in by_id]
                if members:
                    scopes.append((group.GetName(), sorted(members)))
    else:
        grouped = {}
        for fp in footprints:
            path = fp.GetPath().AsString() if hasattr(fp, 'GetPath') else ''
            sheet = path.rsplit('/', 1)[0] if '/' in path.strip('/') else ''
            if sheet:
                grouped.setdefault(sheet, []).append(identity(fp))
            else:
                warnings.append(f'{fp.GetReference()}: schematic sheet path unavailable.')
        scopes = sorted(grouped.items())
    return {'clusters': [{'id': _alphabet(index), 'name': name, 'symbol_ids': ids,
                          'references': sorted(by_id[key].GetReference() for key in ids),
                          'evidence': [{'kind': 'pcb_' + scope}]} for index, (name, ids) in enumerate(scopes)],
            'warnings': warnings, 'source': 'native_board', 'schematic_selection': 'unavailable'}
