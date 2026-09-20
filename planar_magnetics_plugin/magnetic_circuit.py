"""Bounded, one-dimensional magnetic circuit; no field-mesh or hysteresis claim.

B-H samples are [B in tesla, H in A/m], starting at the origin. Piecewise
linear H(B) permits exact segment inversion of NI = H(B) le + B gap / mu0.
No material extrapolation is performed beyond the supplied samples.
"""
import math

MU0 = 4e-7 * math.pi


def validate_core(core):
    for key in ('permeability', 'effective_area_mm2', 'path_length_mm', 'saturation_t'):
        value = getattr(core, key)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} must be finite and positive')
    for key in ('gap_mm', 'loss_k', 'loss_alpha', 'loss_beta'):
        value = getattr(core, key)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f'{key} must be finite and nonnegative')
    points = core.bh_points
    if not points:
        return
    if len(points) < 2 or len(points) > 4096 or tuple(points[0]) != (0, 0):
        raise ValueError('B-H table needs 2–4096 samples starting at [0, 0]')
    previous = (-1., -1.)
    for point in points:
        if len(point) != 2 or any(not math.isfinite(x) for x in point):
            raise ValueError('B-H samples must be finite [B tesla, H A/m] pairs')
        if point[0] <= previous[0] or point[1] <= previous[1]:
            raise ValueError('B and H must both increase strictly')
        previous = point
    if points[-1][0] < core.saturation_t:
        raise ValueError('B-H samples must cover the specified saturation threshold')


def operating_point(core, turns, current_a):
    validate_core(core)
    if not math.isfinite(turns) or turns <= 0 or not math.isfinite(current_a):
        raise ValueError('Turns must be positive; current must be finite')
    area, length, gap = core.effective_area_mm2 * 1e-6, core.path_length_mm * 1e-3, core.gap_mm * 1e-3
    mmf = abs(turns * current_a)
    slope = 1 / (MU0 * core.permeability)
    offset = 0.
    if core.bh_points:
        last_b, last_h = core.bh_points[-1]
        if mmf > last_h * length + last_b * gap / MU0:
            raise ValueError('Current exceeds supplied B-H data; extend the measured material table')
        for (b0, h0), (b1, h1) in zip(core.bh_points, core.bh_points[1:]):
            if mmf <= h1 * length + b1 * gap / MU0:
                slope = (h1 - h0) / (b1 - b0)
                offset = h0 - slope * b0
                break
    denominator = slope * length + gap / MU0
    field = (mmf - offset * length) / denominator
    threshold = field >= core.saturation_t
    valid = bool(core.bh_points) or not threshold
    return dict(current_a=current_a, flux_density_t=math.copysign(field, current_a),
                flux_wb=math.copysign(field * area, current_a),
                differential_inductance_h=turns * turns * area / denominator if valid else None,
                ideal_gap_force_n=field * field * area / (2 * MU0) if gap > 0 and valid else None,
                saturation_threshold_exceeded=threshold, model_valid=valid,
                model='tabulated anhysteretic B-H circuit' if core.bh_points else 'linear permeability circuit')


def current_sweep(core, turns, maximum_a, count=101):
    if not math.isfinite(maximum_a) or maximum_a <= 0 or not isinstance(count, int) or not 2 <= count <= 1001:
        raise ValueError('Sweep needs positive finite maximum current and 2–1001 samples')
    return [operating_point(core, turns, maximum_a * i / (count - 1)) for i in range(count)]


def saturation_current(core, turns):
    validate_core(core)
    if not math.isfinite(turns) or turns <= 0:raise ValueError('Turns must be positive')
    b=core.saturation_t;h=b/(MU0*core.permeability)
    for (b0,h0),(b1,h1) in zip(core.bh_points,core.bh_points[1:]):
        if b<=b1:
            h=h0+(b-b0)*(h1-h0)/(b1-b0);break
    return (h*core.path_length_mm*1e-3+b*core.gap_mm*1e-3/MU0)/turns


def transformer_flux_swing(core, primary_turns, voltage_v, on_time_us):
    """One pulse delta B. Reset and topology must be supplied by the designer."""
    validate_core(core)
    if any(not math.isfinite(v) or v <= 0 for v in (primary_turns, voltage_v, on_time_us)):
        raise ValueError('Turns, pulse voltage and on-time must be positive and finite')
    return voltage_v * on_time_us * 1e-6 / (primary_turns * core.effective_area_mm2 * 1e-6)
