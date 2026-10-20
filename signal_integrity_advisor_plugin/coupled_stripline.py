"""Homogeneous, lossless rectangular coupled strips between two ideal PEC planes.

Heights are measured from the common conductor centre to each plane. Constant
total-charge panels collocate the Dirichlet Green function in a 2D strip; the
free-space logarithmic singularity is integrated analytically. This is an
electrostatic cross-section model, not a board return-path or dielectric solver.
Only the Python standard library is required.
"""
from __future__ import annotations

import math
from functools import lru_cache

from .crosstalk import EPS0, C_MM_NS, _panel_log_distance, _rectangle_panels, _solve, _positive

# Absolute tolerance for the dimensionless modal difference. This conservative
# reporting floor is five times the relative Green quadrature tolerance and well
# above double-precision subtraction noise. It is a numerical acceptance floor,
# not a physical uncertainty bound or a promise to resolve smaller coupling.
COUPLING_NUMERICAL_FLOOR = 1e-9

# Positive abscissae and weights of the 8/16-point Gauss-Legendre rules.
_GAUSS8 = (
    (.1834346424956498, .3626837833783620),
    (.5255324099163290, .3137066458778873),
    (.7966664774136267, .2223810344533745),
    (.9602898564975363, .1012285362903763),
)
_GAUSS16 = (
    (.09501250983763744, .1894506104550685),
    (.2816035507792589, .1826034150449236),
    (.4580167776572274, .1691565193950025),
    (.6178762444026438, .1495959888165767),
    (.7554044083550030, .1246289712555339),
    (.8656312023878318, .09515851168249278),
    (.9445750230732326, .06225352393864789),
    (.9894009349916499, .02715245941175409),
)


def _quadrature(function, lo=0., hi=1., depth=0):
    """Adaptive integration, with explicit failure rather than a silent fallback."""
    mid, half = (lo + hi) / 2, (hi - lo) / 2
    def rule(nodes):
        return half * sum(weight * (function(mid - half * node) +
                                    function(mid + half * node))
                          for node, weight in nodes)
    coarse, fine = rule(_GAUSS8), rule(_GAUSS16)
    if abs(fine - coarse) <= 2e-11 * (hi - lo) + 2e-10 * abs(fine):
        return fine
    if depth == 10:
        raise ValueError("Two-plane Green-function quadrature did not converge.")
    return (_quadrature(function, lo, mid, depth + 1) +
            _quadrature(function, mid, hi, depth + 1))


def _green(point, source):
    """Dimensionless Green function for PEC planes at y=0 and y=1.

    log[(cosh(pi*dx)-cos(pi*(y+ys))) /
        (cosh(pi*dx)-cos(pi*(y-ys)))] / (4*pi).
    The equivalent log1p form avoids cancellation for weak mutual coupling.
    """
    u = math.pi * abs(point[0] - source[0])
    v = math.pi * (point[1] - source[1])
    numerator = 2 * math.sin(math.pi * point[1]) * math.sin(math.pi * source[1])
    if u > 40:
        decay = math.exp(-u)
        ratio = 2 * numerator * decay / (1 + decay * decay - 2 * math.cos(v) * decay)
    else:
        denominator = 2 * (math.sinh(u / 2) ** 2 + math.sin(v / 2) ** 2)
        ratio = numerator / denominator
    return math.log1p(ratio) / (4 * math.pi)


def _regular_part(point, source):
    """G + log(distance)/(2*pi), evaluated continuously at coincidence."""
    u = math.pi * (point[0] - source[0])
    v = math.pi * (point[1] - source[1])
    r2 = u * u + v * v
    if r2 == 0:
        denominator_factor = 1.
    else:
        sinhc = math.sinh(u / 2) / (u / 2) if u else 1.
        sinc = math.sin(v / 2) / (v / 2) if v else 1.
        denominator_factor = (u * u * sinhc * sinhc + v * v * sinc * sinc) / r2
    numerator = 2 * (math.sinh(u / 2) ** 2 +
                     math.sin(math.pi * (point[1] + source[1]) / 2) ** 2)
    return (math.log(numerator) - math.log(.5 * math.pi * math.pi * denominator_factor)) / (4 * math.pi)


def _panel_green(point, panel):
    a, b = panel
    dx, dy = b[0] - a[0], b[1] - a[1]
    centre = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    length = math.hypot(dx, dy)
    nearby = math.dist(point, centre) <= 2 * length
    kernel = _regular_part if nearby else _green
    value = _quadrature(lambda s: kernel(point, (a[0] + s * dx, a[1] + s * dy)))
    return value - _panel_log_distance(point, panel) / (2 * math.pi) if nearby else value


def _modal_capacitances(width, gap, lower, upper, thickness, er, panels):
    # Normalize by total plane spacing: 2D capacitance is scale invariant.
    total = lower + upper
    w, g, h, t = (value / total for value in (width, gap, lower, thickness))
    if t:
        first = _rectangle_panels(w, h, t, panels, 0.)
    else:
        edges = [w * (1 - math.cos(math.pi * i / panels)) / 2 for i in range(panels + 1)]
        first = [((a, h), (b, h)) for a, b in zip(edges, edges[1:])]
    # Reflection maps conductor 1 onto conductor 2. Modal symmetry then reduces
    # each solve to a single conductor without assuming a symmetric vertical stack.
    second = [((2 * w + g - a[0], a[1]), (2 * w + g - b[0], b[1])) for a, b in first]
    centres = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in first]
    self_matrix = [[_panel_green(point, panel) for panel in first] for point in centres]
    mutual = [[_panel_green(point, panel) for panel in second] for point in centres]
    rhs = [1.] * len(first)
    charges = [_solve([[a + sign * b for a, b in zip(row, cross)]
                       for row, cross in zip(self_matrix, mutual)], rhs) for sign in (1, -1)]
    return tuple(EPS0 * er * sum(charge) for charge in charges)


def _refinement(low, high):
    if any(not (math.isfinite(ce) and math.isfinite(co) and 0 < ce <= co)
           for ce, co in (low, high)):
        raise ValueError("Two-plane modes failed positivity.")
    modal = max(abs(a - b) / b for a, b in zip(low, high))
    coupling = [(co - ce) / (co + ce) for ce, co in (low, high)]
    absolute = abs(coupling[1] - coupling[0])
    relative = absolute / coupling[1] if coupling[1] > COUPLING_NUMERICAL_FLOOR else None
    return modal, absolute, relative, coupling[1]


@lru_cache(maxsize=512, typed=True)
def coupled_stripline_modes(width_mm, gap_mm, lower_height_mm, upper_height_mm,
                            epsilon_r, copper_mm=0.):
    """Return even/odd TEM modes with an explicit 2% panel-refinement gate.

    Equal rectangular conductors share a height in a homogeneous dielectric.
    Width/minimum-height is bounded to 0.1..10 and gap/minimum-height >= 0.1.
    Thickness cannot exceed width or touch either plane. Refinement measures
    discretization change, not uncertainty in the physical model assumptions.
    Coupling has its own 2% relative / 1e-9 absolute refinement gate because
    convergence of the much larger modal self capacitances does not establish
    convergence of their difference. Relative refinement is unavailable when
    coupling is at or below the absolute numerical reporting floor.
    """
    w, g, lower, upper, er = [_positive(value, name) for value, name in zip(
        (width_mm, gap_mm, lower_height_mm, upper_height_mm, epsilon_r),
        ("width", "gap", "lower height", "upper height", "Er"))]
    h = min(lower, upper)
    if er < 1 or not .1 <= w / h <= 10 or g / h < .1:
        raise ValueError("Two-plane screening requires Er >= 1, 0.1 <= width/minimum height <= 10 and gap/minimum height >= 0.1.")
    if (isinstance(copper_mm, bool) or not isinstance(copper_mm, (float, int)) or
            not math.isfinite(copper_mm) or copper_mm < 0 or copper_mm > w or copper_mm >= 2 * h):
        raise ValueError("Copper thickness must be between zero and width, without touching either reference plane.")
    calculate = lambda n: _modal_capacitances(w, g, lower, upper, copper_mm, er, n)
    low = calculate(8)
    ce, co = calculate(16)
    count = 16
    refinement, coupling_absolute, coupling_relative, coupling = _refinement(low, (ce, co))
    if refinement > .005 or (coupling_absolute > COUPLING_NUMERICAL_FLOOR and
                            (coupling_relative is None or coupling_relative > .005)):
        low = ce, co
        ce, co = calculate(32)
        count = 32
        refinement, coupling_absolute, coupling_relative, coupling = _refinement(low, (ce, co))
    if refinement > .02:
        raise ValueError("Two-plane modes failed positivity/convergence (2% panel refinement limit).")
    if coupling_absolute > COUPLING_NUMERICAL_FLOOR and (coupling_relative is None or coupling_relative > .02):
        raise ValueError("Two-plane coupling failed convergence (2% relative / 1e-9 absolute refinement limit).")
    velocity = C_MM_NS * 1e6 / math.sqrt(er)
    ze, zo = 1 / (velocity * ce), 1 / (velocity * co)
    return dict(z_even_ohm=ze, z_odd_ohm=zo, c_even_pf_m=ce * 1e12,
                c_odd_pf_m=co * 1e12, l_even_nh_m=ze / velocity * 1e9,
                l_odd_nh_m=zo / velocity * 1e9, panel_refinement_relative=refinement,
                panels_per_horizontal_face=count, copper_thickness_mm=copper_mm,
                coupling=coupling, coupling_refinement_absolute=coupling_absolute,
                coupling_refinement_relative=coupling_relative,
                coupling_numerical_floor=COUPLING_NUMERICAL_FLOOR,
                coupling_numerical_status="RESOLVED" if coupling > COUPLING_NUMERICAL_FLOOR else "BELOW_NUMERICAL_FLOOR",
                model="homogeneous-two-plane",
                lower_height_mm=lower, upper_height_mm=upper)
