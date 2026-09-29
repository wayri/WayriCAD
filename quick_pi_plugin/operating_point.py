"""Voltage-driven DC load and current-sweep calculations for a linear PI mesh.

The mesh provides a one-ampere path resistance at fixed material temperature.
Only the explicit diode forward drop is current dependent; no transient or
electrothermal feedback is implied.
"""
from __future__ import annotations

import math

from .series_models import forward_drop


def path_drop(current_a, linear_path_ohm, branches=()):
    current = float(current_a)
    resistance = float(linear_path_ohm)
    if not math.isfinite(current) or current < 0 or not math.isfinite(resistance) or resistance < 0:
        raise ValueError('Current and linear path resistance must be finite and nonnegative.')
    fixed = sum(float(branch['fixed_drop_v']) for branch in branches if 'fixed_drop_v' in branch)
    diode = sum(forward_drop(branch, current) for branch in branches if 'diode' in branch) if current > 0 else 0.
    return current * resistance + fixed + diode


def load_current(source_voltage_v, linear_path_ohm, load_ohm, branches=()):
    """Solve Vs = path_drop(I) + I*Rload for a positive forward-biased DC current."""
    source = float(source_voltage_v)
    load = float(load_ohm)
    resistance = float(linear_path_ohm)
    if not all(map(math.isfinite, (source, load, resistance))) or source <= 0 or load <= 0 or resistance < 0:
        raise ValueError('Source voltage and load resistance must be finite and positive; path resistance must be nonnegative.')
    fixed = path_drop(0., resistance, branches)
    if source <= fixed:
        raise ValueError('Source voltage cannot forward-bias the specified fixed-drop path at a positive load current.')
    lo, hi = 0., source / (resistance + load)
    for _ in range(80):
        mid = (lo + hi) / 2
        if path_drop(mid, resistance, branches) + mid * load > source:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def current_sweep(source_voltage_v, linear_path_ohm, branches, currents_a):
    source = float(source_voltage_v)
    if not math.isfinite(source):
        raise ValueError('Source voltage must be finite.')
    rows = []
    for raw in currents_a:
        current = float(raw)
        if not math.isfinite(current) or current <= 0:
            raise ValueError('Sweep currents must be finite and positive.')
        branch_rows = []
        for branch in branches:
            if 'fixed_drop_v' in branch or 'diode' in branch:
                branch_rows.append({'id': branch.get('id'), 'model': 'diode' if 'diode' in branch else 'fixed_drop',
                                    'forward_drop_V': forward_drop(branch, current)})
        drop = path_drop(current, linear_path_ohm, branches)
        rows.append({'current_A': current, 'path_drop_V': drop, 'sink_voltage_V': source-drop,
                     'negative_sink_voltage': source-drop < 0, 'components': branch_rows})
    return rows
