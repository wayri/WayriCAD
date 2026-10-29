"""Validated inputs and scalar results for Quick EMerge studies."""

import hashlib
import json
import math
from pathlib import Path

DEFAULT_CONFIG = {
    "mode": "patch", "f_start_hz": 1.55e9, "f_stop_hz": 1.60e9,
    "points": 81, "substrate_x_mm": 100, "substrate_y_mm": 100,
    "thickness_mm": 1.524, "er": 3.38, "patch_width_mm": 53,
    "patch_length_mm": 52, "feed_width_mm": 3.2, "inset_width_mm": 7,
    "inset_length_mm": 15.5, "line_length_mm": 30, "line_width_mm": 3.2,
    "air_margin_mm": 30, "mesh_edge_mm": 2, "resolution": 0.2,
    "field_z_mm": 2, "field_grid": 81, "z0_ohm": 50,
    "solver": "SUPERLU", "sweep": "linear", "adaptive_steps": 0,
    "convergence": 0.02, "max_tets": 250000,
    "rule_area_id": "", "signal_net": "", "reference_net": "", "region_er_reviewed": False, "advanced": {},
}


def validate_config(raw):
    """Return a complete normalized configuration or raise ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("configuration must be a dictionary")
    unknown = set(raw) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError("unknown configuration keys: " + ", ".join(sorted(unknown)))
    config = {**DEFAULT_CONFIG, **raw}
    if config["mode"] not in ("patch", "pcb_line", "pcb_region"):
        raise ValueError("mode must be patch, pcb_line or pcb_region")
    for key in ('rule_area_id', 'signal_net', 'reference_net'):
        if not isinstance(config[key], str):
            raise ValueError(key+' must be a string')
    if type(config['region_er_reviewed']) is not bool:
        raise ValueError('region_er_reviewed must be boolean')
    if config['mode'] == 'pcb_region' and (not all(config[k].strip() for k in ('rule_area_id', 'signal_net', 'reference_net')) or
                                          not config['region_er_reviewed']):
        raise ValueError('Select a rule area, signal/reference nets and review the entered dielectric permittivity.')
    if config["solver"] not in ("SUPERLU", "PARDISO", "UMFPACK", "AASDS", "CUDSS", "SPARTA"):
        raise ValueError("unknown solver")
    if config["sweep"] not in ("linear", "adaptive"):
        raise ValueError("unknown sweep")
    for key in DEFAULT_CONFIG:
        if key in ("mode", "solver", "sweep", "rule_area_id", "signal_net", "reference_net", "region_er_reviewed", "advanced"):
            continue
        value = config[key]
        if isinstance(value, bool):
            raise ValueError(f"{key} must be a finite number")
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{key} must be a finite number") from None
        if not math.isfinite(value) or value < 0 or (value == 0 and key != "adaptive_steps"):
            raise ValueError(f"{key} must be finite and positive")
        if key in ("points", "field_grid", "adaptive_steps", "max_tets"):
            lower, limit = {"points": (2, 200), "field_grid": (2, 201),
                            "adaptive_steps": (0, 20), "max_tets": (100, 10000000)}[key]
            if not value.is_integer() or not lower <= value <= limit:
                raise ValueError(f"{key} must be an integer between {lower} and {limit}")
            value = int(value)
        config[key] = value
    if config["f_start_hz"] >= config["f_stop_hz"]:
        raise ValueError("frequency start must be less than stop")
    if config["sweep"] == "adaptive" and config["points"] < 5:
        raise ValueError("adaptive sweep requires at least 5 points")
    if config["field_z_mm"] >= config["air_margin_mm"]:
        raise ValueError("field plane must lie inside the air region")
    if config["resolution"] > 1:
        raise ValueError("resolution must not exceed 1")
    if config["convergence"] > 1:
        raise ValueError("convergence must not exceed 1")
    study = config["advanced"].get("study", "driven") if isinstance(config["advanced"], dict) else "driven"
    if study in ("driven", "optimization", "array") and config["mode"] == "patch":
        if (config["patch_width_mm"] >= config["substrate_x_mm"] or
                config["patch_length_mm"] >= config["substrate_y_mm"] or
                config["feed_width_mm"] + 2 * config["inset_width_mm"] >= config["patch_width_mm"] or
                config["inset_length_mm"] >= config["patch_length_mm"]):
            raise ValueError("patch and inset must fit inside the substrate")
    elif study in ('driven', 'optimization') and config['mode'] == 'pcb_line' and (config["line_length_mm"] >= config["substrate_x_mm"] or
          config["line_width_mm"] >= config["substrate_y_mm"]):
        raise ValueError("line must fit inside the substrate")
    from .advanced import validate_advanced
    config['advanced'] = validate_advanced(config['advanced'], config)
    return config


def source_identity(board_path):
    """Identify a saved KiCad board by absolute path and exact bytes."""
    path = Path(board_path).expanduser().resolve(strict=True)
    if path.suffix.lower() != ".kicad_pcb" or not path.is_file():
        raise ValueError("source must be a saved .kicad_pcb file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest()}


def config_digest(config):
    """Hash the canonical normalized configuration."""
    data = json.dumps(validate_config(config), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def metrics(frequencies, s11, z0=50):
    """Calculate sampled reflection metrics without assuming passive results."""
    if isinstance(z0, bool):
        raise ValueError("z0 must be finite and positive")
    try:
        z0 = float(z0)
        freq = [float(v) if not isinstance(v, bool) else float("nan") for v in frequencies]
        gamma = [complex(v) if not isinstance(v, bool) else complex(float("nan")) for v in s11]
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid frequency or S11 data") from None
    if not math.isfinite(z0) or z0 <= 0:
        raise ValueError("z0 must be finite and positive")
    if (not freq or len(freq) != len(gamma) or
            any(not math.isfinite(f) or f <= 0 for f in freq) or
            any(b <= a for a, b in zip(freq, freq[1:])) or
            any(not math.isfinite(g.real) or not math.isfinite(g.imag) for g in gamma)):
        raise ValueError("frequency and S11 arrays must be finite, aligned and ordered")
    magnitude = [abs(g) for g in gamma]
    db = [20 * math.log10(v) if v else -math.inf for v in magnitude]
    impedances = [z0 * (1 + g) / (1 - g) if g != 1 else None for g in gamma]
    return {
        "s11_db": db,
        "return_loss_db": [-v for v in db],
        "vswr": [(1 + v) / (1 - v) if v < 1 else None for v in magnitude],
        "impedance_real_ohm": [z.real if z is not None else None for z in impedances],
        "impedance_imag_ohm": [z.imag if z is not None else None for z in impedances],
        "resonance_hz": freq[min(range(len(freq)), key=magnitude.__getitem__)],
    }
