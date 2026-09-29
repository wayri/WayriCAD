"""Bounded, steady-state PCB thermal network for QuickTherm.

This is a thin-sheet, lateral-conduction screen with local convection and
radiation to a prescribed ambient. It is not CFD, a multilayer thermal model,
or a replacement for measured package-to-board thermal resistance.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from .thermal_board_view import _inside


_SIGMA = 5.670374419e-8  # W/(m² K⁴)


def _number(value, name, *, positive=False, minimum=None):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number.") from exc
    if not math.isfinite(number) or (positive and number <= 0) or (minimum is not None and number < minimum):
        raise ValueError(f"{name} is outside its allowed range.")
    return number


def _inside_board(point, outlines):
    return any(_inside(point, shape["outer_mm"]) and
               not any(_inside(point, hole) for hole in shape.get("holes_mm", []))
               for shape in outlines)


def _heat_loss(temp_c, ambient_c, area_m2, h, emissivity):
    return area_m2 * (h * (temp_c - ambient_c) + emissivity * _SIGMA *
                      ((temp_c + 273.15) ** 4 - (ambient_c + 273.15) ** 4))


def _radiation_slope(temp_c, area_m2, emissivity):
    return 4 * area_m2 * emissivity * _SIGMA * (temp_c + 273.15) ** 3


def _sink_temperature(power_w, ambient_c, area_m2, h, emissivity):
    if power_w == 0:
        return ambient_c
    lo = ambient_c
    hi = ambient_c + 1
    while _heat_loss(hi, ambient_c, area_m2, h, emissivity) < power_w:
        hi = ambient_c + 2 * (hi - ambient_c)
        if hi > 10000:
            raise ValueError("Sink solution exceeds 10000 °C; check exposed area and power.")
    for _ in range(65):
        mid = (lo + hi) / 2
        if _heat_loss(mid, ambient_c, area_m2, h, emissivity) < power_w:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _optional_resistance(settings, key, reference):
    mapping = settings.get(key, {})
    if not isinstance(mapping, Mapping):
        raise ValueError(f"{key} must map references to thermal resistances.")
    if reference not in mapping:
        return None
    return _number(mapping[reference], f"{reference} {key}", minimum=0)


def _source_cells(component, cells, xs, ys, dx_mm, dy_mm):
    """Return normalized cell weights for the footprint's axis-aligned bounds.

    Bounds are a geometric contact proxy, not copper-pad contact geometry.
    Missing bounds use a point source. Valid bounds that do not overlap the
    active board mesh are an error, since silently falling back would hide a
    footprint/outline mismatch.
    """
    bounds = component.get("bbox_mm")
    if bounds is None:
        position = component["position_mm"]
        nearest = min(range(len(cells)), key=lambda index:
                      (xs[cells[index][0]] - position[0]) ** 2 +
                      (ys[cells[index][1]] - position[1]) ** 2)
        return [(nearest, 1.0)], "point_fallback", None
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError(f"{component['reference']}: footprint bbox_mm must contain four millimetre coordinates.")
    x0, y0, x1, y1 = [_number(value, f"{component['reference']} footprint bound") for value in bounds]
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"{component['reference']}: footprint bounding box has zero or negative area.")
    overlaps = []
    for index, (i, j) in enumerate(cells):
        cx, cy = xs[i], ys[j]
        overlap_x = max(0.0, min(x1, cx + dx_mm / 2) - max(x0, cx - dx_mm / 2))
        overlap_y = max(0.0, min(y1, cy + dy_mm / 2) - max(y0, cy - dy_mm / 2))
        overlap = overlap_x * overlap_y
        if overlap > 0:
            overlaps.append((index, overlap))
    total = math.fsum(area for _, area in overlaps)
    if total <= 0:
        raise ValueError(f"{component['reference']}: footprint bounding box does not overlap active board cells.")
    return [(index, area / total) for index, area in overlaps], "footprint_bbox_proxy", total


def _solve_board_sparse(neighbors, sources, ambient, area, h, emissivity):
    """Newton solve of the conservative finite-volume sheet network."""
    try:
        import numpy as np
        from scipy.sparse import csr_matrix, diags
        from scipy.sparse.linalg import spsolve
    except ImportError as exc:
        raise RuntimeError("High-density QuickTherm mesh needs NumPy and SciPy in the KiCad Python runtime.") from exc
    count = len(sources)
    if not any(sources):
        return [ambient] * count, 0
    rows, cols, values = [], [], []
    for index, edges in enumerate(neighbors):
        rows.append(index)
        cols.append(index)
        values.append(math.fsum(g for _, g in edges))
        for other, conductance in edges:
            rows.append(index)
            cols.append(other)
            values.append(-conductance)
    laplacian = csr_matrix((values, (rows, cols)), shape=(count, count))
    source_vector = np.asarray(sources, dtype=float)
    temp = np.full(count, ambient, dtype=float)
    for iteration in range(35):
        kelvin = temp + 273.15
        loss = area * (h * (temp - ambient) + emissivity * _SIGMA *
                       (kelvin ** 4 - (ambient + 273.15) ** 4))
        slope = area * (h + 4 * emissivity * _SIGMA * kelvin ** 3)
        matrix = laplacian + diags(slope, format="csr")
        candidate = spsolve(matrix, source_vector + slope * temp - loss)
        if not np.all(np.isfinite(candidate)) or np.max(candidate) > 10000 or np.min(candidate) < -273.15:
            raise ValueError("Thermal network diverged; inspect units, power, and heat rejection.")
        change = float(np.max(np.abs(candidate - temp)))
        temp = candidate
        if change <= 1e-7:
            return temp.tolist(), iteration + 1
    raise ValueError("Thermal network did not converge; check power, emissivity, and convection inputs.")


def solve_thermal_network(view, quick_therm_result, settings):
    """Solve board midplane and optional virtual-sink temperatures.

    ``view`` is the JSON-safe output of ``build_board_thermal_view``. ``settings``
    specifies material, geometric and ambient-transfer assumptions explicitly.
    Legacy RθJA values in ``quick_therm_result`` are *not* reused as junction-to-
    board resistance. A junction estimate is emitted only when a new explicit
    component-to-board/sink resistance is supplied.
    """
    if not isinstance(settings, Mapping):
        raise ValueError("Thermal network settings must be a mapping.")
    outlines = view.get("outline", [])
    if view.get("outline_status") != "valid" or not outlines or view.get("bbox_status") != "verified_outline":
        raise ValueError("A verified, closed Edge.Cuts outline is required for board thermal calculation.")
    ambient = _number(settings.get("ambient_c", quick_therm_result.get("ambient_c")), "Ambient (°C)", minimum=-273.15)
    k = _number(settings.get("board_k_w_mk"), "Effective in-plane board conductivity (W/m/K)", positive=True)
    thickness_m = _number(settings.get("board_thickness_mm"), "Board thickness (mm)", positive=True) / 1000
    emissivity = _number(settings.get("board_emissivity"), "Board emissivity", minimum=0)
    if emissivity > 1:
        raise ValueError("Board emissivity must be at most 1.")
    board_airflow = _number(settings.get("board_airflow_m_s"), "Board airflow (m/s)", minimum=0)
    sink_airflow = _number(settings.get("sink_airflow_m_s"), "Sink airflow (m/s)", minimum=0)
    environment = quick_therm_result.get("environment", "air")
    if environment not in ("air", "vacuum"):
        raise ValueError("QuickTherm environment must be air or vacuum.")
    if environment == "vacuum" and (board_airflow or sink_airflow):
        raise ValueError("Airflow must be zero in vacuum.")
    board_h = (_number(settings["board_h_w_m2k"], "Board convection coefficient (W/m²/K)", minimum=0)
               if "board_h_w_m2k" in settings else (5 + 4 * board_airflow if environment == "air" else 0))
    sink_h = (_number(settings["sink_h_w_m2k"], "Sink convection coefficient (W/m²/K)", minimum=0)
              if "sink_h_w_m2k" in settings else (5 + 5 * sink_airflow if environment == "air" else 0))
    if environment == "vacuum" and (board_h or sink_h):
        raise ValueError("Convection coefficients must be zero in vacuum.")
    raw_n = settings.get("grid_cells_long_axis", 48)
    if isinstance(raw_n, bool) or not isinstance(raw_n, int) or not 4 <= raw_n <= 100:
        raise ValueError("grid_cells_long_axis must be an integer from 4 to 100.")
    xmin, ymin, xmax, ymax = [_number(v, "Board bound") for v in view["bbox_mm"]]
    width_m, height_m = (xmax - xmin) / 1000, (ymax - ymin) / 1000
    if width_m <= 0 or height_m <= 0:
        raise ValueError("Board outline bounding box must have positive area.")
    nx = max(2, round(raw_n * width_m / max(width_m, height_m)))
    ny = max(2, round(raw_n * height_m / max(width_m, height_m)))
    dx, dy = width_m / nx, height_m / ny
    dx_mm, dy_mm = dx * 1000, dy * 1000
    xs = [xmin + (i + .5) * (xmax - xmin) / nx for i in range(nx)]
    ys = [ymin + (j + .5) * (ymax - ymin) / ny for j in range(ny)]
    cells = [(i, j) for j, y in enumerate(ys) for i, x in enumerate(xs) if _inside_board((x, y), outlines)]
    if not cells:
        raise ValueError("Grid did not place cells inside the verified board outline; increase grid resolution.")
    cell_index = {cell: index for index, cell in enumerate(cells)}
    count = len(cells)
    area = dx * dy * 2  # Both exposed faces; edges and copper planes are not separately modeled.
    neighbors = [[] for _ in cells]
    for index, (i, j) in enumerate(cells):
        for key, conductance in (((i - 1, j), k * thickness_m * dy / dx),
                                 ((i + 1, j), k * thickness_m * dy / dx),
                                 ((i, j - 1), k * thickness_m * dx / dy),
                                 ((i, j + 1), k * thickness_m * dx / dy)):
            other = cell_index.get(key)
            if other is not None:
                neighbors[index].append((other, conductance))
    sources = [0.0] * count
    by_ref = {row["reference"]: row for row in view.get("components", [])}
    result_components = []
    sink_defs = settings.get("sink_exposed_area_mm2", {})
    if not isinstance(sink_defs, Mapping):
        raise ValueError("sink_exposed_area_mm2 must map component references to exposed areas.")
    raw_sink_e = settings.get("sink_emissivity", emissivity)
    if not isinstance(raw_sink_e, Mapping):
        raw_sink_e = {ref: raw_sink_e for ref in sink_defs}
    total_board_power = 0.0
    for row in quick_therm_result.get("components", []):
        ref = str(row["reference"])
        component = by_ref.get(ref)
        if component is None or not component.get("on_board"):
            raise ValueError(f"{ref} needs a footprint center within the verified board outline.")
        power = _number(row.get("power_w"), f"{ref} power (W)", minimum=0)
        legacy_path = row.get("heat_path")
        network_path = "board" if legacy_path in ("air", "board") else legacy_path
        entry = {"reference": ref, "side": component["side"], "power_w": power,
                 "position_mm": component["position_mm"], "heat_path": network_path,
                 "source_heat_path": legacy_path,
                 "board_site_c": None, "sink_c": None, "junction_c": None}
        if network_path == "heatsink":
            if ref not in sink_defs:
                raise ValueError(f"{ref}: specify sink_exposed_area_mm2; envelope dimensions do not establish fin area.")
            sink_area = _number(sink_defs[ref], f"{ref} exposed sink area (mm²)", positive=True) / 1e6
            sink_e = _number(raw_sink_e.get(ref, emissivity), f"{ref} sink emissivity", minimum=0)
            if sink_e > 1:
                raise ValueError(f"{ref}: sink emissivity must be at most 1.")
            if sink_h == 0 and sink_e == 0:
                raise ValueError(f"{ref}: sink has no heat-rejection path.")
            entry["sink_c"] = _sink_temperature(power, ambient, sink_area, sink_h, sink_e)
            entry["sink_area_m2"] = sink_area
            entry["sink_emissivity"] = sink_e
            resistance = _optional_resistance(settings, "component_to_sink_k_per_w", ref)
            if resistance is not None:
                entry["junction_c"] = entry["sink_c"] + power * resistance
        elif network_path == "board":
            weights, source_kind, source_area = _source_cells(component, cells, xs, ys, dx_mm, dy_mm)
            entry["source_distribution"] = source_kind
            entry["source_cell_count"] = len(weights)
            entry["source_overlap_area_mm2"] = source_area
            entry["source_cells"] = weights
            for index, weight in weights:
                sources[index] += power * weight
            total_board_power += power
        else:
            raise ValueError(f"{ref}: unsupported heat path.")
        result_components.append(entry)
    if total_board_power == 0 and not result_components:
        raise ValueError("No solved QuickTherm components are available.")
    if total_board_power > 0 and board_h == 0 and emissivity == 0:
        raise ValueError("Board has no heat-rejection path; specify radiation, convection, or both.")
    temp, iterations = _solve_board_sparse(neighbors, sources, ambient, area, board_h, emissivity)
    grid = [[None for _ in range(nx)] for _ in range(ny)]
    for index, (i, j) in enumerate(cells):
        grid[j][i] = temp[index]
    for entry in result_components:
        if entry["heat_path"] == "board":
            weights = entry.pop("source_cells")
            entry["board_site_c"] = math.fsum(temp[index] * weight for index, weight in weights)
            resistance = _optional_resistance(settings, "component_to_board_k_per_w", entry["reference"])
            if resistance is not None:
                entry["junction_c"] = entry["board_site_c"] + entry["power_w"] * resistance
    board_conv = math.fsum(area * board_h * (t - ambient) for t in temp)
    board_rad = math.fsum(_heat_loss(t, ambient, area, 0, emissivity) for t in temp)
    sink_conv = math.fsum(row["sink_area_m2"] * sink_h * (row["sink_c"] - ambient)
                          for row in result_components if row["heat_path"] == "heatsink")
    sink_rad = math.fsum(_heat_loss(row["sink_c"], ambient, row["sink_area_m2"], 0, row["sink_emissivity"])
                         for row in result_components if row["heat_path"] == "heatsink")
    input_power = math.fsum(row["power_w"] for row in result_components)
    residual = input_power - board_conv - board_rad - sink_conv - sink_rad
    tolerance = max(1e-5, input_power * 1e-4)
    return {
        "model": "steady-state thin-sheet board conduction with convection and radiation",
        "status": "converged" if abs(residual) <= tolerance else "imbalanced",
        "environment": environment, "ambient_c": ambient,
        "settings": {"board_k_w_mk": k, "board_thickness_mm": thickness_m * 1000,
                     "board_emissivity": emissivity, "board_airflow_m_s": board_airflow,
                     "sink_airflow_m_s": sink_airflow, "board_h_w_m2k": board_h,
                     "sink_h_w_m2k": sink_h},
        "board_field": {"x_centers_mm": xs, "y_centers_mm": ys, "values_c": grid,
                        "grid_cells_long_axis": raw_n, "active_cells": count,
                        "solver_iterations": iterations,
                        "sampled_min_c": min(temp), "sampled_max_c": max(temp),
                        "top_bottom_note": "One through-thickness midplane temperature per cell; top and bottom PCB faces are assumed equal."},
        "components": result_components,
        "heat_balance": {"input_w": input_power, "board_convection_w": board_conv,
                         "board_radiation_w": board_rad, "sink_convection_w": sink_conv,
                         "sink_radiation_w": sink_rad, "residual_w": residual,
                         "relative_residual": abs(residual) / max(input_power, 1e-12),
                         "tolerance_w": tolerance},
        "coverage": dict(quick_therm_result.get("coverage", {})),
        "assumptions": [
            "Board is a uniform isotropic thin sheet with an effective in-plane conductivity; copper and vias are not resolved.",
            "Top and bottom board faces have the same cell temperature and the same exposed convection/radiation properties.",
            "Convection uses h = 5 + 4v for the board and h = 5 + 5v for sinks (W/m²/K) in air unless an explicit h is supplied; these are screening correlations, not CFD.",
            "Radiation uses gray diffuse emissivity and a uniform prescribed ambient/surroundings temperature.",
            "Virtual sink nodes are independent of the board and require explicit exposed area; no sink-to-board parallel path is inferred.",
            "Legacy RθJA/RθJB values are not reused for junction estimates. A new junction estimate requires explicit component-to-board/sink resistance.",
            "Board heat is spread over each footprint's axis-aligned bounding box as a contact-area proxy; text or package overhang can make this unlike true thermal-pad contact. Missing bounds use a point source.",
            "Only solved scoped component power is included; missing field mappings and other board heat sources remain outside the heat balance.",
        ],
    }
