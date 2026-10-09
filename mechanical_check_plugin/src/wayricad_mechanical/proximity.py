"""Conservative AABB search; only the supplied measurement establishes a gap."""
import heapq
import itertools
import math

from .findings import bbox_distance


def envelope_measure(a, b):
    """Closest points of two same-side XY footprint rectangles, in CAD mm."""
    if a['side'] != b['side']:
        raise ValueError('Quick 2D measures same-side footprint envelopes only')
    points = [[], []]
    for i in range(3):
        lo, hi, other_lo, other_hi = a['bounds'][i], a['bounds'][i+3], b['bounds'][i], b['bounds'][i+3]
        first, second = ((hi, other_lo) if hi < other_lo else
                         (lo, other_hi) if other_hi < lo else
                         (max(lo, other_lo), max(lo, other_lo)))
        points[0].append(first)
        points[1].append(second)
    return dict(refs=[a['ref'], b['ref']], distance_mm=math.dist(*points), points=points,
                evidence='2D footprint envelopes', unit='mm', status='measured')


def exact_measure(a, b):
    distance, pairs, _ = a['shape'].distToShape(b['shape'])
    if not math.isfinite(distance) or distance < 0 or not pairs:
        raise ValueError('Kernel returned no finite distance or surface witnesses')
    points = [list(p) for p in pairs[0]]
    if len(points) != 2 or any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in points):
        raise ValueError('Kernel returned invalid surface witnesses')
    return dict(refs=[a['ref'], b['ref']], distance_mm=distance, points=points,
                evidence='exact STEP surfaces', unit='mm', status='measured')


class PairMeasurements:
    def __init__(self, measure):
        self.measure = measure
        self.records = {}
        self.errors = {}
        self.stats = dict(distance_queries=0, cache_hits=0, failed_queries=0, bbox_tests=0)

    def get(self, a, b):
        key = tuple(sorted((a['ref'], b['ref'])))
        if key in self.errors:
            raise ValueError(self.errors[key])
        if key in self.records:
            self.stats['cache_hits'] += 1
            return self.records[key]
        self.stats['distance_queries'] += 1
        try:
            record = self.measure(a, b)
        except Exception as exc:
            self.stats['failed_queries'] += 1
            self.errors[key] = str(exc)
            raise
        self.records[key] = record
        return record


class BoundsTree:
    def __init__(self, bodies):
        self.bounds = ([min(b['bounds'][i] for b in bodies) for i in range(3)] +
                       [max(b['bounds'][i+3] for b in bodies) for i in range(3)])
        self.children = []
        self.bodies = bodies if len(bodies) <= 4 else []
        if not self.bodies:
            axis = max(range(3), key=lambda i: self.bounds[i+3]-self.bounds[i])
            ordered = sorted(bodies, key=lambda b: b['bounds'][axis]+b['bounds'][axis+3])
            middle = len(ordered)//2
            self.children = [BoundsTree(ordered[:middle]), BoundsTree(ordered[middle:])]


def nearest_parts(bodies, cache, same_side=False):
    """Prove a nearest eligible part with lower bounds; failures stay unknown.

    Ties select one deterministic witness. A measured zero is globally minimal;
    stop immediately, even in dense geometry. Collision threshold checks still
    visit all potentially colliding pairs independently of this nearest search.
    """
    eligible = [b for b in bodies if b['kind'] in ('component', 'comparison_component')]
    for side in (('top', 'bottom') if same_side else (None,)):
        group = sorted((b for b in eligible if side is None or b['side'] == side), key=lambda b: b['ref'])
        if len(group) < 2:
            continue
        tree = BoundsTree(group)
        for body in group:
            best, best_distance, failed_bounds = None, math.inf, []
            serial = itertools.count()
            queue = [(0.0, 0, next(serial), tree)]
            while queue:
                lower, depth, _, node = heapq.heappop(queue)
                if lower >= best_distance:
                    break
                if node.children:
                    for child in node.children:
                        cache.stats['bbox_tests'] += 1
                        bound = bbox_distance(body['bounds'], child.bounds)
                        if bound < best_distance:
                            # Equal lower bounds descend immediately to get an
                            # upper bound, avoiding a breadth-first dense scan.
                            heapq.heappush(queue, (bound, depth-1, next(serial), child))
                    continue
                for other in node.bodies:
                    if body is other:
                        continue
                    cache.stats['bbox_tests'] += 1
                    bound = bbox_distance(body['bounds'], other['bounds'])
                    if bound >= best_distance:
                        continue
                    try:
                        record = cache.get(body, other)
                    except Exception:
                        failed_bounds.append(bound)
                        continue
                    value = record['distance_mm']
                    if value < best_distance:
                        best, best_distance = record, value
            if best is not None and not any(bound < best_distance for bound in failed_bounds):
                best.setdefault('nearest_for', []).append(body['ref'])
    return list(cache.records.values())
