"""Geometry-based 2.5D mesh recommendations; not numerical error estimates."""
from __future__ import annotations

import math


def mode(request):
    value = request.get('mesh_sizing', 'manual')
    if value not in ('auto', 'manual'):
        raise ValueError('mesh_sizing must be auto or manual.')
    if value == 'auto' and request.get('model_dimension', '2.5d') != '2.5d':
        raise ValueError('Automatic geometry sizing currently supports 2.5D only. Select a manual 3D edge size.')
    return value


def _box(polygons):
    import numpy as np
    points = np.asarray([xy[:2] for p in polygons for xy in p['outer']], dtype=float)
    if not len(points):
        return None
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError('Automatic mesh sizing needs finite copper contours.')
    return points.min(axis=0), points.max(axis=0)


def recommend(geometry, max_cells=400000):
    """Choose a global background edge and local targets from physical features.

    The background uses the occupied extent / 40, capped at 0.8 mm. Three
    nominal edges across a track/contact/annular width trigger local refinement.
    Contact bounding boxes are proxies; arbitrary zone necks are unresolved.
    """
    import numpy as np
    if isinstance(max_cells,bool) or not isinstance(max_cells,int) or max_cells<=0:
        raise ValueError('Automatic mesh sizing needs a positive integer cell budget.')
    boxes = [_box(layer.get('polygons', [])) for layer in geometry['layers']]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        raise ValueError('No copper geometry is available for mesh sizing.')
    low = np.min([b[0] for b in boxes], axis=0)
    high = np.max([b[1] for b in boxes], axis=0)
    extent = float(np.linalg.norm(high - low))
    if not math.isfinite(extent) or extent <= 0:
        raise ValueError('Copper extent must be finite and positive.')
    edge = min(.8, extent / 40)
    features = [];unresolved=[]
    for row in geometry.get('mesh_features', []):
        width = float(row['width_mm'])
        if not math.isfinite(width) or width <= 0:
            raise ValueError('Physical mesh feature widths must be finite and positive.')
        features.append({**row, 'target_mm': min(edge, width / 3)})
    for terminal in geometry.get('terminals', []):
        for layer, polygons in terminal.get('polygons', {}).items():
            box = _box(polygons)
            if box is None:
                continue
            lo, hi = box; width = float(np.min(hi - lo))
            if width <= 0:
                unresolved.append({'id':terminal['id'],'layer':str(layer),'reason':'Degenerate contact bounding-box width; no local target.'})
                continue
            features.append({'kind': 'contact_bbox', 'id': terminal['id'], 'layer': str(layer),
                             'low_mm': lo.tolist(), 'high_mm': hi.tolist(),
                             'width_mm': width, 'target_mm': min(edge, width / 3)})
    for via in geometry.get('vias', []):
        for layer, diameter in via.get('diameters_mm', {}).items():
            width = (float(diameter) - max(via.get('drill_size_mm', [via['drill_mm']]))) / 2
            if not math.isfinite(width) or width <= 0:
                unresolved.append({'id':via['id'],'layer':str(layer),'reason':'Annular width cannot be bounded from saved diameter/drill dimensions; native contact retained without an annular target.'})
                continue
            radius = float(diameter) / 2
            features.append({'kind': 'barrel_contact', 'id': via['id'], 'layer': str(layer),
                             'low_mm': [via['x_mm']-radius, via['y_mm']-radius],
                             'high_mm': [via['x_mm']+radius, via['y_mm']+radius],
                             'width_mm': width, 'target_mm': min(edge, width / 3)})
    def area_of(ring):
        xy=np.asarray(ring,dtype=float);following=np.roll(xy,-1,axis=0)
        return abs(float(np.sum(xy[:,0]*following[:,1]-xy[:,1]*following[:,0])))/2
    area = float(geometry.get('area_mm2') or sum(
        area_of(p['outer'])-sum(area_of(ring) for ring in p.get('holes',[]))
        for layer in geometry['layers'] for p in layer.get('polygons', [])))
    if not math.isfinite(area) or area<=0:raise ValueError('Copper area must be finite and positive.')
    ideal_edge=edge
    # Reserve three quarters of the estimated capacity for local features and
    # native boundary vertices. This is only a cost estimate, not a mesh bound.
    edge=max(ideal_edge,math.sqrt(16*area/max_cells))
    estimate = math.ceil(4 * area / edge**2)
    return {'mode': 'auto', 'background_edge_mm': edge,
            'ideal_background_edge_mm':ideal_edge,
            'budget_adjusted_background':edge>ideal_edge,
            'minimum_local_target_mm': min([edge] + [f['target_mm'] for f in features]),
            'features': features, 'feature_count': len(features), 'cell_budget': max_cells,
            'estimated_background_triangles': estimate,
            'estimated_ideal_background_triangles':math.ceil(4*area/ideal_edge**2),
            'grading':'Feature width / 3 locally; edge target grows 0.5 mm per mm distance to the background target.',
            'budget_warning': estimate > max_cells,
            'unresolved_feature_classes': ['Arcs (native contours retained, no centerline width target)',
                                           'Narrow zone necks and arbitrary polygon-only features'],
            'unresolved_features':unresolved,
            'limitations': ['Heuristic geometry resolution, not mesh convergence or an accuracy certificate.',
                           'Zone necks, curvature error, contact singularities and flux-error adaptivity are not inferred.',
                           'Contact bounding boxes approximate local support; native contours and drilled holes remain unchanged.',
                           'No automatic coarsening: the exact triangle budget may reject the requested refinement.']}


def edge_targets(points, features, background_edge, cancelled=None):
    """Spatially limit feature queries; never scan every feature for every edge."""
    from scipy.spatial import cKDTree
    import numpy as np
    points = np.asarray(points)[:, :2]
    targets = np.full(len(points), background_edge)
    tree = cKDTree(points)
    for index, row in enumerate(features):
        if index % 128 == 0 and cancelled and cancelled():
            raise InterruptedError('Automatic mesh refinement cancelled.')
        width = row['width_mm']; padding = 2*width + 2*background_edge
        if row.get('kind') == 'track':
            a = np.asarray(row['start_mm']); b = np.asarray(row['end_mm'])
            center = (a+b)/2; radius = np.linalg.norm(b-a)/2 + padding
            chosen = np.asarray(tree.query_ball_point(center, radius), dtype=int)
            if not len(chosen):continue
            direction = b-a; length2 = float(direction @ direction)
            fraction = np.clip((points[chosen]-a) @ direction / max(length2, 1e-30), 0., 1.)
            distance=np.maximum(0.,np.linalg.norm(points[chosen] - (a + fraction[:, None]*direction), axis=1)-width/2)
        else:
            lo = np.asarray(row['low_mm']); hi = np.asarray(row['high_mm'])
            native_lo=lo;native_hi=hi;lo=lo-padding;hi=hi+padding
            chosen = np.asarray(tree.query_ball_point((lo+hi)/2, np.linalg.norm(hi-lo)/2), dtype=int)
            if not len(chosen):continue
            distance=np.linalg.norm(np.maximum(0.,np.maximum(native_lo-points[chosen],points[chosen]-native_hi)),axis=1)
        graded=row['target_mm']+.5*distance
        targets[chosen] = np.minimum(targets[chosen], graded)
    return targets


def sizing_html(mesh):
    from html import escape
    import json
    data = mesh.get('mesh_sizing')
    if not data:return ''
    def concise(value):
        if isinstance(value,dict):return {k:concise(v) for k,v in value.items() if k!='features'}
        if isinstance(value,list):return [concise(v) for v in value]
        return value
    compact = concise(data)
    compact['achieved_layer_resolution']=mesh.get('mesh_report',[])
    return '<h2>Mesh sizing and resolution</h2><pre>' + escape(json.dumps(compact, indent=2, allow_nan=False)) + '</pre>'
