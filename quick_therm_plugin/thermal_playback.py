"""Display helpers for stored, computed spatial transient frames."""
import bisect
import math


def frame_at_time(frames, time_s):
    """Hold the latest computed frame; never interpolate a synthetic solution."""
    return max(0, min(len(frames)-1, bisect.bisect_right(
        [frame['time_s'] for frame in frames], time_s)-1)) if frames else None


def transient_temperature_limits(transient):
    """One board/component scale over all frames, independent of camera."""
    low, high = math.inf, -math.inf
    spatial = transient.get('spatial_index', {})
    count = spatial.get('active_cells_per_layer', 0)*len(spatial.get('layers', []))
    # Without a spatial layer index, retain all declared solved nodes in the
    # scale rather than treating missing metadata as a zero temperature.
    for frame in transient.get('frames', []):
        temperatures = frame.get('temperatures_c', [])
        values=temperatures[:count or len(temperatures)]
        values=values+[temperatures[row['storage_node']] for row in transient.get('components',[])
                       if row.get('storage_node') is not None]
        for value in values:
            if value is not None and math.isfinite(value):
                low, high = min(low, value), max(high, value)
    if not math.isfinite(low):
        return None
    return (low-.5, high+.5) if low == high else (low, high)


def step_schedules(rows, duration_s):
    """Build explicit multipliers from the native one-step-per-source editor."""
    result = {}
    for reference, initial, switch, final in rows:
        initial = float(initial)
        if not math.isfinite(initial) or initial < 0:
            raise ValueError(reference+': initial multiplier must be finite and nonnegative.')
        points = [[0., initial]]
        if str(switch).strip():
            switch, final = float(switch), float(final)
            if not math.isfinite(switch) or not 0 < switch <= duration_s:
                raise ValueError(reference+': switch time must be greater than zero and within the duration.')
            if not math.isfinite(final) or final < 0:
                raise ValueError(reference+': final multiplier must be finite and nonnegative.')
            points.append([switch, final])
        elif str(final).strip():
            raise ValueError(reference+': enter a switch time for the final multiplier.')
        result[reference] = points
    return result
