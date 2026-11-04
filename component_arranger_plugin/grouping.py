"""Read-only placement scopes from saved schematics and native PCB objects.

Wire distances are millimetres along drawn wires, not air-line distances. Labels
are suggestions until explicitly accepted; proximity never creates an electrical
connection. Schematic coordinates describe circuit grouping, not PCB clearance.
"""

from __future__ import annotations

import hashlib
import heapq
import math
from pathlib import Path
import re


_METADATA_MAX_SHEETS = 32
_METADATA_MAX_BYTES = 8 * 1024 * 1024
_METADATA_MAX_SYMBOLS = 4096
_METADATA_MAX_PINS = 8192


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


def _pin_locations(symbol, library, warnings, numbered=False, instance_unit=None, pin_limit=None, budget=None):
    lib_id = _value(symbol, 'lib_id')
    definition = library.get(lib_id)
    if definition is None:
        warnings.append(f'{lib_id}: embedded symbol geometry missing; no inferred wire links.')
        return []
    if budget is not None:
        budget['remaining'] -= len(definition)
        if budget['remaining'] < 0:
            raise _PinLinkLimit
    at = _first(symbol, 'at', ['at', '0', '0', '0'])
    origin = _point(at)
    angle = math.radians(float(at[3]) if len(at) > 3 else 0)
    unit = int(instance_unit or _value(symbol, 'unit', '1'))
    mirror = _value(symbol, 'mirror')
    pins = []
    variants = {}
    explicit_style = _value(symbol, 'convert') or _value(symbol, 'body_style')
    for block in _children(definition, 'symbol'):
        if budget is not None:
            budget['remaining'] -= len(block)
            if budget['remaining'] < 0:
                raise _PinLinkLimit
        match = re.search(r'_(\d+)_(\d+)$', str(block[1]))
        if match and int(match[1]) not in (0, unit):
            continue
        style = int(match[2]) if match else 0
        if numbered:
            variants.setdefault(style, set())
        for pin in _children(block, 'pin'):
            if pin_limit is not None and len(pins) >= pin_limit:
                raise _PinLinkLimit
            x, y = _point(_first(pin, 'at'))
            # Library coordinates use upward Y; sheet coordinates use downward Y.
            y = -y
            if mirror == 'x':
                y = -y
            elif mirror == 'y':
                x = -x
            point = (round(origin[0] + x * math.cos(angle) + y * math.sin(angle), 6),
                     round(origin[1] - x * math.sin(angle) + y * math.cos(angle), 6))
            pins.append(point)
            if numbered:
                number = _value(pin, 'number')
                if number:
                    variants[style].add((number, point))
    if not pins:
        warnings.append(f'{lib_id}: no supported embedded pins; review this symbol explicitly.')
    if not numbered:
        return sorted(set(pins))
    common = variants.get(0, set())
    styles = sorted(style for style in variants if style)
    if explicit_style:
        selected = common | variants.get(int(explicit_style), set())
    elif len(styles) > 1:
        # Without an instance body style, only identical mappings in every
        # alternate representation can be used as physical pad evidence.
        selected = set.intersection(*(common | variants[style] for style in styles))
        if any(common | variants[style] != selected for style in styles):
            warnings.append(f'{lib_id}: ambiguous alternate pin geometry omitted from drawn-wire attraction.')
    else:
        selected = common | (variants[styles[0]] if styles else set())
    by_number = {}
    for number, point in selected:
        by_number.setdefault(number, set()).add(point)
    if any(len(points) > 1 for points in by_number.values()):
        warnings.append(f'{lib_id}: duplicate pin numbers at different positions omitted from drawn-wire attraction.')
    result = [{'number': number, 'position_mm': next(iter(points))}
              for number, points in sorted(by_number.items()) if len(points) == 1]
    if pins and not result:
        warnings.append(f'{lib_id}: reliable numbered pins unavailable; no drawn-wire attraction for this symbol.')
    return result


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


class _PinLinkLimit(Exception):
    pass


def _distances(graph, starts, limit=math.inf, budget=None):
    distances = {p: 0.0 for p in starts}
    queue = [(0.0, p) for p in starts]
    heapq.heapify(queue)
    while queue:
        distance, point = heapq.heappop(queue)
        if distance != distances[point]:
            continue
        for target, step in graph.get(point, {}).items():
            if budget is not None:
                budget['remaining'] -= 1
                if budget['remaining'] < 0:
                    raise _PinLinkLimit
            value = distance + step
            if value <= limit and value < distances.get(target, math.inf):
                distances[target] = value
                heapq.heappush(queue, (value, target))
    return distances


def _drawn_pin_links(graph, symbols, limit, links, warnings, budget):
    """Retain per-pin paths without joining a component's separate pins."""
    endpoints = sorted({(symbol['id'], pin['number'], tuple(pin['position_mm']), symbol['reference'])
                        for symbol in symbols for pin in symbol['pins']})
    try:
        for index, (source, number, point, reference) in enumerate(endpoints):
            if not graph.get(point):
                continue
            distances = _distances(graph, [point], limit, budget)
            for target, target_number, target_point, target_reference in endpoints[index + 1:]:
                budget['remaining'] -= 1
                if budget['remaining'] < 0:
                    raise _PinLinkLimit
                if source == target or not graph.get(target_point):
                    continue
                distance = distances.get(target_point, math.inf)
                if distance <= limit:
                    if len(links) >= 4096:
                        raise _PinLinkLimit
                    links.append({'from_symbol': source, 'to_symbol': target,
                                  'from_reference': reference, 'to_reference': target_reference,
                                  'from_pin': number, 'to_pin': target_number,
                                  'length_mm': round(distance, 6), 'kind': 'drawn_wire',
                                  'sheet_path': symbols[0]['sheet_path']})
    except _PinLinkLimit:
        budget['remaining'] = -1
        warnings.append('Drawn-wire pin metadata truncated at the 4096-link or 1000000-step limit; omitted links do not receive attraction.')


def infer_schematic_groups(path, max_wire_mm=25.0, include_label_links=False,
                           include_global_links=False, proximity_mm=None, *,
                           metadata_only=False, references=None):
    """Infer saved-sheet clusters and return separately reviewable label links.

    Args:
        path: Root .kicad_sch path. Child sheet files are read relative to parents.
        max_wire_mm: Maximum drawn shortest path between any two component pins.
        include_label_links: Explicit acceptance of local and hierarchical labels.
        include_global_links: Explicit acceptance of global-label connections.
        proximity_mm: Optional graphical-distance grouping heuristic in mm.
        metadata_only: Bounded pin evidence only; skip cluster and label searches.
        references: Optional references to retain as pin-link endpoints. Other
            confirmed physical pins still split drawn wires at their positions.

    Returns:
        JSON-compatible clusters, symbols, pin_links, label_links, warnings,
        source_fingerprints (SHA-256 of each saved sheet) and thresholds.
        Label-link cluster IDs always refer to the pre-acceptance wire clusters.
    """
    if not isinstance(max_wire_mm, (int, float)) or isinstance(max_wire_mm, bool) or not math.isfinite(max_wire_mm) or max_wire_mm <= 0:
        raise GroupingError('Wire-length threshold must be a positive finite number in mm.')
    if proximity_mm is not None and (not isinstance(proximity_mm, (int, float)) or isinstance(proximity_mm, bool) or not math.isfinite(proximity_mm) or proximity_mm <= 0):
        raise GroupingError('Proximity threshold must be a positive finite number in mm.')
    symbols, edges, label_records, warnings = [], [], [], []
    pin_links, source_fingerprints = [], {}
    pin_budget = {'remaining': 1000000}
    selected_references = None if references is None else set(references)
    metadata_budget = {'sheets': 0, 'bytes': 0, 'symbols': 0, 'pins': 0, 'stopped': False}

    def stop_metadata(reason):
        metadata_budget['stopped'] = True
        pin_links.clear()
        warnings.append(f'Drawn-wire pin metadata omitted: {reason}; no schematic attraction is added.')

    def load(filename, sheet_path, ancestry):
        if metadata_only and metadata_budget['stopped']:
            return
        filename = Path(filename).resolve()
        if filename in ancestry:
            raise GroupingError('Recursive schematic sheet file detected.')
        try:
            if metadata_only:
                if metadata_budget['sheets'] >= _METADATA_MAX_SHEETS:
                    stop_metadata(f'{_METADATA_MAX_SHEETS}-sheet limit exceeded')
                    return
                metadata_budget['sheets'] += 1
                remaining = _METADATA_MAX_BYTES - metadata_budget['bytes']
                # Bounded read also protects against growth after a size check.
                with filename.open('rb') as stream:
                    raw = stream.read(remaining + 1)
                if len(raw) > remaining:
                    stop_metadata(f'{_METADATA_MAX_BYTES}-byte saved-sheet limit exceeded')
                    return
                metadata_budget['bytes'] += len(raw)
            else:
                raw = filename.read_bytes()
            fingerprint = hashlib.sha256(raw).hexdigest()
            key = str(filename)
            if key in source_fingerprints and source_fingerprints[key] != fingerprint:
                raise GroupingError(f'Saved schematic {filename.name} changed while loading repeated sheet instances; reload the scope.')
            source_fingerprints[key] = fingerprint
            root = _parse(raw.decode('utf-8-sig'))
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
            if metadata_only:
                metadata_budget['symbols'] += 1
                if metadata_budget['symbols'] > _METADATA_MAX_SYMBOLS:
                    stop_metadata(f'{_METADATA_MAX_SYMBOLS}-symbol limit exceeded')
                    return
            props = {p[1]: p[2] for p in _children(node, 'property') if len(p) > 2}
            ref = props.get('Reference', '?')
            occurrences = set()
            for project in _children(_first(node, 'instances', []), 'project'):
                for instance in _children(project, 'path'):
                    if instance[1].rstrip('/') == current_path.rstrip('/'):
                        ref = _value(instance, 'reference', ref)
                        occurrences.add((ref, _value(instance, 'unit', _value(node, 'unit', '1'))))
            try:
                pins = _pin_locations(node, library, warnings, numbered=True,
                                      instance_unit=next(iter(occurrences))[1] if len(occurrences) == 1 else None,
                                      pin_limit=_METADATA_MAX_PINS - metadata_budget['pins'] if metadata_only else None,
                                      budget=pin_budget if metadata_only else None)
            except _PinLinkLimit:
                stop_metadata(f'{_METADATA_MAX_PINS}-pin endpoint or bounded symbol-geometry work limit exceeded')
                return
            if len(occurrences) > 1:
                warnings.append(f'{ref}: ambiguous schematic occurrence omitted from drawn-wire attraction.')
                pins = []
            if metadata_only:
                metadata_budget['pins'] += len(pins)
                if metadata_budget['pins'] > _METADATA_MAX_PINS:
                    stop_metadata(f'{_METADATA_MAX_PINS}-pin endpoint limit exceeded')
                    return
            symbol = {'id': current_path + '/' + _value(node, 'uuid', ref), 'reference': ref,
                      'sheet_path': current_path, 'position_mm': _point(_first(node, 'at')),
                      'pins_mm': [p['position_mm'] for p in pins] if metadata_only else _pin_locations(node, library, warnings),
                      'pins': pins, 'lib_id': _value(node, 'lib_id'),
                      'unit': int(next(iter(occurrences))[1]) if len(occurrences) == 1 else int(_value(node, 'unit', '1'))}
            if not metadata_only or selected_references is None or ref in selected_references:
                symbols.append(symbol)
            local_symbols.append(symbol)
        endpoint_symbols = [s for s in local_symbols if selected_references is None or s['reference'] in selected_references]
        if metadata_only:
            confirmed_pins = {p['position_mm'] for s in local_symbols for p in s['pins']}
            wires = _children(root, 'wire')
            point_counts = [len(_children(_first(w, 'pts', []), 'xy')) for w in wires]
            segments = sum(max(0, count - 1) for count in point_counts)
            split_bound = sum(point_counts) + len(_children(root, 'junction')) + len(confirmed_pins)
            construction_steps = segments * split_bound
            if construction_steps > pin_budget['remaining'] or split_bound > _METADATA_MAX_PINS:
                stop_metadata('bounded graph-construction work or endpoint limit exceeded')
                return
            if sum(bool(s['pins']) for s in endpoint_symbols) >= 2:
                pin_budget['remaining'] -= construction_steps
                graph = _wire_graph(root, confirmed_pins, [])
                _drawn_pin_links(graph, endpoint_symbols, max_wire_mm, pin_links, warnings, pin_budget)
                if pin_budget['remaining'] < 0:
                    stop_metadata('bounded pin-path work or link limit exceeded')
                    return
        else:
            labels = []
            for kind in ('label', 'global_label', 'hierarchical_label'):
                for label in _children(root, kind):
                    labels.append({'kind': kind, 'name': label[1], 'point': _point(_first(label, 'at')),
                                   'sheet_path': current_path})
            graph = _wire_graph(root, [p for s in local_symbols for p in s['pins_mm']], labels)
            if pin_budget['remaining'] >= 0:
                # Labels are not junctions for attraction. They cannot create a
                # path by splitting two otherwise disconnected crossing wires.
                confirmed_pins = {p['position_mm'] for s in local_symbols for p in s['pins']}
                legacy_pins = {p for s in local_symbols for p in s['pins_mm']}
                if not labels and confirmed_pins == legacy_pins:
                    pin_graph = graph
                else:
                    segments = sum(max(0, len(_children(_first(w, 'pts', []), 'xy')) - 1) for w in _children(root, 'wire'))
                    construction_steps = segments * (len(graph) + len(confirmed_pins - legacy_pins))
                    if construction_steps > pin_budget['remaining']:
                        pin_budget['remaining'] = -1
                        warnings.append('Drawn-wire pin metadata omitted after the 1000000-step graph-construction limit; omitted links do not receive attraction.')
                        pin_graph = None
                    else:
                        pin_budget['remaining'] -= construction_steps
                        pin_graph = _wire_graph(root, confirmed_pins, [])
                if pin_graph is not None:
                    _drawn_pin_links(pin_graph, endpoint_symbols, max_wire_mm, pin_links, warnings, pin_budget)
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
            if metadata_only and metadata_budget['stopped']:
                break
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
    if metadata_only:
        return {'clusters': [], 'wire_clusters': [], 'symbols': symbols,
                'pin_links': sorted(pin_links, key=lambda link: (link['from_symbol'], link['from_pin'], link['to_symbol'], link['to_pin'])),
                'source_fingerprints': dict(sorted(source_fingerprints.items())),
                'label_links': [], 'warnings': sorted(set(warnings)), 'threshold_mm': max_wire_mm,
                'proximity_mm': proximity_mm, 'source': 'saved_schematic'}
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
            'pin_links': sorted(pin_links, key=lambda link: (link['from_symbol'], link['from_pin'], link['to_symbol'], link['to_pin'])),
            'source_fingerprints': dict(sorted(source_fingerprints.items())),
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
