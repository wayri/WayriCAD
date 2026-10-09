"""Read-only CAD edge selection against projected sampled polylines.

Samples are ``[screen_x, screen_y, window_depth, world_x, world_y, world_z]``.
Window depth must be normalized to [0, 1]. Screen X/Y and the cursor must use
the same pixel origin, orientation and viewport scale.

The returned position is a *selection witness*, linearly interpolated using
the nearest projected segment parameter. It is exact for a straight segment
under orthographic projection. Under perspective projection it is approximate
because clip W is not supplied; denser sampling reduces that approximation.
Use the returned edge identity, not this witness, for kernel measurements.
"""
from collections.abc import Mapping
import math
from numbers import Real


def _finite_numbers(values):
    return all(isinstance(value, Real) and not isinstance(value, bool)
               and math.isfinite(value) for value in values)


def _sample(point):
    try:
        if len(point) != 6 or not _finite_numbers(point) or not 0 <= point[2] <= 1:
            return None
        return tuple(float(value) for value in point)
    except TypeError:
        return None


def nearest_edge(position, projected_edges, tolerance=8, accept=None):
    """Return the closest accepted sampled edge within at most eight pixels.

    Each edge is a mapping with ``reference``, a nonnegative integer
    ``edge_index``, and iterable ``points`` in the format described above.
    Invalid samples break continuity: segments spanning a clipped or missing
    sample are never invented. Degenerate projected segments are ignored.

    ``accept(candidate)`` can reject a candidate for section clipping or
    occlusion. Rejection permits another segment/edge to win. Closest pixels
    take precedence, then smaller normalized depth, then stable input order.
    Only one accepted candidate is retained; no candidate list is accumulated.
    Invalid cursors return None; an invalid tolerance raises ValueError.
    """
    if not _finite_numbers((tolerance,)) or not 0 <= tolerance <= 8:
        raise ValueError('Edge selection tolerance must be between 0 and 8 screen pixels.')
    try:
        if len(position) != 2 or not _finite_numbers(position):
            return None
        px, py = map(float, position)
    except TypeError:
        return None
    best, best_key = None, None
    for edge in projected_edges:
        if not isinstance(edge, Mapping):
            continue
        reference, edge_index = edge.get('reference'), edge.get('edge_index')
        if (not isinstance(reference, str) or not reference
                or not isinstance(edge_index, int) or isinstance(edge_index, bool) or edge_index < 0):
            continue
        try:
            points = iter(edge.get('points', ()))
        except TypeError:
            continue
        previous = None
        for point in points:
            current = _sample(point)
            if current is None:
                previous = None
                continue
            start, previous = previous, current
            if start is None:
                continue
            if (px < min(start[0], current[0]) - tolerance
                    or px > max(start[0], current[0]) + tolerance
                    or py < min(start[1], current[1]) - tolerance
                    or py > max(start[1], current[1]) + tolerance):
                continue
            dx, dy = current[0] - start[0], current[1] - start[1]
            length_squared = dx * dx + dy * dy
            if not math.isfinite(length_squared) or length_squared <= 1e-12:
                continue
            parameter = ((px - start[0]) * dx + (py - start[1]) * dy) / length_squared
            if not math.isfinite(parameter):
                continue
            parameter = max(0., min(1., parameter))
            witness = [(1 - parameter) * a + parameter * b for a, b in zip(start, current)]
            distance = math.hypot(px - witness[0], py - witness[1])
            if distance > tolerance:
                continue
            key = distance, witness[2]
            if best_key is not None and key >= best_key:
                continue
            candidate = dict(reference=reference, edge_index=edge_index,
                             position=witness[3:], screen_position=witness[:2],
                             depth=witness[2], screen_distance=distance)
            if accept is None or accept(candidate):
                best, best_key = candidate, key
    return best
