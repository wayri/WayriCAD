"""Conservative, deterministic centreline simplification; all distances are mm.

This module knows nothing about nets, clearance, tracks, or native KiCad APIs.
Callers must check those contracts separately. A returned path has fixed ends
and at most one 0/45/90-degree bend. None means no eligible improvement.
"""

from math import hypot, isfinite

# Far below KiCad's 1 nm coordinate grid. Used only for angle/length equality,
# never to expand the requested deviation capsule.
_EQUALITY_MM = 1e-9


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _length(points):
    return sum(hypot(*_sub(b, a)) for a, b in zip(points, points[1:]))


def _collapse(points):
    result = []
    for point in points:
        while len(result) > 1:
            u, v = _sub(result[-1], result[-2]), _sub(point, result[-1])
            if _cross(u, v) != 0 or _dot(u, v) <= 0:
                break
            result.pop()
        result.append(point)
    return result


def _distance_squared(point, a, b):
    vector, offset = _sub(b, a), _sub(point, a)
    square = _dot(vector, vector)
    projection = _dot(offset, vector)
    if 0 <= projection <= square and _cross(offset, vector) == 0:
        return 0.0
    fraction = min(1.0, max(0.0, projection / square))
    return (offset[0] - fraction * vector[0]) ** 2 + (offset[1] - fraction * vector[1]) ** 2


def _covered(source, target, radius):
    """Prove directed coverage by convex segment capsules, never just samples.

    Both endpoints inside one target segment's radius capsule prove the whole
    source interval is inside it by convexity. Subdivide otherwise. The finite
    work/depth limits can reject a valid borderline path, never approve an
    unproved interval. Testing in both directions bounds Hausdorff distance.
    """
    segments = list(zip(target, target[1:]))
    pending = [(a, b, 0) for a, b in zip(source, source[1:])]
    limit = radius * radius
    budget = 8192
    while pending:
        budget -= 1
        if budget < 0:
            return False
        a, b, depth = pending.pop()
        distances = [(_distance_squared(a, c, d), _distance_squared(b, c, d))
                     for c, d in segments]
        if any(x <= limit and y <= limit for x, y in distances):
            continue
        if min(x for x, _ in distances) > limit or min(y for _, y in distances) > limit:
            return False
        if depth >= 20:
            return False
        middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        pending.extend(((a, middle, depth + 1), (middle, b, depth + 1)))
    return True


def _on_segment(point, a, b):
    return (_cross(_sub(point, a), _sub(b, a)) == 0
            and min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= point[1] <= max(a[1], b[1]))


def _intersects(a, b, c, d):
    ab, cd = _sub(b, a), _sub(d, c)
    p, q = _cross(ab, _sub(c, a)), _cross(ab, _sub(d, a))
    r, s = _cross(cd, _sub(a, c)), _cross(cd, _sub(b, c))
    if ((p > 0 > q or q > 0 > p) and (r > 0 > s or s > 0 > r)):
        return True
    return ((p == 0 and _on_segment(c, a, b)) or (q == 0 and _on_segment(d, a, b))
            or (r == 0 and _on_segment(a, c, d)) or (s == 0 and _on_segment(b, c, d)))


def _octilinear(a, b):
    x, y = _sub(b, a)
    return abs(x) <= _EQUALITY_MM or abs(y) <= _EQUALITY_MM or abs(abs(x) - abs(y)) <= _EQUALITY_MM


def _single_excursions(points, candidate):
    """Each candidate leg may absorb one small excursion, not repeated tuning."""
    legs = list(zip(candidate, candidate[1:]))
    offsets = [[] for _ in legs]
    previous = 0
    for point in points:
        index = min(range(len(legs)), key=lambda i: _distance_squared(point, *legs[i]))
        if index < previous:
            return False
        previous = index
        a, b = legs[index]
        offsets[index].append(_cross(_sub(b, a), _sub(point, a)))
    for values, (leg_start, leg_end) in zip(offsets, legs):
        signs = []
        noise = _EQUALITY_MM * hypot(*_sub(leg_end, leg_start))
        for a, b in zip(values, values[1:]):
            difference = b - a
            # Cross products scale with leg length; suppress numerical noise
            # in equal offsets without relaxing the geometric coverage test.
            if abs(difference) > noise and (not signs or (difference > 0) != signs[-1]):
                signs.append(difference > 0)
        if len(signs) > 2:
            return False
    return True


def simplify(points, max_deviation=0.05, max_shortening=0.1):
    """Return a shorter-vertex path or None, with absolute mm bounds.

    Reject invalid coordinates, repeated points, intersections, reverse travel
    along the end-to-end direction, and repeated transverse excursions (tuning
    meanders). Exact collinear subdivisions can collapse at zero deviation.
    Candidates are ranked by length, vertex count, then coordinates. This is
    deliberately incomplete: conservative coverage proof limits may reject
    geometrically permissible candidates.
    """
    try:
        points = [tuple(map(float, point)) for point in points]
        if (not isfinite(max_deviation) or not isfinite(max_shortening)
                or max_deviation < 0 or max_shortening < 0
                or len(points) < 3 or len(points) > 256
                or any(len(p) != 2 or not all(map(isfinite, p)) for p in points)
                or len(set(points)) != len(points)):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    direction = _sub(points[-1], points[0])
    segments = list(zip(points, points[1:]))
    for index, (a, b) in enumerate(segments):
        vector = _sub(b, a)
        if _dot(vector, direction) < 0:
            return None
        for c, d in segments[index + 2:]:
            if _intersects(a, b, c, d):
                return None
    original = _collapse(points)
    start, end = points[0], points[-1]
    candidates = []
    if _octilinear(start, end):
        candidates.append([start, end])
    # Intersections of the four permitted line orientations through each end.
    orientations = ((1, 0), (0, 1), (1, 1), (1, -1))
    for u in orientations:
        for v in orientations:
            denominator = _cross(u, v)
            if denominator == 0:
                continue
            scale = _cross(direction, v) / denominator
            bend = (start[0] + scale * u[0], start[1] + scale * u[1])
            if bend in (start, end):
                continue
            first, second = _sub(bend, start), _sub(end, bend)
            if (_dot(first, second) >= 0 and _dot(first, direction) >= 0
                    and _dot(second, direction) >= 0
                    and _octilinear(start, bend) and _octilinear(bend, end)):
                candidates.append([start, bend, end])
    # Exact collinear collapse represents the same geometric path and avoids
    # sum-rounding making a diagonal subdivision appear microscopically short.
    initial_length = _length(original)
    for candidate in sorted(candidates, key=lambda p: (_length(p), len(p), p)):
        if len(candidate) >= len(points) or not _single_excursions(points, candidate):
            continue
        shortening = initial_length - _length(candidate)
        if not -_EQUALITY_MM <= shortening <= max_shortening + _EQUALITY_MM:
            continue
        if (_covered(original, candidate, max_deviation)
                and _covered(candidate, original, max_deviation)):
            return candidate
    return None


def simplify_local(points, max_deviation=0.05, max_shortening=0.1):
    """Clean bounded 3..8-vertex windows while retaining larger route bends.

    At most 1024 windows are considered, with at most 129 source vertices.
    Every accepted replacement is checked against the entire original path,
    in both directions, and against the total shortening budget. Repeated
    excursions in forward octilinear subchains conservatively exclude tuning
    patterns before any window is changed. None means no eligible cleanup.
    """
    try:
        original = [tuple(map(float, point)) for point in points]
        if (not isfinite(max_deviation) or not isfinite(max_shortening)
                or max_deviation < 0 or max_shortening < 0
                or not 3 <= len(original) <= 129
                or any(len(p) != 2 or not all(map(isfinite, p)) for p in original)
                or len(set(original)) != len(original)):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    original_segments = list(zip(original, original[1:]))
    for a, b, c in zip(original, original[1:], original[2:]):
        first, second = _sub(b, a), _sub(c, b)
        if _cross(first, second) == 0 and _dot(first, second) < 0:
            return None
    for index, (a, b) in enumerate(original_segments):
        if any(_intersects(a, b, c, d) for c, d in original_segments[index + 2:]):
            return None
    for start in range(len(original) - 4):
        for size in range(5, min(9, len(original) - start) + 1):
            window = original[start:start + size]
            chord = _sub(window[-1], window[0])
            if (_octilinear(window[0], window[-1])
                    and all(_dot(_sub(b, a), chord) >= 0 for a, b in zip(window, window[1:]))
                    and not _single_excursions(window, [window[0], window[-1]])):
                return None
    result = original[:]
    initial_length = _length(_collapse(original))
    start, attempts = 0, 0
    while start < len(result) - 2 and attempts < 1024:
        changed = False
        for size in range(min(8, len(result) - start), 2, -1):
            if attempts >= 1024:
                break
            attempts += 1
            remaining = max(0.0, max_shortening - (initial_length - _length(_collapse(result))))
            replacement = simplify(result[start:start + size], max_deviation, remaining)
            if replacement is None:
                continue
            candidate = result[:start] + replacement + result[start + size:]
            shortening = initial_length - _length(_collapse(candidate))
            if not -_EQUALITY_MM <= shortening <= max_shortening + _EQUALITY_MM:
                continue
            if len(set(candidate)) != len(candidate):
                continue
            segments = list(zip(candidate, candidate[1:]))
            if any(_intersects(a, b, c, d) for i, (a, b) in enumerate(segments)
                   for c, d in segments[i + 2:]):
                continue
            if (_covered(_collapse(original), _collapse(candidate), max_deviation)
                    and _covered(_collapse(candidate), _collapse(original), max_deviation)):
                result, changed = candidate, True
                break
        start = max(0, start - 1) if changed else start + 1
    return result if result != original else None
