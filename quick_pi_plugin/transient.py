"""Bounded lumped rail transients with explicit, passive R/L/C parameters.

An ideal voltage source feeds a common bus through source R/L. Each branch
feeds a constant-current load through path R/L, with a capacitor and series
ESR from that load node to return. Currents are positive towards the load;
capacitor current is positive while charging. No parameters or spatial fields
are inferred from the DC copper mesh.

For path currents i, capacitor voltages v and requested load currents d:
    L di/dt + R i + v = Vs * 1 + ESR * d
    C dv/dt = i - d
where L = diag(path L) + source L * 11', and
R = diag(path R + ESR) + source R * 11'. Backward Euler solves these
equations, including their zero-inductance algebraic limits. Exact event
samples preserve stored energy and resolve algebraic/ESR jumps.
"""
from __future__ import annotations

import hashlib
import json
import math

from .solver import SolverError


class TransientError(SolverError):
    """An explicit transient request is invalid or cannot be resolved reliably."""


MAX_LOADS = 64
MAX_COARSE_INTERVALS = 10000
MAX_TRACE_VALUES = 750000
SCHEMA = 'wayricad.pi-transient/v1'


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool):
        raise TransientError(name + ' must be a finite number.')
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise TransientError(name + ' must be a finite number.') from exc
    if not math.isfinite(result) or (positive and result <= 0) or (nonnegative and result < 0):
        raise TransientError(name + ' is outside its valid range.')
    return result


def _request(request):
    if not isinstance(request, dict):
        raise TransientError('Transient request must be an object.')
    allowed = {'action', 'duration_s', 'step_s', 'source_voltage_V',
               'source_resistance_ohm', 'source_inductance_H',
               'source_current_limit_A', 'loads'}
    unknown = set(request) - allowed
    if unknown:
        raise TransientError('Unknown transient option: ' + ', '.join(sorted(unknown)))
    normalized = {}
    for key in ('duration_s', 'step_s', 'source_voltage_V', 'source_resistance_ohm'):
        normalized[key] = _number(request.get(key), key, positive=True)
    normalized['source_inductance_H'] = _number(request.get('source_inductance_H', 0),
                                                'source_inductance_H', nonnegative=True)
    limit = request.get('source_current_limit_A')
    normalized['source_current_limit_A'] = None if limit is None else _number(
        limit, 'source_current_limit_A', nonnegative=True)
    rows = request.get('loads')
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_LOADS:
        raise TransientError(f'Define 1 to {MAX_LOADS} explicit transient loads.')
    loads = []
    identifiers = set()
    load_keys = {'id', 'label', 'terminal', 'initial_current_A', 'step_current_A',
                 'step_time_s', 'path_resistance_ohm', 'path_inductance_H',
                 'capacitance_F', 'esr_ohm', 'min_voltage_V', 'max_voltage_V'}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) - load_keys:
            raise TransientError('Each load needs only the documented explicit R/L/C and step fields.')
        identifier = row.get('id', str(index + 1))
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 128:
            raise TransientError('Load id must be a nonempty string of at most 128 characters.')
        if identifier in identifiers:
            raise TransientError('Repeated load identity: ' + identifier)
        identifiers.add(identifier)
        label = row.get('label', row.get('terminal', identifier))
        if not isinstance(label, str) or len(label) > 256:
            raise TransientError('Load label must be a string of at most 256 characters.')
        load = {'id': identifier, 'label': label}
        if 'terminal' in row:
            if not isinstance(row['terminal'], str) or len(row['terminal']) > 256:
                raise TransientError('Load terminal must be a string of at most 256 characters.')
            load['terminal'] = row['terminal']
        for key in ('initial_current_A', 'step_current_A', 'step_time_s',
                    'path_resistance_ohm', 'path_inductance_H', 'esr_ohm'):
            # R/L/ESR are explicit inputs, including explicit zero values.
            load[key] = _number(row.get(key), identifier + ': ' + key, nonnegative=True)
        load['capacitance_F'] = _number(row.get('capacitance_F'),
                                        identifier + ': capacitance_F', positive=True)
        if load['step_time_s'] > normalized['duration_s']:
            raise TransientError(identifier + ': step_time_s must lie inside the simulation duration.')
        for key in ('min_voltage_V', 'max_voltage_V'):
            load[key] = None if row.get(key) is None else _number(row[key], identifier + ': ' + key)
        if load['min_voltage_V'] is not None and load['max_voltage_V'] is not None:
            if load['max_voltage_V'] < load['min_voltage_V']:
                raise TransientError(identifier + ': maximum voltage must be at least its minimum.')
        loads.append(load)
    normalized['loads'] = loads
    ratio = normalized['duration_s'] / normalized['step_s']
    if normalized['step_s'] / 2 == 0:
        raise TransientError('step_s is too small for the required half-step comparison.')
    if not math.isfinite(ratio) or ratio > MAX_COARSE_INTERVALS:
        raise TransientError(f'Transient duration/step exceeds {MAX_COARSE_INTERVALS:,} intervals.')
    return normalized


def _timeline(duration, step, events):
    # Replace only rounding-equivalent regular grid points with the exact event
    # value. Distinct user event times are never silently merged.
    count = math.ceil(duration / step)
    grid = {0., duration}
    grid.update(index * step for index in range(1, count) if index * step < duration)
    for event in events:
        nearest = round(event / step) * step
        if nearest in grid and nearest not in events:
            if abs(nearest - event) <= 8 * max(math.ulp(nearest), math.ulp(event)):
                grid.remove(nearest)
        grid.add(event)
    # A tiny remainder caused solely by multiplying the regular grid is not a
    # distinct physical interval. Preserve duration and all actual event times.
    for value in tuple(grid):
        if value not in events and value not in (0., duration):
            if abs(duration - value) <= 8 * max(math.ulp(duration), math.ulp(value)):
                grid.remove(value)
    return sorted(grid)


def _contrasts(np, indices, count):
    """Orthonormal zero-sum vectors supported on exactly zero-valued branches."""
    result = np.zeros((count, max(0, len(indices) - 1)))
    for column in range(len(indices) - 1):
        size = column + 1
        scale = math.sqrt(size * (size + 1))
        result[indices[:size], column] = 1 / scale
        result[indices[size], column] = -size / scale
    return result


def _factor(np, cho_factor, matrix):
    diagonal = np.diag(matrix)
    if not np.isfinite(matrix).all() or np.any(diagonal <= 0):
        raise TransientError('R/L/C values and step are outside a finite numerical range.')
    scale = 1 / np.sqrt(diagonal)
    scaled = matrix * scale[:, None] * scale[None, :]
    try:
        factor = cho_factor(scaled, lower=True, check_finite=False)
    except (ValueError, ArithmeticError, np.linalg.LinAlgError) as exc:
        raise TransientError('The explicit R/L/C and time scales cannot be resolved numerically; rescale or revise the step.') from exc
    return factor, scale


def _solve(np, cho_solve, factor, right):
    decomposition, scale = factor
    value = scale * cho_solve(decomposition, scale * right, check_finite=False)
    if not np.isfinite(value).all():
        raise TransientError('Transient state exceeded a finite numerical range.')
    return value


def _model(parameters, np, cho_factor, cho_solve):
    loads = parameters['loads']
    count = len(loads)
    path_r = np.array([row['path_resistance_ohm'] for row in loads])
    path_l = np.array([row['path_inductance_H'] for row in loads])
    esr = np.array([row['esr_ohm'] for row in loads])
    capacitance = np.array([row['capacitance_F'] for row in loads])
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
        inverse_c = 1 / capacitance
        inductance = np.diag(path_l) + parameters['source_inductance_H'] * np.ones((count, count))
        resistance = np.diag(path_r + esr) + parameters['source_resistance_ohm'] * np.ones((count, count))
    if not all(np.isfinite(value).all() for value in (inverse_c, inductance, resistance)):
        raise TransientError('Explicit R/L/C parameters exceed a finite numerical range.')
    zero_l = np.flatnonzero(path_l == 0)
    if parameters['source_inductance_H'] > 0:
        null_l = _contrasts(np, zero_l, count)
    else:
        null_l = np.eye(count)[:, zero_l]
    zero_both = np.flatnonzero((path_l == 0) & (path_r == 0) & (esr == 0))
    null_both = _contrasts(np, zero_both, count)
    projection = None
    charge_projection = None
    if null_l.shape[1]:
        reduced = null_l.T @ resistance @ null_l
        if null_both.shape[1]:
            coordinates = null_l.T @ null_both
            # This term only fixes the ideal zero-R/L current-split gauge; it
            # is not a physical resistor. Scale it by the unreduced physical
            # resistance. The reduced matrix can be identically zero, so its
            # roundoff (or a tiny absolute floor) would amplify projected RHS
            # roundoff and destroy stored magnetic current before the charge
            # constraint below removes the arbitrary current split.
            weight = float(np.max(np.diag(resistance)))
            reduced = reduced + weight * coordinates @ coordinates.T
            charge_projection = _factor(np, cho_factor,
                                        null_both.T @ (inverse_c[:, None] * null_both))
        projection = _factor(np, cho_factor, reduced)
    return dict(path_r=path_r, path_l=path_l, esr=esr, capacitance=capacitance,
                inverse_c=inverse_c, inductance=inductance, resistance=resistance,
                null_l=null_l, null_both=null_both, projection=projection,
                charge_projection=charge_projection)


def _event_current(parameters, model, current, capacitor, demand, np, cho_solve):
    """Change only algebraic currents; preserve capacitor and magnetic state."""
    null_l = model['null_l']
    if not null_l.shape[1]:
        return current.copy()
    null_both = model['null_both']
    right = (parameters['source_voltage_V'] + model['esr'] * demand - capacitor
             - model['resistance'] @ current)
    # Zero R/L loops between parallel capacitors impose equal voltage, not an
    # arbitrary current split. Differentiate that constraint to split current
    # according to their explicit capacitances.
    if null_both.shape[1]:
        right = right - null_both @ (null_both.T @ right)
    updated = current + null_l @ _solve(np, cho_solve, model['projection'], null_l.T @ right)
    if null_both.shape[1]:
        right = null_both.T @ (model['inverse_c'] * (demand - updated))
        updated = updated + null_both @ _solve(np, cho_solve, model['charge_projection'], right)
    return updated


def _quantities(parameters, model, current, capacitor, demand, np):
    source_current = float(np.sum(current))
    voltage = capacitor + model['esr'] * (current - demand)
    source_voltage = parameters['source_voltage_V'] - parameters['source_resistance_ohm'] * source_current
    source_l = parameters['source_inductance_H']
    if source_l:
        forcing = (parameters['source_voltage_V'] + model['esr'] * demand - capacitor
                   - model['resistance'] @ current)
        zero = model['path_l'] == 0
        if zero.any():
            inductive_drop = float(np.mean(forcing[zero]))
        else:
            smallest = float(model['path_l'].min())
            weights = smallest / model['path_l']
            parallel_l = smallest / float(weights.sum())
            inductive_drop = float(np.dot(weights, forcing) / weights.sum()) * source_l / (source_l + parallel_l)
        source_voltage -= inductive_drop
    path_loss = model['path_r'] * current ** 2
    esr_loss = model['esr'] * (current - demand) ** 2
    source_loss = float(parameters['source_resistance_ohm'] * np.square(np.float64(source_current)))
    stored = float(.5 * current @ model['inductance'] @ current +
                   .5 * np.dot(model['capacitance'], capacitor ** 2))
    return dict(current=current.copy(), capacitor=capacitor.copy(), demand=demand.copy(),
                voltage=voltage, source_current=source_current, source_voltage=source_voltage,
                path_loss=path_loss, esr_loss=esr_loss, source_loss=source_loss,
                loss=float(source_loss + path_loss.sum() + esr_loss.sum()), stored=stored,
                source_power=parameters['source_voltage_V'] * source_current,
                load_power=voltage * demand)


def _advance_state(parameters, model, current, capacitor, demand, step, cache,
                   np, cho_factor, cho_solve):
    """One BE state update and its physical/numerical energy ledger."""
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
        if step not in cache:
            matrix = model['inductance'] / step + model['resistance'] + np.diag(step * model['inverse_c'])
            cache[step] = _factor(np, cho_factor, matrix)
            if len(cache) > 256:
                cache.pop(next(iter(cache)))
        right = (model['inductance'] @ current / step + parameters['source_voltage_V']
                 + model['esr'] * demand - capacitor + step * model['inverse_c'] * demand)
        updated_current = _solve(np, cho_solve, cache[step], right)
        updated_capacitor = capacitor + step * model['inverse_c'] * (updated_current - demand)
    quantities = _quantities(parameters, model, updated_current, updated_capacitor, demand, np)
    delta_i = updated_current - current; delta_v = updated_capacitor - capacitor
    delta_energy = float(.5 * delta_i @ model['inductance'] @ (updated_current + current) +
                         .5 * np.dot(model['capacitance'] * delta_v, updated_capacitor + capacitor))
    damping = float(.5 * delta_i @ model['inductance'] @ delta_i +
                    .5 * np.dot(model['capacitance'], delta_v ** 2))
    supplied = step * quantities['source_power']; load_energy = step * float(quantities['load_power'].sum())
    loss_energy = step * quantities['loss']
    residual = delta_energy - supplied + load_energy + loss_energy + damping
    charge_residual = model['capacitance'] * delta_v - step * (updated_current - demand)
    kvl_residual = (model['inductance'] @ delta_i / step + model['resistance'] @ updated_current + updated_capacitor
                    - parameters['source_voltage_V'] - model['esr'] * demand)
    ledger = dict(source_energy_J=supplied, load_energy_J=load_energy,
                  resistive_loss_energy_J=loss_energy, backward_euler_numerical_dissipation_J=damping,
                  energy_residual_J=residual, delta_stored_energy_J=delta_energy,
                  source_loss_energy_J=step * quantities['source_loss'],
                  path_loss_energy_J=(step * quantities['path_loss']).tolist(),
                  esr_loss_energy_J=(step * quantities['esr_loss']).tolist(),
                  max_charge_residual_C=float(np.max(np.abs(charge_residual))),
                  max_kvl_residual_V=float(np.max(np.abs(kvl_residual))),
                  energy_scale=abs(delta_energy)+abs(supplied)+abs(load_energy)+abs(loss_energy)+damping,
                  charge_scale=float(np.sum(np.abs(model['capacitance'] * delta_v) + step * (np.abs(updated_current)+np.abs(demand)))),
                  charge_error=float(np.sum(np.abs(charge_residual))))
    if not all(np.isfinite(value).all() for value in (*quantities.values(), *ledger.values())):
        raise TransientError('Transient state/energy exceeded a finite numerical range.')
    return updated_current, updated_capacitor, quantities, ledger


class RailStateStepper:
    """Persistent rail state with fixed L/C and explicit resistance overrides.

    State dictionaries contain independent JSON-safe current_A,
    capacitor_voltage_V and requested_current_A arrays. Rebuilding this stepper
    changes resistances, not its supplied state; project_state changes only
    zero-inductance algebraic currents. advance never performs DC initialization.
    """

    def __init__(self, request, resistances=None):
        self.parameters = _request(request)
        try:
            import numpy as np
            from scipy.linalg import cho_factor, cho_solve
        except ImportError as exc:
            raise TransientError('Quick PI transients require NumPy and SciPy.') from exc
        self.np, self.cho_factor, self.cho_solve = np, cho_factor, cho_solve
        if resistances is not None:
            if not isinstance(resistances, dict):
                raise TransientError('Resistance overrides must be an element-id object.')
            allowed = {'source', *('path:'+row['id'] for row in self.parameters['loads']),
                       *('esr:'+row['id'] for row in self.parameters['loads'])}
            if set(resistances) - allowed:
                raise TransientError('Unknown resistance override identity.')
            for element, value in resistances.items():
                value = _number(value, element+' resistance', positive=element == 'source', nonnegative=True)
                if element == 'source':
                    self.parameters['source_resistance_ohm'] = value
                else:
                    kind, identifier = element.split(':', 1)
                    row = next(row for row in self.parameters['loads'] if row['id'] == identifier)
                    row['path_resistance_ohm' if kind == 'path' else 'esr_ohm'] = value
        self.model = _model(self.parameters, np, cho_factor, cho_solve)
        identity = [self.parameters['source_voltage_V'], self.parameters['source_inductance_H'],
                    [[row['id'],row['path_inductance_H'],row['capacitance_F']] for row in self.parameters['loads']]]
        self.storage_signature = hashlib.sha256(json.dumps(identity,separators=(',',':')).encode('utf-8')).hexdigest()
        self.resistances = {'source':self.parameters['source_resistance_ohm']}
        for row in self.parameters['loads']:
            self.resistances['path:'+row['id']] = row['path_resistance_ohm']
            self.resistances['esr:'+row['id']] = row['esr_ohm']
        self.cache = {}

    def _state(self, state):
        keys = ('current_A', 'capacitor_voltage_V', 'requested_current_A')
        if not isinstance(state, dict) or set(state) != {*keys,'storage_signature'}:
            raise TransientError('Rail state requires current, capacitor voltage and requested current arrays.')
        if state['storage_signature'] != self.storage_signature:
            raise TransientError('Rail state belongs to different load identities, voltage source or L/C storage parameters.')
        values = []
        for key in keys:
            raw = state[key]
            if not isinstance(raw, list) or len(raw) != len(self.parameters['loads']):
                raise TransientError('Rail state does not match the explicit load count.')
            values.append(self.np.array([_number(value, key, nonnegative=key == 'requested_current_A') for value in raw]))
        null_both = self.model['null_both']
        if null_both.shape[1] and self.np.max(self.np.abs(null_both.T @ values[1])) > 1e-12*max(
                abs(self.parameters['source_voltage_V']),float(self.np.max(self.np.abs(values[1])))):
            raise TransientError('Parallel ideal capacitors require compatible capacitor voltages; impulse charge sharing is unsupported.')
        return values

    def _encoded_state(self,current, capacitor, demand):
        return dict(current_A=current.tolist(), capacitor_voltage_V=capacitor.tolist(),
                    requested_current_A=demand.tolist(),storage_signature=self.storage_signature)

    def initial_state(self):
        demand = self.np.array([row['initial_current_A'] for row in self.parameters['loads']])
        capacitor = (self.parameters['source_voltage_V'] - self.parameters['source_resistance_ohm'] * demand.sum()
                     - self.model['path_r'] * demand)
        return self._encoded_state(demand, capacitor, demand)

    def project_state(self, state, requested_current_A=None):
        current, capacitor, demand = self._state(state)
        if requested_current_A is not None:
            proposed = {**state, 'requested_current_A': requested_current_A}
            demand = self._state(proposed)[2]
        current = _event_current(self.parameters, self.model, current, capacitor, demand, self.np, self.cho_solve)
        return self._encoded_state(current, capacitor, demand)

    def quantities(self, state):
        current, capacitor, demand = self._state(state)
        result = _quantities(self.parameters, self.model, current, capacitor, demand, self.np)
        if not all(self.np.isfinite(value).all() for value in result.values()):
            raise TransientError('Persistent rail output exceeded a finite numerical range.')
        return result

    def advance(self, state, step_s):
        step = _number(step_s, 'Electrical integration step', positive=True)
        current, capacitor, demand = self._state(state)
        current, capacitor, quantities, ledger = _advance_state(
            self.parameters, self.model, current, capacitor, demand, step, self.cache,
            self.np, self.cho_factor, self.cho_solve)
        return self._encoded_state(current, capacitor, demand), quantities, ledger


def _integrate(parameters, model, timeline, events, cancel, np, cho_factor, cho_solve):
    demand = np.array([row['initial_current_A'] for row in parameters['loads']])
    current = demand.copy()
    capacitor = (parameters['source_voltage_V'] - parameters['source_resistance_ohm'] * demand.sum()
                 - model['path_r'] * demand)
    times = []; phases = []; samples = []
    totals = dict(source_energy_J=0., load_energy_J=0., resistive_loss_energy_J=0.,
                  backward_euler_numerical_dissipation_J=0., energy_residual_J=0.,
                  max_charge_residual_C=0., max_kvl_residual_V=0.)
    energy_scale = charge_scale = charge_error = absolute_energy_error = 0.
    cache = {}

    def cancelled():
        if cancel and cancel():
            raise InterruptedError('Quick PI transient cancelled. No board files were changed.')

    def record(time, phase):
        quantities = _quantities(parameters, model, current, capacitor, demand, np)
        if not all(np.isfinite(value).all() for value in quantities.values()):
            raise TransientError('Transient output exceeded a finite numerical range.')
        times.append(time); phases.append(phase); samples.append(quantities)

    def event(time):
        nonlocal demand, current
        for index in events[time]:
            demand[index] = parameters['loads'][index]['step_current_A']
        current = _event_current(parameters, model, current, capacitor, demand, np, cho_solve)
        record(time, 'step_after')

    cancelled();record(0., 'initial')
    initial = samples[0]
    if 0. in events:
        event(0.)
    for previous, time in zip(timeline, timeline[1:]):
        cancelled()
        step = time - previous
        if step <= 0:
            raise TransientError('Event times cannot be distinguished at floating-point resolution.')
        current, capacitor, _, ledger = _advance_state(parameters, model, current, capacitor, demand,
                                                      step, cache, np, cho_factor, cho_solve)
        absolute_energy_error += abs(ledger['energy_residual_J'])
        for key in ('source_energy_J', 'load_energy_J', 'resistive_loss_energy_J',
                    'backward_euler_numerical_dissipation_J', 'energy_residual_J'):
            totals[key] += ledger[key]
        for key in ('max_charge_residual_C', 'max_kvl_residual_V'):
            totals[key] = max(totals[key], ledger[key])
        energy_scale += ledger['energy_scale']; charge_scale += ledger['charge_scale']
        charge_error += ledger['charge_error']
        record(time, 'step_before' if time in events else 'sample')
        if time in events:
            event(time)
    totals.update(energy_relative_error=absolute_energy_error / max(energy_scale, 1e-300),
                  charge_relative_error=charge_error / max(charge_scale, 1e-300),
                  initial_stored_energy_J=initial['stored'], final_stored_energy_J=samples[-1]['stored'],
                  intervals=len(timeline)-1, samples=len(samples), max_interval_s=max(
                      right-left for left, right in zip(timeline, timeline[1:])))
    if not all(math.isfinite(value) for value in totals.values()):
        raise TransientError('Transient conservation checks exceeded a finite numerical range.')
    totals['balance_status'] = 'PASSED' if max(totals['energy_relative_error'], totals['charge_relative_error']) <= 1e-8 else 'FAILED'
    return times, phases, samples, totals


def _voltage_violations(values, times, row, source_voltage):
    minimum = min(values);maximum = max(values)
    tolerance = 1e-12 * max(abs(source_voltage), abs(minimum), abs(maximum),
                             abs(row.get('min_voltage_V') or 0), abs(row.get('max_voltage_V') or 0))
    violations = []
    for kind, observed, limit, comparison in (
            ('negative_voltage', minimum, 0., minimum < -tolerance),
            ('minimum_voltage', minimum, row['min_voltage_V'], row['min_voltage_V'] is not None and minimum < row['min_voltage_V'] - tolerance),
            ('maximum_voltage', maximum, row['max_voltage_V'], row['max_voltage_V'] is not None and maximum > row['max_voltage_V'] + tolerance)):
        if comparison:
            violations.append(dict(kind=kind, limit_V=limit, observed_V=observed,
                                   time_s=times[values.index(observed)]))
    return violations


def solve_transient(request, cancel=None):
    """Return JSON-safe lumped transients plus conservation/refinement evidence.

    Initialization is the pre-step DC steady state, not an arbitrary charged
    capacitor. Events include before/after samples with duplicate timestamps.
    Source current limits are diagnostic budgets only: the ideal-source trace
    is never clipped or described as a CV/CC-regulated simulation.
    """
    if cancel and cancel():
        raise InterruptedError('Quick PI transient cancelled before initialization.')
    parameters = _request(request)
    try:
        import numpy as np
        from scipy.linalg import cho_factor, cho_solve
    except ImportError as exc:
        raise TransientError('Quick PI transients require NumPy and SciPy.') from exc
    events = {}
    for index, row in enumerate(parameters['loads']):
        events.setdefault(row['step_time_s'], []).append(index)
    coarse = _timeline(parameters['duration_s'], parameters['step_s'], set(events))
    fine = _timeline(parameters['duration_s'], parameters['step_s'] / 2, set(events))
    samples_bound = len(coarse) + len(events)
    if samples_bound * (9 * len(parameters['loads']) + 8) > MAX_TRACE_VALUES:
        raise TransientError(f'Transient output exceeds {MAX_TRACE_VALUES:,} scalar trace values; reduce duration/load count or increase step.')
    if len(coarse)-1 > MAX_COARSE_INTERVALS + MAX_LOADS or len(fine)-1 > 2 * MAX_COARSE_INTERVALS + MAX_LOADS:
        raise TransientError('Transient timeline exceeds its bounded interval count.')
    model = _model(parameters, np, cho_factor, cho_solve)
    times, phases, samples, checks = _integrate(parameters, model, coarse, events, cancel, np, cho_factor, cho_solve)
    fine_times, fine_phases, fine_samples, fine_checks = _integrate(parameters, model, fine, events, cancel, np, cho_factor, cho_solve)
    matched = {(time, phase): sample for time, phase, sample in zip(fine_times, fine_phases, fine_samples)}
    pairs = [(sample, matched[(time, phase)]) for time, phase, sample in zip(times, phases, samples)]
    differences = [float(max(abs(a['voltage'][index]-b['voltage'][index]) for a,b in pairs))
                   for index in range(len(parameters['loads']))]
    refinement = dict(status='CHECKED_NOT_CERTIFIED', method='fixed_model_half_step',
                      coarse_step_s=parameters['step_s'], fine_step_s=parameters['step_s']/2,
                      comparison_samples=len(pairs), fine_balance_status=fine_checks['balance_status'],
                      max_load_voltage_difference_V=max(differences),
                      max_source_current_difference_A=max(abs(a['source_current']-b['source_current']) for a,b in pairs),
                      max_capacitor_voltage_difference_V=max(float(np.max(np.abs(a['capacitor']-b['capacitor']))) for a,b in pairs),
                      per_load=[dict(id=row['id'], max_voltage_difference_V=differences[index],
                                     minimum_voltage_difference_V=abs(min(sample['voltage'][index] for sample in samples)-min(sample['voltage'][index] for sample in fine_samples)),
                                     maximum_voltage_difference_V=abs(max(sample['voltage'][index] for sample in samples)-max(sample['voltage'][index] for sample in fine_samples)))
                                for index,row in enumerate(parameters['loads'])],
                      notice='One step halving is evidence of time-step sensitivity, not an error bound or convergence certification. Resolve load edges and ringing with further smaller steps.')
    checks.update(method='backward_euler', time_refinement=refinement,
                  energy_notice='Backward Euler adds the reported nonnegative numerical dissipation; it is not physical copper/ESR heat.')
    loads = []
    all_violations = []
    for index, row in enumerate(parameters['loads']):
        voltage = [float(sample['voltage'][index]) for sample in samples]
        violations = _voltage_violations(voltage, times, row, parameters['source_voltage_V'])
        loads.append(dict(id=row['id'], label=row['label'],
                          **({'terminal':row['terminal']} if 'terminal' in row else {}),
                          voltage_V=voltage, capacitor_voltage_V=[float(sample['capacitor'][index]) for sample in samples],
                          current_A=[float(sample['current'][index]) for sample in samples],
                          requested_current_A=[float(sample['demand'][index]) for sample in samples],
                          capacitor_current_A=[float(sample['current'][index]-sample['demand'][index]) for sample in samples],
                          load_power_W=[float(sample['load_power'][index]) for sample in samples],
                          path_loss_W=[float(sample['path_loss'][index]) for sample in samples],
                          esr_loss_W=[float(sample['esr_loss'][index]) for sample in samples],
                          min_voltage_V=min(voltage), max_voltage_V=max(voltage),
                          limits={key:row[key] for key in ('min_voltage_V','max_voltage_V')},
                          within_voltage_limits=not violations, violations=violations))
        all_violations.extend(dict(load_id=row['id'], **item) for item in violations)
    source_current = [sample['source_current'] for sample in samples]
    source_voltage = [sample['source_voltage'] for sample in samples]
    limit = parameters['source_current_limit_A']
    peak_current = max(source_current)
    current_tolerance = 1e-12 * max(abs(peak_current), abs(limit or 0))
    exceeded = limit is not None and peak_current > limit + current_tolerance
    if exceeded:
        all_violations.append(dict(kind='source_current_budget', limit_A=limit,
                                   observed_A=peak_current, time_s=times[source_current.index(peak_current)]))
    if min(source_voltage) < -1e-12 * max(parameters['source_voltage_V'], max(abs(value) for value in source_voltage)):
        all_violations.append(dict(kind='negative_source_bus_voltage', limit_V=0., observed_V=min(source_voltage),
                                   time_s=times[source_voltage.index(min(source_voltage))]))
    initial = samples[0]
    # Initial feasibility is assessed separately from a step scheduled at t=0.
    initial_rows = [dict(id=row['id'], current_A=row['initial_current_A'],
                         voltage_V=float(initial['voltage'][index]), capacitor_voltage_V=float(initial['capacitor'][index]),
                         violations=_voltage_violations([float(initial['voltage'][index])], [0.], row, parameters['source_voltage_V']))
                    for index,row in enumerate(parameters['loads'])]
    initial_valid = all(not row['violations'] for row in initial_rows) and initial['source_voltage'] >= 0
    if limit is not None and initial['source_current'] > limit + current_tolerance:
        initial_valid = False
    feasible = not all_violations
    notice = ('Explicit lumped R/L/C rail model with pre-step DC initialization. Constant-current demands continue below zero voltage; there is no UVLO, converter control or spatial transient copper field. '
              'Source current limits are diagnostic budgets only: currents are not capped and CV/CC regulation is not simulated. '
              'The ideal voltage source can absorb reverse current; real-source sink capability must be checked. '
              'Backward Euler damps ringing; review the half-step evidence and refine before relying on peaks.')
    if not initial_valid:
        notice += ' The pre-step DC state already violates voltage/current constraints and is a requested-load diagnostic, not a feasible initialized rail.'
    return dict(schema=SCHEMA, model='lumped_multisink_rlc', notice=notice, parameters=parameters,
                source_set_voltage_V=parameters['source_voltage_V'], times_s=times, sample_phase=phases,
                source_current_A=source_current, source_voltage_V=source_voltage,
                source_power_W=[sample['source_power'] for sample in samples],
                source_resistive_loss_W=[sample['source_loss'] for sample in samples],
                total_resistive_loss_W=[sample['loss'] for sample in samples],
                stored_energy_J=[sample['stored'] for sample in samples], loads=loads, checks=checks,
                initialization=dict(method='pre_step_dc_steady_state', feasible=initial_valid,
                                    source_current_A=initial['source_current'], source_voltage_V=initial['source_voltage'],
                                    loads=initial_rows),
                feasibility=dict(feasible=feasible, operating_point_valid=feasible,
                                 status='FEASIBLE_REQUESTED_MODEL' if feasible else 'REQUESTED_LOAD_DIAGNOSTIC',
                                 source_current_limit_mode='diagnostic_only', source_current_limit_A=limit,
                                 source_current_limit_exceeded=exceeded, peak_source_current_A=peak_current,
                                 source_current_headroom_A=None if limit is None else limit-peak_current,
                                 violations=all_violations))
