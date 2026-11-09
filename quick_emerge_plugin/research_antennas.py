"""Published antenna benchmarks supported by Quick EMerge.

The registry is intentionally data-only.  It records source geometry, expected
observables and model limits; executable solver construction lives in
``research_geometry``.  Values are SI unless their key names include ``_mm`` or
``_ghz``.
"""
from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import math


SCHEMA = 1


_TEMPLATES = {
    "rezaeipour-2021-dual-feed-patch": {
        "title": "2.45 GHz dual-feed multi-polarization patch",
        "citation": {
            "authors": "R. Rezaeipour and R. Sadeghzadeh",
            "title": "A Multi Polarization Square Patch Antenna with a Reconfigurable Feeding Network",
            "year": 2021,
            "doi": "10.48550/arXiv.2106.07291",
            "url": "https://arxiv.org/abs/2106.07291",
        },
        "category": ["polarization", "wifi", "ism"],
        "geometry": {
            "kind": "dual_feed_square_patch",
            "board_mm": [70.0, 70.0],
            "board_extent_provenance": (
                "Quick EMerge solver enclosure; the paper specifies the 27 mm patch "
                "and feed dimensions, not a 70 mm substrate outline"
            ),
            "patch_side_mm": 27.0,
            "substrate_height_mm": 1.0,
            "relative_permittivity": 4.6,
            "feed_width_mm": 1.84,
            "feed_length_mm": 36.0,
        },
        "recommended_sweep_ghz": [2.30, 2.60, 31],
        "published_targets": {
            "linear_resonance_ghz": 2.45,
            "circular_resonance_ghz": 2.44,
            "circular_min_axial_ratio_db": 1.0,
            "measured_rhcp_ar_band_ghz": [2.39, 2.48],
            "measured_lhcp_ar_band_ghz": [2.36, 2.47],
        },
        "model_scope": "Radiator and orthogonal feeds; PIN-diode/Wilkinson/branch-line network omitted.",
    },
    "yang-2016-wlan-monopole": {
        "title": "2.4/5 GHz dual-band WLAN printed monopole",
        "citation": {
            "authors": "J. Yang et al.",
            "title": "Design of Miniaturized Dual-Band Microstrip Antenna for WLAN Application",
            "year": 2016,
            "doi": "10.3390/s16070983",
            "url": "https://doi.org/10.3390/s16070983",
        },
        "category": ["wifi", "wlan", "dual-band"],
        "geometry": {
            "kind": "yang_wlan_monopole",
            "board_mm": [16.0, 29.0],
            "substrate_height_mm": 1.6,
            "relative_permittivity": 4.4,
            "feed_width_mm": 3.0,
            "feed_length_mm": 14.0,
            "partial_ground_length_mm": 13.0,
            "l1_mm": 14.0, "l2_mm": 7.0, "l3_mm": 3.0,
            "l4_mm": 12.0, "l5_mm": 12.0, "l6_mm": 3.0,
        },
        "recommended_sweep_ghz": [2.20, 6.20, 81],
        "published_targets": {
            "simulated_bands_ghz": [[2.40, 2.52], [4.50, 7.50]],
            "reported_gain_dbi": {"2.45": 4.4, "5.20": 4.1, "5.80": 5.0},
        },
        "model_scope": "Published two-layer radiator and partial ground; connector/package omitted.",
    },
    "liu-2020-cubesat-yagi": {
        "title": "Printed Yagi for CubeSat S-band operation",
        "citation": {
            "authors": "S. Liu et al.",
            "title": "A Printed Yagi Antenna for CubeSat with Multi-Frequency Tilt Operation",
            "year": 2020,
            "doi": "10.3390/electronics9060986",
            "url": "https://doi.org/10.3390/electronics9060986",
        },
        "category": ["yagi", "satellite", "s-band", "cubesat"],
        "geometry": {
            "kind": "liu_cubesat_yagi",
            "board_mm": [100.0, 98.0],
            "substrate_height_mm": 0.6,
            "relative_permittivity": 4.4,
            "loss_tangent": 0.02,
            "reflector_length_mm": 58.8,
            "driven_length_mm": 58.8,
            "director_1_length_mm": 50.5,
            "director_2_length_mm": 48.8,
            "element_width_mm": 3.0,
            "element_spacing_mm": 14.6,
            "balanced_feed_width_mm": 3.0,
            "balanced_feed_gap_mm": 1.0,
            "balun_driven_x_mm": -28.43,
            "balun_outer_half_gap_mm": 2.5,
            "balun_geometry_provenance": (
                "Taper coordinates digitized from the source drawing for screening; "
                "matching claims require source-CAD or measured-fixture reconciliation"
            ),
        },
        "recommended_sweep_ghz": [2.20, 3.20, 51],
        "published_targets": {
            "deployed_90deg_band_ghz": [2.38, 2.57],
            "deployed_90deg_gain_dbi_at_2_4": 6.12,
            "tilted_10deg_band_ghz": [2.82, 3.07],
            "tilted_50deg_band_ghz": [1.30, 1.40],
        },
        "model_scope": "Planar printed radiator. CubeSat chassis and mechanical tilt states are not included.",
    },
    "verho-2023-aesa-4x4": {
        "title": "3 GHz 4x4 active electronically steered array",
        "citation": {
            "authors": "S. Verho, V. T. Nguyen and J.-Y. Chung",
            "title": "A 4 x 4 Active Antenna Array with Adjustable Beam Steering",
            "year": 2023,
            "doi": "10.3390/s23031324",
            "url": "https://doi.org/10.3390/s23031324",
        },
        "category": ["aesa", "phased-array", "s-band"],
        "geometry": {
            "kind": "rectangular_array_factor",
            "frequency_ghz": 3.0,
            "count_x": 4, "count_y": 4,
            "pitch_x_mm": 40.0, "pitch_y_mm": 40.0,
            "aperture_mm": [160.0, 160.0],
        },
        "published_targets": {
            "scan_range_deg": [0.0, 45.0],
            "maximum_steering_error_deg": 2.0,
            "measured_gain_range_dbi": [2.8, 4.7],
            "measured_peak_frequency_ghz": 2.995,
        },
        "model_scope": "Array-factor scan law and optional passive element FEM; varactor/PIN/feed losses require measured calibration data.",
    },
    "kabir-2023-cubesat-sx-shared-aperture": {
        "title": "CubeSat S/X-band circularly polarized shared aperture",
        "citation": {
            "authors": "S. S. Kabir, M. H. Khan and S. I. Latif",
            "title": "A Multi-Band Circularly Polarized-Shared Aperture Antenna for Space Applications at S and X Bands",
            "year": 2023,
            "doi": "10.3390/electronics12214439",
            "url": "https://doi.org/10.3390/electronics12214439",
        },
        "category": ["satellite", "cubesat", "s-band", "x-band", "circular-polarization"],
        "geometry": {
            "kind": "kabir_sx_shared_aperture",
            "board_mm": [60.0, 60.0],
            "duroid_5880_er": 2.2,
            "duroid_6010_er": 10.2,
            "material_permittivity_provenance": (
                "Nominal Rogers laminate values; the paper identifies RT/duroid "
                "5880 and 6010 but does not state dielectric constants in Table 1"
            ),
            "lower_layer_height_mm": 0.787,
            "upper_layer_height_mm": 0.787,
            "air_gap_mm": 16.2,
            "prs_height_mm": 2.5,
            "s_ring_length_mm": 41.7,
            "s_slot_length_mm": 13.8,
            "s_corner_perturbation_mm": 2.2,
            "slot_spacing_mm": 7.05,
            "s_feed_xy_mm": [5.7, 0.0],
            "x_patch_length_mm": 10.8,
            "x_corner_perturbation_mm": 1.0,
            "x_feed_xy_mm": [12.3, -10.4],
            "paper_axes": "x-down-y-right; solver transform (x,y)=(paper_y,-paper_x)",
        },
        "recommended_sweep_ghz": [1.95, 8.65, 135],
        "published_targets": {
            "s_band_s11_ghz": [2.013, 2.043],
            "s_band_ar_ghz": [2.013, 2.020],
            "s_band_min_ar_db_at_2_016": 1.9,
            "s_band_peak_gain_dbic": 7.7,
            "x_band_s11_ghz": [8.320, 8.530],
            "x_band_ar_ghz": [8.433, 8.500],
            "x_band_min_ar_db_at_8_460": 0.9,
            "x_band_peak_gain_dbic": 12.8,
        },
        "model_scope": "Published 60 mm stack and coax feeds. Fast presets are screening meshes; publication comparison requires mesh/air-boundary convergence.",
    },
}


def list_templates(pattern="*"):
    """Return deep-copied summaries matching an ID or category wildcard."""
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern must be a non-empty string")
    rows = []
    for template_id, value in sorted(_TEMPLATES.items()):
        searchable = [template_id, value["title"], *value["category"]]
        if any(fnmatch.fnmatchcase(item.lower(), pattern.lower()) for item in searchable):
            rows.append({"id": template_id, **copy.deepcopy(value)})
    return rows


def get_template(template_id):
    try:
        return {"schema": SCHEMA, "id": template_id, **copy.deepcopy(_TEMPLATES[template_id])}
    except KeyError:
        raise ValueError("unknown research antenna template: " + str(template_id)) from None


def template_digest(template):
    """Identify the complete recorded source geometry, targets and limits."""
    payload = json.dumps(template, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def example_config(template_id, *, screening=True):
    """Return a validated, reproducible setup for a published benchmark.

    Screening presets are intentionally coarse and cannot establish agreement
    with the paper.  Set ``screening=False`` for the documented starting point
    of a mesh/air-boundary convergence study.
    """
    from .model import validate_config

    template = get_template(template_id)
    geometry = template["geometry"]
    start, stop, points = template.get("recommended_sweep_ghz", [
        geometry.get("frequency_ghz", 3.0) * 0.9,
        geometry.get("frequency_ghz", 3.0) * 1.1,
        41,
    ])
    board = geometry.get("board_mm", geometry.get("aperture_mm", [180.0, 180.0]))
    thickness = geometry.get("substrate_height_mm", geometry.get("lower_layer_height_mm", 1.6))
    er = geometry.get("relative_permittivity", geometry.get("duroid_5880_er", 4.3))
    high_frequency = stop >= 8.0
    raw = {
        "mode": "patch",
        "f_start_hz": start * 1e9,
        "f_stop_hz": stop * 1e9,
        "points": min(int(points), 31 if screening else int(points)),
        "substrate_x_mm": board[0],
        "substrate_y_mm": board[1],
        "thickness_mm": thickness,
        "er": er,
        "air_margin_mm": 35.0 if template_id == "kabir-2023-cubesat-sx-shared-aperture" else 30.0,
        "mesh_edge_mm": (1.2 if high_frequency else 2.5) if screening else (0.45 if high_frequency else 1.0),
        "resolution": 0.35 if screening else 0.2,
        "field_z_mm": 24.0 if template_id == "kabir-2023-cubesat-sx-shared-aperture" else 2.0,
        "field_grid": 41 if screening else 81,
        "max_tets": 600000 if screening else 2500000,
        "advanced": {
            "study": "research_antenna",
            "research_template": template_id,
            "research_excitation": "auto",
            "loss_tangent": geometry.get("loss_tangent", 0.0),
        },
    }
    return validate_config(raw)


def rectangular_array_phases(template_id, theta_deg, phi_deg=0.0):
    """Return the paper scan-law phase progression and per-element weights."""
    template = get_template(template_id)
    geometry = template["geometry"]
    if geometry["kind"] != "rectangular_array_factor":
        raise ValueError("template does not define a rectangular array")
    if not all(math.isfinite(float(v)) for v in (theta_deg, phi_deg)) or abs(float(theta_deg)) >= 90:
        raise ValueError("theta must be finite and in (-90, 90) degrees")
    wavelength = 299792458.0 / (geometry["frequency_ghz"] * 1e9)
    theta, phi = math.radians(theta_deg), math.radians(phi_deg)
    phase_x = -2 * math.pi * geometry["pitch_x_mm"] * 1e-3 * math.sin(theta) * math.cos(phi) / wavelength
    phase_y = -2 * math.pi * geometry["pitch_y_mm"] * 1e-3 * math.sin(theta) * math.sin(phi) / wavelength
    weights = []
    for iy in range(geometry["count_y"]):
        for ix in range(geometry["count_x"]):
            phase = ix * phase_x + iy * phase_y
            weights.append([math.cos(phase), math.sin(phase)])
    return {
        "phase_x_deg": math.degrees(phase_x),
        "phase_y_deg": math.degrees(phase_y),
        "weights_ri": weights,
        "normalization": "unit amplitude per element",
    }


def axial_ratio_db(ex, ey):
    """Compute polarization axial ratio from two complex far-field components."""
    ex, ey = complex(ex), complex(ey)
    s0 = abs(ex) ** 2 + abs(ey) ** 2
    s1 = abs(ex) ** 2 - abs(ey) ** 2
    s2 = 2.0 * (ex * ey.conjugate()).real
    linear = math.hypot(s1, s2)
    major2, minor2 = (s0 + linear) / 2.0, (s0 - linear) / 2.0
    if s0 <= 0 or minor2 <= max(s0, 1.0) * 1e-15:
        return math.inf
    return 20.0 * math.log10(math.sqrt(major2 / minor2))


def polarization_handedness(ex, ey):
    """Return the signed Stokes-S3 label under the documented +z convention."""
    s3 = -2.0 * (complex(ex) * complex(ey).conjugate()).imag
    if abs(s3) <= 1e-15:
        return "linear-or-degenerate"
    return "positive-s3" if s3 > 0 else "negative-s3"
