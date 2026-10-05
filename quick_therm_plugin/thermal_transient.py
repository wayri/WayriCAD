"""Read-only coupled-air electrothermal RC screen for board assemblies.

The network is deliberately lumped: board and sink capacities, contact
resistances and heat-transfer conductances are supplied, not inferred from a
PCB drawing. Temperatures are in Celsius, time in seconds, power in watts.
"""
from __future__ import annotations

import hashlib
import json
import math
import copy
from pathlib import Path


def _number(value, label, *, positive=False, nonnegative=False):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result) or (positive and result <= 0) or (nonnegative and result < 0):
        raise ValueError(f"{label} is outside its allowed range.")
    return result


def _canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _interpolate(points, flow, label):
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError(f"{label} needs at least two measured points.")
    pairs = [(_number(p[0], label+" flow", nonnegative=True),
              _number(p[1], label+" value", nonnegative=True)) for p in points]
    if any(b[0] <= a[0] for a, b in zip(pairs, pairs[1:])):
        raise ValueError(f"{label} flows must increase strictly.")
    if not pairs[0][0] <= flow <= pairs[-1][0]:
        raise ValueError(f"{label} does not cover the operating flow.")
    for a, b in zip(pairs, pairs[1:]):
        if a[0] <= flow <= b[0]:
            fraction = (flow-a[0])/(b[0]-a[0])
            return a[1]+fraction*(b[1]-a[1])
    return pairs[-1][1]


def fan_operating_point(fan_curve, system_k_pa_s2_m6, bypass_fraction, fans_parallel=1):
    """Intersect a measured fan P-Q curve with Δp=K Q², then remove bypass.

    ``fan_curve`` is ``[[m³/s, Pa], ...]`` at the assembled fan configuration.
    ``system_k_pa_s2_m6`` applies to total fan flow. The bypass fraction is an
    explicit assembly assumption, never deduced from free-air fan ratings.
    """
    k = _number(system_k_pa_s2_m6, "System pressure coefficient", positive=True)
    if isinstance(fans_parallel, bool) or not isinstance(fans_parallel, int) or not 1 <= fans_parallel <= 16:
        raise ValueError("fans_parallel must be an integer from 1 to 16.")
    bypass = _number(bypass_fraction, "Bypass fraction", nonnegative=True)
    if bypass >= 1:
        raise ValueError("Bypass fraction must be below one.")
    if not isinstance(fan_curve, list) or len(fan_curve) < 2:
        raise ValueError("A measured fan P-Q curve with at least two points is required.")
    curve = [(_number(row[0], "Fan flow", nonnegative=True),
              _number(row[1], "Fan pressure", nonnegative=True)) for row in fan_curve]
    if curve[0][0] != 0 or any(b[0] <= a[0] or b[1] > a[1]
                             for a, b in zip(curve, curve[1:])):
        raise ValueError("Fan curve must start at zero flow, rise in flow and not rise in pressure.")
    if curve[0][1] <= 0 or curve[-1][0] <= 0:
        raise ValueError("Fan curve needs positive shutoff pressure and flow coverage.")
    high = curve[-1][0]
    high *= fans_parallel
    if _interpolate(fan_curve, high/fans_parallel, "Fan curve") > k*high*high:
        raise ValueError("Fan curve ends before its system-curve intersection.")
    low = 0.0
    for _ in range(64):
        mid = (low+high)/2
        if _interpolate(fan_curve, mid/fans_parallel, "Fan curve") > k*mid*mid:
            low = mid
        else:
            high = mid
    total = (low+high)/2
    return {"total_m3_s": total, "board_channel_m3_s": total*(1-bypass),
            "bypass_fraction": bypass, "pressure_pa": k*total*total,
            "fans_parallel": fans_parallel}


def _solve_linear(matrix, rhs):
    """Dense pivoted elimination; bounded to small explicit RC networks."""
    size = len(rhs)
    rows = [list(matrix[i])+[rhs[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < 1e-14:
            raise ValueError("Thermal network is disconnected or singular.")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        for j in range(col, size+1):
            rows[col][j] /= scale
        for row in range(size):
            if row == col:
                continue
            factor = rows[row][col]
            for j in range(col, size+1):
                rows[row][j] -= factor*rows[col][j]
    return [rows[i][-1] for i in range(size)]


def _parallel_air_profile(temperatures, contacts, positions, inlet_c, mass_heat_capacity_w_k):
    """Conserve heat through serial +X-to−X stations in one Blade passage."""
    stages = []
    air = inlet_c
    for stage_index, x_mm in enumerate(positions):
        selected = [(node, h) for node, h, index in contacts if index == stage_index]
        conductance = sum(h for _, h in selected)
        if conductance:
            solid = sum(h*temperatures[node] for node, h in selected)/conductance
            transfer = math.exp(-conductance/mass_heat_capacity_w_k)
            outlet = solid+(air-solid)*transfer
            mean = solid+(air-solid)*(-math.expm1(-conductance/mass_heat_capacity_w_k))/(
                conductance/mass_heat_capacity_w_k)
        else:
            outlet = mean = air
        stages.append({"x_mm": x_mm, "inlet_c": air, "mean_c": mean,
                       "outlet_c": outlet,
                       "heat_w": mass_heat_capacity_w_k*(outlet-air)})
        air = outlet
    return stages


def solve_coupled_transient(config):
    """Solve four explicit serial boards or parallel air passages with R(T).

    Each board has one board node plus component junction and optional isolated
    sink nodes. The fan and all conductance curves are supplied measurements or
    declared assumptions. No spatial copper field or CFD is calculated.
    """
    if not isinstance(config, dict):
        raise ValueError("Transient config must be an object.")
    boards = config.get("boards")
    if not isinstance(boards, list) or len(boards) != 4:
        raise ValueError("Coupled transient requires exactly four ordered boards.")
    topology = config.get("air_topology")
    if topology not in ("serial_boards", "parallel_passages"):
        raise ValueError("air_topology must explicitly be serial_boards or parallel_passages.")
    if topology == "parallel_passages":
        if config.get("air_flow_direction") != "-X":
            raise ValueError("Parallel Blade passages require explicit air_flow_direction: -X.")
        if config.get("passage_flow_allocation") != "effective_per_blade":
            raise ValueError("parallel_passages requires passage_flow_allocation: effective_per_blade; four Blade allocations are not five physical gaps.")
        pitch = _number(config.get("blade_pitch_mm"), "Blade pitch (mm)", positive=True)
        fractions = config.get("passage_flow_fractions")
        if not isinstance(fractions, list) or len(fractions) != 4:
            raise ValueError("Four positive passage_flow_fractions must sum to one.")
        fractions = [_number(value, "Passage flow fraction", positive=True)
                     for value in fractions]
        if abs(sum(fractions)-1) > 1e-6:
            raise ValueError("Four positive passage_flow_fractions must sum to one.")
    else:
        pitch, fractions = None, None
    inlet = _number(config.get("inlet_air_c"), "Inlet air temperature")
    initial = _number(config.get("initial_c", inlet), "Initial temperature")
    if inlet <= -273.15 or initial <= -273.15:
        raise ValueError("Absolute temperature must be positive.")
    duration = _number(config.get("duration_s"), "Duration (s)", positive=True)
    step = _number(config.get("step_s"), "Step (s)", positive=True)
    if duration/step > 10000:
        raise ValueError("Transient exceeds 10,000 steps; increase step_s.")
    air_density = _number(config.get("air_density_kg_m3"), "Air density", positive=True)
    air_cp = _number(config.get("air_cp_j_kgk"), "Air heat capacity", positive=True)
    if "prescribed_total_flow_m3_s" in config:
        if config.get("fan_curve") is not None or config.get("system_k_pa_s2_m6") is not None:
            raise ValueError("Prescribed flow cannot be combined with fan P-Q/system inputs.")
        total_flow = _number(config["prescribed_total_flow_m3_s"],
                             "Prescribed total flow", positive=True)
        bypass = _number(config.get("bypass_fraction"), "Bypass fraction",
                         nonnegative=True)
        if bypass >= 1:
            raise ValueError("Bypass fraction must be below one.")
        flow = {"total_m3_s": total_flow,
                "board_channel_m3_s": total_flow*(1-bypass),
                "bypass_fraction": bypass, "pressure_pa": None,
                "fans_parallel": config.get("fans_parallel"),
                "source": "prescribed_sensitivity_input"}
    else:
        flow = fan_operating_point(config.get("fan_curve"),
                                   config.get("system_k_pa_s2_m6"),
                                   config.get("bypass_fraction"),
                                   config.get("fans_parallel", 1))
        flow["source"] = "declared_fan_curve_system_intersection"
    channel_flows = ([flow["board_channel_m3_s"]*fraction for fraction in fractions]
                     if fractions is not None else [flow["board_channel_m3_s"]]*4)
    if any(value <= 0 for value in channel_flows):
        raise ValueError("The board channel has no air mass flow.")
    names = set()
    network = []
    for bi, board in enumerate(boards):
        name = str(board.get("name", "")).strip()
        if not name or name in names:
            raise ValueError("Each ordered board needs a unique name.")
        names.add(name)
        capacity = _number(board.get("capacity_j_k"), name+" board capacity", positive=True)
        h_curve = board.get("air_conductance_curve")
        h_board = _interpolate(h_curve, channel_flows[bi], name+" board hA")
        fixed = _number(board.get("fixed_power_w", 0), name+" fixed power", nonnegative=True)
        components = board.get("components")
        if not isinstance(components, list) or not components:
            raise ValueError(name+" needs at least one mapped heat source.")
        nodes = [{"id": "board", "capacity": capacity, "air_h": h_board,
                  "fixed_power": fixed, "links": []}]
        boundary = board.get("fixed_boundary")
        if boundary is not None:
            if not boundary.get("contact_evidence"):
                raise ValueError(name+": fixed boundary needs contact_evidence.")
            boundary = {"temperature_c": _number(boundary.get("temperature_c"),
                                                    name+" fixture temperature"),
                        "conductance_w_k": 1/_number(boundary.get("contact_r_k_w"),
                                                       name+" fixture contact R", positive=True)}
            if boundary["temperature_c"] <= -273.15:
                raise ValueError(name+": fixture temperature must exceed absolute zero.")
        seen = set()
        source_positions = {}
        for component in components:
            ref = str(component.get("reference", "")).strip()
            if not ref or ref in seen:
                raise ValueError(name+" has a missing or duplicate component reference.")
            seen.add(ref)
            if topology == "parallel_passages":
                source_positions[ref] = _number(component.get("streamwise_x_mm"),
                                                ref+" saved X position (mm)")
            if "fixed_power_w" not in component and "resistive_loss" not in component:
                raise ValueError(ref+": actual dissipation must be supplied explicitly.")
            c = _number(component.get("capacity_j_k"), ref+" junction capacity", positive=True)
            rjb = _number(component.get("r_junction_board_k_w"), ref+" junction-board R", positive=True)
            power = _number(component.get("fixed_power_w", 0), ref+" fixed power", nonnegative=True)
            index = len(nodes)
            nodes.append({"id": ref, "capacity": c, "air_h": 0.0,
                          "fixed_power": power, "links": [(0, 1/rjb)],
                          "temperature_loss": None})
            nodes[0]["links"].append((index, 1/rjb))
            loss = component.get("resistive_loss")
            if loss is not None:
                current = _number(loss.get("current_a"), ref+" current", nonnegative=True)
                resistance = _number(loss.get("resistance_ref_ohm"), ref+" reference R", nonnegative=True)
                alpha = _number(loss.get("alpha_per_k"), ref+" R(T) coefficient")
                reference = _number(loss.get("reference_c"), ref+" R(T) reference")
                nodes[index]["temperature_loss"] = (current*current*resistance, alpha, reference)
            sink = component.get("isolated_sink")
            if sink is not None:
                if not sink.get("isolation_evidence"):
                    raise ValueError(ref+": electrically isolated sink needs explicit isolation_evidence.")
                if sink.get("contact_kind") == "metal_drain":
                    if not str(sink.get("drain_net", "")).strip():
                        raise ValueError(ref+": metal-drain sink needs the live drain_net.")
                    working = _number(sink.get("working_voltage_v"),
                                      ref+" drain working voltage", nonnegative=True)
                    insulation = _number(sink.get("insulation_rating_v"),
                                         ref+" insulation rating", positive=True)
                    if insulation < working:
                        raise ValueError(ref+": insulation rating is below the declared working voltage.")
                elif sink.get("contact_kind") != "generic_isolated":
                    raise ValueError(ref+": isolated sink contact_kind must be metal_drain or generic_isolated.")
                rjs = _number(sink.get("r_junction_sink_k_w"), ref+" junction-sink R", positive=True)
                cs = _number(sink.get("capacity_j_k"), ref+" sink capacity", positive=True)
                hs = _interpolate(sink.get("air_conductance_curve"),
                                  channel_flows[bi], ref+" sink hA")
                si = len(nodes)
                nodes.append({"id": ref+" sink", "capacity": cs, "air_h": hs,
                              "fixed_power": 0.0, "links": [(index, 1/rjs)]})
                nodes[index]["links"].append((si, 1/rjs))
            body = component.get("package_body")
            if body is not None:
                rb = _number(body.get("r_junction_body_k_w"),
                             ref+" junction-to-body R", positive=True)
                cb = _number(body.get("capacity_j_k"), ref+" body capacity", positive=True)
                hb = _interpolate(body.get("air_conductance_curve"),
                                  channel_flows[bi], ref+" body hA")
                body_index = len(nodes)
                nodes.append({"id": ref+" body", "capacity": cb, "air_h": hb,
                              "fixed_power": 0.0, "links": [(index, 1/rb)]})
                nodes[index]["links"].append((body_index, 1/rb))
        if len(nodes) > 100:
            raise ValueError(name+" RC network exceeds 100 nodes.")
        if topology == "parallel_passages":
            positions = sorted(set(source_positions.values()), reverse=True)
            stages = {position: index for index, position in enumerate(positions)}
            contacts = [(0, h_board/len(positions), index)
                        for index in range(len(positions))]
            for ni, node in enumerate(nodes[1:], 1):
                ref = node["id"].removesuffix(" sink").removesuffix(" body")
                if node["air_h"]:
                    contacts.append((ni, node["air_h"], stages[source_positions[ref]]))
        else:
            positions = []
            contacts = [(ni, node["air_h"], 0) for ni, node in enumerate(nodes)
                        if node["air_h"]]
        network.append({"name": name, "nodes": nodes, "boundary": boundary,
                        "contacts": contacts, "positions": positions,
                        "mass_heat_capacity_w_k": channel_flows[bi]*air_density*air_cp,
                        "flow_m3_s": channel_flows[bi]})

    previous = [[initial]*len(board["nodes"]) for board in network]
    history = []
    max_residual = 0.0
    elapsed = 0.0
    while elapsed < duration-1e-12:
        dt = min(step, duration-elapsed)
        inlet_now = inlet
        row = {"time_s": elapsed+dt, "boards": []}
        next_state = []
        for board, old in zip(network, previous):
            nodes = board["nodes"]
            temps = old[:]
            stage_means = [inlet_now]*max(1, len(board["positions"]))
            for iteration in range(80):
                matrix = [[0.0]*len(nodes) for _ in nodes]
                rhs = [0.0]*len(nodes)
                for i, node in enumerate(nodes):
                    storage = node["capacity"]/dt
                    matrix[i][i] = storage+node["air_h"]
                    air_rhs = sum(h*stage_means[stage]
                                  for ni, h, stage in board["contacts"] if ni == i)
                    rhs[i] = storage*old[i]+air_rhs+node["fixed_power"]
                    if i == 0 and board["boundary"] is not None:
                        conductance = board["boundary"]["conductance_w_k"]
                        matrix[i][i] += conductance
                        rhs[i] += conductance*board["boundary"]["temperature_c"]
                    for j, g in node["links"]:
                        matrix[i][i] += g
                        matrix[i][j] -= g
                    loss = node.get("temperature_loss")
                    if loss:
                        p0, alpha, reference = loss
                        power = p0*(1+alpha*(temps[i]-reference))
                        if power < 0:
                            raise ValueError("R(T) produces negative resistance in the solved range.")
                        rhs[i] += power
                candidate = _solve_linear(matrix, rhs)
                if any(not math.isfinite(t) or t <= -273.15 or t > 10000 for t in candidate):
                    raise ValueError("Coupled transient diverged; check boundaries and R(T) loss.")
                if topology == "parallel_passages":
                    profile = _parallel_air_profile(candidate, board["contacts"],
                                                    board["positions"], inlet_now,
                                                    board["mass_heat_capacity_w_k"])
                    new_means = [stage["mean_c"] for stage in profile]
                else:
                    new_means = stage_means
                change = max(abs(a-b) for a, b in zip(candidate, temps))
                air_change = max(abs(a-b) for a, b in zip(new_means, stage_means))
                if max(change, air_change) < 1e-8:
                    temps = candidate
                    stage_means = new_means
                    break
                temps, stage_means = candidate, new_means
            else:
                raise ValueError("Electrothermal/air iteration did not converge.")
            power = sum(node["fixed_power"] +
                        (node["temperature_loss"][0]*(1+node["temperature_loss"][1]*
                         (temps[i]-node["temperature_loss"][2]))
                         if node.get("temperature_loss") else 0.0)
                        for i, node in enumerate(nodes))
            air_w = sum(h*(temps[ni]-stage_means[stage])
                        for ni, h, stage in board["contacts"])
            fixture_w = (board["boundary"]["conductance_w_k"]*
                         (temps[0]-board["boundary"]["temperature_c"])
                         if board["boundary"] is not None else 0.0)
            stored_w = sum(node["capacity"]*(temps[i]-old[i])/dt for i, node in enumerate(nodes))
            residual = power-air_w-fixture_w-stored_w
            max_residual = max(max_residual, abs(residual))
            if abs(residual) > max(1e-8, 1e-6*max(power, 1)):
                raise ValueError("Transient energy balance exceeded tolerance.")
            if topology == "parallel_passages":
                profile = _parallel_air_profile(temps, board["contacts"],
                                                board["positions"], inlet_now,
                                                board["mass_heat_capacity_w_k"])
                outlet = profile[-1]["outlet_c"]
            else:
                profile = []
                outlet = inlet_now+air_w/board["mass_heat_capacity_w_k"]
            row["boards"].append({"name": board["name"], "inlet_air_c": inlet_now,
                                   "outlet_air_c": outlet, "power_w": power,
                                   "flow_m3_s": board["flow_m3_s"],
                                   "air_stages": profile,
                                   "air_heat_w": air_w, "fixture_heat_w": fixture_w,
                                   "stored_heat_w": stored_w,
                                   "energy_residual_w": residual,
                                   "temperatures_c": {node["id"]: temps[i]
                                                      for i, node in enumerate(nodes)}})
            next_state.append(temps)
            if topology == "serial_boards":
                inlet_now = outlet
        if topology == "parallel_passages":
            row["mixed_outlet_air_c"] = sum(
                board["outlet_air_c"]*network[index]["flow_m3_s"]
                for index, board in enumerate(row["boards"]))/sum(channel_flows)
        previous = next_state
        elapsed += dt
        history.append(row)
    checks = []
    if "max_local_air_c" in config:
        limit = _number(config["max_local_air_c"], "Local air limit")
        maximum = max([board["outlet_air_c"] for sample in history
                       for board in sample["boards"]] +
                      [stage["outlet_c"] for sample in history for board in sample["boards"]
                       for stage in board["air_stages"]])
        checks.append({"kind": "local_air", "maximum_c": maximum, "limit_c": limit,
                       "status": "PASS" if maximum <= limit else "FAIL"})
    for bi, board in enumerate(boards):
        for component in board["components"]:
            if "maximum_junction_c" not in component:
                continue
            limit = _number(component["maximum_junction_c"], "Junction limit")
            ref = str(component["reference"])
            maximum = max(sample["boards"][bi]["temperatures_c"][ref]
                          for sample in history)
            checks.append({"kind": "junction", "board": board["name"], "reference": ref,
                           "maximum_c": maximum, "limit_c": limit,
                           "status": "PASS" if maximum <= limit else "FAIL"})
    return {"model": "coupled-air lumped electrothermal RC transient",
            "status": "computed_unqualified", "model_sha256": _canonical_hash(config),
            "air_topology": topology, "air_flow_direction": config.get("air_flow_direction"),
            "blade_pitch_mm": pitch, "passage_flow_fractions": fractions,
            "passage_flow_allocation": config.get("passage_flow_allocation"),
            "fan_operating_point": flow, "max_energy_residual_w": max_residual,
            "history": history, "checks": checks,
            "check_status": ("UNKNOWN" if not checks else
                             "FAIL" if any(check["status"] == "FAIL" for check in checks)
                             else "PASS"),
            "assumptions": ["Air topology, passage flow fractions, bypass and direction are explicit inputs; the model does not derive passage flow from blade pitch.",
                            "Parallel passages use streamwise lumped air stages from high X to low X, not a CFD velocity/pressure field.",
                            "Fan P-Q, pressure loss, convection curves, heat capacities and contact resistances are explicit inputs.",
                            "This lumped RC model does not resolve copper fields, package hotspots, recirculation, radiation or CFD.",
                            "R(T) is an entered ohmic loss law, not a MOSFET linear-mode SOA model.",
                            "Numerical convergence and energy balance do not qualify installed hardware."]}


def run_saved_board_transient(config):
    """Hash all four saved KiCad boards around a read-only RC analysis."""
    boards = config.get("boards", [])
    model_config = copy.deepcopy(config)
    before = {}
    hashes_by_board = {}
    positions_by_board = {}
    for bi, board in enumerate(boards):
        path = Path(board.get("board_path", "")).resolve()
        if not path.is_file() or path.suffix.lower() != ".kicad_pcb":
            raise ValueError("Each assembly member needs a saved .kicad_pcb file.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = board.get("expected_source_sha256")
        if expected and digest != expected:
            raise ValueError("A saved board changed since its thermal inputs were reviewed.")
        import pcbnew

        loaded = pcbnew.LoadBoard(str(path))
        if loaded is None:
            raise ValueError("KiCad could not load an assembly board.")
        footprints = {fp.GetReference(): fp for fp in loaded.GetFootprints()}
        references = set(footprints)
        missing = sorted(str(component.get("reference", ""))
                         for component in board.get("components", [])
                         if component.get("reference") not in references)
        if missing:
            raise ValueError("Heat sources are not on the saved board: " + ", ".join(missing))
        if config.get("air_topology") == "parallel_passages":
            positions = {}
            for part in model_config["boards"][bi]["components"]:
                ref = part["reference"]
                native_x = pcbnew.ToMM(footprints[ref].GetPosition().x)
                if ("streamwise_x_mm" in part and
                        abs(_number(part["streamwise_x_mm"], ref+" X position")-native_x) > .5):
                    raise ValueError(ref+": supplied streamwise X differs from the saved footprint by more than 0.5 mm.")
                part["streamwise_x_mm"] = native_x
                positions[ref] = native_x
            positions_by_board[str(board.get("name", ""))] = positions
        before[str(path)] = digest
        hashes_by_board[str(board.get("name", ""))] = digest
    result = solve_coupled_transient(model_config)
    for path, digest in before.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError("A saved board changed during thermal analysis.")
    result["source_sha256"] = hashes_by_board
    result["saved_component_x_mm"] = positions_by_board
    return result
