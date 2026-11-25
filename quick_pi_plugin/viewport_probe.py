'''Precise indexed hover for the native Quick PI copper viewport.'''
from bisect import bisect_left, bisect_right
import math

from .barrel import drill_dimensions, drill_wall_distance
from .report import METRICS, cell_values
from .view_scope import analyzed_nets, mesh_net_labels


def contact_labels(bundle):
    geometry = bundle.get('geometry') or bundle.get('mesh', {}).get('geometry', {})
    request = bundle.get('request', {})
    terminals = {row['id']: row for row in geometry.get('terminals', [])}
    groups = [request.get('source_terminals') or [request.get('source_terminal', request.get('source'))]]
    for sink in request.get('sinks', []):
        groups.append(sink.get('terminals') or sink.get('terminal_ids') or [sink.get('terminal')])
    groups.append(request.get('sink_terminals') or [request.get('sink_terminal', request.get('sink'))])
    members = {}
    for group in groups:
        rows = [terminals[key] for key in group if key in terminals]
        labels = ', '.join(dict.fromkeys(row.get('label', row['id']) for row in rows))
        for row in rows:
            members[row['id']] = labels
    return terminals, members


def attach_viewport_probes(canvas, axes, bundle, layer, metric, visible_nets, current_result):
    import numpy as np
    from wayricad_runtime.board_render import hit_test, prepare_scene
    from wayricad_runtime.plot_probe import attach_probes

    mesh, result = bundle['mesh'], bundle['result']
    geometry = bundle.get('geometry') or mesh.get('geometry', {})
    labels = mesh_net_labels(bundle)
    indices = np.flatnonzero([str(value) == str(layer) for value in mesh['triangle_layer']])
    if visible_nets is not None:
        indices = indices[np.isin(labels[indices], visible_nets)]
    points = np.asarray(mesh['points_mm'])
    triangles = np.asarray(mesh['triangles'], dtype=int).reshape(-1, 3)
    polygons = points[triangles[indices], :2]
    centers = polygons.mean(axis=1)
    values = cell_values(mesh, result, metric)
    samples = [[x, y, values[i], 'Cell '+str(i)] for (x, y), i in zip(centers, indices)]
    names = {str(row['id']): row.get('name', str(row['id'])) for row in geometry.get('layers', [])}
    order = {str(row['id']): row.get('z_mm', i) for i, row in enumerate(geometry.get('layers', []))}
    single_net = analyzed_nets(bundle)
    single_net = single_net[0] if len(single_net) == 1 else None
    cached_result = None
    via_values = {}
    barrels = []
    for barrel in mesh.get('vias', []):
        net = barrel.get('net') or single_net
        if visible_nets is not None and net not in visible_nets:
            continue
        span = [str(barrel.get(key)) for key in ('top_layer', 'bottom_layer')]
        if str(layer) not in order or any(value not in order for value in span):
            continue
        if not min(order[value] for value in span) <= order[str(layer)] <= max(order[value] for value in span):
            continue
        if 'x_mm' not in barrel or 'y_mm' not in barrel:
            continue
        radius = max(drill_dimensions(barrel)) / 2 + barrel['plating_mm']
        barrels.append((float(barrel['x_mm']), radius, barrel, net, span))
    barrels.sort(key=lambda row: row[0])
    barrel_x = [row[0] for row in barrels]
    max_radius = max((row[1] for row in barrels), default=0.0)
    scene = prepare_scene(bundle.get('board_scene', {}))
    terminals, groups = contact_labels(bundle)
    pad_scene = prepare_scene(dict(scene, primitives=[row for row in scene.get('primitives', [])
        if row.get('role') == 'pad' and row.get('uuid') in terminals and str(row.get('layer')) == str(layer)]))

    def number(value, units):
        return f'{value:.6g} {units}' if value is not None and math.isfinite(value) else 'Unavailable / floating'

    def hover(event, sample):
        nonlocal cached_result, via_values
        if event.inaxes is not axes or event.xdata is None or event.ydata is None:
            return ''
        x, y = event.xdata, event.ydata
        position = f'X {x:.3f} · Y {y:.3f} mm'
        candidates = []
        for i in range(bisect_left(barrel_x, x-max_radius), bisect_right(barrel_x, x+max_radius)):
            bx, radius, barrel, net, span = barrels[i]
            if abs(x-bx) > radius or abs(y-barrel['y_mm']) > radius:
                continue
            distance = drill_wall_distance((x, y), barrel)
            if distance < -1e-10:
                return ''
            if distance <= barrel['plating_mm']+1e-10:
                live = current_result()
                if live is not cached_result:
                    via_values = {str(row['id']): row for row in live.get('vias', [])}
                    cached_result = live
                solved = via_values.get(str(barrel['id']), {})
                text = (f'{net or "Net unavailable"} · {names.get(span[0], span[0])} → {names.get(span[1], span[1])}'
                        f'\n{position} · Barrel current {number(solved.get("current_A"), "A")}'
                        f'\nCurrent density {number(solved.get("current_density_A_mm2"), "A/mm²")}')
                candidates.append((abs(solved.get('current_A') or 0), text))
        if candidates:
            return max(candidates)[1]
        if sample is None:
            return ''
        net = str(labels[int(sample[3][5:])])
        contacts = []
        if net and pad_scene.get('primitives'):
            for pad in hit_test(pad_scene, x, y, visible_layers=[layer], net=net):
                key = pad['uuid']
                contacts.append(groups.get(key) or terminals[key].get('label', key))
        text = (f'{net or "Net unavailable"} · {names.get(str(layer), layer)}\n{position} · '
                f'{number(sample[2], METRICS[metric][1])}')
        if contacts:
            text += '\nPads ' + ' | '.join(dict.fromkeys(contacts))
        return text

    return attach_probes(canvas, axes, samples, METRICS[metric][1], polygons=polygons,
                         hover_text=hover, pin_on_click=False)
