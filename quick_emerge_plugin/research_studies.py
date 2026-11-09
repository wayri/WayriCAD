"""Research-benchmark analysis that does not require a full FEM model."""
from __future__ import annotations

import math

from .model import config_digest
from .research_antennas import get_template, rectangular_array_phases, template_digest


def _complex_pairs(values):
    return [[float(value.real), float(value.imag)] for value in values]


def solve_rectangular_array_factor(np, config, backend_info):
    """Evaluate the source paper's rectangular-array scan law.

    This deliberately excludes active phase-shifter, feed and element-pattern
    losses.  Those are measured effects in the source paper and must not be
    inferred from an ideal array factor.
    """
    advanced = config["advanced"]
    template = get_template(advanced["research_template"])
    geometry = template["geometry"]
    theta_target = float(advanced["scan_theta_deg"])
    phi_target = float(advanced["scan_phi_deg"])
    phase = rectangular_array_phases(template["id"], theta_target, phi_target)
    weights = np.asarray([complex(*pair) for pair in phase["weights_ri"]])
    frequency = geometry["frequency_ghz"] * 1e9
    wavelength = 299792458.0 / frequency
    k0 = 2.0 * math.pi / wavelength
    xs = (np.arange(geometry["count_x"]) - (geometry["count_x"] - 1) / 2.0) * geometry["pitch_x_mm"] * 1e-3
    ys = (np.arange(geometry["count_y"]) - (geometry["count_y"] - 1) / 2.0) * geometry["pitch_y_mm"] * 1e-3
    positions = np.asarray([(x, y) for y in ys for x in xs])
    theta_deg = np.linspace(-89.75, 89.75, 720)
    theta = np.deg2rad(theta_deg)
    phi = math.radians(phi_target)
    phase_space = k0 * (np.outer(np.sin(theta) * math.cos(phi), positions[:, 0]) +
                        np.outer(np.sin(theta) * math.sin(phi), positions[:, 1]))
    field = np.exp(1j * phase_space) @ weights
    magnitude = np.abs(field)
    magnitude /= max(float(magnitude.max()), 1e-30)
    peak_index = int(np.argmax(magnitude))
    peak_theta = float(theta_deg[peak_index])
    result = {
        "schema": 1,
        "backend": backend_info,
        "analysis_engine": "closed-form rectangular array factor",
        "model_scope": "published-scan-law-no-active-network",
        "config": config,
        "config_sha256": config_digest(config),
        "frequencies_hz": [frequency],
        "port_count": 0,
        "s_parameters": {},
        "research": template,
        "research_sha256": template_digest(template),
        "array_factor": {
            "theta_deg": theta_deg.tolist(),
            "normalized_magnitude": magnitude.tolist(),
            "target_theta_deg": theta_target,
            "target_phi_deg": phi_target,
            "predicted_peak_theta_deg": peak_theta,
            "scan_error_deg": peak_theta - theta_target,
            "progressive_phase_x_deg": phase["phase_x_deg"],
            "progressive_phase_y_deg": phase["phase_y_deg"],
            "weights_ri": phase["weights_ri"],
            "element_count": geometry["count_x"] * geometry["count_y"],
        },
        "assumptions": [
            "Isotropic identical elements with equal amplitude",
            "Published 40 mm pitch and 3 GHz scan law",
            "No mutual coupling, element pattern, varactor/PIN state error, feed loss or fabrication loss",
            "Measured gain is retained as source evidence and is not predicted by this array-factor result",
        ],
    }
    from .research_validation import compare_with_publication
    result["publication_comparison"] = compare_with_publication(result)
    return result


def solve_analytical_research(np, config, backend_info):
    template = get_template(config["advanced"]["research_template"])
    if template["geometry"]["kind"] == "rectangular_array_factor":
        return solve_rectangular_array_factor(np, config, backend_info)
    raise ValueError("selected research antenna requires the full-wave geometry path")
