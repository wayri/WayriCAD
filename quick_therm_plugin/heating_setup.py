"""Reviewed spatial-heating setup and source-power schedule helpers.

These functions normalize user inputs only. They do not infer thermal material
properties, choose a converged time step, or change the thermal equations.
"""
import math
import re


def time_seconds(raw, label="Time"):
    """Parse a positive duration in seconds, milliseconds, minutes or hours."""
    if isinstance(raw, bool):
        raise ValueError(label + " must be a time, not a boolean.")
    match = re.fullmatch(r"\s*([+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+\-]?\d+)?)\s*(ms|s|sec|min|h)?\s*", str(raw), re.I)
    if not match:
        raise ValueError(label + ": enter a number with optional ms, s, min or h.")
    value = float(match[1]) * {None: 1, "ms": .001, "s": 1, "sec": 1, "min": 60, "h": 3600}[match[2].lower() if match[2] else None]
    if not math.isfinite(value) or value <= 0:
        raise ValueError(label + " must be finite and positive.")
    return value


def heating_settings(values):
    """Return the established spatial transient keys from reviewed form values."""
    result = {key: time_seconds(values[key], label) for key, label in (
        ("duration_s", "Duration"), ("timestep_s", "Maximum solver step"),
        ("frame_interval_s", "Stored frame interval"))}
    for key, label in (("initial_c", "Initial temperature"),
                       ("copper_volumetric_capacity_j_m3k", "Copper heat capacity"),
                       ("dielectric_volumetric_capacity_j_m3k", "Dielectric heat capacity")):
        raw = values[key]
        try:
            if isinstance(raw, bool):
                raise ValueError()
            number = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(label + " must be a finite number.") from exc
        if not math.isfinite(number) or (not -273.15 < number <= 10000 if key == "initial_c" else number <= 0):
            raise ValueError(label + (" must exceed absolute zero and not exceed 10000 °C." if key == "initial_c" else " must be positive."))
        result[key] = number
    duration = result["duration_s"]
    if duration/result["timestep_s"] > 10000:
        raise ValueError("More than 10000 regular solver steps. Increase the maximum step or shorten the study.")
    if duration/result["frame_interval_s"] > 999:
        raise ValueError(f"More than 1000 stored frames. Use an interval of at least {duration/999:.6g} s, or shorten the study.")
    return result


def heating_advice(settings, schedules=None):
    """Bound setup work without claiming exact node count or time convergence."""
    duration = settings["duration_s"]
    frames = math.ceil(duration/settings["frame_interval_s"]) + 1
    events = {float(point[0]) for points in (schedules or {}).values() for point in points
              if isinstance(point, (list, tuple)) and len(point) == 2 and 0 < float(point[0]) < duration}
    # Schedule events are retained as computed frames. This bound can count an
    # event twice when it coincides with a regular frame, so it is advice only.
    frame_bound = frames + len(events)
    step_bound = math.ceil(duration/settings["timestep_s"]) + frames - 2 + len(events)
    return {"regular_frames": frames, "frame_upper_bound": frame_bound,
            "step_upper_bound": step_bound, "nodes_per_frame_budget": 5000000//frame_bound,
            "schedule_events": len(events),
            "note": "Storage depends on the solved mesh; events can add frames. Smaller time steps still require refinement checks."}


def watt_step_schedules(rows, powers, duration_s):
    """Convert explicit watts to existing multipliers; never invent base power.

    A zero-power source can remain zero. To schedule nonzero heat, the user must
    first enter a positive base power in Component inputs. The returned mapping
    is detached; validation failure never partially changes the caller's data.
    """
    from .thermal_playback import step_schedules
    duration_s = time_seconds(duration_s, "Duration")
    converted = []
    for reference, initial, switch, final in rows:
        base = powers.get(reference)
        if isinstance(base, bool) or not isinstance(base, (int, float)) or not math.isfinite(base) or base < 0:
            raise ValueError(reference + ": enter a known nonnegative base power in Component inputs first.")
        def multiplier(raw):
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(reference + ": enter finite nonnegative watts.") from exc
            if not math.isfinite(value) or value < 0:
                raise ValueError(reference + ": enter finite nonnegative watts.")
            if base == 0:
                if value != 0:
                    raise ValueError(reference + ": base power is zero; enter a positive base power in Component inputs before scheduling heat.")
                return 0.
            return value/base
        converted.append((reference, multiplier(initial), switch,
                          multiplier(final) if str(final).strip() else ""))
    return step_schedules(converted, duration_s)


def watt_step_rows(references, powers, schedules):
    """Read an existing one-step profile without dropping complex/invalid data."""
    if not isinstance(schedules, dict):
        raise ValueError("Power schedules must be a reference mapping.")
    for reference, points in schedules.items():
        if not isinstance(points, list) or not 1 <= len(points) <= 2:
            raise ValueError("Existing multi-step profiles: use Advanced schedules + sinks to retain every event.")
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or value < 0 for value in point):
                raise ValueError(str(reference) + ": invalid power schedule; review Advanced schedules + sinks.")
        if points[0][0] != 0 or (len(points) == 2 and points[1][0] <= 0):
            raise ValueError(str(reference) + ": retain nonzero-start or repeated-time profiles in Advanced schedules + sinks.")
    rows=[]
    for reference in references:
        base=powers.get(reference)
        points=schedules.get(reference, [[0,1]])
        rows.append([reference, str(base) if base is not None else "Unknown",
                     str(base*points[0][1]) if base is not None else "",
                     str(points[1][0]) if len(points) == 2 else "",
                     str(base*points[1][1]) if base is not None and len(points) == 2 else ""])
    return rows
