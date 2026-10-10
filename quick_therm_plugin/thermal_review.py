"""Evaluate mapped temperature limits and read-only virtual board probes."""

from __future__ import annotations

import math
import re
from bisect import bisect_right


_TEMPERATURE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(°?C|K)?\s*$")


def parse_temperature(value):
    """Return an absolute Celsius temperature from a saved footprint field."""
    match = _TEMPERATURE.fullmatch(str(value))
    if not match:
        raise ValueError("Expected a temperature in °C or K.")
    result = float(match.group(1))
    if match.group(2) == "K":
        result -= 273.15
    if not math.isfinite(result) or result < -273.15:
        raise ValueError("Temperature must be finite and at least absolute zero.")
    return result


def evaluate_limits(board, thermal, field_map, manual_limits=None):
    """Check solved junctions against each part's mapped minimum/maximum fields."""
    from .quick_therm import _footprint_properties

    field_map = dict(field_map or {})
    manual_limits = dict(manual_limits or {})
    if any(not isinstance(values, dict) or set(values) - {"minimum_c", "maximum_c"}
           for values in manual_limits.values()):
        raise ValueError("Explicit limits need minimum_c and/or maximum_c per reference.")
    if set(field_map) - {"minimum_c", "maximum_c"}:
        raise ValueError("Only minimum_c and maximum_c may be mapped as limits.")
    if any(not isinstance(name, str) or not name.strip() for name in field_map.values()):
        raise ValueError("Temperature limit fields need nonempty saved property names.")
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    solved = {row["reference"]: row for row in thermal["components"]}
    references = thermal.get("references") or sorted(solved)
    rows = []
    for reference in references:
        fields = _footprint_properties(footprints[reference])
        issues = []
        bounds = {}
        overrides = manual_limits.get(reference, {})
        for key in set(field_map) | set(overrides):
            name = field_map.get(key, key)
            raw = overrides[key] if key in overrides else fields.get(name)
            if raw is None or not str(raw).strip():
                issues.append(f"Missing {name} ({key})")
                continue
            try:
                bounds[key] = parse_temperature(raw)
            except ValueError as exc:
                issues.append(f"{name}: {exc}")
        value = solved.get(reference, {}).get("junction_c")
        if value is None:
            issues.append("Component temperature unresolved")
        if not field_map and not overrides:
            issues.append("No temperature-limit fields mapped")
        if (bounds.get("minimum_c") is not None and bounds.get("maximum_c") is not None
                and bounds["minimum_c"] > bounds["maximum_c"]):
            issues.append("Minimum limit exceeds maximum limit")
        failures = []
        if value is not None and not issues:
            if "minimum_c" in bounds and value < bounds["minimum_c"]:
                failures.append("Below minimum")
            if "maximum_c" in bounds and value > bounds["maximum_c"]:
                failures.append("Above maximum")
        status = "UNKNOWN" if issues else "FAIL" if failures else "PASS"
        rows.append({"reference": reference, "junction_c": value,
                     "minimum_c": bounds.get("minimum_c"), "maximum_c": bounds.get("maximum_c"),
                     "status": status, "issues": issues + failures})
    counts = {status: sum(row["status"] == status for row in rows)
              for status in ("PASS", "FAIL", "UNKNOWN")}
    overall = "FAIL" if counts["FAIL"] else "UNKNOWN" if counts["UNKNOWN"] else "PASS"
    return {"status": overall, "field_map": field_map, "manual_limits": manual_limits,
            "counts": counts, "rows": rows}


def sample_probes(view, network, definitions):
    """Sample nearest valid thermal cell; never extrapolate outside board/coverage."""
    from .thermal_board_view import _on_board, _inside

    definitions = list(definitions or [])
    if len(definitions) > 256:
        raise ValueError("At most 256 thermal probes are supported.")
    labels = set()
    rows = []
    for index, probe in enumerate(definitions, 1):
        if not isinstance(probe, dict):
            raise ValueError("Each probe must be an object with x_mm, y_mm and side.")
        label = str(probe.get("label") or f"P{index}").strip()
        side = str(probe.get("side", "top")).lower()
        try:
            x, y = float(probe["x_mm"]), float(probe["y_mm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Probe x_mm and y_mm must be finite numbers.") from exc
        if not label or label in labels or side not in ("top", "bottom") or not all(map(math.isfinite, (x, y))):
            raise ValueError("Probe labels must be unique; side must be top/bottom and coordinates finite.")
        labels.add(label)
        row = {"label": label, "x_mm": x, "y_mm": y, "side": side,
               "temperature_c": None, "status": "UNKNOWN", "source": None,
               "method": "nearest cell center", "reason": None}
        if view.get("outline_status") != "valid" or not _on_board((x, y), view.get("outline", [])) or any(_inside((x,y),drill["contour_mm"]) for drill in view.get("drills", [])):
            row["reason"] = "Outside a verified board outline or inside a drilled void"
            rows.append(row)
            continue
        if network and network.get("layers"):
            field = network["layers"][0 if side == "top" else -1]
            row["source"] = "layered_board_model"
        elif network and network.get("board_field"):
            field = network["board_field"]
            row["source"] = "thin_sheet_board_model"
        else:
            field = view.get("fields_by_side", {}).get(side, {})
            row["source"] = "component_junction_interpolation"
        xs, ys, values = field.get("x_centers_mm", []), field.get("y_centers_mm", []), field.get("values_c", [])
        if field.get("status", "available") != "available" or not xs or not ys or not values:
            row["reason"] = field.get("reason") or "No supported thermal field at this position"
        else:
            column = min(range(len(xs)), key=lambda i: abs(xs[i] - x))
            line = min(range(len(ys)), key=lambda i: abs(ys[i] - y))
            value = values[line][column]
            if value is None or not math.isfinite(float(value)):
                row["reason"] = "Outside modeled or interpolated cell coverage"
            else:
                row.update(temperature_c=float(value), status="ESTIMATE")
        rows.append(row)
    return rows


def cursor_readout(view, network, x_mm, y_mm, side):
    """Inspect one visible board cell and any footprint directly under the cursor.

    The field source is explicit so an interpolated junction estimate cannot be
    mistaken for a solved board-surface temperature.
    """
    from .thermal_board_view import _on_board, _inside

    x, y = float(x_mm), float(y_mm)
    if side not in ("top", "bottom") or not all(map(math.isfinite, (x, y))):
        raise ValueError("Cursor needs finite coordinates and a top/bottom side.")
    output = {"x_mm": x, "y_mm": y, "side": side, "on_board": False,
              "temperature_c": None, "field_source": None,
              "reference": None, "component_id": None, "junction_c": None,
              "model_junction_c": None}
    if view.get("outline_status") != "valid" or not _on_board((x, y), view.get("outline", [])) or any(_inside((x,y),drill["contour_mm"]) for drill in view.get("drills", [])):
        return output
    output["on_board"] = True
    if network and network.get("layers"):
        field = network["layers"][0 if side == "top" else -1]
        output["field_source"] = field["name"] + " layer model"
    elif network and network.get("board_field"):
        field = network["board_field"]
        output["field_source"] = "thin-sheet board model"
    else:
        field = view.get("fields_by_side", {}).get(side, {})
        output["field_source"] = "junction interpolation"
    xs, ys, values = (field.get("x_centers_mm", []),
                      field.get("y_centers_mm", []), field.get("values_c", []))
    if xs and ys and values and field.get("status", "available") == "available":
        def cell_index(axis, coordinate, centers):
            edges = field.get(axis + "_edges_mm")
            if edges and len(edges) == len(centers)+1:
                index = bisect_right(edges, coordinate)-1
                return index if 0 <= index < len(centers) else None
            return min(range(len(centers)), key=lambda i: abs(centers[i]-coordinate))

        i, j = cell_index("x", x, xs), cell_index("y", y, ys)
        if i is not None and j is not None and j < len(values) and i < len(values[j]):
            value = values[j][i]
            if value is not None and math.isfinite(float(value)):
                output["temperature_c"] = float(value)
    candidates = []
    for part in view.get("components", []):
        if part.get("side") != side or not part.get("position_mm"):
            continue
        bbox = part.get("bbox_mm")
        if bbox and len(bbox) == 4:
            hit = bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]
        else:
            px, py = part["position_mm"]
            hit = math.hypot(x-px, y-py) <= 1.0
        if hit:
            px, py = part["position_mm"]
            candidates.append(((x-px)**2+(y-py)**2, part))
    if candidates:
        part = min(candidates, key=lambda item: item[0])[1]
        model = next((row for row in (network or {}).get("components", [])
                      if row["reference"] == part["reference"]), {})
        output.update(reference=part["reference"], component_id=part["id"],
                      junction_c=part.get("junction_c"),
                      model_junction_c=model.get("junction_c"))
    return output


def board_point_from_3d(axes, pixel_x, pixel_y, board_z_mm):
    """Intersect a Matplotlib screen ray with the saved board's XY plane.

    Return None for an edge-on ray. This is a viewing projection only; no PCB
    geometry is transformed or rewritten. Coordinates and plane height use mm.
    """
    import numpy as np
    from mpl_toolkits.mplot3d import proj3d

    px, py = axes.transData.inverted().transform((pixel_x, pixel_y))
    inverse = np.linalg.inv(axes.get_proj())
    near = np.asarray(proj3d.inv_transform(px, py, -1., inverse), dtype=float).reshape(3)
    far = np.asarray(proj3d.inv_transform(px, py, 1., inverse), dtype=float).reshape(3)
    direction = far - near
    if not np.all(np.isfinite(direction)) or abs(direction[2]) < 1e-10:
        return None
    point = near + direction * ((board_z_mm - near[2]) / direction[2])
    return (float(point[0]), float(point[1])) if np.all(np.isfinite(point)) else None


def transient_frame_network(network, index):
    """Return a display-only network for a stored time frame, without mutation."""
    import copy
    transient = network.get('transient') or {}
    frame = transient['frames'][index]
    spatial = transient['spatial_index']; temperatures = frame['temperatures_c']
    result = copy.deepcopy({key:value for key,value in network.items() if key != "transient"})
    cells = spatial['cells']; count = spatial['active_cells_per_layer']
    nx, ny = len(spatial['x_centers_mm']), len(spatial['y_centers_mm'])
    for layer_index, layer in enumerate(result['layers']):
        values = [[None for _ in range(nx)] for _ in range(ny)]
        for cell_index, (i,j) in enumerate(cells):
            values[j][i] = temperatures[layer_index*count+cell_index]
        layer['values_c'] = values
        known=[value for row in values for value in row if value is not None]
        layer['sampled_min_c']=min(known) if known else None
        layer['sampled_max_c']=max(known) if known else None
    result['display_time_s'] = frame['time_s']
    schedules=transient.get('power_schedules',{})
    originals={row['reference']:row for row in result.get('components',[])}
    components=[]
    for definition in transient.get('components',[]):
        reference=definition['reference'];row=originals.get(reference,{'reference':reference})
        contact=sum(temperatures[node]*weight for node,weight in definition['nodes'])
        points=schedules.get(reference)
        if points:
            if transient.get('schedule_interpolation','linear')=='step':
                import bisect
                scale=points[max(0,bisect.bisect_right([p[0] for p in points],frame['time_s'])-1)][1]
            else:
                import numpy as np
                scale=float(np.interp(frame['time_s'],[point[0] for point in points],[point[1] for point in points]))
        else:scale=1.
        power=definition['power_w']*scale;resistance=definition.get('junction_resistance_k_per_w')
        row.update(board_site_c=contact,power_w=power)
        row['source_peak_c']=max(temperatures[node] for node,_ in definition['nodes'])
        row.pop('source_peak_cell',None)
        row['junction_peak_proxy_c']=None
        if definition.get('storage_node') is not None:
            value=temperatures[definition['storage_node']];kind=definition['temperature_kind']
            row.update(component_temperature_c=value,temperature_kind=kind,
                       body_c=value if kind=='body' else None,
                       junction_c=value if kind=='junction' else None,
                       contact_heat_w=(value-contact)/definition['resistance_k_per_w'],
                       junction_model='Explicit lumped '+kind+' RC node; no internal solid gradient')
            if definition.get('exposed_area_mm2') is not None:
                area=definition['exposed_area_mm2']*1e-6;ambient=result['ambient_c']
                row['convection_w']=area*definition['h_w_m2k']*(value-ambient)
                row['radiation_w']=area*definition['emissivity']*5.670374419e-8*((value+273.15)**4-(ambient+273.15)**4)
        else:
            row.update(junction_c=None if resistance is None else contact+power*resistance,
                       junction_model='Massless package offset from transient contact; no die heat capacity')
        row['sink_c']=contact if row.get('sink_c') is not None else None
        components.append(row)
    result['components']=components
    result['heat_balance_meaning']='Steady-state reference balance; frame heat storage and interval balances are in transient.energy_balance.'
    return result


def frame_view(view, network):
    """Copy footprint annotations to the selected result time without stale Tj."""
    import copy
    result={**view,"components":[dict(part) for part in view.get("components",[])]}
    if 'display_time_s' not in (network or {}):return result
    components={row['reference']:row for row in network.get('components',[])}
    for part in result.get('components',[]):
        row=components.get(part['reference'],{})
        part.update(junction_c=row.get('junction_c'),power_w=row.get('power_w'),solved=row.get('junction_c') is not None,
                    component_temperature_c=row.get('component_temperature_c'),temperature_kind=row.get('temperature_kind'))
    return result


def frame_limit_status(row, temperature):
    """Re-evaluate already parsed bounds against the selected time's junction."""
    if temperature is None or row.get('issues') and row.get('status')=='UNKNOWN':return 'UNKNOWN'
    low,high=row.get('minimum_c'),row.get('maximum_c')
    if low is None and high is None:return 'UNKNOWN'
    if low is not None and high is not None and low>high:return 'UNKNOWN'
    return 'FAIL' if (low is not None and temperature<low or high is not None and temperature>high) else 'PASS'
