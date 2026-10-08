"""Circular and rotated obround drilled-wall geometry, in millimetres."""
from __future__ import annotations
import math


def drill_dimensions(item):
    """Return finished drill X/Y dimensions; old circular records remain valid."""
    values = item.get("drill_size_mm", [item.get("drill_mm", 0)] * 2)
    x, y = map(float, values)
    if not all(math.isfinite(v) and v > 0 for v in (x, y)):
        raise ValueError("Drill dimensions must be finite and positive.")
    return x, y


def drill_wall_distance(point, item):
    """Signed distance to a rotated capsule wall: negative inside the void."""
    x, y = drill_dimensions(item)
    # KiCad positive pad rotation is negative in board XY (Y points down).
    angle = -math.radians(float(item.get("drill_angle_deg", 0)))
    dx, dy = point[0] - item["x_mm"], point[1] - item["y_mm"]
    local_x = dx * math.cos(angle) + dy * math.sin(angle)
    local_y = -dx * math.sin(angle) + dy * math.cos(angle)
    if x < y:
        local_x, local_y = local_y, local_x
    half_run = abs(x - y) / 2
    return math.hypot(max(abs(local_x) - half_run, 0), local_y) - min(x, y) / 2


def barrel_area_mm2(item, plating_mm):
    """Axial metal area for a uniformly outward-plated circular/capsule wall.

    For finished drill perimeter P and plating t: A = P*t + pi*t**2.
    A capsule of major axis a and minor axis b has P = 2*(a-b)+pi*b.
    This preserves straight slot walls and semicircular end caps exactly.
    """
    x, y = drill_dimensions(item)
    t = float(plating_mm)
    if not math.isfinite(t) or t <= 0 or 2*t >= min(x, y):
        raise ValueError("Barrel plating thickness is implausible for its drill.")
    return (2 * abs(x-y) + math.pi * min(x,y)) * t + math.pi * t*t
