"""Place measured screen labels without clipping or overlapping other labels.

All coordinates are screen pixels. Rectangles are (left, bottom, right, top);
the algorithm also works with a downward-pointing screen Y axis. It uses no GUI
or renderer objects, so callers can measure text once and draw the returned
rectangles (and leader lines to their anchors) in their chosen renderer.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LabelRequest:
    key: object
    anchor: tuple
    size: tuple
    priority: float = 0


def _finite(values):
    return all(isinstance(value, (int, float)) and not isinstance(value, bool)
               and math.isfinite(value) for value in values)


def _separate(rect, other, gap):
    return (rect[2] + gap <= other[0] or other[2] + gap <= rect[0]
            or rect[3] + gap <= other[1] or other[3] + gap <= rect[1])


def _candidates(anchor, size, gap):
    """Try nearby diagonal/cardinal positions, then bounded rings in both axes."""
    x, y = anchor
    w, h = size
    for ring in range(4):
        dx, dy = gap + ring * (w + gap), gap + ring * (h + gap)
        yield x + dx, y + dy
        yield x - w - dx, y + dy
        yield x + dx, y - h - dy
        yield x - w - dx, y - h - dy
        yield x - w / 2, y + dy
        yield x - w / 2, y - h - dy
        yield x + dx, y - h / 2
        yield x - w - dx, y - h / 2


def layout_labels(requests, width, height, *, scale=1, padding=3, margin=4,
                  reserved=()):
    """Return ``{key: rectangle}`` for labels that have a free bounded slot.

    Higher priority labels are placed first; equal priorities retain input
    order. ``size`` is the renderer's measured pixel size, already including
    its text/background padding. ``scale`` multiplies the gap and viewport
    margin, not measured text sizes. ``reserved`` holds other pixel rectangles
    such as a scale bar, legend or status badge. Labels with invalid sizes,
    offscreen anchors or no free candidate are omitted, never overlapped.
    Duplicate keys and invalid configuration raise ValueError.
    """
    if (not _finite((width, height, scale, padding, margin)) or scale <= 0
            or padding < 0 or margin < 0):
        raise ValueError('Viewport, scale, padding and margin must be finite; scale must be positive.')
    requests = list(requests)
    if len({request.key for request in requests}) != len(requests):
        raise ValueError('Label keys must be unique.')
    if not all(_finite((request.priority,)) for request in requests):
        raise ValueError('Label priorities must be finite numbers.')
    occupied = []
    for rect in reserved:
        if len(rect) != 4 or not _finite(rect) or rect[2] < rect[0] or rect[3] < rect[1]:
            raise ValueError('Reserved rectangles must contain four finite ordered coordinates.')
        occupied.append(tuple(rect))
    gap, edge = padding * scale, margin * scale
    if width <= 2 * edge or height <= 2 * edge:
        return {}
    placed = {}
    for _, request in sorted(enumerate(requests), key=lambda item: (-item[1].priority, item[0])):
        if (len(request.anchor) != 2 or len(request.size) != 2
                or not _finite((*request.anchor, *request.size))):
            continue
        x, y = request.anchor
        w, h = request.size
        if (not 0 <= x <= width or not 0 <= y <= height or w <= 0 or h <= 0
                or w > width - 2 * edge or h > height - 2 * edge):
            continue
        seen = set()
        for left, bottom in _candidates(request.anchor, request.size, gap):
            # Clamping offers the closest legal edge position near viewport
            # corners, but never bypasses collision tests.
            left = max(edge, min(left, width - edge - w))
            bottom = max(edge, min(bottom, height - edge - h))
            rect = (left, bottom, left + w, bottom + h)
            if rect in seen:
                continue
            seen.add(rect)
            if all(_separate(rect, other, gap) for other in occupied):
                placed[request.key] = rect
                occupied.append(rect)
                break
    return placed
