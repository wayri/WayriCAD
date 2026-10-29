"""Board-section RLC channel and bounded periodic PRBS7 receiver response.

Each extracted uniform section is an exact distributed RLC two-port. Cascading
preserves section order and impedance steps; no aggregate-Z0 substitution is
made. R is the extractor's DC copper resistance, not a frequency-independent
reuse of its single-frequency AC resistance. Skin/dielectric loss remain absent.
"""
from __future__ import annotations

import math

from .eye_model import _number, _prbs7

MODEL = 'board-section-rlc-prbs7'
MAX_WORK = 16_000_000


def channel_sections(path, topology, via_l_nh=None, via_c_pf=None):
    """Validate ordered extractor sections; never fill missing field geometry."""
    if not topology or topology.get('complete') is not True:
        raise ValueError('Whole-net topology is unverified or contains branches/stubs; select a complete two-terminal channel.')
    if path.status not in ('ok', 'partial') or not path.segments:
        raise ValueError('No complete ordered RLC sections are available from the board.')
    if path.zone_count or path.layer_changes > path.via_count:
        raise ValueError('Zones and pad-only layer transitions need a reviewed channel model.')
    allowed = {'NONUNIFORM_IMPEDANCE', 'VIA_DISCONTINUITY_UNMODELED'}
    if any(row.get('code') not in allowed for row in path.blockers):
        raise ValueError('Resolve the RLC extractor blockers before simulating the board eye: ' +
                         ', '.join(sorted({str(row.get('code')) for row in path.blockers if row.get('code') not in allowed})))
    if len(path.segments) > 512:
        raise ValueError('The channel exceeds the 512-section eye budget; review a smaller complete channel.')
    result = []
    for section in path.segments:
        kind = section.get('kind')
        resistance = _number('section resistance_ohm', section.get('resistance_ohm'), positive=False)
        common = dict(kind=kind, item_uuid=section.get('item_uuid'), layer=section.get('layer'),
                      resistance_ohm=resistance)
        if kind == 'via':
            if via_l_nh is None or via_c_pf is None:
                raise ValueError('Via return-loop L and shunt C are not extracted. Enter reviewed per-via loop inductance and capacitance in Eye setup; isolated barrel L is not a loop model.')
            common.update(inductance_h=_number('per-via loop L', via_l_nh)*1e-9,
                          capacitance_f=_number('per-via C', via_c_pf, positive=False)*1e-12,
                          basis='User-assumed symmetric pi via; extracted barrel R; identical L/C per traversed via')
        elif kind == 'track':
            if section.get('status') != 'ok' or not section.get('reference_layer'):
                raise ValueError('A track lacks a supported, covered reference-plane RLC extraction.')
            common.update(inductance_h=_number('section inductance_nh', section.get('inductance_nh'))*1e-9,
                          capacitance_f=_number('section capacitance_pf', section.get('capacitance_pf'))*1e-12,
                          basis=section.get('model', 'Extracted uniform RLC section'))
        else:
            raise ValueError('Unsupported channel section: ' + str(kind))
        result.append(common)
    if sum(s['kind'] == 'via' for s in result) != path.via_count:
        raise ValueError('Via section inventory differs from the extracted path.')
    return result


def transfer(sections, frequencies_hz, source_ohm, load_ohm=None, load_pf=0.):
    """Return receiver/source voltage transfer from cascaded ABCD matrices.

    For section-total Z=R+sL, Y=sC, p=sqrt(ZY): A=D=cosh(p),
    B=Z*sinh(p)/p, C=Y*sinh(p)/p. The analytic p=0 limit handles DC.
    H=1/[A+B*YL+Rs*(C+D*YL)] includes receiver capacitance in YL.
    Via sections use shunt C/2, series R+sL, shunt C/2 instead of a line.
    """
    import numpy as np
    frequency = np.asarray(frequencies_hz, dtype=float)
    if frequency.ndim != 1 or not np.all(np.isfinite(frequency)) or np.any(frequency < 0):
        raise ValueError('Channel frequencies must be a finite nonnegative vector.')
    if len(frequency)*max(1, len(sections)) > MAX_WORK:
        raise ValueError('Channel frequency/section workload exceeds the bounded eye budget.')
    if load_ohm == 0:
        return np.zeros(len(frequency), dtype=complex)
    s = 2j*np.pi*frequency
    a = np.ones(len(s), dtype=complex); b = np.zeros(len(s), dtype=complex)
    c = b.copy(); d = a.copy()
    for row in sections:
        z = row['resistance_ohm'] + s*row['inductance_h']
        y = s*row['capacitance_f']
        if row['kind'] == 'via':
            aa = dd = 1 + z*y/2
            bb = z
            cc = y + z*y*y/4
        else:
            p = np.sqrt(z*y)
            if np.max(p.real, initial=0) > 40:
                raise ValueError('Section attenuation exceeds the supported matrix range.')
            small = np.abs(p) < 1e-5
            factor = np.empty_like(p)
            factor[small] = 1 + p[small]**2/6 + p[small]**4/120
            factor[~small] = np.sinh(p[~small])/p[~small]
            aa = dd = np.cosh(p); bb = z*factor; cc = y*factor
        a, b, c, d = a*aa+b*cc, a*bb+b*dd, c*aa+d*cc, c*bb+d*dd
    yl = s*load_pf*1e-12 + (0 if load_ohm is None else 1/load_ohm)
    denominator = a+b*yl + source_ohm*(c+d*yl)
    if not np.all(np.isfinite(denominator)) or np.any(np.abs(denominator) < 1e-14):
        raise ValueError('Undamped resonance or numerical range failure; review source/load damping.')
    return 1/denominator


def _periodic_source(count, dt_ns, ui_ns, ramp_ns, bits):
    """Sample the analytic moving-average ramp of a cyclic bit pattern."""
    import numpy as np
    prefix = np.r_[0., np.cumsum(bits)]
    def integral(time):
        cycles, phase = np.divmod(time/ui_ns, len(bits))
        cells = np.minimum(phase.astype(int), len(bits)-1)
        return ui_ns*(cycles*prefix[-1]+prefix[cells]+np.asarray(bits)[cells]*(phase-cells))
    time = np.arange(count)*dt_ns
    return (integral(time)-integral(time-ramp_ns))/ramp_ns


def simulate_board_eye(path, *, topology, source_ohm, load_ohm=None, load_pf=0.,
                       rise_ns, bitrate_mbps, swing_v=1., via_l_nh=None, via_c_pf=None):
    """Return a converged sampled linear channel eye, or an actionable error.

    PRBS7 is solved in periodic steady state. Sampling is doubled from 64 to
    128 (then 256/512 if needed); aligned waveform error must be <=0.5% of
    source swing. A separate ramped-step FFT window grows until its pre-edge
    history and final DC level agree within 0.1%; unresolved wraparound fails.
    """
    try:
        import numpy as np
    except ImportError as error:
        raise ValueError('Board RLC eyes need NumPy; run the managed runtime dependency setup.') from error
    sections = channel_sections(path, topology, via_l_nh, via_c_pf)
    source = _number('source_ohm', source_ohm, positive=False)
    load = None if load_ohm is None else _number('load_ohm', load_ohm, positive=False)
    capacitance = _number('receiver C', load_pf, positive=False)
    rise = _number('rise_ns', rise_ns); rate = _number('bitrate_mbps', bitrate_mbps)
    swing = _number('swing_v', swing_v)
    ui = 1000/rate; ramp = rise/.8
    delay = sum(math.sqrt(row['inductance_h']*row['capacitance_f'])*1e9
                for row in sections if row['kind'] == 'track')
    if not .001 <= ramp/ui <= 10 or not 0 < delay/ui <= 100:
        raise ValueError('Board eye supports ramp durations 0.001–10 UI and route delay up to 100 UI.')
    bits = _prbs7(); previous = None; error = None
    for samples in (64, 128, 256, 512):
        dt = ui/samples; count = len(bits)*samples
        frequency = np.fft.rfftfreq(count, dt*1e-9)
        response = transfer(sections, frequency, source, load, capacitance)
        waveform = np.fft.irfft(np.fft.rfft(_periodic_source(count, dt, ui, ramp, bits))*response, n=count)*swing
        indices = (np.arange(len(bits))[:, None]*samples + np.arange(129)[None, :]*samples/64 + delay/dt) % count
        traces = np.interp(indices.ravel(), np.arange(count+1), np.r_[waveform, waveform[0]]).reshape(127, 129)
        if previous is not None:
            error = float(np.max(np.abs(traces-previous)))
            if error <= .005*swing and ramp/dt >= 8:
                break
        previous = traces
    else:
        raise ValueError('Eye waveform did not converge within 512 samples/UI; reduce bandwidth or review channel damping.')
    # A periodic half-window pulse approximates an isolated step only after
    # both its preceding fall and its present rise have settled. Check both.
    dc = float(transfer(sections, [0.], source, load, capacitance)[0].real)*swing
    count = 32768
    while count <= 262144:
        time = np.arange(count)*dt
        start = count//4
        pulse = np.clip((time-time[start])/ramp, 0, 1)-np.clip((time-time[3*start])/ramp, 0, 1)
        volts = np.fft.irfft(np.fft.rfft(pulse)*transfer(sections, np.fft.rfftfreq(count, dt*1e-9), source, load, capacitance), n=count)*swing
        before = float(np.max(np.abs(volts[start//2:start-8])))
        settled = float(np.max(np.abs(volts[2*start:3*start-8]-dc)))
        if max(before, settled) <= .001*swing:
            break
        count *= 2
    else:
        raise ValueError('Step history did not settle within the bounded FFT window; increase physical damping.')
    stop = max(delay+4*ramp, delay+4*ui)
    # Include all significant ringing, not merely a few UIs after arrival.
    # Avoid the later falling edge of the periodic step-test pulse.
    rising = volts[start:3*start-8]
    unsettled = np.flatnonzero(np.abs(rising-dc) > .001*swing)
    last = int(unsettled[-1]) if len(unsettled) else 0
    end = min(len(rising)-1, max(int(stop/dt), last+samples, 512))
    chosen = np.unique(np.linspace(0, end, min(end+1, 2049)).astype(int))
    step_time = chosen*dt
    step_voltage = volts[start+chosen]
    highs = traces[np.asarray(bits, dtype=bool), 32]
    lows = traces[~np.asarray(bits, dtype=bool), 32]
    return dict(schema='wayricad.board-rlc-eye/v1', status='SIMULATED', model=MODEL,
        inputs=dict(source_ohm=source, load_ohm=load, load_pf=capacitance, rise_ns=rise,
                    bitrate_mbps=rate, swing_v=swing, via_l_nh=via_l_nh, via_c_pf=via_c_pf),
        ui_ns=ui, ramp_duration_ns=ramp, alignment_delay_ns=delay,
        channel_sections=sections, time_ui=[i/64 for i in range(129)], traces_v=traces.tolist(), bits=bits,
        center_ui=.5, center_opening_v=float(min(highs)-max(lows)),
        center_high_min_v=float(min(highs)), center_low_max_v=float(max(lows)),
        min_v=float(traces.min()), max_v=float(traces.max()),
        step_response=dict(time_ns=step_time.tolist(), voltage_v=step_voltage.tolist()),
        numerics=dict(samples_per_ui=samples, waveform_refinement_error_v=error,
                      waveform_tolerance_v=.005*swing, step_window_samples=count,
                      step_history_error_v=before, step_settling_error_v=settled,
                      step_tolerance_v=.001*swing, dc_receiver_v=dc),
        assumptions=[
            'Ordered RLC extractor sections cascaded as distributed lossy transmission lines; width changes retain their reflections.',
            'Frequency-independent extracted DC copper R and quasi-static section L/C; ideal reference conductor.',
            'Linear Thevenin source, explicit resistive receiver (blank means open) and user-entered receiver capacitance.',
            'Periodic PRBS7 with equal causal linear ramps, ideal clock and no jitter; alignment uses summed geometric line delay.',
            'Opening is sampled at 0.5 UI, not an optimized receiver sampling phase.',
        ] + (['Every traversed via uses the same explicitly assumed loop L/C pi equivalent; isolated extracted via L is not used.'] if path.via_count else []),
        limitations=[
            'Not IBIS, LPDDR4 timing/ODT/training simulation, protocol compliance or a measured eye.',
            'Skin/proximity effect, return-conductor resistance, dielectric loss/dispersion, roughness and coupled aggressors are not included.',
            'Pads, packages, connectors and nonlinear clamps are not extracted; receiver C is an explicit assumption, not an IBIS value.',
            'Finite PRBS7 and bounded sampled FFT can miss narrow peaks or worst-case longer patterns.',
            'No eye mask, clock recovery, BER prediction or multi-conductor differential channel solve.',
        ])
