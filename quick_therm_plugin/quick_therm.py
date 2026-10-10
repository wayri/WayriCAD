"""Bounded, read-only board thermal screening from mapped footprint fields.

This is a lumped steady-state estimate, not a spatial thermal or transient solve.
No nominal component power or thermal resistance is invented. Results are scoped
to the selected footprints and carry explicit coverage and model assumptions.
"""
from __future__ import annotations

import math
import re
from typing import Mapping


_QUANTITY = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\d]*)\s*$")
_UNITS = {
    "power_w": {"": 1.0, "W": 1.0, "mW": 1e-3, "uW": 1e-6, "µW": 1e-6},
    "theta_ja_air_k_per_w": {"": 1.0, "K/W": 1.0, "°C/W": 1.0, "C/W": 1.0},
    "theta_jb_k_per_w": {"": 1.0, "K/W": 1.0, "°C/W": 1.0, "C/W": 1.0},
    "theta_jc_k_per_w": {"": 1.0, "K/W": 1.0, "°C/W": 1.0, "C/W": 1.0},
}
_SINK_SHAPES = frozenset(("straight_fin", "pin_fin", "radial_fin", "plate", "resistance_only"))
_FIELD_ALIASES = {
    "power_w": {"powerw", "power", "dissipation", "dissipationw", "powerdissipation", "powerdissipationw"},
    "theta_ja_air_k_per_w": {"rthetaja", "thetaja", "rja", "rthetajakperw", "thetajakperw"},
    "theta_jb_k_per_w": {"rthetajb", "thetajb", "rjb", "rthetajbkperw", "thetajbkperw"},
    "theta_jc_k_per_w": {"rthetajc", "thetajc", "rjc", "rthetajckperw", "thetajckperw"},
}


def restored_field_mapping(field_names, previous=None):
    """Keep explicit mappings and suggest only one unambiguous saved alias."""
    names = list(dict.fromkeys(str(name) for name in field_names))
    previous = previous or {}
    result = {}
    for quantity, aliases in _FIELD_ALIASES.items():
        if previous.get(quantity) in names:
            result[quantity] = previous[quantity]
            continue
        candidates = [name for name in names if re.sub(r"[\s_()\-/]", "", name.casefold().replace("θ", "theta")) in aliases]
        result[quantity] = candidates[0] if len(candidates) == 1 else ""
    return result


def _finite(value, label, *, positive=False):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result) or (result <= 0 if positive else result < 0):
        bound = "positive" if positive else "nonnegative"
        raise ValueError(f"{label} must be finite and {bound}.")
    return result


def parse_field_quantity(value, quantity):
    """Parse a footprint field; bare numbers use the units named by quantity."""
    if quantity not in _UNITS:
        raise ValueError(f"Unsupported QuickTherm quantity: {quantity}")
    match = _QUANTITY.fullmatch(str(value))
    unit = re.sub(r"\s", "", match.group(2)).replace("μ", "µ") if match else None
    if match is None or unit not in _UNITS[quantity]:
        units = "W, mW or µW" if quantity == "power_w" else "K/W or °C/W"
        raise ValueError(f"Expected {quantity} as a number in {units}; received {str(value)!r}.")
    return _finite(float(match.group(1)) * _UNITS[quantity][unit], quantity,
                   positive=quantity != "power_w")


def _footprint_properties(footprint):
    """Read saved footprint custom properties without importing pcbnew at module load."""
    if hasattr(footprint, "GetFieldsText"):
        properties = footprint.GetFieldsText()
    elif hasattr(footprint, "GetFields"):
        properties = {field.GetName(): field.GetText() for field in footprint.GetFields()}
    else:
        raise ValueError("This KiCad footprint binding does not expose saved fields.")
    try:
        return {str(key): str(value) for key, value in dict(properties).items()}
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("KiCad did not return readable footprint fields.") from exc


def extract_mapped_components(board, field_map: Mapping[str, str], *, references=None,
                              required_quantities_by_reference=None):
    """Extract only mapped, saved fields from a loaded KiCad board.

    `references` scopes analysis to known dissipating components. Every included
    reference is reported, including those with absent or invalid fields.
    """
    if not hasattr(board, "GetFootprints"):
        raise ValueError("Pass a loaded KiCad board with GetFootprints().")
    if not isinstance(field_map, Mapping) or not field_map.get("power_w"):
        raise ValueError("Map power_w to a saved footprint field name.")
    for key, name in field_map.items():
        if key not in _UNITS or not isinstance(name, str) or not name.strip():
            raise ValueError(f"Invalid field mapping for {key}.")
    wanted = None if references is None else {str(ref).strip() for ref in references}
    if wanted is not None and (not wanted or "" in wanted):
        raise ValueError("Select at least one nonempty component reference.")
    result = []
    seen = set()
    for footprint in board.GetFootprints():
        reference = str(footprint.GetReference())
        if "*" in reference:
            continue
        if wanted is not None and reference not in wanted:
            continue
        if reference in seen:
            raise ValueError(f"Duplicate footprint reference: {reference}")
        seen.add(reference)
        fields = _footprint_properties(footprint)
        row = {"reference": reference, "values": {}, "issues": [], "source_fields": {}}
        quantities = (required_quantities_by_reference.get(reference, tuple(field_map))
                      if required_quantities_by_reference is not None else tuple(field_map))
        for quantity in quantities:
            if quantity not in field_map:
                row["issues"].append(f"Missing field mapping for {quantity}")
                continue
            field_name = field_map[quantity]
            raw = fields.get(field_name)
            row["source_fields"][quantity] = field_name
            if raw is None or not str(raw).strip():
                row["issues"].append(f"Missing {field_name} ({quantity})")
                continue
            try:
                row["values"][quantity] = parse_field_quantity(raw, quantity)
            except ValueError as exc:
                row["issues"].append(f"{field_name}: {exc}")
        result.append(row)
    if wanted is not None and wanted - seen:
        raise ValueError("Selected references absent from saved board: " + ", ".join(sorted(wanted-seen)))
    return sorted(result, key=lambda row: row["reference"])


def _normalize_heatsinks(heatsinks, environment):
    if heatsinks is None:
        return {}
    if not isinstance(heatsinks, Mapping):
        raise ValueError("Heatsinks must map component references to definitions.")
    theta_key = "theta_sa_air_k_per_w" if environment == "air" else "theta_sa_vacuum_k_per_w"
    normalized = {}
    for ref, config in heatsinks.items():
        reference = str(ref).strip()
        if not reference or reference in normalized or not isinstance(config, Mapping):
            raise ValueError("Each heatsink needs a unique component reference and settings.")
        shape = str(config.get("shape", ""))
        if shape not in _SINK_SHAPES:
            raise ValueError(f"{reference}: choose a supported heatsink shape.")
        allowed = {"shape", "width_mm", "height_mm", "depth_mm", "contact_k_per_w",
                   "theta_sa_air_k_per_w", "theta_sa_vacuum_k_per_w"}
        unknown = set(config) - allowed
        if unknown:
            raise ValueError(f"{reference}: unsupported heatsink settings: {', '.join(sorted(unknown))}")
        entry = {"shape": shape,
                 "contact_k_per_w": _finite(config.get("contact_k_per_w"),
                     f"{reference} contact resistance (K/W)", positive=True),
                 theta_key: _finite(config.get(theta_key),
                     f"{reference} {theta_key}", positive=True)}
        for dimension in ("width_mm", "height_mm", "depth_mm"):
            raw = config.get(dimension)
            if raw is None and shape == "resistance_only":
                entry[dimension] = None
            else:
                entry[dimension] = _finite(raw, f"{reference} {dimension}", positive=True)
        normalized[reference] = entry
    return normalized


def simulate_steady_state(components, *, environment, ambient_c,
                          vacuum_board_to_environment_k_per_w=None, heatsinks=None):
    """Estimate junction temperatures for mapped components.

    Air: Tj = Ta + P * RthetaJA_air, independent components. The supplied RJA
    must characterize the actual board and airflow; package datasheet values
    may differ drastically. Vacuum: Tb = Ta + sum(P) * Rboard_environment and
    Tj = Tb + P * RthetaJB. The board-environment value must account for the
    actual conductive/radiative sink, with no gas convection contribution.
    """
    if environment not in ("air", "vacuum"):
        raise ValueError("Environment must be 'air' or 'vacuum'.")
    try:
        ambient = float(ambient_c)
    except (TypeError, ValueError) as exc:
        raise ValueError("Ambient temperature must be finite in °C.") from exc
    if not math.isfinite(ambient) or ambient < -273.15:
        raise ValueError("Ambient temperature must be finite and at least −273.15 °C.")
    rows = list(components)
    if not rows:
        raise ValueError("No components are in the selected thermal scope.")
    sinks = _normalize_heatsinks(heatsinks, environment)
    references = {str(item.get("reference", "")).strip() for item in rows}
    if set(sinks) - references:
        raise ValueError("Heatsink references absent from thermal scope: " +
                         ", ".join(sorted(set(sinks) - references)))
    board_quantity = "theta_ja_air_k_per_w" if environment == "air" else "theta_jb_k_per_w"
    valid = []
    excluded = []
    seen = set()
    for item in rows:
        reference = str(item.get("reference", "")).strip()
        if not reference or reference in seen:
            raise ValueError("Each thermal component needs a unique nonempty reference.")
        seen.add(reference)
        values = item.get("values", {})
        issues = list(item.get("issues", []))
        required = ("power_w", "theta_jc_k_per_w" if reference in sinks else board_quantity)
        missing = [key for key in required if key not in values]
        issues.extend(f"Missing {key}" for key in missing if not any(key in issue for issue in issues))
        if issues:
            excluded.append({"reference": reference, "issues": issues})
            continue
        power = _finite(values["power_w"], f"{reference} power (W)")
        resistance = _finite(values[required[1]], f"{reference} {required[1]}", positive=True)
        if reference in sinks:
            sink = sinks[reference]
            theta_key = "theta_sa_air_k_per_w" if environment == "air" else "theta_sa_vacuum_k_per_w"
            resistance += sink["contact_k_per_w"] + sink[theta_key]
        valid.append({"reference": reference, "power_w": power,
                      "resistance_k_per_w": resistance, "heat_path": "heatsink" if reference in sinks else "board",
                      **({"heatsink": sinks[reference]} if reference in sinks else {})})
    if environment == "vacuum" and excluded:
        raise ValueError("Vacuum result needs complete power and mapped thermal fields for every scoped "
                         "component; missing: " + ", ".join(row["reference"] for row in excluded))
    if not valid:
        raise ValueError("No scoped components have the required mapped thermal fields.")
    total_power = math.fsum(row["power_w"] for row in valid)
    board_power = math.fsum(row["power_w"] for row in valid if row["heat_path"] == "board")
    if environment == "vacuum" and any(row["heat_path"] == "board" for row in valid):
        board_r = _finite(vacuum_board_to_environment_k_per_w,
                          "Vacuum board-to-environment resistance (K/W)", positive=True)
    else:
        board_r = None
    board_c = ambient + board_power * board_r if board_r is not None else None
    if board_c is not None and not math.isfinite(board_c):
        raise ValueError("Board temperature estimate overflowed; check mapped units and resistance.")
    results = []
    for row in valid:
        rise_local = row["power_w"] * row["resistance_k_per_w"]
        base = board_c if row["heat_path"] == "board" and board_c is not None else ambient
        junction = base + rise_local
        if not math.isfinite(junction):
            raise ValueError("Thermal estimate overflowed; check mapped units and resistances.")
        results.append({**row, "junction_c": junction, "rise_above_ambient_k": junction-ambient,
                        "rise_local_k": rise_local})
    return {"model": "steady-state lumped thermal screen", "environment": environment,
            "ambient_c": ambient, "board_c": board_c,
            "vacuum_board_to_environment_k_per_w": board_r,
            "total_scoped_power_w": total_power, "board_path_power_w": board_power,
            "coverage": {"scoped": len(rows), "solved": len(valid), "excluded": excluded,
                         "complete": not excluded},
            "components": sorted(results, key=lambda row: row["junction_c"], reverse=True),
            "assumptions": (
                ["Air RÎ¸JA is a user-supplied component-to-ambient resistance for this board and airflow.",
                 "Components are thermally independent; no board temperature field or coupling is solved."]
                if environment == "air" else
                ["Scoped components without heatsinks enter one isothermal board node through user-supplied RÎ¸JB.",
                 "The supplied board-to-environment resistance represents actual radiation/conduction in vacuum.",
                 "Gas convection is excluded; unscoped heat sources are excluded."]) +
            (["Each defined heatsink is an independent junction-to-case, contact, and sink-to-environment path.",
              "A heatsink component's power is excluded from the shared board node; parallel board conduction is not modeled.",
              "Heatsink shape and dimensions describe visualization only; resistance is never inferred from them."]
             if sinks else [])}


def analyze_board(board, field_map, *, environment, ambient_c,
                  references=None, vacuum_board_to_environment_k_per_w=None, heatsinks=None):
    """One-call read-only extraction and thermal estimate for UI/CLI adapters."""
    if not isinstance(field_map, Mapping):
        raise ValueError("Map saved footprint field names before running QuickTherm.")
    if environment not in ("air", "vacuum"):
        raise ValueError("Environment must be 'air' or 'vacuum'.")
    sinks = _normalize_heatsinks(heatsinks, environment)
    required = "theta_ja_air_k_per_w" if environment == "air" else "theta_jb_k_per_w"
    active_map = {key: field_map[key] for key in ("power_w", required, "theta_jc_k_per_w")
                  if key in field_map}
    components = extract_mapped_components(board, active_map, references=references,
        required_quantities_by_reference={str(fp.GetReference()):
            ("power_w", "theta_jc_k_per_w" if str(fp.GetReference()) in sinks else required)
            for fp in board.GetFootprints()})
    if any(row["reference"] not in sinks for row in components) and required not in field_map:
        raise ValueError(f"Map {required} for components without heatsinks.")
    if sinks and "theta_jc_k_per_w" not in field_map:
        raise ValueError("Map theta_jc_k_per_w for components with heatsinks.")
    result = simulate_steady_state(components, environment=environment, ambient_c=ambient_c,
                                   vacuum_board_to_environment_k_per_w=vacuum_board_to_environment_k_per_w,
                                   heatsinks=sinks)
    result["field_map"] = dict(field_map)
    result["references"] = None if references is None else sorted({str(ref) for ref in references})
    return result


def analyze_manual_board(board, values_by_reference, *, environment, ambient_c,
                         references, vacuum_board_to_environment_k_per_w=None,
                         heatsinks=None):
    """Screen explicitly entered component values without changing the saved PCB."""
    if not isinstance(values_by_reference, Mapping):
        raise ValueError("Enter power and thermal resistance for each selected component.")
    selected = [str(ref).strip() for ref in references or ()]
    if not selected or any(not ref for ref in selected) or len(set(selected)) != len(selected):
        raise ValueError("Select distinct dissipating components before entering thermal values.")
    board_refs = {str(fp.GetReference()) for fp in board.GetFootprints()
                  if "*" not in str(fp.GetReference())}
    missing_refs = set(selected) - board_refs
    if missing_refs:
        raise ValueError("Selected references absent from saved board: " + ", ".join(sorted(missing_refs)))
    sinks = _normalize_heatsinks(heatsinks, environment)
    quantity = "theta_ja_air_k_per_w" if environment == "air" else "theta_jb_k_per_w"
    rows = []
    for ref in selected:
        raw = values_by_reference.get(ref)
        if not isinstance(raw, Mapping):
            raise ValueError(f"{ref}: enter explicit power and thermal resistance.")
        required = "theta_jc_k_per_w" if ref in sinks else quantity
        values = {}
        for key in ("power_w", required):
            if key not in raw or str(raw[key]).strip() == "":
                raise ValueError(f"{ref}: enter {key}; no default is assumed.")
            try:
                values[key] = parse_field_quantity(raw[key], key)
            except ValueError as exc:
                raise ValueError(f"{ref}: {exc}") from exc
        rows.append({"reference": ref, "values": values, "issues": [],
                     "source_fields": {key: "Manual entry" for key in values}})
    result = simulate_steady_state(rows, environment=environment, ambient_c=ambient_c,
                                   vacuum_board_to_environment_k_per_w=vacuum_board_to_environment_k_per_w,
                                   heatsinks=sinks)
    result["field_map"] = {}
    result["references"] = sorted(selected)
    result["input_source"] = "Explicit values entered in QuickTherm; saved PCB was not modified."
    result["manual_values"] = {row["reference"]: row["values"] for row in rows}
    return result


def analyze_power_sources(board, *, environment, ambient_c, references,
                          field_map=None, manual_values=None, allow_empty=False):
    """Extract verified heat inputs without inventing a junction resistance.

    CalculiX solves a board surface field from power and its declared boundary.
    Package junction temperatures remain unknown until RÎ¸JB is supplied.
    """
    if environment not in ("air", "vacuum", "forced_air", "potting", "sealed"):
        raise ValueError("Environment must be 'air' or 'vacuum'.")
    ambient = _finite(ambient_c, "Ambient temperature")
    selected = [str(ref).strip() for ref in references or ()]
    if (not selected and not allow_empty) or len(set(selected)) != len(selected) or any(not ref for ref in selected):
        raise ValueError("Select distinct dissipating components for CalculiX.")
    if manual_values is None and not selected:
        rows=[]
    elif manual_values is None:
        if not isinstance(field_map, Mapping) or not field_map.get("power_w"):
            raise ValueError("Map the saved power field for CalculiX.")
        rows = extract_mapped_components(board, {"power_w": field_map["power_w"]},
                                         references=selected)
    else:
        board_refs = {str(fp.GetReference()) for fp in board.GetFootprints()
                      if "*" not in str(fp.GetReference())}
        missing = set(selected)-board_refs
        if missing:
            raise ValueError("Selected references absent from saved board: " + ", ".join(sorted(missing)))
        rows = []
        for ref in selected:
            raw = manual_values.get(ref, {})
            if not isinstance(raw, Mapping) or "power_w" not in raw:
                raise ValueError(f"{ref}: enter dissipated power; no default is assumed.")
            rows.append({"reference": ref,
                         "values": {"power_w": parse_field_quantity(raw["power_w"], "power_w")},
                         "issues": [], "source_fields": {"power_w": "Manual entry"}})
    valid = [{"reference": row["reference"], "power_w": row["values"]["power_w"],
              "heat_path": "board", "resistance_k_per_w": None,
              "junction_c": None, "rise_above_ambient_k": None, "rise_local_k": None,
              "source_fields": row["source_fields"]}
             for row in rows if not row["issues"]]
    excluded = [{"reference": row["reference"], "issues": row["issues"]}
                for row in rows if row["issues"]]
    return {"model": "board power sources; junction unresolved",
            "environment": environment, "ambient_c": ambient, "board_c": None,
            "vacuum_board_to_environment_k_per_w": None,
            "total_scoped_power_w": math.fsum(row["power_w"] for row in valid),
            "board_path_power_w": math.fsum(row["power_w"] for row in valid),
            "coverage": {"scoped": len(rows), "solved": 0,
                         "power_sources": len(valid), "excluded": excluded,
                         "complete": not excluded},
            "components": sorted(valid, key=lambda row: row["reference"]),
            "references": sorted(selected), "field_map": dict(field_map or {}),
            "assumptions": ["Power sources are explicit. No package junction or ambient resistance is inferred."]}
