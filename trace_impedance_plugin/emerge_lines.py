"""Validated quasi-static PCB line cross sections, ported from EMerge.

Source: wayri/EMerge src/emerge/_emerge/geo/pcb_tools/calculator.py,
revision 50283a2 (calculator validation PR #1). The scalar implementation
uses only the standard library so each KiCad PCM installs independently.
All dimensions are millimetres; outputs are ohms or relative permittivity.
"""

from __future__ import annotations

import math

ETA0 = 376.73031366857


def _geometry(*values):
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("Line geometry must be positive and finite")


def _ellipk(k):
    if k == 1.0:
        return math.inf
    a, b = 1.0, math.sqrt((1.0 - k) * (1.0 + k))
    for _ in range(48):
        a_next, b_next = (a + b) / 2, math.sqrt(a * b)
        a, b = a_next, b_next
        if abs(a - b) <= 1e-15 * a:
            break
    return math.pi / (2 * a)


def _ellip_ratio(k):
    """K(k)/K(k') with a small-modulus asymptote avoiding cancellation."""
    if not math.isfinite(k) or not 0 <= k <= 1:
        raise ValueError("Elliptic modulus must lie in [0, 1]")
    if k == 0:
        return 0.0
    if k == 1:
        return math.inf
    if k < 1e-7:
        return (math.pi / 2) / math.log(4 / k)
    complementary = math.sqrt((1 - k) * (1 + k))
    if complementary < 1e-7:
        return math.log(4 / complementary) / (math.pi / 2)
    return _ellipk(k) / _ellipk(complementary)


def _air_impedance(u):
    return (60 * math.log(8 / u + u / 4) if u <= 1 else
            120 * math.pi / (u + 1.393 + .667 * math.log(u + 1.444)))


def microstrip(width_mm, height_mm, copper_mm, er):
    """Finite-thickness microstrip; returns (Z0, epsilon_effective)."""
    w, h, t, er = map(float, (width_mm, height_mm, copper_mm, er))
    _geometry(w, h, er)
    if not math.isfinite(t) or t < 0 or t >= h or er < 1:
        raise ValueError("Copper must be nonnegative and thinner than dielectric; er >= 1")
    u = w / h
    if not .1 <= u <= 10:
        raise ValueError("Microstrip model requires 0.1 <= width/height <= 10")
    ur, factor = u, 1.0
    if t:
        tn = t / h
        x = math.sqrt(6.517 * u)
        coth = 1 / math.tanh(x)
        du1 = tn / math.pi * math.log(1 + 4 * math.e / (tn * coth * coth))
        dur = .5 * du1 * (1 + 1 / math.cosh(math.sqrt(er - 1)))
        ur = u + dur
        factor = (_air_impedance(u + du1) / _air_impedance(ur)) ** 2
    eeff = (er + 1) / 2 + (er - 1) / (2 * math.sqrt(1 + 12 / ur))
    if ur < 1:
        eeff += .02 * (1 - ur) ** 2 * (er - 1)
    eeff *= factor
    z0 = _air_impedance(ur) / math.sqrt(eeff)
    if not math.isfinite(z0) or z0 <= 0 or not 1 <= eeff <= er * (1 + 1e-12):
        raise ValueError("Microstrip estimate is outside the physical model range")
    return z0, eeff


def stripline(width_mm, plane_spacing_mm, copper_mm, er):
    """Centered homogeneous stripline; planes are equally spaced from trace."""
    w, b, t, er = map(float, (width_mm, plane_spacing_mm, copper_mm, er))
    _geometry(w, b, er)
    if not math.isfinite(t) or t < 0 or t >= b or er < 1:
        raise ValueError("Copper must be nonnegative and thinner than plane spacing; er >= 1")
    if w / b > 10:
        raise ValueError("Wide stripline is outside this screening range")
    if t == 0:
        k = 1 / math.cosh(math.pi * w / (2 * b))
        z0 = ETA0 / (4 * math.sqrt(er)) * _ellip_ratio(k)
    else:
        x = t / b
        m = 2 / (1 + (2 * x / 3) * (1 - x))
        u = w / b
        frac = (x / (2 - x)) ** 2 + ((.0796 * x) / (u + 1.1 * x)) ** m
        bc = x / (math.pi * (1 - x)) * (1 - .5 * math.log(frac))
        a = 1 / (w / (b - t) + bc)
        p = 8 * a / math.pi
        z0 = 30 / math.sqrt(er) * math.log(1 + 4 * a / math.pi * (p + math.sqrt(p * p + 6.27)))
    if not math.isfinite(z0) or z0 <= 0:
        raise ValueError("Stripline estimate is outside the physical model range")
    return z0, er


def coplanar(width_mm, ground_slot_mm, substrate_mm, er, *, backside_ground=False):
    """Zero-thickness CPW/GCPW with infinite symmetric lateral ground."""
    w, s, h, er = map(float, (width_mm, ground_slot_mm, substrate_mm, er))
    _geometry(w, s, h, er)
    if er < 1 or max(w / h, s / h) > 20:
        raise ValueError("CPW material or aspect ratio is outside the screening range")
    b = w + 2 * s
    q1 = _ellip_ratio(w / b)
    if backside_ground:
        k3 = math.tanh(math.pi * w / (4 * h)) / math.tanh(math.pi * b / (4 * h))
        q3 = _ellip_ratio(k3)
        eeff = 1 + q3 / (q1 + q3) * (er - 1)
        z0 = ETA0 / (2 * (q1 + q3) * math.sqrt(eeff))
    else:
        k2 = math.sinh(math.pi * w / (4 * h)) / math.sinh(math.pi * b / (4 * h))
        q2 = _ellip_ratio(k2)
        eeff = 1 + (er - 1) * q2 / (2 * q1)
        z0 = ETA0 / (4 * q1 * math.sqrt(eeff))
    return z0, eeff


def edge_coupled_stripline(width_mm, pair_gap_mm, plane_spacing_mm, er):
    """Zero-thickness edge-coupled symmetric stripline (Zdiff=2*Zodd)."""
    w, s, b, er = map(float, (width_mm, pair_gap_mm, plane_spacing_mm, er))
    _geometry(w, s, b, er)
    if er < 1 or max(w / b, s / b) > 10:
        raise ValueError("Coupled stripline is outside the screening range")
    x1 = math.pi * w / (2 * b)
    x2 = math.pi * (w + s) / (2 * b)
    k_prime = math.tanh(x1) / math.tanh(x2)
    k = math.sqrt((1 - k_prime) * (1 + k_prime))
    z_odd = ETA0 / (4 * math.sqrt(er)) * _ellip_ratio(k)
    if not math.isfinite(z_odd) or z_odd <= 0:
        raise ValueError("Coupled stripline modal impedance is unresolved")
    return 2 * z_odd
