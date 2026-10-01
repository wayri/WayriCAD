"""Bounded, continuous heater centerlines, in millimetres.

Circular paths use a disk inscribed in the requested envelope. Annular leads
reserve space at the bottom. Maze paths cover a grid of complete square cells;
their circular outline is consequently stepped rather than a smooth foil edge.
No geometry is written to a board here.
"""
from __future__ import annotations

import math
import random

PATTERNS = ("Circular serpentine", "Circular foil", "Split circular foil", "Annular arc meander",
            "Seeded maze", "Circular maze")
MAX_POINTS = 60000
MAX_MAZE_CELLS = 3000


def generate_path(pattern, width_mm, height_mm, trace_width_mm, spacing_mm,
                  inner_diameter_mm=20.0, slot_angle_deg=30.0,
                  terminal_length_mm=10.0, random_seed=1):
    """Return one ordered path; no branches, layers, or disconnected islands.

    Circular foil uses the same disk-clipped series raster as circular
    serpentine. A large trace width and small spacing create the wide foil
    appearance. Maze seeds randomize a spanning-tree coverage path, not a
    branching electrical maze. Complexity limits are explicit errors.
    """
    values = (width_mm, height_mm, trace_width_mm, spacing_mm,
              inner_diameter_mm, slot_angle_deg, terminal_length_mm)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Heater pattern dimensions must be finite.")
    if min(width_mm, height_mm, trace_width_mm, spacing_mm) <= 0:
        raise ValueError("Width, height, trace width and isolating cut spacing must be positive.")
    if pattern not in PATTERNS:
        raise ValueError("Choose a supported heater fill pattern.")
    pitch = trace_width_mm + spacing_mm
    if min(width_mm, height_mm) < 3 * pitch:
        raise ValueError("Heater area is too small for this trace width and spacing.")
    if pattern == "Annular arc meander":
        result = _annular(width_mm, height_mm, trace_width_mm, pitch,
                          inner_diameter_mm, slot_angle_deg, terminal_length_mm)
    elif pattern == "Split circular foil":
        result = _split_circular_foil(width_mm, height_mm, trace_width_mm,
                                      pitch, terminal_length_mm)
    elif pattern in ("Seeded maze", "Circular maze"):
        result = _maze(width_mm, height_mm, trace_width_mm, pitch,
                       random_seed, pattern == "Circular maze")
    else:
        result = _circular_raster(width_mm, height_mm, trace_width_mm, pitch)
    if len(result) > MAX_POINTS:
        raise ValueError("Pattern is too detailed; increase trace width or spacing.")
    return result


def circular_envelope(width_mm, height_mm, terminal_length_mm=0.0):
    """Return (centre_x, centre_y, radius), with bottom lead space reserved."""
    diameter = min(width_mm, height_mm - terminal_length_mm)
    return width_mm / 2, terminal_length_mm + diameter / 2, diameter / 2


def _circular_raster(width, height, trace, pitch):
    cx, cy, radius = circular_envelope(width, height)
    radius -= trace / 2
    count = int(2 * radius / pitch) + 1
    if count * 2 > MAX_POINTS:
        raise ValueError("Pattern is too detailed; increase trace width or spacing.")
    # Centred rows avoid zero-length pole chords and leave equal edge margins.
    count = max(2, count - 1)
    result = []
    for row in range(count):
        y = (row - (count - 1) / 2) * pitch
        dx = math.sqrt(max(0.0, radius * radius - y * y))
        ends = ((cx - dx, cy + y), (cx + dx, cy + y))
        result.extend(ends if row % 2 == 0 else reversed(ends))
    return result


def _annular(width, height, trace, pitch, inner_diameter, slot_angle, lead):
    if inner_diameter <= 0 or lead < 0 or not 5 <= slot_angle <= 150:
        raise ValueError("Annular inner diameter must be positive, terminal length non-negative, and slot angle 5–150 degrees.")
    cx, cy, outer = circular_envelope(width, height, lead)
    if outer <= 0:
        raise ValueError("Terminal length leaves no room for the annular heater.")
    # Chord sag is accounted for at the inner edge so a polyline never enters
    # the specified opening after its full trace width is applied.
    tolerance = min(0.005, pitch / 100)
    rmin = inner_diameter / 2 + trace / 2 + tolerance
    rmax = outer - trace / 2
    lane_pitch = pitch + 2 * tolerance
    count = int((rmax - rmin) / lane_pitch) + 1
    if count % 2 == 0:
        count -= 1
    if count < 3:
        raise ValueError("Annular band needs room for at least three arc lanes.")
    half_slot = math.radians(slot_angle) / 2
    lowest_radius = rmax - (count - 1) * lane_pitch
    if lowest_radius * math.sin(half_slot) < 1.5 * pitch:
        raise ValueError("The inner slot is too narrow for the selected width and spacing.")
    start = -math.pi / 2 + half_slot
    end = 3 * math.pi / 2 - half_slot
    steps = max(12, math.ceil((end - start) / (2 * math.acos(max(-1.0, 1 - tolerance / rmax)))))
    if count * (steps + 1) + 2 > MAX_POINTS:
        raise ValueError("Annular path is too detailed; increase width or spacing.")
    result = []
    for lane in range(count):
        radius = rmax - lane * lane_pitch
        angles = [start + (end - start) * index / steps for index in range(steps + 1)]
        if lane % 2:
            angles.reverse()
        result.extend((cx + radius * math.cos(angle), cy + radius * math.sin(angle))
                      for angle in angles)
    # The inner lead first turns further into the slot along the innermost
    # radius. A vertical lead at the arc endpoint would pass close to the
    # preceding radial connectors, despite having no centreline crossing.
    # Reserve a corridor nearer the slot centre before descending to the tab.
    terminal_angle = 3 * math.pi / 2 - math.asin(pitch / (2 * lowest_radius))
    exit_steps = max(1, math.ceil((terminal_angle - end) / ((end-start)/steps)))
    result.extend((cx + lowest_radius * math.cos(end + (terminal_angle-end)*index/exit_steps),
                   cy + lowest_radius * math.sin(end + (terminal_angle-end)*index/exit_steps))
                  for index in range(1, exit_steps+1))
    # Coordinates are y-up; odd lane count puts ends on opposite slot sides.
    terminal_y = trace / 2
    result.insert(0, (result[0][0], terminal_y))
    result.append((result[-1][0], terminal_y))
    return result


def split_circular_envelope(width_mm, height_mm, terminal_length_mm):
    """Return disk centre/radius with terminal space reserved at the left."""
    diameter = min(width_mm-terminal_length_mm, height_mm)
    return terminal_length_mm + diameter/2, height_mm/2, diameter/2


def _split_circular_foil(width, height, trace, pitch, lead):
    if lead < 0:
        raise ValueError("Terminal length must be non-negative.")
    cx,cy,outer = split_circular_envelope(width,height,lead)
    radius = outer-trace/2
    if radius <= 2*pitch:
        raise ValueError("Terminal length leaves too little room for a split circular heater.")
    # Keep edge-column strokes substantial, avoiding short stubs beside the
    # two left leads. Both banks share identical columns and an even count.
    usable_half_width = math.sqrt(radius*radius-(1.5*pitch)**2)
    count = int(2*usable_half_width/pitch)+1
    count -= count % 2
    if count < 2:
        raise ValueError("Split circular heater needs at least two columns.")
    if 4*count+2 > MAX_POINTS:
        raise ValueError("Pattern is too detailed; increase trace width or spacing.")
    columns = [cx+(index-(count-1)/2)*pitch for index in range(count)]
    result = []
    for index,x in enumerate(columns):
        extent = math.sqrt(max(0.,radius*radius-(x-cx)**2))
        stroke = ((x,cy-pitch/2),(x,cy-extent))
        result.extend(stroke if index%2 == 0 else reversed(stroke))
    for index,x in enumerate(reversed(columns)):
        extent = math.sqrt(max(0.,radius*radius-(x-cx)**2))
        stroke = ((x,cy+pitch/2),(x,cy+extent))
        result.extend(stroke if index%2 == 0 else reversed(stroke))
    result.insert(0,(trace/2,cy-pitch/2))
    result.append((trace/2,cy+pitch/2))
    return result


def _maze(width, height, trace, pitch, seed, circular):
    # A four-vertex cycle per coarse cell; merging cycles along a spanning
    # tree produces one Hamiltonian cycle without branches or crossings.
    nx = int((width - trace - pitch) / (2 * pitch)) + 1
    ny = int((height - trace - pitch) / (2 * pitch)) + 1
    if nx * ny > MAX_MAZE_CELLS:
        raise ValueError("Maze is too detailed; increase trace width or spacing.")
    if min(nx, ny) < 1:
        raise ValueError("Heater area cannot contain a maze cell.")
    x0 = (width - (2 * nx - 1) * pitch) / 2
    y0 = (height - (2 * ny - 1) * pitch) / 2
    radius = min(width, height) / 2 - trace / 2
    cells = {(x, y) for x in range(nx) for y in range(ny)
             if not circular or all((x0 + (2*x + dx)*pitch - width/2)**2
                                    + (y0 + (2*y + dy)*pitch - height/2)**2
                                    <= radius**2 + 1e-10
                                    for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1)))}
    if not cells:
        raise ValueError("Circular heater cannot contain a complete maze cell.")
    rng = random.Random(seed)
    root = min(cells)
    visited, stack, tree = {root}, [root], []
    while stack:
        cell = stack[-1]
        neighbors = [(cell[0]+dx, cell[1]+dy) for dx, dy in ((1,0),(-1,0),(0,1),(0,-1))]
        neighbors = [neighbor for neighbor in neighbors if neighbor in cells and neighbor not in visited]
        if not neighbors:
            stack.pop()
            continue
        neighbor = rng.choice(neighbors)
        visited.add(neighbor)
        tree.append((cell, neighbor))
        stack.append(neighbor)
    if visited != cells:
        raise ValueError("Circular maze cell mask is disconnected; change dimensions or pitch.")
    edges = {}
    def connect(a, b):
        edges.setdefault(a, set()).add(b)
        edges.setdefault(b, set()).add(a)
    def disconnect(a, b):
        edges[a].remove(b)
        edges[b].remove(a)
    for x, y in sorted(cells):
        vertices = [(2*x,2*y),(2*x+1,2*y),(2*x+1,2*y+1),(2*x,2*y+1)]
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            connect(a, b)
    for a, b in tree:
        if a[0] != b[0]:
            left, right = sorted((a, b))
            u = (2*left[0]+1, 2*left[1]); v = (u[0], u[1]+1)
            p = (u[0]+1, u[1]); q = (p[0], p[1]+1)
        else:
            top, bottom = sorted((a, b), key=lambda cell: cell[1])
            u = (2*top[0], 2*top[1]+1); v = (u[0]+1, u[1])
            p = (u[0], u[1]+1); q = (p[0]+1, p[1])
        disconnect(u, v); disconnect(p, q)
        connect(u, p); connect(v, q)
    bottom = min(cells, key=lambda cell: (cell[1], abs(cell[0] - nx/2)))
    first = (2*bottom[0], 2*bottom[1])
    last = (first[0]+1, first[1])
    disconnect(first, last)
    ordered, previous, current = [], None, first
    while True:
        ordered.append(current)
        following = edges[current] - ({previous} if previous is not None else set())
        if not following:
            break
        previous, current = current, next(iter(following))
        if len(ordered) > len(edges):
            raise ValueError("Maze topology failed to form a single series path.")
    if len(ordered) != len(edges) or current != last:
        raise ValueError("Maze topology failed to cover all cells.")
    return [(x0 + x*pitch, y0 + y*pitch) for x, y in ordered]
