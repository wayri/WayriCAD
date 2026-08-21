"""Industry-standard transmission-line models for routed copper geometry.

Closed-form references used here are the same equations published by the
industry standards and textbooks:

* IPC-2141A microstrip characteristic impedance,
* symmetric stripline impedance,
* Hammerstad approximation of effective permittivity,
* telegrapher relations linking Z0 to distributed L and C,
* skin-depth surface resistance for AC conductor loss.

``numpy`` accelerates frequency/geometry sweeps when it is importable; every
function also runs on the Python standard library alone so headless KiCad
runtimes keep working.
"""

from __future__ import annotations

import math

try:  # CODATA values via SciPy when available.
    from scipy.constants import epsilon_0 as EPS0  # type: ignore
    from scipy.constants import mu_0 as MU0  # type: ignore
except ImportError:  # pragma: no cover - SciPy is optional
    EPS0 = 8.8541878128e-12
    MU0 = 1.25663706212e-6

C_LIGHT = 299792458.0
COPPER_RESISTIVITY = 1.724e-8


def eps_effective(relative_permittivity: float, width_mm: float, height_mm: float) -> float:
    """Hammerstad effective permittivity for a microstrip."""
    er = max(float(relative_permittivity), 1.0)
    ratio = width_mm / max(height_mm, 1e-9)
    return 0.5 * (er + 1.0) + 0.5 * (er - 1.0) / math.sqrt(1.0 + 12.0 / max(ratio, 1e-6))


def z0_microstrip(width_mm: float, height_mm: float, copper_mm: float, relative_permittivity: float) -> float:
    """IPC-2141A microstrip characteristic impedance (ohm)."""
    w = max(float(width_mm), 1e-6)
    h = max(float(height_mm), 1e-6)
    t = min(max(float(copper_mm), 0.0), h)
    ratio = max(5.98 * h / (0.8 * w + t), 1.000001)
    return (87.0 / math.sqrt(max(relative_permittivity, 1.0) + 1.41)) * math.log(ratio)


def z0_stripline_symmetric(width_mm: float, height_mm: float, copper_mm: float, relative_permittivity: float) -> float:
    """Symmetric stripline characteristic impedance (ohm)."""
    w = max(float(width_mm), 1e-6)
    h = max(float(height_mm), 1e-6)
    t = min(max(float(copper_mm), 0.0), h)
    ratio = max(4.0 * h / (math.pi * 0.67 * (0.8 * w + t)), 1.000001)
    return (60.0 / math.sqrt(max(relative_permittivity, 1.0))) * math.log(ratio)


def tl_l_c_per_meter(z0_ohm: float, effective_permittivity: float) -> tuple[float, float]:
    """Distributed L (H/m) and C (F/m) from Z0 and effective permittivity."""
    z0 = max(float(z0_ohm), 1e-9)
    eeff = max(float(effective_permittivity), 1.0)
    inductance_per_m = z0 * math.sqrt(eeff) / C_LIGHT
    capacitance_per_m = math.sqrt(eeff) / (z0 * C_LIGHT)
    return inductance_per_m, capacitance_per_m


def skin_depth_m(frequency_hz: float, resistivity: float = COPPER_RESISTIVITY) -> float:
    return math.sqrt(resistivity / (math.pi * max(abs(frequency_hz), 1e-3) * MU0))


def dc_resistance_per_m(width_mm: float, copper_mm: float, resistivity: float = COPPER_RESISTIVITY) -> float:
    w = max(float(width_mm), 1e-6) / 1000.0
    t = max(float(copper_mm), 1e-6) / 1000.0
    return resistivity / (w * t)


def ac_resistance_per_m(
    frequency_mhz: float,
    width_mm: float,
    copper_mm: float,
    resistivity: float = COPPER_RESISTIVITY,
) -> float:
    """Conductor loss per metre including skin effect at ``frequency_mhz``."""
    w = max(float(width_mm), 1e-6) / 1000.0
    t = max(float(copper_mm), 1e-6) / 1000.0
    delta = skin_depth_m(float(frequency_mhz) * 1e6, resistivity)
    if delta >= t:  # Low frequency: current fills the conductor.
        return dc_resistance_per_m(width_mm, copper_mm, resistivity)
    surface_resistance = resistivity / delta
    return surface_resistance / max(w + t, 1e-9)


def solve(
    width_mm: float,
    height_mm: float,
    copper_mm: float,
    relative_permittivity: float,
    length_mm: float,
    frequency_mhz: float = 100.0,
    topology: str = "microstrip",
) -> dict:
    """Return a labelled first-order model bundle for one average route."""
    w = max(float(width_mm), 1e-6)
    h = max(float(height_mm), 1e-6)
    t = max(float(copper_mm), 1e-6)
    er = max(float(relative_permittivity), 1.0)
    name = "stripline" if str(topology).lower().startswith("strip") else "microstrip"
    if name == "stripline":
        # Symmetric planes: h spans the full plane-to-plane dielectric.
        z0 = z0_stripline_symmetric(w, h, t, er)
        eeff = er
    else:
        z0 = z0_microstrip(w, h, t, er)
        eeff = eps_effective(er, w, h)
    l_per_m, c_per_m = tl_l_c_per_meter(z0, eeff)
    length_m = max(float(length_mm), 0.0) / 1000.0
    r_dc = dc_resistance_per_m(w, t) * length_m
    r_ac = ac_resistance_per_m(frequency_mhz, w, t) * length_m
    velocity = C_LIGHT / math.sqrt(eeff)
    delay_ns = length_m / velocity * 1e9
    return {
        "model": f"IPC-2141A {name}" if name == "microstrip" else "symmetric stripline",
        "topology": name,
        "z0_ohm": z0,
        "effective_permittivity": eeff,
        "width_to_height": w / h,
        "inductance_nh": l_per_m * length_m * 1e9,
        "capacitance_pf": c_per_m * length_m * 1e12,
        "inductance_per_m_nh": l_per_m * 1e9,
        "capacitance_per_m_pf": c_per_m * 1e12,
        "resistance_dc_ohm": r_dc,
        "resistance_ac_ohm": r_ac,
        "skin_depth_um": skin_depth_m(float(frequency_mhz) * 1e6) * 1e6,
        "velocity_m_s": velocity,
        "propagation_delay_ns": delay_ns,
    }


def z0_width_sweep(
    height_mm: float,
    copper_mm: float,
    relative_permittivity: float,
    topology: str = "microstrip",
    widths_mm: "list[float] | None" = None,
) -> "list[tuple[float, float]]":
    """Synthesis insight: characteristic impedance across trace widths."""
    if widths_mm is None:
        try:
            import numpy as np

            widths = np.geomspace(0.08, 8.0, 96).tolist()
        except ImportError:
            widths = [0.08 * (100.0 ** (index / 95.0)) for index in range(96)]
    else:
        widths = list(widths_mm)
    stripline = str(topology).lower().startswith("strip")
    solver = z0_stripline_symmetric if stripline else z0_microstrip
    return [(w, solver(w, height_mm, copper_mm, relative_permittivity)) for w in widths]
