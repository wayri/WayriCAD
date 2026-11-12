"""Bounded steady-state 3D rectilinear cell-centred thermoelectric network.

Public API: solve_thermoelectric3d(request, cancel=None). JSON schema version 1:
grid.edges_mm = {x: [...], y: [...], z: [...]}; material_ids is x-fast,
z*nx*ny+y*nx+x, with null meaning void. Also accepts top-level edges_mm.
Materials have thermal_conductivity_w_mk (positive scalar or [kx,ky,kz]),
resistivity_ohm_m (positive scalar, null = insulator; rho_ohm_m alias),
reference_c (default 20), tcr_per_k, seebeck_v_k, seebeck_slope_v_k2.
temperature_factors = [[C, R/Rref], ...] overrides linear TCR, must include
[reference_c, 1], and never extrapolates. material_temperature_range_c limits
each material. fixed_voltage_v and fixed_temperature_c map cell indices to
values. terminals optionally maps names to {cells: [...], voltage_v: value}.
These are ideal prescribed CELL CENTRES, not physical boundary-face contacts.
heat_w is a flat external heat array (negative = cooling). boundary contains
ambient_c (20), h_w_m2k (0), emissivity (0), applied on every exposed face,
including void-facing surfaces. Void does not conduct or exchange radiation.

SI equations on oriented face i->j (T in kelvins):
I = g*(Vi-Vj + Sbar*(Ti-Tj)); Pi = S*T.
Heat into i = K*(Tj-Ti) + I**2/(2*g) - Sbar*Ti*I;
heat into j = K*(Ti-Tj) + I**2/(2*g) + Sbar*Tj*I.
Their sum is exactly I*(Vi-Vj). K and g use series half-cell resistances.
Sbar is the arithmetic mean of cell Seebeck values. Temperature-dependent S
is a conservative edge approximation, NOT a qualified continuum Thomson
model. Half-edge Joule allocation and interface averaging need mesh studies.

Primary references (equations/sign conventions adapted to edge orientation):
https://doc.comsol.com/6.4/doc/com.comsol.help.heat/heat_ug_theory.07.087.html
https://doc.comsol.com/6.3/doc/com.comsol.help.heat/heat_ug_theory.07.041.html
These describe Kelvin coupling, current/heat conservation and symmetric Joule
partition; they do not validate this implementation or any particular material.

Settings: max_cells <= 50000 (default 10000), max_iterations <= 1000 (200),
max_linear_iterations <= 10000 (2000), relaxation in (0,1] (0.5),
temperature_tolerance_c (1e-7), residual_tolerance_w (1e-8),
linear_tolerance (1e-10), temperature_bounds_c ([-100,1000]).
At most 256 materials and 10000 total table points; minimum edge spacing is
1e-9 mm. Sparse Jacobi-preconditioned SciPy CG avoids direct-solver fill.
Cancellation is checked between assembly stages and in linear iterations;
a native sparse operation itself is not preemptible. No transient physics,
contact resistance, fluid flow, view factors, phase changes, or rotated tensors.
Only source-level numerical reference checks, not hardware qualification.
"""
from __future__ import annotations

import math
import inspect
from collections.abc import Mapping


MAX_CELLS = 50000
SIGMA = 5.670374419e-8


def _number(value, name, low=-math.inf, high=math.inf):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} outside [{low}, {high}]")
    return result


def solve_thermoelectric3d(request, cancel=None):
    """Return JSON-safe converged fields; ValueError invalid, RuntimeError failed.

    cancel is a zero-argument predicate (or threading.Event). Terminal current
    is positive INTO the domain, electrical_power_w = sum(V*terminal_current).
    heat_out_w includes ambient exchange and ideal temperature clamps (signed).
    Null potential/current density denotes an insulator or void; void thermal
    fields are null. Face currents are authoritative; cell current density is
    the average of present conductive face fluxes per axis, not a contact flux.
    """
    import numpy as np
    from scipy.sparse import coo_matrix, diags
    from scipy.sparse.csgraph import connected_components
    from scipy.sparse.linalg import cg
    # SciPy 1.10/1.11 use tol; newer releases use rtol. Inspect once per
    # solve, never retry backend TypeErrors which may signal a real defect.
    cg_tolerance_key = 'rtol' if 'rtol' in inspect.signature(cg).parameters else 'tol'

    def checkpoint():
        if cancel is not None and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()):
            raise RuntimeError("thermoelectric3d cancelled")

    checkpoint()
    if not isinstance(request, Mapping) or request.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    settings = request.get("settings", {})
    if not isinstance(settings, Mapping):
        raise ValueError("settings must be a mapping")

    def setting(name, default, low, high):
        return _number(settings.get(name, default), name, low, high)

    def integer(name, default, low, high):
        value = setting(name, default, low, high)
        if value != int(value):
            raise ValueError(f"{name} must be integral")
        return int(value)

    cap = integer("max_cells", 10000, 1, MAX_CELLS)
    iterations = integer("max_iterations", 200, 1, 1000)
    linear_iterations = integer("max_linear_iterations", 2000, 1, 10000)
    relax = setting("relaxation", 0.5, 1e-6, 1)
    temp_tol = setting("temperature_tolerance_c", 1e-7, 1e-12, 1)
    residual_tol = setting("residual_tolerance_w", 1e-8, 1e-14, 1)
    linear_tol = setting("linear_tolerance", 1e-10, 1e-14, 1e-3)

    def bounds(value, name):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"{name} needs [minimum, maximum]")
        lo, hi = [_number(v, name, -273.149999, 10000) for v in value]
        if lo > hi:
            raise ValueError(f"{name} is reversed")
        return lo, hi

    global_bounds = bounds(settings.get("temperature_bounds_c", [-100, 1000]), "temperature_bounds_c")
    grid = request.get("grid", {})
    if not isinstance(grid, Mapping):
        raise ValueError("grid must be a mapping")
    edges = grid.get("edges_mm", request.get("edges_mm"))
    if not isinstance(edges, Mapping):
        raise ValueError("grid.edges_mm must contain x, y, z")
    axes = []
    for axis in "xyz":
        values = edges.get(axis)
        if not isinstance(values, (list, tuple)) or not 2 <= len(values) <= cap + 1:
            raise ValueError(f"{axis} grid edges invalid or over cap")
        a = np.array([_number(v, "grid edge", -1e9, 1e9) for v in values]) * 0.001
        if np.any(np.diff(a) < 1e-12):
            raise ValueError("grid edges must be strictly increasing, spacing >= 1e-9 mm")
        axes.append(a)
    nx, ny, nz = shape = tuple(len(a)-1 for a in axes)
    n = nx*ny*nz
    if n > cap:
        raise ValueError(f"grid exceeds max_cells={cap}")
    ids = request.get("material_ids")
    if not isinstance(ids, (list, tuple)) or len(ids) != n:
        raise ValueError("material_ids must be a flat grid-sized array")
    if any(v is not None and not isinstance(v, str) for v in ids):
        raise ValueError("material_ids entries must be strings or null")
    materials = request.get("materials", {})
    if not isinstance(materials, Mapping) or len(materials) > 256:
        raise ValueError("materials must be a mapping of at most 256 entries")
    active = np.array([v is not None for v in ids])
    if not np.any(active):
        raise ValueError("grid contains no material")
    k = np.ones((n, 3))
    rho0 = np.full(n, np.inf)
    ref = np.full(n, 20.)
    tcr, s0, slope = (np.zeros(n) for _ in range(3))
    low = np.full(n, global_bounds[0])
    high = np.full(n, global_bounds[1])
    tables = []
    table_points = 0
    for mid in dict.fromkeys(v for v in ids if v is not None):
        if not isinstance(mid, str) or mid not in materials:
            raise ValueError(f"unknown material {mid!r}")
        m = materials[mid]
        if not isinstance(m, Mapping):
            raise ValueError("material must be a mapping")
        mask = np.array([v == mid for v in ids])
        kval = m.get("thermal_conductivity_w_mk")
        if not isinstance(kval, (list, tuple)):
            kval = [kval]*3
        if len(kval) != 3:
            raise ValueError("thermal conductivity needs scalar or xyz")
        k[mask] = [_number(v, "thermal conductivity", 1e-12, 1e8) for v in kval]
        rho = m.get("resistivity_ohm_m", m.get("rho_ohm_m"))
        if "resistivity_ohm_m" in m and "rho_ohm_m" in m and m["rho_ohm_m"] != rho:
            raise ValueError("conflicting resistivity aliases")
        if rho is not None:
            rho0[mask] = _number(rho, "resistivity", 1e-15, 1e15)
        reference = _number(m.get("reference_c", 20), "reference_c", -273.149999, 10000)
        ref[mask] = reference
        tcr[mask] = _number(m.get("tcr_per_k", 0), "tcr_per_k", -1, 1)
        s0[mask] = _number(m.get("seebeck_v_k", 0), "seebeck_v_k", -1, 1)
        slope[mask] = _number(m.get("seebeck_slope_v_k2", 0), "seebeck_slope_v_k2", -0.1, 0.1)
        if "material_temperature_range_c" in m:
            lo, hi = bounds(m["material_temperature_range_c"], "material_temperature_range_c")
            low[mask] = np.maximum(low[mask], lo)
            high[mask] = np.minimum(high[mask], hi)
        if "temperature_factors" in m:
            table = m["temperature_factors"]
            if not isinstance(table, (list, tuple)) or not 2 <= len(table) <= 10000:
                raise ValueError("temperature_factors needs 2..10000 points")
            table_points += len(table)
            if table_points > 10000:
                raise ValueError("total temperature_factors exceeds 10000 points")
            rows = []
            for row in table:
                if not isinstance(row, (list, tuple)) or len(row) != 2:
                    raise ValueError("temperature_factors needs [temperature_c, factor] pairs")
                rows.append([_number(row[0], "table temperature", -273.149999, 10000),
                             _number(row[1], "resistance factor", 1e-12, 1e12)])
            table = np.array(rows)
            if np.any(np.diff(table[:, 0]) <= 0) or not any(
                    abs(t-reference) <= 1e-9 and abs(f-1) <= 1e-9 for t, f in table):
                raise ValueError("temperature_factors must increase and include reference factor 1")
            low[mask] = np.maximum(low[mask], table[0, 0])
            high[mask] = np.minimum(high[mask], table[-1, 0])
            tables.append((mask, table))
    if np.any(low[active] > high[active]):
        raise ValueError("empty material/global temperature range intersection")
    conducting = active & np.isfinite(rho0)

    def indexed(values, name, valid):
        if not isinstance(values, Mapping):
            raise ValueError(f"{name} must map cell indices to values")
        result = {}
        for key, value in values.items():
            try:
                i = int(key)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} invalid cell index") from exc
            if str(i) != str(key) or not 0 <= i < n or not valid[i]:
                raise ValueError(f"{name} invalid cell index {key}")
            result[i] = _number(value, name)
        return result

    fixed_v = indexed(request.get("fixed_voltage_v", {}), "fixed_voltage_v", conducting)
    fixed_t = indexed(request.get("fixed_temperature_c", {}), "fixed_temperature_c", active)
    terminals = request.get("terminals", {})
    terminal_cells = {}
    if not isinstance(terminals, Mapping):
        raise ValueError("terminals must be a mapping")
    assigned = set()
    for name, terminal in terminals.items():
        if not isinstance(terminal, Mapping):
            raise ValueError("terminal must be a mapping")
        cells = terminal.get("cells", [])
        if not isinstance(name, str) or not isinstance(cells, (list, tuple)) or not cells:
            raise ValueError("terminal needs a name and nonempty cells")
        voltage = _number(terminal.get("voltage_v"), "terminal voltage_v")
        cellmap = indexed({str(c): voltage for c in cells}, "terminal cells", conducting)
        if len(cellmap) != len(cells) or assigned.intersection(cellmap):
            raise ValueError("duplicate/overlapping terminal cells")
        for i in cellmap:
            if i in fixed_v and fixed_v[i] != voltage:
                raise ValueError("conflicting terminal voltage")
        fixed_v.update(cellmap)
        assigned.update(cellmap)
        terminal_cells[name] = list(cellmap)
    boundary = request.get("boundary", {})
    if not isinstance(boundary, Mapping):
        raise ValueError("boundary must be a mapping")
    ambient = _number(boundary.get("ambient_c", 20), "ambient_c", -273.149999, 10000)
    h = _number(boundary.get("h_w_m2k", 0), "h_w_m2k", 0, 1e8)
    emissivity = _number(boundary.get("emissivity", 0), "emissivity", 0, 1)
    heat_values = request.get("heat_w", [0.]*n)
    if not isinstance(heat_values, (list, tuple)) or len(heat_values) != n:
        raise ValueError("heat_w must be grid-sized")
    external = np.array([_number(v, "heat_w", -1e12, 1e12) for v in heat_values])
    if np.any(external[~active] != 0):
        raise ValueError("heat_w applied to void")
    widths = [np.diff(a) for a in axes]
    coords = np.array([(x, y, z) for z in range(nz) for y in range(ny) for x in range(nx)])
    sizes = np.column_stack([widths[d][coords[:, d]] for d in range(3)])
    volumes = np.prod(sizes, axis=1)
    exposed = np.zeros(n)
    face_i, face_j, face_axis, area, di, dj = ([] for _ in range(6))
    strides = [1, nx, nx*ny]
    for i in np.flatnonzero(active):
        if i % 1024 == 0:
            checkpoint()
        for d in range(3):
            a = volumes[i]/sizes[i, d]
            for direction in (-1, 1):
                neighbor = i+direction*strides[d]
                inside = 0 <= coords[i, d]+direction < shape[d]
                if not inside or not active[neighbor]:
                    exposed[i] += a
                elif direction == 1:
                    face_i.append(i); face_j.append(neighbor); face_axis.append(d)
                    area.append(a); di.append(sizes[i, d]/2); dj.append(sizes[neighbor, d]/2)
    fi, fj, fa = [np.array(v, dtype=int) for v in (face_i, face_j, face_axis)]
    area, di, dj = [np.array(v) for v in (area, di, dj)]
    thermal_g = area/(di/k[fi, fa]+dj/k[fj, fa])
    electric_faces = conducting[fi] & conducting[fj]
    ei, ej = fi[electric_faces], fj[electric_faces]

    def laplacian(i, j, g):
        return coo_matrix((np.concatenate((g, g, -g, -g)),
                          (np.concatenate((i, j, i, j)), np.concatenate((i, j, j, i)))),
                          shape=(n, n)).tocsr()

    thermal_l = laplacian(fi, fj, thermal_g)

    def check_anchors(i, j, mask, anchors, name):
        graph = laplacian(i, j, np.ones(len(i)))
        _, labels = connected_components(graph, directed=False)
        if not set(labels[mask]).issubset(set(labels[list(anchors)])):
            raise ValueError(f"{name}: floating component / no sink or reference")

    check_anchors(ei, ej, conducting, fixed_v, "electrical")
    thermal_anchors = set(fixed_t)
    if h or emissivity:
        thermal_anchors.update(np.flatnonzero(active & (exposed > 0)))
    check_anchors(fi, fj, active, thermal_anchors, "thermal")

    def linear(matrix, rhs, fixed, mask, guess):
        checkpoint()
        known = np.array(sorted(fixed), dtype=int)
        unknown_mask = mask.copy()
        unknown_mask[known] = False
        unknown = np.flatnonzero(unknown_mask)
        result = guess.copy()
        result[known] = [fixed[i] for i in known]
        if len(unknown):
            a = matrix[unknown][:, unknown]
            b = rhs[unknown] - matrix[unknown][:, known] @ result[known]
            diagonal = a.diagonal()
            if np.any(diagonal <= 0):
                raise ValueError("singular linear system")
            solution, info = cg(a, b, x0=result[unknown], **{cg_tolerance_key: linear_tol}, atol=1e-14,
                                M=diags(1/diagonal), maxiter=linear_iterations,
                                callback=lambda _: checkpoint())
            if info != 0 or not np.all(np.isfinite(solution)):
                raise RuntimeError(f"sparse linear solve failed to converge ({info})")
            result[unknown] = solution
        return result

    temperature = np.clip(np.full(n, ambient), low, high)
    for i, value in fixed_t.items():
        temperature[i] = value
    potential = np.zeros(n)

    def validate_temperature(t):
        if not np.all(np.isfinite(t)) or np.any(t[active] < low[active]) or np.any(t[active] > high[active]):
            raise ValueError("temperature outside material/table/global bounds (no extrapolation)")

    def fields(t, v):
        validate_temperature(t)
        factor = 1+tcr*(t-ref)
        for mask, table in tables:
            factor[mask] = np.interp(t[mask], table[:, 0], table[:, 1])
        if np.any(factor[conducting] <= 0):
            raise ValueError("nonpositive temperature-dependent resistivity")
        rho = rho0*factor
        g = area[electric_faces]/(di[electric_faces]*rho[ei]+dj[electric_faces]*rho[ej])
        seebeck = s0+slope*(t-ref)
        sb = (seebeck[ei]+seebeck[ej])/2
        emf = sb*(t[ei]-t[ej])
        rhs = np.zeros(n)
        np.add.at(rhs, ei, -g*emf); np.add.at(rhs, ej, g*emf)
        v = linear(laplacian(ei, ej, g), rhs, fixed_v, conducting, v)
        current = g*(v[ei]-v[ej]+emf)
        joule_edge = current**2/g
        source = external.copy()
        joule = np.zeros(n)
        np.add.at(joule, ei, joule_edge/2); np.add.at(joule, ej, joule_edge/2)
        source += joule
        np.add.at(source, ei, -sb*(t[ei]+273.15)*current)
        np.add.at(source, ej, sb*(t[ej]+273.15)*current)
        kelvin = t+273.15
        ambient_k = ambient+273.15
        radiation_g = emissivity*SIGMA*exposed*(kelvin+ambient_k)*(kelvin**2+ambient_k**2)
        sink_g = h*exposed+radiation_g
        heat_ambient = sink_g*(t-ambient)
        balance = source-thermal_l@t-heat_ambient
        return v, current, joule, source, sink_g, heat_ambient, balance

    history = []
    free = active.copy()
    free[list(fixed_t)] = False
    validate_temperature(temperature)
    for iteration in range(1, iterations+1):
        checkpoint()
        potential, current, joule, source, sink_g, _, _ = fields(temperature, potential)
        target = linear(thermal_l+diags(sink_g), source+sink_g*ambient,
                        fixed_t, active, temperature)
        updated = temperature+relax*(target-temperature)
        delta = float(np.max(np.abs(updated[active]-temperature[active])))
        temperature = updated
        potential, current, joule, source, sink_g, heat_ambient, balance = fields(temperature, potential)
        residual = float(np.max(np.abs(balance[free]))) if np.any(free) else 0.
        history.append({"iteration": iteration, "temperature_change_c": delta,
                        "max_heat_residual_w": residual})
        if delta <= temp_tol and residual <= residual_tol:
            break
    else:
        raise RuntimeError(f"thermoelectric3d nonlinear nonconvergence after {iterations} iterations")
    terminal_current = np.zeros(n)
    np.add.at(terminal_current, ei, current); np.add.at(terminal_current, ej, -current)
    electric_free = conducting.copy()
    electric_free[list(fixed_v)] = False
    current_residual = float(np.max(np.abs(terminal_current[electric_free]))) if np.any(electric_free) else 0.
    current_scale = float(np.max(np.abs(current))) if len(current) else 0.
    if current_residual > 1e-12 + 1e-8*current_scale:
        raise RuntimeError("electrical charge balance failed")
    electrical_power = math.fsum(potential[i]*terminal_current[i] for i in fixed_v)
    clamp_heat = {str(i): float(balance[i]) for i in fixed_t}
    heat_out = float(heat_ambient.sum())+math.fsum(clamp_heat.values())
    energy_residual = float(external.sum())+electrical_power-heat_out
    if abs(energy_residual) > residual_tol*max(1, int(np.count_nonzero(free))) + 1e-10*max(1, abs(electrical_power)):
        raise RuntimeError("global energy balance failed")
    density = np.zeros((n, 3)); counts = np.zeros((n, 3))
    ea = fa[electric_faces]
    flux = current/area[electric_faces]
    for cells in (ei, ej):
        np.add.at(density, (cells, ea), flux)
        np.add.at(counts, (cells, ea), 1)
    density /= np.maximum(counts, 1)

    def flat(values, mask):
        return [float(values[i]) if mask[i] else None for i in range(n)]

    temperature_cells = flat(temperature, active)
    result = {
        "schema_version": 1, "converged": True, "iterations": iteration, "history": history,
        "temperature_c": temperature_cells, "temperatures_c": temperature_cells,
        "material_ids": list(ids), "potential_v": flat(potential, conducting),
        "current_density_a_m2": [density[i].tolist() if conducting[i] else None for i in range(n)],
        "joule_heat_w": flat(joule, active), "joule_density_w_m3": flat(joule/volumes, active),
        "terminal_current_a": {str(i): float(terminal_current[i]) for i in fixed_v},
        "terminal_currents_a": {name: float(terminal_current[cells].sum()) for name, cells in terminal_cells.items()},
        "electrical_power_w": electrical_power, "external_heat_w": float(external.sum()),
        "heat_out_w": heat_out, "ambient_heat_out_w": float(heat_ambient.sum()),
        "fixed_temperature_heat_out_w": clamp_heat, "energy_residual_w": energy_residual,
        "max_heat_residual_w": residual,
        "max_current_residual_a": current_residual,
        "material_temperature_range_c": {str(i): [float(low[i]), float(high[i])] for i in np.flatnonzero(active)},
        "faces": {"cell_i": ei.tolist(), "cell_j": ej.tolist(), "current_a": current.tolist()},
        "coordinates": {"shape_xyz": list(shape), "edges_mm": {d: (a*1000).tolist() for d, a in zip("xyz", axes)},
                        "centres_mm": ((np.column_stack([(axes[d][coords[:, d]]+axes[d][coords[:, d]+1])/2 for d in range(3)]))*1000).tolist(),
                        "cell_volume_m3": volumes.tolist(), "ordering": "x-fast"},
        "model": "steady-state true 3D rectilinear finite-volume thermoelectric edge network",
        "limits": ["cell-centre ideal contacts", "no transient or fluid physics", "diagonal thermal conductivity only",
                   "temperature-dependent Seebeck is an edge approximation, not qualified Thomson physics",
                   "symmetric edge Joule allocation; mesh refinement required", "no material table extrapolation"],
    }
    result["grid"] = {"edges_mm": result["coordinates"]["edges_mm"]}
    result["energy_balance"] = {key: result[key] for key in (
        "electrical_power_w", "external_heat_w", "heat_out_w", "ambient_heat_out_w",
        "fixed_temperature_heat_out_w", "energy_residual_w", "max_heat_residual_w",
        "max_current_residual_a")}
    return result
