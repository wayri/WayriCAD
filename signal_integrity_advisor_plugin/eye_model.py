"""Illustrative, uniform lossless-line receiver eye. No external dependencies."""
import math


def _number(name, value, *, positive=True):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return number


def _prbs7():
    state = 127
    bits = []
    for _ in range(127):
        bits.append(state & 1)
        state = (state >> 1) | (((state ^ (state >> 1)) & 1) << 6)
    return bits


def simulate_eye(*, z0_ohm, delay_ns, source_ohm, rise_ns, bitrate_mbps,
                 load_ohm=None, swing_v=1.0):
    """Return JSON-safe sampled eye and step data with explicit model limits.

    Source swing is the Thevenin open-circuit 0-to-swing voltage. Source edges
    use a causal linear ramp whose 10-to-90% duration equals ``rise_ns``.
    The receiver response is the exact lossless bounce-series model truncated
    at a bounded absolute voltage error. A periodic PRBS7 source incorporates
    all prior history; there is no artificial all-zero startup in the eye.
    """
    z0 = _number('z0_ohm', z0_ohm)
    delay = _number('delay_ns', delay_ns)
    source = _number('source_ohm', source_ohm, positive=False)
    rise = _number('rise_ns', rise_ns)
    bitrate = _number('bitrate_mbps', bitrate_mbps)
    swing = _number('swing_v', swing_v)
    load = None if load_ohm is None else _number('load_ohm', load_ohm, positive=False)
    if not (1e-9 <= delay <= 1e9 and 1e-9 <= rise <= 1e9):
        raise ValueError('Delay and rise time must be between 1e-9 and 1e9 ns')
    if not 1e-6 <= bitrate <= 1e9:
        raise ValueError('Bit rate must be between 1e-6 and 1e9 Mbps')
    if not 1e-9 <= swing <= 1e6:
        raise ValueError('Source swing must be between 1e-9 and 1e6 V')
    if not 1e-9 <= z0 <= 1e12 or source > 1e12 or (load is not None and load > 1e12):
        raise ValueError('Z0 must be between 1e-9 and 1e12 ohm; source/load must not exceed 1e12 ohm')
    if not math.isfinite(source + z0) or (load is not None and not math.isfinite(load + z0)):
        raise ValueError('Resistance range exceeds numerical limits')
    ui = 1000.0 / bitrate
    ramp = rise / .8
    if not math.isfinite(ui) or not math.isfinite(ramp) or not .0001 <= delay / ui <= 100:
        raise ValueError('delay must be between 0.0001 and 100 UI')
    if not .0001 <= ramp / ui <= 10:
        raise ValueError('linear ramp duration must be between 0.0001 and 10 UI')
    gs = (source - z0) / (source + z0)
    gl = 1.0 if load is None else (load - z0) / (load + z0)
    q = gs * gl
    if not math.isfinite(q) or abs(q) >= 1:
        raise ValueError('Non-decaying lossless reflections: add finite source/load damping')
    first = z0 / (source + z0) * (1 + gl)
    terms = []
    coefficient = first
    for index in range(512):
        arrival = delay * (2 * index + 1)
        if not math.isfinite(arrival + ramp):
            raise ValueError('Time range exceeds numerical limits')
        terms.append((arrival, coefficient))
        coefficient *= q
        tail = abs(coefficient) / (1 - abs(q))
        if tail <= 1e-7:
            break
    else:
        raise ValueError('Reflection settling exceeds the 512-echo budget; increase damping')
    if not math.isfinite(swing * max(1, abs(first) / (1 - abs(q)))):
        raise ValueError('Voltage range exceeds numerical limits')
    stop = max(delay + 4 * ramp, terms[-1][0] + ramp, delay + 2 * ui)
    if not math.isfinite(stop):
        raise ValueError('Time range exceeds numerical limits')

    bits = _prbs7()
    prefix = [0]
    for bit in bits:
        prefix.append(prefix[-1] + bit)

    def integral(t):
        cycles, phase = divmod(t / ui, len(bits))
        cell = min(int(phase), len(bits) - 1)
        return ui * (cycles * prefix[-1] + prefix[cell] + bits[cell] * (phase - cell))

    def digital_ramp(t):
        return (integral(t) - integral(t - ramp)) / ramp

    def receiver(t):
        return swing * sum(weight * digital_ramp(t - arrival) for arrival, weight in terms)

    # 64 samples/UI; all 127 cyclic PRBS contexts. Budget is independent of inputs.
    time_ui = [i / 64 for i in range(129)]
    if len(terms) * (len(bits) * len(time_ui) + 513) > 3_000_000:
        raise ValueError('Eye workload exceeds budget; increase source/load damping')
    # Align the ideal bit boundaries at the first-arrival receiver time.
    traces = [[receiver(delay + (bit_index + t) * ui) for t in time_ui]
              for bit_index in range(len(bits))]
    high = [trace[32] for trace, bit in zip(traces, bits) if bit]
    low = [trace[32] for trace, bit in zip(traces, bits) if not bit]
    high_min, low_max = min(high), max(low)
    step_time = [stop * i / 512 for i in range(513)]
    # Include every echo corner so a short rise or long delay cannot disappear.
    step_time = sorted(set(step_time + [p for arrival, _ in terms for p in (arrival, arrival + ramp)]))
    step_voltage = [swing * sum(weight * min(1., max(0., (t - arrival) / ramp))
                               for arrival, weight in terms) for t in step_time]
    return {
        'schema': 'wayricad.illustrative-eye/v1',
        'status': 'ILLUSTRATIVE', 'model': 'uniform-lossless-line-prbs7',
        'inputs': dict(z0_ohm=z0, delay_ns=delay, source_ohm=source, load_ohm=load,
                       rise_ns=rise, bitrate_mbps=bitrate, swing_v=swing),
        'ui_ns': ui, 'ramp_duration_ns': ramp,
        'source_reflection': gs, 'load_reflection': gl, 'echo_count': len(terms),
        'truncation_bound_v': swing * tail,
        'time_ui': time_ui, 'traces_v': traces, 'bits': bits,
        'center_ui': .5, 'center_opening_v': high_min - low_max,
        'center_high_min_v': high_min, 'center_low_max_v': low_max,
        'min_v': min(map(min, traces)), 'max_v': max(map(max, traces)),
        'step_response': {'time_ns': step_time, 'voltage_v': step_voltage},
        'assumptions': [
            'Uniform lossless transmission line with constant real Z0 and one-way delay.',
            'Linear Thevenin driver and purely resistive load; None means open circuit.',
            '0-to-swing open-circuit source with equal causal linear rising/falling ramps.',
            'Periodic PRBS7 steady-state history; time zero aligned to first receiver arrival.',
            'Opening is minimum high minus maximum low at 0.5 UI, not an optimized sampling phase.',
        ],
        'limitations': [
            'Illustrative screening, not IBIS, protocol compliance or a measured eye.',
            'No conductor/dielectric loss, dispersion, coupling, vias, stubs, nonlinear clamps or jitter.',
            '64 samples/UI and finite PRBS7 pattern can miss narrow peaks or worst-case long patterns.',
            'No clock recovery, eye-width measurement, mask test or bit-error-rate prediction.',
        ],
    }
