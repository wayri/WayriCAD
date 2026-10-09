"""Exact state advancement for one explicit thermal R/C path to ambient.

Units: temperatures C, resistance K/W, capacity J/K, power W, time s.
The supplied power is constant over this interval. Its energy is integrated
independently from the endpoint temperature, including inward ambient heat.
No board/package capacity or spatial temperature field is inferred.
"""
from __future__ import annotations

import math


def _number(value, label, *, positive=False, nonnegative=False):
    if isinstance(value, bool):
        raise ValueError(label+' must be finite.')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label+' must be finite.') from exc
    if not math.isfinite(result) or positive and result <= 0 or nonnegative and result < 0:
        raise ValueError(label+' is outside its finite physical range.')
    return result


def advance_thermal_rc(temperature_c, ambient_c, resistance_K_W,
                       capacitance_J_K, power_W, elapsed_s):
    """Return exact endpoint state and input/ambient/stored energy in joules."""
    start = _number(temperature_c, 'Initial temperature')
    ambient = _number(ambient_c, 'Ambient temperature')
    if min(start, ambient) < -273.15:
        raise ValueError('Temperature must be at least absolute zero.')
    resistance = _number(resistance_K_W, 'Thermal resistance', positive=True)
    capacity = _number(capacitance_J_K, 'Thermal capacity', positive=True)
    power = _number(power_W, 'Interval power', nonnegative=True)
    elapsed = _number(elapsed_s, 'Thermal interval', positive=True)
    tau = resistance * capacity
    if not math.isfinite(tau) or tau <= 0:
        raise ValueError('Thermal R/C time scale cannot be resolved in finite arithmetic.')
    u = elapsed / tau
    if u == 0:
        raise ValueError('Thermal interval is below floating-point time resolution.')
    change = -math.expm1(-u)
    decay = math.exp(-u)
    if u < 1e-4:
        lag = u*(.5+u*(-1/6+u*(1/24+u*(-1/120+u/720))))
    else:
        lag = 1-change/u
    target = ambient + resistance*power
    end = start+(target-start)*change if change <= .5 else target+(start-target)*decay
    input_j = power*elapsed
    outward = math.fsum((capacity*(start-ambient)*change, input_j*lag))
    # Use the unrounded increment for the energy ledger. End-start can lose a
    # very small temperature rise on a large absolute-temperature baseline.
    stored = capacity*(target-start)*change
    residual = math.fsum((input_j, -outward, -stored))
    values = (target, end, input_j, outward, stored, residual)
    if not all(math.isfinite(value) for value in values):
        raise ValueError('Thermal state/energy overflowed; check explicit units and scales.')
    return dict(temperature_c=end, input_J=input_j, to_ambient_J=outward,
                stored_change_J=stored, residual_J=residual,
                relative_residual=abs(residual)/max(abs(input_j)+abs(outward)+abs(stored), 1e-300))
