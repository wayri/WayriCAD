"""Layer-resolved, steady-state finite-volume board thermal screen.

All dimensions in the public geometry are millimetres. Thermal calculations
use metres, watts, and kelvins. This is a bounded 2.5D screen, not CFD or a
package/fixture contact model. Only explicitly selected mounts are sinks.
"""
from __future__ import annotations

import math
from bisect import bisect_right
import time
from collections.abc import Mapping

from .thermal_board_view import _inside
from .thermal_drills import drill_dimensions, drill_wall_distance, barrel_area_mm2


SIGMA = 5.670374419e-8


def _num(value, name, *, low=None, high=None):
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number.") from exc
    if not math.isfinite(n) or (low is not None and n < low) or (high is not None and n > high):
        raise ValueError(f"{name} is outside its allowed range.")
    return n



def _component_storage(settings, result):
    """Validate explicit lumped component models without inventing properties."""
    raw = settings.get("component_storage", {})
    if not isinstance(raw, Mapping):
        raise ValueError("component_storage must map selected references to explicit thermal properties.")
    references = [str(part["reference"]) for part in result.get("components", [])]
    if raw and len(set(references)) != len(references):
        raise ValueError("Component storage requires unique selected source references.")
    if any(not isinstance(ref, str) or ref not in references for ref in raw):
        raise ValueError("component_storage references must be selected heat sources.")
    models = {}
    required = {"capacity_j_k", "resistance_k_per_w", "temperature_kind"}
    for ref in sorted(raw):
        spec = raw[ref]
        surface_keys = {"exposed_area_mm2", "h_w_m2k", "emissivity"}
        if not isinstance(spec, Mapping) or not required <= set(spec) or set(spec)-required-{"initial_c"}-surface_keys:
            raise ValueError(ref + ": component storage requires capacity_j_k, resistance_k_per_w, temperature_kind, optional initial_c and optional explicit surface properties only.")
        if set(spec) & surface_keys and not surface_keys <= set(spec):
            raise ValueError(ref + ": exposed_area_mm2, h_w_m2k and emissivity must be supplied together.")
        if spec["temperature_kind"] not in ("body", "junction"):
            raise ValueError(ref + ": temperature_kind must be body or junction.")
        model = {"temperature_kind": spec["temperature_kind"]}
        for key in ("capacity_j_k", "resistance_k_per_w", "initial_c", "exposed_area_mm2", "h_w_m2k", "emissivity"):
            if key not in spec:
                continue
            try:
                if isinstance(spec[key], bool):
                    raise ValueError()
                value = float(spec[key])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(ref + ": " + key + " must be a finite number.") from exc
            if not math.isfinite(value) or (key in ("capacity_j_k", "resistance_k_per_w", "exposed_area_mm2") and value <= 0):
                raise ValueError(ref + ": " + key + " must be finite and positive.")
            if key == "initial_c" and not -273.15 < value <= 10000:
                raise ValueError(ref + ": initial_c must exceed absolute zero and not exceed 10000 C.")
            if key in ("h_w_m2k", "emissivity") and value < 0 or key == "emissivity" and value > 1:
                raise ValueError(ref + ": invalid surface convection or emissivity.")
            if key == "h_w_m2k" and result.get("environment", "air") == "vacuum" and value != 0:
                raise ValueError(ref + ": vacuum requires zero component convection.")
            model[key] = value
        models[ref] = model
    return models


def _board_contains(point, outlines):
    return any(_inside(point, shape["outer_mm"]) and
               not any(_inside(point, hole) for hole in shape.get("holes_mm", []))
               for shape in outlines)


def _ring_bounds(ring):
    return (min(p[0] for p in ring), min(p[1] for p in ring),
            max(p[0] for p in ring), max(p[1] for p in ring))


def _polygon_ring_bounds(polygon):
    # JSON-safe cached bounds; no source PCB mutation and no precision change.
    bounds = polygon.get("_thermal_ring_bounds")
    if bounds is None:
        bounds = [_ring_bounds(ring) for ring in [polygon["outer"], *polygon.get("holes", [])]]
        polygon["_thermal_ring_bounds"] = bounds
    return bounds


def _polygon_contains(point, polygon):
    bounds = _polygon_ring_bounds(polygon)
    x, y = point
    def candidate(bound):
        return bound[0]-1e-9 <= x <= bound[2]+1e-9 and bound[1]-1e-9 <= y <= bound[3]+1e-9
    return (candidate(bounds[0]) and _inside(point, polygon["outer"]) and
            not any(candidate(bound) and _inside(point, hole)
                    for hole, bound in zip(polygon.get("holes", []), bounds[1:])))


def _segments_cross(a, b, c, d):
    """True when two closed planar segments touch or cross."""
    def orient(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    ab_c, ab_d = orient(a, b, c), orient(a, b, d)
    cd_a, cd_b = orient(c, d, a), orient(c, d, b)
    if ((ab_c > 0 and ab_d < 0 or ab_c < 0 and ab_d > 0) and
            (cd_a > 0 and cd_b < 0 or cd_a < 0 and cd_b > 0)):
        return True
    for value, p, q, r in ((ab_c, a, b, c), (ab_d, a, b, d),
                           (cd_a, c, d, a), (cd_b, c, d, b)):
        if abs(value) <= 1e-12 and (min(p[0], q[0])-1e-12 <= r[0] <= max(p[0], q[0])+1e-12 and
                                     min(p[1], q[1])-1e-12 <= r[1] <= max(p[1], q[1])+1e-12):
            return True
    return False


def _polygon_intersects_cell(polygon, x0, y0, x1, y1):
    """Conservative candidate test; exact copper transport is checked at faces."""
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    if any(_polygon_contains(point, polygon) for point in corners):
        return True
    ring = polygon["outer"]
    if any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in ring):
        return True
    for a, b in zip(ring, ring[1:]+ring[:1]):
        if any(_segments_cross(a, b, c, d)
               for c, d in zip(corners, corners[1:]+corners[:1])):
            return True
    return False


def _clip_ring_to_cell(ring, x0, y0, x1, y1):
    """Clip a simple polygon ring to an axis-aligned thermal cell."""
    vertices = [tuple(point) for point in ring]
    for axis, limit, keep_above in ((0, x0, True), (0, x1, False),
                                    (1, y0, True), (1, y1, False)):
        if not vertices:
            break
        clipped = []
        previous = vertices[-1]
        previous_inside = previous[axis] >= limit if keep_above else previous[axis] <= limit
        for current in vertices:
            current_inside = current[axis] >= limit if keep_above else current[axis] <= limit
            if current_inside != previous_inside:
                fraction = (limit-previous[axis])/(current[axis]-previous[axis])
                clipped.append((previous[0]+fraction*(current[0]-previous[0]),
                                previous[1]+fraction*(current[1]-previous[1])))
            if current_inside:
                clipped.append(current)
            previous, previous_inside = current, current_inside
        vertices = clipped
    return vertices


def _ring_area(ring):
    return abs(math.fsum(a[0]*b[1]-b[0]*a[1]
                         for a, b in zip(ring, ring[1:]+ring[:1])))/2 if len(ring) >= 3 else 0.0


def _polygon_cell_fraction(polygon, x0, y0, x1, y1):
    """Area fraction of filled copper, subtracting clipped polygon holes."""
    outer = _ring_area(_clip_ring_to_cell(polygon["outer"], x0, y0, x1, y1))
    holes = math.fsum(_ring_area(_clip_ring_to_cell(hole, x0, y0, x1, y1))
                      for hole, bound in zip(polygon.get("holes", []), _polygon_ring_bounds(polygon)[1:])
                      if bound[2] >= x0 and bound[0] <= x1 and bound[3] >= y0 and bound[1] <= y1)
    return max(0.0, min(1.0, (outer-holes)/((x1-x0)*(y1-y0))))


def _drill_at(point, layer_id, geometry):
    for item in [*geometry.get("barrels", []), *geometry.get("mounting_holes", [])]:
        if item.get("span_layers") and layer_id not in item["span_layers"]:
            continue
        if not item.get("drill_mm") and not item.get("drill_size_mm"):
            continue
        if drill_wall_distance(point, item) < 0:
            return item.get("id")
    return None


def _face_copper_fraction(start, end, polygon, normal, offset):
    """Fraction of a cell face crossed by continuous copper on both sides."""
    dx, dy = end[0]-start[0], end[1]-start[1]
    length_sq = dx*dx+dy*dy
    cuts = [0.0, 1.0]
    margin = max(1e-9, 1e-12*max(1.0,length_sq)/math.sqrt(length_sq))
    face_bounds = (min(start[0],end[0])-margin, min(start[1],end[1])-margin,
                   max(start[0],end[0])+margin, max(start[1],end[1])+margin)
    for ring, bound in zip([polygon["outer"], *polygon.get("holes", [])], _polygon_ring_bounds(polygon)):
        if (bound[2] < face_bounds[0] or bound[0] > face_bounds[2] or
                bound[3] < face_bounds[1] or bound[1] > face_bounds[3]):
            continue
        for a, b in zip(ring, ring[1:]+ring[:1]):
            if (max(a[0],b[0]) < face_bounds[0] or min(a[0],b[0]) > face_bounds[2] or
                    max(a[1],b[1]) < face_bounds[1] or min(a[1],b[1]) > face_bounds[3]):
                continue
            ex, ey = b[0]-a[0], b[1]-a[1]
            denominator = dx*ey-dy*ex
            ax, ay = a[0]-start[0], a[1]-start[1]
            if abs(denominator) > 1e-15:
                t = (ax*ey-ay*ex)/denominator
                u = (ax*dy-ay*dx)/denominator
                if -1e-12 <= t <= 1+1e-12 and -1e-12 <= u <= 1+1e-12:
                    cuts.append(min(1.0, max(0.0, t)))
            elif abs(ax*dy-ay*dx) <= 1e-12*max(1.0, length_sq):
                cuts.extend(min(1.0, max(0.0, (p[0]-start[0])*dx/length_sq+
                                                  (p[1]-start[1])*dy/length_sq))
                            for p in (a, b))
    cuts = sorted(set(round(t, 14) for t in cuts))
    fraction = 0.0
    for low, high in zip(cuts, cuts[1:]):
        if high-low <= 1e-14:
            continue
        t = (low+high)/2
        x, y = start[0]+t*dx, start[1]+t*dy
        if (_polygon_contains((x-offset*normal[0], y-offset*normal[1]), polygon) and
                _polygon_contains((x+offset*normal[0], y+offset*normal[1]), polygon)):
            fraction += high-low
    return min(1.0, max(0.0, fraction))


def _source_weights(component, cells, xs, ys, x_edges, y_edges,
                    contact_polygons=None, drilled_holes=None):
    """Area-weighted saved pad copper or explicitly labelled bbox fallback."""
    bounds = component.get("bbox_mm")
    if bounds is None:
        pos = component["position_mm"]
        nearest = min(range(len(cells)), key=lambda n:
                      (xs[cells[n][0]]-pos[0])**2 + (ys[cells[n][1]]-pos[1])**2)
        return [(nearest, 1.0)], "point_fallback", None, 0.0, 0.0
    if len(bounds) != 4:
        raise ValueError(f"{component['reference']}: footprint bbox_mm needs four coordinates.")
    x0, y0, x1, y1 = [_num(v, "Footprint bound") for v in bounds]
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"{component['reference']}: invalid footprint bounding box.")
    hits = []
    effective_cells = 0.0
    for index, (i, j) in enumerate(cells):
        left, bottom = max(x0, x_edges[i]), max(y0, y_edges[j])
        right, top = min(x1, x_edges[i+1]), min(y1, y_edges[j+1])
        area = max(0, right-left)*max(0, top-bottom)
        if area and contact_polygons is not None:
            area = min(area, math.fsum(_polygon_cell_fraction(
                polygon, left, bottom, right, top)*area for polygon in contact_polygons))
        if area > 0:
            hits.append((index, area))
            effective_cells += area/((x_edges[i+1]-x_edges[i])*(y_edges[j+1]-y_edges[j]))
    total = math.fsum(v for _, v in hits)
    if total <= 0:
        raise ValueError(f"{component['reference']}: footprint does not overlap the board grid.")
    moved = 0.0
    unresolved_annulus = False
    if contact_polygons is not None and drilled_holes:
        def drilled_center(ci):
            i, j = cells[ci]
            return any(drill_wall_distance((xs[i], ys[j]), hole) < 0 for hole in drilled_holes)

        retained = [(ci, area) for ci, area in hits if not drilled_center(ci)]
        targets = [(ci, area) for ci, area in retained if
                   any(_polygon_contains((xs[cells[ci][0]], ys[cells[ci][1]]), polygon)
                       for polygon in contact_polygons)] or retained
        if any(drilled_center(ci) for ci, _ in hits):
            if not targets:
                # A coarse grid can place every overlapped cell center in the
                # drill despite a finite copper annulus. Preserve the heat in
                # nearby non-drilled nodes but mark the contact unresolved.
                cx, cy = (x0+x1)/2, (y0+y1)/2
                targets = [(ci, 0.0) for ci in sorted(
                    (ci for ci in range(len(cells)) if not drilled_center(ci)),
                    key=lambda ci: (xs[cells[ci][0]]-cx)**2+
                                   (ys[cells[ci][1]]-cy)**2)[:4]]
                if not targets:
                    raise ValueError(f"{component['reference']}: no board cell center outside the drill.")
                unresolved_annulus = True
            # Keep every non-drilled overlap, including boundary cells whose
            # centers fall outside the polygon. Only drill-center heat moves.
            revised = {ci: area for ci, area in retained}
            for ci, area in hits:
                if not drilled_center(ci):
                    continue
                moved += area
                ix, iy = cells[ci]
                nearest = sorted(targets, key=lambda item:
                                 (xs[cells[item[0]][0]]-xs[ix])**2+
                                 (ys[cells[item[0]][1]]-ys[iy])**2)[:4]
                raw = [1/max(1e-9, math.hypot(xs[cells[target][0]]-xs[ix],
                                              ys[cells[target][1]]-ys[iy]))
                       for target, _ in nearest]
                factor = math.fsum(raw)
                for (target, _), weight in zip(nearest, raw):
                    revised[target] = revised.get(target, 0.0)+area*weight/factor
            hits = sorted(revised.items())
            if not math.isclose(math.fsum(area for _, area in hits), total,
                                rel_tol=1e-12, abs_tol=1e-12):
                raise ArithmeticError("Source annulus redistribution lost contact area.")
    return ([(index, area/total) for index, area in hits],
            ("saved_pad_copper_polygon_unresolved_annulus_proxy" if unresolved_annulus else
             "saved_pad_copper_polygon_annulus_stencil" if moved else
             "saved_pad_copper_polygon") if contact_polygons is not None else
            "footprint_bbox_proxy", total, effective_cells, moved)


def solve_multilayer_thermal(geometry, view, result, settings, progress=None):
    """Solve layer temperatures, explicit mount fluxes and a heat balance.

    ``geometry`` is from ``collect_thermal_geometry``; ``view`` and ``result``
    are the corresponding QuickTherm board view and mapped-field result.
    Components whose heat path is a separate heatsink are not silently included.
    """
    try:
        import numpy as np
        from scipy.sparse import coo_matrix, diags
        from scipy.sparse.csgraph import connected_components
        from scipy.sparse.linalg import spsolve
    except ImportError as exc:
        raise RuntimeError("Layer-resolved QuickTherm requires NumPy and SciPy.") from exc
    if not isinstance(settings, Mapping):
        raise ValueError("Thermal settings must be a mapping.")
    if geometry.get("outline_status") != "valid" or not geometry.get("outline"):
        raise ValueError("A verified closed Edge.Cuts outline is required.")
    # Bounds are run-local accelerators. A caller may revise public polygon
    # rings between solves; never reuse prior bounds across analysis runs.
    for record in [*geometry.get("layers", []), *geometry.get("source_contacts", [])]:
        for polygon in record.get("polygons_mm", []):
            polygon.pop("_thermal_ring_bounds", None)
    for barrel in geometry.get("barrels", []):
        for polygons in barrel.get("land_polygons_mm", {}).values():
            for polygon in polygons:
                polygon.pop("_thermal_ring_bounds", None)
    layers = list(geometry.get("layers", []))
    if len(layers) < 2 or len({row["id"] for row in layers}) != len(layers):
        raise ValueError("At least two distinct stackup copper layers are required.")
    if any(layers[i+1]["z_mm"] <= layers[i]["z_mm"] for i in range(len(layers)-1)):
        raise ValueError("Copper stackup Z positions must increase from top to bottom.")
    dielectric_k = _num(settings.get("dielectric_k_w_mk"), "Dielectric conductivity (W/m/K)", low=1e-9)
    copper_k = _num(settings.get("copper_k_w_mk", 385), "Copper conductivity (W/m/K)", low=1e-9)
    plating = _num(settings.get("via_plating_mm"), "Via plating thickness (mm)", low=1e-9)
    ambient = _num(settings.get("ambient_c", result.get("ambient_c", 20)), "Ambient (°C)", low=-273.15)
    emissivity = _num(settings.get("board_emissivity", 0.85), "Emissivity", low=0, high=1)
    environment = result.get("environment", "air")
    from .thermal_environments import boundary_settings
    settings, environment_notes = boundary_settings(environment, settings)
    ambient = _num(settings.get("ambient_c", ambient), "Boundary temperature (°C)", low=-273.15)
    airflow = _num(settings.get("board_airflow_m_s", 0), "Airflow (m/s)", low=0)
    h = _num(settings.get("board_h_w_m2k", 5+4*airflow if environment == "air" else 0),
             "Board convection coefficient (W/m²/K)", low=0)
    emissivity = _num(settings.get("board_emissivity", emissivity), "Emissivity", low=0, high=1)
    grid_n = settings.get("grid_cells_long_axis", 48)
    if isinstance(grid_n, bool) or not isinstance(grid_n, int) or not 24 <= grid_n <= 80:
        raise ValueError("grid_cells_long_axis must be an integer from 24 to 80.")
    blur = _num(settings.get("copper_blur_cells", 0), "Copper supersampling", low=0, high=1)
    if blur not in (0, .5, 1):
        raise ValueError("copper_blur_cells supports 0, 0.5 or 1.")
    copper_mode = settings.get("copper_raster_mode", "area_face")
    if copper_mode not in ("area_face", "sampled"):
        raise ValueError("copper_raster_mode must be area_face or sampled.")
    xmin, ymin, xmax, ymax = [_num(v, "Board bound") for v in geometry["bbox_mm"]]
    width, height = xmax-xmin, ymax-ymin
    if width <= 0 or height <= 0:
        raise ValueError("Board bounding box must have positive width and height.")
    nx = max(2, round(grid_n*width/max(width, height)))
    ny = max(2, round(grid_n*height/max(width, height)))
    x_edges = [xmin+i*width/nx for i in range(nx+1)]
    y_edges = [ymin+j*height/ny for j in range(ny+1)]
    phase = settings.get("grid_phase_fraction", [0, 0])
    if not isinstance(phase, (list, tuple)) or len(phase) != 2:
        raise ValueError("grid_phase_fraction must have X and Y offsets.")
    phase_x = _num(phase[0], "X grid phase", low=-.5, high=.5)
    phase_y = _num(phase[1], "Y grid phase", low=-.5, high=.5)
    x_step, y_step = width/nx, height/ny
    x_edges = [x_edges[0]]+[value+phase_x*x_step for value in x_edges[1:-1]]+[x_edges[-1]]
    y_edges = [y_edges[0]]+[value+phase_y*y_step for value in y_edges[1:-1]]+[y_edges[-1]]
    refinement = settings.get("source_refinement_factor", 1)
    if isinstance(refinement, bool) or refinement not in (1, 2):
        raise ValueError("source_refinement_factor must be 1 or 2.")
    if refinement == 2:
        sources_by_ref = {part["reference"] for part in result.get("components", [])
                          if part.get("heat_path") == "board"}
        source_boxes = []
        for component in view.get("components", []):
            if component["reference"] not in sources_by_ref:
                continue
            bbox = component.get("bbox_mm")
            if bbox is not None and len(bbox) == 4:
                source_boxes.append(tuple(_num(value, "Source bound") for value in bbox))
            else:
                x, y = component["position_mm"]
                source_boxes.append((x, y, x, y))

        def split_near_sources(edges, axis):
            base = edges[1]-edges[0]
            intervals = [(box[axis]-base, box[axis+2]+base) for box in source_boxes]
            refined = [edges[0]]
            for left, right in zip(edges, edges[1:]):
                if any(right >= low and left <= high for low, high in intervals):
                    refined.append((left+right)/2)
                refined.append(right)
            return refined

        x_edges = split_near_sources(x_edges, 0)
        y_edges = split_near_sources(y_edges, 1)
    nx, ny = len(x_edges)-1, len(y_edges)-1
    xs = [(x_edges[i]+x_edges[i+1])/2 for i in range(nx)]
    ys = [(y_edges[j]+y_edges[j+1])/2 for j in range(ny)]
    x_widths = [(x_edges[i+1]-x_edges[i])/1000 for i in range(nx)]
    y_widths = [(y_edges[j+1]-y_edges[j])/1000 for j in range(ny)]
    cells = [(i, j) for j, y in enumerate(ys) for i, x in enumerate(xs)
             if _board_contains((x, y), geometry["outline"])]
    if not cells:
        raise ValueError("Thermal grid does not intersect the verified board outline.")
    ncell = len(cells)
    sink_parts = [part for part in result.get("components", []) if part.get("heat_path") == "heatsink"]
    nboard = ncell*len(layers)
    component_storage = _component_storage(settings, result)
    storage_nodes = {ref: nboard+len(sink_parts)+index
                     for index, ref in enumerate(component_storage)}
    nnode = nboard+len(sink_parts)+len(storage_nodes)
    if nnode > 150000:
        raise ValueError("Thermal grid exceeds 150,000 layer cells; reduce resolution.")
    by_cell = {cell: index for index, cell in enumerate(cells)}
    node = lambda layer_index, cell_index: layer_index*ncell+cell_index
    cell_areas = [x_widths[i]*y_widths[j] for i, j in cells]
    # A dielectric slice is bounded halfway to its neighboring copper layers.
    z = [_num(row["z_mm"], "Layer Z (mm)") for row in layers]
    thickness = [_num(row["thickness_mm"], "Copper thickness (mm)", low=1e-9) for row in layers]
    intervals = []
    for i in range(len(layers)-1):
        gap = z[i+1]-z[i]-(thickness[i]+thickness[i+1])/2
        if gap <= 0:
            raise ValueError("Stackup layers overlap or have no dielectric separation.")
        intervals.append(gap/1000)
    slice_thickness = [((intervals[i-1] if i else 0)+(intervals[i] if i < len(intervals) else 0))/2
                       for i in range(len(layers))]
    # Copper membership is kept per polygon. Supersampling improves subcell
    # occupancy but lateral copper edges require the *same* polygon at the face.
    memberships = []
    raster_started = time.monotonic()
    raster_total = len(layers)*ncell
    raster_done = 0
    if progress:
        progress("copper rasterization", 0, raster_total, 0.0, None)
    for layer in layers:
        polygons = layer.get("polygons_mm", [])
        bounds = []
        for polygon in polygons:
            outer = polygon["outer"]
            bounds.append((min(p[0] for p in outer), min(p[1] for p in outer),
                           max(p[0] for p in outer), max(p[1] for p in outer)))
        layer_members = []
        for i, j in cells:
            dx_mm = x_edges[i+1]-x_edges[i]
            dy_mm = y_edges[j+1]-y_edges[j]
            if copper_mode == "area_face":
                probes = []
            elif blur == 1:
                probes = [(xs[i]+a*dx_mm/3, ys[j]+b*dy_mm/3)
                          for a in (-1, 0, 1) for b in (-1, 0, 1)]
            elif blur == .5:
                probes = [(xs[i], ys[j]), (xs[i]-dx_mm/3, ys[j]),
                          (xs[i]+dx_mm/3, ys[j]), (xs[i], ys[j]-dy_mm/3),
                          (xs[i], ys[j]+dy_mm/3)]
            else:
                probes = [(xs[i], ys[j])]
            weights = {}
            for poly_index, polygon in enumerate(polygons):
                x0, y0, x1, y1 = bounds[poly_index]
                if (x1 < xs[i]-dx_mm/2 or x0 > xs[i]+dx_mm/2 or
                        y1 < ys[j]-dy_mm/2 or y0 > ys[j]+dy_mm/2):
                    continue
                fraction = (_polygon_cell_fraction(polygon, x_edges[i], y_edges[j],
                                                   x_edges[i+1], y_edges[j+1])
                            if copper_mode == "area_face" else
                            sum(_polygon_contains(point, polygon) for point in probes)/len(probes))
                if fraction:
                    weights[poly_index] = fraction
                elif _polygon_intersects_cell(polygon, x_edges[i], y_edges[j],
                                               x_edges[i+1], y_edges[j+1]):
                    # Keep a candidate even when all fixed sample points miss a
                    # thin feature. Face intersection decides conductivity.
                    weights[poly_index] = 1e-12
            layer_members.append(weights)
            raster_done += 1
            if progress and (raster_done == raster_total or
                             raster_done % max(1, raster_total//100) == 0):
                elapsed = time.monotonic()-raster_started
                eta = elapsed*(raster_total-raster_done)/raster_done
                progress("copper rasterization", raster_done, raster_total,
                         elapsed, eta)
        memberships.append(layer_members)
    edges = []
    copper_edges = 0
    def add_edge(a, b, g):
        if g > 0:
            edges.append((a, b, g))
    conductance_started = time.monotonic()
    for li, layer in enumerate(layers):
        if progress:
            elapsed = time.monotonic()-conductance_started
            progress("layer conductance assembly", li, len(layers), elapsed,
                     elapsed*(len(layers)-li)/li if li else None)
        polygons = layer.get("polygons_mm", [])
        for ci, (i, j) in enumerate(cells):
            for key, length, run, face_start, face_end, normal, offset in (
                ((i+1, j), y_widths[j],
                 (x_widths[i]+x_widths[i+1])/2 if i+1 < nx else x_widths[i],
                 (x_edges[i+1], y_edges[j]), (x_edges[i+1], y_edges[j+1]),
                 (1, 0), min(x_widths[i], x_widths[i+1])*1e-1 if i+1 < nx else 0),
                ((i, j+1), x_widths[i],
                 (y_widths[j]+y_widths[j+1])/2 if j+1 < ny else y_widths[j],
                 (x_edges[i], y_edges[j+1]), (x_edges[i+1], y_edges[j+1]),
                 (0, 1), min(y_widths[j], y_widths[j+1])*1e-1 if j+1 < ny else 0)):
                cj = by_cell.get(key)
                if cj is None:
                    continue
                base = dielectric_k*slice_thickness[li]*length/run
                common = memberships[li][ci].keys() & memberships[li][cj].keys()
                copper_fraction = max((min(
                    _face_copper_fraction(face_start, face_end, polygons[p], normal, offset),
                    memberships[li][ci][p], memberships[li][cj][p])
                    if copper_mode == "area_face" else
                    _face_copper_fraction(face_start, face_end, polygons[p], normal, offset)
                    for p in common), default=0)
                bonus = copper_k*(thickness[li]/1000)*length/run*copper_fraction
                if bonus:
                    copper_edges += 1
                add_edge(node(li, ci), node(li, cj), base+bonus)
    if progress:
        progress("layer conductance assembly", len(layers), len(layers),
                 time.monotonic()-conductance_started, 0.0)
    for li, gap in enumerate(intervals):
        for ci in range(ncell):
            add_edge(node(li, ci), node(li+1, ci),
                     dielectric_k*cell_areas[ci]/gap)
    layer_ids = {row["id"]: i for i, row in enumerate(layers)}
    via_edges = 0
    annulus_edges = 0
    unresolved_barrel_stencils = 0
    barrel_loss_stencils = {}
    barrel_mode = settings.get("barrel_contact_mode", "annulus_stencil")
    if barrel_mode not in ("annulus_stencil", "nearest_cell"):
        raise ValueError("barrel_contact_mode must be annulus_stencil or nearest_cell.")
    barrel_started = time.monotonic()
    barrels = geometry.get("barrels", [])
    for barrel_index, via in enumerate(barrels):
        if progress and barrel_index % max(1, len(barrels)//100) == 0:
            elapsed = time.monotonic()-barrel_started
            progress("plated barrel contact assembly", barrel_index, len(barrels), elapsed,
                     elapsed*(len(barrels)-barrel_index)/barrel_index if barrel_index else None)
        span = [layer_ids[lid] for lid in via.get("span_layers", []) if lid in layer_ids]
        if len(span) < 2:
            continue
        span.sort()
        drill = _num(via["drill_mm"], "Barrel drill (mm)", low=1e-9)
        if plating*2 >= drill:
            raise ValueError(f"{via['id']}: plating thickness is implausible for its drill.")
        barrel_area = barrel_area_mm2(via, plating)/1e6
        x, y = float(via["x_mm"]), float(via["y_mm"])
        ci = min(range(ncell), key=lambda ci: (xs[cells[ci][0]]-x)**2+(ys[cells[ci][1]]-y)**2)
        if (abs(xs[cells[ci][0]]-x)>x_widths[cells[ci][0]]*1000 or
                abs(ys[cells[ci][1]]-y)>y_widths[cells[ci][1]]*1000):
            continue
        for a, b in zip(span, span[1:]):
            unresolved_before = unresolved_barrel_stencils
            if b != a+1:
                raise ValueError(f"{via['id']}: barrel span is not continuous through the stackup.")
            if barrel_mode == "nearest_cell" and drill_dimensions(via)[0] != drill_dimensions(via)[1]:
                raise ValueError("Plated slots require the distributed annulus_stencil contact mode.")
            if barrel_mode == "nearest_cell":
                stencil = [(ci, 1.0)]
            elif drill_dimensions(via)[0] != drill_dimensions(via)[1]:
                # Apportion the exact slot-wall axial conductance among actual
                # flashed land cells on both adjacent layers, outside the void.
                lands = via.get("land_polygons_mm", {})
                pair_lands = [lands.get(str(layers[index]["id"]), []) for index in (a, b)]
                candidates = []
                for candidate, (ix, iy) in enumerate(cells):
                    wall = drill_wall_distance((xs[ix], ys[iy]), via)
                    if wall <= 0:
                        continue
                    overlaps = [math.fsum(_polygon_cell_fraction(poly, x_edges[ix], y_edges[iy],
                                                x_edges[ix+1], y_edges[iy+1]) for poly in land)
                                for land in pair_lands]
                    if min(overlaps) > 0:
                        reach = math.hypot(x_widths[ix], y_widths[iy])*500
                        candidates.append((candidate, min(overlaps)/max(wall, reach/2, plating)))
                if not candidates:
                    # On coarse meshes the entire land may lie in drill-centred
                    # cells. Keep axial conductance with an explicit unresolved
                    # proxy rather than dropping the slot or adding heat in it.
                    distances = [(candidate, drill_wall_distance((xs[ix], ys[iy]), via))
                                 for candidate, (ix, iy) in enumerate(cells)
                                 if drill_wall_distance((xs[ix], ys[iy]), via) > 0]
                    if not distances:
                        raise ValueError(f"{via['id']}: no board cell center outside the slot.")
                    distances.sort(key=lambda entry: entry[1])
                    candidates = [(candidate, 1/max(distance, plating)) for candidate, distance in distances[:8]]
                    unresolved_barrel_stencils += 1
                total = math.fsum(weight for _, weight in candidates)
                stencil = [(candidate, weight/total) for candidate, weight in candidates]
            else:
                diameters = via.get("outer_diameters_mm", {})
                diam_a = float(diameters.get(str(layers[a]["id"]), drill+2*plating))
                diam_b = float(diameters.get(str(layers[b]["id"]), drill+2*plating))
                outer_radius = max(drill/2, min(diam_a, diam_b)/2)
                candidates = []
                for candidate, (ix, iy) in enumerate(cells):
                    distance = math.hypot(xs[ix]-x, ys[iy]-y)
                    cell_reach = math.hypot(x_widths[ix], y_widths[iy])*500
                    if drill/2 < distance <= outer_radius+cell_reach:
                        candidates.append((candidate, distance))
                if not candidates:
                    candidates = [(candidate, math.hypot(xs[ix]-x, ys[iy]-y))
                                  for candidate, (ix, iy) in enumerate(cells)
                                  if math.hypot(xs[ix]-x, ys[iy]-y) > drill/2]
                    if not candidates:
                        raise ValueError(f"{via['id']}: no board cell center outside the drill.")
                    unresolved_barrel_stencils += 1
                candidates.sort(key=lambda entry: entry[1])
                candidates = candidates[:8]
                raw = [1/max(distance, drill/2) for _, distance in candidates]
                total = math.fsum(raw)
                stencil = [(candidate, weight/total)
                           for (candidate, _), weight in zip(candidates, raw)]
            lands = via.get("land_polygons_mm", {})
            pair_lands = [lands.get(str(layers[index]["id"]), []) for index in (a,b)]
            verified = (barrel_mode == "annulus_stencil" and unresolved_before == unresolved_barrel_stencils
                        and all(pair_lands) and all(
                            _drill_at((xs[cells[ci][0]],ys[cells[ci][1]]),layers[li]["id"],geometry) is None
                            and any(_polygon_cell_fraction(poly,x_edges[cells[ci][0]],y_edges[cells[ci][1]],
                                                          x_edges[cells[ci][0]+1],y_edges[cells[ci][1]+1]) > 0
                                    for poly in pair_lands[endpoint])
                            for endpoint,li in enumerate((a,b)) for ci,_ in stencil))
            key = (str(via["id"]),layers[a]["id"],layers[b]["id"])
            if key in barrel_loss_stencils:
                raise ValueError("Repeated barrel segment identity in thermal geometry.")
            barrel_loss_stencils[key] = {"verified": bool(verified), "nodes": [
                (node(li,ci),.5*weight) for li in (a,b) for ci,weight in stencil]}
            conductance = copper_k*barrel_area/((z[b]-z[a])/1000)
            for target, weight in stencil:
                add_edge(node(a, target), node(b, target), conductance*weight)
            annulus_edges += len(stencil)
            via_edges += 1
    if progress:
        progress("plated barrel contact assembly", len(barrels), len(barrels),
                 time.monotonic()-barrel_started, 0.0)
    sources = np.zeros(nnode, dtype=float)
    view_refs = {row["reference"]: row for row in view.get("components", [])}
    output_components = []
    source_sites = {}
    sink_nodes = {}
    sink_areas = settings.get("sink_exposed_area_mm2", {})
    sink_to_board = settings.get("sink_to_board_k_per_w", {})
    sink_resistances = settings.get("component_to_sink_k_per_w", {})
    board_resistances = settings.get("component_to_board_k_per_w", {})
    contact_pad_numbers = settings.get("source_contact_pad_numbers", {})
    if not isinstance(contact_pad_numbers, Mapping):
        raise ValueError("source_contact_pad_numbers must map references to pad numbers.")
    contact_records = geometry.get("source_contacts", [])
    for label, mapping in (("sink_exposed_area_mm2", sink_areas),
                           ("sink_to_board_k_per_w", sink_to_board),
                           ("component_to_sink_k_per_w", sink_resistances),
                           ("component_to_board_k_per_w", board_resistances)):
        if not isinstance(mapping, Mapping):
            raise ValueError(label + " must map references to values.")
    sink_airflow = _num(settings.get("sink_airflow_m_s", 0), "Sink airflow (m/s)", low=0)
    if environment == "vacuum" and sink_airflow:
        raise ValueError("Sink airflow must be zero in vacuum.")
    sink_h = _num(settings.get("sink_h_w_m2k", 5+5*sink_airflow if environment == "air" else 0),
                  "Sink convection coefficient (W/m²/K)", low=0)
    if environment == "vacuum" and sink_h:
        raise ValueError("Sink convection must be zero in vacuum.")
    sink_e_raw = settings.get("sink_emissivity", emissivity)
    if not isinstance(sink_e_raw, Mapping):
        sink_e_raw = {str(part["reference"]): sink_e_raw for part in sink_parts}
    for part in result.get("components", []):
        ref = str(part["reference"])
        power = _num(part.get("power_w"), f"{ref} power (W)", low=0)
        component = view_refs.get(ref)
        if component is None or not component.get("on_board", True):
            raise ValueError(f"{ref}: mapped component has no verified board position.")
        if part.get("heat_path") == "heatsink":
            if ref not in sink_areas:
                raise ValueError(f"{ref}: enter sink_exposed_area_mm2; shape dimensions do not establish exposed area.")
            area = _num(sink_areas[ref], f"{ref} sink exposed area (mm²)", low=1e-9)/1e6
            sink_e = _num(sink_e_raw.get(ref, emissivity), f"{ref} sink emissivity", low=0, high=1)
            if sink_h == 0 and sink_e == 0 and ref not in sink_to_board and ref not in storage_nodes:
                raise ValueError(f"{ref}: sink has no heat rejection path.")
            ni = nboard+len(sink_nodes)
            sink_nodes[ref] = (ni, area, sink_e)
            if ref not in storage_nodes:
                sources[ni] += power
            if ref in sink_to_board:
                resistance = _num(sink_to_board[ref], f"{ref} sink-to-board resistance (K/W)", low=1e-9)
                pos = component["position_mm"]
                ci = min(range(ncell), key=lambda ci:
                         (xs[cells[ci][0]]-pos[0])**2+(ys[cells[ci][1]]-pos[1])**2)
                li = 0 if component.get("side", "top").lower() == "top" else len(layers)-1
                add_edge(ni, node(li, ci), 1/resistance)
            output_components.append({"reference": ref, "power_w": power,
                                      "side": component.get("side", "top"), "heat_path": "heatsink",
                                      "source_distribution": "virtual_sink_node",
                                      "board_site_c": None, "sink_c": None, "junction_c": None})
            continue
        li = 0 if component.get("side", "top").lower() == "top" else len(layers)-1
        contact_polygons = None
        pad_number = contact_pad_numbers.get(ref)
        if pad_number is not None:
            if component.get("bbox_mm") is None:
                raise ValueError(f"{ref}: selected pad contact requires a saved component bounding box.")
            matched = [record for record in contact_records
                       if record["reference"] == ref and
                       str(record["pad_number"]) == str(pad_number) and
                       record["layer_id"] == layers[li]["id"]]
            contact_polygons = [polygon for record in matched
                                for polygon in record["polygons_mm"]]
            if not contact_polygons:
                raise ValueError(f"{ref}: selected pad {pad_number} has no saved copper contact on {layers[li]['name']}.")
        relevant_holes = []
        if contact_polygons is not None:
            bbox = component.get("bbox_mm")
            for hole in [*geometry.get("barrels", []), *geometry.get("mounting_holes", [])]:
                if not hole.get("drill_mm") and not hole.get("drill_size_mm"):
                    continue
                radius = max(drill_dimensions(hole))/2
                if (bbox[0]-radius <= hole["x_mm"] <= bbox[2]+radius and
                        bbox[1]-radius <= hole["y_mm"] <= bbox[3]+radius):
                    relevant_holes.append(hole)
        weights, distribution, contact_area, effective_cells, moved_area = _source_weights(
            component, cells, xs, ys, x_edges, y_edges, contact_polygons,
            relevant_holes)
        if not math.isclose(math.fsum(weight for _, weight in weights), 1.0,
                            rel_tol=1e-12, abs_tol=1e-12):
            raise ArithmeticError(f"{ref}: mapped source fractions do not conserve power.")
        if ref not in storage_nodes:
            for ci, weight in weights:
                sources[node(li, ci)] += power*weight
        source_sites[ref] = (li, weights)
        output_components.append({"reference": ref, "power_w": power, "side": component.get("side", "top"),
                                  "heat_path": "board", "sink_c": None,
                                  "source_distribution": distribution,
                                  "source_cells": len(weights),
                                  "source_contact_area_mm2": contact_area,
                                  "source_drill_redistributed_mm2": moved_area,
                                  "effective_source_cells": effective_cells,
                                  "source_bbox_mm": component.get("bbox_mm"),
                                  "source_pad_number": str(pad_number) if pad_number is not None else None,
                                  "source_net": matched[0]["net"] if pad_number is not None else None,
                                  "source_cell_size_mm": {
                                      "min_x": min(x_edges[cells[ci][0]+1]-x_edges[cells[ci][0]]
                                                   for ci, _ in weights),
                                      "max_x": max(x_edges[cells[ci][0]+1]-x_edges[cells[ci][0]]
                                                   for ci, _ in weights),
                                      "min_y": min(y_edges[cells[ci][1]+1]-y_edges[cells[ci][1]]
                                                   for ci, _ in weights),
                                      "max_y": max(y_edges[cells[ci][1]+1]-y_edges[cells[ci][1]]
                                                   for ci, _ in weights)},
                                  "source_peak_c": None,
                                  "source_peak_cell": None,
                                  "junction_peak_proxy_c": None,
                                  "board_site_c": None,
                                  "junction_c": None})
    copper_sources = _map_copper_losses(settings.get("copper_loss_sources", []), geometry, layers,
                                        cells, x_edges, y_edges, barrel_loss_stencils)
    if {source["id"] for source in copper_sources} & set(view_refs):
        raise ValueError("Copper loss identities must not collide with component references.")
    for source in copper_sources:
        for ni, weight in source["nodes"]:
            sources[ni] += source["power_w"]*weight
    if not output_components and not copper_sources:
        raise ValueError("No mapped QuickTherm component or copper loss power is available.")
    component_contacts = {}
    by_reference = {part["reference"]: part for part in output_components}
    for ref, spec in component_storage.items():
        ni = storage_nodes[ref]
        contacts = ([(sink_nodes[ref][0], 1.0)] if ref in sink_nodes else
                    [(node(source_sites[ref][0], ci), weight) for ci, weight in source_sites[ref][1]])
        component_contacts[ref] = contacts
        for contact_node, weight in contacts:
            conductance = weight/spec["resistance_k_per_w"]
            if not math.isfinite(conductance) or conductance <= 0:
                raise ValueError(ref + ": component contact conductance exceeds the finite numerical range.")
            add_edge(ni, contact_node, conductance)
        sources[ni] = by_reference[ref]["power_w"]
    declared_power = math.fsum(part["power_w"] for part in [*output_components, *copper_sources])
    allocated_power = float(np.sum(sources))
    if not math.isclose(allocated_power, declared_power,
                        rel_tol=1e-10, abs_tol=1e-10):
        raise ArithmeticError("Mapped source power was not fully allocated to thermal nodes.")
    boundaries = settings.get("mount_boundaries", [])
    if not isinstance(boundaries, list):
        raise ValueError("mount_boundaries must be a list of selected mounting-hole records.")
    available_mounts = {item["id"]: item for item in geometry.get("mounting_holes", [])}
    mounts = []
    fixed = {}
    contact_edges = []
    used_mounts = set()
    for boundary in boundaries:
        mount_id = boundary.get("id")
        if mount_id not in available_mounts or mount_id in used_mounts:
            raise ValueError("Each mount boundary must select one unique saved mounting-hole ID.")
        used_mounts.add(mount_id)
        mount = available_mounts[mount_id]
        if not mount.get("plated", False) and not boundary.get("mechanical_contact", False):
            raise ValueError(
                f"{mount_id}: NPTH mounting hole has no plated thermal contact; "
                "declare an explicit mechanical fixture contact before using it as a sink.")
        temp = _num(boundary.get("temperature_c"), "Mount temperature (°C)", low=-273.15)
        resistance = _num(boundary.get("contact_r_k_w"), "Mount contact resistance (K/W)", low=0)
        side = boundary.get("side", "top")
        if side not in ("top", "bottom"):
            raise ValueError("Mount side must be top or bottom.")
        li = 0 if side == "top" else len(layers)-1
        ci = min(range(ncell), key=lambda ci:
                 (xs[cells[ci][0]]-mount["x_mm"])**2+(ys[cells[ci][1]]-mount["y_mm"])**2)
        ni = node(li, ci)
        if resistance == 0:
            if ni in fixed:
                raise ValueError("Two ideal mount boundaries map to one thermal cell; refine the grid or combine contacts.")
            fixed[ni] = temp
        else:
            contact_edges.append((ni, 1/resistance, temp))
        mounts.append({"id": mount_id, "side": side, "temperature_c": temp,
                       "contact_r_k_w": resistance, "node_index": ni, "heat_flux_w": None,
                       "contact_kind": "selected_plated_hole" if mount.get("plated", False) else "explicit_npth_mechanical_contact",
                       "evidence": "user-selected fixture contact; geometry alone does not prove contact"})
    rr, cc, vv = [], [], []
    for a, b, g in edges:
        rr.extend((a, b, a, b)); cc.extend((a, b, b, a)); vv.extend((g, g, -g, -g))
    laplacian = coo_matrix((vv, (rr, cc)), shape=(nnode, nnode)).tocsr()
    contact_g = np.zeros(nnode, dtype=float)
    contact_rhs = np.zeros(nnode, dtype=float)
    for ni, g, temp in contact_edges:
        contact_g[ni] += g
        contact_rhs[ni] += g*temp
    surface_area = np.zeros(nnode, dtype=float)
    convection_h = np.full(nnode, h, dtype=float)
    surface_e = np.full(nnode, emissivity, dtype=float)
    for ci in range(ncell):
        surface_area[node(0, ci)] += cell_areas[ci]
        surface_area[node(len(layers)-1, ci)] += cell_areas[ci]
    for ref, (ni, area, sink_e) in sink_nodes.items():
        surface_area[ni] = area
        convection_h[ni] = sink_h
        surface_e[ni] = sink_e
    for ref, ni in storage_nodes.items():
        spec = component_storage[ref]
        if "exposed_area_mm2" in spec:
            surface_area[ni] = spec["exposed_area_mm2"]/1e6
            convection_h[ni] = spec["h_w_m2k"]
            surface_e[ni] = spec["emissivity"]
    _, graph_labels = connected_components(laplacian, directed=False)
    unexcited_anchors = 0
    display_anchors = set()
    for label in set(int(value) for value in graph_labels):
        indices = np.flatnonzero(graph_labels == label)
        has_rejection = (bool(np.any(surface_area[indices]*(convection_h[indices]+surface_e[indices])))
                         or bool(np.any(contact_g[indices]))
                         or any(int(index) in fixed for index in indices))
        if not has_rejection:
            if np.any(sources[indices]):
                raise ValueError("A powered thermal region has no convection, radiation or fixture path.")
            fixed[int(indices[0])] = ambient
            display_anchors.add(int(indices[0]))
            unexcited_anchors += 1
    free = np.asarray([i for i in range(nnode) if i not in fixed], dtype=int)
    fixed_ids = np.asarray(sorted(fixed), dtype=int)
    temp = np.full(nnode, ambient, dtype=float)
    for ni, value in fixed.items():
        temp[ni] = value
    if progress:
        progress("thermal solve", 0, 1, 0.0, None)
    solve_started = time.monotonic()
    if len(free):
        for iteration in range(40):
            kelvin = temp + 273.15
            loss = surface_area*(convection_h*(temp-ambient)+surface_e*SIGMA*(kelvin**4-(ambient+273.15)**4))
            slope = surface_area*(convection_h+4*surface_e*SIGMA*kelvin**3)
            matrix = laplacian+diags(contact_g+slope, format="csr")
            rhs = sources+contact_rhs+slope*temp-loss
            if len(fixed_ids):
                rhs[free] -= matrix[free][:, fixed_ids] @ temp[fixed_ids]
            candidate = spsolve(matrix[free][:, free], rhs[free])
            if not np.all(np.isfinite(candidate)) or np.max(candidate)>10000 or np.min(candidate)<-273.15:
                raise ValueError("Thermal solve diverged; check power and boundary inputs.")
            change = float(np.max(np.abs(candidate-temp[free])))
            temp[free] = candidate
            if change <= 1e-7:
                break
        else:
            raise ValueError("Layer-resolved thermal solve did not converge.")
        iterations = iteration+1
    else:
        iterations = 0
    if progress:
        progress("thermal solve", 1, 1, time.monotonic()-solve_started, 0.0)
    for part in output_components:
        if part["heat_path"] == "heatsink":
            ni, _, _ = sink_nodes[part["reference"]]
            part["sink_c"] = float(temp[ni])
            if part["reference"] in sink_resistances and part["reference"] not in storage_nodes:
                r = _num(sink_resistances[part["reference"]],
                         "Component-to-sink resistance (K/W)", low=0)
                part["junction_c"] = part["sink_c"]+part["power_w"]*r
            continue
        li, weights = source_sites[part["reference"]]
        part["board_site_c"] = math.fsum(float(temp[node(li, ci)])*weight for ci, weight in weights)
        peak_ci = max((ci for ci, _ in weights), key=lambda ci: temp[node(li, ci)])
        peak_i, peak_j = cells[peak_ci]
        peak_point = (xs[peak_i], ys[peak_j])
        part["source_peak_c"] = float(temp[node(li, peak_ci)])
        part["source_peak_cell"] = {
            "x_mm": peak_point[0], "y_mm": peak_point[1],
            "center_in_drill_id": _drill_at(peak_point, layers[li]["id"], geometry),
            "center_in_copper": any(_polygon_contains(peak_point, polygon)
                                    for polygon in layers[li].get("polygons_mm", [])),
            "copper_area_fraction": max(memberships[li][peak_ci].values(), default=0),
        }
        if part["reference"] in board_resistances and part["reference"] not in storage_nodes:
            r = _num(board_resistances[part["reference"]], "Component-to-board resistance (K/W)", low=0)
            part["junction_c"] = part["board_site_c"]+part["power_w"]*r
            part["junction_peak_proxy_c"] = part["source_peak_c"]+part["power_w"]*r
    for ref, spec in component_storage.items():
        part = by_reference[ref]
        value = float(temp[storage_nodes[ref]])
        part.update(storage_node=storage_nodes[ref], temperature_kind=spec["temperature_kind"],
                    capacity_j_k=spec["capacity_j_k"], resistance_k_per_w=spec["resistance_k_per_w"],
                    component_temperature_c=value,
                    body_c=value if spec["temperature_kind"] == "body" else None,
                    junction_c=value if spec["temperature_kind"] == "junction" else None,
                    junction_peak_proxy_c=None, component_model="lumped_component_storage",
                    contact_heat_w=math.fsum(weight*(value-float(temp[ni]))/spec["resistance_k_per_w"]
                                            for ni, weight in component_contacts[ref]))
    kelvin = temp+273.15
    conv_terms = surface_area*convection_h*(temp-ambient)
    rad_terms = surface_area*surface_e*SIGMA*(kelvin**4-(ambient+273.15)**4)
    for ref, ni in storage_nodes.items():
        part = by_reference[ref]
        part.update(convection_w=float(conv_terms[ni]), radiation_w=float(rad_terms[ni]))
        part.update({key: component_storage[ref][key] for key in ("exposed_area_mm2", "h_w_m2k", "emissivity")
                     if key in component_storage[ref]})
    convection = float(np.sum(conv_terms))
    radiation = float(np.sum(rad_terms))
    residual_nodes = np.asarray(laplacian@temp + contact_g*temp-contact_rhs +
                                conv_terms+rad_terms-sources)
    for mount in mounts:
        ni = mount.pop("node_index")
        if mount["contact_r_k_w"] == 0:
            # At a Dirichlet node, the balancing fixture flux is the negative
            # of its unconstrained equation residual. Positive leaves board.
            mount["heat_flux_w"] = float(-residual_nodes[ni])
        else:
            mount["heat_flux_w"] = float((temp[ni]-mount["temperature_c"])/mount["contact_r_k_w"])
    mount_flux = math.fsum(item["heat_flux_w"] for item in mounts)
    input_w = float(np.sum(sources))
    residual = input_w-convection-radiation-mount_flux
    tolerance = max(1e-5, abs(input_w)*1e-4)
    fields = []
    for li, layer in enumerate(layers):
        values = [[None for _ in range(nx)] for _ in range(ny)]
        for ci, (i, j) in enumerate(cells):
            values[j][i] = float(temp[node(li, ci)])
        slab = temp[li*ncell:(li+1)*ncell]
        peak_ci = int(np.argmax(slab))
        peak_i, peak_j = cells[peak_ci]
        peak_point = (xs[peak_i], ys[peak_j])
        fields.append({"id": layer["id"], "name": layer["name"], "z_mm": z[li],
                       "value_location": "finite_volume_cell",
                       "x_centers_mm": xs, "y_centers_mm": ys,
                       "x_edges_mm": x_edges, "y_edges_mm": y_edges,
                       "values_c": values,
                       "sampled_min_c": float(np.min(slab)), "sampled_max_c": float(np.max(slab)),
                       "sampled_max_cell": {
                           "x_mm": peak_point[0], "y_mm": peak_point[1],
                           "center_in_drill_id": _drill_at(peak_point, layer["id"], geometry),
                           "center_in_copper": any(_polygon_contains(peak_point, polygon)
                                                   for polygon in layer.get("polygons_mm", [])),
                           "copper_area_fraction": max(memberships[li][peak_ci].values(), default=0),
                       }})
    transient = None
    if settings.get("transient_settings") is not None:
        from .thermal_spatial_transient import evolve
        transient_settings = settings["transient_settings"]
        copper_capacity = _num(transient_settings.get("copper_volumetric_capacity_j_m3k"),
                               "Copper volumetric heat capacity (J/m³/K)", low=1e-9)
        dielectric_capacity = _num(transient_settings.get("dielectric_volumetric_capacity_j_m3k"),
                                   "Dielectric volumetric heat capacity (J/m³/K)", low=1e-9)
        capacity = np.zeros(nnode)
        for li in range(len(layers)):
            for ci in range(ncell):
                # Union upper bound avoids double counting overlapping copper polygons.
                copper_fraction = min(1.0, sum(memberships[li][ci].values()))
                capacity[node(li, ci)] = cell_areas[ci] * (
                    slice_thickness[li] * dielectric_capacity + thickness[li]/1000 *
                    (copper_fraction*copper_capacity + (1-copper_fraction)*dielectric_capacity))
        for ref, (ni, _, _) in sink_nodes.items():
            capacity[ni] = _num(transient_settings.get("sink_capacity_j_k", {}).get(ref),
                                ref + " sink heat capacity (J/K)", low=1e-9)
        for ref, ni in storage_nodes.items():
            capacity[ni] = component_storage[ref]["capacity_j_k"]
        initial_vector = None
        if storage_nodes:
            initial = _num(transient_settings.get("initial_c", ambient), "Initial temperature (C)")
            initial_vector = np.full(nnode, initial)
            for ref, ni in storage_nodes.items():
                initial_vector[ni] = component_storage[ref].get("initial_c", initial)
        source_vectors = {}
        for part in output_components:
            ref = part["reference"]
            vector = np.zeros(nnode)
            if ref in storage_nodes:
                vector[storage_nodes[ref]] = part["power_w"]
            elif ref in sink_nodes:
                vector[sink_nodes[ref][0]] = part["power_w"]
            else:
                li, weights = source_sites[ref]
                for ci, weight in weights:
                    vector[node(li, ci)] = part["power_w"]*weight
            source_vectors[ref] = vector
        for source in copper_sources:
            vector = np.zeros(nnode)
            for ni, weight in source["nodes"]:
                vector[ni] = source["power_w"]*weight
            source_vectors[source["id"]] = vector
        # Anchors used only to display an unpowered steady region are not
        # physical fixtures and must not drain its initial stored energy.
        transient_fixed = {ni: value for ni, value in fixed.items() if ni not in display_anchors}
        transient = evolve(laplacian, capacity, source_vectors, surface_area, convection_h,
                           surface_e, ambient, contact_g, contact_rhs, transient_fixed, transient_settings,
                           initial_temperatures_c=initial_vector)
        # Flattening metadata makes every frame reusable without rebuilding copper geometry.
        transient["spatial_index"] = {"cells": cells, "x_centers_mm": xs, "y_centers_mm": ys,
                                      "layers": [{"id": layer["id"], "name": layer["name"], "z_mm": z[li]}
                                                 for li, layer in enumerate(layers)],
                                      "active_cells_per_layer": ncell}
        transient["copper_loss_sources"] = copper_sources
        transient["components"] = []
        for part in output_components:
            ref = part["reference"]
            sites = ([(sink_nodes[ref][0], 1.0)] if ref in sink_nodes else
                     [(node(source_sites[ref][0], ci), weight) for ci, weight in source_sites[ref][1]])
            definition = {"reference": ref, "nodes": sites, "power_w": part["power_w"]}
            if ref in storage_nodes:
                spec = component_storage[ref]
                definition.update(storage_node=storage_nodes[ref], temperature_kind=spec["temperature_kind"],
                                  capacity_j_k=spec["capacity_j_k"], resistance_k_per_w=spec["resistance_k_per_w"],
                                  initial_c=float(transient["frames"][0]["temperatures_c"][storage_nodes[ref]]))
                definition.update({key: spec[key] for key in ("exposed_area_mm2", "h_w_m2k", "emissivity") if key in spec})
            else:
                definition["junction_resistance_k_per_w"] = (sink_resistances.get(ref) if ref in sink_nodes
                                                              else board_resistances.get(ref))
            transient["components"].append(definition)
        if storage_nodes:
            transient["assumptions"].append("Selected component nodes store heat using explicit lumped capacities and contact resistances; body and junction temperatures are distinct declared quantities, with no internal solid gradients.")
    return {"model": "steady-state layer-resolved finite-volume board screen",
            **({"transient": transient} if transient is not None else {}),
            "status": "converged" if abs(residual) <= tolerance else "imbalanced",
            "environment": environment, "ambient_c": ambient, "layers": fields,
            "components": output_components, "mounts": mounts, "copper_loss_sources": copper_sources,
            "heat_balance": {"input_w": input_w, "convection_w": convection,
                             "radiation_w": radiation, "mount_flux_w": mount_flux,
                             "board_convection_w": float(np.sum(conv_terms[:nboard])),
                             "board_radiation_w": float(np.sum(rad_terms[:nboard])),
                             "sink_convection_w": float(np.sum(conv_terms[nboard:nboard+len(sink_parts)])),
                             "sink_radiation_w": float(np.sum(rad_terms[nboard:nboard+len(sink_parts)])),
                             "component_convection_w": float(np.sum(conv_terms[nboard+len(sink_parts):])),
                             "component_radiation_w": float(np.sum(rad_terms[nboard+len(sink_parts):])),
                             "copper_loss_input_w": math.fsum(source["power_w"] for source in copper_sources),
                             "component_input_w": math.fsum(part["power_w"] for part in output_components),
                             "residual_w": residual,
                             "relative_residual": abs(residual)/max(abs(input_w), 1e-12),
                             "tolerance_w": tolerance},
            "settings": {"dielectric_k_w_mk": dielectric_k, "copper_k_w_mk": copper_k,
                         "via_plating_mm": plating, "grid_cells_long_axis": grid_n,
                         "source_refinement_factor": refinement,
                         "copper_raster_mode": copper_mode,
                         "barrel_contact_mode": barrel_mode,
                         "grid_phase_fraction": [phase_x, phase_y],
                         "copper_blur_cells": blur, "board_h_w_m2k": h,
                         "board_emissivity": emissivity, "sink_h_w_m2k": sink_h,
                         "component_storage": component_storage},
            "mesh": {"nx": nx, "ny": ny, "active_cells_per_layer": ncell,
                     "source_refinement_factor": refinement,
                     "solver_iterations": iterations, "copper_lateral_edges": copper_edges,
                     "via_vertical_edges": via_edges,
                     "barrel_stencil_edges": annulus_edges,
                     "unresolved_barrel_stencils": unresolved_barrel_stencils,
                     "unexcited_regions_anchored_at_ambient": unexcited_anchors,
                     "component_storage_nodes": len(storage_nodes)},
            "assumptions": environment_notes + [
                "Copper area and shared-face occupancy are clipped from saved polygons in area_face mode; subcell conductance remains a finite-volume approximation.",
                "Dielectric is homogeneous and isotropic between copper midplanes; no anisotropic laminate data are inferred.",
                "Via plating thickness, material conductivity and fixture contacts are explicit user inputs.",
                "Barrel heat flow is a 1D axial approximation; individual land-to-barrel contact and package-pad spreading are unresolved.",
                "The annulus stencil apportions axial barrel conductance among nearby cell centers outside circular or obround drills. Plated slots use exact capsule-wall metal area and actual flashed land polygons; this is not a resolved barrel/land solid mesh.",
                "An explicitly declared NPTH mechanical contact couples to the nearest dielectric cell through entered contact resistance; no copper-plane contact is inferred.",
                "Only top and bottom faces reject heat; edge radiation, package shadows, view factors, airflow fields are unresolved. Spatial transients require explicit volumetric heat capacities and time-step convergence.",
                "Sources use footprint bounding boxes as contact proxies, or a labelled point fallback; junction temperature needs explicit component-to-board resistance.",
                "Legacy massless junction estimates use area-weighted contact temperature plus power times explicit package resistance; source peaks are not resolved die maxima.",
                "Selected storage components use a uniform lumped node with explicit capacity and resistance. Its declared body temperature does not imply a junction temperature. Component surface cooling requires explicit exposed area, convection and emissivity; neither exposed geometry nor internal solid gradients are inferred.",
                "Storage-node links use contact weight divided by resistance; an isothermal component can redistribute heat among nonuniform contact cells, unlike prescribed fixed source fractions.",
                "Reviewed copper losses enter their declared copper-layer cells by conservative polygon overlap. Unsupported board, copper or drill-void mappings are rejected; there is no nearest-cell heat relocation.",
                "Virtual heatsink nodes use entered exposed area and component-to-sink resistance; they couple to the board only if an explicit sink-to-board resistance is supplied.",
                "An unpowered region with no thermal boundary is anchored at ambient only to make its otherwise undefined temperature displayable.",
                "A zero residual is numerical energy balance, not validation of material, boundary or contact assumptions.",
            ]}


def solve_multilayer_thermal_convergence(geometry, view, result, settings,
                                         acceptance, progress=None):
    """Repeat the saved-source steady solve and report mesh acceptance.

    This is a global-grid convergence gate, not a source-contact qualification.
    A tiny source touching four cells still has less than one area-equivalent
    cell and must not pass a four-cell resolution requirement.
    """
    if not isinstance(acceptance, Mapping):
        raise ValueError("mesh_acceptance must be a mapping.")
    grids = acceptance.get("grid_cells_long_axis", [24, 48, 80])
    if (not isinstance(grids, list) or len(grids) < 2 or
            any(isinstance(n, bool) or not isinstance(n, int) or not 24 <= n <= 80
                for n in grids) or grids != sorted(set(grids))):
        raise ValueError("Mesh acceptance needs two or more increasing grid sizes from 24 to 80.")
    tolerance = _num(acceptance.get("maximum_change_c"), "Mesh maximum change (°C)", low=0)
    layer_tolerance = _num(acceptance.get("maximum_layer_peak_change_c", tolerance),
                           "Layer peak maximum change (°C)", low=0)
    field_tolerance = _num(acceptance.get("maximum_field_change_c", tolerance),
                           "Spatial field maximum change (°C)", low=0)
    source_tolerance = _num(acceptance.get("maximum_source_peak_change_c", tolerance),
                            "Source peak maximum change (°C)", low=0)
    phase_offset = acceptance.get("phase_offset_fraction")
    if phase_offset is not None:
        if (not isinstance(phase_offset, (list, tuple)) or len(phase_offset) != 2 or
                all(_num(value, "Mesh phase offset", low=-.5, high=.5) == 0
                    for value in phase_offset)):
            raise ValueError("phase_offset_fraction needs a nonzero offset within ±0.5.")
    minimum_cells = acceptance.get("minimum_source_cells", 4)
    if isinstance(minimum_cells, bool) or not isinstance(minimum_cells, int) or minimum_cells < 1:
        raise ValueError("minimum_source_cells must be a positive integer.")
    solves = []
    for grid in grids:
        selected = dict(settings)
        selected["grid_cells_long_axis"] = grid
        def stage_progress(stage, completed, total, elapsed, eta):
            if progress:
                progress(f"grid {grid}: {stage}", completed, total, elapsed, eta)
        solves.append(solve_multilayer_thermal(geometry, view, result, selected,
                                                progress=stage_progress))
    coarse, fine = solves[-2:]
    coarse_parts = {part["reference"]: part for part in coarse["components"]}
    changes = {}
    source_peak_changes = {}
    underresolved = []
    source_resolution = {}

    def part_temperature(part):
        return (part["junction_c"] if part["junction_c"] is not None else
                part["sink_c"] if part["sink_c"] is not None else part["board_site_c"])

    for part in fine["components"]:
        ref = part["reference"]
        changes[ref] = abs(part_temperature(part)-part_temperature(coarse_parts[ref]))
        if part["heat_path"] == "board":
            source_peak_changes[ref] = abs(part["source_peak_c"]-
                                           coarse_parts[ref]["source_peak_c"])
            effective = part["effective_source_cells"]
            source_resolution[ref] = {
                "overlapped_cells": part["source_cells"],
                "effective_cells": effective,
                "contact_area_mm2": part["source_contact_area_mm2"],
                "distribution": part["source_distribution"],
            }
            if effective < minimum_cells:
                underresolved.append(ref)
    worst = max(changes.values(), default=0)
    def compare_fields(previous_solve, current_solve):
        previous_layers = {layer["id"]: layer for layer in previous_solve["layers"]}
        peaks, differences, unmatched = {}, [], 0
        for layer in current_solve["layers"]:
            previous = previous_layers[layer["id"]]
            peaks[layer["name"]] = abs(layer["sampled_max_c"]-
                                        previous["sampled_max_c"])
            x_edges, y_edges = layer["x_edges_mm"], layer["y_edges_mm"]
            for j, y in enumerate(previous["y_centers_mm"]):
                fj = bisect_right(y_edges, y)-1
                for i, x in enumerate(previous["x_centers_mm"]):
                    old = previous["values_c"][j][i]
                    if old is None:
                        continue
                    fi = bisect_right(x_edges, x)-1
                    if not 0 <= fi < len(x_edges)-1 or not 0 <= fj < len(y_edges)-1:
                        unmatched += 1
                        continue
                    new = layer["values_c"][fj][fi]
                    if new is None:
                        unmatched += 1
                    else:
                        differences.append(abs(old-new))
        return peaks, max(differences, default=0), unmatched

    layer_peak_changes, worst_field, unmatched_field_cells = compare_fields(coarse, fine)
    worst_layer = max(layer_peak_changes.values(), default=0)
    worst_source = max(source_peak_changes.values(), default=0)
    drill_center_peaks = (["layer:"+layer["name"] for layer in fine["layers"]
                           if layer["sampled_max_cell"]["center_in_drill_id"]] +
                          ["source:"+part["reference"] for part in fine["components"]
                           if part.get("source_peak_cell") and
                           part["source_peak_cell"]["center_in_drill_id"]])
    unresolved_contacts = [part["reference"] for part in fine["components"]
                           if part.get("source_distribution") ==
                           "saved_pad_copper_polygon_unresolved_annulus_proxy"]
    phase_result = {"status": "NOT_RUN", "offset_fraction": None}
    if phase_offset is not None:
        shifted_settings = dict(settings)
        shifted_settings["grid_cells_long_axis"] = grids[-1]
        shifted_settings["grid_phase_fraction"] = list(phase_offset)
        shifted = solve_multilayer_thermal(
            geometry, view, result, shifted_settings,
            progress=(lambda stage, completed, total, elapsed, eta:
                      progress(f"grid {grids[-1]} phase: {stage}", completed,
                               total, elapsed, eta)) if progress else None)
        shifted_parts = {part["reference"]: part for part in shifted["components"]}
        component_delta = max(abs(part_temperature(part)-
                                  part_temperature(shifted_parts[part["reference"]]))
                              for part in fine["components"])
        source_delta = max((abs(part["source_peak_c"]-
                                shifted_parts[part["reference"]]["source_peak_c"])
                            for part in fine["components"] if part["heat_path"] == "board"),
                           default=0)
        shifted_peaks, field_delta, unmatched_shifted = compare_fields(fine, shifted)
        layer_delta = max(shifted_peaks.values(), default=0)
        phase_pass = (shifted["status"] == "converged" and not unmatched_shifted and
                      component_delta <= tolerance and source_delta <= source_tolerance and
                      layer_delta <= layer_tolerance and field_delta <= field_tolerance)
        phase_result = {"status": "PASS" if phase_pass else "FAIL",
                        "offset_fraction": list(phase_offset),
                        "maximum_component_change_c": component_delta,
                        "maximum_source_peak_change_c": source_delta,
                        "maximum_layer_peak_change_c": layer_delta,
                        "maximum_field_change_c": field_delta,
                        "unmatched_field_cells": unmatched_shifted}
    passed = (all(solve["status"] == "converged" for solve in solves) and
              not underresolved and not drill_center_peaks and
              not unresolved_contacts and
              fine["mesh"]["unresolved_barrel_stencils"] == 0 and
              not unmatched_field_cells and
              worst <= tolerance and worst_layer <= layer_tolerance and
              worst_field <= field_tolerance and worst_source <= source_tolerance and
              phase_result["status"] != "FAIL")
    fine["mesh_acceptance"] = {
        "status": "PASS" if passed else "FAIL",
        "grid_cells_long_axis": grids, "maximum_change_c": worst,
        "allowed_change_c": tolerance,
        "component_changes_c": changes,
        "layer_peak_changes_c": layer_peak_changes,
        "maximum_layer_peak_change_c": worst_layer,
        "allowed_layer_peak_change_c": layer_tolerance,
        "source_peak_changes_c": source_peak_changes,
        "maximum_source_peak_change_c": worst_source,
        "allowed_source_peak_change_c": source_tolerance,
        "maximum_field_change_c": worst_field,
        "allowed_field_change_c": field_tolerance,
        "unmatched_field_cells": unmatched_field_cells,
        "field_comparison": "coarse cell centers sampled from the finest-grid containing cell",
        "phase_sensitivity": phase_result,
        "minimum_source_cells": minimum_cells,
        "underresolved_sources": underresolved,
        "drill_center_peaks": drill_center_peaks,
        "unresolved_contact_sources": unresolved_contacts,
        "unresolved_barrel_stencils": fine["mesh"]["unresolved_barrel_stencils"],
        "source_resolution": source_resolution,
        "source_sha256": geometry.get("source_sha256"),
        "note": "Cell count means overlap-area-equivalent cells, not cells touched. Contact spreading and source-shape fidelity remain unresolved.",
    }
    return fine


def _loss_number(value, name, *, positive=False):
    if isinstance(value, bool):
        raise ValueError(name + ' must be finite and numeric.')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(name + ' must be finite and numeric.') from exc
    if not math.isfinite(value) or value < 0 or positive and value == 0:
        raise ValueError(name + ' is outside its finite physical range.')
    return value


def _loss_area(ring):
    if len(ring) < 3:
        return 0.
    x, y = ring[0]
    return abs(math.fsum((a[0]-x)*(b[1]-y)-(b[0]-x)*(a[1]-y)
                        for a,b in zip(ring,ring[1:]+ring[:1])))/2


def _loss_clip(subject, convex):
    """Exact straight-edge clipping; clip polygon must be counter-clockwise."""
    result = list(subject)
    for a,b in zip(convex,convex[1:]+convex[:1]):
        if not result:
            break
        previous = result[-1]
        def side(p):
            return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
        old, result = result, []
        fp = side(previous)
        for current in old:
            fc = side(current)
            if (fp >= 0) != (fc >= 0):
                fraction = fp/(fp-fc)
                result.append((previous[0]+fraction*(current[0]-previous[0]),
                               previous[1]+fraction*(current[1]-previous[1])))
            if fc >= 0:
                result.append(current)
            previous, fp = current, fc
    return result


def _loss_polygon(raw, identifier):
    if not isinstance(raw, (list,tuple)) or not 3 <= len(raw) <= 1024:
        raise ValueError(identifier + ': polygon_mm requires 3 to 1024 convex XY vertices.')
    ring = []
    for point in raw:
        if not isinstance(point, (list,tuple)) or len(point) != 2 or any(isinstance(v,bool) for v in point):
            raise ValueError(identifier + ': polygon_mm requires finite XY coordinates.')
        try:
            xy = tuple(float(v) for v in point)
        except (TypeError,ValueError,OverflowError) as exc:
            raise ValueError(identifier + ': polygon_mm requires finite XY coordinates.') from exc
        if not all(math.isfinite(v) for v in xy):
            raise ValueError(identifier + ': polygon_mm requires finite XY coordinates.')
        ring.append(xy)
    if ring[0] == ring[-1]:
        ring.pop()
    if len(set(ring)) != len(ring) or _loss_area(ring) <= 1e-16:
        raise ValueError(identifier + ': loss polygon is repeated or degenerate.')
    x,y = ring[0]
    signed = math.fsum((a[0]-x)*(b[1]-y)-(b[0]-x)*(a[1]-y) for a,b in zip(ring,ring[1:]+ring[:1]))
    if signed < 0:
        ring.reverse()
    # Every vertex must lie to the left of every directed edge. This also
    # rejects self-crossing star orderings that a turn-only test would accept.
    for a,b in zip(ring,ring[1:]+ring[:1]):
        if any((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]) < -max(1e-24,_loss_area(ring)*1e-10) for p in ring):
            raise ValueError(identifier + ': loss polygon must be convex and non-self-intersecting.')
    return ring


def _loss_overlaps_drill(ring, drill):
    """Analytical segment-to-polygon distance for circular/rotated slot voids."""
    dx,dy = drill_dimensions(drill)
    angle = -math.radians(float(drill.get('drill_angle_deg',0))) + (math.pi/2 if dy > dx else 0)
    run = abs(dx-dy)/2
    direction = (run*math.cos(angle),run*math.sin(angle))
    a = (drill['x_mm']-direction[0],drill['y_mm']-direction[1])
    b = (drill['x_mm']+direction[0],drill['y_mm']+direction[1])
    if _inside(a,ring) or _inside(b,ring) or any(_segments_cross(a,b,c,d) for c,d in zip(ring,ring[1:]+ring[:1])):
        return True
    def distance(p,c,d):
        vx,vy = d[0]-c[0],d[1]-c[1]
        norm = vx*vx+vy*vy
        t = min(1.,max(0.,((p[0]-c[0])*vx+(p[1]-c[1])*vy)/norm)) if norm else 0.
        return math.hypot(p[0]-c[0]-t*vx,p[1]-c[1]-t*vy)
    minimum = min([distance(p,a,b) for p in ring]+
                  [distance(p,c,d) for p in (a,b) for c,d in zip(ring,ring[1:]+ring[:1])])
    return minimum < min(dx,dy)/2-1e-10


def _map_copper_losses(raw, geometry, layers, cells, x_edges, y_edges, barrel_stencils=None):
    """Retain integrated watts; incomplete physical support is an error."""
    from .thermal_mesh import board_tiles
    if not isinstance(raw,list):
        raise ValueError('copper_loss_sources must be a list of reviewed loss records.')
    if not raw:
        return []
    layer_indices = {row['id']:i for i,row in enumerate(layers)}
    planar_keys = {'id','layer_id','polygon_mm','power_w'}
    via_keys = {'id','barrel_id','top_layer','bottom_layer','power_w'}
    seen = set(); output = []; tile_cache = {}
    board_faces = None
    indices = {cell:index for index,cell in enumerate(cells)}
    holes = [h for h in [*geometry.get('barrels',[]),*geometry.get('mounting_holes',[])]
             if h.get('drill_mm') or h.get('drill_size_mm')]
    def faces_for(key):
        nonlocal board_faces
        if key is None:
            if board_faces is None:
                board_faces = [(face,_ring_bounds(face)) for face in board_tiles({'outline':geometry['outline']})]
            return board_faces
        if key not in tile_cache:
            polygons = layers[layer_indices[key]].get('polygons_mm',[])
            tile_cache[key] = [(face,_ring_bounds(face)) for face in board_tiles({'outline':[
                {'outer_mm':p['outer'],'holes_mm':p.get('holes',[])} for p in polygons]})]
        return tile_cache[key]
    for record in raw:
        if not isinstance(record,Mapping) or set(record) not in (planar_keys,via_keys):
            raise ValueError('Copper loss records require explicit planar polygon/layer or adjacent barrel-segment fields.')
        identifier = record['id']
        if not isinstance(identifier,str) or not identifier.startswith('copper:') or len(identifier) <= 7 or identifier in seen:
            raise ValueError('Copper loss IDs must be unique and prefixed copper:.')
        seen.add(identifier)
        power = _loss_number(record['power_w'],identifier+' power_w')
        if 'barrel_id' in record:
            if not isinstance(record['barrel_id'],str):
                raise ValueError(identifier+': barrel_id must be a saved identity.')
            top,bottom = record['top_layer'],record['bottom_layer']
            if any(isinstance(lid,bool) or not isinstance(lid,(str,int)) or lid not in layer_indices for lid in (top,bottom)):
                raise ValueError(identifier+': unknown via layer.')
            mapping = (barrel_stencils or {}).get((record['barrel_id'],top,bottom))
            if mapping is None or not mapping['verified']:
                raise ValueError(identifier+': no resolved barrel contact stencil with saved land coverage; refine the grid or review flashed lands.')
            weights = mapping['nodes']
            output.append(dict(record,power_w=power,nodes=weights,mapped_power_w=power*math.fsum(w for _,w in weights),
                               coverage_fraction=1.,mapping='retained_barrel_contact_stencil_uniform_axial'))
            continue
        layer = record['layer_id']
        if isinstance(layer,bool) or not isinstance(layer,(str,int)) or layer not in layer_indices:
            raise ValueError(identifier+': unknown copper layer_id.')
        ring = _loss_polygon(record['polygon_mm'],identifier)
        area = _loss_area(ring); bound = _ring_bounds(ring)
        tolerance = max(1e-24,area*1e-8)
        for kind in (None,layer):
            overlap = math.fsum(_loss_area(_loss_clip(face,ring)) for face,bbox in faces_for(kind)
                               if bbox[0] < bound[2] and bbox[2] > bound[0] and bbox[1] < bound[3] and bbox[3] > bound[1])
            if abs(overlap-area) > tolerance:
                raise ValueError(identifier+': loss polygon is not fully supported by saved board/copper material; clipped loss cannot be renormalized.')
        for hole in holes:
            if hole.get('span_layers') and layer not in hole['span_layers']:
                continue
            if _loss_overlaps_drill(ring,hole):
                raise ValueError(identifier+': loss polygon intersects a drill void; provide actual copper-only support.')
        hits = []
        for j in range(max(0,bisect_right(y_edges,bound[1])-1),min(len(y_edges)-1,bisect_right(y_edges,bound[3]))):
            for i in range(max(0,bisect_right(x_edges,bound[0])-1),min(len(x_edges)-1,bisect_right(x_edges,bound[2]))):
                ci = indices.get((i,j))
                if ci is None:
                    continue
                amount = _loss_area(_clip_ring_to_cell(ring,x_edges[i],y_edges[j],x_edges[i+1],y_edges[j+1]))
                if amount <= 0:
                    continue
                center = ((x_edges[i]+x_edges[i+1])/2,(y_edges[j]+y_edges[j+1])/2)
                if _drill_at(center,layer,geometry) is not None:
                    raise ValueError(identifier+': mapped cell center lies in a drill void; refine the thermal grid.')
                hits.append((layer_indices[layer]*len(cells)+ci,amount))
        mapped_area = math.fsum(amount for _,amount in hits)
        if not hits or abs(mapped_area-area) > tolerance:
            raise ValueError(identifier+': unresolved thermal cell coverage; refine the grid instead of dropping heat.')
        weights = [(ni,amount/mapped_area) for ni,amount in hits]
        output.append(dict(id=identifier,layer_id=layer,polygon_mm=ring,power_w=power,nodes=weights,
                           mapped_power_w=power*math.fsum(w for _,w in weights),area_mm2=area,
                           mapped_area_mm2=mapped_area,coverage_fraction=mapped_area/area,
                           mapping='exact_polygon_overlap'))
    return output
