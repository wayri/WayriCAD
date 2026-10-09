"""Display-only polygon tessellation of saved board contours, without CAD writes.

Vertical strips preserve straight saved contour edges, including concave boards,
disjoint outlines, overlapping drills and drills crossing an Edge.Cuts boundary.
No raster mask, convex hull or invented rectangular substrate replaces geometry.
"""
from __future__ import annotations


def board_tiles(view):
    """Return convex XY faces for the outline minus its cutouts and saved drills."""
    rings = []
    shapes = []
    for shape in view.get('outline', []):
        outer = shape.get('outer_mm', [])
        if len(outer) < 3:
            continue
        outer_id = len(rings)
        rings.append(outer)
        holes = []
        for ring in shape.get('holes_mm', []):
            if len(ring) >= 3:
                holes.append(len(rings)); rings.append(ring)
        shapes.append((outer_id, holes))
    drill_ids = []
    for drill in view.get('drills', []):
        ring = drill.get('contour_mm', [])
        if len(ring) >= 3:
            drill_ids.append(len(rings)); rings.append(ring)
    segments = []
    events = {}
    for ring_id, ring in enumerate(rings):
        for a, b in zip(ring, ring[1:]+ring[:1]):
            if a[0] == b[0]:
                continue
            if a[0] > b[0]:
                a, b = b, a
            segment = (a[0], b[0], a[1], (b[1]-a[1])/(b[0]-a[0]), ring_id)
            index = len(segments); segments.append(segment)
            events.setdefault(a[0], [[], []])[0].append(index)
            events.setdefault(b[0], [[], []])[1].append(index)
    def y_at(segment, x):
        return segment[2] + (x-segment[0])*segment[3]
    drill_set = set(drill_ids)
    def inside(active_rings):
        return (not drill_set.intersection(active_rings) and
                any(outer in active_rings and not any(h in active_rings for h in holes)
                    for outer, holes in shapes))
    xs = sorted(events)
    active = set(); faces = []
    for left, right in zip(xs, xs[1:]):
        active.difference_update(events[left][1]); active.update(events[left][0])
        edges = [segments[i] for i in active]
        # Intersecting contours need additional strip boundaries so crossing
        # edges never swap order inside a face (e.g. an edge mounting slot).
        splits = {left, right}
        for index, a in enumerate(edges):
            for b in edges[index+1:]:
                slope = a[3]-b[3]
                if a[4] == b[4] or abs(slope) < 1e-14:
                    continue
                cross = (b[2]-b[0]*b[3]-a[2]+a[0]*a[3])/slope
                if left+1e-10 < cross < right-1e-10:
                    splits.add(cross)
        splits = sorted(splits)
        for x0, x1 in zip(splits, splits[1:]):
            middle = (x0+x1)/2
            ordered = sorted(edges, key=lambda edge: y_at(edge, middle))
            active_rings = set()
            for index, lower in enumerate(ordered[:-1]):
                if lower[4] in active_rings:
                    active_rings.remove(lower[4])
                else:
                    active_rings.add(lower[4])
                upper = ordered[index+1]
                if inside(active_rings) and y_at(upper, middle)-y_at(lower, middle) > 1e-10:
                    faces.append([(x0, y_at(lower, x0)), (x1, y_at(lower, x1)),
                                  (x1, y_at(upper, x1)), (x0, y_at(upper, x0))])
    return faces


def clip_rectangle(face, bounds):
    """Clip a convex XY face to a field cell, preserving subcell holes."""
    result = face
    for axis, limit, keep_above in ((0, bounds[0], True), (0, bounds[2], False),
                                    (1, bounds[1], True), (1, bounds[3], False)):
        if not result:
            return []
        clipped = []
        previous = result[-1]
        for current in result:
            previous_in = previous[axis] >= limit if keep_above else previous[axis] <= limit
            current_in = current[axis] >= limit if keep_above else current[axis] <= limit
            if previous_in != current_in:
                fraction = (limit-previous[axis])/(current[axis]-previous[axis])
                clipped.append(tuple(previous[i]+fraction*(current[i]-previous[i]) for i in (0, 1)))
            if current_in:
                clipped.append(current)
            previous = current
        result = clipped
    area = abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(result, result[1:]+result[:1])))/2
    return result if len(result) >= 3 and area > 1e-12 else []
