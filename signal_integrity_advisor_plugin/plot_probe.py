"""Pick existing waveform samples without interpolating an uncomputed result."""
from bisect import bisect_left


def sample_at(xs, traces, x, y):
    """Return nearest sampled x and nearest trace voltage, or None for no data."""
    if not xs or not traces:
        return None
    right = min(bisect_left(xs, x), len(xs)-1)
    index = min({right, max(0, right-1)}, key=lambda i: (abs(xs[i]-x), i))
    candidates = [(n, trace[index]) for n, trace in enumerate(traces)
                  if len(trace) > index and trace[index] is not None]
    if not candidates:
        return None
    trace, voltage = min(candidates, key=lambda row: abs(row[1]-y))
    return {'sample': index, 'trace': trace, 'x': xs[index], 'voltage_v': voltage}
