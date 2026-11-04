"""Pure review-canvas coordinates and provider-authorized comment overlays.

The viewport uses downward-positive Y, as SVG does. Callers must establish a
document-to-SVG coordinate mapping before projecting document-mm anchors. This
module neither discovers such a mapping nor authorizes a cached provider row.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import math

from .model import anchor, scope


def _number(value, label, limit=1e15):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            abs(value) > limit or not math.isfinite(value)):
        raise ValueError(label + ' must be a finite number within the canvas limits.')
    return float(value)


def _point(value):
    if isinstance(value, dict):
        values = value.get('x'), value.get('y')
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        values = value
    else:
        raise ValueError('A canvas position needs explicit x and y coordinates.')
    return tuple(_number(item, 'Position', 1e6) for item in values)


class Viewport:
    """Aspect-preserving transform of ``(min_x, min_y, width, height)`` bounds."""
    MIN_SCALE = 1e-6
    MAX_SCALE = 1e6
    MAX_OFFSET = 1e15

    def __init__(self, bounds, width, height):
        if not isinstance(bounds, (tuple, list)) or len(bounds) != 4:
            raise ValueError('Canvas bounds need min x, min y, width and height.')
        self.bounds = tuple(_number(value, 'Bounds', 1e9) for value in bounds)
        if self.bounds[2] <= 0 or self.bounds[3] <= 0:
            raise ValueError('Canvas bounds need positive width and height.')
        self.width, self.height = self._size(width, height)
        self.scale = 1.
        self.offset_x = self.offset_y = 0.
        self.fit()

    @staticmethod
    def _size(width, height):
        values = tuple(_number(v, 'Client size', 1e6) for v in (width, height))
        if any(value < 0 for value in values):
            raise ValueError('Client size cannot be negative.')
        return tuple(max(1., value) for value in values)

    def _offset(self, x, y):
        self.offset_x, self.offset_y = (max(-self.MAX_OFFSET, min(self.MAX_OFFSET, v)) for v in (x, y))

    def fit(self):
        x, y, width, height = self.bounds
        self.scale = max(self.MIN_SCALE, min(self.MAX_SCALE, self.width / width, self.height / height))
        self._offset((self.width - width*self.scale)/2 - x*self.scale,
                     (self.height - height*self.scale)/2 - y*self.scale)

    def project(self, x, y):
        """Document/SVG coordinates to client pixels; positive Y stays down."""
        return (_number(x, 'X', 2e9)*self.scale + self.offset_x,
                _number(y, 'Y', 2e9)*self.scale + self.offset_y)

    def unproject(self, x, y):
        """Client pixels to coordinates in the same frame as the supplied bounds."""
        return ((_number(x, 'Client X') - self.offset_x)/self.scale,
                (_number(y, 'Client Y') - self.offset_y)/self.scale)

    def pan(self, dx, dy):
        self._offset(self.offset_x + _number(dx, 'Pan X'), self.offset_y + _number(dy, 'Pan Y'))

    def zoom(self, factor, x, y):
        """Zoom around a client-pixel cursor, preserving its document location."""
        factor = _number(factor, 'Zoom factor')
        if factor <= 0:
            raise ValueError('Zoom factor must be positive.')
        point = self.unproject(x, y)
        self.scale = max(self.MIN_SCALE, min(self.MAX_SCALE, self.scale*factor))
        self._offset(float(x) - point[0]*self.scale, float(y) - point[1]*self.scale)

    def resize(self, width, height):
        point = self.unproject(self.width/2, self.height/2)
        self.width, self.height = self._size(width, height)
        self._offset(self.width/2 - point[0]*self.scale, self.height/2 - point[1]*self.scale)


@dataclass(frozen=True)
class Marker:
    comment_id: str
    anchor: dict
    x: float
    y: float
    severity: str = 'info'
    state: str = 'open'
    label: str = ''
    region: tuple[float, float, float, float] | None = None


def markers_from_rows(rows, expected_scope, status, positions=None):
    """Place only a current provider snapshot's exact-scope validated anchors.

    ``positions`` maps a UUID/object ID to one ``{x, y}`` or ``(x, y)`` point.
    A list of point candidates is accepted only when it contains exactly one;
    repeated identities remain ambiguous even if their coordinates coincide.
    Unplaced entries contain ``comment_id``, ``id``, ``label``, ``anchor`` and
    ``reason``. No coordinate or publication is inferred from a local cache.
    """
    expected = scope(expected_scope)
    if not isinstance(rows, (list, tuple)):
        raise ValueError('Provider rows must be a list.')
    positions = positions if isinstance(positions, dict) else {}
    identifiers = Counter(row.get('id') for row in rows if isinstance(row, dict) and isinstance(row.get('id'), str))
    markers, unplaced = [], []
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get('id')
        identifier = identifier if isinstance(identifier, str) else ''
        annotations = row.get('annotations')
        if isinstance(annotations, list):
            candidates = [(value.get('anchor'), value) for value in annotations if isinstance(value, dict)]
        else:
            candidates = [(value, {}) for value in row.get('anchors', [])] if isinstance(row.get('anchors'), list) else []
        if not candidates:
            candidates = [(None, {})]
        for raw, annotation in candidates:
            text = annotation.get('text', row.get('body', ''))
            label = ' '.join(text.split())[:160] if isinstance(text, str) else ''
            def unavailable(reason, target=None):
                unplaced.append(dict(comment_id=identifier, id=identifier, label=label,
                                     anchor=deepcopy(target), reason=reason))
            if status != 'synced':
                unavailable('Provider snapshot is not synced; cached or stale anchors are unverified.')
                continue
            if not identifier or identifiers[identifier] != 1:
                unavailable('Provider comment identity is missing or ambiguous.')
                continue
            try:
                target = anchor(raw)
            except (ValueError, TypeError, OverflowError):
                unavailable('This comment has no valid design anchor.')
                continue
            if scope(target) != expected:
                unavailable('Anchor belongs to another provider, repository, revision or design file.', target)
                continue
            area = target.get('area')
            region = tuple(float(area[key]) for key in ('x', 'y', 'width', 'height')) if area else None
            try:
                if 'position' in target:
                    x, y = _point(target['position'])
                elif area:
                    x, y = area['x'] + area['width']/2, area['y'] + area['height']/2
                else:
                    key = target.get('uuid') or target.get('objectId')
                    if not key or key not in positions:
                        raise ValueError('Anchor has no explicit position or uniquely resolved saved object.')
                    found = positions[key]
                    if isinstance(found, (list, tuple)) and not (len(found) == 2 and
                            all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in found)):
                        if len(found) != 1:
                            raise ValueError('Saved object identity has multiple position matches.')
                        found = found[0]
                    x, y = _point(found)
            except ValueError as exc:
                unavailable(str(exc), target)
                continue
            severity = annotation.get('severity', row.get('severity', 'info'))
            state = annotation.get('state', row.get('state', 'open'))
            markers.append(Marker(identifier, deepcopy(target), float(x), float(y),
                                  severity if isinstance(severity, str) else 'info',
                                  state if isinstance(state, str) else 'open', label, region))
    markers.sort(key=lambda item: (item.comment_id, item.x, item.y, item.label))
    return markers, unplaced


def hit_test(markers, viewport, x, y, *, radius=10, include_regions=True):
    """Return the closest pin within a pixel radius, otherwise a containing region."""
    x, y = _number(x, 'Hit X'), _number(y, 'Hit Y')
    radius = _number(radius, 'Hit radius', 1e6)
    if radius < 0:
        raise ValueError('Hit radius cannot be negative.')
    pins, regions = [], []
    for index, marker in enumerate(markers):
        px, py = viewport.project(marker.x, marker.y)
        distance = math.hypot(px-x, py-y)
        if distance <= radius:
            pins.append((distance, marker.comment_id, index, marker))
        if include_regions and marker.region:
            left, top, width, height = marker.region
            a, b = viewport.project(left, top), viewport.project(left+width, top+height)
            if a[0] <= x <= b[0] and a[1] <= y <= b[1]:
                regions.append((width*height, marker.comment_id, index, marker))
    candidates = pins or regions
    return min(candidates)[-1] if candidates else None


def draft_point(target_scope, x, y):
    """Build an unpublished point anchor in the document's verified mm frame."""
    x, y = _point((x, y))
    return anchor(dict(scope(target_scope), kind='position', position=dict(x=x, y=y)))


def draft_region(target_scope, x, y, width, height):
    """Build an unpublished rectangular-region anchor; no remote action occurs."""
    x, y, width, height = (_number(v, 'Region', 1e6) for v in (x, y, width, height))
    return anchor(dict(scope(target_scope), kind='region', area=dict(x=x, y=y, width=width, height=height)))
