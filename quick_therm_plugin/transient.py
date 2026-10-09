"""Bounded analytical transients for explicit independent thermal R/C paths.

Temperatures are °C, resistances K/W, capacities J/K, powers W and times s.
Each component obeys C dT/dt = P(t) - (T - ambient)/R. No capacitance,
component coupling, board field or electrical loss is inferred from a PCB.
"""
from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping
import math


MAX_DURATION_S = 365 * 24 * 3600
MAX_COMPONENTS = 256
MAX_SAMPLES = 10_001
MAX_COMPONENT_SAMPLES = 1_000_000


class TransientCancelled(InterruptedError):
    """A cancelled study returns no partial result."""


def _cancelled(cancel):
    if cancel is not None and cancel():
        raise TransientCancelled("QuickTherm transient cancelled. No PCB files were changed.")


def _number(value, label, *, minimum=None, positive=False):
    try:
        if isinstance(value, bool):
            raise ValueError()
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number.")
    if positive and result <= 0:
        raise ValueError(f"{label} must be positive.")
    if minimum is not None and result < minimum:
        raise ValueError(f"{label} must be at least {minimum:g}.")
    return result


def _finite_result(value, label):
    if not math.isfinite(value):
        raise ValueError(f"{label} overflowed; check thermal units and magnitudes.")
    return value


def _sum(values, label):
    try:
        return _finite_result(math.fsum(values), label)
    except OverflowError as exc:
        raise ValueError(f"{label} overflowed; check thermal units and magnitudes.") from exc


def _identity(value, label):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
        raise ValueError(f"{label} must be a nonempty string of at most 256 characters.")
    return value.strip()


def _times(duration, step, events, cancel):
    quotient = duration / step
    if not math.isfinite(quotient) or quotient >= MAX_SAMPLES:
        raise ValueError(f"Duration / output step must allow at most {MAX_SAMPLES} samples.")
    event_times = sorted({0., duration, *events})
    times = set(event_times)
    for i in range(1, math.floor(quotient) + 1):
        if i % 256 == 0:
            _cancelled(cancel)
        t = i * step
        if not 0 < t < duration:
            continue
        index = bisect_left(event_times, t)
        neighbors = event_times[max(0, index - 1):index + 1]
        # Keep the user's exact event, rather than e.g. both 0.3 and the
        # one-ulp-different regular-grid multiplication 3 * 0.1. Distinct
        # explicit events are retained, even if very close to one another.
        if not any(abs(t - event) <= 4 * max(math.ulp(t), math.ulp(event))
                   for event in neighbors):
            times.add(t)
    if len(times) > MAX_SAMPLES:
        raise ValueError(f"Output grid including power events exceeds {MAX_SAMPLES} samples.")
    return sorted(times)


def _fractions(elapsed, tau):
    """Return 1-exp(-u), exp(-u), and 1-(1-exp(-u))/u stably."""
    if elapsed == 0:
        return 0., 1., 0.
    u = elapsed / tau
    if u == 0:
        raise ValueError("A time interval is below floating-point thermal time resolution.")
    decay = math.exp(-u)
    change = -math.expm1(-u)
    if u < 1e-4:
        # Integral of heating above ambient, avoiding cancellation near t=0.
        lag = u * (.5 + u * (-1/6 + u * (1/24 + u * (-1/120 + u/720))))
    else:
        lag = 1 - change / u
    return change, decay, lag


def _temperature(start, target, elapsed, tau):
    change, decay, _ = _fractions(elapsed, tau)
    # Use the nearer endpoint to retain small rises and long cooling tails.
    value = start + (target - start) * change if change <= .5 else target + (start - target) * decay
    return _finite_result(value, "Transient temperature")


def _segment_energy(start, ambient, power, elapsed, tau, capacity):
    change, _, lag = _fractions(elapsed, tau)
    input_j = _finite_result(power * elapsed, "Input energy")
    initial_outward = _finite_result(((start - ambient) * change) * capacity,
                                    "Ambient heat transfer")
    # Integrate (T(t)-ambient)/R independently of rounded output endpoints.
    outward = _sum((initial_outward, input_j * lag), "Ambient heat transfer")
    return input_j, outward


def _energy(input_j, outward_j, stored_j):
    residual = _sum((input_j, -outward_j, -stored_j), "Energy residual")
    scale = max(abs(input_j), abs(outward_j), abs(stored_j), 1e-30)
    return {"input_J": input_j, "to_ambient_J": outward_j,
            "stored_change_J": stored_j, "residual_J": residual,
            "relative_residual": residual / scale}


def solve_transient(request, cancel=None):
    """Solve one explicit power step per independent component.

    Required request keys: duration_s, step_s, ambient_c, components (list).
    initial_temperature_c defaults to ambient only when absent. Each component
    needs id and/or reference, initial_power_W, step_power_W, step_time_s,
    resistance_K_W and capacitance_J_K. Optional limit_c is an upper temperature
    limit; None means unspecified. Times include zero, duration, regular output
    samples and every exact event. At an event power_W reports the new power;
    temperature is continuous. step_s controls sampling, not integration error.

    Bounds are exported as MAX_* constants. Invalid or overflowing inputs raise
    ValueError. A callable cancel is polled during bounded work; cancellation
    raises TransientCancelled without returning incomplete traces.
    """
    if cancel is not None and not callable(cancel):
        raise ValueError("cancel must be a callable or None.")
    _cancelled(cancel)
    allowed = {"duration_s", "step_s", "ambient_c", "initial_temperature_c", "components"}
    if not isinstance(request, Mapping) or set(request) - allowed:
        raise ValueError("Use the supported thermal transient request fields only.")
    duration = _number(request.get("duration_s"), "Duration (s)", positive=True)
    if duration > MAX_DURATION_S:
        raise ValueError(f"Duration must not exceed {MAX_DURATION_S} s (365 days).")
    step = _number(request.get("step_s"), "Output step (s)", positive=True)
    ambient = _number(request.get("ambient_c"), "Ambient temperature (°C)", minimum=-273.15)
    initial = _number(request.get("initial_temperature_c", ambient),
                      "Initial temperature (°C)", minimum=-273.15)
    raw = request.get("components")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_COMPONENTS:
        raise ValueError(f"Provide between 1 and {MAX_COMPONENTS} thermal components.")
    rows = []
    ids, references = set(), set()
    component_keys = {"id", "reference", "initial_power_W", "step_power_W", "step_time_s",
                      "resistance_K_W", "capacitance_J_K", "limit_c"}
    for item in raw:
        _cancelled(cancel)
        if not isinstance(item, Mapping) or set(item) - component_keys:
            raise ValueError("Use the supported thermal component fields only.")
        identifier = _identity(item.get("id", item.get("reference")), "Component id")
        reference = _identity(item.get("reference", identifier), "Component reference")
        if identifier in ids or reference in references:
            raise ValueError("Each thermal component needs a unique id and reference.")
        ids.add(identifier); references.add(reference)
        resistance = _number(item.get("resistance_K_W"), reference + " resistance (K/W)", positive=True)
        capacity = _number(item.get("capacitance_J_K"), reference + " explicit capacitance (J/K)", positive=True)
        tau = _finite_result(resistance * capacity, reference + " thermal time constant")
        if tau <= 0:
            raise ValueError(reference + " thermal time constant underflowed; check units.")
        before = _number(item.get("initial_power_W"), reference + " initial power (W)", minimum=0)
        after = _number(item.get("step_power_W"), reference + " step power (W)", minimum=0)
        event = _number(item.get("step_time_s"), reference + " step time (s)", minimum=0)
        if event > duration:
            raise ValueError(reference + " step time must be within the study duration.")
        limit = None if item.get("limit_c") is None else _number(item["limit_c"], reference + " limit (°C)", minimum=-273.15)
        before_target = _finite_result(ambient + before * resistance, reference + " initial equilibrium")
        after_target = _finite_result(ambient + after * resistance, reference + " step equilibrium")
        rows.append({"id": identifier, "reference": reference, "resistance_K_W": resistance,
                     "capacitance_J_K": capacity, "time_constant_s": tau,
                     "initial_power_W": before, "step_power_W": after, "step_time_s": event,
                     "limit_c": limit, "_before_target": before_target, "_after_target": after_target})
    times = _times(duration, step, [row["step_time_s"] for row in rows], cancel)
    if len(times) * len(rows) > MAX_COMPONENT_SAMPLES:
        raise ValueError(f"Output exceeds {MAX_COMPONENT_SAMPLES} component/time pairs; use a larger output step or fewer components.")
    components = []
    for row in rows:
        _cancelled(cancel)
        event, tau = row["step_time_s"], row["time_constant_s"]
        event_temperature = _temperature(initial, row["_before_target"], event, tau)
        temperatures, powers = [], []
        for index, t in enumerate(times):
            if index % 256 == 0:
                _cancelled(cancel)
            if t <= event:
                temperature = _temperature(initial, row["_before_target"], t, tau)
            else:
                temperature = _temperature(event_temperature, row["_after_target"], t - event, tau)
            temperatures.append(temperature)
            powers.append(row["initial_power_W"] if t < event else row["step_power_W"])
        before_energy = _segment_energy(initial, ambient, row["initial_power_W"], event, tau, row["capacitance_J_K"])
        after_energy = _segment_energy(event_temperature, ambient, row["step_power_W"], duration - event, tau, row["capacitance_J_K"])
        energy = _energy(_sum((before_energy[0], after_energy[0]), "Input energy"),
                         _sum((before_energy[1], after_energy[1]), "Ambient heat transfer"),
                         _finite_result((temperatures[-1] - initial) * row["capacitance_J_K"], "Stored energy"))
        peak = max(temperatures)
        components.append({key: value for key, value in row.items() if not key.startswith("_")} | {
            "temperature_c": temperatures, "power_W": powers,
            "peak_temperature_c": peak, "peak_time_s": times[temperatures.index(peak)],
            "final_temperature_c": temperatures[-1],
            "limit_exceeded": row["limit_c"] is not None and peak > row["limit_c"],
            "energy_balance": energy})
    totals = [_sum((row["energy_balance"][key] for row in components), key)
              for key in ("input_J", "to_ambient_J", "stored_change_J")]
    energy = _energy(*totals)
    energy["notice"] = "Signed ambient heat is positive outward. Residual is numerical conservation, not physical validation."
    evaluated = sum(row["limit_c"] is not None for row in components)
    exceeded = [row["reference"] for row in components if row["limit_exceeded"]]
    _cancelled(cancel)
    return {"model": "independent lumped thermal RC transient screen",
            "notice": "Explicit independent thermal R/C paths to a prescribed constant ambient; no whole-board temperature field or coupled electrothermal simulation.",
            "assumptions": ["Resistance and thermal capacitance are supplied explicitly and constant; no capacity is inferred from a package or PCB.",
                            "Each component has one independent heat path to the prescribed ambient; shared board/sink nodes and radiation nonlinearities are not modeled.",
                            "One instantaneous power step per component; temperature remains continuous at the event.",
                            "Output sampling uses the exact constant-power RC response; smoother traces add no physical or spatial resolution."],
            "ambient_c": ambient, "initial_temperature_c": initial,
            "duration_s": duration, "step_s": step, "times_s": times, "components": components,
            "limits": {"evaluated_components": evaluated, "exceeded_components": exceeded,
                       "within_all_specified_limits": not exceeded if evaluated else None},
            "energy_balance": energy,
            "numerics": {"method": "analytical_piecewise_constant_RC", "step_is_output_sampling": True,
                         "event_times_included": True, "sample_count": len(times),
                         "max_output_gap_s": max(b - a for a, b in zip(times, times[1:]))}}
