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


def evaluate_limits(board, thermal, field_map):
    """Check solved junctions against each part's mapped minimum/maximum fields."""
    from .quick_therm import _footprint_properties

    field_map = dict(field_map or {})
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
        for key, name in field_map.items():
            raw = fields.get(name)
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
        if not field_map:
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
    return {"status": overall, "field_map": field_map, "counts": counts, "rows": rows}


def sample_probes(view, network, definitions):
    """Sample nearest valid thermal cell; never extrapolate outside board/coverage."""
    from .thermal_board_view import _on_board

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
        if view.get("outline_status") != "valid" or not _on_board((x, y), view.get("outline", [])):
            row["reason"] = "Outside a verified board outline"
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
    from .thermal_board_view import _on_board

    x, y = float(x_mm), float(y_mm)
    if side not in ("top", "bottom") or not all(map(math.isfinite, (x, y))):
        raise ValueError("Cursor needs finite coordinates and a top/bottom side.")
    output = {"x_mm": x, "y_mm": y, "side": side, "on_board": False,
              "temperature_c": None, "field_source": None,
              "reference": None, "component_id": None, "junction_c": None,
              "model_junction_c": None}
    if view.get("outline_status") != "valid" or not _on_board((x, y), view.get("outline", [])):
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
