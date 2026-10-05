"""Layer-resolved, steady-state finite-volume board thermal screen.

All dimensions in the public geometry are millimetres. Thermal calculations
use metres, watts, and kelvins. This is a bounded 2.5D screen, not CFD or a
package/fixture contact model. Only explicitly selected mounts are sinks.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from .thermal_board_view import _inside


SIGMA = 5.670374419e-8


def _num(value, name, *, low=None, high=None):
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number.") from exc
    if not math.isfinite(n) or (low is not None and n < low) or (high is not None and n > high):
        raise ValueError(f"{name} is outside its allowed range.")
    return n


def _board_contains(point, outlines):
    return any(_inside(point, shape["outer_mm"]) and
               not any(_inside(point, hole) for hole in shape.get("holes_mm", []))
               for shape in outlines)


def _polygon_contains(point, polygon):
    return (_inside(point, polygon["outer"]) and
            not any(_inside(point, hole) for hole in polygon.get("holes", [])))


def _source_weights(component, cells, xs, ys, dx_mm, dy_mm):
    """Overlap-weighted footprint bbox, or labelled point fallback."""
    bounds = component.get("bbox_mm")
    if bounds is None:
        pos = component["position_mm"]
        nearest = min(range(len(cells)), key=lambda n:
                      (xs[cells[n][0]]-pos[0])**2 + (ys[cells[n][1]]-pos[1])**2)
        return [(nearest, 1.0)], "point_fallback"
    if len(bounds) != 4:
        raise ValueError(f"{component['reference']}: footprint bbox_mm needs four coordinates.")
    x0, y0, x1, y1 = [_num(v, "Footprint bound") for v in bounds]
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"{component['reference']}: invalid footprint bounding box.")
    hits = []
    for index, (i, j) in enumerate(cells):
        x, y = xs[i], ys[j]
        area = max(0, min(x1, x+dx_mm/2)-max(x0, x-dx_mm/2)) * \
               max(0, min(y1, y+dy_mm/2)-max(y0, y-dy_mm/2))
        if area > 0:
            hits.append((index, area))
    total = math.fsum(v for _, v in hits)
    if total <= 0:
        raise ValueError(f"{component['reference']}: footprint does not overlap the board grid.")
    return [(index, area/total) for index, area in hits], "footprint_bbox_proxy"


def solve_multilayer_thermal(geometry, view, result, settings):
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
    if environment not in ("air", "vacuum"):
        raise ValueError("QuickTherm environment must be air or vacuum.")
    airflow = _num(settings.get("board_airflow_m_s", 0), "Airflow (m/s)", low=0)
    if environment == "vacuum" and airflow:
        raise ValueError("Airflow must be zero in vacuum.")
    h = _num(settings.get("board_h_w_m2k", 5+4*airflow if environment == "air" else 0),
             "Board convection coefficient (W/m²/K)", low=0)
    if environment == "vacuum" and h:
        raise ValueError("Convection must be zero in vacuum.")
    grid_n = settings.get("grid_cells_long_axis", 48)
    if isinstance(grid_n, bool) or not isinstance(grid_n, int) or not 24 <= grid_n <= 80:
        raise ValueError("grid_cells_long_axis must be an integer from 24 to 80.")
    blur = _num(settings.get("copper_blur_cells", 0), "Copper supersampling", low=0, high=1)
    if blur not in (0, .5, 1):
        raise ValueError("copper_blur_cells supports 0, 0.5 or 1.")
    xmin, ymin, xmax, ymax = [_num(v, "Board bound") for v in geometry["bbox_mm"]]
    width, height = xmax-xmin, ymax-ymin
    if width <= 0 or height <= 0:
        raise ValueError("Board bounding box must have positive width and height.")
    nx = max(2, round(grid_n*width/max(width, height)))
    ny = max(2, round(grid_n*height/max(width, height)))
    dx_mm, dy_mm = width/nx, height/ny
    dx, dy = dx_mm/1000, dy_mm/1000
    xs = [xmin+(i+.5)*dx_mm for i in range(nx)]
    ys = [ymin+(j+.5)*dy_mm for j in range(ny)]
    cells = [(i, j) for j, y in enumerate(ys) for i, x in enumerate(xs)
             if _board_contains((x, y), geometry["outline"])]
    if not cells:
        raise ValueError("Thermal grid does not intersect the verified board outline.")
    ncell = len(cells)
    sink_parts = [part for part in result.get("components", []) if part.get("heat_path") == "heatsink"]
    nboard = ncell*len(layers)
    nnode = nboard+len(sink_parts)
    if nnode > 150000:
        raise ValueError("Thermal grid exceeds 150,000 layer cells; reduce resolution.")
    by_cell = {cell: index for index, cell in enumerate(cells)}
    node = lambda layer_index, cell_index: layer_index*ncell+cell_index
    cell_area = dx*dy
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
    for layer in layers:
        polygons = layer.get("polygons_mm", [])
        bounds = []
        for polygon in polygons:
            outer = polygon["outer"]
            bounds.append((min(p[0] for p in outer), min(p[1] for p in outer),
                           max(p[0] for p in outer), max(p[1] for p in outer)))
        layer_members = []
        for i, j in cells:
            if blur == 1:
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
                fraction = sum(_polygon_contains(point, polygon) for point in probes)/len(probes)
                if fraction:
                    weights[poly_index] = fraction
            layer_members.append(weights)
        memberships.append(layer_members)
    edges = []
    copper_edges = 0
    def add_edge(a, b, g):
        if g > 0:
            edges.append((a, b, g))
    for li, layer in enumerate(layers):
        polygons = layer.get("polygons_mm", [])
        for ci, (i, j) in enumerate(cells):
            for key, length, run, face in (
                ((i+1, j), dy, dx, (xs[i]+dx_mm/2, ys[j])),
                ((i, j+1), dx, dy, (xs[i], ys[j]+dy_mm/2))):
                cj = by_cell.get(key)
                if cj is None:
                    continue
                base = dielectric_k*slice_thickness[li]*length/run
                common = memberships[li][ci].keys() & memberships[li][cj].keys()
                copper_fraction = max((min(memberships[li][ci][p], memberships[li][cj][p])
                                       for p in common if _polygon_contains(face, polygons[p])), default=0)
                bonus = copper_k*(thickness[li]/1000)*length/run*copper_fraction
                if bonus:
                    copper_edges += 1
                add_edge(node(li, ci), node(li, cj), base+bonus)
    for li, gap in enumerate(intervals):
        conductance = dielectric_k*cell_area/gap
        for ci in range(ncell):
            add_edge(node(li, ci), node(li+1, ci), conductance)
    layer_ids = {row["id"]: i for i, row in enumerate(layers)}
    via_edges = 0
    for via in geometry.get("barrels", []):
        span = [layer_ids[lid] for lid in via.get("span_layers", []) if lid in layer_ids]
        if len(span) < 2:
            continue
        span.sort()
        drill = _num(via["drill_mm"], "Barrel drill (mm)", low=1e-9)
        if plating*2 >= drill:
            raise ValueError(f"{via['id']}: plating thickness is implausible for its drill.")
        barrel_area = math.pi*((drill+2*plating)**2-drill**2)/4/1e6
        x, y = float(via["x_mm"]), float(via["y_mm"])
        ci = min(range(ncell), key=lambda ci: (xs[cells[ci][0]]-x)**2+(ys[cells[ci][1]]-y)**2)
        if abs(xs[cells[ci][0]]-x)>dx_mm or abs(ys[cells[ci][1]]-y)>dy_mm:
            continue
        for a, b in zip(span, span[1:]):
            if b != a+1:
                raise ValueError(f"{via['id']}: barrel span is not continuous through the stackup.")
            add_edge(node(a, ci), node(b, ci), copper_k*barrel_area/((z[b]-z[a])/1000))
            via_edges += 1
    sources = np.zeros(nnode, dtype=float)
    view_refs = {row["reference"]: row for row in view.get("components", [])}
    output_components = []
    source_sites = {}
    sink_nodes = {}
    sink_areas = settings.get("sink_exposed_area_mm2", {})
    sink_to_board = settings.get("sink_to_board_k_per_w", {})
    sink_resistances = settings.get("component_to_sink_k_per_w", {})
    board_resistances = settings.get("component_to_board_k_per_w", {})
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
            if sink_h == 0 and sink_e == 0 and ref not in sink_to_board:
                raise ValueError(f"{ref}: sink has no heat rejection path.")
            ni = nboard+len(sink_nodes)
            sink_nodes[ref] = (ni, area, sink_e)
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
        weights, distribution = _source_weights(component, cells, xs, ys, dx_mm, dy_mm)
        li = 0 if component.get("side", "top").lower() == "top" else len(layers)-1
        for ci, weight in weights:
            sources[node(li, ci)] += power*weight
        source_sites[ref] = (li, weights)
        output_components.append({"reference": ref, "power_w": power, "side": component.get("side", "top"),
                                  "heat_path": "board", "sink_c": None,
                                  "source_distribution": distribution,
                                  "source_cells": len(weights), "board_site_c": None,
                                  "junction_c": None})
    if not output_components:
        raise ValueError("No mapped QuickTherm component power is available.")
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
        surface_area[node(0, ci)] += cell_area
        surface_area[node(len(layers)-1, ci)] += cell_area
    for ref, (ni, area, sink_e) in sink_nodes.items():
        surface_area[ni] = area
        convection_h[ni] = sink_h
        surface_e[ni] = sink_e
    _, graph_labels = connected_components(laplacian, directed=False)
    unexcited_anchors = 0
    for label in set(int(value) for value in graph_labels):
        indices = np.flatnonzero(graph_labels == label)
        has_rejection = (bool(np.any(surface_area[indices]*(convection_h[indices]+surface_e[indices])))
                         or bool(np.any(contact_g[indices]))
                         or any(int(index) in fixed for index in indices))
        if not has_rejection:
            if np.any(sources[indices]):
                raise ValueError("A powered thermal region has no convection, radiation or fixture path.")
            fixed[int(indices[0])] = ambient
            unexcited_anchors += 1
    free = np.asarray([i for i in range(nnode) if i not in fixed], dtype=int)
    fixed_ids = np.asarray(sorted(fixed), dtype=int)
    temp = np.full(nnode, ambient, dtype=float)
    for ni, value in fixed.items():
        temp[ni] = value
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
    for part in output_components:
        if part["heat_path"] == "heatsink":
            ni, _, _ = sink_nodes[part["reference"]]
            part["sink_c"] = float(temp[ni])
            if part["reference"] in sink_resistances:
                r = _num(sink_resistances[part["reference"]],
                         "Component-to-sink resistance (K/W)", low=0)
                part["junction_c"] = part["sink_c"]+part["power_w"]*r
            continue
        li, weights = source_sites[part["reference"]]
        part["board_site_c"] = math.fsum(float(temp[node(li, ci)])*weight for ci, weight in weights)
        if part["reference"] in board_resistances:
            r = _num(board_resistances[part["reference"]], "Component-to-board resistance (K/W)", low=0)
            part["junction_c"] = part["board_site_c"]+part["power_w"]*r
    kelvin = temp+273.15
    conv_terms = surface_area*convection_h*(temp-ambient)
    rad_terms = surface_area*surface_e*SIGMA*(kelvin**4-(ambient+273.15)**4)
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
        fields.append({"id": layer["id"], "name": layer["name"], "z_mm": z[li],
                       "x_centers_mm": xs, "y_centers_mm": ys, "values_c": values,
                       "sampled_min_c": float(np.min(slab)), "sampled_max_c": float(np.max(slab))})
    return {"model": "steady-state layer-resolved finite-volume board screen",
            "status": "converged" if abs(residual) <= tolerance else "imbalanced",
            "environment": environment, "ambient_c": ambient, "layers": fields,
            "components": output_components, "mounts": mounts,
            "heat_balance": {"input_w": input_w, "convection_w": convection,
                             "radiation_w": radiation, "mount_flux_w": mount_flux,
                             "board_convection_w": float(np.sum(conv_terms[:nboard])),
                             "board_radiation_w": float(np.sum(rad_terms[:nboard])),
                             "sink_convection_w": float(np.sum(conv_terms[nboard:])),
                             "sink_radiation_w": float(np.sum(rad_terms[nboard:])),
                             "residual_w": residual,
                             "relative_residual": abs(residual)/max(abs(input_w), 1e-12),
                             "tolerance_w": tolerance},
            "settings": {"dielectric_k_w_mk": dielectric_k, "copper_k_w_mk": copper_k,
                         "via_plating_mm": plating, "grid_cells_long_axis": grid_n,
                         "copper_blur_cells": blur, "board_h_w_m2k": h,
                         "board_emissivity": emissivity, "sink_h_w_m2k": sink_h},
            "mesh": {"nx": nx, "ny": ny, "active_cells_per_layer": ncell,
                     "solver_iterations": iterations, "copper_lateral_edges": copper_edges,
                     "via_vertical_edges": via_edges,
                     "unexcited_regions_anchored_at_ambient": unexcited_anchors},
            "assumptions": [
                "Copper occupancy is sampled per cell; lateral copper coupling requires the same filled polygon at the shared face.",
                "Dielectric is homogeneous and isotropic between copper midplanes; no anisotropic laminate data are inferred.",
                "Via plating thickness, material conductivity and fixture contacts are explicit user inputs.",
                "Barrel heat flow is a 1D axial approximation; individual land-to-barrel contact and package-pad spreading are unresolved.",
                "An explicitly declared NPTH mechanical contact couples to the nearest dielectric cell through entered contact resistance; no copper-plane contact is inferred.",
                "Only top and bottom faces reject heat; edge radiation, package shadows, view factors, airflow fields and spatial transients are unresolved.",
                "Sources use footprint bounding boxes as contact proxies, or a labelled point fallback; junction temperature needs explicit component-to-board resistance.",
                "Virtual heatsink nodes use entered exposed area and component-to-sink resistance; they couple to the board only if an explicit sink-to-board resistance is supplied.",
                "An unpowered region with no thermal boundary is anchored at ambient only to make its otherwise undefined temperature displayable.",
                "A zero residual is numerical energy balance, not validation of material, boundary or contact assumptions.",
            ]}


def solve_multilayer_thermal_convergence(geometry, view, result, settings, acceptance):
    """Repeat the saved-source steady solve and report mesh acceptance.

    This is a global-grid convergence gate, not a locally adaptive mesh or a
    source-contact qualification. It deliberately returns FAIL when the finest
    two meshes disagree or a footprint source occupies too few grid cells.
    """
    if not isinstance(acceptance, Mapping):
        raise ValueError("mesh_acceptance must be a mapping.")
    grids = acceptance.get("grid_cells_long_axis", [24, 48, 80])
    if (not isinstance(grids, list) or len(grids) < 2 or
            any(isinstance(n, bool) or not isinstance(n, int) or not 24 <= n <= 80
                for n in grids) or grids != sorted(set(grids))):
        raise ValueError("Mesh acceptance needs two or more increasing grid sizes from 24 to 80.")
    tolerance = _num(acceptance.get("maximum_change_c"), "Mesh maximum change (°C)", low=0)
    minimum_cells = acceptance.get("minimum_source_cells", 4)
    if isinstance(minimum_cells, bool) or not isinstance(minimum_cells, int) or minimum_cells < 1:
        raise ValueError("minimum_source_cells must be a positive integer.")
    solves = []
    for grid in grids:
        selected = dict(settings)
        selected["grid_cells_long_axis"] = grid
        solves.append(solve_multilayer_thermal(geometry, view, result, selected))
    coarse, fine = solves[-2:]
    coarse_parts = {part["reference"]: part for part in coarse["components"]}
    changes = {}
    underresolved = []
    for part in fine["components"]:
        ref = part["reference"]
        key = "junction_c" if part["junction_c"] is not None else (
            "sink_c" if part["sink_c"] is not None else "board_site_c")
        changes[ref] = abs(part[key]-coarse_parts[ref][key])
        if part.get("source_cells", minimum_cells) < minimum_cells:
            underresolved.append(ref)
    worst = max(changes.values(), default=0)
    passed = (all(solve["status"] == "converged" for solve in solves) and
              not underresolved and worst <= tolerance)
    fine["mesh_acceptance"] = {
        "status": "PASS" if passed else "FAIL",
        "grid_cells_long_axis": grids, "maximum_change_c": worst,
        "allowed_change_c": tolerance,
        "component_changes_c": changes,
        "minimum_source_cells": minimum_cells,
        "underresolved_sources": underresolved,
        "source_sha256": geometry.get("source_sha256"),
        "note": "Global-grid and footprint-cell screen only; local contact spreading remains unresolved.",
    }
    return fine
