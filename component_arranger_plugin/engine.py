"""Bounded deterministic placement proposals in millimetres.

Courtyards and pads are footprint-local. Bottom poses mirror local X before
rotation. This module screens envelopes and straight-line net MSTs; it does not
route copper, qualify decoupling loops, or replace native board validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import re
from typing import Mapping

Point = tuple[float, float]
Polygon = tuple[Point, ...]
EPS = 1e-8
MAX_FOOTPRINTS = 128
MAX_PADS = 512


@dataclass(frozen=True)
class Pad:
    number: str
    net: str
    x: float
    y: float


@dataclass(frozen=True)
class Footprint:
    key: str
    reference: str
    x: float
    y: float
    angle: float = 0.0
    side: str = "top"
    courtyards: tuple[Polygon, ...] = ()
    pads: tuple[Pad, ...] = ()
    fields: Mapping[str, str] = field(default_factory=dict)
    package: str = "unknown"
    locked: bool = False
    through_hole: bool = False
    routing_margin: float = 0.0


@dataclass(frozen=True)
class Obstacle:
    polygon: Polygon
    sides: tuple[str, ...] = ("top", "bottom")


@dataclass(frozen=True)
class Settings:
    anchor: str
    area: tuple[float, float, float, float]
    allowed_angles: tuple[float, ...] = (0.0, 90.0)
    allowed_sides: tuple[str, ...] = ("top",)
    density: float = 0.5
    grid_mm: float = 0.5
    max_candidates: int = 6000
    passes: int = 2
    capacitor_targets: Mapping[str, str] = field(default_factory=dict)
    crossing_weight: float = 10.0
    external_pads: tuple[Pad, ...] = ()


@dataclass(frozen=True)
class Metrics:
    length_mm: float
    crossings: int
    edges: int
    capacitor_order_violations: int = 0
    capacitor_distance_mm: float = 0.0


@dataclass(frozen=True)
class Result:
    footprints: tuple[Footprint, ...]
    before: Metrics
    after: Metrics
    achieved_density: float
    target_density: float
    complete: bool
    warnings: tuple[str, ...]
    evaluations: int


def transform(point: Point, footprint: Footprint) -> Point:
    """Transform one local point using mirror-X, rotation, then translation."""
    x, y = point
    if footprint.side == "bottom":
        x = -x
    angle = math.radians(footprint.angle)
    c, s = math.cos(angle), math.sin(angle)
    return footprint.x + x*c - y*s, footprint.y + x*s + y*c


def world_courtyards(footprint: Footprint) -> tuple[Polygon, ...]:
    return tuple(tuple(transform(p, footprint) for p in poly)
                 for poly in footprint.courtyards)


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def _on(a: Point, b: Point, p: Point) -> bool:
    return (abs(_cross(a, b, p)) <= EPS and
            min(a[0], b[0])-EPS <= p[0] <= max(a[0], b[0])+EPS and
            min(a[1], b[1])-EPS <= p[1] <= max(a[1], b[1])+EPS)


def _intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
    v = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    if ((v[0] > EPS and v[1] < -EPS or v[0] < -EPS and v[1] > EPS) and
            (v[2] > EPS and v[3] < -EPS or v[2] < -EPS and v[3] > EPS)):
        return True
    return any((_on(a, b, c), _on(a, b, d), _on(c, d, a), _on(c, d, b)))


def _edges(poly: Polygon):
    return zip(poly, poly[1:] + poly[:1])


def _inside(p: Point, poly: Polygon) -> bool:
    inside = False
    for a, b in _edges(poly):
        if _on(a, b, p):
            return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1]) + a[0]
            if p[0] < x:
                inside = not inside
    return inside


def _point_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0]-a[0], b[1]-a[1]
    den = dx*dx + dy*dy
    t = max(0.0, min(1.0, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)) if den else 0
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def _bounds(poly: Polygon) -> tuple[float, float, float, float]:
    return min(p[0] for p in poly), min(p[1] for p in poly), max(p[0] for p in poly), max(p[1] for p in poly)


def polygons_conflict(a: Polygon, b: Polygon, clearance: float = 0.0) -> bool:
    """Reject touching, overlap, containment and insufficient edge clearance."""
    ax, ay, ar, at = _bounds(a)
    bx, by, br, bt = _bounds(b)
    if ar+clearance < bx-EPS or br+clearance < ax-EPS or at+clearance < by-EPS or bt+clearance < ay-EPS:
        return False
    if _inside(a[0], b) or _inside(b[0], a):
        return True
    for p, q in _edges(a):
        for r, s in _edges(b):
            if _intersects(p, q, r, s):
                return True
            if clearance > 0 and min(_point_distance(p, r, s), _point_distance(q, r, s),
                                     _point_distance(r, p, q), _point_distance(s, p, q)) < clearance-EPS:
                return True
    return False


def _contained(poly: Polygon, boundary: Polygon, margin: float) -> bool:
    if not all(_inside(p, boundary) for p in poly):
        return False
    for a, b in _edges(poly):
        # Endpoints alone do not establish containment in a concave outline.
        for c, d in _edges(boundary):
            if _intersects(a, b, c, d):
                return False
            if margin > 0 and min(_point_distance(a, c, d), _point_distance(b, c, d),
                                  _point_distance(c, a, b), _point_distance(d, a, b)) < margin-EPS:
                return False
    return True


def _share_side(a: Footprint, b: Footprint) -> bool:
    return a.through_hole or b.through_hole or a.side == b.side


def legal(footprint: Footprint, others: tuple[Footprint, ...], settings: Settings,
          obstacles: tuple[Obstacle, ...] = (), board_outline: Polygon | None = None,
          board_holes: tuple[Polygon, ...] = ()) -> bool:
    """Check actual polygon envelopes, routing margins, board and hole boundaries."""
    xmin, ymin, xmax, ymax = settings.area
    for poly in world_courtyards(footprint):
        margin = footprint.routing_margin
        x0, y0, x1, y1 = _bounds(poly)
        if x0-margin < xmin-EPS or y0-margin < ymin-EPS or x1+margin > xmax+EPS or y1+margin > ymax+EPS:
            return False
        if board_outline and not _contained(poly, board_outline, margin):
            return False
        if any(polygons_conflict(poly, hole, margin) for hole in board_holes):
            return False
        if any((footprint.through_hole or footprint.side in obstacle.sides) and
               polygons_conflict(poly, obstacle.polygon, margin) for obstacle in obstacles):
            return False
        for other in others:
            if other.key == footprint.key or not _share_side(footprint, other):
                continue
            if any(polygons_conflict(poly, op, margin + other.routing_margin)
                   for op in world_courtyards(other)):
                return False
    return True


def _capacitance_values(value: str, *, allow_code: bool = False) -> list[float]:
    if not isinstance(value, str):
        return []
    value = value.strip().replace("\u00b5", "u").replace("\u03bc", "u")
    explicit = list(re.finditer(
        r"(?<![\w.+-])((?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)\s*([munp]?)f(?![a-z])",
        value, re.I))
    embedded = list(re.finditer(
        r"(?<![\w.+-])(\d+)([munp])(\d+)(?:f)?(?!\w)", value, re.I))
    values = []
    for match in explicit:
        number, unit = float(match[1]), match[2].lower()
        result = number * {"": 1, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}[unit]
        values.append(result if math.isfinite(result) and result > 0 else math.nan)
    for match in embedded:
        number, unit = float(match[1]+"."+match[3]), match[2].lower()
        values.append(number * {"m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}[unit])
    if values:
        return values
    shorthand = re.fullmatch(
        r"((?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)\s*([munp])", value, re.I)
    if shorthand:
        result = float(shorthand[1]) * {"m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}[shorthand[2].lower()]
        return [result] if math.isfinite(result) and result > 0 else []
    if allow_code and re.fullmatch(r"\d{3}", value):
        result = int(value[:2]) * 10**int(value[2]) * 1e-12
        return [result] if result > 0 else []
    return []


def parse_capacitance(value: str, *, allow_code: bool = False) -> float | None:
    """Parse one explicit F/mF/uF/nF/pF, embedded 4n7, or enabled EIA code.

    Return farads. Multiple capacitance tokens, invalid values and unitless
    numbers remain unknown. A voltage/tolerance description does not introduce
    another capacitance. EIA codes require a declared marking/code field.
    """
    values = _capacitance_values(value, allow_code=allow_code)
    return values[0] if len(values) == 1 and math.isfinite(values[0]) else None


def capacitance(footprint: Footprint) -> float | None:
    """Read normalized metadata keys; contradictory/ambiguous fields stay unknown."""
    names = {"capacitance", "value", "capacitancevalue", "nominalcapacitance",
             "capvalue", "cvalue", "componentvalue"}
    known = []
    for key, value in footprint.fields.items():
        normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
        code = bool(re.search(r"capacitance.*code|capacitor.*marking|eia.*code", str(key), re.I))
        if normalized not in names and not code:
            continue
        values = _capacitance_values(str(value), allow_code=code)
        if len(values) > 1 or any(not math.isfinite(v) for v in values):
            return None
        known.extend(values)
    if not known or any(not math.isclose(known[0], v, rel_tol=1e-9, abs_tol=0) for v in known[1:]):
        return None
    return known[0]


def classify_package(footprint: Footprint) -> str:
    """Classify declared package metadata; never infer escape feasibility."""
    text = " ".join((footprint.package, *map(str, footprint.fields.values()))).upper()
    for family in ("BGA", "LGA", "QFN", "QFP"):
        if family in text:
            return family
    if footprint.through_hole or "THT" in text:
        return "THT"
    return "SMD" if "SMD" in text or "SMD" in footprint.package.upper() else "unknown"


def infer_anchor(footprints: tuple[Footprint, ...]) -> str:
    """Suggest the most connected, then largest component with stable tie-breaking."""
    if not footprints:
        raise ValueError("Select at least one footprint")
    def rank(fp):
        nets = {p.net for p in fp.pads if p.net}
        links = sum(bool(nets & {p.net for p in other.pads if p.net}) for other in footprints if other.key != fp.key)
        return -links, -len(fp.pads), -sum(abs(_area(p)) for p in fp.courtyards), fp.reference, fp.key
    return min(footprints, key=rank).key


def _area(poly: Polygon) -> float:
    return sum(a[0]*b[1]-a[1]*b[0] for a, b in _edges(poly))/2


def suggested_area(footprints: tuple[Footprint, ...], anchor: str, density: float = 0.5,
                   allowed_sides: tuple[str, ...] = ("top",)) -> tuple[float, float, float, float]:
    """Suggest a square around the anchor using reserved envelope area, not routability."""
    if not 0 < density <= 1:
        raise ValueError("Density must be in (0, 1]")
    center = next((fp for fp in footprints if fp.key == anchor), None)
    if center is None:
        raise ValueError("Choose an anchor footprint from the selection")
    if not allowed_sides or not set(allowed_sides) <= {"top", "bottom"}:
        raise ValueError("Allowed sides must contain top and/or bottom")
    count = len(set(allowed_sides))
    reserved = sum(_reserved_area(fp) * (count if fp.through_hole else 1)
                   for fp in footprints)
    side = math.sqrt(reserved / (density * count))
    radius = max((max(abs(x-center.x), abs(y-center.y)) + center.routing_margin
                  for p in world_courtyards(center) for x, y in p), default=0)
    half = max(side/2, radius + 0.5)
    return center.x-half, center.y-half, center.x+half, center.y+half


def _reserved_area(fp: Footprint) -> float:
    return sum((_bounds(p)[2]-_bounds(p)[0]+2*fp.routing_margin)*
               (_bounds(p)[3]-_bounds(p)[1]+2*fp.routing_margin) for p in fp.courtyards)


def _cap_targets(footprints: tuple[Footprint, ...], settings: Settings):
    anchor = next(fp for fp in footprints if fp.key == settings.anchor)
    associations = {}
    for fp in footprints:
        if fp.key == anchor.key:
            continue
        explicit = settings.capacitor_targets.get(fp.key, settings.capacitor_targets.get(fp.reference))
        is_cap = re.match(r"^C\d", fp.reference, re.I) or any("capacitor" in str(v).lower() for v in fp.fields.values())
        if not is_cap and explicit is None:
            continue
        candidates = [p for p in anchor.pads if p.number == explicit] if explicit is not None else [
            p for p in anchor.pads if p.net and re.search(r"(?:VCC|VDD|VIN|VBAT|VREF|VEE|\dV\d|[+-]\d)", p.net, re.I)
            and any(q.net == p.net for q in fp.pads)]
        if candidates:
            chosen = min(candidates, key=lambda p: (math.hypot(transform((p.x,p.y),anchor)[0]-fp.x,
                                                                    transform((p.x,p.y),anchor)[1]-fp.y),p.number))
            if explicit is not None and not any(p.net and p.net == chosen.net for p in fp.pads):
                raise ValueError(f"{fp.reference} has no pad on anchor pad {explicit} net; choose a shared power pin")
            associations[fp.key] = (chosen.number, transform((chosen.x,chosen.y),anchor), chosen.net, capacitance(fp))
        elif explicit is not None:
            raise ValueError(f"Unknown anchor pad {explicit!r} for capacitor {fp.reference}")
    return associations


def _mst(points):
    if len(points) < 2:
        return []
    result = []
    # Prim updates each unconnected point once per added vertex, O(pads^2).
    best = {i: (math.dist(points[0], points[i]), 0) for i in range(1,len(points))}
    while best:
        j = min(best, key=lambda k: (best[k][0], best[k][1], k))
        distance, i = best.pop(j)
        result.append((points[i], points[j], distance))
        for k in best:
            proposal = (math.dist(points[j], points[k]), j)
            if proposal < best[k]:
                best[k] = proposal
    return result


def metrics(footprints: tuple[Footprint, ...], settings: Settings | None = None) -> Metrics:
    """Count net MST length and crossings of different-net straight edges in XY.

    Crossings include bottom-to-top projected edges: this is a ratsnest proxy,
    not a count of physical copper shorts or proof of route completion.
    """
    nets = {}
    for fp in footprints:
        for pad in fp.pads:
            if pad.net:
                nets.setdefault(pad.net, []).append(transform((pad.x,pad.y), fp))
    if settings:
        for pad in settings.external_pads:
            if pad.net:
                nets.setdefault(pad.net, []).append((pad.x,pad.y))
    edges = [(net,a,b,length) for net, points in sorted(nets.items())
             for a,b,length in _mst(sorted(set(points)))]
    crossings = sum(a[0] != b[0] and _intersects(a[1],a[2],b[1],b[2])
                    for i,a in enumerate(edges) for b in edges[i+1:])
    violations = 0
    distance = 0.0
    if settings:
        targets = _cap_targets(footprints,settings)
        groups = {}
        for fp in footprints:
            if fp.key not in targets:
                continue
            number, target, net, value = targets[fp.key]
            eligible = [transform((p.x,p.y),fp) for p in fp.pads if p.net == net]
            d = min((math.dist(target,p) for p in eligible),default=math.dist(target,(fp.x,fp.y)))
            distance += d
            if value is not None:
                groups.setdefault(number,[]).append((value,d,fp.key))
        for members in groups.values():
            violations += sum(a[0] < b[0] and a[1] >= b[1]-EPS for a in members for b in members)
    return Metrics(sum(e[3] for e in edges),crossings,len(edges),violations,distance)


def _density(footprints,settings):
    # Occupancy uses union's enclosing rectangle on each occupied side. Courtyard
    # bounding areas are conservative for concave/multipart envelopes.
    areas = 0.0
    reserved = 0.0
    for side in settings.allowed_sides:
        members = [fp for fp in footprints if fp.side == side or fp.through_hole]
        points = [p for fp in members for poly in world_courtyards(fp) for p in poly]
        if points:
            x0,y0,x1,y1 = _bounds(tuple(points))
            areas += (x1-x0)*(y1-y0)
            reserved += sum(sum(abs(_area(p)) for p in fp.courtyards) for fp in members)
    return min(1.0,reserved/areas) if areas > EPS else 0.0


def _score(footprints,settings):
    m = metrics(footprints,settings)
    # Capacitor order is a first-priority constraint; final results explicitly
    # report infeasibility instead of silently accepting an inverted hierarchy.
    density_error = abs(_density(footprints, settings) - settings.density)
    return (m.capacitor_order_violations, m.crossings,
            max(0.0, density_error - 0.05),
            m.length_mm + m.capacitor_distance_mm, density_error)


def _validate(footprints, settings, obstacles, board_outline, board_holes):
    if not footprints or len({fp.key for fp in footprints}) != len(footprints):
        raise ValueError("Footprints must have unique keys and a nonempty selection")
    if len(footprints) > MAX_FOOTPRINTS:
        raise ValueError(f"Select at most {MAX_FOOTPRINTS} footprints per bounded arrangement")
    if sum(len(fp.pads) for fp in footprints) + len(settings.external_pads) > MAX_PADS:
        raise ValueError(f"At most {MAX_PADS} selected plus external pads are supported; choose a smaller group (no endpoints were omitted)")
    if settings.anchor not in {fp.key for fp in footprints}:
        raise ValueError("Choose an anchor footprint from the selection")
    if not settings.allowed_sides or not set(settings.allowed_sides) <= {"top","bottom"}:
        raise ValueError("Allowed sides must contain top and/or bottom")
    if not settings.allowed_angles or any(not math.isfinite(a) for a in settings.allowed_angles):
        raise ValueError("Choose at least one finite allowed rotation")
    values = (*settings.area, settings.density, settings.grid_mm, settings.crossing_weight)
    if not all(math.isfinite(x) for x in values) or not 0 < settings.density <= 1 or settings.grid_mm <= 0 or settings.crossing_weight < 0:
        raise ValueError("Invalid finite area, density, grid or objective weight")
    if settings.area[0] >= settings.area[2] or settings.area[1] >= settings.area[3]:
        raise ValueError("Placement area must have positive width and height")
    if not isinstance(settings.max_candidates,int) or isinstance(settings.max_candidates,bool) or not 1 <= settings.max_candidates <= 100000:
        raise ValueError("Candidate budget must be an integer from 1 to 100000")
    if not isinstance(settings.passes,int) or isinstance(settings.passes,bool) or not 1 <= settings.passes <= 20:
        raise ValueError("Search passes must be an integer from 1 to 20")
    def polygon_valid(poly):
        if len(poly) < 3 or not all(math.isfinite(v) for p in poly for v in p) or abs(_area(poly)) <= EPS:
            return False
        edges = list(_edges(poly))
        return not any(_intersects(a,b,c,d) for i,(a,b) in enumerate(edges) for j,(c,d) in enumerate(edges)
                       if j > i+1 and not (i==0 and j==len(edges)-1))
    if any(not math.isfinite(v) for p in settings.external_pads for v in (p.x,p.y)):
        raise ValueError("Invalid external pad coordinates")
    for fp in footprints:
        if fp.side not in {"top","bottom"} or not all(math.isfinite(v) for v in (fp.x,fp.y,fp.angle,fp.routing_margin)) or fp.routing_margin < 0:
            raise ValueError(f"Invalid pose or routing margin: {fp.reference}")
        if not fp.courtyards or not all(polygon_valid(p) for p in fp.courtyards):
            raise ValueError(f"Missing or invalid courtyard: {fp.reference}")
        if any(not math.isfinite(v) for p in fp.pads for v in (p.x,p.y)):
            raise ValueError(f"Invalid pad coordinates: {fp.reference}")
    if any(not o.sides or not set(o.sides) <= {"top", "bottom"} for o in obstacles):
        raise ValueError("Obstacle sides must contain top and/or bottom")
    if any(not polygon_valid(o.polygon) for o in obstacles) or any(not polygon_valid(p) for p in board_holes) or (board_outline is not None and not polygon_valid(board_outline)):
        raise ValueError("Invalid obstacle or board polygon")


def arrange(footprints: tuple[Footprint, ...], settings: Settings, *,
            obstacles: tuple[Obstacle, ...] = (), board_outline: Polygon | None = None,
            board_holes: tuple[Polygon, ...] = ()) -> Result:
    """Search finite legal poses, preserving anchor/locks and returning measured gains.

    An incomplete result preserves the original input exactly. Search is bounded
    by max_candidates and passes, with no guaranteed crossing/density target.
    Priority is capacitor ordering, crossing count, then meeting the requested
    density within five percentage points. Outside that band, the nearest
    sampled density wins; inside it, length plus capacitor pad distance wins.
    Density can trade some length but can never override crossing priority. Up to 128 selected footprints and 512 total pad endpoints are
    supported without silently discarding external connections.
    Movable parts may use only allowed absolute angles and permitted sides; THT
    parts retain their side. Native copper, model heights and route feasibility
    must be checked by the caller before applying any proposal.
    """
    footprints = tuple(footprints)
    _validate(footprints,settings,obstacles,board_outline,board_holes)
    targets = _cap_targets(footprints,settings)
    before = metrics(footprints,settings)
    warnings = []
    for family in sorted({classify_package(fp) for fp in footprints} & {"BGA", "LGA", "QFP", "QFN", "THT"}):
        warnings.append(f"{family}: routing margins reserve envelope space only; pin escape, via access and assembly clearance require native review")
    for fp in footprints:
        if fp.key in targets and targets[fp.key][3] is None:
            warnings.append(f"{fp.reference}: capacitance unknown; explicit value needed for ordering")
    original = {fp.key:fp for fp in footprints}
    fixed = [fp for fp in footprints if fp.locked or fp.key == settings.anchor]
    movable = sorted((fp for fp in footprints if fp not in fixed),key=lambda fp:(
        fp.key not in targets, targets[fp.key][3] if fp.key in targets and targets[fp.key][3] is not None else math.inf,
        -_reserved_area(fp),fp.reference,fp.key))
    def is_legal(fp,others):
        return legal(fp,tuple(others),settings,obstacles,board_outline,board_holes)
    if not all(is_legal(fp,fixed) for fp in fixed):
        return Result(footprints,before,before,_density(footprints,settings),settings.density,False,
                      tuple(warnings+["Anchor/locked footprints conflict with the area, obstacles or each other"]),0)
    original_legal = all(is_legal(fp,footprints) for fp in footprints)
    original_allowed = all(fp.side in settings.allowed_sides and any(abs((fp.angle-a+180)%360-180)<EPS for a in settings.allowed_angles)
                           for fp in movable)
    best = footprints if original_legal and original_allowed else None
    best_score = _score(best,settings) if best else None
    current = list(fixed)
    evaluations = 0
    xmin,ymin,xmax,ymax = settings.area
    # Limit grid enumeration before allocation. Large areas use a coarser grid,
    # while the original pose and target-adjacent positions remain candidates.
    spacing = max(settings.grid_mm,math.sqrt((xmax-xmin)*(ymax-ymin)/max(64,settings.max_candidates)))
    nx = min(512,int((xmax-xmin)/spacing)+1)
    ny = min(512,int((ymax-ymin)/spacing)+1)
    anchor = original[settings.anchor]
    grid = [(xmin+i*spacing,ymin+j*spacing) for i in range(nx) for j in range(ny)]
    # Greedy legalization then coordinate descent. All options are exact polygon
    # tested; later passes can improve a legal initial layout without worsening it.
    for pass_index in range(settings.passes):
        if pass_index:
            if best is None:
                break
            current = list(best)
        failed = False
        for index,fp in enumerate(movable):
            current_fp = next((p for p in current if p.key==fp.key),fp)
            placed = [p for p in current if p.key != fp.key]
            remaining = [p for p in movable if p.key not in {q.key for q in placed} and p.key != fp.key]
            # Unplaced originals contribute to objective only, never to legality.
            target = targets[fp.key][1] if fp.key in targets else (anchor.x,anchor.y)
            positions = sorted(set([(current_fp.x,current_fp.y),(fp.x,fp.y),*grid]),
                               key=lambda p:(math.dist(p,target),p))
            slots = max(1,(settings.max_candidates-evaluations)//max(1,(settings.passes-pass_index)*len(movable)-index))
            # Spend some attempts near the target, but spread the remaining
            # sampled positions across the full region. Exhausting every angle
            # at only the closest grid points falsely strands later parts in an
            # otherwise spacious region. Original poses are always tried first.
            orientations = len(settings.allowed_angles) * sum(
                not fp.through_hole or side == fp.side
                for side in settings.allowed_sides)
            position_budget = max(1, slots // max(1, orientations))
            nearby = positions[:max(1, min(64, position_budget // 2))]
            spread_count = max(1, position_budget - len(nearby))
            spread = [positions[round(i * (len(positions)-1) / max(1, spread_count-1))]
                      for i in range(spread_count)]
            preferred = [(current_fp.x, current_fp.y), (fp.x, fp.y), *nearby, *spread]
            unique = dict.fromkeys(preferred + positions)
            positions = list(unique)
            winner = current_fp if is_legal(current_fp,placed) and current_fp.side in settings.allowed_sides and any(abs((current_fp.angle-a+180)%360-180)<EPS for a in settings.allowed_angles) else None
            winner_score = _score(tuple(placed+[winner]+remaining),settings) if winner else None
            used = 0
            for x,y in positions:
                for side in settings.allowed_sides:
                    if fp.through_hole and side != fp.side:
                        continue
                    for angle in settings.allowed_angles:
                        if evaluations >= settings.max_candidates or used >= slots:
                            break
                        evaluations += 1
                        used += 1
                        candidate = replace(fp,x=x,y=y,angle=angle,side=side)
                        if not is_legal(candidate,placed):
                            continue
                        score = _score(tuple(placed+[candidate]+remaining),settings)
                        if winner_score is None or score < winner_score:
                            winner,winner_score = candidate,score
                    if evaluations >= settings.max_candidates or used >= slots:
                        break
                if evaluations >= settings.max_candidates or used >= slots:
                    break
            if winner is None:
                failed = True
                warnings.append(f"No legal sampled pose found for {fp.reference} within area/budget")
                break
            current = placed+[winner]
        if not failed:
            ordered = tuple(next(p for p in current if p.key==fp.key) for fp in footprints)
            score = _score(ordered,settings)
            if all(is_legal(fp,ordered) for fp in ordered) and (best_score is None or score < best_score):
                best,best_score = ordered,score
        if evaluations >= settings.max_candidates:
            break
    if best is None or metrics(best,settings).capacitor_order_violations:
        warnings.append("No fully legal, capacitor-ordered proposal found; original placement retained")
        return Result(footprints,before,before,_density(footprints,settings),settings.density,False,tuple(dict.fromkeys(warnings)),evaluations)
    after = metrics(best,settings)
    achieved = _density(best,settings)
    if abs(achieved-settings.density) > 0.05:
        warnings.append("Requested density was not reached; best sampled legal placement retained")
    if after.crossings:
        warnings.append("Ratsnest crossings remain; zero or 90% reduction is not guaranteed")
    if evaluations >= settings.max_candidates:
        warnings.append("Candidate budget reached")
    warnings.append("Envelope/MST screening only; native clearance, copper connectivity and 3D checks are required")
    return Result(best,before,after,achieved,settings.density,True,tuple(dict.fromkeys(warnings)),evaluations)
