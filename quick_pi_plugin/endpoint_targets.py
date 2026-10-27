"""Screen-space endpoint markers and conservative proximity picking.

Different electrical units never share a wheel target. Pads in the same unit
do: their total requested current is changed once, without an equal pad split.
"""
from dataclasses import dataclass
import math


PROXIMITY_PX = 14.
AMBIGUITY_PX = 2.


@dataclass(frozen=True)
class EndpointHit:
    role: str
    index: int | None
    label: str
    ambiguous: bool = False


def pad_center(outline):
    """Use the same bounding-box center for visible markers and hit targets."""
    return ((min(point[0] for point in outline) + max(point[0] for point in outline)) / 2,
            (min(point[1] for point in outline) + max(point[1] for point in outline)) / 2)


def marker_style(is_source, board_view=True):
    """Modest fixed-point markers retain visibility without hiding copper."""
    color = (0.075, .52, .30) if is_source else (.73, .27, .21)
    return dict(marker='o' if is_source else 's', markersize=8.5 if board_view else 9.,
                color='#13854c' if is_source else '#b94535',
                markerfacecolor=(*color, .27), markeredgecolor=(*color, .85),
                markeredgewidth=1.2, linestyle='none', zorder=10)


def _edge_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    amount = max(0., min(1., ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length)) if length else 0.
    return math.hypot(point[0] - start[0] - amount * dx, point[1] - start[1] - amount * dy)


def _inside(point, ring):
    inside = False
    x, y = point
    for start, end in zip(ring, ring[1:] + ring[:1]):
        ax, ay = start
        bx, by = end
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def project_anchors(anchors, transform):
    """Project all pad vertices once per view transform, using one bulk call."""
    points=[];spans=[]
    for anchor in anchors:
        start=len(points);points.append(anchor['center']);points.extend(anchor.get('outline',()))
        spans.append((anchor,start,len(points)))
    if not points:return []
    projected=transform(points);result=[]
    for anchor,start,end in spans:
        center=tuple(projected[start]);ring=[tuple(point) for point in projected[start+1:end]]
        bounds=(min(p[0] for p in ring),min(p[1] for p in ring),max(p[0] for p in ring),max(p[1] for p in ring)) if ring else (*center,*center)
        result.append({**anchor,'center':center,'outline':ring,'bounds':bounds})
    return result


def pick_endpoint(mouse, anchors, transform, proximity_px=PROXIMITY_PX,
                  ambiguity_px=AMBIGUITY_PX):
    """Pick the nearest distinct unit, or explicitly reject overlapping targets.

    ``mouse`` and anchor coordinates are data coordinates; ``transform`` maps
    them to display pixels. Direct pad hits take precedence over nearby pads.
    Outside a pad, distance is measured from its outline or visible marker.
    Equidistant units within a small pixel margin are ambiguous, rather than
    silently choosing a sink by list order. Repeated pads/layers of one unit
    remain a single target. Callers filter layers before supplying anchors.
    """
    mouse = tuple(transform(mouse)) if transform is not None else tuple(mouse)
    units = {}
    for anchor in anchors:
        center = tuple(transform(anchor['center'])) if transform is not None else anchor['center']
        if transform is None and 'bounds' in anchor:
            left,top,right,bottom=anchor['bounds']
            if math.hypot(max(left-mouse[0],0.,mouse[0]-right),max(top-mouse[1],0.,mouse[1]-bottom))>proximity_px:
                continue
        ring = [tuple(transform(point[:2])) for point in anchor.get('outline', ())] if transform is not None else anchor.get('outline',[])
        center_distance = math.dist(center, mouse)
        edge_distance = min((_edge_distance(mouse, a, b)
                             for a, b in zip(ring, ring[1:] + ring[:1])), default=math.inf)
        inside = len(ring) >= 3 and (_inside(mouse, ring) or edge_distance <= 1e-7)
        distance = 0. if inside else min(center_distance, edge_distance)
        if distance > proximity_px:
            continue
        key = (anchor['role'], anchor.get('index'))
        record = (inside, distance, center_distance, str(anchor['label']))
        previous = units.get(key)
        if previous is None or (not inside, distance, center_distance) < (not previous[0], previous[1], previous[2]):
            units[key] = record
    if not units:
        return None
    direct = {key: value for key, value in units.items() if value[0]}
    ranked = sorted((value[1], value[2], key, value[3]) for key, value in (direct or units).items())
    first = ranked[0]
    competitors = ranked if direct else [row for row in ranked if row[0] - first[0] <= ambiguity_px]
    if len(competitors) > 1:
        labels = ', '.join(dict.fromkeys(row[3] for row in competitors))
        return EndpointHit('ambiguous', None, labels, True)
    return EndpointHit(first[2][0], first[2][1], first[3])
