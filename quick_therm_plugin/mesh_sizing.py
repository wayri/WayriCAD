"""Bounded geometry-based sizing for the existing rectilinear thermal solver.

Recommendations are screening heuristics, not discretization-error estimates.
Polygon bounds describe regions, not the lengths of tessellated contour edges.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import heapq
import math


def mesh_mode(settings):
    mode = settings.get('mesh_mode', 'manual')
    if mode not in ('auto', 'manual'):
        raise ValueError('mesh_mode must be auto or manual.')
    return mode


def _box(points):
    if not points:
        return None
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs), max(ys)]


def recommend_mesh(geometry, view, result, settings, progress=None):
    """Choose base long-axis cells and bounded source/contact/material targets."""
    bounds = geometry.get('bbox_mm', view.get('bbox_mm'))
    if not bounds or len(bounds) != 4 or not all(math.isfinite(float(v)) for v in bounds):
        raise ValueError('Automatic mesh needs finite board bounds.')
    span = max(bounds[2]-bounds[0], bounds[3]-bounds[1])
    if min(bounds[2]-bounds[0], bounds[3]-bounds[1]) <= 0:
        raise ValueError('Automatic mesh needs positive board dimensions.')
    features = []
    total_features = 0
    missing_source_bounds = []
    priorities = {'source': 0, 'contact': 1, 'barrel': 2, 'material region': 3}
    scoped = {row['reference'] for row in result.get('components', []) if row.get('heat_path') == 'board'}

    def add(box, kind, identity, divisions):
        nonlocal total_features
        if box is None or len(box) != 4:
            return
        box = list(map(float, box))
        size = min(box[2]-box[0], box[3]-box[1])
        if not all(math.isfinite(v) for v in box) or size <= 0:
            return
        if box[2] < bounds[0] or box[0] > bounds[2] or box[3] < bounds[1] or box[1] > bounds[3]:
            return
        feature = {'bounds_mm': box, 'kind': kind, 'id': str(identity),
                   'size_mm': size, 'target_mm': size/divisions}
        total_features += 1
        item = (-priorities[kind], -size, -total_features, feature)
        if len(features) < 2048:
            heapq.heappush(features, item)
        elif item[:3] > features[0][:3]:
            heapq.heapreplace(features, item)

    for part in view.get('components', []):
        if part.get('reference') in scoped:
            previous_count = total_features
            add(part.get('bbox_mm'), 'source', part['reference'], 4)
            if previous_count == total_features:
                missing_source_bounds.append(str(part['reference']))
    for contact in geometry.get('source_contacts', []):
        for index, polygon in enumerate(contact.get('polygons_mm', [])):
            add(_box(polygon.get('outer', [])), 'contact',
                str(contact.get('reference', 'pad')) + ':' + str(index), 3)
    for barrel_index, barrel in enumerate(geometry.get('barrels', [])):
        if progress and barrel_index % 256 == 0:
            progress('automatic mesh barrel review', barrel_index, len(geometry['barrels']), 0., None)
        x, y, diameter = barrel['x_mm'], barrel['y_mm'], barrel['drill_mm']
        add([x-diameter/2, y-diameter/2, x+diameter/2, y+diameter/2], 'barrel', barrel['id'], 2)
    selected_mounts = {row.get('id') for row in settings.get('mount_boundaries', [])}
    for mount in geometry.get('mounting_holes', []):
        if mount['id'] in selected_mounts and mount.get('drill_mm'):
            x, y, diameter = mount['x_mm'], mount['y_mm'], mount['drill_mm']
            add([x-diameter/2, y-diameter/2, x+diameter/2, y+diameter/2], 'contact', mount['id'], 3)
    for layer in geometry.get('layers', []):
        for index, polygon in enumerate(layer.get('polygons_mm', [])):
            if progress and index % 256 == 0:
                progress('automatic mesh feature review', index, len(layer['polygons_mm']), 0., None)
            box = _box(polygon.get('outer', []))
            if box and min(box[2]-box[0], box[3]-box[1]) < span/4:
                add(box, 'material region', str(layer['id']) + ':' + str(index), 2)
            for hole_index, hole in enumerate(polygon.get('holes', [])):
                add(_box(hole), 'material region', str(layer['id'])+':'+str(index)+':hole:'+str(hole_index), 2)
    features = [row[3] for row in features]
    features.sort(key=lambda row: (priorities[row['kind']], row['size_mm'], row['id']))
    omitted = max(0, total_features-2048)
    source_sizes = [row['size_mm'] for row in features if row['kind'] in ('source', 'contact')]
    grid = max(24, min(64, math.ceil(span/min(source_sizes)))) if source_sizes else 48
    budget = settings.get('auto_mesh_max_layer_cells', 50000)
    if isinstance(budget, bool) or not isinstance(budget, int) or not 1152 <= budget <= 150000:
        raise ValueError('auto_mesh_max_layer_cells must be an integer from 1152 to 150000.')
    layers = max(1, len(geometry.get('layers', [])))
    reserved_nodes = len(settings.get('component_storage') or {}) + sum(
        part.get('heat_path') == 'heatsink' for part in result.get('components', []))
    budget = min(budget, 150000-reserved_nodes)
    width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
    # The rectangle upper bound includes cells outside the outline. This is
    # intentionally conservative and is checked before any sparse allocation.
    def cells(n):
        return max(2, round(n*width/span))*max(2, round(n*height/span))*layers
    # Leave room for local refinement on many-layer boards instead of spending
    # the entire node budget on a uniform background grid.
    base_budget = budget*.55 if features else budget
    while grid > 24 and cells(grid) > base_budget:
        grid -= 1
    if cells(grid) > budget:
        raise ValueError('Automatic mesh budget cannot fit the minimum base grid for this stackup.')
    warnings = ['Geometry-based sizing is not mesh convergence; run independent spatial and time-step studies.',
                'Targets use axis-aligned region bounds; thin rotated traces, plated-wall thickness and package solids are not resolved by this heuristic.']
    if omitted:
        warnings.append(str(omitted) + ' lower-priority feature regions exceed the 2048-region sizing budget.')
    if missing_source_bounds:
        warnings.append(str(len(missing_source_bounds)) + ' scoped sources lack usable footprint bounds; source size is unresolved.')
    return {'mode': 'auto', 'recommended_grid_cells_long_axis': grid,
            'base_size_mm': span/grid, 'features': features, 'feature_regions_omitted': omitted,
            'maximum_layer_cells': budget, 'warnings': warnings,
            'reserved_storage_and_sink_nodes': reserved_nodes,
            'source_bounds_unavailable': missing_source_bounds[:40],
            'meaning': 'Rectilinear region refinement; no automatic thermal-error or CFD model.'}


def refine_edges(x_edges, y_edges, recommendation, layers, grid, progress=None, passes=4):
    """Split existing intervals conservatively, preserving every old edge.

    Splits extend across the tensor-product grid. They never alter copper
    connectivity or smooth across gaps. Targets scale with an explicit grid
    sweep so automatic sizing cannot silently replace convergence levels.
    """
    if isinstance(passes, bool) or not isinstance(passes, int) or not 1 <= passes <= 4:
        raise ValueError('auto_mesh_max_refinement_passes must be an integer from 1 to 4.')
    edges = [list(x_edges), list(y_edges)]
    scale = recommendation['recommended_grid_cells_long_axis']/grid
    features = recommendation['features']
    budget = recommendation['maximum_layer_cells']
    limited = False
    priorities = {'source': 0, 'contact': 1, 'barrel': 2, 'material region': 3}
    for iteration in range(passes):
        if progress:
            progress('automatic local mesh refinement', iteration, passes, 0., None)
        changed = False
        for axis in (0, 1):
            values = edges[axis]
            desired = [math.inf]*(len(values)-1)
            ranks = [math.inf]*(len(values)-1)
            for feature in features:
                box = feature['bounds_mm']
                start = max(0, bisect_right(values, box[axis])-2)
                end = min(len(values)-1, bisect_left(values, box[axis+2])+1)
                for index in range(start, end):
                    target = feature['target_mm']*scale
                    if values[index+1]-values[index] <= target*(1+1e-12):
                        continue
                    rank = priorities[feature['kind']]
                    if rank < ranks[index]:
                        ranks[index], desired[index] = rank, target
                    elif rank == ranks[index]:
                        desired[index] = min(desired[index], target)
            candidates = [index for index, (left, right) in enumerate(zip(values, values[1:]))
                          if right-left > desired[index]*(1+1e-12)]
            # Prioritize the most underresolved interval, deterministically.
            candidates.sort(key=lambda i: (ranks[i], -(values[i+1]-values[i])/desired[i], i))
            available = min(511, budget//max(1, layers*(len(edges[1-axis])-1)))-(len(values)-1)
            if axis == 0 and available > 0:
                # Reserve comparable growth for Y, rather than letting the
                # first tensor axis consume every remaining layer cell.
                growth = math.sqrt(budget/max(1, layers*(len(edges[0])-1)*(len(edges[1])-1)))
                available = min(available, max(1, int((len(values)-1)*(growth-1))))
            if len(candidates) > max(0, available):
                limited = True
            selected = set(candidates[:max(0, available)])
            refined = [values[0]]
            for index, (left, right) in enumerate(zip(values, values[1:])):
                if index in selected:
                    refined.append((left+right)/2)
                    changed = True
                refined.append(right)
            edges[axis] = refined
        if not changed:
            break
    unresolved = []
    for feature in features:
        for axis, values in enumerate(edges):
            start = max(0, bisect_right(values, feature['bounds_mm'][axis])-1)
            end = min(len(values)-1, bisect_left(values, feature['bounds_mm'][axis+2]))
            if any(values[i+1]-values[i] > feature['target_mm']*scale*(1+1e-12)
                   for i in range(start, max(start+1, end)) if i < len(values)-1):
                unresolved.append(feature['kind'] + ': ' + feature['id'])
                break
    widths = [[b-a for a, b in zip(values, values[1:])] for values in edges]
    details = {key: value for key, value in recommendation.items() if key != 'features'}
    details.update(effective_grid_cells_long_axis=grid, nx=len(edges[0])-1, ny=len(edges[1])-1,
                   minimum_cell_size_mm=min(min(row) for row in widths),
                   maximum_cell_size_mm=max(max(row) for row in widths),
                   unresolved_feature_count=len(unresolved), unresolved_features=unresolved[:40],
                   budget_limited=limited, retained_feature_regions=len(features))
    if unresolved:
        details['warnings'] = details['warnings'] + [str(len(unresolved)) + ' retained feature regions do not meet their heuristic target size; refine or review contacts.']
    return edges[0], edges[1], details
