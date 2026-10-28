"""Conservative, dependency-free planning of ideal two-layer ROI boundary ports.

Coordinates are millimetres. This module does not infer interior feed points or
establish electrical/solver qualification from polygon geometry.
"""
from copy import deepcopy
import math

EPS = 1e-6


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _point(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _on(p, a, b):
    d = _sub(b, a)
    length = math.hypot(*d)
    return abs(_cross(_sub(p, a), d)) <= EPS * length and all(
        min(a[i], b[i]) - EPS <= p[i] <= max(a[i], b[i]) + EPS for i in (0, 1))


def _ring(raw):
    if not isinstance(raw, (list, tuple)):
        raise ValueError('Polygon ring must be a sequence')
    points = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) != 2 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in p
        ):
            raise ValueError('Polygon coordinates must be finite numbers')
        points.append(tuple(p))
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3 or len(set(points)) != len(points):
        raise ValueError('Polygon ring has missing or duplicate vertices')
    if any(math.dist(a, b) <= EPS for a, b in _edges(points)):
        raise ValueError('Polygon has a zero-length edge')
    if abs(sum(_cross(a, b) for a, b in _edges(points))) <= EPS * EPS:
        raise ValueError('Polygon has zero area')
    edges = list(_edges(points))
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges):
            if j <= i or j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            v, w = _sub(b, a), _sub(d, c)
            den = _cross(v, w)
            if abs(den) > EPS * max(math.hypot(*v), math.hypot(*w)):
                t = _cross(_sub(c, a), w) / den
                u = _cross(_sub(c, a), v) / den
                intersects = 0 <= t <= 1 and 0 <= u <= 1
            else:
                intersects = any((_on(p, a, b) for p in (c, d))) or any(
                    (_on(p, c, d) for p in (a, b)))
            if intersects:
                raise ValueError('Polygon ring self-intersects')
    return points


def _edges(ring):
    return zip(ring, ring[1:] + ring[:1])


def _polygons(raw):
    if not isinstance(raw, list) or not raw:
        raise ValueError('Nonempty polygon list required')
    return [(_ring(p['outer_mm']), [_ring(h) for h in p.get('holes_mm', [])]) for p in raw]


def _all_edges(polys):
    return [edge for outer, holes in polys for ring in [outer] + holes for edge in _edges(ring)]


def _inside_ring(p, ring):
    if any(_on(p, a, b) for a, b in _edges(ring)):
        return 0
    inside = False
    for a, b in _edges(ring):
        if (a[1] > p[1]) != (b[1] > p[1]):
            if p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                inside = not inside
    return 1 if inside else -1


def _covered(p, polys):
    return any(_inside_ring(p, outer) >= 0 and all(_inside_ring(p, h) <= 0 for h in holes)
               for outer, holes in polys)


def _overlap(a, b, c, d):
    length = math.dist(a, b)
    if abs(_cross(_sub(c, a), _sub(b, a))) > EPS * length or abs(
        _cross(_sub(d, a), _sub(b, a))) > EPS * length:
        return None
    axis = 0 if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else 1
    ts = sorted(((c[axis] - a[axis]) / (b[axis] - a[axis]),
                 (d[axis] - a[axis]) / (b[axis] - a[axis])))
    lo, hi = max(0., ts[0]), min(1., ts[1])
    return (_point(a, b, lo), _point(a, b, hi)) if (hi - lo) * length > EPS else None


def _span_covered(a, b, polys):
    """Split at every polygon boundary, including holes, before testing coverage."""
    ts = [0., 1.]
    v = _sub(b, a)
    length = math.dist(a, b)
    for c, d in _all_edges(polys):
        w = _sub(d, c)
        den = _cross(v, w)
        if abs(den) > EPS * max(math.hypot(*v), math.hypot(*w)):
            t, u = _cross(_sub(c, a), w) / den, _cross(_sub(c, a), v) / den
            if -EPS <= t <= 1 + EPS and -EPS <= u <= 1 + EPS:
                ts.append(max(0., min(1., t)))
        else:
            for p in (c, d):
                if _on(p, a, b):
                    ts.append(sum((p[i] - a[i]) * v[i] for i in (0, 1)) / length**2)
    ts = sorted(set(ts))
    return all(_covered(_point(a, b, t), polys) for t in ts) and all(
        _covered(_point(a, b, (x + y) / 2), polys) for x, y in zip(ts, ts[1:]))


def _merge(segments):
    segments = sorted(set(tuple(sorted((a, b))) for a, b in segments))
    changed = True
    while changed:
        changed = False
        for i, (a, b) in enumerate(segments):
            for j in range(i + 1, len(segments)):
                c, d = segments[j]
                if _overlap(a, b, c, d) or any(math.dist(p, q) <= EPS for p in (a, b) for q in (c, d)):
                    if abs(_cross(_sub(c, a), _sub(b, a))) <= EPS * math.dist(a, b) and abs(_cross(_sub(d, a), _sub(b, a))) <= EPS * math.dist(a, b):
                        points = sorted((a, b, c, d))
                        segments[i] = (points[0], points[-1])
                        segments.pop(j)
                        changed = True
                        break
            if changed:
                break
    return sorted(segments)


def plan_region(snapshot, signal_net, reference_net):
    """Return a reviewable plan; unsupported electrical cases become blockers.

    Malformed geometry raises ValueError rather than returning a plausible plan.
    """
    if snapshot.get('schema') != 1:
        raise ValueError('Unsupported snapshot schema')
    if not isinstance(signal_net, str) or not signal_net or not isinstance(reference_net, str) or not reference_net:
        raise ValueError('Signal and reference net names are required')
    try:
        thickness = snapshot['substrate']['thickness_mm']
        if isinstance(thickness, bool) or not isinstance(thickness, (int, float)) or not math.isfinite(thickness) or thickness <= 0:
            raise ValueError('Substrate thickness must be finite and positive')
        substrate = _polygons(snapshot['substrate']['outline'])
        area = _polygons(snapshot['area']['outline'])
        copper = [(item, _polygons(item['polygons'])) for item in snapshot['copper']]
    except (KeyError, TypeError) as exc:
        raise ValueError('Malformed ROI snapshot') from exc
    result = {key: deepcopy(snapshot[key]) for key in ('source', 'area', 'substrate', 'copper')}
    result.update(schema=1, ports=[], diagnostics=[], blockers=[])
    blockers = result['blockers']
    blockers.extend(str(x) for x in snapshot.get('unsupported', []))
    if signal_net == reference_net:
        blockers.append('Signal and reference nets must differ')
    substrate_boundary = _all_edges(substrate)
    # Only rule-area cuts can terminate a boundary port. Natural board edges
    # and pre-existing board cutouts are physical geometry, not invented feeds.
    boundary = _merge([overlap for a, b in substrate_boundary
                       for c, d in _all_edges(area)
                       if (overlap := _overlap(a, b, c, d)) is not None])
    reference = [p for item, polys in copper if item.get('layer') == 'B.Cu' and item.get('net') == reference_net for p in polys]
    candidates = []
    for item, polys in copper:
        cuts = [overlap for a, b in _all_edges(polys) for c, d in boundary
                if (overlap := _overlap(a, b, c, d)) is not None]
        if item.get('layer') == 'F.Cu' and item.get('net') == signal_net:
            candidates.extend(cuts)
        elif not (item.get('layer') == 'B.Cu' and item.get('net') == reference_net) and cuts:
            blockers.append('Unselected cut conductor: %s on %s' % (item.get('net'), item.get('layer')))
        if item.get('layer') not in ('F.Cu', 'B.Cu'):
            blockers.append('Unsupported copper layer: %s' % item.get('layer'))
    candidates = _merge(candidates)
    if not candidates:
        blockers.append('No signal crossing at a rule-area cut of the substrate boundary; explicit interior ports are unsupported')
    if len(candidates) > 8:
        blockers.append('More than eight boundary ports are unsupported')
    for a, b in candidates:
        # A port touching a substrate corner has no unique boundary normal.
        if any((_on(a, c, d) or _on(b, c, d)) and abs(_cross(_sub(b, a), _sub(d, c))) > EPS * math.dist(a, b)
               for c, d in substrate_boundary):
            blockers.append('Ambiguous signal port at a substrate corner')
        if not reference or not _span_covered(a, b, reference):
            blockers.append('Reference copper does not continuously cover the entire port span')
        result['ports'].append(dict(number=len(result['ports']) + 1, signal_net=signal_net,
            reference_net=reference_net, a_mm=list(a), b_mm=list(b), width_mm=math.dist(a, b),
            z_signal_mm=0., z_reference_mm=-thickness))
    result['blockers'] = list(dict.fromkeys(blockers))
    result['diagnostics'].append('Ideal lumped boundary ports only; geometry does not establish solver qualification')
    return result
