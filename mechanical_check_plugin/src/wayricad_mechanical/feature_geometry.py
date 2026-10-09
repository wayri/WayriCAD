"""CAD feature inspection and exact rulers. Polylines are display evidence only."""
import math


def point_coordinates(value):
    """External coordinates accept JSON-like numeric triples, never coercion."""
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or any(type(v) not in (int, float) for v in value)):
        raise ValueError('Point requires three finite numeric CAD X/Y/Z coordinates')
    try:
        return xyz(value)
    except OverflowError as exc:
        raise ValueError('Point requires three finite numeric CAD X/Y/Z coordinates') from exc


def xyz(point):
    result = [float(v) for v in point]
    if len(result) != 3 or not all(math.isfinite(v) for v in result):
        raise ValueError('Feature coordinates must be finite CAD X/Y/Z millimetres')
    return result


def selector(value):
    if not isinstance(value, dict) or value.get('kind') not in ('point', 'edge', 'center'):
        raise ValueError('Choose a point, CAD edge or geometric volume center')
    if not isinstance(value.get('ref'), str) or not value['ref']:
        raise ValueError('Feature requires a body reference')
    result = dict(kind=value['kind'], ref=value['ref'])
    if value['kind'] == 'point':
        try:
            result['position'] = point_coordinates(value['position'])
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError('Point requires finite CAD X/Y/Z coordinates') from exc
    elif value['kind'] == 'edge':
        index = value.get('edge_index')
        if type(index) is not int or index < 0:
            raise ValueError('CAD edge index must be a nonnegative integer')
        result['edge_index'] = index
    return result


def validate_feature_record(record):
    """Imported JSON is evidence to validate before passing it to the viewer."""
    try:
        features = record['features']
        if not isinstance(features, list) or len(features) != 2:
            raise ValueError('Feature ruler requires two selectors')
        normalized = [selector(feature) for feature in features]
        if record.get('measurement_kind') != measurement_kind(normalized):
            raise ValueError('Feature ruler kind disagrees with its selectors')
        if record.get('refs') != [feature['ref'] for feature in normalized] or record.get('unit') != 'mm':
            raise ValueError('Feature ruler references or units are invalid')
        if not isinstance(record.get('evidence'), str) or not record['evidence'].strip():
            raise ValueError('Feature ruler evidence is missing')
        descriptions = record.get('feature_evidence')
        if descriptions is not None and (not isinstance(descriptions, list) or len(descriptions) != 2
                                         or not all(isinstance(value, str) for value in descriptions)):
            raise ValueError('Feature ruler endpoint evidence is invalid')
        distance = record['distance_mm']
        if type(distance) not in (int, float) or not math.isfinite(distance) or distance < 0:
            raise ValueError('Feature ruler distance must be finite and nonnegative')
        witnesses = record['points']
        if not isinstance(witnesses, (list, tuple)) or len(witnesses) != 2:
            raise ValueError('Feature ruler requires two witnesses')
        points = [point_coordinates(point) for point in witnesses]
        if not math.isclose(math.dist(*points), distance, abs_tol=1e-6, rel_tol=1e-8):
            raise ValueError('Feature ruler witnesses disagree with its distance')
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError('Cached feature ruler is malformed') from exc


def measurement_kind(features):
    kinds = sorted(f['kind'] for f in features)
    if kinds == ['edge', 'point']:
        return 'point_edge'
    if kinds[0] == kinds[1]:
        return kinds[0] + '_' + kinds[1]
    raise ValueError('Choose two points, two edges, a point and edge, or two body centers')


def volume_centroid(shape):
    # BREP reads produce generic Part.Shape compounds, which have no
    # CenterOfMass property. Their transformed solids expose the exact integral.
    solids = [(float(solid.Volume), xyz(solid.CenterOfMass)) for solid in shape.Solids]
    if not solids or any(not math.isfinite(volume) or volume <= 0 for volume, _ in solids):
        raise ValueError('Geometric volume centroid requires positive solid volumes')
    volume = sum(volume for volume, _ in solids)
    return [sum(weight*point[axis] for weight, point in solids)/volume for axis in range(3)]


def inspect_shape(shape, sample_budget):
    """Use serialized BREP topology. Bounded samples never become kernel inputs.

    All edges retain their indices, including edges without display samples.
    A scene-wide point budget limits report size; curves use at most 65 points.
    Sampling is uniformly parameterized, with no chord-accuracy claim.
    """
    bounds = shape.BoundBox
    volume = float(shape.Volume)
    if not math.isfinite(volume) or volume <= 0:
        raise ValueError('Geometric volume centroid requires positive solid volume')
    result = dict(status='available', center_mm=volume_centroid(shape),
                  center_evidence='geometric volume centroid (uniform volume weighting; not mass)',
                  dimensions_mm=[bounds.XLength, bounds.YLength, bounds.ZLength],
                  volume_mm3=volume, edges=[], unit='mm',
                  edge_sampling='bounded parameter samples for picking/display only; distances use CAD curves')
    edges = shape.Edges
    result['edge_count'] = len(edges)
    for index, edge in enumerate(edges):
        item = dict(index=index, points=[], status='unavailable')
        try:
            item.update(length_mm=float(edge.Length), curve=type(edge.Curve).__name__)
            count = 2 if item['curve'] in ('Line', 'LineSegment') else 65
            if sample_budget[0] < count:
                item['reason'] = 'Scene display sample budget exhausted; exact CAD edge remains queryable'
            else:
                first, last = edge.ParameterRange
                item['points'] = [xyz(edge.valueAt(first + (last-first)*i/(count-1))) for i in range(count)]
                item['status'] = 'available'
                sample_budget[0] -= count
        except Exception as exc:
            item['reason'] = 'CAD edge display sampling unavailable: ' + str(exc)
        result['edges'].append(item)
    return result


def measure_features(features, shapes, evidence):
    """Resolve edges and centroids from BREP, then obtain exact kernel witnesses."""
    import FreeCAD as App
    import Part
    if len(features) != 2 or len(shapes) != 2 or len(evidence) != 2:
        raise ValueError('A feature ruler requires exactly two features and cached bodies')
    features = [selector(f) for f in features]
    kind = measurement_kind(features)
    geometry, descriptions = [], []
    for feature, shape, source in zip(features, shapes, evidence):
        if feature['kind'] == 'point':
            geometry.append(Part.Vertex(App.Vector(*feature['position'])))
            descriptions.append('picked tessellated surface point (display approximation)')
        elif feature['kind'] == 'center':
            if not math.isfinite(shape.Volume) or shape.Volume <= 0:
                raise ValueError('Selected body has no positive solid volume')
            geometry.append(Part.Vertex(App.Vector(*volume_centroid(shape))))
            descriptions.append('geometric volume centroid (uniform volume weighting; not mass)')
        else:
            index = feature['edge_index']
            if index >= len(shape.Edges):
                raise ValueError('Selected CAD edge is unavailable; rerun analysis')
            geometry.append(shape.Edges[index])
            descriptions.append('exact CAD edge curve')
        if source != 'exact STEP surfaces':
            descriptions[-1] += ' of conservative hardware envelope'
    distance, pairs, _ = geometry[0].distToShape(geometry[1])
    if not math.isfinite(distance) or distance < 0 or not pairs:
        raise ValueError('Kernel returned no finite feature distance or witnesses')
    points = [xyz(point) for point in pairs[0]]
    if len(points) != 2 or not math.isclose(math.dist(*points), distance, abs_tol=1e-6, rel_tol=1e-8):
        raise ValueError('Kernel feature witnesses disagree with distance')
    return dict(type='feature_ruler', measurement_kind=kind, features=features,
                refs=[f['ref'] for f in features], distance_mm=distance, points=points,
                evidence='; '.join(descriptions), feature_evidence=descriptions, unit='mm', status='measured')
