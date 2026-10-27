"""Exact fixed-temperature current rescaling of a solved 2.5D PI field.

Only a common positive multiplier on every prescribed sink current is allowed.
The mesh, conductivity, and electrode topology stay fixed; no matrix assembly,
factorization, or nonlinear operating-point inference occurs on update.
"""
from __future__ import annotations

import copy
import math

import numpy as np


class LiveCurrentError(ValueError):
    """A solved bundle cannot safely support proportional live-current changes."""


_REQUIRED = {
    'potential_V', 'cell_J_A_mm2', 'cell_sheet_current_A_mm', 'cell_power_W',
    'cell_thermal', 'vias', 'sinks', 'analytics', 'source_voltage_V',
    'source_current_A', 'sink_current_A', 'total_sink_current_A',
    'voltage_drop_V', 'total_power_W', 'conductor_power_W',
    'component_power_W', 'feasibility', 'thermal_assumptions',
    'planar_power_W', 'via_power_W', 'max_current_density_A_mm2',
    'current_balance_error_A', 'max_nodal_residual_A',
}


def live_current_eligibility(bundle):
    """Return ``(eligible, reason)`` for a solved proportional-current bundle."""
    if not isinstance(bundle, dict):
        return False, 'A solved Quick PI bundle is required.'
    request, result, mesh = (bundle.get(name) for name in ('request', 'result', 'mesh'))
    if not all(isinstance(value, dict) for value in (request, result, mesh)):
        return False, 'A solved bundle with request, mesh and result is required.'
    if request.get('action') != 'solve' or request.get('model_dimension', '2.5d') != '2.5d':
        return False, 'Live current requires a solved fixed-temperature 2.5D case.'
    if result.get('model') != '2.5D linear triangular DC conductivity FEM':
        return False, 'Live current requires the 2.5D linear copper solver result.'
    from .constant_power import requested as power_requested
    if power_requested(request) or result.get('operating_mode') == 'constant_power_loads':
        return False, 'Constant-power loads require a new nonlinear operating-point solve.'
    if request.get('load_resistance_ohm') is not None or request.get('sweep') or bundle.get('sweep'):
        return False, 'Resistive operating points and current sweeps require their own solve workflow.'
    if request.get('series') or mesh.get('lumped_branches') or result.get('components'):
        return False, 'Series branches and component paths are unsupported for live current.'
    if request.get('package_conduction') or mesh.get('package_contacts') or result.get('package_contacts'):
        return False, 'Package-contact paths are unsupported for live current.'
    if result.get('contains_forward_drop') or result.get('component_power_W') or result.get('package_power_W'):
        return False, 'Forward-drop and non-copper loss models are unsupported for live current.'
    if any(name in bundle for name in ('return_path', 'power_loop', 'electrothermal', 'transient', 'coupled')) or any(
            request.get(name) for name in ('return_path', 'power_loop', 'electrothermal', 'transient', 'shared_return')):
        return False, 'Return-path, power-loop and electrothermal studies are unsupported for live current.'
    missing = _REQUIRED - result.keys()
    if missing:
        return False, 'Solved result is missing required fields: ' + ', '.join(sorted(missing))
    sinks = result['sinks']
    if not isinstance(sinks, list) or not sinks:
        return False, 'At least one prescribed current sink is required.'
    try:
        currents = [float(row['current_A']) for row in sinks]
        base = math.fsum(currents)
        recorded = float(result['total_sink_current_A'])
    except (TypeError, KeyError, ValueError, OverflowError):
        return False, 'Solved sink currents must be finite positive numbers.'
    if any(not math.isfinite(value) or value <= 0 for value in currents) or not math.isfinite(base):
        return False, 'Solved sink currents must be finite positive numbers.'
    if not math.isclose(base, recorded, rel_tol=1e-10, abs_tol=1e-12):
        return False, 'Solved sink currents do not match the recorded total.'
    try:
        request_voltage = float(request.get('source_voltage', 1.))
        solved_voltage = float(result['source_voltage_V'])
    except (TypeError, KeyError, ValueError, OverflowError):
        return False, 'Source voltage is missing or invalid.'
    if not math.isfinite(request_voltage) or not math.isclose(request_voltage, solved_voltage,
                                                               rel_tol=1e-10, abs_tol=1e-12):
        return False, 'Request source voltage does not match the solved field.'
    request_sinks = request.get('sinks')
    if request_sinks is not None:
        if not isinstance(request_sinks, list) or len(request_sinks) != len(sinks):
            return False, 'Request sink identities do not match the solved loads.'
        try:
            specified = [float(row['current_A']) for row in request_sinks]
        except (TypeError, KeyError, ValueError, OverflowError):
            return False, 'Request sink currents are missing or invalid.'
        if any(not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-12)
               for a, b in zip(specified, currents)):
            return False, 'Request sink currents do not match the solved loads.'
    else:
        try:
            legacy = float(request.get('sink_current', 1.))
        except (TypeError, ValueError, OverflowError):
            return False, 'Legacy request current is missing or invalid.'
        if len(sinks) != 1 or not math.isclose(legacy, base, rel_tol=1e-10, abs_tol=1e-12):
            return False, 'Legacy request current does not match the single solved sink.'
    if not all(len(result[field]) == len(result['cell_power_W'])
               for field in ('cell_J_A_mm2', 'cell_sheet_current_A_mm', 'cell_thermal')):
        return False, 'Solved cell field lengths disagree.'
    if any((row is None) != (result['cell_power_W'][index] is None)
           for field in ('cell_J_A_mm2', 'cell_sheet_current_A_mm')
           for index, row in enumerate(result[field])):
        return False, 'Solved cell activity masks disagree.'
    if not isinstance(result['feasibility'], dict) or 'source_current_limit_A' not in result['feasibility']:
        return False, 'Solved feasibility limits are missing.'
    request_limit = request.get('source_current_limit')
    solved_limit = result['feasibility']['source_current_limit_A']
    if (request_limit is None) != (solved_limit is None):
        return False, 'Request source-current limit does not match the solved result.'
    if request_limit is not None:
        try:
            matches = math.isclose(float(request_limit), float(solved_limit), rel_tol=1e-10, abs_tol=1e-12)
        except (TypeError, ValueError, OverflowError):
            matches = False
        if not matches:
            return False, 'Request source-current limit does not match the solved result.'
    if not isinstance(result['thermal_assumptions'], dict) or 'ambient_c' not in result['thermal_assumptions']:
        return False, 'Solved thermal assumptions are missing.'
    analytics = result['analytics']
    if (not isinstance(analytics, dict) or
            any(name not in analytics for name in ('layers', 'losses', 'hotspots_by_current_density', 'hotspots_by_heating_density')) or
            any(name not in analytics['losses'] for name in ('planar_W', 'via_W', 'component_W', 'package_W'))):
        return False, 'Solved layer and loss analytics are missing.'
    return True, ''


def _thermal(base, factor_sq, ambient):
    row = dict(base)
    if row.get('status') == 'disconnected':
        return row
    time_to_limit = base.get('time_to_limit_s')
    ratio = base.get('energy_ratio')
    temperature = base.get('adiabatic_temperature_c')
    row['time_to_limit_s'] = None if time_to_limit is None else time_to_limit / factor_sq
    row['energy_ratio'] = None if ratio is None else ratio * factor_sq
    row['adiabatic_temperature_c'] = None if temperature is None else ambient + (temperature - ambient) * factor_sq
    row['status'] = ('pulse_duration_required' if row['energy_ratio'] is None else
                     'temperature_limit_exceeded_adiabatic' if row['energy_ratio'] >= 1 else
                     'below_adiabatic_limit')
    return row


class LiveCurrentModel:
    """A reusable, immutable solved basis for proportional sink-current updates.

    Returned views share static geometry, mesh and material metadata with the
    private basis. Callers may edit the returned request and computed result
    fields, but must treat that static topology and metadata as read-only.
    """

    def __init__(self, bundle):
        eligible, reason = live_current_eligibility(bundle)
        if not eligible:
            raise LiveCurrentError(reason)
        self._base = copy.deepcopy(bundle)
        result = self._base['result']
        self.base_current_A = float(result['total_sink_current_A'])
        self._source_voltage = float(result['source_voltage_V'])
        self._potential_mask = [value is None for value in result['potential_V']]
        self._potential_offset = np.asarray([0. if value is None else value - self._source_voltage
                                             for value in result['potential_V']], dtype=float)
        self._cell_mask = [value is None for value in result['cell_power_W']]
        self._density = np.asarray([value if value is not None else (0., 0.)
                                    for value in result['cell_J_A_mm2']], dtype=float)
        self._sheet = np.asarray([value if value is not None else (0., 0.)
                                  for value in result['cell_sheet_current_A_mm']], dtype=float)
        self._power = np.asarray([0. if value is None else value
                                  for value in result['cell_power_W']], dtype=float)
        self._ambient = float(result['thermal_assumptions']['ambient_c'])

    def update(self, total_current_A):
        """Return a new solved-bundle view at a positive proportional total load."""
        if isinstance(total_current_A, bool):
            raise LiveCurrentError('Live current must be a finite positive number of amperes.')
        try:
            total = float(total_current_A)
        except (TypeError, ValueError, OverflowError) as exc:
            raise LiveCurrentError('Live current must be a finite positive number of amperes.') from exc
        if not math.isfinite(total) or total <= 0:
            raise LiveCurrentError('Live current must be a finite positive number of amperes.')
        factor = total / self.base_current_A
        square = factor * factor
        if not math.isfinite(square) or square <= 0:
            raise LiveCurrentError('Live current ratio is outside the supported numeric range.')

        base = self._base['result']
        # The full result includes one geometry/thermal dictionary per cell.
        # Copy only the structures whose values change with current; copying
        # unchanged topology on each slider event dominates the update time.
        result = dict(base)
        result['vias'] = [dict(row) for row in base['vias']]
        result['sinks'] = [dict(row) for row in base['sinks']]
        result['feasibility'] = dict(base['feasibility'])
        baseline_analysis = base['analytics']
        result['analytics'] = {
            **baseline_analysis,
            'layers': [dict(row) for row in baseline_analysis['layers']],
            'losses': dict(baseline_analysis['losses']),
            'hotspots_by_current_density': [dict(row) for row in baseline_analysis['hotspots_by_current_density']],
            'hotspots_by_heating_density': [dict(row) for row in baseline_analysis['hotspots_by_heating_density']],
        }
        output = dict(self._base)
        output['result'] = result
        request = copy.deepcopy(self._base['request'])
        output['request'] = request

        if request.get('sinks') is not None:
            for row, original in zip(request['sinks'], self._base['request']['sinks']):
                row['current_A'] = original['current_A'] * factor
        else:
            request['sink_current'] = total
        if 'terminal_units' in output:
            output['terminal_units'] = copy.deepcopy(self._base['terminal_units'])
            for row in output['terminal_units'].get('loads', []):
                row['current_A'] *= factor

        potential = (self._source_voltage + factor * self._potential_offset).tolist()
        # Numeric tuples serialize as JSON arrays and become untracked by the
        # cyclic collector. Tens of thousands of nested lists otherwise cause
        # long full-heap collection pauses during repeated interactive changes.
        density_values = (factor * self._density).ravel().tolist()
        density = list(zip(density_values[::2], density_values[1::2]))
        sheet_values = (factor * self._sheet).ravel().tolist()
        sheet = list(zip(sheet_values[::2], sheet_values[1::2]))
        power = (square * self._power).tolist()
        for index, inactive in enumerate(self._potential_mask):
            if inactive: potential[index] = None
        for index, inactive in enumerate(self._cell_mask):
            if inactive: density[index] = sheet[index] = power[index] = None
        result['potential_V'] = potential
        result['cell_J_A_mm2'] = density
        result['cell_sheet_current_A_mm'] = sheet
        result['cell_power_W'] = power
        result['cell_thermal'] = [_thermal(row, square, self._ambient) for row in base['cell_thermal']]
        for row, original in zip(result['vias'], base['vias']):
            for key in ('current_A', 'current_density_A_mm2'):
                if original[key] is not None: row[key] = original[key] * factor
            if original['power_W'] is not None: row['power_W'] = original['power_W'] * square
            row['thermal'] = _thermal(original['thermal'], square, self._ambient)

        result['source_current_A'] = base['source_current_A'] * factor
        result['sink_current_A'] = total
        result['total_sink_current_A'] = total
        for row, original in zip(result['sinks'], base['sinks']):
            row['current_A'] = original['current_A'] * factor
            row['voltage_drop_V'] = original['voltage_drop_V'] * factor
            row['voltage_V'] = self._source_voltage - row['voltage_drop_V']
            maximum = row['max_voltage_V']
            min_tol = 1e-12 * max(abs(row['voltage_V']), abs(row['min_voltage_V']))
            max_tol = None if maximum is None else 1e-12 * max(abs(row['voltage_V']), abs(maximum))
            row['voltage_limit_tolerances_V'] = {'minimum': min_tol, 'maximum': max_tol}
            row['within_voltage_limits'] = (row['voltage_V'] >= row['min_voltage_V'] - min_tol and
                                            (maximum is None or row['voltage_V'] <= maximum + max_tol))
        drop = max(row['voltage_drop_V'] for row in result['sinks'])
        result['voltage_drop_V'] = drop
        result['sink_voltage_V'] = self._source_voltage - drop
        result['negative_sink_voltage'] = result['sink_voltage_V'] < 0
        result['drop_over_current_ohm'] = drop / total
        result['V_over_I_ohm'] = self._source_voltage / total
        result['conductor_power_W'] = base['conductor_power_W'] * square
        result['total_power_W'] = base['total_power_W'] * square
        result['planar_power_W'] = base['planar_power_W'] * square
        result['via_power_W'] = base['via_power_W'] * square
        result['max_current_density_A_mm2'] = base['max_current_density_A_mm2'] * factor
        result['current_balance_error_A'] = base['current_balance_error_A'] * factor
        result['max_nodal_residual_A'] = base['max_nodal_residual_A'] * factor
        terminal_loss = math.fsum(row['current_A'] * row['voltage_drop_V'] for row in result['sinks'])
        result['energy_relative_error'] = abs(result['total_power_W'] - terminal_loss) / max(abs(terminal_loss), 1e-30)

        feasibility = result['feasibility']
        limit = feasibility['source_current_limit_A']
        over = limit is not None and total > limit and not math.isclose(total, limit, rel_tol=1e-12, abs_tol=0.)
        violations = []
        if over:
            violations.append(f'Required source current {total:.9g} A exceeds its {limit:.9g} A limit.')
        for row in result['sinks']:
            if not row['within_voltage_limits']:
                violations.append(f"Sink {row['label']} voltage {row['voltage_V']:.9g} V is outside its specified voltage limits.")
        feasible = not violations
        feasibility.update(status='FEASIBLE' if feasible else 'INFEASIBLE', feasible=feasible,
                           source_current_headroom_A=None if limit is None else
                           (limit - total if over else max(0., limit - total)),
                           source_current_limit_exceeded=over, violations=violations,
                           operating_point_valid=feasible)

        analysis = result['analytics']
        for row, original in zip(analysis['layers'], base['analytics']['layers']):
            row['planar_power_W'] = original['planar_power_W'] * square
            if original['peak_current_density_A_mm2'] is not None:
                row['peak_current_density_A_mm2'] = original['peak_current_density_A_mm2'] * factor
        for key in ('hotspots_by_current_density', 'hotspots_by_heating_density'):
            for row, original in zip(analysis[key], base['analytics'][key]):
                row['current_density_A_mm2'] = original['current_density_A_mm2'] * factor
                row['power_W'] = original['power_W'] * square
                row['power_density_W_mm3'] = original['power_density_W_mm3'] * square
                row['thermal'] = _thermal(original['thermal'], square, self._ambient)
        losses = analysis['losses']
        for key in ('planar_W', 'via_W', 'component_W', 'package_W'):
            losses[key] = base['analytics']['losses'][key] * square
        losses['total_W'] = math.fsum(losses[key] for key in ('planar_W', 'via_W', 'component_W', 'package_W'))
        losses['accounting_error_W'] = abs(losses['total_W'] - result['total_power_W'])
        if base.get('fusing'):
            from .fusing import rescale
            result['fusing']=rescale(base['fusing'],factor)
        result['live_current'] = {'base_current_A': self.base_current_A,
                                  'scale': factor,
                                  'basis': 'proportional fixed-temperature 2.5D prescribed-current field',
                                  'notice': 'Solver refinement count describes the original factorized solve.'}
        return output
