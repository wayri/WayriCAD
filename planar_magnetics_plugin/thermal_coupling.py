"""Explicit primary-trace electrothermal screen using the bundled QuickTherm core.

No magnetic or core thermal material properties are inferred from a core name.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
from dataclasses import asdict, dataclass, replace

from .analysis import COPPER_RHO, CoilSpec, MagneticsEngine
try:
    from .wayricad_runtime.thermal_multilayer import (
        DistributedHeatSource, prepare_distributed_sources, solve_multilayer_thermal,
    )
except ModuleNotFoundError as exc:
    if exc.name != __package__ + ".wayricad_runtime":
        raise
    from wayricad_runtime.thermal_multilayer import (
        DistributedHeatSource, prepare_distributed_sources, solve_multilayer_thermal,
    )


def _number(value, name, low=None):
    value = float(value)
    if not math.isfinite(value) or (low is not None and value < low):
        raise ValueError(name + " must be finite and within its allowed range.")
    return value


@dataclass(frozen=True)
class ThermalDrive:
    mode: str = "current"
    value: float = 0.5
    reference_c: float = 20.0
    copper_alpha_per_k: float = 0.00393
    resistance_model: str = "dc"
    tolerance_c: float = 0.01
    max_iterations: int = 60
    maximum_c: float = 200.0


def input_fingerprint(result, geometry, settings, drive, layer_map, origin_mm, core_contact):
    payload = [asdict(result), geometry, settings, asdict(drive), layer_map,
               origin_mm, core_contact]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                                     default=str).encode("utf-8")).hexdigest()


def require_fresh(study, result, geometry, settings, drive, layer_map,
                  origin_mm=(0, 0), core_contact=None):
    if study["input_fingerprint"] != input_fingerprint(
            result, geometry, settings, drive, layer_map, origin_mm, core_contact):
        raise ValueError("Thermal study is stale; solve again before export.")


def rectangular_profile(width_mm, height_mm, layer_count, spacing_mm, copper_um):
    """User-declared coupon, not a saved-board geometry extraction."""
    w = _number(width_mm, "Board width", 1e-6)
    h = _number(height_mm, "Board height", 1e-6)
    spacing = _number(spacing_mm, "Layer spacing", 1e-6)
    thickness = _number(copper_um, "Copper thickness", 1e-6) / 1000
    if isinstance(layer_count, bool) or not isinstance(layer_count, int) or not 2 <= layer_count <= 16:
        raise ValueError("Declare 2 to 16 physical thermal layers.")
    if spacing <= thickness:
        raise ValueError("Layer spacing must exceed copper thickness.")
    return dict(outline_status="valid", bbox_mm=[-w/2, -h/2, w/2, h/2],
                outline=[dict(outer_mm=[[-w/2, -h/2], [w/2, -h/2],
                                       [w/2, h/2], [-w/2, h/2]], holes_mm=[])],
                layers=[dict(id=i, name=f"Layer {i}", z_mm=i*spacing,
                             thickness_mm=thickness, polygons_mm=[])
                        for i in range(layer_count)], barrels=[], mounting_holes=[])


def solve_thermal_study(result, geometry, settings, drive, layer_map,
                        origin_mm=(0, 0), core_contact=None, *, cancel=None):
    """Map primary segment rectangles, then damp a steady-state fixed point.

    core_contact, if supplied, requires power_w, layer_id and polygon_mm. It is
    a prescribed board-contact heat input, not an inferred core thermal network.
    """
    def check_cancelled():
        if cancel and cancel():
            raise InterruptedError("Magnetics thermal study cancelled.")

    def call_backend(function, *args, **kwargs):
        check_cancelled()
        parameters = inspect.signature(function).parameters
        if ("cancel" in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD
                                          for p in parameters.values())):
            kwargs["cancel"] = cancel
        value = function(*args, **kwargs)
        check_cancelled()
        return value

    check_cancelled()
    if drive.mode not in ("current", "voltage"):
        raise ValueError("Drive mode must be current or voltage.")
    value = _number(drive.value, "Drive", 0)
    reference = _number(drive.reference_c, "Reference temperature", -273.14)
    alpha = _number(drive.copper_alpha_per_k, "Copper coefficient", 0)
    tolerance = _number(drive.tolerance_c, "Temperature tolerance", 1e-8)
    ceiling = _number(drive.maximum_c, "Maximum temperature", reference)
    ambient = _number(settings.get("ambient_c"), "Ambient", -273.14)
    if (isinstance(drive.max_iterations, bool) or not isinstance(drive.max_iterations, int)
            or not 1 <= drive.max_iterations <= 100):
        raise ValueError("Iteration count must be an integer from 1 to 100.")
    if drive.resistance_model not in ("dc", "legacy_ac"):
        raise ValueError("Resistance model must be dc or legacy_ac.")
    if drive.mode == "voltage" and drive.resistance_model != "dc":
        raise ValueError("Voltage drive is resistive DC only, not an AC impedance solve.")
    if result.spec.secondary_turns:
        raise ValueError("Secondary loaded windings are unsupported; use a primary-only study.")
    if result.spec.layer_connection not in ("Series", "Parallel"):
        raise ValueError("Unknown winding connection.")
    if not isinstance(layer_map, (list, tuple)) or len(layer_map) != result.spec.layers:
        raise ValueError("Map every primary winding layer to a physical thermal layer.")
    if len(set(layer_map)) != len(layer_map):
        raise ValueError("Primary layers need distinct physical thermal layers.")
    board = copy.deepcopy(geometry)
    physical = {layer["id"]: layer for layer in board["layers"]}
    if any(layer not in physical for layer in layer_map):
        raise ValueError("Winding layer map selects an unknown thermal layer.")
    for layer in layer_map:
        if not math.isclose(float(physical[layer]["thickness_mm"]),
                            result.spec.copper_um/1000, rel_tol=1e-6):
            raise ValueError("Thermal copper thickness must match the declared winding thickness.")
    ox, oy = [_number(v, "Winding origin") for v in origin_mm]
    templates, resistances = [], []
    ac_factor = (result.resistance_ac_ohm / result.resistance_dc_ohm
                 if drive.resistance_model == "legacy_ac" else 1.0)
    divisor = result.spec.layers**2 if result.spec.layer_connection == "Parallel" else 1
    for index, segment in enumerate(result.segments):
        check_cancelled()
        if segment.winding != "Primary":
            continue
        if (isinstance(segment.layer, bool) or not isinstance(segment.layer, int)
                or not 0 <= segment.layer < len(layer_map)):
            raise ValueError("Segment selects an invalid primary winding layer.")
        length = _number(segment.length_mm, "Segment length", 1e-9)
        width = _number(segment.width_mm, "Segment width", 1e-9)
        thickness = _number(result.spec.copper_um, "Copper thickness", 1e-9)
        x0, y0, x1, y1 = [_number(v, "Segment coordinate") for v in
                           (segment.x1_mm+ox, segment.y1_mm+oy,
                            segment.x2_mm+ox, segment.y2_mm+oy)]
        nx, ny = -(y1-y0)/length*width/2, (x1-x0)/length*width/2
        polygon = [[x0+nx,y0+ny], [x1+nx,y1+ny],
                   [x1-nx,y1-ny], [x0-nx,y0-ny]]
        layer = layer_map[segment.layer]
        physical[layer].setdefault("polygons_mm", []).append(dict(outer=polygon, holes=[]))
        templates.append(DistributedHeatSource(f"primary-{index}", "planar", 0, layer, polygon))
        resistances.append(COPPER_RHO*length*1e-3/(width*1e-3*thickness*1e-6)*ac_factor/divisor)
    if not templates:
        raise ValueError("No primary trace segments are available.")
    core_power = None
    if core_contact is not None:
        core_power = _number(core_contact["power_w"], "Explicit core contact power", 0)
        templates.append(DistributedHeatSource("core-contact", "branch", core_power,
                         core_contact["layer_id"], core_contact["polygon_mm"]))
    support = call_backend(prepare_distributed_sources, board, settings, templates)
    temperatures = [ambient]*len(resistances)
    history = []
    for iteration in range(1, drive.max_iterations+1):
        check_cancelled()
        factors = [1+alpha*(t-reference) for t in temperatures]
        if min(factors) <= 0:
            raise ValueError("Copper resistance law is nonpositive at this temperature.")
        local_r = [r*f for r, f in zip(resistances, factors)]
        total_r = math.fsum(local_r)
        current = value if drive.mode == "current" else value/total_r
        sources = [replace(s, power_w=current**2*r)
                   for s, r in zip(templates, local_r)]
        if core_contact is not None:
            sources.append(templates[-1])
        thermal = call_backend(solve_multilayer_thermal, board, {}, {"components": [],
            "environment": settings.get("environment", "air")}, settings,
            distributed_sources=sources, prepared_sources=support)
        check_cancelled()
        updated = [s["temperature_c"] for s in thermal["distributed_sources"][:len(local_r)]]
        peak = max(layer["sampled_max_c"] for layer in thermal["layers"])
        if peak > ceiling or not all(math.isfinite(t) for t in updated):
            raise ValueError("Thermal study exceeds its temperature validity ceiling.")
        delta = max(abs(a-b) for a, b in zip(updated, temperatures))
        history.append(dict(iteration=iteration, delta_c=delta, current_a=current,
                            trace_power_w=current**2*total_r))
        if thermal["status"] != "converged":
            raise ValueError("Shared thermal kernel did not balance heat.")
        if delta <= tolerance:
            break
        temperatures = [(a+b)/2 for a, b in zip(updated, temperatures)]
    else:
        raise ValueError("Electrothermal iteration did not converge; no valid study produced.")
    check_cancelled()
    active_temperatures = [[value for row in layer["values_c"] for value in row
                            if value is not None] for layer in thermal["layers"]]
    winding_peak = max(active_temperatures[li][ci]
                       for source in thermal["distributed_sources"][:len(resistances)]
                       for li, ci, weight in source["support_weights"] if weight > 0)
    return dict(input_fingerprint=input_fingerprint(result, geometry, settings, drive,
                layer_map, origin_mm, core_contact), status="converged", thermal=thermal,
                inputs=dict(coil=asdict(result.spec), geometry=geometry, settings=settings,
                            drive=asdict(drive), layer_map=layer_map, origin_mm=origin_mm,
                            core_contact=core_contact),
                winding_mean_c=math.fsum(t*r for t,r in zip(updated,resistances))/math.fsum(resistances),
                winding_peak_c=winding_peak, winding_segment_peak_c=max(updated),
                current_a=current, resistance_ohm=total_r,
                trace_loss_w=current**2*total_r, core_contact_power_w=core_power,
                magnetic_core_loss_estimate_w=result.core_loss_w if result.core.loss_k > 0 else None,
                history=history, assumptions=[
                    "User-declared geometry/material/boundaries; no saved-board extraction implied.",
                    "Primary trace loss only; via/pad/terminal Joule heat and secondary load excluded.",
                    "Copper rho=1.724e-8 ohm m at the explicitly chosen reference temperature.",
                    "Series current is uniform; parallel layers assume equal current sharing, not a branch solve.",
                    "Legacy AC multiplier, when selected, is frozen; voltage mode is DC resistive only.",
                    "Core contact is prescribed heat entering the board, not core temperature or inferred contact resistance.",
                    "No inferred core conductivity, eddy loss, temperature-dependent magnetic loss or qualified 3D model.",
                    "Segment rectangles are cell-sampled for conduction; narrow traces/corners need grid sensitivity review."])


def main(argv=None):
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Explicit magnetics multilayer electrothermal screen")
    parser.add_argument("input", help="JSON: coil, geometry, settings, drive, layer_map; optional origin_mm/core_contact")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = MagneticsEngine.analyze(CoilSpec(**data["coil"]))
    geometry = (data["geometry"] if "geometry" in data else
                rectangular_profile(**data["profile"]))
    study = solve_thermal_study(result, geometry, data["settings"],
                              ThermalDrive(**data["drive"]), data["layer_map"],
                              data.get("origin_mm", (0, 0)), data.get("core_contact"))
    with Path(args.output).open("x", encoding="utf-8") as stream:
        json.dump(study, stream, indent=2, allow_nan=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
