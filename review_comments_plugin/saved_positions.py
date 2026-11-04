"""Conservative saved KiCad UUID locations for read-only review markers.

Coordinates are document millimetres.  This resolves only geometries whose
location is explicit in the selected saved source; it never follows sheets or
uses cached or live editor state.
"""
from __future__ import annotations

from collections import Counter
import math

from wayricad_runtime.schematic_sexpr import Node, parse


MAX_SOURCE_CHARS = 64 * 1024 * 1024
MAX_OBJECTS = 200_000
MAX_COORD_MM = 1_000_000


def _number(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value) or abs(value) > MAX_COORD_MM:
        raise ValueError('Unsupported saved coordinate.')
    return value


def _xy(node: Node | None) -> tuple[float, float] | None:
    if node is None or len(node.atoms) < 3:
        return None
    try:
        return _number(node.val(1)), _number(node.val(2))
    except (ValueError, OverflowError):
        return None


def _angle(node: Node | None) -> float | None:
    if node is None:
        return None
    if len(node.atoms) < 4:
        return 0.0
    try:
        return _number(node.val(3))
    except (ValueError, OverflowError):
        return None


def _uuid(node: Node) -> str | None:
    values = node.nodes('uuid')
    return values[0].val() if len(values) == 1 and values[0].val() else None


def _midpoint(node: Node) -> tuple[float, float] | None:
    start, end = _xy(node.one('start')), _xy(node.one('end'))
    if start is None or end is None:
        return None
    return ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)


def _pcb_pad(pad: Node, footprint: Node) -> tuple[float, float] | None:
    if footprint.one('transform') is not None:
        return None  # New affine placement needs its own verified transform.
    origin, relative = _xy(footprint.one('at')), _xy(pad.one('at'))
    angle = _angle(footprint.one('at'))
    if origin is None or relative is None or angle is None:
        return None
    # Saved pad coordinates are footprint-relative. KiCad's
    # SetFPRelativePosition rotates them by the parent orientation on both
    # sides; a second mirror here would double-flip back-side pads.
    layer = footprint.one('layer')
    if layer is None or layer.val() not in ('F.Cu', 'B.Cu'):
        return None
    x, y = relative
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    result = (origin[0] + x*cosine + y*sine,
              origin[1] - x*sine + y*cosine)
    return result if all(math.isfinite(v) and abs(v) <= MAX_COORD_MM for v in result) else None


def _pcb_position(node: Node) -> tuple[float, float] | None:
    if node.tag in ('footprint', 'via', 'gr_text', 'gr_text_box', 'gr_arc'):
        # Arcs have no single unambiguous point; do not map them.
        return None if node.tag == 'gr_arc' else _xy(node.one('at'))
    if node.tag in ('segment', 'gr_line', 'gr_rect'):
        return _midpoint(node)
    if node.tag == 'gr_circle':
        return _xy(node.one('center'))
    return None


def saved_positions(source: str) -> dict[str, dict[str, float]]:
    """Return unique supported UUIDs in one saved PCB or schematic source.

    Repeated UUIDs and unsupported geometry are omitted, including collisions
    at the same coordinate. Explicit anchor coordinates are handled separately
    by the canvas model and are unaffected by this mapping.
    """
    if not isinstance(source, str) or len(source) > MAX_SOURCE_CHARS:
        raise ValueError('Saved review source must be bounded text (64 MiB maximum).')
    tree = parse(source)
    if tree.tag not in ('kicad_pcb', 'kicad_sch'):
        raise ValueError('Expected a saved KiCad PCB or schematic source.')
    if len(tree.children) > MAX_OBJECTS:
        raise ValueError('Saved review source exceeds the object limit.')
    counts: Counter[str] = Counter()
    pending = [tree]
    visited = 0
    while pending:
        node = pending.pop()
        visited += 1
        if visited > MAX_OBJECTS:
            raise ValueError('Saved review source exceeds the object limit.')
        if node.tag == 'uuid' and node.val():
            counts[node.val()] += 1
        pending.extend(node.children)

    points: dict[str, tuple[float, float]] = {}
    for node in tree.children:
        key = _uuid(node)
        if tree.tag == 'kicad_pcb':
            point = _pcb_position(node)
            if node.tag == 'footprint':
                point = (_xy(node.one('at')) if node.one('transform') is None and
                         node.one('layer') and node.one('layer').val() in ('F.Cu', 'B.Cu') else None)
                for pad in node.nodes('pad'):
                    pad_key = _uuid(pad)
                    pad_point = _pcb_pad(pad, node)
                    if pad_key and pad_point and counts[pad_key] == 1:
                        points[pad_key] = pad_point
        elif node.tag in ('symbol', 'sheet', 'label', 'global_label', 'hierarchical_label',
                          'junction', 'no_connect', 'text', 'text_box'):
            point = _xy(node.one('at'))
        elif node.tag == 'wire':
            point = None
            pts = node.one('pts')
            xy_nodes = pts.nodes('xy') if pts else []
            if len(xy_nodes) == 2:
                a, b = _xy(xy_nodes[0]), _xy(xy_nodes[1])
                if a is not None and b is not None:
                    point = ((a[0]+b[0])/2, (a[1]+b[1])/2)
        else:
            point = None
        if key and point and counts[key] == 1:
            points[key] = point
    return {key: {'x': point[0], 'y': point[1]} for key, point in points.items()}
